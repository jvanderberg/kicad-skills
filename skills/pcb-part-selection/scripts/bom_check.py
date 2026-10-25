#!/usr/bin/env python3
"""Check every part in a KiCad schematic against LCSC stock before ordering (or after any part change).

  bom_check.py project.kicad_sch [--boards 5] [--region global|cn] [--sourcing FILE] [--min-pkg 0402] [--json out.json]

The assembler, the LCSC warehouse region it buys from, the order quantity and the stock policy come from the
project's sourcing.json (sourcing.py: found next to the schematic or up to the repository root, each folder and its
docs/); --boards and --region override it for one run and the override is printed. With neither a sourcing.json nor
--region it stops: stock differs by region, and a lookup in the wrong warehouse is how an unorderable part gets
approved. The first line of the output says which context was used.

It exports the netlist with kicad-cli, groups parts by LCSC number, looks each one up with JLCImport's CLI
(https://github.com/jvanderberg/kicad_jlcimport, always with an explicit --region), and flags:
  - parts with no LCSC number (JLC will not place them; may be intentional for hand-fit parts)
  - LCSC numbers not listed in the region, or with stock below what the order needs (count per board x boards, plus
    attrition); a short part is also looked up in the other region and shown as not counting
  - stock below the project's policy (min_stock), unless a named exception in sourcing.json covers the part
  - packages smaller than --min-pkg (0201 and 01005 cost extra and yield worse at JLC economic assembly)
  - Extended parts (each unique one adds a loading fee at JLC)
  - parts whose Datasheet field is blank or KiCad's "~" (the link exists upstream - JLCImport writes the LCSC
    datasheet URL - and a stage dropped it; kicad-pcb-workflow/scripts/partfields.py says which stage)
  - ICs whose datasheet is not saved in the project (a PDF in docs/datasheets/ or datasheets/, found from the
    schematic folder up to the repository root, whose file name contains the part's MPN, value or LCSC number): a
    reviewer - person or agent - can only check pins and limits against a datasheet it can open (--no-local-datasheets
    skips it; datasheet.py fetch saves one)
  - derived values whose source part changed (derived_check.py, when the project has a design-values.json): a part
    swap that passes the stock check can still invalidate a trip current, a divider or a thermal estimate
Stock moves daily: re-run right before ordering, and never trust a number from an earlier session.
"""
import argparse, collections, json, os, re, shutil, subprocess, sys, tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sourcing  # noqa: E402

SIZES = ['01005', '0201', '0402', '0603', '0805', '1206']


def pkg_size(fp, val):
    m = re.search(r'(?<!\d)(01005|0201|0402|0603|0805|1206)(?!\d)', fp + ' ' + val)
    return m.group(1) if m else None


def export_netlist(sch, kicad_cli):
    xmlp = os.path.join(tempfile.mkdtemp(), 'net.xml')
    from kicad_locks import cli_run
    cli_run([kicad_cli, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xmlp, sch], sch, check=True,
                   capture_output=True)
    return xmlp


def bom_groups(xmlp):
    """(groups by LCSC number, parts without one). A group: lcsc, refs, value, fp, size, no_ds (refs without a link)"""
    root = ET.parse(xmlp).getroot()
    groups = collections.OrderedDict(); missing = []
    for c in root.find('components'):
        ref = c.get('ref')
        if ref.startswith('#'):
            continue
        f = {e.get('name'): (e.text or '').strip() for e in c.find('fields')} if c.find('fields') is not None else {}
        props = {p.get('name'): p.get('value') for p in c.findall('property')}
        if 'dnp' in props or 'exclude_from_bom' in props:
            continue
        lc = f.get('LCSC') or f.get('LCSC Part') or f.get('JLCPCB Part #') or ''
        fp = (c.findtext('footprint') or '').split(':')[-1]; val = c.findtext('value') or ''
        if not re.match(r'^C\d+$', lc):
            missing.append((ref, val, fp)); continue
        g = groups.setdefault(lc, dict(lcsc=lc, refs=[], value=val, fp=fp, size=pkg_size(fp, val), no_ds=[]))
        g['refs'].append(ref)
        if (f.get('Datasheet') or c.findtext('datasheet') or '').strip() in ('', '~'):
            g['no_ds'].append(ref)
    return groups, missing


