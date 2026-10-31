# Decoupling distance per IC power pin, by the copper path rather than by eye. Writes PACK/decoupling.json.
#   python decoupling.py PACK
# For every IC supply pin (pin type power_in/power_out, a supply pin name, or an untyped / passive pin on a net classed
# power - not a logic input strapped to a rail, such as EN or DIR tied to VIN) that has a
# capacitor to ground: the nearest same-net capacitor by path along the net's own copper - tracks,
# vias (the barrel span between the layers they join) and pours/planes (a straight line across the filled piece) -
# with the length on tracks, across planes and through vias, an inductance estimate (tracks: microstrip Z0 x
# sqrt(eps_eff) / c on their own layer and width; vias: 0.2 h (ln(4h/d) + 1); plane spreading not included), how many
# capacitors lie within the limit, and the distance from that capacitor's ground pad to the nearest ground via.
# What joins what is KiCad's own connectivity, which boarddump.py records (board.json "connectivity": the links behind
# the ratsnest and DRC's unconnected items, with thermal-relief spokes, tracks across a pour, overlapping pads, copper
# touching an arc and vias on the layers they span). This script only places the touch points and measures: two
# tracks meet at their closest points, a via or pad at the point of the track nearest its centre; a via or pad joins a
# fill piece at its centre and a track where its centreline enters and leaves the piece (or at its point nearest the
# piece); arcs are measured along the arc. So a FAIL "no capacitor reachable" is a pin that DRC also reports
# unconnected from them, and the coverage compares the links' unconnected count with KiCad's and DRC's.
# A board.json without "connectivity" (from an older boarddump.py) is NOT CHECKED: re-run make_pack.sh.
# A rail that reaches its pins by tracks only (no plane) is where this matters most: allocate a decoupling site at each
# power pin at placement. review_config.json "decoupling": {"max_mm": 5, "ignore": ["U7"]} (defaults shown, none ignored).
import heapq
from common import *
from shapely.ops import nearest_points

DC = CFG.get('decoupling') or {}
MAXMM = float(DC.get('max_mm', 5.0))
IGNORE = set(DC.get('ignore', []))
SUPPLY_FN = re.compile(r'^(P|A|D|IO)?V(DD|CC|IN|BAT|SYS|REG|CORE|IO|USB|BUS|DDA|CCA)\w*$|^(A|D|IO|P)?VDD\w*$|^VREG\w*$|^V\d+V\d*$', re.I)
ZL = {L: STACK[L]['z'] for L in LAYERS}

def fnname(pf, pin): return re.sub(r'~\{([^}]*)\}', r'\1', re.sub(r'_%s$' % re.escape(pin), '', pf or ''))

# board.json items by the ids boarddump.py gives them in "connectivity": t<i> tracks[i], v<i> vias[i],
# p<f>.<k> footprints[f].pads[k], z<i>/<layer>/<j> piece j of zones[i].filled[layer]
ITEM, NET_ITEMS = {}, collections.defaultdict(list)
for i, t in enumerate(B['tracks']): ITEM['t%d' % i] = ('t', t['net'], t)
for i, v in enumerate(B['vias']): ITEM['v%d' % i] = ('v', v['net'], v)
for fi, f in enumerate(B['footprints']):
    for k, p in enumerate(f['pads']): ITEM['p%d.%d' % (fi, k)] = ('p', p['net'], (f, p))
for zi, z in enumerate(B['zones']):
    for L, pl in z['filled'].items():
        for j, pc in enumerate(pl): ITEM['z%d/%s/%d' % (zi, L, j)] = ('z', z['net'], (L, pc))
