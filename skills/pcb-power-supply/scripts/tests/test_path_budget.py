"""path_budget.py on a case unlike any battery board:  python3 tests/test_path_budget.py
A 5 V USB source through a 0.25 Ohm cable + 30 mOhm connector + 50 mOhm eFuse into a 10 W buck: the naive 2.0 A
hides a 3.9 V node (below a 4.2 V UVLO) and an eFuse trip; the solver must find both, find the hand-computed
operating point, report P_max = V^2/4R when there is no solution, and honour trip delays for a transient."""
import json, math, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import path_budget as pb

SPEC = {'name': 'USB cable to a buck', 'source': {'name': 'USB 5 V', 'V': {'min': 4.75, 'nom': 5.0}, 'R': 0.0},
        'path': [{'name': 'cable', 'R': {'short': 0.10, 'long': 0.25}},
                 {'name': 'connector', 'R': 0.03},
                 {'name': 'eFuse', 'R': 0.05, 'limits': [{'what': 'eFuse trip', 'I_max': 2.5, 't_trip_s': 0.005, 'latches': 'until re-plug'}]}],
        'loads': [{'name': 'buck', 'P_out': 9.0, 'eff': 0.9}],
        'node_limits': [{'what': 'buck UVLO', 'V_min': 4.2}],
        'transients': [{'name': '1 ms 2 A pulse', 'I_add': 2.0, 'duration_s': 0.001}, {'name': '10 ms 2 A step', 'I_add': 2.0, 'duration_s': 0.01}]}


def test_operating_point_matches_hand_solution():
    V, R, P = 5.0, 0.33, 10.0
    I, Vn = pb.operating_point(V, R, P, 0.0)
    assert abs(I * (V - I * R) - P) < 1e-9
    assert abs(I - (V - math.sqrt(V * V - 4 * R * P)) / (2 * R)) < 1e-12 and abs(Vn - 4.218) < 0.01 and I > 2.0
    assert pb.operating_point(3.0, 0.2, 12.0, 0.0) is None            # 12 W > 3^2 / (4 x 0.2) = 11.25 W


def test_corners_find_uvlo_trip_and_collapse():
    res = {(r['source'], r['R_corner']): r for r in pb.solve(SPEC)}
    short = res[('nom', 'short')]
    assert not short['fails'] and abs(short['V_node'] - (5.0 - short['I'] * 0.18)) < 1e-9, short
    long_min = res[('min', 'long')]
    msgs = ' '.join(f for f, _ in long_min['fails'])
    assert 'buck UVLO' in msgs and long_min['I'] > 2.0 * 1.15, long_min        # naive 2.0 A; solved > 2.3 A
    tr = {t['name']: t for t in short['transients']}
    assert not any('eFuse' in f for f, _ in tr['1 ms 2 A pulse']['fails']), tr   # shorter than the 5 ms trip
    assert any('eFuse' in f and latch for f, latch in tr['10 ms 2 A step']['fails']), tr
    assert short['V_src_min'] and 4.5 < short['V_src_min'] < 5.0, short['V_src_min']


def test_cli_and_power_run_copper():
    d = tempfile.mkdtemp()
    json.dump({'runs': [{'name': 'trace', 'P_W': 0.04, 'sinks': [{'ref': 'U1', 'pad': '1', 'amps': 2.0, 'drop_mV': 20}]}]},
              open(os.path.join(d, 'power_runs.json'), 'w'))
    spec = dict(SPEC, path=SPEC['path'] + [{'name': 'copper', 'from_power_run': 'power_runs.json:trace'}])
    json.dump(spec, open(os.path.join(d, 'p.json'), 'w'))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'path_budget.py'), os.path.join(d, 'p.json')], capture_output=True, text=True)
    assert r.returncode == 1 and '| copper | 10.0 |' in r.stdout and 'LATCHES' in r.stdout, r.stdout[-1500:]


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
