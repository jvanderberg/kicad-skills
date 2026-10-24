# EMC / SI geometry checks. Writes PACK/emc.json.   python emc.py PACK
#  - reference continuity: for every signal track, what lies under it on the nearest copper layer (ground, another net's
#    pour, or nothing), sampled every 0.1 mm; spans off ground are listed with coordinates
#  - crosstalk: parallel runs of fast nets with neighbours on the same layer (edge) and the adjacent layer (broadside)
#  - layer changes: signal vias, the layers they join and the distance to the nearest ground via (return-current path)
#  - edge proximity of fast nets, switching-node copper area, hot loops (IC pin -> input cap -> ground pin)
#  - fast-net inventory with closed-form microstrip Z0, and differential pair length/skew
# Net classes come from review_config.json "net_classes" (regex -> class); classes in "fast_classes" get the full checks.
from shapely.strtree import STRtree
from common import *

def z0_microstrip(w, h, er=ER):
    u = w / h
    if u < 1:
        ee = (er + 1) / 2 + (er - 1) / 2 * ((1 + 12 / u) ** -0.5 + 0.04 * (1 - u) ** 2)
        return 60 / math.sqrt(ee) * math.log(8 / u + u / 4)
    ee = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / u) ** -0.5
    return 120 * math.pi / (math.sqrt(ee) * (u + 1.393 + 0.667 * math.log(u + 1.444)))

REF = {L: [o for o, _ in neighbours(L)] for L in LAYERS}
H = {L: neighbours(L)[0][1] if neighbours(L) else 1.5 for L in LAYERS}
refgeo = {}
for L in LAYERS:
    zf = all_zone_fill(L)
    g = unary_union([zf.get(n, Polygon()) for n in GND])
    refgeo[L] = dict(gnd=g, core=g.buffer(-0.2) if not g.is_empty else g, other={n: v for n, v in zf.items() if n not in GND and not v.is_empty})
def classify(L, xs, ys):
    r = refgeo[L]; out = np.array(['void'] * len(xs), dtype=object)
    for n, g in r['other'].items(): out[shapely.contains_xy(g, xs, ys)] = n
    out[shapely.contains_xy(r['gnd'], xs, ys)] = 'GND_edge'; out[shapely.contains_xy(r['core'], xs, ys)] = 'GND'
    return out

sig_tracks = [t for t in B['tracks'] if cls(t['net']) != 'power']
_op = collections.defaultdict(list)
for f in B['footprints']:
    for p in f['pads']:
        if p['th'] and p['net']: _op[p['net']].append(Point(p['x'], p['y']).buffer(max(p['drill'], 0.3) / 2 + 1.0))
for v in B['vias']: _op[v['net']].append(Point(v['x'], v['y']).buffer(v['drill'] / 2 + 0.6))
own_pads = {k: unary_union(v) for k, v in _op.items()}
ref_report = collections.defaultdict(lambda: dict(len=collections.Counter(), spans=[]))
for t in sig_tracks:
    if not REF[t['layer']]: continue
    a, b = np.array(t['a']), np.array(t['b']); d = float(np.linalg.norm(b - a))
    k = max(int(d / 0.1), 1); s = np.linspace(0, 1, k + 1); P = a[None, :] + (b - a)[None, :] * s[:, None]
    c = classify(REF[t['layer']][0], P[:, 0], P[:, 1])
    rec = ref_report[(t['net'], t['layer'])]
    for v in c: rec['len'][v] += d / len(c)
    i = 0
    while i < len(c):
        j = i
        while j + 1 < len(c) and c[j + 1] == c[i]: j += 1
        L_ = (j - i + 1) * d / len(c)
        if c[i] != 'GND' and L_ >= 0.15:
            seg = LineString([P[i], P[j]]) if j > i else Point(P[i])
            entry = bool(t['net'] in own_pads and seg.distance(own_pads[t['net']]) < 0.05 and seg.length < 1.6)   # expected antipad gap
            rec['spans'].append(dict(ref=c[i], len=round(L_, 2), at=[round(P[i, 0], 2), round(P[i, 1], 2)], to=[round(P[j, 0], 2), round(P[j, 1], 2)], pad_entry=entry))
            if entry: rec['len']['pad_entry'] += L_; rec['len'][c[i]] -= L_
        i = j + 1
