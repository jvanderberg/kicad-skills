#!/usr/bin/env python3
"""Add a rectangular F.CrtYd courtyard to footprints that have none (most EasyEDA footprints, as JLCImport imports
them, have none).

  add_courtyard.py [--class CLASS | --margin MM] [--dry-run] FILE.kicad_mod|LIB.pretty|PROJECT_DIR ...

Without a courtyard, DRC cannot report this part overlapping its neighbours: courtyards_overlap is silent, so a
placement can look DRC-clean while two parts sit on top of each other. A PROJECT_DIR (the folder of a .kicad_pro)
means every library its fp-lib-table keeps inside the project (`${KIPRJMOD}/...`, e.g. JLCImport.pretty).

The courtyard is the rectangle around the pads and the part body, plus a clearance chosen per footprint, rounded
outward to KiCad's 0.01 mm courtyard grid. The clearances are IPC's nominal courtyard excess (density level B) as
KiCad's KLC F5.3 applies it (kicad-pcb-workflow references/new-design.md s5 has the sources):
  small    0.15 mm  body no longer than 1.5 mm (0402 and smaller chips)  IPC-7351B chips < 0603; KLC F5.3 item 5
  default  0.25 mm  every other SMD and through-hole part                 IPC-7351B tables 3-2..3-4, 3-15; KLC item 5
  wide     0.5 mm   connectors, crystals and oscillators, canned          KLC F5.3 items 7-9; IPC-7351B table 3-20
                    capacitors, parts you expect to rework (--class)
  bga      1.0 mm   BGA, WLCSP, DSBGA (letter-number ball pads)           IPC-7352 table 3-11; KLC F5.3 item 10
A connector's courtyard holds the part only: leave the mating plug's room around it as well. --class forces a class
for every footprint given; --margin forces a number (e.g. 0.5 for a BGA on a dense board, IPC's least density).

The body is, in this order: the F.Fab outline (KiCad-style footprints); the size in the EasyEDA package name that
JLCImport writes into descr / tags (`..._L2.9-W1.3-...`, `CAP-SMD_BD5.0-...`, a chip code such as R0402), centred
on the silkscreen; else the F.SilkS graphics. Footprints that already have anything on F.CrtYd are left alone. The
file is rewritten by kicad_sexpr in KiCad's own formatting (a file KiCad saved keeps every other line; a differently
formatted one is reformatted, token for token). Check the result in a render next to the datasheet outline
(`kicad-cli fp export svg`): a part whose body overhangs its pads in a way neither the name nor the silk shows
(a right-angle connector's shell, a board-edge part) needs its body added by hand first.
"""
import argparse, glob, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import Uuids, fp_rect, load, save  # noqa: E402

MARGIN = {'small': 0.15, 'default': 0.25, 'wide': 0.5, 'bga': 1.0}
SMALL_BODY = 1.5            # KLC F5.3: 0.15 mm "for parts smaller than 1.5mm"
SMALL_PADS = 1.6            # no body known: a pad span this short is an 0402-size part (KiCad's R_0402 spans 1.56)

# EasyEDA package names (the first word of the name): what they are
BGA = re.compile(r'^(BGA|[A-Z]{1,3}BGA|WLCSP|[A-Z]?CSP)\b|^[A-Z]*BGA-', re.I)
CONNECTOR = re.compile(r'^(CONN|USB|MICRO-?USB|MINI-?USB|HDR|HEADER|PIN-?HEADER|BOX-?HEADER|FPC|FFC|IDC|WAFER|'
                       r'TERMINAL|SCREW|KF\d|DC-?(IN|JACK)|RJ\d|SIM|TF-|MICRO-?SD|SD-|AUDIO|PJ-|IPEX|U\.?FL|BTB|'
                       r'BATTERY|BAT-|HOLDER)', re.I)
CRYSTAL = re.compile(r'^(CRYSTAL|XTAL|OSC|TCXO|VCXO|HC-?49)', re.I)
CANNED = re.compile(r'^CAP-(SMD|TH)_BD', re.I)
LW = re.compile(r'(?:^|[_-])L(\d+(?:\.\d+)?)-W(\d+(?:\.\d+)?)(?:[_-]|$)')
BD = re.compile(r'(?:^|[_-])BD(\d+(?:\.\d+)?)(?:[_-]|$)')
# EIA chip codes (inch) -> nominal body length x width in mm
CHIP = {'01005': (0.4, 0.2), '0201': (0.6, 0.3), '0402': (1.0, 0.5), '0603': (1.6, 0.8), '0805': (2.0, 1.25),
        '1206': (3.2, 1.6), '1210': (3.2, 2.5), '1812': (4.5, 3.2), '2010': (5.0, 2.5), '2512': (6.4, 3.2)}
