# Decoupling distance per IC power pin, by the copper path rather than by eye. Writes PACK/decoupling.json.
#   python decoupling.py PACK
# For every IC supply pin (pin type power_in/power_out, a supply pin name, or an untyped / passive pin on a net classed
# power - not a logic input strapped to a rail, such as EN or DIR tied to VIN) that has a
# capacitor to ground: the nearest same-net capacitor by path along the net's own copper - tracks,
# vias (the barrel span between the layers they join) and pours/planes (a straight line across the filled piece) -
# with the length on tracks, across planes and through vias, an inductance estimate (tracks: microstrip Z0 x
# sqrt(eps_eff) / c on their own layer and width; vias: 0.2 h (ln(4h/d) + 1); plane spreading not included), how many
# capacitors lie within the limit, and the distance from that capacitor's ground pad to the nearest ground via.
# Joins, by copper overlap (distance under the sum of the half-widths, strictly, as KiCad 10's BuildConnectivity was
# measured to do), at a track's ends or mid-way along it: two tracks whose centrelines come within w1/2 + w2/2 (a
# T-join, a crossing, a parallel run; joined at their closest points), a via within w/2 + size/2 of a track's
# centreline or size1/2 + size2/2 of another via, and a track or via closer than its half-width to a pad. A via joins
# only the layers it spans: a through via all of them; a blind, buried or micro via the run between the layers
# board.json records for it ("layers"; one without them is treated as through, with a warning).
# Not joined, although KiCad joins them (a false "no capacitor reachable" or a longer path; check such a pin by hand):
# a pad on a pour by thermal-relief spokes when the pad's centre lies outside the fill, and a track crossing a pour
# with no vertex inside it (a pour joins only points inside its filled piece); two pads whose copper overlaps with
# neither centre inside the other; copper touching an arc track beyond its two chords (arcs are a -> mid -> end).
# A rail that reaches its pins by tracks only (no plane) is where this matters most: allocate a decoupling site at each
# power pin at placement. review_config.json "decoupling": {"max_mm": 5, "ignore": ["U7"]} (defaults shown, none ignored).
import heapq, itertools
from common import *
from shapely.ops import nearest_points

DC = CFG.get('decoupling') or {}
MAXMM = float(DC.get('max_mm', 5.0))
IGNORE = set(DC.get('ignore', []))
SUPPLY_FN = re.compile(r'^(P|A|D|IO)?V(DD|CC|IN|BAT|SYS|REG|CORE|IO|USB|BUS|DDA|CCA)\w*$|^(A|D|IO|P)?VDD\w*$|^VREG\w*$|^V\d+V\d*$', re.I)
OUTER = LAYERS[0], LAYERS[-1]
ZL = {L: STACK[L]['z'] for L in LAYERS}

def fnname(pf, pin): return re.sub(r'~\{([^}]*)\}', r'\1', re.sub(r'_%s$' % re.escape(pin), '', pf or ''))

TOUCH = 5e-7    # mm: half KiCad's 1 nm grid. Shapes exactly r1 + r2 apart only touch, and KiCad does not join them

def touches(d, reach):
    """copper reach mm apart (the sum of the two half-widths) overlaps at distance d, as KiCad's connectivity has it"""
    return d < reach - TOUCH

SPANLESS = [v for v in B['vias'] if v.get('type_name') not in (None, 'through') and not v.get('layers')]
if SPANLESS:
    WARN.append('%d blind/buried/micro vias with no layer span in board.json, treated as through vias (they may join '
                'layers they do not reach)' % len(SPANLESS))

def via_span(v):
    """the copper layers a via joins, top to bottom: the run between the outermost layers board.json records for it
    (all of them for a through via, or one without a record)"""
    ix = sorted(LAYERS.index(L) for L in v.get('layers') or () if L in LAYERS)
    return LAYERS[ix[0]:ix[-1] + 1] if ix else list(LAYERS)

