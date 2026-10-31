#!/usr/bin/env python3
"""Copy footprints into another library with their silkscreen outline removed, for parts placed tighter than their
outline on purpose (layout-rules.md "Placement and mechanical").

  strip_outline.py FILE.kicad_mod [...] --to PROJECT/NoOutline.pretty [--dry-run]

An EasyEDA footprint has no courtyard, so its silk outline is its placement boundary (board_lint.py SILK OUTLINE).
Where a part has to sit closer than that (a decoupling capacitor at its pin), it gets a copy of its footprint without
the outline, and is then spaced by the rules of thumb instead. The copy keeps the file and footprint name, pads, origin
and everything else: JLCImport's production export recognises JLC's own footprint by its name (the part after the
library nickname), and JLC places by the pads, origin and rotation, so only the library nickname changes. Register the
library once (`libtable.py add PROJECT fp NoOutline NoOutline.pretty`) and set the tightened parts' Footprint field to
`NoOutline:<name>`; parts left at full spacing keep the original.
Removed, per silk layer: the outline - every line, arc, rectangle, polygon or circle that reaches the edge of the
layer's silk extent. Kept: text, marks (a circle or a filled shape under 1 mm both ways, such as a pin-1 dot: the rule
board_lint.py uses) and drawing inside the outline (a diode symbol, a cathode bar). When the outline itself carried the
polarity (a chamfered corner, a cathode bar drawn as one of its sides) nothing marks it any more: the script says when
nothing is left, and a polarised part then needs a dot added by its pin 1 / cathode. Look at the result in a render.
"""
import argparse, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import load, save  # noqa: E402

SHAPES = ('fp_line', 'fp_arc', 'fp_rect', 'fp_poly', 'fp_circle')
SILK = {'F.SilkS', 'B.SilkS'}
MARK = 1.0                                       # board_lint.py MARK


def _layer(n):
    lay = n.find('layer')
    return str(lay[1]) if lay is not None else None


def _width(n):
    s = n.find('stroke')
    w = s.find('width') if s is not None else n.find('width')
    return w.number(1) if w is not None else 0.0


def is_mark(g):
    """a pin-1 dot or similar: a circle, or a filled shape, smaller than MARK both ways (stroke included)"""
    fill = g.find('fill')
    filled = fill is not None and str(fill[1]) in ('solid', 'yes')
    if g.head != 'fp_circle' and not filled:
        return False
    pts = [(n.number(1), n.number(2)) for n in g.walk() if n.head in ('start', 'end', 'mid', 'center', 'xy')]
    if not pts:
        return False
    if g.head == 'fp_circle' and g.find('center') is not None:
        c, e = g.need('center'), g.need('end')
        size = 2 * math.dist((c.number(1), c.number(2)), (e.number(1), e.number(2)))
        return size + _width(g) < MARK
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(xs) - min(xs) + _width(g) < MARK and max(ys) - min(ys) + _width(g) < MARK


def _points(g):
    if g.head == 'fp_circle' and g.find('center') is not None:
        c, e = g.need('center'), g.need('end')
        cx, cy = c.number(1), c.number(2)
        r = math.dist((cx, cy), (e.number(1), e.number(2)))
        return [(cx - r, cy), (cx + r, cy), (cx, cy - r), (cx, cy + r)]
    return [(n.number(1), n.number(2)) for n in g.walk() if n.head in ('start', 'end', 'mid', 'center', 'xy')]


def outline(fp):
    """(outline shapes, shapes kept) on the silk layers: a non-mark shape with a point on the edge of its layer's silk
    extent (within half its stroke and 0.02 mm) is outline"""
    drop, keep = [], []
    for layer in SILK:
        gs = [g for g in fp.nodes() if g.head in SHAPES and _layer(g) == layer]
        body = [g for g in gs if not is_mark(g)]
        keep += [g for g in gs if is_mark(g)]
        pts = [p for g in body for p in _points(g)]
        if not pts:
            continue
        x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
        x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
        for g in body:
            tol = _width(g) / 2 + 0.02
            edge = any(min(abs(x - x0), abs(x - x1), abs(y - y0), abs(y - y1)) <= tol for x, y in _points(g))
            (drop if edge else keep).append(g)
    return drop, keep


def strip(path, dest, dry):
    fp = load(path)
    drop, marks = outline(fp)
    out = os.path.join(dest, os.path.basename(path))
    if not dry:
        for g in drop:
            fp.remove_node(g)
        save(fp, out)
    msg = '%s %s: %d outline shape(s) removed, %d mark(s) / inner shape(s) kept' % ('would write' if dry else 'wrote', out, len(drop), len(marks))
    if not drop:
        msg += ' - it had no outline to remove'
    elif not marks:
        msg += ' - NOTHING LEFT TO MARK IT: if the part is polarised, add a dot by pin 1 / the cathode and check a render'
    return msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--to', required=True, help='destination .pretty library (created if missing)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    dest = os.path.abspath(a.to)
    if not dest.endswith('.pretty'):
        sys.exit('--to must be a .pretty library folder')
    for f in a.files:
        if os.path.abspath(os.path.dirname(f)) == dest:
            sys.exit('%s is already in %s: copy into a separate library (the original stays for parts at full spacing)'
                     % (f, dest))
    if not a.dry_run:
        os.makedirs(dest, exist_ok=True)
    for f in a.files:
        print(strip(f, dest, a.dry_run))


if __name__ == '__main__':
    main()