for iid, (k, net, o) in ITEM.items(): NET_ITEMS[net].append(iid)
CONN = B.get('connectivity')
LINKS = collections.defaultdict(list)                    # net -> [(id, id, kind)]; kind "cluster": joined via copper
if CONN:                                                 # board.json does not record (see boarddump.py)
    bad = [l for l in CONN['links'] if l[0] not in ITEM or l[1] not in ITEM or ITEM[l[0]][1] != ITEM[l[1]][1]]
    if bad: WARN.append('%d connectivity links name items not in board.json or on two nets (edited by hand?): ignored' % len(bad))
    for l in CONN['links']:
        if l not in bad: LINKS[ITEM[l[0]][1]].append((l[0], l[1], l[2] if len(l) > 2 else 'touch'))
    WARN += ['board.json connectivity: ' + w for w in CONN.get('warnings', [])]
else:
    WARN.append('board.json has no "connectivity" (written by an older boarddump.py): decoupling NOT CHECKED - re-run make_pack.sh')

def find(grp, x):
    """union-find root of x in grp (path halving)"""
    while grp[x] != x: grp[x] = grp[grp[x]]; x = grp[x]
    return x

def entries(line, poly):
    """distances along a track's centreline where it enters and leaves a fill piece (its ends, if they lie inside),
    or to its point nearest the piece when only the track's edge reaches it"""
    g = line.intersection(poly); ds = set()
    for part in getattr(g, 'geoms', [g]):
        if not part.is_empty and part.geom_type in ('LineString', 'Point'):
            ds |= {line.project(Point(q)) for q in (part.coords[0], part.coords[-1])}
    return ds or {line.project(nearest_points(line, poly)[0])}

