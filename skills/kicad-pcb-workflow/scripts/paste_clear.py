#!/usr/bin/env python3
"""Derive a footprint whose paste windows clear every drilled hole (thermal vias in an exposed pad), optionally with
larger via drills.

  paste_clear.py SRC OUT.kicad_mod [--drill 0.3] [--margin 0.05]
    SRC: a .kicad_mod file, LIB.pretty:NAME, or a KiCad library name (Package_DFN_QFN:QFN-24-..._ThermalVias)

KiCad's own *_ThermalVias footprints fail board_lint.py's PASTE ON HOLE as shipped: QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm
_ThermalVias has four 1.17 mm paste windows at +-0.675 mm that cover its corner drills at +-1.1 mm, and reflow pulls
that paste down the barrels. Their 0.2 mm drills in 0.5 mm pads are free at JLC on 4+ layers but charged on 2 (a hole
under 0.3 mm is free only on a multilayer board with a via of 0.45 mm or more: kicad-new-board
references/jlcpcb-stackups.md); --drill 0.3 enlarges every plated drill smaller than that, for a 2-layer board.

Each paste-only window (a pad on F.Paste / B.Paste and no copper, rect or roundrect) that comes within --margin of a
drill is cut to the largest of the four rectangles beside that hole (left, right, above, below), repeated until it
clears every hole; a window left smaller than 0.2 mm is removed. The footprint is renamed to OUT's file name and the
paste coverage of each exposed pad is printed (typically 40-60 %; fewer, larger vias leave more room). Pads whose own
paste covers a drill, and windows of other shapes, are listed and left alone (exit 1). Then point the symbol at the
new footprint in the project library and re-run board_lint.py: no PASTE ON HOLE, and the coverage NOTE.
"""
import argparse, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fpcheck import resolve  # noqa: E402
from kicad_sexpr import load, save  # noqa: E402

MIN_SIDE = 0.2


def _layers(p):
    lay = p.find('layers')
    return [str(v) for v in lay[1:]] if lay is not None else []


