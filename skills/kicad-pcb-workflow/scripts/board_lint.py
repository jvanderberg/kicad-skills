#!/usr/bin/env python3
"""Checks KiCad's DRC does not make. Run with KiCad's bundled python ($KICAD_PYTHON, from kicad_env.sh):
  $KICAD_PYTHON board_lint.py BOARD.kicad_pcb [--no-models] [--no-silk] [--no-courtyard] [--no-via-in-pad]
        [--no-paste] [--vias-filled [REF ...]] [--no-hardware] [--hardware-r MM | --hardware-r REF=MM ...]
(started with another python it re-runs itself under KiCad's: interp.py)

- footprints without a courtyard (most EasyEDA imports): DRC's courtyards_overlap cannot see them, so they can sit on
  top of other parts. Such a part's area is its silkscreen outline (its boundary: layout-rules.md "Placement and
  mechanical"), its body (F.Fab graphics) and its pads, one rectangle. SILK OUTLINE reports a pair whose areas
  overlap on the same side when either is bounded by its outline (DRC's silk_overlap only sees crossing lines, not a
  part sitting inside another's outline); BODY OVERLAP, when neither has an outline: a body or pads on a neighbour's
  body, pads or courtyard, e.g. a QFN's body overhanging its pads onto the next part. A part without an outline (none
  drawn, or a strip_outline.py copy, known by its "Silk outline" property whatever inner drawing it kept) is checked by
  its body and pads and listed in a NOTE as spaced by rule of thumb. Silk deleted on the board itself leaves no such
  property: what silk is left counts as the outline. Rectangles are axis-aligned, so a part at 45 degrees is checked
  generously;
- 3D models whose file does not exist (${KICAD10_3DMODEL_DIR}, ${KIPRJMOD} and other variables expanded from the
  environment and kicad_common.json): the 3D render silently shows bare pads, so a missing model looks like a
  missing part or hides a collision. KiCad's own library references models it does not install for some footprints;
- silkscreen text over another footprint's body (the extent of its F.Fab graphics and pads) on the same side:
  DRC checks silk against pads, other silk and the board edge, not against component bodies, so a label printed
  under a part passes DRC and disappears once the part is fitted. Touching a courtyard's clearance margin is not
  reported; overlaps of less than --min-overlap (0.1 mm) in either direction are ignored;
- vias on or touching a pad of their own net: DRC and every clearance check skip same-net copper, so a via dropped into
  a neighbouring pad of the same net (FET source pins side by side, a decoupling cap's ground pad) passes, and the
  open barrel wicks solder out of that joint. Pads that are exposed / thermal pads (>= 1 mm^2 and >= 2x their
  footprint's median pad area) are listed as NOTE lines, not problems: vias there are usually intended, and the fab
  order must say filled / tented (or the paste wicks the same way);
- PASTE ON HOLE: a solder-paste aperture (a pad's own paste, or a paste-only window pad, after its paste margin) over a
  drilled hole - a via or any plated or unplated pad drill. Reflow pulls the paste down the barrel: voids under an
  exposed pad, a starved joint, solder balls on the far side. Library footprints do this too (thermal-via variants
  with one paste window per quadrant over the vias). Fix: paste windows that avoid every hole (paste_clear.py derives
  such a footprint from a library one), or order the vias
  filled and capped (via-in-pad process) and say so with --vias-filled (all vias) or --vias-filled U1 U3 (vias in
  those parts' pads). For every exposed pad with holes the paste coverage (paste area / copper area, typically 40-60 %)
  is printed as a NOTE, so a re-drawn window pattern is checked in the same run;
- UNDER HARDWARE: copper of another net on F.Cu or B.Cu within the hardware radius of a mounting hole (a footprint
  whose only pads are holes >= 2 mm, or a MountingHole footprint): the screw head, washer or metal standoff sits on it,
  insulated by solder mask alone. Default radius: the drill diameter + 0.5 mm (a washer or standoff about twice the
  hole, plus margin); --hardware-r 3.5 for every hole, or --hardware-r H1=4 per hole. Copper of the hole's own net
  (a grounded mounting ring) is not reported; a pour of another net is a NOTE (often deliberate: name the hardware's
  potential with --hardware-net GND and it is not mentioned).
Exit 1 if anything is found (NOTE lines do not count). It does not replace looking at a 3D render and a silk render.
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from interp import need  # noqa: E402
from outline_rules import REMOVED, is_mark  # noqa: E402
need('pcbnew')                                      # started with another python: re-run under KiCad's
import pcbnew  # noqa: E402

# pcbnew.LoadBoard prints wx's "assert traits failed ... create wxApp before calling this" on every run (KiCad 10.0.x,
# harmless). Drop exactly that line and pass every other stderr line through: never filter a whole category.
_WX_NOISE = re.compile(r'stdpbase\.cpp\(\d+\): assert ""traits"" failed in Get\(\): create wxApp before calling this')
def load_board(path):
    import tempfile
    sys.stderr.flush(); saved = os.dup(2)
    with tempfile.TemporaryFile() as tf:
        os.dup2(tf.fileno(), 2)
        try:
            return pcbnew.LoadBoard(path)
        finally:
            os.dup2(saved, 2); os.close(saved); tf.seek(0)
            for line in tf.read().decode('utf-8', 'replace').splitlines():
                if not _WX_NOISE.search(line): print(line, file=sys.stderr)

MM = pcbnew.ToMM


def kicad_vars(board_path):
    v = {}
    home = os.path.expanduser('~')
    for c in (os.path.join(home, 'Library/Preferences/kicad/10.0/kicad_common.json'), os.path.join(home, '.config/kicad/10.0/kicad_common.json'),
              os.path.join(os.environ.get('APPDATA', ''), 'kicad/10.0/kicad_common.json')):
        if os.path.exists(c):
            try:
                v.update((json.load(open(c)).get('environment') or {}).get('vars') or {})
            except ValueError:
                pass
    for base in ('/Applications/KiCad/KiCad.app/Contents/SharedSupport', '/usr/share/kicad', 'C:/Program Files/KiCad/10.0/share/kicad'):
        if os.path.isdir(os.path.join(base, '3dmodels')):
            v.setdefault('KICAD10_3DMODEL_DIR', os.path.join(base, '3dmodels'))
            v.setdefault('KICAD9_3DMODEL_DIR', os.path.join(base, '3dmodels'))
            break
    v.update({k: val for k, val in os.environ.items() if k.startswith('KICAD')})
    v['KIPRJMOD'] = os.path.dirname(os.path.abspath(board_path))
    return v


def expand(path, env):
    return re.sub(r'\$\{(\w+)\}', lambda m: env.get(m.group(1), m.group(0)), path)


def box(bb):
    return (MM(bb.GetX()), MM(bb.GetY()), MM(bb.GetRight()), MM(bb.GetBottom()))


def overlap(a, b, minimum):
    return min(a[2], b[2]) - max(a[0], b[0]) > minimum and min(a[3], b[3]) - max(a[1], b[1]) > minimum


def merged(rs):
    """one rectangle over rectangles rs (None for none)"""
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs)) if rs else None


def bodies(f):
    """the part's own area: one rectangle over its F.Fab (B.Fab) graphics and its pads. Imported footprints often
    have nothing on F.Fab but a pin-1 mark, so the pads always count."""
    fab = pcbnew.B_Fab if f.IsFlipped() else pcbnew.F_Fab
    rs = [box(g.GetBoundingBox()) for g in f.GraphicalItems() if isinstance(g, pcbnew.PCB_SHAPE) and g.GetLayer() == fab]
    m = merged(rs + [box(p.GetBoundingBox()) for p in f.Pads()])
    return [m] if m else []


def outline_removed(f):
    """the footprint is a strip_outline.py copy (its hidden REMOVED property came onto the board with it)"""
    return any(fd.GetName() == REMOVED[0] for fd in f.GetFields())


def silk_outline(f):
    """rectangles of the footprint's silkscreen outline on its own side: graphics, not text, without marks such as a
    pin-1 dot (outline_rules.is_mark); none for a strip_outline.py copy, whatever inner drawing it kept"""
    if outline_removed(f):
        return []
    silk = pcbnew.B_SilkS if f.IsFlipped() else pcbnew.F_SilkS
    rs = []
    for g in f.GraphicalItems():
        if not isinstance(g, pcbnew.PCB_SHAPE) or g.GetLayer() != silk:
            continue
        r = box(g.GetBoundingBox())
        if not is_mark('circle' if g.GetShape() == pcbnew.SHAPE_T_CIRCLE else 'other', g.IsSolidFill(), r[2] - r[0], r[3] - r[1]):
            rs.append(r)
    return rs


def courtyard(f):
    """this footprint's own courtyard on its side (computed per footprint: references can repeat)"""
    f.BuildCourtyardCaches()
    return f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)