refout = []
for (net, L), rec in sorted(ref_report.items(), key=lambda kv: natkey(kv[0][0])):
    refout.append(dict(net=net, cls=cls(net), layer=L, ref_layer=REF[L][0], length=round(sum(rec['len'].values()), 2), over_gnd=round(rec['len']['GND'], 2),
                       not_over_gnd={k: round(v, 2) for k, v in rec['len'].items() if k not in ('GND', 'pad_entry') and v > 0.05},
                       spans=sorted([x for x in rec['spans'] if not x['pad_entry']], key=lambda s: -s['len'])[:8]))

segs = [(t, LineString([t['a'], t['b']])) for t in sig_tracks if t['a'] != t['b']]
def ang(t): return math.atan2(t['b'][1] - t['a'][1], t['b'][0] - t['a'][0]) % math.pi
def overlap_len(l1, t2):
    p = [l1.project(Point(q)) for q in (t2['a'], t2['b'])]
    return max(min(max(p), l1.length) - max(min(p), 0), 0)
bylayer = collections.defaultdict(list)
for t, l in segs: bylayer[t['layer']].append((t, l))
trees = {L: STRtree([l for _, l in v]) for L, v in bylayer.items()}
pairs = collections.defaultdict(lambda: dict(len=0.0, min_gap=9.9, min_ctr=9.9))
for L, items in bylayer.items():
    adj = [L] + [o for o, h in neighbours(L) if h < 0.3]     # broadside only to a close neighbour
    for t1, l1 in items:
        if cls(t1['net']) not in FAST: continue
        for L2 in adj:
            if L2 not in trees: continue
            for j in trees[L2].query(l1.buffer(0.8)):
                t2, l2 = bylayer[L2][j]
                if t2['net'] == t1['net']: continue
                da = abs(ang(t1) - ang(t2)); da = min(da, math.pi - da)
                if da > math.radians(20): continue
                ov = overlap_len(l1, t2)
                if ov < 0.3: continue
                ctr = l1.distance(l2.interpolate(0.5, normalized=True))
                pr = pairs[(t1['net'], t2['net'], L, L2)]; pr['len'] += ov; pr['min_ctr'] = min(pr['min_ctr'], ctr)
                if L2 == L: pr['min_gap'] = min(pr['min_gap'], ctr - (t1['w'] + t2['w']) / 2)
                pr.setdefault('at', [round(l1.coords[0][0], 2), round(l1.coords[0][1], 2)])
xt = []; seen = set()
for (n1, n2, L, L2), pr in sorted(pairs.items(), key=lambda kv: -kv[1]['len']):
    if L == L2:                      # same-layer pairs are found from both ends: keep one
        if (n2, n1, L) in seen: continue
        seen.add((n1, n2, L))
    hh = H[L]; D = pr['min_ctr']; k = 1 / (1 + (D / hh) ** 2) if D > 0 else 1.0
    if pr['len'] < 2.0 and k < 0.2: continue
    xt.append(dict(net=n1, other=n2, cls=[cls(n1), cls(n2)], layer=L, other_layer=L2, kind='edge' if L == L2 else 'broadside', coupled_mm=round(pr['len'], 1),
                   min_centre_mm=round(D, 3), min_gap_mm=round(pr['min_gap'], 3) if L == L2 else None, coupling_k=round(k, 3), next_est_pct=round(25 * k, 1), at=pr['at']))
xt.sort(key=lambda r: -(r['coupled_mm'] * r['coupling_k']))

gpts = np.array([(v['x'], v['y']) for v in B['vias'] if v['net'] in GND] + [(p['x'], p['y']) for f in B['footprints'] for p in f['pads'] if p['net'] in GND and p['th']] or [(1e9, 1e9)])
gtree = STRtree(shapely.points(gpts))
tr_end = collections.defaultdict(set)
for t in B['tracks']:
    for q in (t['a'], t['b']): tr_end[(t['net'], round(q[0], 2), round(q[1], 2))].add(t['layer'])
vchg = []
for v in B['vias']:
    if cls(v['net']) == 'power': continue
    ls = sorted(tr_end.get((v['net'], round(v['x'], 2), round(v['y'], 2)), set()), key=LAYERS.index)
    i = gtree.nearest(Point(v['x'], v['y']))
    vchg.append(dict(net=v['net'], cls=cls(v['net']), at=[round(v['x'], 2), round(v['y'], 2)], layers=ls,
                     ref_layers=sorted({REF[L][0] for L in ls if REF[L]}), nearest_gnd_via_mm=round(math.dist(gpts[i], (v['x'], v['y'])), 2)))

