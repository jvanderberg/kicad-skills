# Run with KiCad's bundled python (it has pcbnew):
#   <kicad-python> boarddump.py board.kicad_pcb PACK_DIR
# Dumps copper geometry (pads, tracks, arcs, vias, the zone fills KiCad saved, board outline, stackup) and KiCad's own
# connectivity (which copper items touch) to PACK_DIR/board.json for the analysis scripts, which run in a normal venv
# (numpy, scipy, shapely>=2, matplotlib).
# It never refills zones: refill first with `kicad-cli pcb drc --refill-zones --save-board` on a COPY, so the analysis sees
# exactly the copper KiCad would plot.
import argparse, collections, itertools, json, sys, re, os
ap = argparse.ArgumentParser(description='Dump a board\'s copper geometry to PACK_DIR/board.json for the analysis scripts.')
ap.add_argument('board', help='the .kicad_pcb (zones refilled on a copy first)'); ap.add_argument('pack', metavar='PACK_DIR')
ap.add_argument('--no-connectivity', action='store_true', help='skip KiCad\'s connectivity (decoupling.py needs it; '
                'pour_check.py and the router do not)')
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
ITEMS, ID, DUP = [], {}, set()   # (id, item) of every copper item on a net, uuid -> id, uuids used twice
def ident(iid, item):
    if item.GetNetCode() > 0:
        u = item.m_Uuid.AsString()
        if u in ID: DUP.add(u)
        ITEMS.append((iid, item)); ID[u] = iid
for f in b.GetFootprints():
    fd = dict(ref=f.GetReference(), value=f.GetValue(), fp=str(f.GetFPID().GetLibItemName()), lib=str(f.GetFPID().GetLibNickname()),
              x=mm(f.GetPosition().x), y=mm(f.GetPosition().y), rot=f.GetOrientationDegrees(), side='B' if f.IsFlipped() else 'F', pads=[])
    for k, p in enumerate(f.Pads()):
        ident('p%d.%d' % (len(D['footprints']), k), p)
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
        ident('v%d' % len(D['vias']), t)
        D['vias'].append(dict(x=mm(t.GetPosition().x), y=mm(t.GetPosition().y), net=t.GetNetname(), size=mm(t.GetWidth(pcbnew.F_Cu)),
                              drill=mm(t.GetDrillValue()), type=int(t.GetViaType()), type_name=_VT.get(t.GetViaType(), 'unknown'),
                              layers=[LN[t.TopLayer()], LN[t.BottomLayer()]]))   # the span: blind / buried vias join only these
    elif t.GetClass() == 'PCB_ARC':
        ident('t%d' % len(D['tracks']), t)
        D['tracks'].append(dict(a=(mm(t.GetStart().x), mm(t.GetStart().y)), m=(mm(t.GetMid().x), mm(t.GetMid().y)), b=(mm(t.GetEnd().x), mm(t.GetEnd().y)),
                                w=mm(t.GetWidth()), layer=pcbnew.BOARD.GetStandardLayerName(t.GetLayer()), net=t.GetNetname(), arc=True))
    else:
        ident('t%d' % len(D['tracks']), t)
        D['tracks'].append(dict(a=(mm(t.GetStart().x), mm(t.GetStart().y)), b=(mm(t.GetEnd().x), mm(t.GetEnd().y)), w=mm(t.GetWidth()),
                                layer=pcbnew.BOARD.GetStandardLayerName(t.GetLayer()), net=t.GetNetname()))
ZONES = []
for z in b.Zones():
    if not z.GetIsRuleArea() and z.GetNetCode() > 0: ZONES.append((len(D['zones']), z))
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

