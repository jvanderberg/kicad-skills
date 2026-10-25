"""thermal_model.py against closed-form solutions (needs numpy + scipy):  python3 tests/test_thermal_model.py
1. Uniform heating of a plate cooled on both faces: every cell sits at q / (2 h), exactly.
2. A point source on a large thin copper plate cooled on both faces (the fin equation): T(r) = Q / (2 pi k t) K0(r / lam),
   lam = sqrt(k t / 2h).
3. Two copper layers through FR4: heat into the top, cooling only on the bottom: the drop across the dielectric is
   q d / k_fr4 (1-D slab).
4. A single via between two otherwise unconnected layers: its conductance is k pi d t / span.
5. Energy balance: the h-weighted mean face rise equals P / (A (h_top + h_bot)) for any source distribution, and a
   clearance gap between two nets on one layer does not conduct as copper.
6. A part's body node shares its heat between its pads as the board takes it: two pads 1 K/W apart, one on a cooled
   copper island and one on an island with no cooling, put all the steady heat into the cooled one."""
import math, os, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
PY = os.environ.get('PY') or os.path.expanduser('~/.cache/kicad-skills/venv/bin/python')
try:
    import numpy as np
    from scipy.special import k0
    import thermal_model as tm
except ImportError as e:             # the analysis venv has them; plain python3 may not: rerun this file under it
    np = None; _why = str(e)

    def test_under_analysis_python():
        if not os.path.exists(PY):
            import pytest
            pytest.skip('numpy/scipy not importable (%s) and no analysis python at %s' % (_why, PY))
        r = subprocess.run([PY, os.path.abspath(__file__)], capture_output=True, text=True)
        assert r.returncode == 0 and 'FAIL' not in r.stdout, r.stdout + r.stderr[-2000:]


def plate(ny, nx, t_mm=0.035, label=0, frac=1.0):
    return dict(name='L', t_mm=t_mm, z_mm=0.0, frac=np.full((ny, nx), frac), label=np.full((ny, nx), label, int))


def test_uniform_plate():
    ny = nx = 20; h = 1.0
    m = tm.Layered(h, np.ones((ny, nx), bool), [plate(ny, nx)], [], k_fr4=0.0)
    q = 200.0                                           # W/m^2
    Q = np.full(m.n, q * (h * 1e-3) ** 2)
    T = m.solve(Q, 10.0)[0]
    assert np.allclose(T, q / 20.0, rtol=1e-7), (T.min(), T.max(), q / 20)


def test_point_source_fin():
    h = 1.0; n = 301; hc = 10.0; t = 0.035                # 300 mm plate, lam = sqrt(385 * 35e-6 / 20) = 26 mm
    m = tm.Layered(h, np.ones((n, n), bool), [plate(n, n, t)], [], k_fr4=0.0)
    Q = np.zeros(m.n); c = n // 2; P = 1.0
    Q[m.idx[0][c, c]] = P
    T = m.solve(Q, hc)[0]
    kt = tm.K_CU * t * 1e-3; lam = math.sqrt(kt / (2 * hc))
    worst = 0
    for r in (5, 10, 20, 40):
        ana = P / (2 * math.pi * kt) * k0(r * 1e-3 / lam)
        num = T[c, c + r]
        worst = max(worst, abs(num - ana) / ana)
    assert worst < 0.02, worst                          # discretisation error at 1 mm cells, r >= 5 cells
    avg = tm.board_average_rise(P, n * n * h * h, hc)  # the whole plate's heat leaves its faces
    assert abs(tm.face_mean([T], m.inside, hc) - avg) / avg < 1e-6


def test_slab_through_fr4():
    ny = nx = 10; h = 1.0; d = 0.2
    L0 = plate(ny, nx); L1 = dict(plate(ny, nx), z_mm=d)
    m = tm.Layered(h, np.ones((ny, nx), bool), [L0, L1], [d], k_fr4=0.3)
    q = 1000.0
    Q = np.zeros(m.n); Q[m.idx[0][m.inside]] = q * (h * 1e-3) ** 2
    T0, T1 = m.solve(Q, 0.0, 25.0)
    assert np.allclose(T0 - T1, q * d * 1e-3 / 0.3, rtol=1e-6), ((T0 - T1).mean(), q * d * 1e-3 / 0.3)
    assert np.allclose(T1, q / 25.0, rtol=1e-6)


