#!/usr/bin/env python3
"""Add a rectangular F.CrtYd courtyard to footprints that have none (imported footprints often ship without one).

  add_courtyard.py [--margin 0.25] [--dry-run] FILE.kicad_mod|LIB.pretty ...

Without a courtyard, DRC cannot report this part overlapping its neighbours: courtyards_overlap is silent, so a
placement can look DRC-clean while two parts sit on top of each other. The courtyard drawn here is the bounding box of
the pads and the body graphics (F.Fab and F.SilkS lines, rectangles, circles, arcs, polygons) plus --margin (default
0.25 mm; give connectors and parts you will rework more), rounded outward to 0.01 mm.
Footprints that already have any F.CrtYd graphic are left alone. Check the result in a render next to the datasheet
outline: a part whose body overhangs its pads (connectors, inductors) needs the F.Fab body to be right first.
"""
import argparse, glob, math, os, re, uuid


def courtyard_sexpr(x0, y0, x1, y1, indent):
    i = indent
    return ('{i}(fp_rect\n{i}\t(start {x0} {y0})\n{i}\t(end {x1} {y1})\n{i}\t(stroke\n{i}\t\t(width 0.05)\n'
            '{i}\t\t(type solid)\n{i}\t)\n{i}\t(fill no)\n{i}\t(layer "F.CrtYd")\n{i}\t(uuid "{u}")\n{i})\n').format(
        i=i, x0=x0, y0=y0, x1=x1, y1=y1, u=uuid.uuid4())


def extent(t):
    xs, ys = [], []
    for m in re.finditer(r'\(pad\s+"[^"]*"\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)\s*'
                         r'(?:\(locked[^)]*\)\s*)?\(size\s+([\d.]+)\s+([\d.]+)\)', t):
        x, y, rot, w, h = float(m.group(1)), float(m.group(2)), float(m.group(3) or 0), float(m.group(4)), float(m.group(5))
        r = math.radians(rot)
        hw = abs(w / 2 * math.cos(r)) + abs(h / 2 * math.sin(r))
        hh = abs(w / 2 * math.sin(r)) + abs(h / 2 * math.cos(r))
        xs += [x - hw, x + hw]; ys += [y - hh, y + hh]
    for m in re.finditer(r'\(fp_(line|rect|arc|circle|poly)(.*?)\(layer "F\.(?:Fab|SilkS)"\)', t, re.S):
        kind, body = m.group(1), m.group(2)
        pts = [(float(a), float(b)) for a, b in re.findall(r'\((?:start|end|mid|center|xy)\s+([-\d.]+)\s+([-\d.]+)\)', body)]
        if kind == 'circle' and len(pts) == 2:            # (center) (end): end is a point on the circle
            (cx, cy), (ex, ey) = pts
            rr = math.dist((cx, cy), (ex, ey))
            pts = [(cx - rr, cy - rr), (cx + rr, cy + rr)]
        for x, y in pts:
            xs.append(x); ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def process(path, margin, dry):
    t = open(path, encoding='utf-8').read()
    if 'F.CrtYd' in t:
        return 'has courtyard  %s' % os.path.basename(path)
    e = extent(t)
    if not e:
        return 'NO GEOMETRY    %s (left alone)' % os.path.basename(path)
    x0, y0 = math.floor((e[0] - margin) * 100) / 100, math.floor((e[1] - margin) * 100) / 100
    x1, y1 = math.ceil((e[2] + margin) * 100) / 100, math.ceil((e[3] + margin) * 100) / 100
    m = re.search(r'\n([ \t]*)\(pad ', t)                 # tab-indented (KiCad) or space-indented files
    if not m:
        return 'NO PADS        %s (left alone)' % os.path.basename(path)
    if not dry:
        i = m.start() + 1
        t = t[:i] + courtyard_sexpr(x0, y0, x1, y1, m.group(1)) + t[i:]
        open(path, 'w', encoding='utf-8').write(t)
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
