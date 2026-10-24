# Check every part in a KiCad schematic against LCSC stock before ordering (or after any part change).
#   python bom_check.py project.kicad_sch [--boards 5] [--min-pkg 0402] [--cli jlcimport-cli]
# Exports the netlist with kicad-cli, groups parts by LCSC number, looks each one up with JLCImport's CLI
# (https://github.com/jvanderberg/kicad_jlcimport, `jlcimport-cli search C12345 --region global`), and flags:
#   - parts with no LCSC number (JLC will not place them; may be intentional for hand-fit parts)
#   - LCSC numbers not found or with stock below what the order needs (count per board x boards, plus 10 % attrition)
#   - packages smaller than --min-pkg (0201 and 01005 cost extra and yield worse at JLC economic assembly)
#   - Extended parts (each unique one adds a loading fee at JLC)
# Stock moves daily: re-run right before ordering, and never trust a number from an earlier session.
import argparse, csv, io, json, os, re, shutil, subprocess, sys, tempfile, collections, xml.etree.ElementTree as ET
ap = argparse.ArgumentParser()
ap.add_argument('sch'); ap.add_argument('--boards', type=int, default=5); ap.add_argument('--min-pkg', default='0402')
ap.add_argument('--cli', default=os.environ.get('JLCIMPORT_CLI') or shutil.which('jlcimport-cli') or 'jlcimport-cli')
ap.add_argument('--kicad-cli', default=os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
ap.add_argument('--json', help='also write results here')
a = ap.parse_args()

xmlp = os.path.join(tempfile.mkdtemp(), 'net.xml')
subprocess.run([a.kicad_cli, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xmlp, a.sch], check=True, capture_output=True)
root = ET.parse(xmlp).getroot()
SIZES = ['01005', '0201', '0402', '0603', '0805', '1206']
def pkg_size(fp, val):
    m = re.search(r'(?<!\d)(01005|0201|0402|0603|0805|1206)(?!\d)', fp + ' ' + val)
    return m.group(1) if m else None
groups = collections.OrderedDict(); missing = []
for c in root.find('components'):
    ref = c.get('ref')
    if ref.startswith('#'): continue
    f = {e.get('name'): (e.text or '').strip() for e in c.find('fields')} if c.find('fields') is not None else {}
    props = {p.get('name'): p.get('value') for p in c.findall('property')}
    if 'dnp' in props or 'exclude_from_bom' in props: continue
    lc = f.get('LCSC') or f.get('LCSC Part') or f.get('JLCPCB Part #') or ''
    fp = (c.findtext('footprint') or '').split(':')[-1]; val = c.findtext('value') or ''
    if not re.match(r'^C\d+$', lc): missing.append((ref, val, fp)); continue
    g = groups.setdefault(lc, dict(lcsc=lc, refs=[], value=val, fp=fp, size=pkg_size(fp, val)))
    g['refs'].append(ref)

def lookup(lc):
    r = subprocess.run([a.cli, 'search', lc, '--region', 'global', '--min-stock', '0', '--csv', '-n', '5'], capture_output=True, text=True, timeout=90)
    for row in csv.DictReader(io.StringIO(r.stdout)):
        if row.get('LCSC') == lc: return row
    return None
rows = []; problems = 0
for lc, g in groups.items():
    need = int(len(g['refs']) * a.boards * 1.1 + 0.999)
    info = lookup(lc)
    flags = []
    if info is None: flags.append('NOT FOUND')
    else:
        stock = int(info['Stock'] or 0)
        if stock < need: flags.append('STOCK %d < need %d' % (stock, need))
        if info.get('Type', '').lower().startswith('ext'): flags.append('extended')
    if g['size'] and SIZES.index(g['size']) < SIZES.index(a.min_pkg): flags.append('package %s below %s' % (g['size'], a.min_pkg))
    problems += any(f for f in flags if f != 'extended')
    rows.append(dict(lcsc=lc, refs=g['refs'], value=g['value'], footprint=g['fp'], need=need, stock=(info or {}).get('Stock'), type=(info or {}).get('Type'),
                     part=(info or {}).get('Part'), package=(info or {}).get('Package'), price=(info or {}).get('Price'), flags=flags))
    print('%-11s %-5s %8s  %-26s %-22s %s' % (lc, len(g['refs']), (info or {}).get('Stock', '-'), (g['value'] or '')[:26], ((info or {}).get('Part') or '')[:22],
                                            ', '.join(flags)), flush=True)
print('\n%d unique LCSC parts, %d with problems, %d extended, %d parts without an LCSC number%s' % (
    len(rows), problems, sum('extended' in r['flags'] for r in rows), len(missing), ': ' + ', '.join(r for r, _, _ in missing) if missing else ''))
print('Also check by hand: the LCSC part really matches the symbol (value, voltage, package, pinout) - a valid number can still be the wrong part.')
if a.json: json.dump(dict(parts=rows, missing_lcsc=missing, boards=a.boards), open(a.json, 'w'), indent=1)
sys.exit(1 if problems else 0)
