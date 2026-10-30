#!/usr/bin/env python3
"""Apply a JLCPCB stackup, design rules and net classes to a KiCad project (no GUI, no pcbnew), through kicad_sexpr.

  board_setup.py PROJECT.kicad_pro|PROJECT_DIR --stackup JLC04161H-7628 [--finish ENIG]
                 [--rules jlc|keep] [--class NAME:track=0.8,clearance=0.2,via=0.6,drill=0.3 ...]
                 [--assign NAME=NET1,NET2 ...] [--pattern NAME=GLOB ...]
  board_setup.py --list

Why: kicad-cli cannot create or set up a board, and pcbnew's python does not expose the board stackup
(GetStackupDescriptor() returns an opaque object in KiCad 10.0.1). This writes:
- the board's (setup (stackup ...)) block from the table below (replacing an existing one), and the board thickness;
- .kicad_pro design rules: comfortable values for JLC's capabilities, not their minimums (--rules jlc), or untouched;
  the via minimums are JLC's no-extra-charge vias for the layer count (0.45 / 0.2 mm on 4+ layers, 0.4 / 0.3 on 2);
- .kicad_pro net classes: Default (0.2 mm track, 0.15 mm clearance, 0.6/0.3 mm via) plus any --class (keys track,
  clearance, via, drill), and net assignments by exact name (--assign) or wildcard pattern (--pattern, KiCad's
  netclass_patterns). A class clearance applies between that class's nets everywhere, IC pins included: a Power
  class at 0.2 mm makes DRC flag a 0.5 mm-pitch IC (VSSOP-8: 0.15 mm between pads) wherever two of its pins are
  power-class nets. Keep class clearances at the Default unless the voltage needs more, and widen tracks instead.
The board's copper layer count must match the stackup (make the board with new_board.py or KiCad first).

Numbers: 4-layer stackups from kicad-new-board/references/jlcpcb-stackups.md (jlcpcb.com/impedance, checked Oct 2026);
the 2-layer entry is derived (1.6 mm board less copper and mask), JLC publishes no 2-layer table. JLC changes these:
re-check the page before ordering and say that you did. Board-specific rules (a footprint-scoped clearance for a
fine-pitch part) belong in the project's .kicad_dru, written by hand with the reason in a comment.
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import Board, Project, stackup  # noqa: E402

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
    'min_through_hole_diameter': 0.2,      # multilayer; 1-2 layers: 0.3 (jlc_rules)
    'min_via_diameter': 0.45,              # JLC charges a hole < 0.3 mm unless the via is >= 0.45 mm on 4+ layers
    'min_via_annular_width': 0.075,
    'min_copper_edge_clearance': 0.3,      # JLC 0.2 mm for routed edges (0.4 for V-cut): margin added
    'min_hole_to_hole': 0.25,              # KiCad default; not in the JLC table we checked - verify
    'min_hole_clearance': 0.25,            # KiCad default
}



def jlc_rules(layers):
    """JLC_RULES for a board of this many copper layers. JLC's quote page (checked 2026-10-30): "Additional charges
    will apply when the via hole < 0.3mm and the via diameter <= 0.4mm ... For multi-layer boards, if the via diameter
    >= 0.45mm, the 0.2mm hole is also without an extra charge." So 0.45 / 0.2 is free on 4+ layers, and on 1-2 layers
    every hole under 0.3 mm is charged (0.4 / 0.3 is the small free via there). KiCad's board rules cannot say "via >=
    0.45 or hole >= 0.3": on 4+ layers they ask for 0.45 everywhere, so a free 0.4 / 0.3 via is flagged too (allow it
    in the project's .kicad_dru if you want it)."""
    r = dict(JLC_RULES)
    if layers <= 2:
        r.update(min_through_hole_diameter=0.3, min_via_diameter=0.4)
    return r


def via_sizes(layers):
    """the via size list (diameter, drill) offered in KiCad: the small one is JLC's free small via for the layer count"""
    small = {'diameter': 0.45, 'drill': 0.2 if layers > 2 else 0.3}
    return [{'diameter': 0.0, 'drill': 0.0}, {'diameter': 0.6, 'drill': 0.3}, {'diameter': 0.8, 'drill': 0.4}, small]


CLASS_BASE = {'bus_width': 12, 'diff_pair_gap': 0.25, 'diff_pair_via_gap': 0.25, 'diff_pair_width': 0.2,
              'line_style': 0, 'microvia_diameter': 0.3, 'microvia_drill': 0.1, 'pcb_color': 'rgba(0, 0, 0, 0.000)',
              'schematic_color': 'rgba(0, 0, 0, 0.000)', 'tuning_profile': '', 'wire_width': 6}
