#!/usr/bin/env python3
"""Lifecycle + stock gate for candidate parts, before any design work is spent on them.

  part_gate.py TPS61088 TPS61088-Q1 BQ25606 C316138 ... [--project DIR] [--per-board 3 | --need 50] [--region R]
  pbpaste | part_gate.py --from-text                  # pasted text, e.g. WEBENCH's TABLE VIEW: part numbers are found

Stock is looked up in the project's region from its sourcing.json (sourcing.py; found from --project, default the
current folder, up to the repository root), with --region passed explicitly to jlcimport-cli: there is no default
region, and stock in the other warehouse does not count (shown beside a short part, labelled as such). The required
stock is per-board count x boards x (1 + attrition) from sourcing.json, at least its stock policy, or --need.

For each device name it prints:
- lifecycle from the manufacturer's product page, where that can be read automatically (TI: ti.com/product/<NAME>,
  the page's status tag: ACTIVE / NRND / LAST TIME BUY / OBSOLETE / PREVIEW). An orderable number is cut back to its
  device page (TPS61089RNRR -> TPS61089; TPS7A1633QDGNRQ1 -> TPS7A16-Q1) and the page used is printed. A page found
  only by dropping something may be another device: a fixed-voltage code from the middle (TLV75518PDRVR -> TLV755P),
  everything from the first "-", "." or "/" (LP5907MFX-3.3/NOPB -> LP5907), or the automotive grade (a plain page for
  a ...Q1 orderable). It counts only when ti.com lists the orderable number under it
  (ti.com/product/TLV755P/part-details/TLV75518PDRVR answers 200); otherwise its status gets a "?" (ACTIVE? (as
  TLV755P, found only by dropping '18' ...)) and fails the gate, whatever the status (also "unknown"), until the
  device is confirmed by hand. No product page for any of those (HTTP 404) is reported as SUSPECT: treat the part as
  discontinued until the manufacturer says otherwise. Other vendors: "check by hand" (open the product page and
  record the status);
- every orderable LCSC variant of that exact device in the project's region, with stock (an LCSC C-number is looked
  up as exactly that part).
  Variants are kept apart: an automotive "-Q1" device is a different part with its own datasheet (equations, limits,
  Rds(on) can differ), so a "-Q1" query only matches orderable numbers ending in Q1, and a plain query excludes them.
Exit 1 if any part is SUSPECT/NRND/OBSOLETE/LAST TIME BUY, has an unconfirmed ("?") status, or has less stock than
--need.

Why: distributor stock is not evidence a part is still made (a discontinued part showed 7,130 units at LCSC), and a
design tool's top picks may have no stock at all. Run this on every candidate before customising a design around it,
and again right before ordering, and present every candidate to the user with its stock, region and date (the
first output line). Results are a snapshot.
"""
import argparse, http.client, os, re, sys, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sourcing  # noqa: E402

# TI device-name prefixes, only those no other maker uses with a digit after them (SN74 logic, SN65/SN75 interface,
# TXS/TXB/TXU translators, OPA, ADS, DRV, HDC, TUSB, TMUX); ISO, REF and TMP only with as many digits as TI's own
# names have, so Infineon's ISO1H811G, ADI's REF02/REF195 and TMP36 are not taken for TI parts
TI_PREFIX = (r'(?:TPSM?|LMR|LMQ|LMZ|LM|TLV|LP|BQ|UCC|LMG|CSD|TLC|TPA|TCA|INA|LMS|TPD|TS|SN|TXS|TXB|TXU|OPA|ADS|DRV|HDC|'
             r'TUSB|TMUX|ISOW?(?=\d{3})|REF(?=\d{4})|TMP(?=\d{3}))')
NAME_RE = re.compile(r'\b(%s\d[0-9A-Z]*(?:-Q1)?)\b' % TI_PREFIX)


def _fetch(url):
    """(final URL, first 400 kB of the page) for a ti.com GET; raises urllib.error.HTTPError for an error status and
    OSError / http.client.HTTPException (IncompleteRead, InvalidURL, ...) when the request itself fails"""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    r = urllib.request.urlopen(req, timeout=20)
    return r.geturl(), r.read(400000).decode('utf-8', 'replace')


