#!/usr/bin/env python3
"""Check a footprint before assigning it: pads, courtyard, size against the package, numbering against the symbol.

  fpcheck.py FOOTPRINT.kicad_mod [--package "VQFN-20-EP(3.6x4.6)"] [--symbol LIB.kicad_sym:NAME] [--pads]

FOOTPRINT may also be LIB.pretty:NAME, or Lib:Name for a KiCad library footprint (found in $KICAD10_FOOTPRINT_DIR or
the usual install path). Prints one line of facts and a list of PROBLEMs; exit 1 if there are any:
- (a note, not a problem) no F.CrtYd courtyard: DRC cannot see overlaps with this part, so space it by rule of thumb
  (references/layout-rules.md); most EasyEDA footprints have none;
- pad count / body size differ from the package string (LCSC's "Package" column, e.g. from jlcimport-cli search):
  "-20" in the name is the lead count, "-EP" an exposed pad, "(3.6x4.6)" the body in mm (either orientation, 0.2 mm
  tolerance against the F.Fab outline; without an F.Fab outline the pad span is printed as a note only);
- symbol pin numbers with no pad, or numbered pads with no symbol pin (an unconnected pad, or a footprint that merges
  pins into one pad - e.g. several FET source pins as one pad "5" - so the symbol must be renumbered to match).
--pads lists each pad number: count, type, position and size in the pad's frame. A custom pad's (size ...) is only its
anchor (EasyEDA writes 0.1 x 0.1 + a polygon: a USB-C's VBUS/GND pads), so a custom pad shows its copper extent
(anchor and primitives together) and is marked "custom: anchor W x H + primitives"; the pad span note uses the same
extents.
Name-based footprint matchers propose wrong pin counts and sizes often enough that every suggested KiCad footprint
needs this check (JLCImport v1.6.7 matched by name; v1.7.0's geometry-checked matcher, PR #122, checks the pads), and the
datasheet's land-pattern figure is still the authority for pad sizes and pitch. EasyEDA package names work as
--package too ("SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR": 3 leads, body 2.9 x 1.3).
"""
import argparse, collections, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import SymbolLibrary, load, pins_of, rotate  # noqa: E402


def fp_dir():
    for c in (os.environ.get('KICAD10_FOOTPRINT_DIR'), os.environ.get('KICAD9_FOOTPRINT_DIR'),
              '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints', '/usr/share/kicad/footprints',
              'C:/Program Files/KiCad/10.0/share/kicad/footprints'):
        if c and os.path.isdir(c):
            return c
    return None


def resolve(spec):
    if os.path.exists(spec):
        return spec
    if '.pretty:' in spec:
        lib, name = spec.split('.pretty:', 1)
        return os.path.join(lib + '.pretty', name + '.kicad_mod')
    if ':' in spec and fp_dir():
        lib, name = spec.split(':', 1)
        return os.path.join(fp_dir(), lib + '.pretty', name + '.kicad_mod')
    sys.exit('footprint not found: ' + spec)


def arc_points(s, m, e, n=32):
    """points along the circular arc start -> mid -> end (the three points if they are collinear)"""
    d = 2 * (s[0] * (m[1] - e[1]) + m[0] * (e[1] - s[1]) + e[0] * (s[1] - m[1]))
    if abs(d) < 1e-12:
        return [s, m, e]
    q = [p[0] ** 2 + p[1] ** 2 for p in (s, m, e)]
    cx = (q[0] * (m[1] - e[1]) + q[1] * (e[1] - s[1]) + q[2] * (s[1] - m[1])) / d
    cy = (q[0] * (e[0] - m[0]) + q[1] * (s[0] - e[0]) + q[2] * (m[0] - s[0])) / d
    r = math.hypot(s[0] - cx, s[1] - cy)
    a0, am, a1 = (math.atan2(p[1] - cy, p[0] - cx) for p in (s, m, e))
    sweep = (a1 - a0) % (2 * math.pi)
    if (am - a0) % (2 * math.pi) > sweep:                 # the arc runs the other way round
        sweep -= 2 * math.pi
    return [(cx + r * math.cos(a0 + sweep * k / n), cy + r * math.sin(a0 + sweep * k / n)) for k in range(n + 1)]


