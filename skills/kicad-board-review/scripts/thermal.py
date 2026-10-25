# Heat sources, board temperatures, thermal vias and stitching for heat. Writes PACK/thermal.json, PACK/thermal.md and
# PACK/maps/thermal_<corner>.png.      python thermal.py PACK [--pitch 0.3] [--no-maps]
#
# 1. Heat-source table (heat.py): every part's loss at every corner of review_config.json "thermal", from currents
#    (given, from a power run, or solved by pcb-power-supply's path_budget.py), efficiencies and resistances. Every part
#    that can dissipate real heat is listed; the ones with no data are UNKNOWN, never left out.
# 2. Temperatures (thermal_model.py): a steady-state layered solve on the board's own copper (every layer, rasterised,
#    nets kept apart), FR4 between the layers, via barrels, heat placed on each part's pads (copper loss along each power
#    run's copper), cooled from both faces at the low / nominal / high film coefficient. Reported next to the board-average
#    check P / (2 A h), with junction estimates where the datasheet gives psi_JB or theta_JC.
# 3. Thermal vias per exposed pad, the pour under each hot part (vias and FR4 down to the planes), weakly stitched ground
#    pieces with what sits on them, edge stitching as planes.py measured it, and a what-if: ground stitching vias on a grid.
import argparse, glob, time
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import *
import heat
import thermal_model as tm

ap = argparse.ArgumentParser(); ap.add_argument('pack'); ap.add_argument('--pitch', type=float); ap.add_argument('--no-maps', action='store_true')
a = ap.parse_args()
t_start = time.time()
TC = dict(heat.DEFAULTS); TC.update(CFG.get('thermal') or {})
TW = []                                   # thermal coverage warnings (common.WARN is added in front)
if not CFG.get('thermal'):
    TW.append('no "thermal" section in review_config.json: no corners, no losses; every candidate heat source is UNKNOWN and no '
              'temperature is computed (vias and stitching below are still measured)')
AMB = TC.get('ambient_C')
if AMB is None:
    AMB = 25.0
    if CFG.get('thermal'): TW.append('thermal.ambient_C not set: temperatures below are rises over a PLACEHOLDER 25 C; set the air temperature around the board (inside the enclosure) at the design corner')
