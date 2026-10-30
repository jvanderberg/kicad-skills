# EMC / SI geometry checks. Writes PACK/emc.json.   python emc.py PACK
#  - reference continuity: for every signal track, what lies under it on the nearest copper layer (ground, another net's
#    pour, or nothing), sampled every 0.1 mm; spans off ground are listed with coordinates
#  - crosstalk: parallel runs of fast nets with neighbours on the same layer (edge) and the adjacent layer (broadside)
#  - layer changes: signal vias, the layers they join and the distance to the nearest ground via (return-current path)
#  - edge proximity of fast nets, switching-node copper area, hot loops (IC pin -> input cap -> ground pin)
#  - fast-net inventory with closed-form microstrip Z0, and differential pair length/skew
# Net classes come from review_config.json "net_classes" (regex -> class) plus switch nodes derived from the netlist
# (topology.py); classes in "fast_classes" get the full checks. Hot loops are the configured ones plus, for every
# switching IC without one, the derived candidates. emc.json "coverage" says what was classified, derived, skipped and
# why; reference spans carry a severity (void > another net's plane > ground edge) so the list can be read in order.
from shapely.strtree import STRtree
from common import *

def z0_microstrip(w, h, er=ER):
    return microstrip(w, h, er)[0]

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
# decoupling capacitors per net (one pad on the net, the other on ground), for "over another net's plane" spans
_decap = {}
def decap_dist(net, pt):
    if net not in _decap:
        _decap[net] = [(r, FP[r]['x'], FP[r]['y']) for r in (TOPO.caps_to_ground(net) if TOPO else []) if r in FP]
    d = [(math.dist(pt, (x, y)), r) for r, x, y in _decap[net]]
    return min(d) if d else (None, None)
def coplanar(L, seg, w):
    """fraction of the span with same-layer ground pour on both sides (a track running inside a ground pour)"""
    g = refgeo[L]['gnd']
    if g.is_empty or seg.geom_type != 'LineString' or seg.length < 0.05: return 0.0
    fr = []
    for side in ('left', 'right'):
        o = seg.parallel_offset(w / 2 + 0.5, side)
        fr.append(o.intersection(g).length / o.length if o.length else 0.0)
    return round(min(fr), 2)
def severity(ref, cop):
    if ref == 'void': return 'high'
    if ref == 'GND_edge': return 'low'
    return 'low' if cop >= 0.7 else 'medium'
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
            sp_ = dict(ref=c[i], len=round(L_, 2), at=[round(P[i, 0], 2), round(P[i, 1], 2)], to=[round(P[j, 0], 2), round(P[j, 1], 2)], pad_entry=entry)
            if not entry:
                sp_['coplanar_gnd'] = coplanar(t['layer'], seg, t['w'])
                if c[i] not in ('void', 'GND_edge'):
                    d_, r_ = decap_dist(c[i], ((P[i, 0] + P[j, 0]) / 2, (P[i, 1] + P[j, 1]) / 2))
                    sp_['nearest_decap'] = dict(ref=r_, mm=round(d_, 1)) if r_ else None
                sp_['severity'] = severity(c[i], sp_['coplanar_gnd'])
            rec['spans'].append(sp_)
            if entry: rec['len']['pad_entry'] += L_; rec['len'][c[i]] -= L_
        i = j + 1
