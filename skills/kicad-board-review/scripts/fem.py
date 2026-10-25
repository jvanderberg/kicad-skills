# Resistive-grid DC solver for one net across all copper layers.
# Each layer's copper is rasterised at pitch h; neighbouring cells are joined by the layer's sheet conductance, vias and
# plated pads join the layers through their barrels. The source pads are held at 0 V and each sink pad draws its current,
# so the voltage at a sink is the IR drop from the source.
#
# Known artefact: a grid can leave one pad cell with no copper neighbours, which reports an absurd drop (GV). If one sink
# looks absurd and the rest look sane, re-solve at a slightly different pitch (0.19 vs 0.2) before believing anything.
import math
import numpy as np
import scipy.sparse as sp, scipy.sparse.linalg as spl
from common import *

RHO = 1.72e-8          # ohm m, copper at 20 C (about +0.39 %/C)
T_PLATE = 20e-6        # via wall plating; JLC and most fabs quote 18-25 um

def thickness(L, t_in=None):
    """copper thickness in metres; t_in overrides inner layers (fab default is often 0.5 oz inside)"""
    if t_in is not None and L not in ('F.Cu', 'B.Cu'): return t_in
    return STACK[L]['t'] * 1e-3

def solve(net, source, sinks, h=0.15, t_in=None, region=None, extra_vias=()):
    """source: list of (ref, pad); sinks: list of ((ref, pad), amps); amps < 0 injects current. Returns dict."""
    t = {L: thickness(L, t_in) for L in LAYERS}
    geo = {L: copper(net, L) for L in LAYERS}
    if region is not None: geo = {L: g.intersection(region) for L, g in geo.items()}
    allg = unary_union([g for g in geo.values() if not g.is_empty])
    x0, y0, x1, y1 = allg.bounds
    nx, ny = int((x1 - x0) / h) + 2, int((y1 - y0) / h) + 2
    xs = x0 + (np.arange(nx) + 0.5) * h; ys = y0 + (np.arange(ny) + 0.5) * h
    X, Y = np.meshgrid(xs, ys)
    masks = {}; idx = {}; n = 0
    for L in LAYERS:
        g = geo[L]
        m = shapely.contains_xy(g, X, Y) if not g.is_empty else np.zeros_like(X, bool)
        masks[L] = m
        ii = -np.ones(m.shape, int); k = int(m.sum()); ii[m] = np.arange(n, n + k); idx[L] = ii; n += k
    rows, cols, vals = [], [], []
    def add(a, b, g):
        rows.extend([a, b, a, b]); cols.extend([a, b, b, a]); vals.extend([g, g, -g, -g])
    for L in LAYERS:
        ii = idx[L]; g = t[L] / RHO     # sheet conductance (S per square)
        for dy, dx in ((0, 1), (1, 0)):
            a = ii[:ii.shape[0] - dy, :ii.shape[1] - dx]; b = ii[dy:, dx:]
            ok = (a >= 0) & (b >= 0)
            A, Bb = a[ok], b[ok]
            rows.extend(np.concatenate([A, Bb, A, Bb]).tolist()); cols.extend(np.concatenate([A, Bb, Bb, A]).tolist())
            vals.extend([g] * (2 * len(A)) + [-g] * (2 * len(A)))
    def cell(L, x, y, r=0.35):
        c = int((x - x0) / h); rr = int((y - y0) / h)
        if 0 <= rr < ny and 0 <= c < nx and idx[L][rr, c] >= 0: return idx[L][rr, c]
        k = int(r / h) + 1; best = None
        for dr in range(-k, k + 1):
            for dc in range(-k, k + 1):
                R_, C_ = rr + dr, c + dc
                if 0 <= R_ < ny and 0 <= C_ < nx and idx[L][R_, C_] >= 0:
                    d = dr * dr + dc * dc
                    if best is None or d < best[0]: best = (d, idx[L][R_, C_])
        return None if best is None else best[1]
    barrels = [(v['x'], v['y'], v['drill']) for v in B['vias'] if v['net'] == net] + list(extra_vias)
    barrels += [(p['x'], p['y'], p['drill']) for f in B['footprints'] for p in f['pads'] if p['net'] == net and p['th'] and p['drill'] > 0]
    links = []
    for (x, y, d) in barrels:
        if region is not None and not region.contains(Point(x, y)): continue
        cs = [(L, cell(L, x, y)) for L in sorted(LAYERS, key=lambda l: STACK[l]['z'])]
        cs = [(L, c) for L, c in cs if c is not None]
        for (La, a), (Lb, b) in zip(cs, cs[1:]):
            dz = max(STACK[Lb]['z'] - STACK[La]['z'], 0.05) * 1e-3
            g = math.pi * d * 1e-3 * T_PLATE / (RHO * dz)
            add(a, b, g); links.append((x, y, La, Lb, a, b, g))
    G = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
    def pad_cells(ref, num):
        out = []
        for p in FP[ref]['pads']:
            if p['num'] != num: continue
            pg = unary_union(polys(p['poly']))
            for L in p['layers']:
                m = shapely.contains_xy(pg, X, Y) & masks[L]
                out += idx[L][m].tolist()
                if not m.any():
                    c = cell(L, p['x'], p['y'], 0.5)
                    if c is not None: out.append(c)
        return out
    src = []
    for ref, num in source: src += pad_cells(ref, num)
    assert src, ('no source cells', net, source)
    I = np.zeros(n); sink_cells = []
    for (ref, num), amps in sinks:
        cs = pad_cells(ref, num); assert cs, ('no sink cells: is %s pad %s on net %s?' % (ref, num, net))
        I[cs] -= amps / len(cs); sink_cells.append(cs)
    fixed = np.zeros(n, bool); fixed[src] = True
    free = np.where(~fixed)[0]
    Gf = G[free][:, free] + sp.identity(len(free)) * 1e-9      # tiny leak keeps islands from making it singular
    V = np.zeros(n)
    V[free] = spl.spsolve(Gf.tocsc(), I[free])
    res = dict(net=net, cells=n, vias=len(barrels), h=h, sinks=[])
    for ((ref, num), amps), cs in zip(sinks, sink_cells):
        res['sinks'].append(dict(ref=ref, pad=num, amps=amps, drop_mV=-1e3 * float(np.mean(V[cs]))))
    P = 0.0; hot = {}; loss = {}
    for L in LAYERS:
        ii = idx[L]; g = t[L] / RHO
        Vg = np.full(ii.shape, np.nan); Vg[ii >= 0] = V[ii[ii >= 0]]
        jx = np.zeros(ii.shape); jy = np.zeros(ii.shape)
        dx = np.nan_to_num((Vg[:, :-1] - Vg[:, 1:]) * g); dy = np.nan_to_num((Vg[:-1, :] - Vg[1:, :]) * g)
        P += float((dx ** 2).sum() / g + (dy ** 2).sum() / g)
        jx[:, :-1] += dx / 2; jx[:, 1:] += dx / 2; jy[:-1, :] += dy / 2; jy[1:, :] += dy / 2
        hot[L] = np.hypot(jx, jy) / h    # amps per mm of copper width
        # where the copper loss is dissipated (W per cell: each link's I^2/g split between its two cells), for thermal.py
        w = np.zeros(ii.shape)
        ex, ey = dx ** 2 / g, dy ** 2 / g
        w[:, :-1] += ex / 2; w[:, 1:] += ex / 2; w[:-1, :] += ey / 2; w[1:, :] += ey / 2
        loss[L] = w
    # current through each via / plated hole, summed over its layer links
    vi = collections.defaultdict(float)
    for (x, y, La, Lb, a, b, g) in links:
        vi[(round(x, 3), round(y, 3))] = max(vi[(round(x, 3), round(y, 3))], abs(g * (V[a] - V[b])))
    res['via_amps'] = sorted(([x, y, i] for (x, y), i in vi.items()), key=lambda r: -r[2])
    # signed current through every barrel segment, from layer La to layer Lb (for "how much leaves this layer")
    res['link_flows'] = [(x, y, La, Lb, float(g * (V[a] - V[b]))) for (x, y, La, Lb, a, b, g) in links]
    res['P_W'] = P
    res['grid'] = dict(x0=x0, y0=y0, h=h, shape=(ny, nx))
    res['_hot'] = hot; res['_V'] = V; res['_idx'] = idx; res['_loss'] = loss
    return res

def hotspots(res, thr, top=6):
    """clusters of cells above thr A/mm, largest peak first: (layer, peak, x, y, extent_mm)"""
    from scipy import ndimage
    g = res['grid']; out = []
    for L, A in res['_hot'].items():
        m = A > thr
        if not m.any(): continue
        lab, k = ndimage.label(m)
        for i in range(1, k + 1):
            sel = lab == i
            pk = A[sel].max(); r, c = np.unravel_index(np.argmax(np.where(sel, A, 0)), A.shape)
            rr, cc = np.where(sel)
            out.append((L, float(pk), g['x0'] + (c + 0.5) * g['h'], g['y0'] + (r + 0.5) * g['h'], float(max(np.ptp(rr), np.ptp(cc)) * g['h'])))
    return sorted(out, key=lambda t: -t[1])[:top]