def outline_overlaps(fps, minimum):
    """SILK OUTLINE and BODY OVERLAP problems, and the NOTEs listing the parts without a courtyard. Each part's area is
    its courtyard's rectangle when it has one, else one rectangle over its silk outline, body (F.Fab) and pads; a pair
    is reported when one of them has no courtyard (two courtyards are DRC's) and the rectangles overlap by more than
    `minimum` both ways: SILK OUTLINE when either is bounded by its outline, else BODY OVERLAP"""
    area, outlined, bare = [], [], []          # area: (ref, flipped, by courtyard, by silk outline, rectangle)
    for f in fps:
        if not f.Pads():
            continue
        cy = courtyard(f)
        if cy.OutlineCount():
            area.append((f.GetReference(), f.IsFlipped(), True, False, box(cy.BBox())))
            continue
        silk = silk_outline(f)
        (outlined if silk else bare).append(f.GetReference())
        area.append((f.GetReference(), f.IsFlipped(), False, bool(silk), merged(silk + bodies(f))))
    probs = []
    for i, (ra, fa, ca, sa, a) in enumerate(area):
        for rb, fb, cb, sb, b in area[i + 1:]:
            if fa != fb or (ca and cb):
                continue
            ox, oy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
            if ox <= minimum or oy <= minimum:
                continue
            at = (ra, rb, ox, oy, (max(a[0], b[0]) + min(a[2], b[2])) / 2, (max(a[1], b[1]) + min(a[3], b[3])) / 2,
                  ' (%s by its courtyard)' % (ra if ca else rb) if ca or cb else '')
            if sa or sb:
                probs.append('SILK OUTLINE  %s and %s overlap by %.2f x %.2f mm at (%.2f, %.2f)%s: move them apart, or '
                             'place them tighter on purpose (remove the outline, space by rule of thumb: layout-rules.md)' % at)
            else:
                probs.append('BODY OVERLAP  %s and %s overlap by %.2f x %.2f mm at (%.2f, %.2f)%s: a body (F.Fab outline) '
                             'or pads on the other part; move them apart' % at)
    notes = []
    if outlined:
        notes.append('NOTE  no courtyard, silk outline checked as the boundary (DRC cannot see these): %s' % ' '.join(outlined))
    if bare:
        notes.append('NOTE  no courtyard and no silk outline, spaced by rule of thumb (layout-rules.md; check the gaps): %s'
                     % ' '.join(bare))
    return probs, notes


