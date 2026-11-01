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

Hierarchical designs: a sheet used N times is one drawing, so an unused or strapped pin in it is one decision. Its N
instances (the same symbol of the same sheet file, under N references) are one row, listed by the first instance's
pin with the others after it, and a note for any of them (e.g. "U101.5") covers all. A strap groups when it is the
same net of the drawing in every instance, whatever the net is called there: /ch1/X and /ch2/X, or a rail each
instance gets through a hierarchical label and the parent names (/BANK1, /BANK2). Rail names may carry a sheet
path ("/ch1/VIN" matches the default --rail-regex).
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netspec import netlist_xml, siblings
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


def group_instances(rows, sib, root):
    """rows of one symbol pin in every instance of a repeated sheet, merged: the first instance's row with the others
    in 'instances'. A strap is the same decision when it is the same net of the drawing: in each instance the pin's net
    holds the same symbol pins of that instance - whatever the net is called there ('/ch1/X' and '/ch2/X', or a rail
    the parent names per instance through a hierarchical label: '/BANK1', '/BANK2')."""
    nodes = {net.get('name'): [(n.get('ref'), n.get('pin')) for n in net.findall('node')] for net in root.find('nets')}

    def drawn(net, sheet):
        """the net as drawn on one instance: the (symbol uuid, pin) on it that belong to that instance"""
        return frozenset((sib[r][1], p) for r, p in nodes.get(net, []) if r in sib and sib[r][2] == sheet)
    groups, out = {}, []
    for r in rows:
        ref, num = r['pin'].split('.', 1)
        f, uuid, sheet = sib.get(ref, ('', ref, '/'))
        kind = 'tied' if r['state'].startswith('tied to ') else r['state']
        k = (f, uuid or ref, num, r['type'], kind, drawn(r['net'], sheet) if kind == 'tied' and sheet != '/' else None)
        if k in groups:
            g = groups[k]
            g['instances'].append(r['pin'])
            if r['state'] != g['state'] and r['state'] not in g['states']:
                g['states'].append(r['state'])
            continue
        r = dict(r, instances=[], states=[])
        groups[k] = r
        out.append(r)
    for r in out:
        if r['states']:                                  # one strap, a differently named net in each instance
            names = [r['state'][len('tied to '):]] + [x[len('tied to '):] for x in r['states']]
            r['state'] += ' (each instance its own: %s)' % ', '.join(names[:4] + (['...'] if len(names) > 4 else []))
    return out


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
                             type=base, state=state, net=name))
    key = lambda r: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', r['pin'])]
    return sorted(rows, key=key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('netlist'); ap.add_argument('--notes'); ap.add_argument('--require-notes', action='store_true')
    ap.add_argument('--rail-regex', default=r'^(/([^/]+/)*)?([AP]?GND\w*|\+\w+|V(CC|DD|IN|BAT|BUS|SYS)\w*)$',
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
    root = netlist_xml(a.netlist)
    rows = group_instances(audit(root, a.rail_regex), siblings(root), root)
    lines = ['| Pin | Part | Name | Type | State | Decision / datasheet note |' + (' Datasheet pin table |' if ds else ''),
             '|---|---|---|---|---|---|' + ('---|' if ds else '')]
    missing = 0
    for r in rows:
        note = next((notes[p] for p in [r['pin']] + r['instances'] if notes.get(p)), '')
        if not note:
            missing += 1
        pin = r['pin'] + (' (and %s)' % ', '.join(r['instances']) if r['instances'] else '')
        row = '| %s | %s | %s | %s | %s | %s |' % (pin, r['value'], r['name'], r['type'], r['state'], note or '**TODO**')
        if ds:
            t = ds.get(r['pin'].split('.')[0]) or ds.get(r['value'])
            row += ' %s |' % ('; '.join(pin_lines(t, r['name'], r['pin'].split('.')[1])) or '(no row for %s %s found)' % (r['name'], r['pin'].split('.')[1])
                              if t else '(no datasheet given)')
        lines.append(row)
    stale = sorted(set(notes) - {p for r in rows for p in [r['pin']] + r['instances']})
    every = sum(1 + len(r['instances']) for r in rows)
    out = '\n'.join(lines) + '\n\n%d pins listed%s, %d without a decision%s\n' % (
        len(rows), ' (%d counting every sheet instance)' % every if every != len(rows) else '', missing,
        '; notes for pins no longer unused/strapped: ' + ' '.join(stale) if stale else '')
    print(out, end='')
    if a.md:
        open(a.md, 'w').write(out)
    sys.exit(1 if a.require_notes and missing else 0)


if __name__ == '__main__':
    main()