def test_single_via():
    n = 3; h = 1.0; span = 1.6
    L0 = plate(n, n, t_mm=5.0); L1 = dict(plate(n, n, t_mm=5.0), z_mm=span)     # thick copper: each layer ~isothermal
    m = tm.Layered(h, np.ones((n, n), bool), [L0, L1], [span], vias=[(1, 1, [0, 1], 0.3)], k_fr4=0.0)
    Q = np.zeros(m.n); Q[m.idx[0][1, 1]] = 0.1
    T0, T1 = m.solve(Q, 0.0, 1e4)
    R = (np.nanmean(T0) - np.nanmean(T1)) / 0.1
    R_ana = 1 / tm.via_conductance(0.3, span)
    assert abs(R - R_ana) / R_ana < 0.01, (R, R_ana)
    assert 150 < R_ana < 250, R_ana                     # the checklist's "100-200 C/W per 0.3 mm via" order of magnitude


def test_energy_balance_and_clearance_gap():
    ny, nx = 20, 40; h = 0.5
    lab = np.zeros((ny, nx), int); lab[:, 20:] = 1; lab[:, 20] = -1        # two nets with a one-cell gap
    L0 = dict(name='F', t_mm=0.035, z_mm=0.0, frac=(lab >= 0).astype(float), label=lab)
    m = tm.Layered(h, np.ones((ny, nx), bool), [L0], [], k_fr4=0.0)
    Q = np.zeros(m.n); Q[m.idx[0][10, 5]] = 0.5
    T = m.solve(Q, 8.0)[0]
    assert abs(tm.face_mean([T], m.inside, 8.0) - tm.board_average_rise(0.5, ny * nx * h * h, 8.0)) < 1e-6
    assert np.nanmax(T[:, 21:]) < 1e-9, 'heat crossed a gap with no copper and no FR4'
    m2 = tm.Layered(h, np.ones((ny, nx), bool), [dict(L0, label=np.zeros((ny, nx), int), frac=np.ones((ny, nx)))], [], k_fr4=0.0)
    T2 = m2.solve(Q, 8.0)[0]
    assert np.nanmax(T2[:, 21:]) > 1e-3, 'one net with no gap must conduct'


def test_body_node_splits_by_what_the_board_takes():
    ny, nx = 4, 9; h = 1.0
    lab = -np.ones((ny, nx), int); lab[:, :4] = 0; lab[:, 5:] = 1
    L0 = dict(name='F', t_mm=0.035, z_mm=0.0, frac=(lab >= 0).astype(float), label=lab)
    inside = np.ones((ny, nx), bool)
    m = tm.Layered(h, inside, [L0], [], k_fr4=0.0)
    hot = m.idx[0][1, 1]; cold = m.idx[0][1, 7]
    (b,) = m.add_bodies([[(hot, 0.5), (cold, 0.5)]])
    # cool only the left island: an extra conductance to ambient on its cells
    import scipy.sparse as sp
    d = np.zeros(m.n); d[m.idx[0][:, :4].ravel()] = 1.0
    Q = np.zeros(m.n); Q[b] = 2.0
    T = m.solve(Q, 0.0, extra=sp.diags(d))[0]
    flow_left = 1.0 * np.nansum(T[:, :4])
    assert abs(flow_left - 2.0) < 1e-6, flow_left                    # every watt leaves through the cooled pad
    assert abs(m.body_T[0][0] - (T[1, 1] + 2.0 / 0.5)) < 1e-6          # body = pad + P x (its link resistance)


if np is None:                       # under plain python3 only the rerun-under-the-venv test is collected
    for _k in [k for k in list(globals()) if k.startswith('test_') and k != 'test_under_analysis_python']:
        del globals()[_k]

if __name__ == '__main__':
    if np is None:
        print('SKIP: numpy/scipy not importable (%s); run with the analysis venv' % _why); sys.exit(0)
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
