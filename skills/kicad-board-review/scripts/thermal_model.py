# Steady-state layered heat-spreading model of a PCB (pure numpy/scipy: no board.json, so it can be tested on its own).
#
# One node per grid cell per copper layer. Each node carries its layer's copper (k_cu x thickness x the cell's copper
# fraction, joined only to neighbouring cells of the SAME net, so a clearance gap between two pours does not conduct as
# copper) plus half of the dielectric above and below it (in-plane FR4). Adjacent copper layers are joined cell by cell
# through the dielectric (k_fr4 x cell area / thickness) and, at every via or plated hole, through its barrel
# (k_cu x pi x drill x plating / span, between the layers where the hole lands on copper of its own net). The two outer
# layers lose heat to ambient through an effective film coefficient h (convection plus radiation) on every cell inside
# the outline. Board edges, the parts' own bodies, wires and the enclosure are not modelled (see analysis-limits.md).
#
# Units: millimetres for geometry, watts and kelvin for heat; temperatures returned are rises above ambient.
import math
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl

K_CU = 385.0          # W/mK, copper
K_FR4 = 0.3           # W/mK, FR4 through the thickness (in-plane is higher, about 0.8; 0.3 is the conservative figure)
PLATING_UM = 20.0     # via barrel plating; fabs quote 18-25 um


def via_conductance(drill_mm, span_mm, plating_um=PLATING_UM, k=K_CU):
    """W/K of a plated barrel (thin wall: pi x d x t) over a span between two copper layers"""
    return k * math.pi * drill_mm * 1e-3 * plating_um * 1e-6 / (max(span_mm, 1e-3) * 1e-3)