refout = []
SEV = {'high': 0, 'medium': 1, 'low': 2}
for (net, L), rec in sorted(ref_report.items(), key=lambda kv: natkey(kv[0][0])):
    spans = [x for x in rec['spans'] if not x['pad_entry']]
    sev = min((x['severity'] for x in spans), key=SEV.get, default=None)
    refout.append(dict(net=net, cls=cls(net), layer=L, ref_layer=REF[L][0], length=round(sum(rec['len'].values()), 2), over_gnd=round(rec['len']['GND'], 2),
                       not_over_gnd={k: round(v, 2) for k, v in rec['len'].items() if k not in ('GND', 'pad_entry') and v > 0.05},
                       severity=sev, spans=sorted(spans, key=lambda s: (SEV[s['severity']], -s['len']))[:8]))

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
# effective hot loops: every configured one, plus the derived candidates of each switching IC that no configured loop
# actually checked (a configured entry whose IC or nets do not match this board counts as not configured)
loops, loop_status = [], []
def check_loop(hl):
    ic, vin, gn = hl['ic'], hl['in_net'], hl.get('gnd_net', 'GND')
    st = dict(ic=ic, loop=hl.get('label', vin), in_net=vin, gnd_net=gn, source=hl['source'])
    loop_status.append(st)
    ipads, gp = pads_on(ic, vin), pads_on(ic, gn)
    if ic not in FP: st['status'] = 'NOT CHECKED: %s is not on the board' % ic; return
    if not ipads: st['status'] = 'NOT CHECKED: no pad of %s is on %s' % (ic, vin); return
    if not gp: st['status'] = 'NOT CHECKED: no pad of %s is on %s' % (ic, gn); return
    s1 = {r for r, _, _, _ in NETS.get(vin, [])}; s2 = {r for r, _, _, _ in NETS.get(gn, [])}
    caps = [r for r in s1 & s2 if r.startswith('C') and pads_on(r, vin) and pads_on(r, gn)]
    if not caps: st['status'] = 'FAIL: no capacitor between %s and %s' % (vin, gn); return
    rows = []
    for c in sorted(caps, key=natkey):
        cv, cg = pads_on(c, vin)[0], pads_on(c, gn)[0]
        a_ = min(ipads, key=lambda p: math.dist((p['x'], p['y']), (cv['x'], cv['y']))); g_ = min(gp, key=lambda p: math.dist((p['x'], p['y']), (cg['x'], cg['y'])))
        dv = math.dist((a_['x'], a_['y']), (cv['x'], cv['y']))
        lp = Polygon([(a_['x'], a_['y']), (cv['x'], cv['y']), (cg['x'], cg['y']), (g_['x'], g_['y'])])
        rows.append(dict(ic=ic, loop=st['loop'], source=hl['source'], cap=c, cap_value=NL['components'].get(c, {}).get('value', ''),
                         farads=parse_value(NL['components'].get(c, {}).get('value', '')), pin_to_cap_mm=round(dv, 2),
                         gnd_pin_to_cap_mm=round(math.dist((g_['x'], g_['y']), (cg['x'], cg['y'])), 2),
                         plan_loop_area_mm2=round(abs(lp.area) if lp.is_valid else lp.buffer(0).area, 2),
                         ic_pin=a_['num'], ic_gnd_pin=g_['num'], cap_pad=cv['num'], cap_gnd_pad=cg['num'],
                         note='distances are pad centre to pad centre; subtract pad half-widths for edge-to-edge'))
    near = [r for r in rows if r['pin_to_cap_mm'] <= 15]
    if not near:
        n0 = min(rows, key=lambda r: r['pin_to_cap_mm'])
        st['status'] = 'FAIL: nearest capacitor %s (%s) is %.1f mm from the pin' % (n0['cap'], n0['cap_value'], n0['pin_to_cap_mm']); return
    loops.extend(near)
    nearest = min(near, key=lambda r: r['pin_to_cap_mm'])
    sized = [r for r in near if r['farads']]
    small = min(sized, key=lambda r: (r['farads'], r['pin_to_cap_mm'])) if sized else None
    st.update(status='ok', caps=len(near), nearest=dict(cap=nearest['cap'], value=nearest['cap_value'], mm=nearest['pin_to_cap_mm'], area=nearest['plan_loop_area_mm2']),
              smallest=dict(cap=small['cap'], value=small['cap_value'], mm=small['pin_to_cap_mm']) if small else None)
for hl in CFG.get('hot_loops', []): check_loop(dict(hl, source='config'))
covered = {s_['ic'] for s_ in loop_status if s_['status'] == 'ok'}
if TOPO:
    for ic, o in TOPO.switching_ics.items():
        if ic in covered: continue
        cs = o['hot_loop_candidates']
        WARN.append('%s (%s) switches %s but no configured hot loop checked it: using %d derived candidate(s) %s - confirm against its datasheet layout' % (
            ic, o['value'], ', '.join(o['switch_nodes']), len(cs), ', '.join(c['in_net'] for c in cs)))
        for c in cs: check_loop(dict(ic=ic, in_net=c['in_net'], gnd_net=c['gnd_net'], label=c['label'], source='derived'))
