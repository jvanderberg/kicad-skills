# Decoupling distance per IC power pin, by the copper path rather than by eye. Writes PACK/decoupling.json.
#   python decoupling.py PACK
# For every IC pin on a supply net (pin type power_in/power_out, a supply pin name, or a net classed power) that has a
# capacitor to ground: the nearest same-net capacitor by path along the net's own copper - tracks (T-joins split),
# vias (the barrel span between the layers they join) and pours/planes (a straight line across the filled piece) -
# with the length on tracks, across planes and through vias, an inductance estimate (tracks: microstrip Z0 x
# sqrt(eps_eff) / c on their own layer and width; vias: 0.2 h (ln(4h/d) + 1); plane spreading not included), how many
# capacitors lie within the limit, and the distance from that capacitor's ground pad to the nearest ground via.
# A rail that reaches its pins by tracks only (no plane) is where this matters most: allocate a decoupling site at each
# power pin at placement. review_config.json "decoupling": {"max_mm": 5, "ignore": ["U7"]} (defaults shown, none ignored).
import heapq
from common import *

DC = CFG.get('decoupling') or {}
MAXMM = float(DC.get('max_mm', 5.0))
IGNORE = set(DC.get('ignore', []))
SUPPLY_FN = re.compile(r'^(P|A|D|IO)?V(DD|CC|IN|BAT|SYS|REG|CORE|IO|USB|BUS|DDA|CCA)\w*$|^(A|D|IO|P)?VDD\w*$|^VREG\w*$|^V\d+V\d*$', re.I)
OUTER = LAYERS[0], LAYERS[-1]
ZL = {L: STACK[L]['z'] for L in LAYERS}

def fnname(pf, pin): return re.sub(r'~\{([^}]*)\}', r'\1', re.sub(r'_%s$' % re.escape(pin), '', pf or ''))

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
        for L, ss in segs.items():
            ends = {self.key(L, p) for a, b, _ in ss for p in (a, b)}
            for a, b, w in ss:
                line = LineString([a, b]); cut = [0.0, line.length]
                for k in ends:                                   # T-joins: another track ends on this one's interior
                    q = self.pos[k][1]
                    if line.distance(Point(q)) <= w / 2 + 1e-6:
                        d = line.project(Point(q))
                        if 1e-6 < d < line.length - 1e-6: cut.append(d)
                cut = sorted(set(cut))
                pts = [line.interpolate(d) for d in cut]
                for p0, p1 in zip(pts, pts[1:]):
                    k0, k1 = self.key(L, (p0.x, p0.y)), self.key(L, (p1.x, p1.y))
                    self.edge(k0, k1, p0.distance(p1), 'track', L, w)
                for k in ends:                                   # an end on the interior joins at the split point
                    q = Point(self.pos[k][1])
                    if line.distance(q) <= w / 2 + 1e-6:
                        p = line.interpolate(line.project(q)); kk = self.key(L, (p.x, p.y))
                        if kk != k: self.edge(k, kk, p.distance(q), 'track', L, w)
        self.vias = []
        for i, v in enumerate(B['vias']):
            if v['net'] != net: continue
            ks = [self.key(L, (v['x'], v['y'])) for L in LAYERS]
            for k0, k1 in zip(ks, ks[1:]):
                self.edge(k0, k1, abs(ZL[self.pos[k1][0]] - ZL[self.pos[k0][0]]), 'via', None, v['drill'])
            self.vias.append((v, ks))
        for f in B['footprints']:
            for p in f['pads']:
                if p['net'] != net: continue
                ks = [self.key(L, (p['x'], p['y'])) for L in p['layers']]
                for k0, k1 in zip(ks, ks[1:]):
                    self.edge(k0, k1, abs(ZL[self.pos[k1][0]] - ZL[self.pos[k0][0]]), 'via', None, p['drill'] or 0.3)
                self.padnode[(f['ref'], str(p['num']))] += ks
                pg = unary_union(polys(p['poly'])) if p['poly'] else Point(p['x'], p['y']).buffer(0.1)
                for k in ks:                                     # track ends and vias on the pad join it
                    L = self.pos[k][0]
                    for k2, (L2, q) in list(self.pos.items()):
                        if L2 == L and k2 != k and pg.buffer(0.01).contains(Point(q)):
                            self.edge(k, k2, math.dist(q, (p['x'], p['y'])), 'track', L, max(min(*rect_dims(pg)), 0.1) if pg.area else 0.2)
        for L in LAYERS:                                         # pours / planes: every node inside a filled piece
            zf = zone_fill(net, L)
            if zf.is_empty: continue
            for pc in (zf.geoms if hasattr(zf, 'geoms') else [zf]):
                shapely.prepare(pc)
                ks = [k for k, (L2, q) in self.pos.items() if L2 == L and pc.buffer(0.05).contains(Point(q))]
                if len(ks) > 1: self.pieces[id(pc)] = ks
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
        supply = pt.split('+')[0] in ('power_in', 'power_out') or bool(SUPPLY_FN.match(fn)) or cls(net) == 'power'
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
            row.update(status='FAIL: no capacitor reachable on %s copper from this pin (%d on the net)' % (net, len(caps)))
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