class NetGraph:
    """the copper of one net as a graph: nodes are points on a layer; edges carry (mm, kind, layer, width)"""
    def __init__(self, net):
        self.net = net; self.adj = collections.defaultdict(list); self.pos = {}; self.pieces = collections.defaultdict(list)
        self.padnode = collections.defaultdict(list)
        segs = collections.defaultdict(list)
        for t in B['tracks']:
            if t['net'] != net or t['a'] == t['b']: continue
            pts = [t['a'], t['m'], t['b']] if t.get('arc') else [t['a'], t['b']]
            for a, b in zip(pts, pts[1:]): segs[t['layer']].append((tuple(a), tuple(b), t['w']))
        vias = [(v, via_span(v)) for v in B['vias'] if v['net'] == net]
        pads = [(f, p, unary_union(polys(p['poly'])) if p['poly'] else Point(p['x'], p['y']).buffer(0.1))
                for f in B['footprints'] for p in f['pads'] if p['net'] == net]
        self.rad = {}                                            # node -> half-width of the copper there (pad joins)
        padjoin = collections.defaultdict(list)                  # pad index -> split points of tracks that touch it
        # Each segment is split wherever something's copper overlaps its own, as KiCad's connectivity does: a track
        # end (T-join), another track mid-span (crossing), a via on a layer it spans and a pad - at its ends or mid-way
        # along it (a via dropped on a straight run, or a track crossing it, has no vertex there).
        for L, ss in segs.items():
            ends = {}                                            # point copper on L: track ends and vias, by half-width
            for a, b, w in ss:
                for q in (a, b):
                    k = self.key(L, q); ends[k] = max(ends.get(k, 0.0), w / 2)
            for v, span in vias:
                if L in span:
                    k = self.key(L, (v['x'], v['y'])); ends[k] = max(ends.get(k, 0.0), v['size'] / 2)
            for k, r in ends.items(): self.rad[k] = max(self.rad.get(k, 0.0), r)
            lines = [LineString([a, b]) for a, b, w in ss]
            # Track to track, segment to segment: two segments closer than w1/2 + w2/2 join at their closest points
            # (the crossing point for crossing centrelines). Where that point is an end of either, the end join below
            # already holds it (an end's own half-width is at least its segment's), so only mid-span pairs are kept.
            xcut, xpairs = collections.defaultdict(list), []
            if len(ss) > 1:
                ii, jj = shapely.STRtree(lines).query(lines, predicate='dwithin', distance=max(w for _, _, w in ss))
                for i, j in zip(ii.tolist(), jj.tolist()):
                    if i >= j or not touches(lines[i].distance(lines[j]), (ss[i][2] + ss[j][2]) / 2): continue
                    p1, p2 = nearest_points(lines[i], lines[j])
                    d1, d2 = lines[i].project(p1), lines[j].project(p2)
                    if min(d1, d2) <= 1e-9 or d1 >= lines[i].length - 1e-9 or d2 >= lines[j].length - 1e-9: continue
                    xcut[i].append(d1); xcut[j].append(d2); xpairs.append((i, d1, j, d2))
            for si, (a, b, w) in enumerate(ss):
                line = lines[si]; cut = [0.0, line.length] + xcut[si]; joins = []; touched = []
                for k, r in ends.items():                        # track ends (T-joins) and vias overlapping this track
                    q = Point(self.pos[k][1])
                    if touches(line.distance(q), w / 2 + r): joins.append((line.project(q), k))
                for i, (f, p, pg) in enumerate(pads):            # pads this track's copper overlaps (joined below)
                    if L in p['layers'] and touches(line.distance(pg), w / 2):
                        near = line.intersection(pg.buffer(w / 2, quad_segs=32))
                        q = nearest_points(near, Point(p['x'], p['y']))[0] if not near.is_empty else nearest_points(line, pg)[0]
                        cut.append(line.project(q)); touched.append((i, line.project(q)))
                cut += [d for d, _ in joins]
                pts = [line.interpolate(d) for d in sorted({min(max(d, 0.0), line.length) for d in cut})]
                for p0, p1 in zip(pts, pts[1:]):
                    k0, k1 = self.key(L, (p0.x, p0.y)), self.key(L, (p1.x, p1.y))
                    if k0 != k1: self.edge(k0, k1, p0.distance(p1), 'track', L, w)
                for p0 in pts:
                    k0 = self.key(L, (p0.x, p0.y)); self.rad[k0] = max(self.rad.get(k0, 0.0), w / 2)
                for d, k in joins:                               # each joining end / via meets the track at its split point
                    p = line.interpolate(d); kk = self.key(L, (p.x, p.y))
                    if kk != k: self.edge(k, kk, p.distance(Point(self.pos[k][1])), 'track', L, w)
                for i, d in touched:
                    p = line.interpolate(d); padjoin[i].append(self.key(L, (p.x, p.y)))
            for i, d1, j, d2 in xpairs:                          # overlapping tracks meet at their split points
                p1, p2 = lines[i].interpolate(d1), lines[j].interpolate(d2)
                k1, k2 = self.key(L, (p1.x, p1.y)), self.key(L, (p2.x, p2.y))
                if k1 != k2: self.edge(k1, k2, p1.distance(p2), 'track', L, min(ss[i][2], ss[j][2]))
        self.vias = []
        for v, span in vias:                                     # the barrel, over the layers the via spans
            ks = [self.key(L, (v['x'], v['y'])) for L in span]
            for k in ks: self.rad[k] = max(self.rad.get(k, 0.0), v['size'] / 2)
            for k0, k1 in zip(ks, ks[1:]):
                self.edge(k0, k1, abs(ZL[self.pos[k1][0]] - ZL[self.pos[k0][0]]), 'via', None, v['drill'])
            self.vias.append((v, ks))
        for (v1, s1), (v2, s2) in itertools.combinations(vias, 2):   # overlapping vias, on the layers both span
            d = math.dist((v1['x'], v1['y']), (v2['x'], v2['y']))
            if touches(d, (v1['size'] + v2['size']) / 2):
                for L in s1:
                    if L in s2:
                        k1, k2 = self.key(L, (v1['x'], v1['y'])), self.key(L, (v2['x'], v2['y']))
                        if k1 != k2: self.edge(k1, k2, d, 'track', L, min(v1['size'], v2['size']))
        R = max(self.rad.values(), default=0.0)
        for i, (f, p, pg) in enumerate(pads):
            ks = [self.key(L, (p['x'], p['y'])) for L in p['layers']]
            for k0, k1 in zip(ks, ks[1:]):
                self.edge(k0, k1, abs(ZL[self.pos[k1][0]] - ZL[self.pos[k0][0]]), 'via', None, p['drill'] or 0.3)
            self.padnode[(f['ref'], str(p['num']))] += ks
            pw = max(min(*rect_dims(pg)), 0.1) if pg.area else 0.2
            x0, y0, x1, y1 = pg.bounds
            near = set(padjoin[i])
            for k2, (L2, q) in list(self.pos.items()):           # track ends, split points and vias overlapping the pad
                if x0 - R <= q[0] <= x1 + R and y0 - R <= q[1] <= y1 + R:
                    dq = pg.distance(Point(q))
                    if dq == 0 or touches(dq, self.rad.get(k2, 0.0)): near.add(k2)
            for k in ks:
                L = self.pos[k][0]
                for k2 in near:
                    if self.pos[k2][0] == L and k2 != k:
                        self.edge(k, k2, math.dist(self.pos[k2][1], (p['x'], p['y'])), 'track', L, pw)
        for L in LAYERS:                                         # pours / planes: every node inside a filled piece
            zf = zone_fill(net, L)
            if zf.is_empty: continue
            # keyed by (layer, index), not id(pc): .geoms hands out a new object each time, freed when pc moves on,
            # so a later piece can reuse its id and overwrite it (a pin left with "no capacitor reachable")
            for i, pc in enumerate(zf.geoms if hasattr(zf, 'geoms') else [zf]):
                pb = pc.buffer(0.05); shapely.prepare(pb)
                ks = [k for k, (L2, q) in self.pos.items() if L2 == L and pb.contains(Point(q))]
                if len(ks) > 1: self.pieces[(L, i)] = ks
        self.piece_of = collections.defaultdict(list)
        for pid, ks in self.pieces.items():
            for k in ks: self.piece_of[k].append(pid)

    def key(self, L, p):
        k = (L, round(p[0], 3), round(p[1], 3))
        self.pos.setdefault(k, (L, (round(p[0], 3), round(p[1], 3))))
        return k

    def edge(self, a, b, mm, kind, L, w):
        self.adj[a].append((b, mm, kind, L, w)); self.adj[b].append((a, mm, kind, L, w))

    def paths(self, src):
        """Dijkstra from the nodes src: {node: (mm, parts)} with parts = [(kind, layer, width, mm), ...]"""
        dist, prev, h = {}, {}, []
        for s in src: heapq.heappush(h, (0.0, s)); dist[s] = 0.0
        while h:
            d, u = heapq.heappop(h)
            if d > dist.get(u, 1e18) + 1e-12: continue
            nb = list(self.adj[u])
            for pid in self.piece_of.get(u, []):
                q0 = self.pos[u][1]
                nb += [(k, math.dist(q0, self.pos[k][1]), 'plane', self.pos[u][0], None) for k in self.pieces[pid] if k != u]
            for v, mm, kind, L, w in nb:
                nd = d + mm
                if nd < dist.get(v, 1e18) - 1e-12:
                    dist[v] = nd; prev[v] = (u, kind, L, w, mm); heapq.heappush(h, (nd, v))
        return dist, prev