CHIP_NAME = re.compile(r'^(?:R|C|L|F|D|FB|LED)?(%s)(?:[-_].*)?$' % '|'.join(CHIP), re.I)
BALL = re.compile(r'^[A-Z]{1,2}\d{1,2}$')


def _layers(n):
    return [str(v) for c in n.nodes() if c.head in ('layer', 'layers') for v in c[1:]]


def _bbox(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def pad_boxes(fp):
    """[(number, shape, (x0, y0, x1, y1))] for every pad with a position and size"""
    out = []
    for p in fp.nodes('pad'):
        at, size = p.find('at'), p.find('size')
        if at is None or size is None:
            continue
        x, y, rot = at.number(1), at.number(2), at.number(3, 0.0)
        w, h = size.number(1), size.number(2)
        r = math.radians(rot)
        hw = abs(w / 2 * math.cos(r)) + abs(h / 2 * math.sin(r))
        hh = abs(w / 2 * math.sin(r)) + abs(h / 2 * math.cos(r))
        out.append((str(p[1]), str(p[3]) if len(p) > 3 else '', (x - hw, y - hh, x + hw, y + hh)))
    return out


def graphics_box(fp, layers, outlines=False):
    """Bounding box of the lines, rectangles, circles, arcs and polygons on `layers`, or None. outlines: unfilled
    items only (EasyEDA's F.Fab holds filled polarity marks and pin-1 dots, not a body)."""
    xs, ys = [], []
    for g in fp.nodes():
        if g.head not in ('fp_line', 'fp_rect', 'fp_arc', 'fp_circle', 'fp_poly') or not set(_layers(g)) & set(layers):
            continue
        if outlines and str(g.get('fill', 'no')) in ('solid', 'yes'):
            continue
        pts = [(n.number(1), n.number(2)) for n in g.walk() if n.head in ('start', 'end', 'mid', 'center', 'xy')]
        if g.head == 'fp_circle' and len(pts) == 2:            # (center) (end): end is a point on the circle
            (cx, cy), (ex, ey) = pts
            rr = math.dist((cx, cy), (ex, ey))
            pts = [(cx - rr, cy - rr), (cx + rr, cy + rr)]
        for x, y in pts:
            xs.append(x); ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def package_names(fp):
    """The words of the footprint's name, descr and tags, minus its LCSC number (EasyEDA package names are in there)"""
    lcsc = {str(p[2]) for p in fp.nodes('property') if len(p) > 2 and str(p[1]) == 'LCSC'}
    words = [str(fp[1])] + [w for h in ('descr', 'tags') for w in re.split(r'[\s;]+', str(fp.get(h, '')))]
    return [w for w in words if w and w not in lcsc]


def name_body(names):
    """(length, width, the word it came from) from an EasyEDA package name, or None"""
    for w in names:
        m, d = LW.search(w), BD.search(w)
        if m or d:
            sizes = [float(v) for v in m.groups()] if m else [float(d.group(1))] * 2
            return max(sizes), min(sizes), w
    for w in names:
        m = CHIP_NAME.match(w)
        if m:
            return CHIP[m.group(1)] + (w,)
    return None


def body(fp, pads):
    """((x0, y0, x1, y1), source) of the part body, or (None, None)"""
    fab = graphics_box(fp, ['F.Fab'], outlines=True)
    if fab and min(fab[2] - fab[0], fab[3] - fab[1]) > 0.5:             # an outline, not a pin-1 mark
        return fab, 'F.Fab'
    silk = graphics_box(fp, ['F.SilkS'])
    nb = name_body(package_names(fp))
    if nb:
        ref = silk or _bbox([b for _, _, b in pads])
        cx, cy = (ref[0] + ref[2]) / 2, (ref[1] + ref[3]) / 2
        L, W, word = nb
        if ref[3] - ref[1] > ref[2] - ref[0]:                          # long side along the silk's (or pads') long side
            L, W = W, L
        return (cx - L / 2, cy - W / 2, cx + L / 2, cy + W / 2), word
    return (silk, 'F.SilkS') if silk else (None, None)


def classify(fp, pads, bbox):
    """(class, why) for the courtyard clearance"""
    names = package_names(fp)
    first = [w.split('_')[0] for w in names]
    numbered = [n for n, _, _ in pads if n]
    if any(BGA.search(w) for w in names) or (
            len(numbered) >= 4 and sum(bool(BALL.match(n)) for n in numbered) >= 0.75 * len(numbered)
            and all(s in ('circle', 'oval') and abs((b[2] - b[0]) - (b[3] - b[1])) < 0.01 for _, s, b in pads)):
        return 'bga', 'ball grid'
    for rx, what in ((CONNECTOR, 'connector'), (CRYSTAL, 'crystal'), (CANNED, 'canned capacitor')):
        hit = next((w for w, f in zip(names, first) if rx.search(f) or rx.search(w)), None)
        if hit:
            return 'wide', '%s (%s)' % (what, hit)
    b, src = bbox
    if b and src != 'F.SilkS':
        if max(b[2] - b[0], b[3] - b[1]) <= SMALL_BODY + 1e-6:
            return 'small', '%.2f x %.2f, no longer than %.1f mm' % (b[2] - b[0], b[3] - b[1], SMALL_BODY)
    else:
        p = _bbox([x for _, _, x in pads])
        if len(pads) <= 3 and max(p[2] - p[0], p[3] - p[1]) <= SMALL_PADS:
            return 'small', 'pads span %.2f x %.2f' % (p[2] - p[0], p[3] - p[1])
    return 'default', ''


def process(path, dry, cls=None, margin=None):
    fp = load(path)
    name = os.path.basename(path)
    if any('F.CrtYd' in _layers(n) for n in fp.walk()):
        return 'has courtyard  %s' % name
    pads = pad_boxes(fp)
    if not pads:
        return 'NO PADS        %s (left alone)' % name
    bb = body(fp, pads)
    e = _bbox([b for _, _, b in pads] + [bb[0]])
    k, why = classify(fp, pads, bb)
    if cls:
        k, why = cls, 'forced'
    m = MARGIN[k] if margin is None else margin
    x0, y0 = math.floor(round((e[0] - m) * 100, 6)) / 100, math.floor(round((e[1] - m) * 100, 6)) / 100
    x1, y1 = math.ceil(round((e[2] + m) * 100, 6)) / 100, math.ceil(round((e[3] + m) * 100, 6)) / 100
    if not dry:
        u = Uuids(seed='kicad_mod:%s' % fp[1])          # derived id: re-running gives the same file
        u.scan(fp)
        fp.insert_before('pad', fp_rect((x0, y0), (x1, y1), 'F.CrtYd', width=0.05, uuids=u))
        save(fp, path)
    body_s = 'body %s' % (bb[1] if bb[1] else 'unknown: pads only')
    return '%s %6.2f x %-6.2f %-7s %.2f mm  %-34s %s%s' % (
        'would add' if dry else 'added    ', x1 - x0, y1 - y0, k, m, name, body_s, '; ' + why if why else '')


def project_libraries(d):
    """The footprint libraries a project keeps inside itself (fp-lib-table entries under ${KIPRJMOD})"""
    t = os.path.join(d, 'fp-lib-table')
    if not os.path.exists(t):
        sys.exit('%s has no fp-lib-table: give the .pretty folder' % d)
    out = []
    for lib in load(t).nodes('lib'):
        uri = str(lib.get('uri', ''))
        if uri.startswith('${KIPRJMOD}'):
            out.append(os.path.normpath(os.path.join(d, uri[len('${KIPRJMOD}'):].lstrip('/\\'))))
    if not out:
        sys.exit('%s: fp-lib-table names no library inside the project' % d)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('paths', nargs='+', help='.kicad_mod files, .pretty folders, or project folders')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--class', dest='cls', choices=sorted(MARGIN), help='one clearance class for every footprint')
    g.add_argument('--margin', type=float, help='one clearance in mm for every footprint')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    files = []
    for p in a.paths:
        if os.path.isdir(p) and not p.rstrip('/\\').endswith('.pretty') and glob.glob(os.path.join(p, '*.kicad_pro')):
            for lib in project_libraries(p):
                print('library %s' % lib)
                files += sorted(glob.glob(os.path.join(lib, '*.kicad_mod')))
        elif os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*.kicad_mod')))
        else:
            files.append(p)
    for f in files:
        print(process(f, a.dry_run, a.cls, a.margin))


if __name__ == '__main__':
    main()
