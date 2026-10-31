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
layer's silk extent. Kept: text, marks (a circle or a filled shape under 1 mm both ways, such as a pin-1 dot:
outline_rules.py, the rule board_lint.py uses) and drawing inside the outline (a diode symbol, a cathode bar). When the
outline itself carried the polarity (a chamfered corner, a cathode bar drawn as one of its sides) nothing marks it any
more: the script says when nothing is left, and a polarised part then needs a dot added by its pin 1 / cathode. Look at
the result in a render.
Added: a hidden property "Silk outline" = "removed by strip_outline.py" (outline_rules.REMOVED). It goes onto the board
with the footprint, and board_lint.py then checks the part by its body and pads and lists it as spaced by rule of
thumb, whatever inner drawing it kept.
Refused (nothing written): an output that is one of the input files (the destination is the source library, also
under another spelling on a case-insensitive disk, or through a link), and two inputs with the same file name.
"""
import argparse, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import Node, Uuids, load, save  # noqa: E402
from kicad_sexpr.common import font_effects  # noqa: E402
from outline_rules import REMOVED, is_mark as _is_mark  # noqa: E402

SHAPES = ('fp_line', 'fp_arc', 'fp_rect', 'fp_poly', 'fp_circle')
SILK = {'F.SilkS', 'B.SilkS'}


def _layer(n):
    lay = n.find('layer')
    return str(lay[1]) if lay is not None else None


def _width(n):
    s = n.find('stroke')
    w = s.find('width') if s is not None else n.find('width')
    return w.number(1) if w is not None else 0.0


def is_mark(g):
    """a pin-1 dot or similar (outline_rules.is_mark): a circle, or a filled shape, smaller than MARK both ways (stroke
    included)"""
    fill = g.find('fill')
    filled = fill is not None and str(fill[1]) in ('solid', 'yes')
    pts = _points(g)
    if not pts:
        return False
    w = _width(g)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return _is_mark('circle' if g.head == 'fp_circle' else g.head[3:], filled, max(xs) - min(xs) + w, max(ys) - min(ys) + w)


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


def mark_removed(fp):
    """add the hidden REMOVED property (after the last property, laid out as the footprint's own are); idempotent"""
    props = fp.nodes('property')
    if any(str(p[1]) == REMOVED[0] for p in props):
        return
    n = Node('property', REMOVED[0], REMOVED[1], Node('at', 0, 0, 0), Node('layer', 'F.Fab'), Node('hide', True))
    if any(p.find('uuid') is not None for p in props):       # JLCImport writes uuids; KiCad's own libraries do not
        u = Uuids(seed='kicad_mod:' + str(fp[1]))
        u.scan(fp)
        n.append(Node('uuid', u.new('property:' + REMOVED[0])))
    n.append(font_effects(1, 0.15))
    if props:
        fp.insert(fp.index(props[-1]) + 1, n)
    else:
        fp.insert_before('attr', n)


def strip(path, out, dry):
    fp = load(path)
    drop, marks = outline(fp)
    if not dry:
        for g in drop:
            fp.remove_node(g)
        mark_removed(fp)
        save(fp, out)
    msg = '%s %s: %d outline shape(s) removed, %d mark(s) / inner shape(s) kept' % ('would write' if dry else 'wrote', out, len(drop), len(marks))
    if not drop:
        msg += ' - it had no outline to remove'
    elif not marks:
        msg += ' - NOTHING LEFT TO MARK IT: if the part is polarised, add a dot by pin 1 / the cathode and check a render'
    return msg


def same_file(a, b):
    """a and b name the same file: by identity when both exist (a case-insensitive disk, links), else by resolved path.
    A path that does not exist cannot be an existing file under another spelling either."""
    if os.path.exists(a) and os.path.exists(b):
        return os.path.samefile(a, b)
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def plan(files, dest):
    """[(input, output)], or exit (before anything is written) when an output would overwrite an input or two inputs
    would write the same output"""
    for f in files:
        if not os.path.isfile(f):
            sys.exit('%s: no such footprint file' % f)
    pairs, seen = [], {}
    for f in files:
        if any(same_file(f, g) for g, _ in pairs):
            continue                                            # the same file named twice
        name = os.path.basename(f)
        if name.lower() in seen:                                # lower: one file on a case-insensitive disk
            sys.exit('%s and %s would both be written to %s: copy them into separate libraries (one run each)'
                     % (seen[name.lower()], f, os.path.join(dest, name)))
        seen[name.lower()] = f
        pairs.append((f, os.path.join(dest, name)))
    for f, _ in pairs:
        if same_file(os.path.dirname(os.path.abspath(f)), dest):
            sys.exit('%s is already in %s: copy into a separate library (the original stays for parts at full spacing)'
                     % (f, dest))
    for _, out in pairs:
        for f, _ in pairs:
            if same_file(out, f):
                sys.exit('%s is the input file %s: copy into a separate library (the original stays for parts at full '
                         'spacing)' % (out, f))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--to', required=True, help='destination .pretty library (created if missing)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    dest = os.path.abspath(a.to)
    if not dest.endswith('.pretty'):
        sys.exit('--to must be a .pretty library folder')
    pairs = plan(a.files, dest)
    if not a.dry_run:
        os.makedirs(dest, exist_ok=True)
    for f, out in pairs:
        print(strip(f, out, a.dry_run))


if __name__ == '__main__':
    main()
