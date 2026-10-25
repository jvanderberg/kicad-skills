#!/usr/bin/env python3
"""List every pin left unconnected, and every input strapped straight to a rail, as decisions to record.

  nc_audit.py NETLIST.xml|SHEET.kicad_sch [--notes notes.json] [--require-notes] [--rail-regex REGEX] [--md out.md]
              [--datasheet REF_OR_VALUE=ds.pdf|ds.txt ...]

A no-connect flag makes ERC pass in silence, and a mode/config pin tied to GND or a rail looks like wiring, so both
hide choices: a floating MODE pin may select a light-load mode through an internal pull-up, a floating EN may float
on, an unused input may need a pull-down per the datasheet. This prints one row per such pin: part, pin number, pin
name, symbol pin type, state, and the note you recorded for it from the datasheet's pin-function table.

**A pin the symbol types as no_connect needs a note like any other.** The type is the symbol author's guess (or an
importer's), not the datasheet: TPS61088-Q1's "NC" pins 11/12 say "connect these two pins to ground plane for good
thermal dissipation", and other parts' NC/DNC/reserved pins must float, be grounded, or be tied to a named rail. Only the
pin-function table decides, so every row needs its text.

notes.json: {"U5.13": "MODE: internal 800k pull-up selects PFM - floating OK (ds p3)", ...}. Without --notes the
project's pin-decisions.json is found by projfiles.py's convention (next to the sheet, or in docs/ up to the repository
root) and the file used is printed. With --require-notes the exit status is 1 while any listed pin has no note.
--datasheet: for parts whose pin table is in that PDF (or pdftotext output), each row shows the datasheet lines that
mention the pin's name and number, so the decision is written from the pin table, not from memory.
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netspec import netlist_xml
import projfiles


def ds_text(path):
    if path.lower().endswith('.pdf'):
        import subprocess
        return subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True, errors='replace').stdout
    return open(path, errors='replace').read()


def pin_lines(text, name, num):
    """datasheet lines that name this pin (its name as a word and its number in the same pin-table row), with the
    description lines that pdftotext puts just above and below the row"""
    lines = text.splitlines()
    row = re.compile(r'^\s*%s\b.*\b%s\b' % (re.escape(name), re.escape(num)), re.I) if name else None
    hits = []
    for i, l in enumerate(lines):
        if row and row.search(l):
            ctx = [x.strip() for x in lines[max(0, i - 2):i + 3] if x.strip()]
            hits.append(' / '.join(ctx))
    return hits[:2]


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
            elif base == 'input' and (rail.search(name) or any(m is not n and m.get('pintype', '').split('+')[0] in ('power_in', 'power_out')
                                                                for m in nodes)):
                # a rail by name, or by structure: the net carries some part's supply pin (an LDO output, VCC, VSYS)
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
    ap.add_argument('--datasheet', action='append', default=[], metavar='REF_OR_VALUE=FILE',
                    help='pin table source for a part (by reference, e.g. U5, or by value, e.g. TPS61088-Q1)')
    a = ap.parse_args()
    notes_path, msg = projfiles.describe(a.netlist, 'pin-decisions.json', a.notes)
    print('notes: ' + msg, file=sys.stderr)
    notes = json.load(open(notes_path)) if notes_path else {}
    ds = {}
    for d in a.datasheet:
        k, f = d.split('=', 1); ds[k] = ds_text(f)
    rows = audit(netlist_xml(a.netlist), a.rail_regex)
    lines = ['| Pin | Part | Name | Type | State | Decision / datasheet note |' + (' Datasheet pin table |' if ds else ''),
             '|---|---|---|---|---|---|' + ('---|' if ds else '')]
    missing = 0
    for r in rows:
        note = notes.get(r['pin'], '')
        if not note:
            missing += 1
        row = '| %s | %s | %s | %s | %s | %s |' % (r['pin'], r['value'], r['name'], r['type'], r['state'], note or '**TODO**')
        if ds:
            t = ds.get(r['pin'].split('.')[0]) or ds.get(r['value'])
            row += ' %s |' % ('; '.join(pin_lines(t, r['name'], r['pin'].split('.')[1])) or '(no row for %s %s found)' % (r['name'], r['pin'].split('.')[1])
                              if t else '(no datasheet given)')
        lines.append(row)
    stale = sorted(set(notes) - {r['pin'] for r in rows})
    out = '\n'.join(lines) + '\n\n%d pins listed, %d without a decision%s\n' % (
        len(rows), missing, '; notes for pins no longer unused/strapped: ' + ' '.join(stale) if stale else '')
    print(out, end='')
    if a.md:
        open(a.md, 'w').write(out)
    sys.exit(1 if a.require_notes and missing else 0)


if __name__ == '__main__':
    main()