def primitive_box(g):
    """(x0, y0, x1, y1) of one custom-pad primitive (gr_poly / gr_line / gr_rect / gr_circle / gr_arc / gr_curve) in
    the pad's frame, its stroke width included; None for anything else (gr_bbox / gr_vector are annotations, not
    copper)"""
    xy = lambda n: (n.number(1), n.number(2))
    if g.head == 'gr_circle':
        (cx, cy), (ex, ey) = xy(g.need('center')), xy(g.need('end'))
        r = math.hypot(ex - cx, ey - cy)
        pts = [(cx - r, cy - r), (cx + r, cy + r)]
    elif g.head == 'gr_arc':
        pts = arc_points(xy(g.need('start')), xy(g.need('mid')), xy(g.need('end')))
    elif g.head in ('gr_poly', 'gr_curve'):
        pts = [xy(n) for n in g.need('pts').nodes('xy')]
    elif g.head in ('gr_line', 'gr_rect'):
        pts = [xy(g.need('start')), xy(g.need('end'))]
    else:
        return None
    if not pts:
        return None
    w = g.find('width')
    if w is None and g.find('stroke') is not None:
        w = g.need('stroke').find('width')
    hw = w.number(1) / 2 if w is not None else 0.0
    return (min(x for x, _ in pts) - hw, min(y for _, y in pts) - hw, max(x for x, _ in pts) + hw, max(y for _, y in pts) + hw)


def pad_extent(p):
    """(w, h, dx, dy): the copper extent of a pad in its own frame and the offset of that extent's centre from the
    pad's anchor. A plain pad is its (size ...); a custom pad (EasyEDA's: a 0.1 mm anchor + a polygon) is its anchor
    and every primitive together."""
    size = p.need('size')
    w, h = size.number(1), size.number(2)
    prims = p.find('primitives')
    if str(p[3]) != 'custom' or prims is None:
        return w, h, 0.0, 0.0
    boxes = [(-w / 2, -h / 2, w / 2, h / 2)] + [b for b in (primitive_box(g) for g in prims.nodes()) if b]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    return x1 - x0, y1 - y0, (x0 + x1) / 2, (y0 + y1) / 2


Pad = collections.namedtuple('Pad', 'number type x y w h rot shape dx dy anchor_w anchor_h')


def pads(fp):
    """[Pad(number, type, x, y, w, h, rot, shape, dx, dy, anchor_w, anchor_h)] for every pad of a footprint node (read
    through kicad_sexpr): w x h is the copper extent in the pad's frame (custom pads: anchor and primitives), centred
    at (dx, dy) from the pad's anchor (x, y) - not 0 only for a custom pad whose primitives are off-centre; anchor_w x
    anchor_h is the (size ...), which is all a custom pad's own size says"""
    out = []
    for p in fp.nodes('pad'):
        at, size = p.find('at'), p.find('size')
        if at is None or size is None:
            continue
        w, h, dx, dy = pad_extent(p)
        out.append(Pad(str(p[1]), str(p[2]), at.number(1), at.number(2), w, h, at.number(3, 0.0), str(p[3]), dx, dy,
                       size.number(1), size.number(2)))
    return out


def pad_box(p):
    """(x0, y0, x1, y1) of a pads() entry's copper extent in the footprint frame (the pad's rotation applied)"""
    corners = [rotate(p.dx + sx * p.w / 2, p.dy + sy * p.h / 2, p.rot) for sx in (-1, 1) for sy in (-1, 1)]
    return (p.x + min(c[0] for c in corners), p.y + min(c[1] for c in corners),
            p.x + max(c[0] for c in corners), p.y + max(c[1] for c in corners))


def pad_line(n, lst):
    """the --pads line of the pads numbered n (the largest one's geometry); a custom pad shows its copper extent,
    marked custom with its anchor size (and the extent's offset from the anchor, if any)"""
    q = max(lst, key=lambda p: p.w * p.h)
    line = '  pad %-5s x%-2d %-8s (%7.3f, %7.3f) %5.2f x %-5.2f' % (n or '""', len(lst), q.type, q.x, q.y, q.w, q.h)
    if q.shape == 'custom':
        line += ' custom: anchor %.2f x %.2f + primitives' % (q.anchor_w, q.anchor_h)
        if abs(q.dx) > 0.0005 or abs(q.dy) > 0.0005:
            line += ', extent centred at (%+.3f, %+.3f) from the anchor' % (q.dx, q.dy)
    return line


def layer_bbox(fp, layer, outlines=False):
    """Bounding box of the points of every fp_line / fp_rect / fp_arc / fp_circle / fp_poly on `layer`, or None.
    outlines: unfilled items only (EasyEDA footprints put filled polarity marks and pin-1 dots on F.Fab)."""
    xs, ys = [], []
    for g in fp.nodes():
        if g.head not in ('fp_line', 'fp_rect', 'fp_arc', 'fp_circle', 'fp_poly') or str(g.get('layer')) != layer:
            continue
        if outlines and str(g.get('fill', 'no')) in ('solid', 'yes'):
            continue
        for n in g.walk():
            if n.head in ('start', 'end', 'mid', 'center', 'xy'):
                xs.append(n.number(1)); ys.append(n.number(2))
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def symbol_pins(spec):
    """Pin numbers of LIB.kicad_sym:NAME (derived symbols flattened), all units."""
    path, name = spec.rsplit(':', 1)
    lib = SymbolLibrary.load(path)
    if name not in lib.names():
        sys.exit('symbol %s not in %s' % (name, path))
    return {p.number for p in pins_of(lib.get(name), None, None)}


