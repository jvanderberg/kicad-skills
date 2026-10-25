#!/usr/bin/env python3
"""Checks KiCad's DRC does not make. Run with KiCad's bundled python ($KICAD_PYTHON, from kicad_env.sh):
  $KICAD_PYTHON board_lint.py BOARD.kicad_pcb [--no-models] [--no-silk] [--no-courtyard] [--no-via-in-pad]

- footprints without a courtyard: DRC's courtyards_overlap cannot see them, so they can sit on top of other parts;
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
  order must say filled / tented (or the paste wicks the same way).
Exit 1 if anything is found (NOTE lines do not count). It does not replace looking at a 3D render and a silk render.
"""
import argparse, json, os, re, sys

import pcbnew

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


def bodies(f):
    """the part's own area: one rectangle over its F.Fab (B.Fab) graphics and its pads. Imported footprints often
    have nothing on F.Fab but a pin-1 mark, so the pads always count."""
    fab = pcbnew.B_Fab if f.IsFlipped() else pcbnew.F_Fab
    rs = [box(g.GetBoundingBox()) for g in f.GraphicalItems() if isinstance(g, pcbnew.PCB_SHAPE) and g.GetLayer() == fab]
    rs += [box(p.GetBoundingBox()) for p in f.Pads()]
    if not rs:
        return []
    return [(min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))]


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
                        inexp.setdefault((f.GetReference(), p.GetNumber()), []).append((x, y))
                    else:
                        where = 'centre on' if p.HitTest(v.GetPosition(), 0) else 'annular ring overlaps'
                        probs.append('VIA IN PAD    via (%s) at (%.2f, %.2f): %s pad %s.%s of its own net - no solder-mask web '
                                     'between them, the open barrel wicks solder from the joint; move it off the pad (or make it '
                                     'a filled via-in-pad on purpose)' % (v.GetNetname(), x, y, where, f.GetReference(), p.GetNumber()))
    notes = ['NOTE          %d via(s) in exposed pad %s.%s (thermal vias?): order them filled or tented, or the paste wicks away' % (
        len(v), r, n) for (r, n), v in sorted(inexp.items())]
    return probs, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('board'); ap.add_argument('--no-models', action='store_true'); ap.add_argument('--no-silk', action='store_true')
    ap.add_argument('--no-courtyard', action='store_true'); ap.add_argument('--min-overlap', type=float, default=0.1)
    ap.add_argument('--no-via-in-pad', action='store_true')
    a = ap.parse_args()
    b = load_board(a.board)
    fps = list(b.GetFootprints())
    probs = []
    crt = {}
    for f in fps:
        f.BuildCourtyardCaches()
        side = pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd
        cy = f.GetCourtyard(side)
        crt[f.GetReference()] = (cy, f.IsFlipped())
        if not a.no_courtyard and cy.OutlineCount() == 0 and f.Pads():
            probs.append('NO COURTYARD  %s (%s): DRC cannot report overlaps with it (add_courtyard.py on its library)' %
                         (f.GetReference(), f.GetFPID().GetUniStringLibId()))
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
                texts.append((None, d.GetShownText(True), d.GetLayer(), box(d.GetBoundingBox())))
        for f in fps:
            for t in list(f.GetFields()) + [g for g in f.GraphicalItems() if isinstance(g, pcbnew.PCB_TEXT)]:
                if t.IsVisible() and t.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and t.GetShownText(True):
                    texts.append((f.GetReference(), t.GetShownText(True), t.GetLayer(), box(t.GetBoundingBox())))
        body = {f.GetReference(): (bodies(f), f.IsFlipped()) for f in fps}
        for owner, s, layer, tb in texts:
            for ref, (bxs, flipped) in body.items():
                if ref == owner or flipped != (layer == pcbnew.B_SilkS):
                    continue
                if any(overlap(tb, bx, a.min_overlap) for bx in bxs):
                    probs.append('SILK ON PART  "%s"%s on %s at (%.2f, %.2f) lies on the body of %s' % (
                        s, ' (of %s)' % owner if owner else '', b.GetLayerName(layer), (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2, ref))
    notes = []
    if not a.no_via_in_pad:
        vp, notes = vias_in_pads(b, fps)
        probs += vp
    for p in probs + notes:
        print(p)
    print('%d footprints checked: %d problem(s)%s' % (len(fps), len(probs), ', %d note(s)' % len(notes) if notes else ''))
    sys.exit(1 if probs else 0)


if __name__ == '__main__':
    main()