def ti_lifecycle(name):
    url = 'https://www.ti.com/product/%s' % name
    try:
        html = _fetch(url)[1]
    except urllib.error.HTTPError as e:
        return ('SUSPECT (product page HTTP %d)' % e.code) if e.code == 404 else 'unknown (HTTP %d)' % e.code
    except (OSError, http.client.HTTPException) as e:      # URLError is an OSError
        return 'unknown (%s: %s)' % (type(e).__name__, e)
    m = re.search(r'<meta\s+name="status"\s+content="([^"]+)"', html, re.I)
    return m.group(1).upper() if m else 'unknown (no status tag on %s)' % url


MAX_TI_REQUESTS = 13   # ti.com requests per part at most, counted in ti_resolve only: up to 12 product pages
                       # (TLV75518PDRVR needs 11, TPS7A2033PDBVR 12; a SUSPECT part tries as many as fit), plus one
                       # part-details confirmation (ti_orderable_confirmed) when the page found may be another device
# two-digit output-voltage codes taken for one in a fixed-voltage order code: 0.8-3.6 V, 4.5 V, 5.0 V. Not 40, 60, 89
# and the like, which end ordinary device numbers (TPS62840, TPS54360, TPS61089)
VOLTAGE_CODES = {'%02d' % v for v in range(8, 37)} | {'45', '50'}
UNCONFIRMED = 'confirm the device'    # ends every unconfirmed lifecycle text (lifecycle_text); gate_flag fails on it


def _trims(name):
    """name cut back letter by letter from the end, longest first, never past its last digit (TPS61089RNRR ->
    TPS61089RNR ... TPS61089; TPS61230ADRRR -> ... TPS61230A, TPS61230): dropping a digit names another device, which
    only _without_voltage does, and says so"""
    digits = [m.end() for m in re.finditer(r'\d', name)]
    floor = digits[-1] if digits else len(name)
    return [name[:i] for i in range(len(name), floor - 1, -1)]


def _without_voltage(name):
    """[(name with a voltage code taken out of the middle, the code)]: TI's fixed-voltage order codes insert a
    two-digit code after the device name (TLV755+18+P+DRVR, TLV767+18+DRVR, TPS7A20+33+PDBVR, TLV1117LV+33+DCYR).
    Only a digit group followed by a letter, ending in a VOLTAGE_CODES code; the first digit group keeps at least three
    digits (TLV755, not TLV7) and a later one none or at least two (TPS7A20, TLV1117LV; not LMG3410R0)."""
    out = []
    for i, m in enumerate(re.finditer(r'\d+(?=[A-Z])', name)):
        run = m.group(0)
        if len(run) < 2 or run[-2:] not in VOLTAGE_CODES:
            continue
        left = len(run) - 2
        if (i == 0 and left < 3) or (i > 0 and left == 1):
            continue
        out.append((name[:m.end() - 2] + name[m.end():], run[-2:]))
    return out


def _q_stem(core):
    """the device part of an automotive orderable without its trailing Q1: up to the Q (temperature grade) after its
    first digit (TPS7A1633QDGNR -> TPS7A1633, TLV75533PQWDRBR -> TLV75533P, LMS3655AQRNLR -> LMS3655A), or None"""
    m = re.match(r'(%s\d[0-9A-Z]*?)Q[A-Z]' % TI_PREFIX, core)
    return m.group(1) if m else None