HS = TC.get('h_W_m2K') or heat.DEFAULTS['h_W_m2K']
HS = HS if isinstance(HS, dict) else {'nominal': float(HS)}
H_NOM = 'nominal' if 'nominal' in HS else sorted(HS, key=lambda k: HS[k])[len(HS) // 2]
if 'h_W_m2K' not in (CFG.get('thermal') or {}):
    TW.append('h (film coefficient) not configured: default %s W/m^2K (still air in a closed box, convection plus radiation, each face) - '
              'an ASSUMPTION and the largest uncertainty in every temperature here' % ', '.join('%s %g' % kv for kv in HS.items()))
HB = float(TC.get('h_bottom_ratio', 1.0))
HOT = float(TC.get('hot_part_W', heat.DEFAULTS['hot_part_W']))
PITCH = a.pitch or float(TC.get('pitch_mm', 0.3))
K_FR4 = float(TC.get('k_fr4', tm.K_FR4)); PLATE = float(TC.get('via_plating_um', tm.PLATING_UM))
OUT, BOT = LAYERS[0], LAYERS[-1]

# ---------------- power runs (copper loss and run currents), worst tag per run
RUNS = {}
for f in sorted(glob.glob(PACK + 'power_runs*.json')):
    tag = os.path.basename(f)[len('power_runs'):-5].lstrip('_')
    for r in json.load(open(f))['runs']:
        if r['name'] not in RUNS or r['P_W'] > RUNS[r['name']]['P_W']:
            RUNS[r['name']] = dict(P_W=r['P_W'], I_total=r['I_total'], net=r['net'], tag=tag, file=os.path.basename(f))

# ---------------- heat table
cfg_src = open(PACK + '.config_source').read().strip() if os.path.exists(PACK + '.config_source') else None
ctx = heat.Context(RUNS, [PACK] + ([os.path.dirname(cfg_src)] if cfg_src else []))
CORNERS = list((TC.get('corners') or {}).keys())
if not CORNERS:
    if CFG.get('thermal'): TW.append('thermal.corners is empty: give at least the worst-case discharge (lowest source voltage, full load), a typical point and charging while running')
    CORNERS = ['default']
run_refs = set()
for r in CFG.get('power_runs', []):
    for s in r.get('source', []) + [x[0] for x in r.get('sinks', [])]: run_refs.add(s.split(':')[0])
CAND = heat.candidates(B['footprints'], run_refs)
HT, hw = heat.table(TC, CORNERS, ctx, set(FP), CAND)
TW += hw
for p_, used in ctx.files_used.items(): TW.append('input used: path_budget results %s' % used)

# ---------------- geometry: copper per net per layer, rasterised with nets kept apart
x0, y0, x1, y1 = EDGE.bounds
NX, NY = int(math.ceil((x1 - x0) / PITCH)), int(math.ceil((y1 - y0) / PITCH))
SS = 3
xs = x0 + (np.arange(NX) + 0.5) * PITCH; ys = y0 + (np.arange(NY) + 0.5) * PITCH
XC, YC = np.meshgrid(xs, ys)
sx = x0 + (np.arange(NX * SS) + 0.5) * PITCH / SS; sy = y0 + (np.arange(NY * SS) + 0.5) * PITCH / SS
XS, YS = np.meshgrid(sx, sy)
def blocks(m): return m.reshape(NY, SS, NX, SS).sum(axis=(1, 3))
shapely.prepare(EDGE)
INSIDE = blocks(shapely.contains_xy(EDGE, XS, YS)) >= (SS * SS + 1) // 2
NETS_ON = collections.defaultdict(set)
for z in B['zones']:
    if not z['keepout']:
        for L in z['filled']: NETS_ON[L].add(z['net'])
for t in B['tracks']: NETS_ON[t['layer']].add(t['net'])
for f in B['footprints']:
    for p in f['pads']:
        for L in p['layers']: NETS_ON[L].add(p['net'])
for v in B['vias']:
    for L in LAYERS: NETS_ON[L].add(v['net'])
NET_ID = {n: i for i, n in enumerate(sorted({n for s in NETS_ON.values() for n in s}))}
GEO = {}
def geo(net, L):
    if (net, L) not in GEO:
        g = copper(net, L)
        shapely.prepare(g)                # contains_xy on an unprepared fill is ~100x slower
        GEO[(net, L)] = g
    return GEO[(net, L)]
LAYER_DATA = []
for L in LAYERS:
    lab_s = -np.ones(XS.shape, int)
    for n in sorted(NETS_ON[L]):
        g = geo(n, L)
        if g.is_empty: continue
        bx0, by0, bx1, by1 = g.bounds
        c0, c1 = max(int((bx0 - x0) / PITCH * SS) - 1, 0), min(int((bx1 - x0) / PITCH * SS) + 2, NX * SS)
        r0, r1 = max(int((by0 - y0) / PITCH * SS) - 1, 0), min(int((by1 - y0) / PITCH * SS) + 2, NY * SS)
        if c1 <= c0 or r1 <= r0: continue
        m = shapely.contains_xy(g, XS[r0:r1, c0:c1], YS[r0:r1, c0:c1])
        sub = lab_s[r0:r1, c0:c1]; sub[m] = NET_ID[n]
    best = np.zeros((NY, NX)); lab = -np.ones((NY, NX), int)
    for k in np.unique(lab_s[lab_s >= 0]):
        cnt = blocks(lab_s == k)
        better = cnt > best
        best[better] = cnt[better]; lab[better] = k
    zc = STACK[L]['z'] + STACK[L]['t'] / 2
    LAYER_DATA.append(dict(name=L, t_mm=STACK[L]['t'], z_mm=zc, frac=best / (SS * SS), label=np.where(INSIDE, lab, -1)))
zs = [d['z_mm'] for d in LAYER_DATA]
GAPS = [max(abs(zs[i + 1] - zs[i]) - (LAYER_DATA[i]['t_mm'] + LAYER_DATA[i + 1]['t_mm']) / 2, 0.01) for i in range(len(LAYERS) - 1)]
if not B.get('stackup'):
    TW.append('the board file has no stackup: 1.6 mm and 35 um copper on every layer ASSUMED (dielectric gaps %s mm)' % ', '.join('%.2f' % g for g in GAPS))

def cell_of(x, y):
    c = int((x - x0) / PITCH); r = int((y - y0) / PITCH)
    return (r, c) if 0 <= r < NY and 0 <= c < NX else None

# vias and plated holes: they join the layers where they land on copper of their own net
HOLES = [dict(x=v['x'], y=v['y'], d=v['drill'], net=v['net'], kind='via', type=v.get('type_name')) for v in B['vias']]
HOLES += [dict(x=p['x'], y=p['y'], d=p['drill'], net=p['net'], kind='pad', ref=f['ref'], pad=p['num'], layers=p['layers'])
          for f in B['footprints'] for p in f['pads'] if p['th'] and p['drill'] > 0]
for hh in HOLES:
    pt = Point(hh['x'], hh['y'])
    hh['landed'] = [i for i, L in enumerate(LAYERS) if (hh['kind'] == 'pad' and L in hh['layers'] and not hh['net']) or geo(hh['net'], L).intersects(pt)]
nonthrough = [h_ for h_ in HOLES if h_['kind'] == 'via' and h_.get('type') not in (None, 'through')]
if nonthrough: TW.append('%d blind/buried/micro vias treated as through vias (their real span is shorter: they join fewer layers)' % len(nonthrough))
if B['vias'] and all(v.get('type_name') is None for v in B['vias']):
    TW.append('board.json has no via type names (dumped by an older boarddump.py): every via treated as a through via')
VIAS = []
for hh in HOLES:
    rc = cell_of(hh['x'], hh['y'])
    if rc and len(hh['landed']) > 1: VIAS.append((rc[0], rc[1], hh['landed'], hh['d']))
t0 = time.time()
MODEL = tm.Layered(PITCH, INSIDE, LAYER_DATA, GAPS, VIAS, k_fr4=K_FR4, plating_um=PLATE)
AREA = float(EDGE.area)

# ---------------- heat placement
def pad_cells(ref, only=None):
    """cells under a part's pads on its own outer layer, with the share of the part's heat each pad takes (by pad area)"""
    f = FP[ref]; L = OUT if f['side'] == 'F' else BOT; li = LAYERS.index(L)
    pads = [p for p in f['pads'] if p['poly'] and p['num'] and (L in p['layers']) and (only is None or p['num'] in only)]
    tot = sum(unary_union(polys(p['poly'])).area for p in pads) or 1.0
    out = []
    for p in pads:
        pg = unary_union(polys(p['poly']))
        m = shapely.contains_xy(pg, XC, YC) & INSIDE
        cells = list(zip(*np.where(m)))
        if not cells:
            rc = cell_of(p['x'], p['y'])
            if rc and INSIDE[rc]: cells = [rc]
        if cells: out.append((pg.area / tot, cells, p))
    return li, out
PART_PADS = {}
def pads_of(ref):
    if ref not in PART_PADS:
        only = ((TC.get('parts') or {}).get(ref) or {}).get('pads')
        PART_PADS[ref] = pad_cells(ref, set(only) if only else None)
    return PART_PADS[ref]
R_BODY = float(TC.get('body_K_W', 1.0))
BODY = {}
def part_q(ref, P, Q):
    if ref not in BODY: return False
    Q[BODY[ref]] += P
    return True
LOSSMAP = {}
def run_q(run, P, Q):
    """copper loss along a power run's copper: the solver's own loss map (power.py), else spread over the net's copper"""
    r = RUNS.get(run)
    if run not in LOSSMAP:
        f = PACK + 'maps/%s%s_loss.npz' % (run, ('_' + r['tag']) if r and r['tag'] else '')
        cells = []
        if os.path.exists(f):
            d = np.load(f)
            for i, L in enumerate(d['layers']):
                w = d['L%d' % i]; rr, cc = np.nonzero(w > 0)
                gx = float(d['x0']) + (cc + 0.5) * float(d['h']); gy = float(d['y0']) + (rr + 0.5) * float(d['h'])
                tc_ = ((gx - x0) / PITCH).astype(int); tr_ = ((gy - y0) / PITCH).astype(int)
                ok = (tc_ >= 0) & (tc_ < NX) & (tr_ >= 0) & (tr_ < NY)
                ok[ok] &= INSIDE[tr_[ok], tc_[ok]]
                li = LAYERS.index(str(L))
                cells.append((MODEL.idx[li][tr_[ok], tc_[ok]], w[rr[ok], cc[ok]]))
            how = 'loss map %s' % os.path.basename(f)
        else:
            net = r['net'] if r else None
            for li, L in enumerate(LAYERS):
                if not net: continue
                m = shapely.contains_xy(geo(net, L), XC, YC) & INSIDE
                cells.append((MODEL.idx[li][m], np.ones(int(m.sum()))))
            how = 'spread evenly over net %s (no loss map: power.py not run with maps)' % net
            TW.append('copper loss of run %s placed without its loss map: %s' % (run, how))
        idx_ = np.concatenate([c for c, _ in cells]) if cells else np.zeros(0, int)
        wts = np.concatenate([w for _, w in cells]) if cells else np.zeros(0)
        LOSSMAP[run] = (idx_, wts / wts.sum() if wts.sum() > 0 else wts, how)
    idx_, wts, _ = LOSSMAP[run]
    if not len(idx_): return False
    np.add.at(Q, idx_, P * wts)
    return True

# a node per heated part's body, joined to its pads (shared by pad area): the board, not a fixed split, decides which pads
# carry the heat (a SOT-223 tab on a pour takes most of it, an isolated signal pin almost none)
heated = sorted({r['ref'] for c in CORNERS for r in HT[c]['rows'] if r.get('ref') in FP and r.get('P_W') and not r.get('run')}, key=natkey)
links = []
for ref in heated:
    li, pads = pads_of(ref)
    if not pads: continue
    w = sum(sh for sh, _, _ in pads)
    links.append((ref, [(MODEL.idx[li][rc], sh / w / len(cells) / R_BODY) for sh, cells, _ in pads for rc in cells]))
for (ref, _), k in zip(links, MODEL.add_bodies([l for _, l in links])): BODY[ref] = k

QS, PLACED = {}, {}
for c in CORNERS:
    Q = np.zeros(MODEL.n); lost = []
    for r in HT[c]['rows']:
        P = r['P_W']
        if not P: continue
        ok = False
        if r.get('run'): ok = run_q(r['run'], P, Q)
        elif r.get('ref') and r['ref'] in FP: ok = part_q(r['ref'], P, Q)
        if not ok:
            lost.append(r)
            outer = np.concatenate([MODEL.idx[0][INSIDE], MODEL.idx[-1][INSIDE]])
            Q[outer] += P / len(outer)
    if lost:
        TW.append('corner %s: %.2f W with no place on the board (%s) spread evenly over both faces' % (c, sum(r['P_W'] for r in lost), ', '.join(r['name'] for r in lost)))
    QS[c] = Q; PLACED[c] = float(Q.sum())

# ---------------- solve every corner at every film coefficient
RISE = {}
for hn, hv in HS.items():
    sols = MODEL.solve([QS[c] for c in CORNERS], hv, hv * HB)
    for c, s in zip(CORNERS, sols): RISE[(c, hn)] = s
t_solve = time.time() - t0

def peak(rl):
    best = None
    for li, g in enumerate(rl):
        if np.isfinite(g).any():
            r, c = np.unravel_index(np.nanargmax(g), g.shape)
            if best is None or g[r, c] > best[0]: best = (float(g[r, c]), LAYERS[li], float(xs[c]), float(ys[r]))
    return best

def part_temp(ref, rl):
    li, pads = pads_of(ref)
    vals = [rl[li][r, c] for _, cells, _ in pads for (r, c) in cells]
    return (float(np.mean(vals)), float(np.max(vals))) if vals else (None, None)

def near_ref(x, y):
    best = None
    for f in B['footprints']:
        d = math.hypot(f['x'] - x, f['y'] - y)
        if best is None or d < best[0]: best = (d, f['ref'])
    return best[1] if best else ''

PARTS_CFG = TC.get('parts') or {}
BOARD = {}
for c in CORNERS:
    P = HT[c]['total_W']
    for hn, hv in HS.items():
        rl = RISE[(c, hn)]
        pk = peak(rl)
        BOARD[(c, hn)] = dict(corner=c, h=hn, h_W_m2K=hv, P_W=P, placed_W=PLACED[c], avg_analytic=tm.board_average_rise(PLACED[c], AREA, hv, hv * HB),
                              avg_solver=tm.face_mean(rl, INSIDE, hv, hv * HB) if PLACED[c] else 0.0,
                              peak=dict(rise=pk[0], layer=pk[1], x=round(pk[2], 1), y=round(pk[3], 1), near=near_ref(pk[2], pk[3])) if pk and PLACED[c] else None)
BOARD_LIM = TC.get('board_T_max_C')
if BOARD_LIM is None:
    BOARD_LIM = 105.0
    if CFG.get('thermal'): TW.append('board_T_max_C not set: 105 C ASSUMED as the board limit (FR4 and solder mask in continuous use; check the laminate\'s Tg / MOT)')
# thermal time constant of the bare board: a corner that lasts much less than this does not reach the steady temperatures
_thick = sum(x['thickness_mm'] for x in B.get('stackup') or []) or 1.6
_cu = sum(d['t_mm'] * 1e-3 * float(d['frac'][INSIDE].sum()) * (PITCH * 1e-3) ** 2 for d in LAYER_DATA)
C_BOARD = (AREA * 1e-6 * _thick * 1e-3 - _cu) * 2.0e6 + _cu * 3.45e6          # FR4 ~2.0 MJ/m^3K, copper 3.45 MJ/m^3K
TAU = {hn: C_BOARD / (hv * (1 + HB) * AREA * 1e-6) for hn, hv in HS.items()}
CONDUCTION = ('i2r', 'copper', 'path', 'path copper')
SPLIT = {c: (sum(r['P_W'] for r in HT[c]['rows'] if r['P_W'] and r['kind'] in CONDUCTION),
             sum(r['P_W'] for r in HT[c]['rows'] if r['P_W'] and r['kind'] in ('converter', 'linear', 'fixed'))) for c in CORNERS}
PART_ROWS = []
refs_hot = sorted({r for c in CORNERS for r, p in HT[c]['by_ref'].items() if p > 0 and r in FP}, key=natkey)
for ref in refs_hot:
    pc = PARTS_CFG.get(ref, {})
    for c in CORNERS:
        P = HT[c]['by_ref'].get(ref, 0.0)
        row = dict(ref=ref, value=FP[ref]['value'], corner=c, P_W=P, T={})
        for hn in HS:
            mean_r, max_r = part_temp(ref, RISE[(c, hn)])
            if mean_r is None: continue
            tj, how = None, 'no psi_JB / theta_JC given: board temperature only'
            if pc.get('psi_jb') is not None: tj, how = AMB + mean_r + P * pc['psi_jb'], 'board + P x psi_JB %.1f C/W' % pc['psi_jb']
            elif pc.get('theta_jc') is not None: tj, how = AMB + mean_r + P * pc['theta_jc'], 'pad + P x theta_JC %.1f C/W (case = soldered pad)' % pc['theta_jc']
            row['T'][hn] = dict(board_rise=mean_r, board_rise_max=max_r, T_board=AMB + mean_r, Tj=tj, tj_how=how)
        lim = pc.get('Tj_max_C') if pc.get('Tj_max_C') is not None else pc.get('T_max_C')
        if lim is not None and row['T']:
            worst = row['T'].get(H_NOM) or next(iter(row['T'].values()))
            tv = worst['Tj'] if worst['Tj'] is not None else worst['T_board']
            row['limit'] = dict(C=lim, what=pc.get('limit_what', 'Tj max' if pc.get('Tj_max_C') is not None else 'T max'),
                                over_nominal=tv > lim,
                                over_low_h=any(((v['Tj'] if v['Tj'] is not None else v['T_board']) > lim) for v in row['T'].values()))
        PART_ROWS.append(row)

# ---------------- exposed pads and their vias
PADS_CFG = TC.get('pads') or {}
def max_P(ref): return max([HT[c]['by_ref'].get(ref, 0.0) for c in CORNERS] or [0.0])
def via_g_to(hh, li_from):
    """W/K from layer li_from down/up the barrel to the nearest other landed layer, and to the far side"""
    ls = hh['landed']
    if li_from not in ls or len(ls) < 2: return 0.0, 0.0, None
    others = [l for l in ls if l != li_from]
    near = min(others, key=lambda l: abs(zs[l] - zs[li_from])); far = max(others, key=lambda l: abs(zs[l] - zs[li_from]))
    return tm.via_conductance(hh['d'], abs(zs[near] - zs[li_from]), PLATE), tm.via_conductance(hh['d'], abs(zs[far] - zs[li_from]), PLATE), LAYERS[near]
def rule_vias(w, h_):
    n = lambda s: max(1, int(math.floor((s - 0.6) / 1.0)) + 1) if s > 0.6 else 1
    return n(w) * n(h_)
EPADS = []
for f in sorted(B['footprints'], key=lambda f: natkey(f['ref'])):
    pads = [p for p in f['pads'] if p['poly'] and p['num'] and not p['th']]
    if len(pads) < 3: continue
    areas = sorted(unary_union(polys(p['poly'])).area for p in pads)
    med = areas[len(areas) // 2]
    seen = set()
    for p in pads:
        pg = unary_union(polys(p['poly'])); A_ = pg.area
        if A_ < 1.0 or A_ < 2 * med or (p['num'] in seen): continue
        seen.add(p['num'])
        # the whole pad (some footprints split an exposed pad into several same-number pads)
        pg = unary_union([unary_union(polys(q['poly'])) for q in pads if q['num'] == p['num']]); A_ = pg.area
        L = p['layers'][0] if p['layers'] else OUT; li = LAYERS.index(L) if L in LAYERS else 0
        inpad = [hh for hh in HOLES if hh['net'] == p['net'] and pg.buffer(0.05).contains(Point(hh['x'], hh['y']))]
        beside = [hh for hh in HOLES if hh['net'] == p['net'] and hh not in inpad and pg.distance(Point(hh['x'], hh['y'])) <= 1.0]
        gn = sum(via_g_to(hh, li)[0] for hh in inpad); gf = sum(via_g_to(hh, li)[1] for hh in inpad)
        gb = sum(via_g_to(hh, li)[0] for hh in beside)
        other_layers = [L2 for L2 in LAYERS if L2 != L and not geo(p['net'], L2).is_empty] if p['net'] else []
        ln, wd = rect_dims(pg)
        key = '%s:%s' % (f['ref'], p['num'])
        rec, basis = (PADS_CFG[key]['vias'], PADS_CFG[key].get('basis', 'review_config thermal.pads')) if key in PADS_CFG else (rule_vias(ln, wd), 'rule of thumb: 0.3 mm vias at 1.0 mm pitch, 0.3 mm from the pad edge')
        Pm = max_P(f['ref'])
        e = dict(ref=f['ref'], value=f['value'], pad=p['num'], net=p['net'], area_mm2=round(A_, 2), dims_mm=[round(ln, 2), round(wd, 2)],
                 vias_in_pad=len(inpad), vias_beside=len(beside), recommended=rec, rec_basis=basis,
                 G_near_W_K=gn, G_far_W_K=gf, G_beside_W_K=gb, near_layer=via_g_to(inpad[0], li)[2] if inpad else None,
                 R_K_W=(1 / (gn + gb)) if gn + gb > 0 else None, net_on_other_layers=other_layers, P_max_W=Pm)
        e['dT_vias_K'] = Pm / (gn + gb) if (gn + gb) > 0 and Pm else None
        if not other_layers and p['net']:
            e['flag'] = 'net %s has no copper on any other layer: vias here would land on nothing; the heat leaves through the %s pour and FR4' % (p['net'], L)
        elif len(inpad) < rec:
            e['flag'] = '%d via(s) in the pad, %d recommended (%s)' % (len(inpad), rec, basis)
        e['severity'] = ('high' if Pm >= HOT and e.get('flag') and (e['dT_vias_K'] or 99) > 10 else 'medium' if Pm >= HOT and e.get('flag')
                         else 'low' if e.get('flag') else 'ok')
        EPADS.append(e)

# ---------------- the pour under each hot part: what joins it to the next layer, and the solved drop across that
POURS = []
def worst_corner(ref): return max(CORNERS, key=lambda c: HT[c]['by_ref'].get(ref, 0.0))
for ref in refs_hot:
    Pm = max_P(ref)
    if Pm < HOT: continue
    c_w = worst_corner(ref); rl = RISE[(c_w, H_NOM)]
    f = FP[ref]; L = OUT if f['side'] == 'F' else BOT; li = LAYERS.index(L); lj = 1 if li == 0 else len(LAYERS) - 2
    if lj == li: continue
    nets = sorted({p['net'] for p in f['pads'] if p['poly'] and p['num'] and L in p['layers'] and p['net']})
    for net in nets:
        zf = zone_fill(net, L)
        if zf.is_empty: continue                                        # a pin on a track, not a pour
        g = geo(net, L)
        pcs = list(g.geoms) if hasattr(g, 'geoms') else [g]
        pp = unary_union([unary_union(polys(p['poly'])) for p in f['pads'] if p['net'] == net and L in p['layers'] and p['poly']])
        piece = max(pcs, key=lambda q: q.intersection(pp).area)
        if piece.intersection(zf).area < 1.0: continue
        vs = [hh for hh in HOLES if hh['net'] == net and piece.buffer(0.05).contains(Point(hh['x'], hh['y'])) and len(hh['landed']) > 1]
        gv = sum(via_g_to(hh, li)[0] for hh in vs)
        gfr = K_FR4 * piece.area * 1e-6 / (GAPS[0 if li == 0 else -1] * 1e-3)
        m_ = shapely.contains_xy(piece, XC, YC) & INSIDE
        if not m_.any(): continue
        dT = float(np.nanmean(rl[li][m_]) - np.nanmean(rl[lj][m_]))
        q_fr4 = float(K_FR4 * (PITCH * 1e-3) ** 2 / (GAPS[0 if li == 0 else -1] * 1e-3) * np.nansum(rl[li][m_] - rl[lj][m_]))
        q_via = 0.0
        for hh in vs:
            rc = cell_of(hh['x'], hh['y']); gn_, _, nl = via_g_to(hh, li)
            if rc and nl: q_via += gn_ * float(rl[li][rc] - rl[LAYERS.index(nl)][rc])
        under = collections.Counter()
        for n2 in NETS_ON[LAYERS[lj]]:
            g2 = geo(n2, LAYERS[lj])
            if not g2.is_empty:
                ov = g2.intersection(piece).area
                if ov > 0.05 * piece.area: under[n2] = round(ov / piece.area * 100)
        others = [L2 for L2 in LAYERS if L2 != L and not geo(net, L2).is_empty]
        e = dict(ref=ref, net=net, layer=L, corner=c_w, P_part_W=HT[c_w]['by_ref'].get(ref, 0.0), piece_mm2=round(piece.area, 1), bbox=[round(v, 1) for v in piece.bounds],
                 vias=len(vs), G_vias_W_K=gv, G_fr4_W_K=gfr, dT_K=dT, Q_down_W=q_fr4 + q_via, Q_vias_W=q_via, under=dict(under), net_on_other_layers=others)
        fl = []
        if not vs and others: fl.append('no via joins this pour to its own net\'s copper on %s' % ', '.join(others))
        elif not vs: fl.append('no other layer has %s copper: the pour reaches the layer below only through %.2f mm of FR4' % (net, GAPS[0 if li == 0 else -1]))
        elif len(vs) < 2: fl.append('one via only')
        # the structure is a finding only where the solve shows it matters: a step of a few kelvin is not trapped heat
        if dT >= 3: fl.append('%.0f K between this pour and the layer below (solved, %s, h %s)' % (dT, c_w, H_NOM))
        if fl and dT >= 3: e['flag'] = '; '.join(fl)
        elif fl: e['note'] = '; '.join(fl) + ' (step %.1f K: not limiting)' % dT
        e['severity'] = 'high' if dT > 20 or (not vs and others and dT > 5) else 'medium' if dT > 5 or (fl and dT >= 3) else 'ok'
        key = (net, L, tuple(e['bbox']))
        prev = next((p for p in POURS if (p['net'], p['layer'], tuple(p['bbox'])) == key), None)
        if prev is not None:                                          # one pour under several hot parts: one row
            prev['ref'] += ', ' + ref
            if dT > prev['dT_K']: prev.update({k: v for k, v in e.items() if k != 'ref'})
            continue
        POURS.append(e)

# ---------------- ground stitching (as planes.py measured it), with what sits on each weak piece
PL = json.load(open(PACK + 'planes.json')) if os.path.exists(PACK + 'planes.json') else None
STITCH = {}
if PL is None:
    TW.append('no planes.json in the pack (planes.py not run): no edge-stitch or weak-piece findings')
else:
    weak = []
    for w in PL.get('weakly_stitched_gnd_pieces', []):
        bb = box(*w['bbox'])
        on = sorted({f['ref'] for f in B['footprints'] for p in f['pads'] if p['net'] in GND and w['layer'] in p['layers'] and bb.intersects(Point(p['x'], p['y']))}, key=natkey)
        heat_on = {r: max_P(r) for r in on}
        weak.append(dict(w, parts=on, parts_W=heat_on, heat=any(v >= HOT for v in heat_on.values())))
    gv = [v for v in B['vias'] if v['net'] in GND]
    STITCH = dict(edge=PL.get('edge_stitch'), weak=weak, grid=PL.get('stitch_grid_10mm'), gnd_vias=len(gv), per_cm2=round(len(gv) / (AREA / 100), 2))

# ---------------- what-if: ground stitching vias on a grid wherever the outer ground pour leaves room
WHATIF = None
wp = TC.get('what_if_stitch_mm', 3.0)
if wp and GND and any(PLACED[c] for c in CORNERS):
    gnet = sorted(GND)[0]
    gF = unary_union([geo(n, OUT) for n in GND]).buffer(-0.45)
    other_hard = {L: unary_union([track_geom(t) for t in B['tracks'] if t['layer'] == L and t['net'] not in GND] +
                                 [pg for _, p_, pg in pad_geoms(layer=L) if p_['net'] not in GND]).buffer(0.45) for L in LAYERS}
    drills = unary_union([Point(h_['x'], h_['y']).buffer(h_['d'] / 2 + 0.6) for h_ in HOLES]) if HOLES else Polygon()
    new = []
    for gx in np.arange(x0 + wp / 2, x1, wp):
        for gy in np.arange(y0 + wp / 2, y1, wp):
            pt = Point(gx, gy)
            if not gF.contains(pt) or drills.contains(pt) or any(other_hard[L].contains(pt) for L in LAYERS): continue
            landed = [i for i, L in enumerate(LAYERS) if any(geo(n, L).buffer(-0.3).contains(pt) for n in GND)]
            rc = cell_of(gx, gy)
            if rc and len(landed) > 1: new.append((rc[0], rc[1], landed, 0.3))
    if new:
        ex = MODEL.extra_vias(new)
        hv = HS[H_NOM]
        sols = MODEL.solve([QS[c] for c in CORNERS], hv, hv * HB, extra=ex)
        WHATIF = dict(pitch_mm=wp, added=len(new), h=H_NOM, corners={})
        for c, s in zip(CORNERS, sols):
            pk0, pk1 = BOARD[(c, H_NOM)]['peak'], peak(s)
            parts = {}
            for ref in refs_hot:
                if max_P(ref) >= HOT:
                    b0 = part_temp(ref, RISE[(c, H_NOM)])[0]; b1 = part_temp(ref, s)[0]
                    if b0 is not None: parts[ref] = dict(before=b0, after=b1)
            WHATIF['corners'][c] = dict(peak_before=pk0['rise'] if pk0 else 0, peak_after=pk1[0] if pk1 else 0, parts=parts)
    else:
        WHATIF = dict(pitch_mm=wp, added=0, h=H_NOM, corners={}, note='no free spot on the outer ground pour at this pitch')

# ---------------- maps
if not a.no_maps and any(PLACED[c] for c in CORNERS):
    os.makedirs(PACK + 'maps', exist_ok=True)
    ext = [x0, x0 + NX * PITCH, y0 + NY * PITCH, y0]
    for c in CORNERS:
        if not PLACED[c]: continue
        rl = RISE[(c, H_NOM)]
        vmax = AMB + np.nanmax([np.nanmax(g) for g in rl]); vmin = AMB + np.nanmin([np.nanmin(g) for g in rl])
        fig, axs = plt.subplots(1, 2, figsize=(11, 4.4))
        for ax, li in zip(axs, (0, len(LAYERS) - 1)):
            im = ax.imshow(AMB + rl[li], extent=ext, cmap='inferno', vmin=vmin, vmax=vmax)
            ax.contour(XC, YC, np.where(INSIDE, 1.0, 0.0), levels=[0.5], colors='w', linewidths=0.5)
            placed = []                    # labels: ref at the part, staggered when parts sit close together
            hot_here = [r_ for r_ in refs_hot if HT[c]['by_ref'].get(r_, 0) >= HOT and (FP[r_]['side'] == 'F') == (li == 0)]
            for ref in sorted(hot_here, key=lambda r_: FP[r_]['x']):
                x_, y_ = FP[ref]['x'], FP[ref]['y']
                dy = next((d_ for d_ in (0, 2.5, -2.5, 5, -5, 7.5, -7.5, 10) if not any(abs(x_ - px) < 5 and abs(y_ + d_ - py) < 2.2 for px, py in placed)), 10)
                placed.append((x_, y_ + dy))
                ax.plot([x_], [y_], marker='+', color='cyan', ms=5)
                ax.annotate(ref, (x_, y_), xytext=(x_, y_ + dy - 1.2), color='cyan', fontsize=7, ha='center',
                            bbox=dict(boxstyle='round,pad=0.1', fc='black', alpha=0.6, lw=0), arrowprops=dict(arrowstyle='-', color='cyan', lw=0.5) if dy else None)
            ax.set_title('%s  %s  (h %g W/m2K, ambient %g C)%s' % (c, LAYERS[li], HS[H_NOM], AMB, ('\n' + ', '.join('%s %.2f W' % (r_, HT[c]['by_ref'][r_]) for r_ in hot_here)) if hot_here else ''), fontsize=8)
            ax.set_xlabel('mm'); fig.colorbar(im, ax=ax, shrink=0.8, label='C')
        fig.tight_layout(); fig.savefig(PACK + 'maps/thermal_%s.png' % re.sub(r'[^\w.-]', '_', c), dpi=90); plt.close(fig)

# ---------------- findings, ranked (R18): what fails first, then what is marginal, then what is worth knowing
FIND = []
if not CFG.get('thermal') or not any(HT[c]['total_W'] for c in CORNERS):
    FIND.append(('high', 'heat NOT CHECKED: no losses are configured (%d candidate heat sources UNKNOWN), so no heat-source table and no '
                         'temperature exist for this board. Add review_config.json "thermal" (corners, sources) and rebuild: the review '
                         'cannot report heat as checked without them' % len(CAND)))
def tval(t): return t['Tj'] if t['Tj'] is not None else t['T_board']
for c in CORNERS:
    b = BOARD.get((c, H_NOM)); pk = b and b['peak']
    if not pk: continue
    rows = [r for r in PART_ROWS if r['corner'] == c and r.get('limit') and r['T']]
    over = [r for r in rows if r['limit']['over_nominal']]
    low = [r for r in rows if r['limit']['over_low_h'] and not r['limit']['over_nominal']]
    bover = AMB + pk['rise'] > BOARD_LIM
    blow = any(BOARD[(c, hn)]['peak'] and AMB + BOARD[(c, hn)]['peak']['rise'] > BOARD_LIM for hn in HS)
    if over or low or bover or blow:
        txt = 'corner %s at h %s: board average %.0f C, peak %.0f C (%s near %s; board limit %g C). Over their limit: %s%s' % (
            c, H_NOM, AMB + b['avg_solver'], AMB + pk['rise'], pk['layer'], pk['near'], BOARD_LIM,
            ', '.join('%s %s %.0f C > %g C (%s)' % (r['ref'], 'Tj' if r['T'][H_NOM]['Tj'] is not None else 'board', tval(r['T'][H_NOM]), r['limit']['C'], r['limit']['what']) for r in over) or 'no part',
            ('; over only at the lowest h: ' + ', '.join(r['ref'] for r in low)) if low else '')
        if b['avg_solver'] + AMB > BOARD_LIM or (over and all(AMB + b['avg_solver'] > r['limit']['C'] for r in over)):
            txt += '. The board AVERAGE is already past these limits: the total loss is too high for this board area and h (copper and vias cannot fix an average)'
        FIND.append(('high' if over or bover else 'medium', txt))
    # parts well above the board average: heat trapped locally, where copper and vias do help
    for r in PART_ROWS:
        if r['corner'] != c or not r['T'].get(H_NOM): continue
        ex = r['T'][H_NOM]['board_rise'] - b['avg_solver']
        if ex > 10 and r['P_W'] >= HOT:
            FIND.append(('medium', '%s at %s: %.0f K above the board average (%.2f W): heat trapped near the part - see its pours and pads' % (r['ref'], c, ex, r['P_W'])))
    cond, conv = SPLIT[c]
    if cond > conv and cond > 0:
        FIND.append(('info', 'corner %s: conduction (I^2 R in FETs, fuse, BATFET, inductors, copper) %.2f W exceeds conversion (converters, regulators) %.2f W - the series path, not the converters, is the main heat source' % (c, cond, conv)))
    if HT[c]['unknown']:
        FIND.append(('medium', 'corner %s: %d UNKNOWN loss(es) (%s) are not in the temperatures' % (c, len(HT[c]['unknown']), ', '.join(sorted({r['name'] for r in HT[c]['unknown']})))))
for e in EPADS:
    if e['severity'] in ('high', 'medium'): FIND.append((e['severity'], '%s pad %s (%s, %.2f W max): %s' % (e['ref'], e['pad'], e['net'], e['P_max_W'], e['flag'])))
for e in POURS:
    if e['severity'] in ('high', 'medium'): FIND.append((e['severity'], 'pour %s on %s under %s (%.1f mm^2): %s' % (e['net'], e['layer'], e['ref'], e['piece_mm2'], e['flag'])))
for w in (STITCH.get('weak') or []):
    if w['heat']: FIND.append(('high', 'ground island %s %.1f mm^2 at %s with %d via(s) carries %s' % (w['layer'], w['area_mm2'], w['bbox'], w['stitch_vias'], ', '.join('%s %.2f W' % (r, w['parts_W'][r]) for r in w['parts'] if w['parts_W'][r] >= HOT))))
if WHATIF and WHATIF.get('corners'):
    best = max(((r, c, d['before'] - d['after']) for c, v in WHATIF['corners'].items() for r, d in v['parts'].items()), key=lambda t: t[2], default=None)
    if best and best[2] > 5: FIND.append(('medium', 'ground stitching every %.1f mm would lower %s by %.0f K at %s: heat is trapped on the outer layer there' % (WHATIF['pitch_mm'], best[0], best[2], best[1])))
    elif best: FIND.append(('info', 'ground stitching every %.1f mm (%d vias) changes no hot part by more than %.1f K: stitching does not limit the temperature here; the loss, the board area and h do' % (WHATIF['pitch_mm'], WHATIF['added'], best[2])))
if STITCH.get('edge') and STITCH['edge'].get('gaps_over_10mm'):
    FIND.append(('info', 'edge stitching: %d ground vias within 3 mm of the edge, gaps up to %.0f mm (an EMC finding, checklist s3; for heat see the pours and the what-if)' % (
        STITCH['edge']['vias_within_3mm'], max(g['gap_mm'] for g in STITCH['edge']['gaps_over_10mm']))))
FIND.sort(key=lambda f: {'high': 0, 'medium': 1, 'info': 2}[f[0]])

# ---------------- json
def jrow(r): return {k: v for k, v in r.items() if not k.startswith('_')}
out = dict(ambient_C=AMB, h_W_m2K=HS, h_bottom_ratio=HB, pitch_mm=PITCH, k_fr4=K_FR4, via_plating_um=PLATE, area_mm2=AREA, corners=CORNERS,
           stackup=dict(layers=[dict(name=d['name'], t_mm=d['t_mm'], z_mm=round(d['z_mm'], 4)) for d in LAYER_DATA], gaps_mm=[round(g, 4) for g in GAPS]),
           heat={c: dict(title=v['title'], total_W=v['total_W'], placed_W=PLACED[c], groups=v['groups'], by_ref=v['by_ref'], rows=[jrow(r) for r in v['rows']])
                 for c, v in HT.items()},
           board=[BOARD[k] for k in sorted(BOARD)], board_T_max_C=BOARD_LIM, tau_s=TAU, conduction_vs_conversion_W=SPLIT,
           findings=[dict(severity=a_, text=b_) for a_, b_ in FIND], parts=PART_ROWS, exposed_pads=EPADS, pours=POURS, stitching=STITCH, what_if=WHATIF,
           coverage=dict(warnings=list(dict.fromkeys(WARN + TW)), candidates=CAND, nodes=MODEL.n, cells=[NY, NX], vias_modelled=len(VIAS),
                         holes=len(HOLES), solve_s=round(t_solve, 1)))
json.dump(out, open(PACK + 'thermal.json', 'w'), indent=1, default=float)

# ---------------- markdown
def f1(v, fmt='%.1f'): return '-' if v is None else fmt % v
m = ['# Heat: sources, board temperature, thermal vias and stitching', '',
     'Method: losses per part per corner from `review_config.json` "thermal" (heat.py: I^2 R, converter efficiency, linear drop, '
     'given figures, copper loss from the power runs). Temperatures from a steady-state layered solve on this board\'s copper '
     '(thermal_model.py: every copper layer at %.2f mm cells with nets kept apart, k_cu 385 W/mK, FR4 k %.2f W/mK between layers, '
     'via barrels %g um plating, each part\'s heat on its pads, copper loss along each run\'s copper), cooled from both faces at '
     'an effective film coefficient h (convection + radiation) to ambient %g C. No enclosure air model, no airflow, no heat through '
     'wires, cells or mounting: h is the dominant uncertainty, so every temperature is shown at %s.' % (
         PITCH, K_FR4, PLATE, AMB, ' / '.join('%s h = %g W/m^2K' % kv for kv in HS.items())), '']
m += ['## Coverage and warnings (read first)', ''] + ['- ' + w for w in out['coverage']['warnings']] + (['- none'] if not out['coverage']['warnings'] else []) + ['']
m += ['- Candidate heat sources (by structure: ICs, FETs, inductors, fuses, diodes, beads, resistors <= 1 ohm, parts on power-run ends): %d; '
      'with a thermal entry: %d.' % (len(CAND), len(CAND) - len({r['ref'] for r in HT[CORNERS[0]]['rows'] if r['why'].startswith('not in thermal.sources')})),
      '- Model: %d x %d cells per layer, %d nodes, %d vias / plated holes joining layers, solved in %.1f s.' % (NX, NY, MODEL.n, len(VIAS), t_solve), '']
m += ['## Findings, ranked', ''] + ['- **%s**: %s' % f for f in FIND] + (['- none'] if not FIND else []) + ['']
m += ['## Heat sources per corner', '']
for c in CORNERS:
    v = HT[c]
    m += ['### %s%s' % (c, ': ' + v['title'] if v['title'] else ''), '',
          'Total known: **%.2f W** (conduction %.2f W, conversion %.2f W). By group: %s. UNKNOWN: %d.' % (v['total_W'], SPLIT[c][0], SPLIT[c][1], ', '.join('%s %.2f W' % kv for kv in sorted(v['groups'].items(), key=lambda kv: -kv[1])) or 'none', len(v['unknown'])), '',
          '| Part | What | Kind | Loss (W) | Inputs | Basis |', '|---|---|---|---|---|---|']
    for r in v['listed']:
        m.append('| %s | %s | %s | %.3f | %s | %s%s%s |' % (r['name'], r['what'], r['kind'], r['P_W'], r.get('inputs', ''), r.get('basis', ''),
                                                       ('; I: ' + r['I_basis']) if r.get('I_basis') else '', (' **ASSUMED**' if r.get('assumed') else '') + ((' (' + r['note'] + ')') if r.get('note') else '')))
    for r in v['unknown']:
        m.append('| %s | %s | %s | **UNKNOWN** | %s | |' % (r['name'], r['what'], r['kind'], r['why']))
    if v['below']: m.append('')
    if v['below']: m.append('- Below the %.2f W listing threshold: %s' % (TC.get('list_threshold_W', 0.05), ', '.join('%s %.3f W' % (r['name'], r['P_W']) for r in v['below'])))
    if v['negligible']: m.append('- Negligible by decision: %s' % '; '.join('%s (%s)' % (r['name'], r['why']) for r in v['negligible']))
    m.append('')
if len(CORNERS) > 1:
    m += ['### Per part, every corner (W)', '', '| Part | ' + ' | '.join(CORNERS) + ' |', '|---' * (len(CORNERS) + 1) + '|']
    allref = sorted({r for c in CORNERS for r in HT[c]['by_ref']}, key=lambda r: -max(HT[c]['by_ref'].get(r, 0) for c in CORNERS))
    for r in allref:
        if max(HT[c]['by_ref'].get(r, 0) for c in CORNERS) <= 0: continue
        m.append('| %s | %s |' % (r, ' | '.join(f1(HT[c]['by_ref'].get(r), '%.3f') for c in CORNERS)))
    m.append('')
m += ['## Board temperature', '',
      'Board average = P / (A x (h_top + h_bottom)) with A = %.0f mm^2 (one face): where every watt must go. The solver\'s mean '
      'face rise must equal it (energy balance); the peak above it is what spreading does not remove. A peak close to the average '
      'means the board is nearly isothermal (more copper or vias will not help much: only area, airflow or less loss will); a peak '
      'far above it means heat is trapped near its source. Board limit: %g C. Time constant of the bare board (FR4 + copper, '
      'parts add to it): %s - a corner that lasts much less than that does not reach these temperatures, one that lasts longer does.' % (
          AREA, BOARD_LIM, ', '.join('%.0f s at h %s' % (TAU[hn], hn) for hn in HS)), '',
      '| Corner | h (W/m^2K) | Heat placed (W) | Board average rise (P/2Ah) | Solver mean rise | Peak rise | Peak at | Peak T (C) |', '|---|---|---|---|---|---|---|---|']
for c in CORNERS:
    for hn in HS:
        b = BOARD[(c, hn)]
        pk = b['peak']
        m.append('| %s | %s %g | %.2f | %.1f K | %.1f K | %s | %s | %s |' % (c, hn, b['h_W_m2K'], b['placed_W'], b['avg_analytic'], b['avg_solver'],
                 f1(pk and pk['rise'], '%.1f K'), '%s (%.1f, %.1f) near %s' % (pk['layer'], pk['x'], pk['y'], pk['near']) if pk else '-',
                 f1(pk and AMB + pk['rise'])))
m += ['', '## Parts: board temperature at the pads and junction estimate', '',
      'T board = ambient + the mean rise over the part\'s pads. Tj = T board + P x psi_JB (datasheet), or pad + P x theta_JC where the '
      'case is the soldered pad; otherwise only the board temperature is known (say so, do not guess a junction).', '',
      '| Part | Corner | Loss (W) | ' + ' | '.join('T board / Tj at h %s' % hn for hn in HS) + ' | Junction method | Limit |', '|---|---|---|' + '---|' * len(HS) + '---|---|']
for r in sorted(PART_ROWS, key=lambda r: (-max(HT[c]['by_ref'].get(r['ref'], 0) for c in CORNERS), r['ref'], CORNERS.index(r['corner']))):
    if r['P_W'] < TC.get('list_threshold_W', 0.05): continue
    lim = r.get('limit')
    ltxt = '-' if not lim else '%s %g C: %s' % (lim['what'], lim['C'], '**OVER at nominal h**' if lim['over_nominal'] else '**over at some h**' if lim['over_low_h'] else 'ok')
    m.append('| %s %s | %s | %.3f | %s | %s | %s |' % (r['ref'], r['value'], r['corner'], r['P_W'],
             ' | '.join('%.0f / %s' % (r['T'][hn]['T_board'], f1(r['T'][hn]['Tj'], '%.0f')) if hn in r['T'] else '-' for hn in HS),
             next(iter(r['T'].values()))['tj_how'] if r['T'] else '-', ltxt))
m += ['', '## Exposed pads and thermal vias', '',
      'Every pad of 1 mm^2 or more that is at least twice its footprint\'s median pad (exposed pads, FET drain tabs). Via '
      'conductance is the barrel (k_cu x pi x drill x plating / span) to the nearest layer where the via lands on its own net; '
      'dT is the drop across the vias if all of the part\'s worst-corner loss went through them (an upper bound).', '',
      '| Part | Pad | Net | Area mm^2 | In pad / beside | Recommended | R vias (K/W) | dT at max loss | Part max W | Finding |', '|---|---|---|---|---|---|---|---|---|---|']
for e in sorted(EPADS, key=lambda e: ({'high': 0, 'medium': 1, 'low': 2, 'ok': 3}[e['severity']], -e['P_max_W'])):
    m.append('| %s %s | %s | %s | %.1f | %d / %d | %d | %s | %s | %.2f | %s%s |' % (e['ref'], e['value'], e['pad'], e['net'], e['area_mm2'], e['vias_in_pad'], e['vias_beside'],
             e['recommended'], f1(e['R_K_W']), f1(e['dT_vias_K'], '%.1f K'), e['P_max_W'], ('**%s**: ' % e['severity']) if e['severity'] in ('high', 'medium') else '', e.get('flag', 'ok')))
if not EPADS: m.append('| - | none found | | | | | | | | |')
m += ['', '## Pours under hot parts (stitching for heat)', '',
      'For every part at or above %.2f W at some corner, each pour (zone fill) its pads sit on: the same-net vias that join it '
      'to another layer, the FR4 under it, and from the solve at the part\'s worst corner (h %s) the temperature step from the pour '
      'to the layer below and the heat that crosses it (through vias / in total). A pour that only FR4 drains, with a step of '
      'many kelvin, is where stitching vias - to a plane of the same net - lower the part\'s temperature.' % (HOT, H_NOM), '',
      '| Part | Net | Layer | Corner | Pour mm^2 | Vias | G vias / G FR4 (W/K) | Step to layer below (K) | Heat down: vias / total (W) | Under it (next layer) | Finding |', '|---|---|---|---|---|---|---|---|---|---|---|']
for e in sorted(POURS, key=lambda e: ({'high': 0, 'medium': 1, 'ok': 2}[e['severity']], -e['dT_K'])):
    m.append('| %s | %s | %s | %s | %.1f | %d | %.3f / %.3f | %.1f | %.2f / %.2f | %s | %s%s |' % (e['ref'], e['net'], e['layer'], e['corner'], e['piece_mm2'], e['vias'], e['G_vias_W_K'], e['G_fr4_W_K'],
             e['dT_K'], e['Q_vias_W'], e['Q_down_W'], ', '.join('%s %d%%' % kv for kv in e['under'].items()) or '-', ('**%s**: ' % e['severity']) if e['severity'] != 'ok' else '', e.get('flag') or ('ok' + ('; ' + e['note'] if e.get('note') else ''))))
if not POURS: m.append('| - | no pour under a part at or above the hot threshold | | | | | | | | | |')
m += ['', '## Ground stitching', '']
if STITCH:
    es = STITCH['edge'] or {}
    m += ['- Ground vias: %d (%.2f per cm^2 of board). Per 10 mm square (rows top to bottom, -1 = outside the board): %s' % (
              STITCH['gnd_vias'], STITCH['per_cm2'], ' / '.join(' '.join(str(v) for v in row) for row in (STITCH['grid'] or {}).get('rows', []))),
          '- Edge: %d ground vias or plated ground holes within 3 mm of the edge on a %.0f mm perimeter; gaps over 10 mm: %s' % (
              es.get('vias_within_3mm', 0), es.get('perimeter_mm', 0), ', '.join('%.0f mm (%s to %s)' % (g['gap_mm'], g['from_xy'], g['to_xy']) for g in es.get('gaps_over_10mm', [])) or 'none'),
          '- Weakly stitched ground pieces (fewer than 2 vias): %d.' % len(STITCH['weak'])]
    for w in STITCH['weak']:
        m.append('  - %s %.1f mm^2 at %s, %d via(s); parts on it: %s%s' % (w['layer'], w['area_mm2'], w['bbox'], w['stitch_vias'],
                 ', '.join('%s %.2f W' % (r, w['parts_W'][r]) for r in w['parts']) or 'none',
                 ' - **heat: a part at or above %.2f W sits on it**' % HOT if w['heat'] else ''))
else:
    m.append('- not measured (no planes.json)')
if WHATIF:
    m += ['', '## What-if: ground stitching vias every %.1f mm' % WHATIF['pitch_mm'], '']
    if WHATIF['added']:
        m += ['%d virtual 0.3 mm ground vias where the outer ground pour leaves room (0.45 mm from other copper), solved at h %s:' % (WHATIF['added'], WHATIF['h']), '',
              '| Corner | Peak rise before / after (K) | Hot parts: board rise before / after (K) |', '|---|---|---|']
        for c, v in WHATIF['corners'].items():
            m.append('| %s | %.1f / %.1f | %s |' % (c, v['peak_before'], v['peak_after'], ', '.join('%s %.1f / %.1f' % (r, d['before'], d['after']) for r, d in v['parts'].items()) or '-'))
        m += ['', 'A small change means the stitching is not what limits the temperature here (area, h and the loss are); a large '
              'one means heat is trapped on the outer layer and vias are a cheap fix.']
    else:
        m.append('- %s' % WHATIF.get('note', 'none added'))
m += ['', '## Limits', '', '- See `analysis-limits.md` (heat). Steady state only; no enclosure air or wall model, no airflow, no heat through '
      'wires, cells, connectors or mounting screws; parts\' bodies and their own convection are not modelled (heat enters the board at '
      'the pads); copper resistance is not iterated with temperature; h is uniform over each face.']
open(PACK + 'thermal.md', 'w').write('\n'.join(m) + '\n')
for w in TW: print('  !!', w)
print('thermal ok: %d corner(s), %s W; %d exposed pads, %d hot-part pours; %.1f s' % (
    len(CORNERS), ', '.join('%.2f' % HT[c]['total_W'] for c in CORNERS), len(EPADS), len(POURS), time.time() - t_start))