class Layered:
    """inside: (ny, nx) bool, cells that are board. layers: list of dict(name, t_mm (copper), z_mm (centre of the copper),
    frac (ny, nx) copper fraction 0..1, label (ny, nx) int net id, -1 = no copper). gaps_mm: dielectric between layer i and
    i+1 (len = layers - 1). vias: list of (iy, ix, [layer indices where it lands, top to bottom], drill_mm)."""

    def __init__(self, pitch_mm, inside, layers, gaps_mm, vias=(), k_fr4=K_FR4, k_fr4_inplane=None, plating_um=PLATING_UM):
        self.h = pitch_mm; self.inside = inside; self.layers = layers; self.gaps = list(gaps_mm)
        self.k_fr4 = k_fr4; self.k_fr4_in = k_fr4 if k_fr4_inplane is None else k_fr4_inplane
        self.plating_um = plating_um
        ny, nx = inside.shape; nL = len(layers)
        assert len(self.gaps) == nL - 1, 'one dielectric gap between each pair of copper layers'
        self.idx = []; n = 0
        for _ in layers:
            ii = -np.ones((ny, nx), int); k = int(inside.sum()); ii[inside] = np.arange(n, n + k); self.idx.append(ii); n += k
        self.n = n
        rows, cols, vals = [], [], []

        def add(a, b, g):
            rows.append(np.concatenate([a, b, a, b])); cols.append(np.concatenate([a, b, b, a]))
            vals.append(np.concatenate([g, g, -g, -g]))
        A = (pitch_mm * 1e-3) ** 2
        for i, L in enumerate(layers):
            ii = self.idx[i]; f = np.where(inside, L['frac'], 0.0); lab = L['label']
            t_fr4 = 0.5 * ((self.gaps[i - 1] if i > 0 else 0.0) + (self.gaps[i] if i < nL - 1 else 0.0)) * 1e-3
            for dy, dx in ((0, 1), (1, 0)):
                a = ii[:ny - dy, :nx - dx]; b = ii[dy:, dx:]
                ok = (a >= 0) & (b >= 0)
                fa = f[:ny - dy, :nx - dx]; fb = f[dy:, dx:]
                same = (lab[:ny - dy, :nx - dx] == lab[dy:, dx:]) & (lab[:ny - dy, :nx - dx] >= 0)
                g = K_CU * L['t_mm'] * 1e-3 * np.where(same, 0.5 * (fa + fb), 0.0) + self.k_fr4_in * t_fr4   # square cell: k t w/l = k t
                add(a[ok], b[ok], g[ok])
        for i in range(nL - 1):
            a = self.idx[i][inside]; b = self.idx[i + 1][inside]
            add(a, b, np.full(len(a), k_fr4 * A / (self.gaps[i] * 1e-3)))
        self.via_g = 0.0
        for (iy, ix, landed, d) in vias:
            if not (0 <= iy < ny and 0 <= ix < nx) or not inside[iy, ix]: continue
            for la, lb in zip(landed, landed[1:]):
                g = via_conductance(d, abs(layers[lb]['z_mm'] - layers[la]['z_mm']), plating_um)
                add(np.array([self.idx[la][iy, ix]]), np.array([self.idx[lb][iy, ix]]), np.array([g]))
        self.G = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
        self.surface_area_m2 = float(inside.sum()) * A
        self.ncell = n; self.bodies = []; self.body_T = []

    def add_bodies(self, bodies):
        """parts' bodies: one extra node per body, joined to board nodes by [(node, W/K), ...]. Heat put on a body node
        reaches the board through whichever of its pads the board can take it from, as it does through a real package.
        Returns the bodies' node indices (use them in Q)."""
        k0 = self.n; nb = len(bodies)
        rows, cols, vals = [], [], []
        for i, links in enumerate(bodies):
            k = k0 + i
            for a, g in links:
                rows += [k, a, k, a]; cols += [k, a, a, k]; vals += [g, g, -g, -g]
        G = sp.block_diag([self.G, sp.csr_matrix((nb, nb))]).tocsr()
        self.G = (G + sp.csr_matrix((vals, (rows, cols)), shape=(k0 + nb, k0 + nb))).tocsr()
        self.n = k0 + nb; ids = list(range(k0, k0 + nb)); self.bodies += ids
        return ids

    def solve(self, Q, h_top, h_bot=None, extra=None):
        """Q: (n,) watts per node (or a list of such vectors). Returns rises: list (one per Q) of [per-layer (ny, nx) arrays,
        NaN outside]. h in W/m^2K on the top (layer 0) and bottom (last layer) faces."""
        h_bot = h_top if h_bot is None else h_bot
        A = (self.h * 1e-3) ** 2
        d = np.full(self.n, 1e-15)        # a negligible leak so an island with no path to ambient is not singular
        if extra is not None and extra.shape[0] < self.n: extra = sp.block_diag([extra, sp.csr_matrix((self.n - extra.shape[0],) * 2)]).tocsr()
        d[self.idx[0][self.inside]] += h_top * A
        d[self.idx[-1][self.inside]] += h_bot * A
        M = self.G + sp.diags(d)
        if extra is not None: M = M + extra
        lu = spl.splu(M.tocsc())
        Qs = Q if isinstance(Q, list) else [Q]
        out = []; self.body_T = []
        for q in Qs:
            q = np.asarray(q, float)
            if len(q) < self.n: q = np.concatenate([q, np.zeros(self.n - len(q))])
            T = lu.solve(q)
            out.append(self.unpack(T)); self.body_T.append(T[self.ncell:])
        return out if isinstance(Q, list) else out[0]

    def unpack(self, T):
        res = []
        for ii in self.idx:
            g = np.full(ii.shape, np.nan); g[ii >= 0] = T[ii[ii >= 0]]; res.append(g)
        return res

    def extra_vias(self, vias):
        """sparse conductance matrix for additional barrels (what-if stitching), same format as the constructor's vias"""
        rows, cols, vals = [], [], []
        ny, nx = self.inside.shape
        for (iy, ix, landed, d) in vias:
            if not (0 <= iy < ny and 0 <= ix < nx) or not self.inside[iy, ix]: continue
            for la, lb in zip(landed, landed[1:]):
                g = via_conductance(d, abs(self.layers[lb]['z_mm'] - self.layers[la]['z_mm']), self.plating_um)
                a, b = self.idx[la][iy, ix], self.idx[lb][iy, ix]
                rows += [a, b, a, b]; cols += [a, b, b, a]; vals += [g, g, -g, -g]
        return sp.csr_matrix((vals, (rows, cols)), shape=(self.n, self.n))


def board_average_rise(P_W, area_mm2, h_top, h_bot=None):
    """the sanity check: all the heat leaves both faces evenly, so the area-weighted mean rise is P / (A (h_top + h_bot))"""
    h_bot = h_top if h_bot is None else h_bot
    return P_W / (area_mm2 * 1e-6 * (h_top + h_bot))


def face_mean(rise_layers, inside, h_top, h_bot=None):
    """the solver's area-weighted mean face rise, weighted by h: must equal board_average_rise (energy balance)"""
    h_bot = h_top if h_bot is None else h_bot
    t, b = rise_layers[0][inside], rise_layers[-1][inside]
    return float((h_top * t.sum() + h_bot * b.sum()) / ((h_top + h_bot) * inside.sum()))