def vias_in_pads(b, fps):
    """(problems, notes): vias whose copper touches a pad of their own net (other nets are DRC's clearance check)"""
    vias = [v for v in b.GetTracks() if isinstance(v, pcbnew.PCB_VIA)]
    probs, inexp = [], {}
    for f in fps:
        pads = list(f.Pads())
        areas = sorted(MM(p.GetSize().x) * MM(p.GetSize().y) for p in pads)
        med = areas[len(areas) // 2] if areas else 0
        for p in pads:
            if not p.GetNetname() or p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                continue
            area = MM(p.GetSize().x) * MM(p.GetSize().y)
            exposed = area >= 1.0 and len(pads) > 2 and area >= 2 * med
            for v in vias:
                if v.GetNetname() != p.GetNetname():
                    continue
                if not any(v.IsOnLayer(L) for L in p.GetLayerSet().CuStack()):
                    continue
                if p.HitTest(v.GetPosition(), int(v.GetWidth(pcbnew.F_Cu) / 2) if hasattr(v, 'GetWidth') else 0):
                    x, y = MM(v.GetPosition().x), MM(v.GetPosition().y)
                    if exposed:
                        inexp.setdefault((id(f), f.GetReference(), p.GetNumber()), []).append((x, y))
                    else:
                        where = 'centre on' if p.HitTest(v.GetPosition(), 0) else 'annular ring overlaps'
                        probs.append('VIA IN PAD    via (%s) at (%.2f, %.2f): %s pad %s.%s of its own net - no solder-mask web '
                                     'between them, the open barrel wicks solder from the joint; move it off the pad (or make it '
                                     'a filled via-in-pad on purpose)' % (v.GetNetname(), x, y, where, f.GetReference(), p.GetNumber()))
    notes = ['NOTE          %d via(s) in exposed pad %s.%s (thermal vias?): order them filled or tented, or the paste wicks away' % (
        len(v), r, n) for (_, r, n), v in sorted(inexp.items(), key=lambda kv: kv[0][1:])]
    return probs, notes


def _rings(shp):
    out = []
    for i in range(shp.OutlineCount()):
        o = shp.Outline(i)
        out.append([(MM(o.CPoint(j).x), MM(o.CPoint(j).y)) for j in range(o.PointCount())])
    return out


def _seg_dist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return ((p[0] - ax - t * dx) ** 2 + (p[1] - ay - t * dy) ** 2) ** 0.5


def _inside(p, ring):
    x, y, c = p[0], p[1], False
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i], ring[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def ring_dist(p, rings):
    """0 inside any ring, else the distance from p to the nearest ring edge"""
    if any(_inside(p, r) for r in rings):
        return 0.0
    return min((_seg_dist(p, r[i - 1], r[i]) for r in rings for i in range(len(r))), default=1e9)


def _area(ring):
    return abs(sum(ring[i - 1][0] * ring[i][1] - ring[i][0] * ring[i - 1][1] for i in range(len(ring)))) / 2


def paste_on_holes(b, fps, filled):
    """(problems, notes): paste apertures over drilled holes; paste coverage of exposed pads that have holes"""
    holes = [(MM(v.GetPosition().x), MM(v.GetPosition().y), MM(v.GetDrillValue()) / 2, 'via (%s)' % v.GetNetname(), None)
             for v in b.GetTracks() if isinstance(v, pcbnew.PCB_VIA)]
    for f in fps:
        for p in f.Pads():
            if p.GetDrillSize().x > 0:
                holes.append((MM(p.GetPosition().x), MM(p.GetPosition().y), MM(min(p.GetDrillSize().x, p.GetDrillSize().y)) / 2,
                              'drill of pad %s.%s' % (f.GetReference(), p.GetNumber()), f))
    probs, notes = [], []
    for f in fps:
        ref = f.GetReference()
        pads = list(f.Pads())
        for side, L in (('F', pcbnew.F_Paste), ('B', pcbnew.B_Paste)):
            ap = [p for p in pads if p.IsOnLayer(L)]
            if not ap:
                continue
            rings = []
            for p in ap:
                m = p.GetSolderPasteMargin(L)
                m = min(m.x, m.y) if hasattr(m, 'x') else (min(m[0], m[1]) if isinstance(m, (tuple, list)) else int(m))
                shp = pcbnew.SHAPE_POLY_SET()
                p.TransformShapeToPolygon(shp, L, int(m), pcbnew.FromMM(0.005), pcbnew.ERROR_OUTSIDE)
                rings += _rings(shp)
            for x, y, r, what, owner in holes:
                # declared filled and capped: board vias, and the part's own thermal-via pads
                if (what.startswith('via') or owner is f) and (filled is True or (filled and ref in filled)):
                    continue
                if ring_dist((x, y), rings) < r:
                    probs.append('PASTE ON HOLE %s paste (%s.Paste) covers the %s at (%.2f, %.2f), drill %.2f mm: reflow pulls the '
                                 'paste down the barrel (voids, starved joint, balls on the far side); split the paste into windows (paste_clear.py) '
                                 'that avoid every hole, or order the vias filled and capped (--vias-filled %s)' % (
                                     ref, side, what, x, y, 2 * r, ref))
            # coverage of each exposed pad that has holes in it: paste area over copper area
            med = sorted(MM(p.GetSize().x) * MM(p.GetSize().y) for p in pads)[len(pads) // 2] if pads else 0
            cu = pcbnew.F_Cu if side == 'F' else pcbnew.B_Cu
            for num in sorted({p.GetNumber() for p in pads if p.GetNumber() and p.IsOnLayer(cu)}):
                cp = [p for p in pads if p.GetNumber() == num and p.IsOnLayer(cu) and p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH]
                if not cp:
                    continue
                area = sum(MM(p.GetSize().x) * MM(p.GetSize().y) for p in cp)
                if area < 1.0 or len(pads) <= 2 or area < 2 * med:
                    continue
                crings = []
                for p in cp:
                    shp = pcbnew.SHAPE_POLY_SET(); p.TransformShapeToPolygon(shp, cu, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_OUTSIDE)
                    crings += _rings(shp)
                inner = [h for h in holes if ring_dist(h[:2], crings) == 0.0]
                if not inner:
                    continue
                pa = sum(_area(r) for r in rings if all(ring_dist(q, crings) <= 0.01 for q in r))
                ca = sum(_area(r) for r in crings)
                notes.append('NOTE          exposed pad %s.%s: paste coverage %.0f %% (%.2f of %.2f mm^2; typically 40-60 %%), %d hole(s) in it' % (
                    ref, num, 100 * pa / ca if ca else 0, pa, ca, len(inner)))
    return probs, notes


def mounting_holes(fps):
    """[(footprint, ref, x, y, drill, net)]: footprints whose pads are all holes of 2 mm or more, or named MountingHole"""
    out = []
    for f in fps:
        pads = list(f.Pads())
        named = 'mountinghole' in str(f.GetFPID().GetLibItemName()).lower()
        drilled = [p for p in pads if p.GetDrillSize().x > 0]
        big = [p for p in drilled if MM(p.GetDrillSize().x) >= 2.0]
        if big and (named or len(big) == len(pads)):
            p = max(big, key=lambda q: q.GetDrillSize().x)
            out.append((f, f.GetReference(), MM(p.GetPosition().x), MM(p.GetPosition().y), MM(p.GetDrillSize().x), p.GetNetname()))
    return out


def under_hardware(b, fps, radius, hw_nets=()):
    """(problems, notes): copper of other nets on the outer layers within the hardware radius of each mounting hole.
    Tracks, vias and pads are problems; a pour is a note (often deliberate); copper of hw_nets is not reported"""
    probs, notes = [], []
    outer = (pcbnew.F_Cu, pcbnew.B_Cu)
    for hole, ref, x, y, drill, net in mounting_holes(fps):
        R = radius.get(ref, radius.get('*')) if radius else None
        R = R if R is not None else drill + 0.5
        found = {}
        for t in b.GetTracks():
            if net and t.GetNetname() == net:
                continue
            if isinstance(t, pcbnew.PCB_VIA):
                d = ((MM(t.GetPosition().x) - x) ** 2 + (MM(t.GetPosition().y) - y) ** 2) ** 0.5 - MM(t.GetWidth(pcbnew.F_Cu)) / 2
                layers = outer
            else:
                if t.GetLayer() not in outer:
                    continue
                a_, b_ = (MM(t.GetStart().x), MM(t.GetStart().y)), (MM(t.GetEnd().x), MM(t.GetEnd().y))
                d = _seg_dist((x, y), a_, b_) - MM(t.GetWidth()) / 2
                layers = (t.GetLayer(),)
            if d < R:
                for L in layers:
                    k = (t.GetNetname(), L, 'via' if isinstance(t, pcbnew.PCB_VIA) else 'track')
                    found[k] = min(found.get(k, 9e9), d)
        for z in b.Zones():
            if z.GetIsRuleArea() or (net and z.GetNetname() == net):
                continue
            for L in outer:
                if not z.IsOnLayer(L):
                    continue
                rings = _rings(z.GetFilledPolysList(L))
                if rings:
                    d = ring_dist((x, y), rings)
                    if d < R:
                        k = (z.GetNetname(), L, 'pour')
                        found[k] = min(found.get(k, 9e9), d)
        for f in fps:
            if f is hole:
                continue
            for p in f.Pads():
                if (net and p.GetNetname() == net) or not any(p.IsOnLayer(L) for L in outer):
                    continue
                shp = pcbnew.SHAPE_POLY_SET()
                L = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
                p.TransformShapeToPolygon(shp, L, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_OUTSIDE)
                d = ring_dist((x, y), _rings(shp))
                if d < R:
                    k = (p.GetNetname() or '%s.%s' % (f.GetReference(), p.GetNumber()), L, 'pad %s.%s' % (f.GetReference(), p.GetNumber()))
                    found[k] = min(found.get(k, 9e9), d)
        for (n, L, kind), d in sorted(found.items(), key=lambda kv: kv[1]):
            if n in hw_nets:
                continue
            if kind == 'pour':
                notes.append('NOTE          %s pour on %s reaches %.2f mm from mounting hole %s (hardware radius %.2f mm): the '
                             'hardware sits on it through solder mask - fine if that is the hardware\'s potential (--hardware-net %s), '
                             'else keep it out' % (n or '(no net)', b.GetLayerName(L), max(d, 0.0), ref, R, n))
                continue
            probs.append('UNDER HARDWARE %s %s on %s %.2f mm from mounting hole %s at (%.2f, %.2f) (hardware radius %.2f mm, '
                         'both sides): the screw head, washer or standoff sits on it with only solder mask between; keep '
                         'other nets outside the radius (a keepout on both outer layers)' % (
                             kind, n or '(no net)', b.GetLayerName(L), max(d, 0.0), ref, x, y, R))
    return probs, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('board'); ap.add_argument('--no-models', action='store_true'); ap.add_argument('--no-silk', action='store_true')
    ap.add_argument('--no-courtyard', action='store_true'); ap.add_argument('--min-overlap', type=float, default=0.1)
    ap.add_argument('--no-via-in-pad', action='store_true')
    ap.add_argument('--no-paste', action='store_true')
    ap.add_argument('--vias-filled', nargs='*', help="vias are ordered filled and capped: all (no refs) or in these parts' pads "
                    "(board vias and the parts' own via pads)")
    ap.add_argument('--no-hardware', action='store_true')
    ap.add_argument('--hardware-r', action='append', default=[], help='hardware radius in mm (all holes) or REF=MM')
    ap.add_argument('--hardware-net', action='append', default=[], help="the hardware's potential (e.g. GND): not reported")
    a = ap.parse_args()
    b = load_board(a.board)
    fps = list(b.GetFootprints())
    probs, notes = [], []
    if not a.no_courtyard:
        probs, notes = outline_overlaps(fps, a.min_overlap)
    if not a.no_models:
        env = kicad_vars(a.board)
        for f in fps:
            for m in f.Models():                      # Models() returns copies: fine for reading, useless for writing
                if not m.m_Show:
                    continue
                p = expand(m.m_Filename, env)
                if '${' in p:
                    probs.append('MODEL VAR     %s: unresolved variable in %s' % (f.GetReference(), m.m_Filename))
                elif not os.path.exists(p) and not os.path.exists(os.path.splitext(p)[0] + '.wrl') \
                        and not os.path.exists(os.path.splitext(p)[0] + '.step'):
                    probs.append('MODEL MISSING %s: %s' % (f.GetReference(), m.m_Filename))
    if not a.no_silk:
        texts = []                                     # (owner ref or None, text, layer, box)
        for d in b.GetDrawings():
            if isinstance(d, pcbnew.PCB_TEXT) and d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                texts.append((None, None, d.GetShownText(True), d.GetLayer(), box(d.GetBoundingBox())))
        for f in fps:
            for t in list(f.GetFields()) + [g for g in f.GraphicalItems() if isinstance(g, pcbnew.PCB_TEXT)]:
                if t.IsVisible() and t.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and t.GetShownText(True):
                    texts.append((f, f.GetReference(), t.GetShownText(True), t.GetLayer(), box(t.GetBoundingBox())))
        body = [(f, f.GetReference(), bodies(f), f.IsFlipped()) for f in fps]      # per footprint: references can repeat
        for ownf, owner, s, layer, tb in texts:
            for f, ref, bxs, flipped in body:
                if f is ownf or flipped != (layer == pcbnew.B_SilkS):
                    continue
                if any(overlap(tb, bx, a.min_overlap) for bx in bxs):
                    probs.append('SILK ON PART  "%s"%s on %s at (%.2f, %.2f) lies on the body of %s' % (
                        s, ' (of %s)' % owner if owner else '', b.GetLayerName(layer), (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2, ref))
    if not a.no_via_in_pad:
        vp, vn = vias_in_pads(b, fps)
        probs += vp; notes += vn
    if not a.no_paste:
        filled = None if a.vias_filled is None else (True if not a.vias_filled else set(a.vias_filled))
        pp, pn = paste_on_holes(b, fps, filled)
        probs += pp; notes += pn
    if not a.no_hardware:
        rad = {}
        for h in a.hardware_r:
            k, _, v = h.rpartition('=')
            rad[k or '*'] = float(v)
        hp, hn = under_hardware(b, fps, rad, set(a.hardware_net))
        probs += hp; notes += hn
    for p in probs + notes:
        print(p)
    print('%d footprints checked: %d problem(s)%s' % (len(fps), len(probs), ', %d note(s)' % len(notes) if notes else ''))
    sys.exit(1 if probs else 0)


if __name__ == '__main__':
    main()
