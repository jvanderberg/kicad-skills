#!/usr/bin/env python3
"""Apply a JLCPCB stackup, design rules and net classes to a KiCad project, as text (no GUI, no pcbnew).

  board_setup.py PROJECT.kicad_pro|PROJECT_DIR --stackup JLC04161H-7628 [--finish ENIG]
                 [--rules jlc|keep] [--class NAME:track=0.8,clearance=0.2,via=0.6,drill=0.3 ...]
                 [--assign NAME=NET1,NET2 ...] [--pattern NAME=GLOB ...]
  board_setup.py --list

Why: kicad-cli cannot create or set up a board, and pcbnew's python does not expose the board stackup
(GetStackupDescriptor() returns an opaque object in KiCad 10.0.1). This writes:
- the board's (setup (stackup ...)) block from the table below (replacing an existing one), and the board thickness;
- .kicad_pro design rules: comfortable values for JLC's capabilities, not their minimums (--rules jlc), or untouched;
- .kicad_pro net classes: Default (0.2 mm track, 0.15 mm clearance, 0.6/0.3 mm via) plus any --class, and net
  assignments by exact name (--assign) or wildcard pattern (--pattern, KiCad's netclass_patterns).
The board's copper layer count must match the stackup (make the board with new_board.py or KiCad first).

Numbers: 4-layer stackups from kicad-new-board/references/jlcpcb-stackups.md (jlcpcb.com/impedance, checked Oct 2026);
the 2-layer entry is derived (1.6 mm board less copper and mask), JLC publishes no 2-layer table. JLC changes these:
re-check the page before ordering and say that you did. Board-specific rules (a footprint-scoped clearance for a
fine-pitch part) belong in the project's .kicad_dru, written by hand with the reason in a comment.
"""
import argparse, json, os, re, sys

MASK = dict(thickness=0.01, er=3.8)            # solder mask: er 3.8 per JLC's impedance page; 0.01 mm nominal
OUTER, INNER = 0.035, 0.0152                   # finished copper, 1 oz outer / 0.5 oz inner (JLC default inner)

# name -> list of copper / dielectric entries between the masks, top to bottom
STACKUPS = {
    'JLC04161H-7628': [('cu', OUTER), ('prepreg', 0.2104, '7628', 4.4), ('cu', INNER), ('core', 1.065, 'FR4', 4.6),
                       ('cu', INNER), ('prepreg', 0.2104, '7628', 4.4), ('cu', OUTER)],
    'JLC04161H-3313': [('cu', OUTER), ('prepreg', 0.0994, '3313', 4.1), ('cu', INNER), ('core', 1.265, 'FR4', 4.6),
                       ('cu', INNER), ('prepreg', 0.0994, '3313', 4.1), ('cu', OUTER)],
    'JLC04161H-1080': [('cu', OUTER), ('prepreg', 0.0764, '1080', 3.91), ('cu', INNER), ('core', 1.265, 'FR4', 4.6),
                       ('cu', INNER), ('prepreg', 0.0764, '1080', 3.91), ('cu', OUTER)],
    'JLC04161H-2116': [('cu', OUTER), ('prepreg', 0.1164, '2116', 4.16), ('cu', INNER), ('core', 1.265, 'FR4', 4.6),
                       ('cu', INNER), ('prepreg', 0.1164, '2116', 4.16), ('cu', OUTER)],
    # derived, not a JLC table: 1.6 - 2 x 0.035 copper - 2 x 0.01 mask
    'JLC-2L-1.6': [('cu', OUTER), ('core', 1.51, 'FR4', 4.6), ('cu', OUTER)],
}

# Design rules: comfortable values inside JLC's published capabilities (jlcpcb-stackups.md), KiCad defaults where JLC
# gives no number. Minimums for DRC, not the values to route with - routing uses the net classes.
JLC_RULES = {
    'min_clearance': 0.15,                 # JLC min 0.09-0.10 mm (1 oz); 0.15 is the comfortable value
    'min_track_width': 0.15,
    'min_through_hole_diameter': 0.2,      # JLC "preferred min via drill"
    'min_via_diameter': 0.35,              # 0.2 drill + 0.15 ("via pad 0.1, preferably 0.15 mm larger than the drill")
    'min_via_annular_width': 0.075,
    'min_copper_edge_clearance': 0.3,      # JLC 0.2 mm for routed edges (0.4 for V-cut): margin added
    'min_hole_to_hole': 0.25,              # KiCad default; not in the JLC table we checked - verify
    'min_hole_clearance': 0.25,            # KiCad default
}

