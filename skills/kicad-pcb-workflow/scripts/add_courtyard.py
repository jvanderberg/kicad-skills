#!/usr/bin/env python3
"""Add a rectangular F.CrtYd courtyard to footprints that have none (imported footprints often ship without one).

  add_courtyard.py [--margin 0.25] [--dry-run] FILE.kicad_mod|LIB.pretty ...

Without a courtyard, DRC cannot report this part overlapping its neighbours: courtyards_overlap is silent, so a
placement can look DRC-clean while two parts sit on top of each other. The courtyard drawn here is the bounding box of
the pads and the body graphics (F.Fab and F.SilkS lines, rectangles, circles, arcs, polygons) plus --margin (default
0.25 mm; give connectors and parts you will rework more), rounded outward to 0.01 mm.
Footprints that already have anything on F.CrtYd are left alone. The file is rewritten by kicad_sexpr in KiCad's own
formatting (a file KiCad saved keeps every other line; a differently formatted one is reformatted, token for token). Check the result in a render next to the datasheet
outline: a part whose body overhangs its pads (connectors, inductors) needs the F.Fab body to be right first.
"""
import argparse, glob, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import Uuids, fp_rect, load, save  # noqa: E402


def _layers(n):
    return [str(v) for c in n.nodes() if c.head in ('layer', 'layers') for v in c[1:]]


def extent(fp):
    """Bounding box (x0, y0, x1, y1) of the pads and the F.Fab / F.SilkS graphics of a footprint node, or None."""
    xs, ys = [], []
    for p in fp.nodes('pad'):
        at, size = p.find('at'), p.find('size')
        if at is None or size is None:
            continue
        x, y, rot = at.number(1), at.number(2), at.number(3, 0.0)
        w, h = size.number(1), size.number(2)
        r = math.radians(rot)
        hw = abs(w / 2 * math.cos(r)) + abs(h / 2 * math.sin(r))
        hh = abs(w / 2 * math.sin(r)) + abs(h / 2 * math.cos(r))
        xs += [x - hw, x + hw]; ys += [y - hh, y + hh]
    for g in fp.nodes():
        if g.head not in ('fp_line', 'fp_rect', 'fp_arc', 'fp_circle', 'fp_poly') or \
                not set(_layers(g)) & {'F.Fab', 'F.SilkS'}:
            continue
        pts = [(n.number(1), n.number(2)) for n in g.walk() if n.head in ('start', 'end', 'mid', 'center', 'xy')]
        if g.head == 'fp_circle' and len(pts) == 2:            # (center) (end): end is a point on the circle
            (cx, cy), (ex, ey) = pts
            rr = math.dist((cx, cy), (ex, ey))
            pts = [(cx - rr, cy - rr), (cx + rr, cy + rr)]
        for x, y in pts:
            xs.append(x); ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def process(path, margin, dry):
    fp = load(path)
    if any('F.CrtYd' in _layers(n) for n in fp.walk()):
        return 'has courtyard  %s' % os.path.basename(path)
    e = extent(fp)
    if not e:
        return 'NO GEOMETRY    %s (left alone)' % os.path.basename(path)
    x0, y0 = math.floor((e[0] - margin) * 100) / 100, math.floor((e[1] - margin) * 100) / 100
    x1, y1 = math.ceil((e[2] + margin) * 100) / 100, math.ceil((e[3] + margin) * 100) / 100
    if fp.find('pad') is None:
        return 'NO PADS        %s (left alone)' % os.path.basename(path)
    if not dry:
        u = Uuids(seed='kicad_mod:%s' % fp[1])          # derived id: re-running gives the same file
        u.scan(fp)
        fp.insert_before('pad', fp_rect((x0, y0), (x1, y1), 'F.CrtYd', width=0.05, uuids=u))
        save(fp, path)
    return '%s %6.2f x %-6.2f %s' % ('would add' if dry else 'added    ', x1 - x0, y1 - y0, os.path.basename(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--margin', type=float, default=0.25)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    files = []
    for p in a.paths:
        files += sorted(glob.glob(os.path.join(p, '*.kicad_mod'))) if os.path.isdir(p) else [p]
    for f in files:
        print(process(f, a.margin, a.dry_run))


if __name__ == '__main__':
    main()