ring = unary_union([p.exterior for p in (EDGE.geoms if hasattr(EDGE, 'geoms') else [EDGE])])
edge = [dict(net=t['net'], layer=t['layer'], dist_mm=round(track_geom(t).distance(ring), 2), at=[round(t['a'][0], 1), round(t['a'][1], 1)])
        for t in sig_tracks if cls(t['net']) in FAST and track_geom(t).distance(ring) < 1.0]

sw = {n: {L: round(copper(n, L).area, 2) for L in LAYERS if not copper(n, L).is_empty} for n in sorted(NETS) if cls(n) == 'switch'}
def pads_on(ref, net): return [p for p in FP[ref]['pads'] if p['net'] == net] if ref in FP else []
loops = []
for hl in CFG.get('hot_loops', []):
    ic, vin, gn = hl['ic'], hl['in_net'], hl.get('gnd_net', 'GND')
    ipads, gp = pads_on(ic, vin), pads_on(ic, gn)
    if not ipads or not gp: continue
    s1 = {r for r, _, _, _ in NETS.get(vin, [])}; s2 = {r for r, _, _, _ in NETS.get(gn, [])}
    for c in sorted([r for r in s1 & s2 if r.startswith('C')], key=natkey):
        cv, cg = pads_on(c, vin)[0], pads_on(c, gn)[0]
        a_ = min(ipads, key=lambda p: math.dist((p['x'], p['y']), (cv['x'], cv['y']))); g_ = min(gp, key=lambda p: math.dist((p['x'], p['y']), (cg['x'], cg['y'])))
        dv = math.dist((a_['x'], a_['y']), (cv['x'], cv['y']))
        if dv > 15: continue
        lp = Polygon([(a_['x'], a_['y']), (cv['x'], cv['y']), (cg['x'], cg['y']), (g_['x'], g_['y'])])
        loops.append(dict(ic=ic, loop=hl.get('label', vin), cap=c, cap_value=NL['components'].get(c, {}).get('value', ''), pin_to_cap_mm=round(dv, 2),
                          gnd_pin_to_cap_mm=round(math.dist((g_['x'], g_['y']), (cg['x'], cg['y'])), 2),
                          plan_loop_area_mm2=round(abs(lp.area) if lp.is_valid else lp.buffer(0).area, 2),
                          note='distances are pad centre to pad centre; subtract pad half-widths for edge-to-edge'))
loops.sort(key=lambda r: (r['ic'], r['loop'], r['pin_to_cap_mm']))

inv = []
for n in sorted({t['net'] for t in sig_tracks if cls(t['net']) in FAST}, key=natkey):
    per = collections.Counter(); ws = collections.Counter()
    for t in B['tracks']:
        if t['net'] == n: per[t['layer']] += seg_len(t); ws[(t['layer'], t['w'])] += seg_len(t)
    inv.append(dict(net=n, cls=cls(n), pins=['%s.%s' % (r, p) for r, p, _, _ in NETS.get(n, [])], length_mm=round(sum(per.values()), 1),
                    per_layer={k: round(v, 1) for k, v in per.items()}, vias=sum(1 for v in B['vias'] if v['net'] == n),
                    z0_ohm={'%s@%.3g' % k: round(z0_microstrip(k[1], H[k[0]]), 1) for k in ws}))
dp = []
for a_, b_ in CFG.get('diff_pairs', []):
    la = sum(seg_len(t) for t in B['tracks'] if t['net'] == a_); lb = sum(seg_len(t) for t in B['tracks'] if t['net'] == b_)
    dp.append(dict(pair=[a_, b_], len_mm=[round(la, 2), round(lb, 2)], skew_mm=round(abs(la - lb), 2),
                   coupled=[r for r in xt if {r['net'], r['other']} == {a_, b_}][:2]))
json.dump(dict(reference=refout, crosstalk=xt, layer_changes=vchg, edge_proximity=edge, switch_copper=sw, hot_loops=loops, fast_nets=inv, diff_pairs=dp,
               stackup=dict(ref_layer=REF, height_mm=H, er=ER),
               notes=dict(z0='Hammerstad microstrip over the nearest copper layer (zero thickness); inner layers treated the same way, so stripline Z0 is overstated',
                          k='coupling k = 1/(1+(D/h)^2), D centre spacing, h height over the reference; saturated backward crosstalk ~ k/4')),
          open(PACK + 'emc.json', 'w'), indent=1)
print('emc ok: ref', len(refout), 'xt', len(xt), 'vias', len(vchg), 'edge', len(edge), 'loops', len(loops), 'fast', len(inv))