CLASS_BASE = {'bus_width': 12, 'diff_pair_gap': 0.25, 'diff_pair_via_gap': 0.25, 'diff_pair_width': 0.2,
              'line_style': 0, 'microvia_diameter': 0.3, 'microvia_drill': 0.1, 'pcb_color': 'rgba(0, 0, 0, 0.000)',
              'schematic_color': 'rgba(0, 0, 0, 0.000)', 'tuning_profile': '', 'wire_width': 6}
DEFAULT_CLASS = dict(track_width=0.2, clearance=0.15, via_diameter=0.6, via_drill=0.3)


# ------------------------------------------------------------------ s-expression writers

def stackup_layer_sexpr(name, typ, extra=()):
    body = ''.join('\t\t\t\t(%s %s)\n' % kv for kv in extra)
    return '\t\t\t(layer "%s"\n\t\t\t\t(type "%s")\n%s\t\t\t)\n' % (name, typ, body)


def stackup_sexpr(name, finish='None'):
    entries = STACKUPS[name]
    ncu = sum(1 for e in entries if e[0] == 'cu')
    cu_names = ['F.Cu'] + ['In%d.Cu' % i for i in range(1, ncu - 1)] + ['B.Cu']
    out = [stackup_layer_sexpr('F.SilkS', 'Top Silk Screen'), stackup_layer_sexpr('F.Paste', 'Top Solder Paste'),
           stackup_layer_sexpr('F.Mask', 'Top Solder Mask', (('thickness', MASK['thickness']), ('material', '"LPI"'),
                                                             ('epsilon_r', MASK['er'])))]
    ci = di = 0
    for e in entries:
        if e[0] == 'cu':
            out.append(stackup_layer_sexpr(cu_names[ci], 'copper', (('thickness', e[1]),)))
            ci += 1
        else:
            di += 1
            out.append(stackup_layer_sexpr('dielectric %d' % di, e[0], (('thickness', e[1]), ('material', '"%s"' % e[2]),
                                                                       ('epsilon_r', e[3]))))
    out += [stackup_layer_sexpr('B.Mask', 'Bottom Solder Mask', (('thickness', MASK['thickness']), ('material', '"LPI"'),
                                                                ('epsilon_r', MASK['er']))),
            stackup_layer_sexpr('B.Paste', 'Bottom Solder Paste'), stackup_layer_sexpr('B.SilkS', 'Bottom Silk Screen')]
    return '\t\t(stackup\n%s\t\t\t(copper_finish "%s")\n\t\t\t(dielectric_constraints no)\n\t\t)\n' % (''.join(out), finish)


def thickness(name):
    return round(sum(e[1] for e in STACKUPS[name]) + 2 * MASK['thickness'], 4)


def copper_count(name):
    return sum(1 for e in STACKUPS[name] if e[0] == 'cu')


# ------------------------------------------------------------------ edits

def _block_end(t, i):
    d, j, ins = 0, i, False
    while True:
        c = t[j]
        if ins:
            if c == '\\':
                j += 2
                continue
            ins = c != '"'
        elif c == '"':
            ins = True
        elif c == '(':
            d += 1
        elif c == ')':
            d -= 1
            if d == 0:
                return j + 1
        j += 1


def apply_stackup(t, name, finish):
    layers = t[t.index('\t(layers\n'):_block_end(t, t.index('\t(layers\n') + 1)]
    have = len(re.findall(r'"(?:F|B|In\d+)\.Cu"', layers))
    if have != copper_count(name):
        sys.exit('board has %d copper layers, stackup %s has %d: change the board first' % (have, name, copper_count(name)))
    m = re.search(r'\n\t\t\(stackup\n', t)
    if m:
        e = _block_end(t, m.start() + 3)
        t = t[:m.start() + 1] + t[e + 1:] if t[e] == '\n' else t[:m.start() + 1] + t[e:]
    i = t.index('\t(setup\n') + len('\t(setup\n')
    t = t[:i] + stackup_sexpr(name, finish) + t[i:]
    return re.sub(r'(\(general\s*\(thickness )[\d.]+', lambda m: m.group(1) + '%g' % thickness(name), t, count=1)