DEFAULT_CLASS = dict(track_width=0.2, clearance=0.15, via_diameter=0.6, via_drill=0.3)


# ------------------------------------------------------------------ stackup (built by kicad_sexpr)

def stackup_node(name, finish='None'):
    """The (stackup ...) node for a table entry. JLC gives no loss tangents: none are written."""
    entries = STACKUPS[name]
    copper = [e[1] for e in entries if e[0] == 'cu']
    dielectrics = [(e[0], e[1], e[2], e[3], None) for e in entries if e[0] != 'cu']
    return stackup(copper, dielectrics, mask_thickness=MASK['thickness'], mask_material='LPI', mask_er=MASK['er'],
                   finish=finish, mask_loss_tangent=None)


def thickness(name):
    return round(sum(e[1] for e in STACKUPS[name]) + 2 * MASK['thickness'], 4)


def copper_count(name):
    return sum(1 for e in STACKUPS[name] if e[0] == 'cu')


# ------------------------------------------------------------------ edits

def apply_stackup(board, name, finish):
    """Replace the board's stackup and thickness; refuses (exit) when the copper layer count differs."""
    have = len(board.copper_layers())
    if have != copper_count(name):
        sys.exit('board has %d copper layers, stackup %s has %d: change the board first' % (have, name, copper_count(name)))
    board.set_stackup(stackup_node(name, finish))
    board.set_thickness(thickness(name))
    return board


CLASS_KEYS = {'track': 'track_width', 'clearance': 'clearance', 'via': 'via_diameter', 'drill': 'via_drill'}


def parse_class(spec):
    """'Power:track=0.8,clearance=0.2' -> ('Power', {...}); SystemExit naming the valid keys on anything else"""
    name, _, kv = spec.partition(':')
    c = dict(DEFAULT_CLASS)
    for item in filter(None, kv.split(',')):
        k, _, v = item.partition('=')
        if k.strip() not in CLASS_KEYS:
            sys.exit('--class %s: unknown key "%s"; the keys are %s (mm), e.g. --class %s:track=0.8,clearance=0.2,via=0.6,'
                     'drill=0.3' % (spec, k.strip(), ', '.join(CLASS_KEYS), name or 'Power'))
        try:
            c[CLASS_KEYS[k.strip()]] = float(v)
        except ValueError:
            sys.exit('--class %s: "%s" needs a number in mm (%s=0.5)' % (spec, item, k.strip()))
    return name, c


def apply_project(project, rules, classes, assigns, patterns, layers=2):
    """project: a kicad_sexpr Project. Rules (for a board of `layers` copper layers; unknown: 2, the stricter), net
    classes (Default first, the user's other classes kept), assignments and patterns."""
    pro = project.data
    ds = project.design_settings()
    if rules == 'jlc':
        ds.setdefault('rules', {}).update(jlc_rules(layers))
        ds['track_widths'] = [0.0, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0]
        ds['via_dimensions'] = via_sizes(layers)
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
    for net, cls in assigns.items():
        project.assign(net, cls, replace=True)   # KiCad 10's list form: {"VBUS": ["Power"]}
    if patterns:
        ns['netclass_patterns'] = [p for p in ns.get('netclass_patterns') or [] if p['pattern'] not in dict(patterns)] + \
            [{'netclass': c, 'pattern': p} for p, c in patterns]
    return project


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
    project = Project.load(pro_path)
    known = {c['name'] for c in project.data.get('net_settings', {}).get('classes') or []} | {'Default'} | \
        {n for n, _ in classes}
    unknown = sorted(({c for c in assigns.values()} | {c for _, c in patterns}) - known)
    if unknown:
        sys.exit('net class %s is not defined: add --class %s:track=...,clearance=...' % (unknown, unknown[0]))
    if a.stackup:
        if a.stackup not in STACKUPS:
            sys.exit('unknown stackup %s; --list shows the table' % a.stackup)
        apply_stackup(Board.load(pcb_path), a.stackup, a.finish).save()      # may refuse before anything is written
        print('stackup %s (%.3f mm) written to %s' % (a.stackup, thickness(a.stackup), pcb_path))
    layers = copper_count(a.stackup) if a.stackup else len(Board.load(pcb_path).copper_layers()) if os.path.exists(pcb_path) else 2
    project = apply_project(project, a.rules, classes, assigns, patterns, layers)
    project.save()                            # KiCad's JSON layout: sorted keys, 2-space indent, final newline
    print('%s: rules %s (%d copper layers); classes %s; %d assignments, %d patterns' % (
        pro_path, a.rules, layers, [c['name'] for c in project.netclasses()], len(assigns), len(patterns)))


if __name__ == '__main__':
    main()