def datasheet_dir(start):
    """docs/datasheets or datasheets, from start up to the repository root (projfiles.py's walk), or None"""
    d = os.path.abspath(start)
    while True:
        for c in (os.path.join(d, 'docs', 'datasheets'), os.path.join(d, 'datasheets')):
            if os.path.isdir(c):
                return c
        if os.path.isdir(os.path.join(d, '.git')) or os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def local_datasheets(xmlp, ddir):
    """[(ref, identity)] of BOM ICs with no PDF in ddir whose name contains their MPN, value or LCSC number"""
    files = [_norm(os.path.splitext(f)[0]) for f in (os.listdir(ddir) if ddir else []) if f.lower().endswith('.pdf')]
    out = []
    for c in ET.parse(xmlp).getroot().find('components'):
        ref = c.get('ref')
        if not re.match(r'^(U|IC)\d', ref):
            continue
        props = {p.get('name') for p in c.findall('property')}
        if 'dnp' in props or 'exclude_from_bom' in props:
            continue
        f = {e.get('name'): (e.text or '').strip() for e in c.find('fields')} if c.find('fields') is not None else {}
        ids = [_norm(x) for x in (f.get('MPN'), f.get('Manufacturer Part'), c.findtext('value'), f.get('LCSC'), f.get('LCSC Part'))]
        ids = [x for x in ids if len(x) >= 4]
        if not any(i in fn or (len(fn) >= 5 and fn in i) for i in ids for fn in files):
            out.append((ref, f.get('MPN') or f.get('Manufacturer Part') or c.findtext('value') or ''))
    return out


def check(groups, ctx, cli, min_pkg='0402'):
    rows = []
    for lc, g in groups.items():
        info, flags, note = sourcing.check_part(lc, ctx, len(g['refs']), cli)
        order, policy, exc = sourcing.need_for(ctx, len(g['refs']), lc)
        if info is not None and info.get('type', '').lower().startswith('ext'):
            flags.append('extended')
        if g['size'] and SIZES.index(g['size']) < SIZES.index(min_pkg):
            flags.append('package %s below %s' % (g['size'], min_pkg))
        if g['no_ds']:
            flags.append('NO DATASHEET on %s' % ' '.join(g['no_ds']))
        info = info or {}
        rows.append(dict(lcsc=lc, refs=g['refs'], value=g['value'], footprint=g['fp'], need=order, policy=policy,
                         stock=info.get('stock'), region=ctx['region'], type=info.get('type'), part=info.get('part'),
                         package=info.get('package'), price=info.get('price'), currency=info.get('currency'),
                         flags=flags, note=note, no_ds=g['no_ds']))
    return rows