def connectivity():
    """KiCad's own connectivity (BuildConnectivity: what the ratsnest and DRC's unconnected items come from) as links
    between board.json items: "t<i>" tracks[i], "v<i>" vias[i], "p<f>.<k>" footprints[f].pads[k] and
    "z<i>/<layer>/<j>" piece j of zones[i].filled[layer]. Tracks, arcs, vias and pads: the items KiCad connects each one
    to (GetConnectedTracks / GetConnectedPads) - T-joins, crossings, vias mid-track, overlapping pads, copper touching
    an arc. Zones: the items KiCad connects to the zone (thermal-relief spokes and a track crossing a pour included),
    each joined to the fill piece its copper collides with on each layer (KiCad's own shapes); two same-net zones join
    where their fills collide. The links are then checked against KiCad's clusters (GetConnectedItems): a cluster they
    leave split, joined through copper board.json does not record (a copper shape, a footprint's own zone), gets a
    "cluster" link and a warning; one they merge that KiCad keeps apart is a warning."""
    b.BuildConnectivity(); cn = b.GetConnectivity(); cn.RecalculateRatsnest()
    uid = lambda o: o.m_Uuid.AsString()
    links, warn = {}, []
    if DUP:              # a uuid two items share cannot say which one KiCad returned: never map it (their own queries
        for u in DUP: del ID[u]                          # below still link them; their zone joins fall to the cluster check)
        warn.append('%d uuid(s) shared by several items (copied pads?): their zone joins are left to the cluster check' % len(DUP))
    def link(a, c, kind='touch'):
        if a != c: links.setdefault(tuple(sorted((a, c))), kind)
    for iid, it in ITEMS:
        for o in list(cn.GetConnectedTracks(it)) + list(cn.GetConnectedPads(it)):
            if uid(o) in ID: link(iid, ID[uid(o)])
    pieces = collections.defaultdict(list)               # zone index -> [(layer, piece index, polygon set, its bbox)]
    for zi, z in ZONES:
        for l in cu:
            if z.IsOnLayer(l):
                ps = z.GetFilledPolysList(l)
                for j in range(ps.OutlineCount()):
                    pc = ps.Subset(j, j + 1); pieces[zi].append((l, j, pc, pc.BBox()))
    pid = lambda zi, l, j: 'z%d/%s/%d' % (zi, LN[l], j)
    lost = 0
    for zi, z in ZONES:
        for o in list(cn.GetConnectedTracks(z)) + list(cn.GetConnectedPads(z)):
            iid = ID.get(uid(o))
            if not iid: continue
            ob = o.GetBoundingBox()
            hits = [pid(zi, l, j) for l, j, ps, bb in pieces[zi] if o.IsOnLayer(l) and bb.Intersects(ob) and ps.Collide(o.GetEffectiveShape(l))]
            for h in hits: link(iid, h)
            lost += not hits
    if lost: warn.append('%d item(s) KiCad connects to a zone collide with none of its fill pieces: left to the cluster check' % lost)
    same = collections.defaultdict(list)                 # (net, layer) -> its fill pieces
    for zi, z in ZONES:
        for l, j, ps, bb in pieces[zi]: same[(z.GetNetCode(), l)].append((zi, l, j, ps, bb))
    for grp in same.values():
        for (za, la, ja, pa, ba), (zc, lc, jc, pc, bc) in itertools.combinations(grp, 2):
            if za != zc and ba.Intersects(bc) and pa.Collide(pc): link(pid(za, la, ja), pid(zc, lc, jc))
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x]); x = parent[x]
        return x
    for a, c in links: parent[find(a)] = find(c)
    clusters, kc, unrec = [], {}, collections.Counter()
    try:
        if ITEMS: cn.GetConnectedItems(ITEMS[0][1])
        ask = True
    except TypeError:                                     # a KiCad whose python cannot ask for an item's cluster
        warn.append('links not checked against KiCad\'s clusters (GetConnectedItems not callable in KiCad %s)' % pcbnew.Version())
        ask = False
    for iid, it in ITEMS if ask else ():
        if iid in kc: continue
        mem = {iid}
        for o in cn.GetConnectedItems(it):
            if uid(o) in ID: mem.add(ID[uid(o)])
            elif o.GetClass() != 'ZONE' or o.GetParentFootprint(): unrec[o.GetClass()] += 1
        for j in mem: kc[j] = len(clusters)
        clusters.append(mem)
    split = 0
    for mem in clusters:
        roots = {}
        for j in sorted(mem): roots.setdefault(find(j), j)
        if len(roots) > 1:
            split += 1; first = min(roots.values())
            for j in roots.values():
                if j != first: link(first, j, 'cluster'); parent[find(j)] = find(first)
    if split:
        warn.append('%d KiCad cluster(s) joined through copper board.json does not record (%s): joined by a straight '
                    '"cluster" link' % (split, ', '.join('%d %s' % kv for kv in sorted(unrec.items())) or 'unknown items'))
    comps = collections.defaultdict(set)
    for j, k in kc.items(): comps[find(j)].add(k)
    merged = sum(len(ks) - 1 for ks in comps.values())
    if merged:
        warn.append('the links join %d pair(s) of copper that KiCad keeps apart (a fill piece chosen by collision)' % merged)
    return dict(source='KiCad %s connectivity' % pcbnew.Version(), unconnected=cn.GetUnconnectedCount(False),
                links=[[a, c] if k == 'touch' else [a, c, k] for (a, c), k in sorted(links.items())], warnings=warn)
if not args.no_connectivity:
    try:
        D['connectivity'] = connectivity()
    except Exception as e:                               # never lose the geometry the other scripts need to it
        print('  !! connectivity not recorded (%s: %s): decoupling.py will say NOT CHECKED' % (type(e).__name__, e), file=sys.stderr)
json.dump(D, open(os.path.join(pack, 'board.json'), 'w'))
C = D.get('connectivity') or dict(links=[], warnings=[])
print(len(D['footprints']), 'footprints', len(D['tracks']), 'tracks', len(D['vias']), 'vias', len(D['zones']), 'zones,', len(cu), 'copper layers,',
      len(C['links']), 'connectivity links')
for w in C['warnings']: print('  !! connectivity:', w)