loops.sort(key=lambda r: (r['ic'], r['loop'], r['pin_to_cap_mm']))
for st in loop_status:
    if st['status'] != 'ok': WARN.append('hot loop %s %s: %s' % (st['ic'], st['loop'], st['status']))

inv = []
for n in sorted({t['net'] for t in sig_tracks if cls(t['net']) in FAST}, key=natkey):
    per = collections.Counter(); ws = collections.Counter()
    for t in B['tracks']:
        if t['net'] == n: per[t['layer']] += seg_len(t); ws[(t['layer'], t['w'])] += seg_len(t)
    inv.append(dict(net=n, cls=cls(n), pins=['%s.%s' % (r, p) for r, p, _, _ in NETS.get(n, [])], length_mm=round(sum(per.values()), 1),
                    per_layer={k: round(v, 1) for k, v in per.items()}, vias=sum(1 for v in B['vias'] if v['net'] == n),
                    z0_ohm={'%s@%.3g' % k: round(z0_microstrip(k[1], H[k[0]]), 1) for k in ws}))
dp = []
DPC = CFG.get('diff_pair_checks') or {}
def pair_geometry(a_, b_):
    """per layer where both run: width, edge gap between the two, differential impedance (edge-coupled microstrip), and
    the gap from the pair to the nearest other same-layer copper (pour fills and other nets' tracks), which turns the
    pair coplanar when it is small: the pour clearance next to a controlled-impedance pair is part of its geometry"""
    out = []
    for L in LAYERS:
        ta = [t for t in B['tracks'] if t['net'] == a_ and t['layer'] == L and t['a'] != t['b']]
        tb = [t for t in B['tracks'] if t['net'] == b_ and t['layer'] == L and t['a'] != t['b']]
        if not ta or not tb: continue
        la = unary_union([LineString([t['a'], t['b']]) for t in ta]); lb = unary_union([LineString([t['a'], t['b']]) for t in tb])
        w = float(np.median([t['w'] for t in ta + tb])); h = H[L]
        other = unary_union([g for n, g in all_zone_fill(L).items() if n not in (a_, b_)] +
                            [track_geom(t) for t in B['tracks'] if t['layer'] == L and t['net'] not in (a_, b_)])
        sp, gp, samples = [], [], []
        for line, mate in ((la, lb), (lb, la)):
            for seg in (line.geoms if hasattr(line, 'geoms') else [line]):
                n = max(int(seg.length / 0.1), 1)
                for i in range(n + 1):
                    q = seg.interpolate(i / n, normalized=True)
                    c = q.distance(mate)
                    if c > 4 * w + 0.6: continue                 # not running as a pair here (fan-out, pads)
                    sp.append(c - w)
                    if not other.is_empty: gp.append(q.distance(other) - w / 2); samples.append((q.x, q.y))
        if not sp: continue
        s = float(np.median(sp)); z0, ee = microstrip(w, h); zd = zdiff_edge(z0, s, h)
        e = dict(layer=L, width_mm=round(w, 3), gap_mm=round(s, 3), h_mm=round(h, 3), z0_ohm=round(z0, 1), zdiff_ohm=round(zd, 1),
                 coupled_mm=round(len(sp) * 0.1 / 2, 1))
        if gp:
            gmin = float(np.min(gp)); gmed = float(np.median(gp)); i = int(np.argmin(gp))
            zc, _ = cpwg(w, max(gmin, 0.01), h)
            near = float(DPC.get('coplanar_gap_mm') or max(2 * w, 3 * h))
            e.update(pour_gap_min_mm=round(gmin, 3), pour_gap_median_mm=round(gmed, 3), pour_gap_at=[round(v, 2) for v in samples[i]],
                     coplanar_below_mm=round(near, 3), z0_coplanar_ohm=round(float(zc), 1))
            if gmin < near:
                e['flag'] = ('same-layer copper %.2f mm from the pair at %s (median %.2f mm; it stops mattering beyond about %.2f mm = '
                             'max(2 w, 3 h)): the line is partly coplanar and its impedance is LOWER than the edge-coupled %.0f ohm '
                             '(grounded-coplanar estimate at that gap: Z0 %.0f ohm vs microstrip %.0f). Keep the pour back along the '
                             'run (a keepout or a clearance rule) or design it as coplanar, and confirm with the fab\'s impedance '
                             'calculator for this stackup' % (gmin, e['pour_gap_at'], gmed, near, zd, zc, z0))
        out.append(e)
    return out