def summary(rows, missing):
    problems = sum(any(f != 'extended' for f in r['flags']) for r in rows)
    return '%d unique LCSC parts, %d with problems, %d extended, %d without a datasheet link, %d parts without an LCSC number%s' % (
        len(rows), problems, sum('extended' in r['flags'] for r in rows), sum(bool(r['no_ds']) for r in rows),
        len(missing), ': ' + ', '.join(r for r, _, _ in missing) if missing else ''), problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sch'); ap.add_argument('--boards', type=int, help='assembled boards (default: sourcing.json, else 5)')
    ap.add_argument('--region', choices=sorted(sourcing.REGIONS), help="override sourcing.json's region for this run")
    ap.add_argument('--sourcing', help='explicit sourcing.json (default: found from the schematic folder)')
    ap.add_argument('--min-pkg', default='0402')
    ap.add_argument('--cli', default=sourcing.default_cli())
    ap.add_argument('--kicad-cli', default=os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
    ap.add_argument('--netlist', help='use this kicadxml netlist instead of exporting one from the schematic')
    ap.add_argument('--no-derived', action='store_true', help='skip the design-values.json check')
    ap.add_argument('--no-local-datasheets', action='store_true', help='skip the check that every IC datasheet is saved in the project')
    ap.add_argument('--json', help='also write results here')
    a = ap.parse_args()
    try:
        ctx = sourcing.resolve(os.path.dirname(os.path.abspath(a.sch)), a.region, a.sourcing)
    except sourcing.SourcingError as e:
        sys.exit('bom_check: %s' % e)
    if a.boards:
        if a.boards != ctx['boards']:
            ctx['notes'].append('--boards %d overrides %d' % (a.boards, ctx['boards']))
        ctx['boards'] = a.boards
    print(sourcing.header(ctx))
    for n in ctx['notes'][1:]:
        print('  note: ' + n)
    xmlp = a.netlist or export_netlist(a.sch, a.kicad_cli)
    groups, missing = bom_groups(xmlp)
    try:
        rows = check(groups, ctx, a.cli, a.min_pkg)
    except sourcing.SourcingError as e:
        sys.exit('bom_check: %s' % e)
    print('%-11s %-5s %8s  %-26s %-22s %s' % ('LCSC', 'qty', 'stock ' + ctx['region'][:2], 'value', 'part', 'flags'))
    for r in rows:
        print('%-11s %-5s %8s  %-26s %-22s %s%s' % (r['lcsc'], len(r['refs']), '-' if r['stock'] is None else r['stock'],
                                                  (r['value'] or '')[:26], (r['part'] or '')[:22], ', '.join(r['flags']),
                                                  '  [%s]' % r['note'] if r['note'] else ''), flush=True)
    line, problems = summary(rows, missing)
    print('\n' + line)
    stale = []
    if not a.no_derived:
        import derived_check
        dv, msg = derived_check.find_values(os.path.dirname(os.path.abspath(a.sch)))
        if dv:
            parts = derived_check.parts_from_netlist(xmlp)
            stale, cov = derived_check.check(json.load(open(dv)), parts)
            print('\nDerived values (%s): %s' % (msg, cov))
            for s in stale:
                print('  ' + s)
            problems += len(stale)
        else:
            print('\nDerived values: %s - values computed from a part\'s parameters (trip currents, dividers, '
                  'snubbers, thermal estimates) are not checked against part changes' % msg)
    nolocal = []
    if not a.no_local_datasheets:
        ddir = datasheet_dir(os.path.dirname(os.path.abspath(a.sch)))
        nolocal = local_datasheets(xmlp, ddir)
        print('\nLocal datasheets (%s): %s' % (ddir or 'no docs/datasheets folder found', '%d IC(s) without one' % len(nolocal) if nolocal else 'every IC has one'))
        for ref, ident in nolocal:
            print('  NO LOCAL DATASHEET %s %s: save it into %s (datasheet.py fetch URL FILE, the MPN in the file name)' % (
                ref, ident, ddir or 'docs/datasheets/'))
        problems += len(nolocal)
    used = {r['lcsc'] for r in rows}
    for e in ctx.get('exceptions') or []:
        if e.get('lcsc') not in used:
            print('note: stock-policy exception for %s is not in the BOM any more: remove it from sourcing.json' % e.get('lcsc'))
    print('Also check by hand: the LCSC part really matches the symbol (value, voltage, package, pinout) - a valid number can still be the wrong part.')
    if a.json:
        json.dump(dict(parts=rows, missing_lcsc=missing, boards=ctx['boards'], region=ctx['region'], assembler=ctx['assembler'],
                       date=sourcing.today(), sourcing=ctx['source'], stale_derived=stale,
                       no_local_datasheet=[r for r, _ in nolocal]), open(a.json, 'w'), indent=1)
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
