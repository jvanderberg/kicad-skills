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
  device page (TPS61089RNRR -> TPS61089, TLV75518PDRVR -> TLV755P: a fixed-voltage code is taken out of the middle)
  and the page used is printed. No product page for any of those (HTTP 404) is reported as SUSPECT: treat the part as
  discontinued until the manufacturer says otherwise. Other vendors: "check by hand" (open the product page and
  record the status);
- every orderable LCSC variant of that exact device in the project's region, with stock (an LCSC C-number is looked
  up as exactly that part).
  Variants are kept apart: an automotive "-Q1" device is a different part with its own datasheet (equations, limits,
  Rds(on) can differ), so a "-Q1" query only matches orderable numbers ending in Q1, and a plain query excludes them.
Exit 1 if any part is SUSPECT/NRND/OBSOLETE/LAST TIME BUY or has less stock than --need.

Why: distributor stock is not evidence a part is still made (a discontinued part showed 7,130 units at LCSC), and a
design tool's top picks may have no stock at all. Run this on every candidate before customising a design around it,
and again right before ordering, and present every candidate to the user with its stock, region and date (the
first output line). Results are a snapshot.
"""
import argparse, os, re, sys, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sourcing  # noqa: E402

# TI device-name prefixes, only those no other maker uses with a digit after them (SN74 logic, SN65/SN75 interface,
# TXS/TXB/TXU translators, OPA, ADS, DRV, HDC, TUSB, TMUX); ISO, REF and TMP only with as many digits as TI's own
# names have, so Infineon's ISO1H811G, ADI's REF02/REF195 and TMP36 are not taken for TI parts
TI_PREFIX = (r'(?:TPSM?|LMR|LMQ|LMZ|LM|TLV|LP|BQ|UCC|LMG|CSD|TLC|TPA|TCA|INA|LMS|TPD|TS|SN|TXS|TXB|TXU|OPA|ADS|DRV|HDC|'
             r'TUSB|TMUX|ISOW?(?=\d{3})|REF(?=\d{4})|TMP(?=\d{3}))')
NAME_RE = re.compile(r'\b(%s\d[0-9A-Z]*(?:-Q1)?)\b' % TI_PREFIX)


def ti_lifecycle(name):
    url = 'https://www.ti.com/product/%s' % name
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html = urllib.request.urlopen(req, timeout=20).read(400000).decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return ('SUSPECT (product page HTTP %d)' % e.code) if e.code == 404 else 'unknown (HTTP %d)' % e.code
    except (urllib.error.URLError, OSError) as e:
        return 'unknown (%s)' % e
    m = re.search(r'<meta\s+name="status"\s+content="([^"]+)"', html, re.I)
    return m.group(1).upper() if m else 'unknown (no status tag on %s)' % url


def _trims(name):
    """name, its -Q1 device form, then name shortened from the end, never below prefix + digits (+ one letter, as in
    TPS61230A), then prefix + digits"""
    out = [name]
    m = re.match(r'(%s\d+[A-Z]?)' % TI_PREFIX, name)
    floor = m.group(1) if m else name
    if name.endswith('Q1') and not name.endswith('-Q1'):
        q = re.match(r'(%s\d+[A-Z]?)Q' % TI_PREFIX, name)
        if q:
            out.append(q.group(1) + '-Q1')
            out.append(re.match(r'%s\d+' % TI_PREFIX, name).group(0) + '-Q1')
    s = name
    while len(s) > len(floor):
        s = s[:-1]
        out.append(s)
    if re.match(r'%s\d+' % TI_PREFIX, name):
        out.append(re.match(r'%s\d+' % TI_PREFIX, name).group(0))
    return out


def _without_voltage(name):
    """the name with a two-digit voltage code taken out of the middle: TI's fixed-voltage order codes insert it
    after the device name (TLV755+18+P+DRVR, TLV767+18+DRVR, TPS7A20+33+PDBVR, TLV1117LV+33+DCYR). Tried for every
    digit group followed by a letter; the first group keeps at least three digits (TLV755, not TLV7)."""
    p = re.match(TI_PREFIX, name)
    out = []
    for m in re.finditer(r'\d+(?=[A-Z])', name):
        run = m.group(0)
        if len(run) < 2 or (p and m.start() == p.end() and len(run) - 2 < 3):
            continue
        out.append(name[:m.end() - 2] + name[m.end():])
    return out


def ti_candidates(name):
    """device-name guesses for a TI name that may be an orderable number, in the order tried: the name trimmed from
    the end (TPS61089RNRR -> TPS61089RNR ... TPS61089; TPS61088QRHLRQ1 -> TPS61088-Q1), then the same for the name
    without a mid-name voltage code (TLV75518PDRVR -> TLV755PDRVR ... TLV755P; TLV76718DRVR -> ... TLV767)."""
    out = _trims(name)
    for v in _without_voltage(name):
        out += _trims(v)
    return list(dict.fromkeys(out))


def ti_resolve(name):
    """(status, device page name). The first candidate with a product page wins; none -> SUSPECT."""
    last = None
    for c in ti_candidates(name):
        st = ti_lifecycle(c)
        if not st.startswith('SUSPECT'):
            return st, c
        last = st
    return last, name


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
            life, page = ti_resolve(n)
            if page != n:
                life += ' (as %s)' % page
        try:
            rows = lcsc_variants(n, reg, a.cli)
            err = None
        except sourcing.SourcingError as e:
            rows, err = [], str(e)
        best = rows[0]['stock'] if rows else 0
        flags = []
        if re.match(r'SUSPECT|NRND|OBSOLETE|LAST TIME', life):
            flags.append('LIFECYCLE')
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
