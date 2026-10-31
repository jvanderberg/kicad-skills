# Run with KiCad's bundled python (it has pcbnew):
#   <kicad-python> boarddump.py board.kicad_pcb PACK_DIR
# Dumps copper geometry (pads, tracks, arcs, vias, the zone fills KiCad saved, board outline, stackup) to PACK_DIR/board.json
# for the analysis scripts, which run in a normal venv (numpy, scipy, shapely>=2, matplotlib).
# It never refills zones: refill first with `kicad-cli pcb drc --refill-zones --save-board` on a COPY, so the analysis sees
# exactly the copper KiCad would plot.
import argparse, json, sys, re, os
ap = argparse.ArgumentParser(description='Dump a board\'s copper geometry to PACK_DIR/board.json for the analysis scripts.')
ap.add_argument('board', help='the .kicad_pcb (zones refilled on a copy first)'); ap.add_argument('pack', metavar='PACK_DIR')
args = ap.parse_args()                              # before the re-exec: --help and a missing argument need no KiCad
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from interp import need; need('pcbnew')            # started with another python: re-run under KiCad's
import pcbnew
src, pack = args.board, args.pack
os.makedirs(pack, exist_ok=True)
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
b = load_board(src)
mm = pcbnew.ToMM
cu = [l for l in b.GetEnabledLayers().CuStack()]
# layers by their canonical name (F.Cu, In1.Cu, ...): the name the stackup block, the .kicad_pcb items and the plans
# that router.py writes back all use. A user name ("Top Layer", as EasyEDA imports set) goes in layer_names, for display.
LN = {l: pcbnew.BOARD.GetStandardLayerName(l) for l in cu}

def poly_set(ps):
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i); ring = [(mm(o.CPoint(j).x), mm(o.CPoint(j).y)) for j in range(o.PointCount())]
        holes = []
        for h in range(ps.HoleCount(i)):
            hh = ps.Hole(i, h); holes.append([(mm(hh.CPoint(j).x), mm(hh.CPoint(j).y)) for j in range(hh.PointCount())])
        out.append([ring, holes])
    return out

# stackup from the file text: copper thickness, dielectric thickness and er, in order from the top
txt = open(src).read()
stack = []
m = re.search(r'\(stackup\b', txt)
if m:
    depth, i = 0, m.start()
    while True:
        c = txt[i]; depth += (c == '(') - (c == ')'); i += 1
        if depth == 0: break
    for lm in re.finditer(r'\(layer "([^"]+)"(.*?)\n\t\t\t\)', txt[m.start():i], re.S):
        body = lm.group(2)
        ty = re.search(r'\(type "([^"]+)"\)', body); th = re.search(r'\(thickness ([\d.]+)', body); er = re.search(r'\(epsilon_r ([\d.]+)\)', body)
        stack.append(dict(name=lm.group(1), type=ty.group(1) if ty else '', thickness_mm=float(th.group(1)) if th else 0.0,
                          er=float(er.group(1)) if er else None))
stack = [s for s in stack if s['type'] in ('copper', 'core', 'prepreg') or s['name'].startswith('dielectric')]

D = dict(source=os.path.abspath(src), layers=[LN[l] for l in cu], layer_names={LN[l]: b.GetLayerName(l) for l in cu}, stackup=stack, footprints=[], tracks=[], vias=[], zones=[], netclass={},
         pad_poly=dict(error_mm=0.005, error_side='outside'))