def unwind(prev, k):
    parts = []
    while k in prev:
        u, kind, L, w, mm = prev[k]; parts.append((kind, L, w, mm)); k = u
    return parts[::-1]

def inductance(parts):
    nh = 0.0
    for kind, L, w, mm in parts:
        if kind == 'track' and L:
            h = neighbours(L)[0][1] if neighbours(L) else 1.0
            nh += nh_per_mm(max(w or 0.2, 0.05), h) * mm
        elif kind == 'via':
            nh += via_nh(mm, w or 0.3)
    return nh

gvias = [(v['x'], v['y']) for v in B['vias'] if v['net'] in GND] + [(p['x'], p['y']) for f in B['footprints'] for p in f['pads'] if p['net'] in GND and p['th']]
rows, skipped, graphs = [], [], {}
for ref, c in sorted(NL['components'].items(), key=lambda kv: natkey(kv[0])):
    if (TOPO.kind.get(ref) if TOPO else ('ic' if ref.startswith('U') else '')) != 'ic' or ref in IGNORE or ref not in FP: continue
    for pin, (net, pf, pt) in sorted(c['pins'].items(), key=lambda kv: natkey(kv[0])):
        if not net or net in GND or net.startswith('unconnected-'): continue
        fn = fnname(pf, pin)
        logic = pt.split('+')[0] in ('input', 'output', 'bidirectional', 'tri_state', 'open_collector', 'open_emitter')
        supply = pt.split('+')[0] in ('power_in', 'power_out') or bool(SUPPLY_FN.match(fn)) or (cls(net) == 'power' and not logic)
        if not supply: continue
        caps = TOPO.caps_to_ground(net) if TOPO else []
        caps = [r for r in caps if r in FP]
        if not caps: skipped.append('%s.%s (%s): no capacitor between it and ground' % (ref, pin, net)); continue
        if net not in graphs: graphs[net] = NetGraph(net)
        G = graphs[net]
        src = G.padnode.get((ref, str(pin)), [])
        row = dict(ic=ref, value=c.get('value', ''), pin=pin, fn=fn, net=net, plane=any(not zone_fill(net, L).is_empty for L in LAYERS))
        if not src: row.update(status='NOT CHECKED: pin pad not on the board'); rows.append(row); continue
        dist, prev = G.paths(src)
        found = []
        for cr in caps:
            cp = next((p for p in FP[cr]['pads'] if p['net'] == net), None)
            ks = G.padnode.get((cr, str(cp['num'])), []) if cp else []
            best = min(((dist[k], k) for k in ks if k in dist), default=None)
            if best: found.append((best[0], cr, best[1], cp))
        if not found:
            row.update(status='FAIL: no capacitor reachable on %s copper from this pin (%d on the net; a pin joined only by '
                              'thermal-relief spokes or overlapping pads is not seen: check it before reporting)' % (net, len(caps)))
            rows.append(row); continue
        found.sort()
        mm, cr, k, cp = found[0]
        parts = unwind(prev, k)
        tr = sum(p[3] for p in parts if p[0] == 'track'); pl = sum(p[3] for p in parts if p[0] == 'plane')
        nv = sum(1 for p in parts if p[0] == 'via')
        gp = next((p for p in FP[cr]['pads'] if p['net'] in GND), None)
        gdist = min((math.dist((gp['x'], gp['y']), q) for q in gvias), default=None) if gp else None
        row.update(cap=cr, cap_value=NL['components'].get(cr, {}).get('value', ''), path_mm=round(mm, 2), track_mm=round(tr, 2),
                   plane_mm=round(pl, 2), via_hops=nv, est_nH=round(inductance(parts), 2),
                   caps_within=sum(1 for f_ in found if f_[0] <= MAXMM), caps_on_net=len(caps),
                   cap_gnd_via_mm=round(gdist, 2) if gdist is not None else None,
                   straight_mm=round(min(math.dist((p['x'], p['y']), (cp['x'], cp['y'])) for p in FP[ref]['pads'] if str(p['num']) == str(pin)), 1))
        flag = []
        if tr > MAXMM: flag.append('%.1f mm of track to the nearest capacitor (limit %.1f)' % (tr, MAXMM))
        if gdist is not None and gdist > 1.5 and not any(p['th'] for p in FP[cr]['pads']): flag.append('capacitor ground pad %.1f mm from a ground via' % gdist)
        row['status'] = ('FLAG: ' + '; '.join(flag)) if flag else 'ok'
        rows.append(row)
flagged = [r for r in rows if not r['status'].startswith('ok')]
for r in flagged:
    if r['status'].startswith(('FAIL', 'NOT')): WARN.append('decoupling %s.%s (%s): %s' % (r['ic'], r['pin'], r['net'], r['status']))
json.dump(dict(coverage=dict(warnings=WARN, max_mm=MAXMM, pins=len(rows), flagged=len(flagged), skipped=skipped,
                             method='path along the net\'s copper (tracks, vias, straight lines across filled pieces); inductance '
                                    'from microstrip per-length L on each track and the via barrels; plane spreading and the '
                                    'capacitor\'s own mounting are not included'),
               pins=rows), open(PACK + 'decoupling.json', 'w'), indent=1)
for w in WARN: print('  !!', w)
print('decoupling ok: %d IC supply pins, %d flagged (limit %.1f mm of track)' % (len(rows), len(flagged), MAXMM))