def parse_class(spec):
    name, _, kv = spec.partition(':')
    keys = {'track': 'track_width', 'clearance': 'clearance', 'via': 'via_diameter', 'drill': 'via_drill'}
    c = dict(DEFAULT_CLASS)
    for item in filter(None, kv.split(',')):
        k, v = item.split('=')
        c[keys[k.strip()]] = float(v)
    return name, c


def apply_project(pro, rules, classes, assigns, patterns):
    ds = pro.setdefault('board', {}).setdefault('design_settings', {})
    if rules == 'jlc':
        ds.setdefault('rules', {}).update(JLC_RULES)
        ds['track_widths'] = [0.0, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0]
        ds['via_dimensions'] = [{'diameter': 0.0, 'drill': 0.0}, {'diameter': 0.6, 'drill': 0.3},
                                {'diameter': 0.8, 'drill': 0.4}, {'diameter': 0.45, 'drill': 0.2}]
    ns = pro.setdefault('net_settings', {})
    old = {c['name']: c for c in ns.get('classes') or []}
    want = dict([('Default', dict(DEFAULT_CLASS))] + classes)
    out = []
    for i, (name, c) in enumerate(want.items()):
        base = dict(CLASS_BASE, **old.get(name, {}))
        base.update(c, name=name, priority=2147483647 if name == 'Default' else i - 1)
        out.append(base)
    out += [c for n, c in old.items() if n not in want]          # keep classes the user already had
    ns['classes'] = out
    ns.setdefault('meta', {'version': 5})
    if assigns:
        a = ns.get('netclass_assignments') or {}
        a.update(assigns)
        ns['netclass_assignments'] = a
    if patterns:
        ns['netclass_patterns'] = [p for p in ns.get('netclass_patterns') or [] if p['pattern'] not in dict(patterns)] + \
            [{'netclass': c, 'pattern': p} for p, c in patterns]
    return pro


def main():
    ap = argparse.ArgumentParser(description='JLC stackup, design rules and net classes for a KiCad project')
    ap.add_argument('project', nargs='?')
    ap.add_argument('--stackup'); ap.add_argument('--finish', default='None', help='copper_finish as KiCad names it')
    ap.add_argument('--rules', default='jlc', choices=['jlc', 'keep'])
    ap.add_argument('--class', dest='classes', action='append', default=[])
    ap.add_argument('--assign', action='append', default=[]); ap.add_argument('--pattern', action='append', default=[])
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    if a.list or not a.project:
        for n in STACKUPS:
            print('%-16s %d copper layers, %.3f mm' % (n, copper_count(n), thickness(n)))
        return
    pro_path = a.project
    if os.path.isdir(pro_path):
        found = [f for f in os.listdir(pro_path) if f.endswith('.kicad_pro')]
        if len(found) != 1:
            sys.exit('expected one .kicad_pro in %s, found %s' % (pro_path, found))
        pro_path = os.path.join(pro_path, found[0])
    pcb_path = pro_path[:-len('.kicad_pro')] + '.kicad_pcb'
    classes = [parse_class(c) for c in a.classes]
    assigns = {}
    for s in a.assign:
        cls, nets = s.split('=', 1)
        assigns.update({n: cls for n in nets.split(',') if n})
    patterns = [(s.split('=', 1)[1], s.split('=', 1)[0]) for s in a.pattern]
    pro = json.load(open(pro_path))
    known = {c['name'] for c in pro.get('net_settings', {}).get('classes') or []} | {'Default'} | {n for n, _ in classes}
    unknown = sorted(({c for c in assigns.values()} | {c for _, c in patterns}) - known)
    if unknown:
        sys.exit('net class %s is not defined: add --class %s:track=...,clearance=...' % (unknown, unknown[0]))
    if a.stackup:
        if a.stackup not in STACKUPS:
            sys.exit('unknown stackup %s; --list shows the table' % a.stackup)
        new = apply_stackup(open(pcb_path, encoding='utf-8').read(), a.stackup, a.finish)    # may refuse: write after
        open(pcb_path, 'w', encoding='utf-8').write(new)
        print('stackup %s (%.3f mm) written to %s' % (a.stackup, thickness(a.stackup), pcb_path))
    pro = apply_project(pro, a.rules, classes, assigns, patterns)
    json.dump(pro, open(pro_path, 'w'), indent=2)
    print('%s: rules %s; classes %s; %d assignments, %d patterns' % (
        pro_path, a.rules, [c['name'] for c in pro['net_settings']['classes']], len(assigns), len(patterns)))


if __name__ == '__main__':
    main()