bb = b.GetBoardEdgesBoundingBox(); D['edge_bbox'] = [mm(bb.GetX()), mm(bb.GetY()), mm(bb.GetRight()), mm(bb.GetBottom())]
eps = pcbnew.SHAPE_POLY_SET(); b.GetBoardPolygonOutlines(eps, True); D['edge'] = poly_set(eps)
for f in b.GetFootprints():
    fd = dict(ref=f.GetReference(), value=f.GetValue(), fp=str(f.GetFPID().GetLibItemName()), lib=str(f.GetFPID().GetLibNickname()),
              x=mm(f.GetPosition().x), y=mm(f.GetPosition().y), rot=f.GetOrientationDegrees(), side='B' if f.IsFlipped() else 'F', pads=[])
    for p in f.Pads():
        layers = [LN[l] for l in cu if p.IsOnLayer(l)]
        shp = pcbnew.SHAPE_POLY_SET()
        # ERROR_OUTSIDE: the polygon contains the true pad (arcs approximated outward), so a clearance measured to it
        # is never larger than KiCad's (router.py reads 'pad_poly' below and stays at least as strict as DRC)
        p.TransformShapeToPolygon(shp, p.GetPrincipalLayer() if layers else pcbnew.F_Cu, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_OUTSIDE)
        fd['pads'].append(dict(num=p.GetNumber(), net=p.GetNetname(), x=mm(p.GetPosition().x), y=mm(p.GetPosition().y), layers=layers,
                               th=p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH, drill=mm(p.GetDrillSize().x), poly=poly_set(shp)))
    D['footprints'].append(fd)
# via type by name: the enum's numbers differ between KiCad versions (THROUGH is 3 in KiCad 9, 4 in KiCad 10)
_VT = {getattr(pcbnew, 'VIATYPE_' + k): k.lower() for k in ('THROUGH', 'BLIND', 'BURIED', 'BLIND_BURIED', 'MICROVIA') if hasattr(pcbnew, 'VIATYPE_' + k)}
for t in b.GetTracks():
    if t.GetClass() == 'PCB_VIA':
        D['vias'].append(dict(x=mm(t.GetPosition().x), y=mm(t.GetPosition().y), net=t.GetNetname(), size=mm(t.GetWidth(pcbnew.F_Cu)),
                              drill=mm(t.GetDrillValue()), type=int(t.GetViaType()), type_name=_VT.get(t.GetViaType(), 'unknown')))
    elif t.GetClass() == 'PCB_ARC':
        D['tracks'].append(dict(a=(mm(t.GetStart().x), mm(t.GetStart().y)), m=(mm(t.GetMid().x), mm(t.GetMid().y)), b=(mm(t.GetEnd().x), mm(t.GetEnd().y)),
                                w=mm(t.GetWidth()), layer=pcbnew.BOARD.GetStandardLayerName(t.GetLayer()), net=t.GetNetname(), arc=True))
    else:
        D['tracks'].append(dict(a=(mm(t.GetStart().x), mm(t.GetStart().y)), b=(mm(t.GetEnd().x), mm(t.GetEnd().y)), w=mm(t.GetWidth()),
                                layer=pcbnew.BOARD.GetStandardLayerName(t.GetLayer()), net=t.GetNetname()))
for z in b.Zones():
    zd = dict(net=z.GetNetname(), name=z.GetZoneName(), prio=z.GetAssignedPriority(), keepout=z.GetIsRuleArea(), layers=[], outline=poly_set(z.Outline()),
              min_w=mm(z.GetMinThickness()), clearance=mm(z.GetLocalClearance() or 0), filled={})
    for l in cu:
        if z.IsOnLayer(l):
            zd['layers'].append(LN[l])
            if not z.GetIsRuleArea(): zd['filled'][LN[l]] = poly_set(z.GetFilledPolysList(l))
    D['zones'].append(zd)
ds = b.GetDesignSettings()
for name, nc in ds.m_NetSettings.GetNetclasses().items():
    D['netclass'][str(name)] = dict(track=mm(nc.GetTrackWidth()), clearance=mm(nc.GetClearance()), via=mm(nc.GetViaDiameter()))
json.dump(D, open(os.path.join(pack, 'board.json'), 'w'))
print(len(D['footprints']), 'footprints', len(D['tracks']), 'tracks', len(D['vias']), 'vias', len(D['zones']), 'zones,', len(cu), 'copper layers')