class NetGraph:
    """the copper of one net as a graph built from KiCad's links. Nodes are (item, layer, x, y), so nothing joins that
    KiCad does not join; edges carry (mm, kind, layer, width). A fill piece joins every node attached to it by a
    straight line across it (paths() adds those edges as it goes)."""
    def __init__(self, net):
        self.adj = collections.defaultdict(list); self.pos = {}; self.padnode = collections.defaultdict(list)
        self.line, self.at, self.cut, self.poly, self.pw = {}, {}, {}, {}, {}
        self.loose = 0                                   # links with no layer in common to touch on: joined straight
        members, grp = collections.defaultdict(set), {}
        for iid in NET_ITEMS[net]:
            k, _, o = ITEM[iid]
            if k == 't':
                self.line[iid] = centreline(o); self.cut[iid] = {0.0, self.line[iid].length}
            elif k == 'v':                               # the barrel, over the layers the via spans
                self.at[iid] = {L: self.key(iid, L, (o['x'], o['y'])) for L in via_span(o)}
                ks = list(self.at[iid].values())
                for k0, k1 in zip(ks, ks[1:]):
                    self.edge(k0, k1, abs(ZL[self.pos[k1][0]] - ZL[self.pos[k0][0]]), 'via', None, o['drill'])
            elif k == 'p':
                f, p = o
                self.at[iid] = {L: self.key(iid, L, (p['x'], p['y'])) for L in LAYERS if L in p['layers']}
                ks = list(self.at[iid].values())
                for k0, k1 in zip(ks, ks[1:]):
                    self.edge(k0, k1, abs(ZL[self.pos[k1][0]] - ZL[self.pos[k0][0]]), 'via', None, p['drill'] or 0.3)
                self.padnode[(f['ref'], str(p['num']))] += ks
                pg = unary_union(polys(p['poly'])) if p['poly'] else Point(p['x'], p['y']).buffer(0.1)
                self.poly[iid] = pg; self.pw[iid] = max(min(*rect_dims(pg)), 0.1) if pg.area else 0.2
            else:
                self.poly[iid] = unary_union(polys([o[1]])); grp[iid] = iid
        rank = dict(t=0, v=1, p=2, z=3)
        for a, b, kind in LINKS[net]:
            if rank[ITEM[a][0]] > rank[ITEM[b][0]]: a, b = b, a
            if ITEM[a][0] == ITEM[b][0] == 'z': grp[find(grp, a)] = find(grp, b); continue
            if kind == 'touch' and self.touch(a, b, members): continue
            self.loose += kind == 'touch'
            self.straight(a, b, members)
        for tid, line in self.line.items():              # each track, split at every point something touches it
            L, w = ITEM[tid][2]['layer'], ITEM[tid][2]['w']; ds = sorted(self.cut[tid])
            for d0, d1 in zip(ds, ds[1:]):
                k0, k1 = self.tnode(tid, d0), self.tnode(tid, d1)
                if k0 != k1: self.edge(k0, k1, d1 - d0, 'track', L, w)
        self.pieces = collections.defaultdict(set)
        for pid, ks in members.items(): self.pieces[find(grp, pid)] |= ks
        self.piece_of = collections.defaultdict(list)
        for pid, ks in self.pieces.items():
            for k in ks: self.piece_of[k].append(pid)

    def key(self, iid, L, p):
        k = (iid, L, round(p[0], 3), round(p[1], 3))
        self.pos.setdefault(k, (L, (round(p[0], 3), round(p[1], 3))))
        return k

    def tnode(self, tid, d):
        """the node d mm along track tid (the track is split there)"""
        line = self.line[tid]; d = min(max(d, 0.0), line.length); self.cut[tid].add(d)
        q = line.interpolate(d); return self.key(tid, ITEM[tid][2]['layer'], (q.x, q.y))

    def touch(self, a, b, members):
        """place the touch KiCad reports between items a and b (a ranked before b: track, via, pad, fill piece)"""
        ka, kb, oa, ob = ITEM[a][0], ITEM[b][0], ITEM[a][2], ITEM[b][2]
        if ka == 't':
            L, la = oa['layer'], self.line[a]
            if kb == 't':                                # a T-join, a crossing, a parallel run: the closest points
                pa, pb = nearest_points(la, self.line[b])
                self.edge(self.tnode(a, la.project(pa)), self.tnode(b, self.line[b].project(pb)), pa.distance(pb), 'track', L,
                          min(oa['w'], ob['w']))
            elif kb in 'vp':                             # a via or pad: the point of the track nearest its centre
                if L not in self.at[b]: return False
                c = Point(self.pos[self.at[b][L]][1])
                if kb == 'p':                            # (within the pad, for a track running across it)
                    near = la.intersection(self.poly[b].buffer(oa['w'] / 2, quad_segs=32))
                    d = la.project(nearest_points(near, c)[0] if not near.is_empty else nearest_points(la, self.poly[b])[0])
                else:
                    d = la.project(c)
                self.edge(self.tnode(a, d), self.at[b][L], c.distance(la.interpolate(d)), 'track', L,
                          self.pw[b] if kb == 'p' else oa['w'])
            else:                                        # a fill piece: where the centreline enters and leaves it
                if ob[0] != L or self.poly[b].is_empty: return False
                members[b] |= {self.tnode(a, d) for d in entries(la, self.poly[b])}
            return True
        if kb == 'z':                                    # a via or pad on a fill piece: at its centre
            if ob[0] not in self.at[a]: return False
            members[b].add(self.at[a][ob[0]]); return True
        common = [L for L in self.at[a] if L in self.at[b]]
        w = min(self.pw[a], self.pw[b]) if ka == 'p' else self.pw[b] if kb == 'p' else min(oa['size'], ob['size'])
        for L in common:                                 # via / pad to via / pad, on each layer both are on
            self.edge(self.at[a][L], self.at[b][L], math.dist(self.pos[self.at[a][L]][1], self.pos[self.at[b][L]][1]), 'track', L, w)
        return bool(common)

    def straight(self, a, b, members):
        """a join with nothing to place it on (KiCad joins a and b through copper board.json does not record, or on no
        layer they share): a straight line between their nearest nodes, a "join" - in the path length, not in the
        track length or the inductance"""
        ends = lambda i: ([self.tnode(i, 0.0), self.tnode(i, self.line[i].length)] if ITEM[i][0] == 't' else list(self.at[i].values()))
        ea = ends(a)
        if not ea or (ITEM[b][0] != 'z' and not ends(b)): return           # a pad on no copper layer
        if ITEM[b][0] == 'z':                            # on the piece's own layer if a reaches it
            members[b].add(next((k for k in ea if self.pos[k][0] == ITEM[b][2][0]), ea[0])); return
        k0, k1 = min(((p, q) for p in ea for q in ends(b)), key=lambda pq: math.dist(self.pos[pq[0]][1], self.pos[pq[1]][1]))
        self.edge(k0, k1, math.dist(self.pos[k0][1], self.pos[k1][1]), 'join', None, None)

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

