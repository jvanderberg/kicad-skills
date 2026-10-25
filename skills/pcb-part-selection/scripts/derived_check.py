#!/usr/bin/env python3
"""Derived values and the part parameters they were computed from: stale after a part change, and what depends on a part.

  derived_check.py check SHEET.kicad_sch [--values design-values.json]     # exit 1 if any value is stale
  derived_check.py deps  SHEET.kicad_sch Q2 [Q3 ...] [--values ...]         # every value computed from these parts

A value computed from a part's parameters is only right for that part: a protector's current trip is its threshold
divided by the FETs' R_DS(on); a current-limit or sense resistor is sized from a FET or shunt; a snubber or
compensation from a capacitance; a thermal estimate from a package's theta / psi; a UVLO divider from an IC's
threshold. Swap the part (a substitute for an unorderable one, a cheaper variant) and every such value silently keeps
the old part's number. The stock check passes, DRC passes, and the board trips at the wrong current.

So each derived value is recorded with what it depends on, in the project's design-values.json (found like every
project input: projfiles.py, the schematic folder and its parents up to the repository root, each folder and its docs/):

  {"values": [
    {"name": "Discharge over-current trip",            # what the value is
     "value": "12.5 A at 25 C (75 mV / 2 x 3.0 mOhm)",  # the number(s) as written in the design notes
     "equation": "I = V_OCD / (R_Q2 + R_Q3)",
     "where": "docs/power-design.md s5",                # where the derivation is written out
     "approved": "user, 2026-10-24",                    # optional: the user agreed to this value (frozen, R26)
     "depends_on": [
       {"ref": "Q2", "part": "C3289423", "param": "R_DS(on) max, Vgs 2.5 V, 25 C", "used": "3.0 mOhm",
        "source": "SiSS80DN datasheet p2"},
       {"ref": "Q3", "part": "C3289423", "param": "R_DS(on) max, Vgs 2.5 V, 25 C", "used": "3.0 mOhm",
        "source": "SiSS80DN datasheet p2"},
       {"ref": "U3", "part": "HY2113-GB3A", "param": "overcurrent threshold V_OCD", "used": "75 mV",
        "source": "HY2113 datasheet, variant table"},
       {"part": "cell", "param": "internal resistance", "used": "20 mOhm", "source": "assumed"}]}]}   # no ref: not on the BOM

"part" is the orderable identity the parameter was read for: the LCSC number, or the MPN, or the Value field, as the
schematic carries it. `check` compares every ref's part on the schematic with the recorded one and reports each value
whose source part changed or disappeared as STALE, naming the parameter and the number that has to be re-read from
the new part's datasheet; for an approved value it says that the re-derived result goes back to the user before any
edit (R26). Dependencies with no ref (cells, cables, assumed values) are listed as not checkable. Coverage: how many
values and dependencies were checked, and which ICs, FETs, inductors and fuses no value names (fine when nothing was
computed from them; a prompt when something was).
bom_check.py runs `check` whenever the project has a design-values.json.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import projfiles  # noqa: E402

NAME = 'design-values.json'
MPN_FIELDS = ('MPN', 'Manufacturer Part', 'Manufacturer_Part_Number', 'MFR.Part', 'Part Number')
WATCH = re.compile(r'^(U|Q|L|F|IC|PS|K)\d')     # parts whose parameters values are usually derived from


def find_values(project_dir, explicit=None):
    p, msg = projfiles.describe(project_dir, NAME, explicit)
    return p, msg


def parts_from_netlist(xmlp):
    """{ref: dict(lcsc, mpn, value, footprint)} for every placed part (power symbols and DNP included: a DNP part
    a value depends on is still a dependency)"""
    out = {}
    for c in ET.parse(xmlp).getroot().find('components'):
        ref = c.get('ref')
        if ref.startswith('#'):
            continue
        f = {e.get('name'): (e.text or '').strip() for e in c.find('fields')} if c.find('fields') is not None else {}
        out[ref] = dict(lcsc=f.get('LCSC') or f.get('LCSC Part') or f.get('JLCPCB Part #') or '',
                        mpn=next((f[k] for k in MPN_FIELDS if f.get(k)), ''), value=c.findtext('value') or '',
                        footprint=(c.findtext('footprint') or ''))
    return out


def export_netlist(sch, kicad_cli=None):
    kicad_cli = kicad_cli or os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
    xmlp = os.path.join(tempfile.mkdtemp(), 'net.xml')
    subprocess.run([kicad_cli, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xmlp, sch], check=True, capture_output=True)
    return xmlp


def identity(p):
    """how the schematic names this part, most specific first"""
    return p['lcsc'] or p['mpn'] or p['value']


def matches(recorded, p):
    r = recorded.strip().upper()
    return any(r == (x or '').strip().upper() for x in (p['lcsc'], p['mpn'], p['value']))


def validate(data):
    probs = []
    vals = data.get('values')
    if not isinstance(vals, list):
        return ['INCOMPLETE %s: top level needs "values": [...]' % NAME]
    for i, v in enumerate(vals):
        nm = v.get('name') or '#%d' % i
        if not v.get('name') or not v.get('value'):
            probs.append('INCOMPLETE value %s: needs "name" and "value"' % nm)
        deps = v.get('depends_on')
        if not deps:
            probs.append('INCOMPLETE value %s: no "depends_on" - which part parameters was it computed from?' % nm)
            continue
        for d in deps:
            miss = [k for k in ('part', 'param', 'used') if not d.get(k)]
            if miss:
                probs.append('INCOMPLETE value %s: dependency %s lacks %s' % (nm, d.get('ref') or d.get('part') or '?', ', '.join(miss)))
    return probs


def check(data, parts):
    """(problems, coverage line)"""
    probs = validate(data)
    n_dep = n_ext = 0; named = set()
    for v in data.get('values') or []:
        for d in v.get('depends_on') or []:
            ref = d.get('ref')
            if not ref:
                n_ext += 1; continue
            n_dep += 1; named.add(ref)
            approved = ' User-approved value (%s): take the re-derived result to the user before changing anything (R26).' % v['approved'] if v.get('approved') else ''
            what = '"%s" = %s (%s) used %s %s = %s%s' % (v.get('name'), v.get('value'), v.get('where') or 'no "where"',
                                                     d.get('part'), d.get('param'), d.get('used'),
                                                     ' [%s]' % d['source'] if d.get('source') else '')
            p = parts.get(ref)
            if p is None:
                probs.append('STALE: %s is not on the schematic any more; %s.%s' % (ref, what, approved))
            elif not matches(d.get('part', ''), p):
                probs.append('STALE: %s is now %s%s; %s. Re-read "%s" from the new part\'s datasheet and re-derive.%s' % (
                    ref, identity(p), ' (%s)' % p['mpn'] if p['mpn'] and p['mpn'] != identity(p) else '', what, d.get('param'), approved))
    unnamed = sorted((r for r in parts if WATCH.match(r) and r not in named), key=lambda s: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)])
    cov = '%d values, %d part dependencies checked against the schematic, %d not checkable (no ref: cells, cables, assumptions)%s' % (
        len(data.get('values') or []), n_dep, n_ext,
        '; no value names %s (fine if nothing was computed from them)' % ', '.join(unnamed) if unnamed else '')
    return probs, cov


def deps(data, parts, refs):
    out = []
    for v in data.get('values') or []:
        hit = [d for d in v.get('depends_on') or [] if d.get('ref') in refs or (d.get('part') and any(matches(d['part'], parts[r]) for r in refs if r in parts))]
        if hit:
            out.append('%s = %s%s  (%s)\n%s' % (v.get('name'), v.get('value'), '  [APPROVED %s]' % v['approved'] if v.get('approved') else '',
                                                v.get('where') or '', '\n'.join('    from %s %s: %s = %s%s' % (d.get('ref', '-'), d.get('part'), d.get('param'), d.get('used'),
                                                                                                   ' [%s]' % d['source'] if d.get('source') else '') for d in hit)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=('check', 'deps')); ap.add_argument('sch'); ap.add_argument('refs', nargs='*')
    ap.add_argument('--values', help='explicit design-values.json'); ap.add_argument('--netlist', help='kicadxml netlist instead of exporting one')
    ap.add_argument('--kicad-cli')
    a = ap.parse_args()
    path, msg = find_values(os.path.dirname(os.path.abspath(a.sch)), a.values)
    print(msg)
    if not path:
        print('nothing to check: record each value computed from a part parameter in %s (format: --help)' % NAME)
        sys.exit(1)
    data = json.load(open(path))
    parts = parts_from_netlist(a.netlist or export_netlist(a.sch, a.kicad_cli))
    if a.cmd == 'deps':
        if not a.refs:
            sys.exit('deps needs one or more refs')
        out = deps(data, parts, set(a.refs))
        print('%d recorded value(s) depend on %s%s' % (len(out), ' '.join(a.refs), ':' if out else
              ' - if anything was computed from these parts, it is not recorded: record it before swapping them'))
        for o in out:
            print('- ' + o)
        return
    probs, cov = check(data, parts)
    print(cov)
    for p in probs:
        print(p)
    print('%d problem(s)' % len(probs))
    sys.exit(1 if probs else 0)


if __name__ == '__main__':
    main()