def parse_package(s):
    """'VQFN-20-EP(3.6x4.6)' -> (20, True, (3.6, 4.6)); missing parts are None. Also EasyEDA package names
    ('SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR' -> 3 leads, body L x W). The number of a family name (SOT-23, SOD-123,
    TO-252, SC-70, TSOT-23) is not a lead count: 'SOT-23' alone gives none; 'SOT-23-6L' gives 6."""
    leads = None
    for m in re.finditer(r'([A-Za-z]*)-(\d+)L?(?=[-_(]|$)', re.split(r'[_(]', s)[0]):
        if not re.search(r'(SOT|SOD|TO|SC|DO)$', m.group(1).upper()):
            leads = int(m.group(2))
            break
    body = re.search(r'\(([\d.]+)\s*[xX*]\s*([\d.]+)', s) or re.search(r'L(\d+(?:\.\d+)?)-W(\d+(?:\.\d+)?)', s)
    return (leads, bool(re.search(r'EP|PAD|HR', s, re.I)),
            (float(body.group(1)), float(body.group(2))) if body else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('footprint'); ap.add_argument('--package'); ap.add_argument('--symbol'); ap.add_argument('--pads', action='store_true')
    a = ap.parse_args()
    path = resolve(a.footprint)
    fp = load(path)
    P = pads(fp)
    numbered = sorted({p[0] for p in P if p[0]}, key=lambda s: (len(s), s))
    crt = layer_bbox(fp, 'F.CrtYd')
    fab = layer_bbox(fp, 'F.Fab', outlines=True)
    if fab and min(fab[2] - fab[0], fab[3] - fab[1]) <= 0.5:          # a pin-1 mark, not a body outline
        fab = None
    probs = []
    print('%s: %d pads (%d numbers: %s), courtyard %s, F.Fab body %s' % (
        os.path.basename(path), len(P), len(numbered), ' '.join(numbered[:40]),
        '%.2f x %.2f' % (crt[2] - crt[0], crt[3] - crt[1]) if crt else 'NONE',
        '%.2f x %.2f' % (fab[2] - fab[0], fab[3] - fab[1]) if fab else 'none'))
    if a.pads:
        for n in numbered + ([''] if any(not p[0] for p in P) else []):
            print(pad_line(n, [p for p in P if p.number == n]))
    if not crt:
        print('note: no F.CrtYd courtyard: DRC will not report overlaps with this part - space it by rule of thumb '
              '(references/layout-rules.md)')
    if a.package:
        leads, ep, body = parse_package(a.package)
        if leads is not None:
            # the exposed pad is usually numbered leads+1; KiCad library footprints may also give it a lead number
            count = len([n for n in numbered if not (ep and n.isdigit() and int(n) == leads + 1)])
            if count != leads and not (ep and count == leads - 1):
                probs.append('package says %d leads%s, footprint has %d numbered pads%s%s' % (
                    leads, ' + EP' if ep else '', len(numbered), ' (EP excluded: %d)' % count if ep else '',
                    ': the footprint merges pins into shared pads - number the symbol to match' if count < leads else ''))
        if body:
            if fab:
                w, h = fab[2] - fab[0], fab[3] - fab[1]
                if not any(abs(w - bw) <= 0.2 and abs(h - bh) <= 0.2 for bw, bh in (body, body[::-1])):
                    probs.append('package body %.2f x %.2f mm, footprint F.Fab outline %.2f x %.2f mm' % (body[0], body[1], w, h))
            elif P:
                boxes = [pad_box(p) for p in P]
                xs = [x for b in boxes for x in (b[0], b[2])]
                ys = [y for b in boxes for y in (b[1], b[3])]
                print('note: no F.Fab body outline; pads span %.2f x %.2f mm vs package body %.2f x %.2f mm - compare with '
                      'the datasheet land pattern by eye' % (max(xs) - min(xs), max(ys) - min(ys), body[0], body[1]))
    if a.symbol:
        sp = symbol_pins(a.symbol)
        fpn = set(numbered)
        if sp - fpn:
            probs.append('symbol pins with no pad: %s' % ' '.join(sorted(sp - fpn, key=lambda s: (len(s), s))))
        if fpn - sp:
            probs.append('pads with no symbol pin (unconnected, or the footprint merges pins): %s' %
                         ' '.join(sorted(fpn - sp, key=lambda s: (len(s), s))))
    for p in probs:
        print('PROBLEM ' + p)
    sys.exit(1 if probs else 0)


if __name__ == '__main__':
    main()