def unconnected():
    """the ratsnest the links leave, as KiCad counts it: per net, its separate pieces of copper less one, where fill
    alone (no pad, track or via on it: an island kept on purpose) is not a piece to connect"""
    n = 0
    for net, ids in NET_ITEMS.items():
        if not net: continue
        grp = {i: i for i in ids}
        for a, b, _ in LINKS[net]: grp[find(grp, a)] = find(grp, b)
        n += max(len({find(grp, i) for i in ids if ITEM[i][0] != 'z'}) - 1, 0)
    return n

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
        row = dict(ic=ref, value=c.get('value', ''), pin=pin, fn=fn, net=net, plane=any(not zone_fill(net, L).is_empty for L in LAYERS))
        if not CONN: row.update(status='NOT CHECKED: board.json has no connectivity'); rows.append(row); continue
        if net not in graphs: graphs[net] = NetGraph(net)
        G = graphs[net]
        src = G.padnode.get((ref, str(pin)), [])
        if not src: row.update(status='NOT CHECKED: pin pad not on the board'); rows.append(row); continue
        dist, prev = G.paths(src)
        found = []
        for cr in caps:
            cp = next((p for p in FP[cr]['pads'] if p['net'] == net), None)
            ks = G.padnode.get((cr, str(cp['num'])), []) if cp else []
            best = min(((dist[k], k) for k in ks if k in dist), default=None)
            if best: found.append((best[0], cr, best[1], cp))
        if not found:
            row.update(status='FAIL: no capacitor reachable on %s copper from this pin (%d on the net; KiCad\'s connectivity '
                              'keeps this pin\'s copper apart from theirs, so DRC reports the net unconnected)' % (net, len(caps)))
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
loose = sum(G.loose for G in graphs.values())
if loose: WARN.append('%d KiCad joins with no layer the two items share: measured as a straight line' % loose)
conn = None
if CONN:
    drc = json.load(open(PACK + 'drc.json')) if os.path.exists(PACK + 'drc.json') else None
    conn = dict(source=CONN.get('source'), links=len(CONN['links']), unconnected_links=unconnected(),
                unconnected_kicad=CONN.get('unconnected'), unconnected_drc=len(drc.get('unconnected_items', [])) if drc else None)
    if len({v for k, v in conn.items() if k.startswith('unconnected_') and v is not None}) > 1:
        WARN.append('connectivity: the links leave %(unconnected_links)s unconnected, KiCad %(unconnected_kicad)s, DRC '
                    '%(unconnected_drc)s - the paths below may not be the copper DRC checked' % conn)
flagged = [r for r in rows if not r['status'].startswith('ok')]
for r in flagged:
    if CONN and r['status'].startswith(('FAIL', 'NOT')): WARN.append('decoupling %s.%s (%s): %s' % (r['ic'], r['pin'], r['net'], r['status']))
json.dump(dict(coverage=dict(warnings=WARN, max_mm=MAXMM, pins=len(rows), flagged=len(flagged), skipped=skipped, connectivity=conn,
                             method='path along the net\'s copper as KiCad connects it (tracks, vias, straight lines across '
                                    'filled pieces); inductance '
                                    'from microstrip per-length L on each track and the via barrels; plane spreading and the '
                                    'capacitor\'s own mounting are not included'),
               pins=rows), open(PACK + 'decoupling.json', 'w'), indent=1)
for w in WARN: print('  !!', w)
print('decoupling ok: %d IC supply pins, %d flagged (limit %.1f mm of track)' % (len(rows), len(flagged), MAXMM))
