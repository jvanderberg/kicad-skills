#!/usr/bin/env python3
"""Lifecycle + stock gate for candidate parts, before any design work is spent on them.

  part_gate.py TPS61088 TPS61088-Q1 BQ25606 ... [--need 50] [--cli jlcimport-cli]
  pbpaste | part_gate.py --from-text [--need 50]      # pasted text, e.g. WEBENCH's TABLE VIEW: part numbers are found

For each device name it prints:
- lifecycle from the manufacturer's product page, where that can be read automatically (TI: ti.com/product/<NAME>,
  the page's status tag: ACTIVE / NRND / LAST TIME BUY / OBSOLETE / PREVIEW). A missing product page (HTTP 404) is
  reported as SUSPECT: treat the part as discontinued until the manufacturer says otherwise. Other vendors: "check by
  hand" (open the product page and record the status);
- every orderable LCSC variant of that exact device (jlcimport-cli search --region global), with stock and the total.
  Variants are kept apart: an automotive "-Q1" device is a different part with its own datasheet (equations, limits,
  Rds(on) can differ), so a "-Q1" query only matches orderable numbers ending in Q1, and a plain query excludes them.
Exit 1 if any part is SUSPECT/NRND/OBSOLETE/LAST TIME BUY or has less stock than --need.

Why: distributor stock is not evidence a part is still made (a discontinued part showed 7,130 units at LCSC), and a
design tool's top picks may have no stock at all. Run this on every candidate before customising a design around it,
and again right before ordering. Results are a snapshot: record the date with them.
"""
import argparse, csv, io, os, re, shutil, subprocess, sys, urllib.error, urllib.request

TI_PREFIX = r'(?:TPSM?|LMR|LMQ|LMZ|LM|TLV|LP|BQ|UCC|LMG|CSD|TLC|TPA|TCA|INA|LMS|TPD|TS)'
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


def ti_candidates(name):
    """device-name guesses for a TI name that may be an orderable number: TPS61089RNRR -> TPS61089RNR ... TPS61089;
    TPS61088QRHLRQ1 -> TPS61088-Q1. Never shorter than prefix + digits (+ one letter, as in TPS61230A)."""
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


def lcsc_variants(name, cli):
    base = name[:-3] if name.upper().endswith('-Q1') else name
    q1 = name.upper().endswith('Q1')
    r = subprocess.run([cli, 'search', base, '--region', 'global', '--min-stock', '0', '--csv', '-n', '30'],
                       capture_output=True, text=True, timeout=120)
    rows = []
    for row in csv.DictReader(io.StringIO(r.stdout)):
        part = (row.get('Part') or '').upper()
        if not part.startswith(base.upper()) or 'JLCPCB' in (row.get('Brand') or '').upper():
            continue
        rest = part[len(base):]
        if rest[:1].isdigit():                       # TPS61088 must not match TPS610881
            continue
        if q1 != part.endswith('Q1'):
            continue
        rows.append(dict(lcsc=row['LCSC'], part=row['Part'], stock=int(row['Stock'] or 0), type=row.get('Type', ''),
                         package=row.get('Package', ''), price=row.get('Price', '')))
    return sorted(rows, key=lambda x: -x['stock']), r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='*'); ap.add_argument('--from-text', action='store_true')
    ap.add_argument('--need', type=int, default=1, help='minimum stock of the best variant (boards x per-board x 1.1)')
    ap.add_argument('--cli', default=os.environ.get('JLCIMPORT_CLI') or shutil.which('jlcimport-cli') or 'jlcimport-cli')
    ap.add_argument('--no-lifecycle', action='store_true')
    a = ap.parse_args()
    names = list(a.names)
    if a.from_text:
        names += NAME_RE.findall(sys.stdin.read())
    names = list(dict.fromkeys(n.upper() for n in names))
    if not names:
        sys.exit('no part names given or found')
    bad = 0
    for n in names:
        if not is_ti(n):
            life = 'check by hand (not a TI part number)'
        elif a.no_lifecycle:
            life = '-'
        else:
            life, page = ti_resolve(n)
            if page != n:
                life += ' (as %s)' % page
        rows, rc = lcsc_variants(n, a.cli)
        best = rows[0]['stock'] if rows else 0
        flags = []
        if re.match(r'SUSPECT|NRND|OBSOLETE|LAST TIME', life):
            flags.append('LIFECYCLE')
        if best < a.need:
            flags.append('STOCK %d < %d' % (best, a.need))
        bad += bool(flags)
        print('%-14s lifecycle %-28s LCSC global: %s%s' % (
            n, life, '%d in stock (best variant), %d variants' % (best, len(rows)) if rows else
            ('search failed (exit %d)' % rc if rc else 'no orderable variant found'),
            '   <-- ' + ', '.join(flags) if flags else ''))
        for r in rows[:6]:
            print('    %-11s %-22s %8d  %-9s %s' % (r['lcsc'], r['part'], r['stock'], r['type'], r['package']))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