def ti_candidates(name):
    """[(device-name guess, why)] for a TI name that may be an orderable number, in the order tried. why is None for
    a guess that keeps the orderable's own device name (letters trimmed off the end: TPS61089RNRR -> TPS61089; a -Q1
    form of an automotive number: TPS61088QRHLRQ1 -> TPS61088-Q1), else what was dropped to make it, which may name
    another device, so a page found that way needs ti_orderable_confirmed:
    - a voltage code from the middle (TLV75518PDRVR -> TLV755P),
    - everything from the first "-", "." or "/" (LP5907MFX-3.3/NOPB -> LP5907, LP2985-33DBVR -> LP2985),
    - the automotive grade: a plain page for a ...Q1 orderable (TPS61088QRHLRQ1 -> TPS61088).
    A trailing lead-finish code (G4, E4, G3, E3: LM358DRG4 -> LM358DR ... LM358) is the same device and is cut first.
    An automotive number tries its -Q1 device pages first (TPS7A1633QDGNRQ1 -> TPS7A1633-Q1, TPS7A16-Q1), then plain
    pages of its device part only (the letters after its Q are the package). Guesses that cannot be a page (with a
    "/", ending in "-" or ".") are left out. Not capped: ti_resolve stops at MAX_TI_REQUESTS."""
    q1 = name.endswith('Q1') and not name.endswith('-Q1')
    core = name[:-2] if q1 else name
    finish = re.match(r'(.*\d.*[A-Z])[GE][34]$', core)   # TI's lead-finish suffix (LM358DRG4, TPS2051BDBVRG4): the
    if finish:                                            # same device, and ti.com lists no part-details for it
        core = finish.group(1)
    head, tail = re.match(r'([^-./]*)(.*)', core).groups()
    base, base_why = (head, ("the suffix '%s'" % tail,)) if tail and tail != '-Q1' else (core, ())
    forms = [(core, ())] + ([(base, base_why)] if base != core else [])
    forms += [(v, ("'%s' as a voltage code" % code,) + base_why) for v, code in _without_voltage(base)]
    out = {}

    def add(c, why):
        if c and '/' not in c and c[-1] not in '-.':
            out.setdefault(c, ' and '.join(why) or None)
    if q1:
        stems = [(_q_stem(f), why) for f, why in forms]
        for stem, why in stems:
            if stem:
                add(stem + '-Q1', why)
                add(_trims(stem)[-1] + '-Q1', why)
        for (stem, why), (f, _) in zip(stems, forms):
            for c in _trims(stem or f):
                add(c, why + ('the automotive grade (Q1)',))
    else:
        for f, why in forms:
            for c in _trims(f):
                add(c, why)
    return list(out.items())


def ti_orderable_confirmed(page, order):
    """True when ti.com lists the orderable number under that device page: ti.com/product/PAGE/part-details/ORDER
    answers 200 at that same URL and the page names ORDER. Checked 2026-10-30: TLV755P/TLV75518PDRVR,
    TLV767/TLV76718DRVR, TPS7A20/TPS7A2033PDBVR, TPS7A16-Q1/TPS7A1633QDGNRQ1, LP2985/LP2985-33DBVR and
    LP5907/LP5907MFX-3.3/NOPB (the "/" as is; encoded as %2F it is a 404) are 200; mismatched pairs
    (TLV755P/TPS61089RNRR, TLV767/TLV75518PDRVR, TPS7A16/TPS7A1633QDGNRQ1, LP5912/LP2985-33DBVR, ...) are a plain 404
    with no redirect. Any failure is False."""
    try:
        url, html = _fetch('https://www.ti.com/product/%s/part-details/%s' % (page, order))
    except (OSError, http.client.HTTPException):      # HTTPError (404) and URLError are OSErrors
        return False
    return url.rstrip('/').upper().endswith('/PART-DETAILS/' + order.upper()) and order.upper() in html.upper()


def ti_resolve(name):
    """(status, device page name, what was dropped to find it or None, orderable confirmed on that page). The first
    candidate with a product page wins; none -> SUSPECT. A page found by dropping something (ti_candidates) is checked
    with ti_orderable_confirmed(page, name), unless its status could not be read. This is the one place that counts
    requests: at most MAX_TI_REQUESTS, a candidate that would need a confirmation only tried while both fit."""
    last, asked = 'SUSPECT (no product page tried)', 0
    for c, why in ti_candidates(name):
        if asked + 1 + bool(why) > MAX_TI_REQUESTS:
            continue
        st = ti_lifecycle(c)
        asked += 1
        if st.startswith('SUSPECT'):
            last = st
            continue
        return st, c, why, bool(why) and not st.startswith('unknown') and ti_orderable_confirmed(c, name)
    return last, name, None, False


def lifecycle_text(name, status, page, why, confirmed=False):
    """the lifecycle column. A page found only by dropping something (why) may be another device: unless ti.com lists
    the orderable number under it (confirmed), its status gets a "?" and the text ends in UNCONFIRMED, so it does not
    pass the gate (gate_flag) whatever the status, until the device is confirmed by hand"""
    if why and confirmed:
        return '%s (as %s; ti.com lists %s under it)' % (status, page, name)
    if why:
        return '%s? (as %s, found only by dropping %s: %s)' % (status, page, why, UNCONFIRMED)
    return status + (' (as %s)' % page if page != name else '')