def _rect(p):
    """(x0, y0, x1, y1) of an axis-aligned pad, or None if it is rotated off 90 degrees"""
    at, size = p.need('at'), p.need('size')
    x, y, rot = at.number(1), at.number(2), at.number(3, 0.0)
    w, h = size.number(1), size.number(2)
    if rot % 90:
        return None
    if rot % 180:
        w, h = h, w
    return (x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def _drill(d):
    """the largest dimension of a (drill D) / (drill oval W H) node, or 0"""
    vals = []
    for a in d.atoms():
        try:
            vals.append(float(a))
        except ValueError:
            pass
    return max(vals or [0.0])


def _dist(c, r):
    """distance from point c to rectangle r (0 inside)"""
    dx = max(r[0] - c[0], 0, c[0] - r[2])
    dy = max(r[1] - c[1], 0, c[1] - r[3])
    return math.hypot(dx, dy)


def _area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


def cut(r, holes, memo=None):
    """the largest rectangle inside r that clears every hole (x, y, keep-out radius), cutting beside one hole at a time
    (left, right, above or below it); None when too little is left"""
    memo = {} if memo is None else memo
    key = tuple(round(v, 6) for v in r)
    if key in memo:
        return memo[key]
    hit = next(((x, y, k) for x, y, k in holes if _dist((x, y), r) < k - 1e-9), None)
    best = r
    if hit is not None:
        x, y, k = hit
        best = None
        for s in ((r[0], r[1], x - k, r[3]), (x + k, r[1], r[2], r[3]), (r[0], r[1], r[2], y - k), (r[0], y + k, r[2], r[3])):
            if s[2] - s[0] >= MIN_SIDE and s[3] - s[1] >= MIN_SIDE:
                f = cut(s, holes, memo)
                if f is not None and (best is None or _area(f) > _area(best) + 1e-9):
                    best = f
    memo[key] = best
    return best


def _set_rect(p, r):
    at, size = p.need('at'), p.need('size')
    rot = at.number(3, 0.0)
    w, h = r[2] - r[0], r[3] - r[1]
    if rot % 180:
        w, h = h, w
    at[1], at[2] = round((r[0] + r[2]) / 2, 4), round((r[1] + r[3]) / 2, 4)
    size[1], size[2] = round(w, 4), round(h, 4)


def derive(fp, drill=None, margin=0.05):
    """Change the footprint node in place. Returns (report lines, problems)."""
    out, probs = [], []
    if drill:
        for p in fp.nodes('pad'):
            d = p.find('drill')
            if str(p[2]) == 'thru_hole' and d is not None and len(d.atoms()) == 1 and 0 < _drill(d) < drill:
                d[1] = drill
                size = p.need('size')
                if size.number(1) < drill + 0.15 or size.number(2) < drill + 0.15:
                    size[1] = size[2] = round(drill + 0.15, 4)
                out.append('pad %s at (%g, %g): drill -> %g mm' % (p[1], p.need('at').number(1), p.need('at').number(2), drill))
    holes = []
    for p in fp.nodes('pad'):
        d = p.find('drill')
        if d is not None and _drill(d) > 0:
            holes.append((p.need('at').number(1), p.need('at').number(2), _drill(d) / 2 + margin))
    for p in list(fp.nodes('pad')):
        lay = _layers(p)
        paste = [L for L in lay if L.endswith('.Paste')]
        if not paste:
            continue
        r = _rect(p)
        own = r is not None and any(_dist((x, y), r) < k - 1e-9 for x, y, k in holes)
        if any(L.endswith('.Cu') for L in lay):
            # a copper pad's own paste: reported where it overlaps a drill (no margin, as board_lint measures it)
            if r is not None and str(p[2]) != 'thru_hole' and any(_dist((x, y), r) < k - margin for x, y, k in holes):
                probs.append('pad %s: its own paste covers a drill - not changed (give it paste-only windows)' % p[1])
            continue
        if r is None or str(p[3]) not in ('rect', 'roundrect'):
            if own or r is None:
                probs.append('paste window at (%g, %g): %s shape, not changed' % (
                    p.need('at').number(1), p.need('at').number(2), str(p[3]) if r is not None else 'rotated'))
            continue
        if not own:
            continue
        n = cut(r, holes)
        if n is None:
            fp.remove_node(p)
            out.append('paste window %.3f x %.3f at (%g, %g): removed (no room beside the drills)' % (
                r[2] - r[0], r[3] - r[1], (r[0] + r[2]) / 2, (r[1] + r[3]) / 2))
            continue
        _set_rect(p, n)
        out.append('paste window %.3f x %.3f at (%.3f, %.3f) -> %.3f x %.3f at (%.3f, %.3f)' % (
            r[2] - r[0], r[3] - r[1], (r[0] + r[2]) / 2, (r[1] + r[3]) / 2,
            n[2] - n[0], n[3] - n[1], (n[0] + n[2]) / 2, (n[1] + n[3]) / 2))
    # coverage of each side's exposed pad that has holes in it: the paste-only windows inside it over its area
    for side in ('F', 'B'):
        windows = [_rect(p) for p in fp.nodes('pad') if side + '.Paste' in _layers(p) and not any(L.endswith('.Cu') for L in _layers(p))]
        cu = {}
        for p in fp.nodes('pad'):
            r = _rect(p)
            if str(p[2]) == 'smd' and r and side + '.Cu' in _layers(p) and any(_dist((x, y), r) == 0 for x, y, _ in holes):
                cu.setdefault(str(p[1]), []).append(r)
        for num, rs in sorted(cu.items()):
            inside = [w for w in windows if w and any(r[0] <= (w[0] + w[2]) / 2 <= r[2] and r[1] <= (w[1] + w[3]) / 2 <= r[3] for r in rs)]
            if not inside:
                continue
            area, pa = sum(_area(r) for r in rs), sum(_area(w) for w in inside)
            out.append('exposed pad %s (%s side): paste coverage %.0f %% (%.2f of %.2f mm^2; typically 40-60 %%), %d hole(s)' % (
                num, side, 100 * pa / area, pa, area, sum(1 for x, y, _ in holes if any(_dist((x, y), r) == 0 for r in rs))))
    return out, probs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--drill', type=float, help='enlarge plated drills smaller than this (mm), e.g. 0.3')
    ap.add_argument('--margin', type=float, default=0.05, help='paste to drill-edge gap (mm)')
    a = ap.parse_args()
    src = resolve(a.src)
    fp = load(src)
    name = os.path.splitext(os.path.basename(a.out))[0]
    fp[1] = name
    lines, probs = derive(fp, a.drill, a.margin)
    for prop in fp.nodes('property'):
        if str(prop[1]) == 'Description':
            prop[2] = '%s (derived from %s: paste windows clear of the drills%s)' % (
                str(prop[2]), os.path.basename(src)[:-len('.kicad_mod')], ', %g mm drills' % a.drill if a.drill else '')
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    save(fp, a.out)
    for line in lines:
        print('  ' + line)
    for line in probs:
        print('  PROBLEM ' + line)
    print('wrote %s (%s)' % (a.out, name))
    sys.exit(1 if probs else 0)


if __name__ == '__main__':
    main()
