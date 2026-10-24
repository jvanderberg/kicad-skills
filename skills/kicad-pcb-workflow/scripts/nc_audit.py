#!/usr/bin/env python3
"""List every pin left unconnected, and every input strapped straight to a rail, as decisions to record.

  nc_audit.py NETLIST.xml|SHEET.kicad_sch [--notes notes.json] [--require-notes] [--rail-regex REGEX] [--md out.md]

A no-connect flag makes ERC pass in silence, and a mode/config pin tied to GND or a rail looks like wiring, so both
hide choices: a floating MODE pin may select a light-load mode through an internal pull-up, a floating EN may float
on, an unused input may need a pull-down per the datasheet. This prints one row per such pin: part, pin number, pin
name, symbol pin type, state, and the note you recorded for it from the datasheet's pin-function table.

notes.json: {"U5.13": "MODE: internal 800k pull-up selects PFM - floating OK (ds p3)", ...}. With --require-notes the
exit status is 1 while any listed pin (other than pins the symbol itself types as no_connect) has no note: run it in
the schematic review and before layout. Pins typed no_connect in the symbol are listed but need no note.
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netspec import netlist_xml


def audit(root, rail_regex):
    comps = {c.get('ref'): (c.findtext('value') or '') for c in root.find('components')}
    rail = re.compile(rail_regex)
    rows = []
    for net in root.find('nets'):
        nodes = [n for n in net.findall('node') if not n.get('ref', '').startswith('#')]
        name = net.get('name')
        for n in nodes:
            ptype = n.get('pintype', '')
            base = ptype.split('+')[0]
            func = n.get('pinfunction', '')
            pname = re.sub(r'_%s$' % re.escape(n.get('pin')), '', func) if func else ''
            if len(nodes) == 1:
                state = 'symbol NC' if base == 'no_connect' else 'unconnected'
            elif base == 'input' and rail.search(name):
                state = 'tied to %s' % name
            else:
                continue
            rows.append(dict(pin='%s.%s' % (n.get('ref'), n.get('pin')), value=comps.get(n.get('ref'), ''), name=pname,
                             type=base, state=state))
    key = lambda r: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', r['pin'])]
    return sorted(rows, key=key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('netlist'); ap.add_argument('--notes'); ap.add_argument('--require-notes', action='store_true')
    ap.add_argument('--rail-regex', default=r'^(/)?([AP]?GND\w*|\+\w+|V(CC|DD|IN|BAT|BUS|SYS)\w*)$',
                    help='net names that count as rails for strapped inputs')
    ap.add_argument('--md', help='also write the table here')
    a = ap.parse_args()
    notes = json.load(open(a.notes)) if a.notes else {}
    rows = audit(netlist_xml(a.netlist), a.rail_regex)
    lines = ['| Pin | Part | Name | Type | State | Decision / datasheet note |', '|---|---|---|---|---|---|']
    missing = 0
    for r in rows:
        note = notes.get(r['pin'], '')
        if not note and r['state'] != 'symbol NC':
            missing += 1
        lines.append('| %s | %s | %s | %s | %s | %s |' % (r['pin'], r['value'], r['name'], r['type'], r['state'],
                                                       note or ('' if r['state'] == 'symbol NC' else '**TODO**')))
    stale = sorted(set(notes) - {r['pin'] for r in rows})
    out = '\n'.join(lines) + '\n\n%d pins listed, %d without a decision%s\n' % (
        len(rows), missing, '; notes for pins no longer unused/strapped: ' + ' '.join(stale) if stale else '')
    print(out, end='')
    if a.md:
        open(a.md, 'w').write(out)
    sys.exit(1 if a.require_notes and missing else 0)


if __name__ == '__main__':
    main()