def gate_flag(life):
    """the flag a lifecycle text raises, or None when it passes"""
    if re.match(r'SUSPECT|NRND|OBSOLETE|LAST TIME', life):
        return 'LIFECYCLE'
    if life.endswith(UNCONFIRMED + ')'):
        return 'LIFECYCLE UNCONFIRMED'
    return None


def is_ti(name):
    return re.match(TI_PREFIX + r'\d', name) is not None


def lcsc_variants(name, region, cli):
    """orderable variants of a device name in one region, most stock first; a C-number is looked up exactly"""
    if re.match(r'^C\d+$', name):
        row = sourcing.lookup(name, region, cli)
        return [row] if row else []
    base = name[:-3] if name.upper().endswith('-Q1') else name
    q1 = name.upper().endswith('Q1')
    rows = []
    for row in sourcing.search(base, region, cli, n=30):
        part = (row.get('part') or '').upper()
        if not part.startswith(base.upper()) or 'JLCPCB' in (row.get('brand') or '').upper():
            continue
        rest = part[len(base):]
        if rest[:1].isdigit():                       # TPS61088 must not match TPS610881
            continue
        if q1 != part.endswith('Q1'):
            continue
        rows.append(row)
    return sorted(rows, key=lambda x: -x['stock'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='*'); ap.add_argument('--from-text', action='store_true')
    ap.add_argument('--project', help='folder to find sourcing.json from (default: the current folder)')
    ap.add_argument('--region', choices=sorted(sourcing.REGIONS), help="override sourcing.json's region")
    ap.add_argument('--sourcing', help='explicit sourcing.json')
    ap.add_argument('--per-board', type=int, default=1, help='parts of this kind per board (sets the order need)')
    ap.add_argument('--need', type=int, help='minimum stock of the best variant, instead of the sourcing.json order need')
    ap.add_argument('--cli', default=sourcing.default_cli())
    ap.add_argument('--no-lifecycle', action='store_true')
    a = ap.parse_args()
    names = list(a.names)
    if a.from_text:
        names += NAME_RE.findall(sys.stdin.read())
    names = list(dict.fromkeys(n.upper() for n in names))
    if not names:
        sys.exit('no part names given or found')
    try:
        ctx = sourcing.resolve(a.project, a.region, a.sourcing)
    except sourcing.SourcingError as e:
        sys.exit('part_gate: %s' % e)
    print(sourcing.header(ctx))
    for n in ctx['notes'][1:]:
        print('  note: ' + n)
    reg = ctx['region']
    bad = 0
    for n in names:
        order, policy, _ = sourcing.need_for(ctx, a.per_board, n if re.match(r'^C\d+$', n) else None)
        need = a.need if a.need is not None else max(order, policy)
        if re.match(r'^C\d+$', n):
            life = 'check by hand (LCSC number: read the MPN below)'
        elif not is_ti(n):
            life = 'check by hand (not a TI part number)'
        elif a.no_lifecycle:
            life = '-'
        else:
            life = lifecycle_text(n, *ti_resolve(n))
        try:
            rows = lcsc_variants(n, reg, a.cli)
            err = None
        except sourcing.SourcingError as e:
            rows, err = [], str(e)
        best = rows[0]['stock'] if rows else 0
        flags = [f for f in (gate_flag(life),) if f]
        if best < need:
            flags.append('STOCK %d < %d in %s' % (best, need, reg))
        other = ''
        if best < need and not err:
            try:
                alt = lcsc_variants(n, sourcing.other(reg), a.cli)
            except sourcing.SourcingError:
                alt = []
            if alt and alt[0]['stock']:
                other = '   [%s has %s - does not count: %s buys from %s]' % (
                    sourcing.other(reg), '{:,}'.format(alt[0]['stock']), ctx['assembler'], reg)
        bad += bool(flags)
        print('%-14s lifecycle %-28s LCSC %s: %s%s%s' % (
            n, life, reg, '%s in stock (best variant), %d variants' % ('{:,}'.format(best), len(rows)) if rows else
            ('search failed: %s' % err if err else 'no orderable variant found'),
            '   <-- ' + ', '.join(flags) if flags else '', other))
        for r in rows[:6]:
            print('    %-11s %-22s %8s  %-9s %-16s %s %s' % (r['lcsc'], r['part'], '{:,}'.format(r['stock']), r['type'], r['package'],
                                                       r['price'], r['currency']))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