for pr in DIFF_PAIRS:
    a_, b_ = pr['nets']
    target = pr['target_ohm']
    la = sum(seg_len(t) for t in B['tracks'] if t['net'] == a_); lb = sum(seg_len(t) for t in B['tracks'] if t['net'] == b_)
    geo_ = pair_geometry(a_, b_)
    for g_ in geo_:
        if g_.get('flag'): WARN.append('diff pair %s/%s on %s: %s' % (a_, b_, g_['layer'], g_['flag']))
        z_ = g_['zdiff_ohm']
        if target and abs(z_ - target) > 0.1 * target:
            WARN.append('diff pair %s/%s on %s: Zdiff about %.0f ohm vs target %g (estimate: verify with the fab\'s calculator)' % (a_, b_, g_['layer'], z_, target))
    dp.append(dict(pair=[a_, b_], len_mm=[round(la, 2), round(lb, 2)], skew_mm=round(abs(la - lb), 2), target_ohm=target, geometry=geo_,
                   coupled=[r for r in xt if {r['net'], r['other']} == {a_, b_}][:2]))
# Electrical cross-check of every checked hot loop: pad-to-pad geometry can look tight while the return runs through
# one small via and an inner layer. A 1 A DC solve (fem.py) from the IC's pins to the nearest capacitor's pad, on the
# ground side and on the supply side, gives the path resistance, the share of the current that leaves the component
# layer through vias, and the share carried by the busiest single via.
def path_check(net, ic, cap, cap_pad, layer):
    from fem import solve
    src = [(ic, p['num']) for p in pads_on(ic, net)]
    pads = [p for r in (ic, cap) for p in FP[r]['pads']]
    xs = [p['x'] for p in pads]; ys = [p['y'] for p in pads]
    m = 5.0                                     # copper within 5 mm of the IC and capacitor pads takes part
    region = box(min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
    try:
        res = solve(net, sorted(set(src)), [((cap, cap_pad), 1.0)], h=0.1, region=region)
    except (AssertionError, ValueError) as ex:
        return dict(error=str(ex)[:120])
    # current leaving the component layer through barrels, and current arriving on it through barrels (the IC's own
    # thermal-via pads can source current on inner layers directly); the larger is the share that left the layer
    # (barrels of the IC's own plated pads - thermal vias in its exposed pad - are part of the pin, not of the path)
    own = {(round(p['x'], 3), round(p['y'], 3)) for p in FP[ic]['pads'] if p['th']}
    fl = [f for f in res['link_flows'] if layer in (f[2], f[3]) and (round(f[0], 3), round(f[1], 3)) not in own]
    out_ = sum(max(0.0, I if La == layer else -I) for x, y, La, Lb, I in fl)
    in_ = sum(max(0.0, -I if La == layer else I) for x, y, La, Lb, I in fl)
    va = [v for v in res['via_amps'] if (round(v[0], 3), round(v[1], 3)) not in own]
    via = va[0][2] if va else 0.0
    vd = next((v for v in B['vias'] if va and math.dist((v['x'], v['y']), va[0][:2]) < 0.01), None)
    r = res['sinks'][0]['drop_mV']
    return dict(r_mohm=round(r, 2), via_share=round(min(max(out_, in_), 1.0), 2), busiest_via_share=round(min(via, 1.0), 2),
                busiest_via=dict(at=[round(va[0][0], 2), round(va[0][1], 2)], size=vd['size'] if vd else None, drill=vd['drill'] if vd else None) if va else None,
                vias_in_region=res['vias'], box_margin_mm=m, suspect=r > 1e4)
if '--no-solve' not in sys.argv:
    for st in loop_status:
        if st['status'] != 'ok': continue
        n = next(r for r in loops if r['ic'] == st['ic'] and r['loop'] == st['loop'] and r['cap'] == st['nearest']['cap'])
        cpad = next(p for p in FP[n['cap']]['pads'] if p['num'] == n['cap_gnd_pad'])
        layer = cpad['layers'][0] if cpad['layers'] else 'F.Cu'
        st['gnd_return'] = path_check(st['gnd_net'], st['ic'], n['cap'], n['cap_gnd_pad'], layer)
        st['supply_side'] = path_check(st['in_net'], st['ic'], n['cap'], n['cap_pad'], layer)
        flags, real = [], False
        for side, d in (('ground return', st['gnd_return']), ('supply side', st['supply_side'])):
            if d.get('error') or d.get('suspect'):
                flags.append('%s not solved (%s)' % (side, d.get('error') or 'grid artefact')); continue
            bv = d['busiest_via']
            one = ('%.0f %% through one via%s at %s' % (100 * d['busiest_via_share'], ' (%g/%g mm)' % (bv['size'], bv['drill'])
                   if bv and bv['size'] else '', bv['at'] if bv else '?')) if d['busiest_via_share'] > 0.5 else ''
            if d['via_share'] > 0.5:
                # the capacitor's pad and the IC's pin are not joined on their own layer (or only by a long detour): the
                # loop closes through an inner layer, however close the parts sit (a pin strap under the IC once split
                # the top ground between the input capacitor and the GND pin of a buck; 79 % went through vias)
                flags.append('%s: %.0f %% of the current leaves %s through vias%s - %s and %s.%s are not joined directly on that '
                             'layer, so the loop closes through an inner layer (path %.1f mOhm)' % (
                                 side, 100 * d['via_share'], layer, ' (%s)' % one if one else '', n['cap'], st['ic'],
                                 'GND pin' if side == 'ground return' else 'supply pin', d['r_mohm'])); real = True
            elif one:
                flags.append('%s: %s (path %.1f mOhm)' % (side, one, d['r_mohm'])); real = True
        st['electrical_flags'] = flags
        if real: st['status'] = 'FLAG: see flags (geometry ok)'          # "not solved" alone is coverage, not a finding
        if flags: WARN.append('hot loop %s %s (cap %s): %s' % (st['ic'], st['loop'], n['cap'], '; '.join(flags)))

coverage = dict(warnings=WARN, classes={c: dict(count=len(v), nets=v[:40]) for c, v in classification_coverage().items()},
                derived_switch_nodes=[dict(net=n, why=e['why'], cls=cls_how(n)[0], how=cls_how(n)[1]) for n, e in (TOPO.switch_nodes.items() if TOPO else [])],
                switching_ics={ic: dict(value=o['value'], switch_nodes=o['switch_nodes'], topology=o['topology_hint'], hot_loops='config' if ic in covered else 'derived')
                               for ic, o in (TOPO.switching_ics.items() if TOPO else [])},
                hot_loops=loop_status, ground_nets=sorted(GND))
json.dump(dict(coverage=coverage, reference=refout, crosstalk=xt, layer_changes=vchg, edge_proximity=edge, switch_copper=sw, hot_loops=loops, fast_nets=inv, diff_pairs=dp,
               stackup=dict(ref_layer=REF, height_mm=H, er=ER),
               notes=dict(z0='Hammerstad microstrip over the nearest copper layer (zero thickness); inner layers treated the same way, so stripline Z0 is overstated',
                          k='coupling k = 1/(1+(D/h)^2), D centre spacing, h height over the reference; saturated backward crosstalk ~ k/4')),
          open(PACK + 'emc.json', 'w'), indent=1)
print('emc ok: ref', len(refout), 'xt', len(xt), 'vias', len(vchg), 'edge', len(edge), 'loops', len(loops), 'fast', len(inv),
      '| switch nodes', len(sw), '(derived %d)' % (len(TOPO.switch_nodes) if TOPO else 0), '| hot loops checked', sum(s_['status'] == 'ok' or s_['status'].startswith('FLAG') for s_ in loop_status), 'of', len(loop_status))
for w in WARN: print('  !!', w)
