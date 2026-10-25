"""heat.py + thermal.py (+ planes.py) on a synthetic board unlike any battery board (no KiCad needed; needs the analysis
venv):  python3 tests/test_thermal_synthetic.py      (uses $PY or ~/.cache/kicad-skills/venv/bin/python)

An 80 x 50 mm 2-layer, 12 V board: a linear regulator U1 (12 V -> 5 V, its tab on a small F.Cu +5V pour with no +5V
copper anywhere else), a QFN buck U2 whose exposed pad has 4 vias where 9 are the rule of thumb, a 50 mOhm shunt R1, an
inductor L1 whose loss comes from pcb-power-supply's path_budget.py, a FET Q1 on a ground island stitched by one via,
a diode D1 nobody configured, and a copper run that the pack does not have. Checks: every loss computed as the inputs
say; D1 and the missing run are UNKNOWN, not dropped; the solver's mean face rise equals P / (2 A h); lower h is hotter;
the tab with no plane, the via shortfall, the FR4-only pour and the hot part on the weak island are all reported; the
coverage section comes first."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.environ.get('PY') or os.path.expanduser('~/.cache/kicad-skills/venv/bin/python')
PB = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'pcb-power-supply', 'scripts', 'path_budget.py')


def rect(x0, y0, x1, y1): return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def pad(num, net, x, y, w, h, layers=('F.Cu',), th=False, drill=0.0):
    return dict(num=num, net=net, x=x, y=y, layers=list(layers), th=th, drill=drill, poly=[[rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2), []]])


def zone(net, layer, ring, holes=()):
    return dict(net=net, name='', prio=0, keepout=False, layers=[layer], outline=[[ring, []]], min_w=0.2, clearance=0.3,
                filled={layer: [[ring, list(holes)]]})


def fp(ref, value, fpname, x, y, pads):
    return dict(ref=ref, value=value, fp=fpname, lib='', x=x, y=y, rot=0, side='F', pads=pads)


def via(x, y, net):
    return dict(x=x, y=y, net=net, size=0.6, drill=0.3, type=3)


def build(d):
    W, H = 80.0, 50.0
    u2_pads = [pad('9', 'GND', 50, 25, 2.6, 2.6)] + [pad(str(i + 1), n, 48.2 + 1.2 * (i % 4), 23.0 if i < 4 else 27.0, 0.3, 0.8)
                                                     for i, n in enumerate(['VIN', 'VIN', 'SW', 'SW', 'GND', 'FB', 'EN', 'BST'])]
    fps = [fp('U1', 'AMS1117-5.0', 'SOT-223-3_TabPin2', 20, 25, [pad('1', 'GND', 17.7, 28.2, 1.0, 1.8), pad('2', '+5V', 20, 28.2, 1.0, 1.8),
                                                              pad('3', '+12V', 22.3, 28.2, 1.0, 1.8), pad('4', '+5V', 20, 22.0, 3.3, 2.0)]),
           fp('U2', 'BUCK-QFN', 'QFN-8-1EP_3x3mm', 50, 25, u2_pads),
           fp('R1', '0R05', 'R_2512', 35, 10, [pad('1', '+12V', 32, 10, 1.5, 3.0), pad('2', 'VIN', 38, 10, 1.5, 3.0)]),
           fp('L1', '4.7uH', 'L_5x5', 60, 25, [pad('1', 'SW', 58, 25, 1.5, 4.0), pad('2', '+3V3', 62, 25, 1.5, 4.0)]),
           fp('Q1', 'AO3400', 'SOT-23', 70, 42, [pad('1', 'G1', 69.05, 43.1, 0.6, 0.7), pad('2', 'GND', 70.95, 43.1, 0.6, 0.7), pad('3', 'LOAD', 70, 40.9, 0.6, 0.7)]),
           fp('D1', 'SS34', 'D_SMA', 10, 10, [pad('1', '+12V', 8, 10, 1.5, 2.0), pad('2', 'GND', 12, 10, 1.5, 2.0)]),
           fp('J1', '12V IN', 'TestPoint_Pad_3x3mm', 5, 25, [pad('1', '+12V', 5, 25, 3, 3)])]
    vias = [via(49.4, 24.4, 'GND'), via(50.6, 24.4, 'GND'), via(49.4, 25.6, 'GND'), via(50.6, 25.6, 'GND'), via(73.0, 45.0, 'GND')]
    board = dict(source='synthetic-thermal', layers=['F.Cu', 'B.Cu'],
                 stackup=[dict(name='F.Cu', type='copper', thickness_mm=0.035, er=None), dict(name='dielectric 1', type='core', thickness_mm=1.53, er=4.5),
                          dict(name='B.Cu', type='copper', thickness_mm=0.035, er=None)],
                 netclass={}, vias=vias, edge=[[rect(0, 0, W, H), []]], edge_bbox=[0, 0, W, H], footprints=fps,
                 tracks=[dict(a=[22.3, 28.2], b=[22.3, 32], w=1.0, layer='F.Cu', net='+12V')],
                 zones=[zone('+5V', 'F.Cu', rect(15, 18, 25, 24)),                        # U1's tab pour, no +5V elsewhere
                        zone('GND', 'F.Cu', rect(46, 21, 54, 29)),                        # U2's ground pour, 4 vias
                        zone('GND', 'F.Cu', rect(68, 40, 74, 46)),                        # Q1's ground island, 1 via
                        zone('GND', 'B.Cu', rect(0.5, 0.5, W - 0.5, H - 0.5))])
    comps = {f['ref']: dict(ref=f['ref'], value=f['value'], fp=f['fp'], pins={p['num']: [p['net'], '', 'passive'] for p in f['pads']}) for f in fps}
    nets = {}
    for f in fps:
        for p in f['pads']: nets.setdefault(p['net'], []).append([f['ref'], p['num'], '', 'passive'])
    # L1's loss comes from a solved path (pcb-power-supply path_budget.py --json), as a review would take it
    spec = {'name': 'buck output path', 'source': {'name': 'buck', 'V': {'full': 3.3, 'light': 3.3}, 'R': 0.0},
            'path': [{'name': 'L1 DCR', 'ref': 'L1', 'R': 0.030}, {'name': 'output cable', 'R': 0.05, 'off_board': True}],
            'loads': [{'name': 'load', 'I': 1.5}]}
    json.dump(spec, open(os.path.join(d, 'pb.json'), 'w'))
    r = subprocess.run([sys.executable, PB, os.path.join(d, 'pb.json'), '--json', os.path.join(d, 'pb_out.json')], capture_output=True, text=True)
    assert os.path.exists(os.path.join(d, 'pb_out.json')), r.stdout + r.stderr
    cfg = dict(ground_nets=['GND'], net_classes=[], power_runs=[],
               thermal=dict(ambient_C=40, h_W_m2K=dict(low=5, nominal=8, high=12), pitch_mm=0.5, what_if_stitch_mm=4.0,
                            corners=dict(full=dict(title='full load', currents=dict(I_in=1.6)), light=dict(title='light load', currents=dict(I_in=0.4))),
                            sources=[dict(ref='U1', what='LDO', kind='linear', V_in=12, V_out=5, I=dict(full=0.3, light=0.1)),
                                     dict(ref='U2', what='buck', kind='converter', P_out=dict(full=5.0, light=1.0), eff=dict(full=0.9, light=0.8), eff_includes=['L1']),
                                     dict(kind='path', **{'from': {'*': dict(path_budget='pb_out.json', source='full', R_corner='')}}),
                                     dict(ref='R1', what='shunt', kind='i2r', R_ohm=0.05, I='I_in'),
                                     dict(ref='Q1', what='load switch', kind='fixed', P_W=dict(full=0.4, light=0.1)),
                                     dict(copper_run='not_a_run', I='I_in'),
                                     dict(ref='J1', kind='negligible', why='a pad')],
                            parts=dict(U1=dict(theta_jc=15.0, Tj_max_C=125), U2=dict(psi_jb=10.0, Tj_max_C=125))))
    for n, v in (('board.json', board), ('netlist.json', dict(components=comps, nets=nets)), ('review_config.json', cfg)):
        json.dump(v, open(os.path.join(d, n), 'w'))


def run(d, *scripts):
    out = ''
    for s in scripts:
        r = subprocess.run([PY, os.path.join(HERE, s), d], capture_output=True, text=True)
        assert r.returncode == 0, (s, r.stdout[-2000:], r.stderr[-3000:])
        out += r.stdout
    return out


def test_synthetic_thermal():
    d = tempfile.mkdtemp()
    build(d)
    out = run(d, 'planes.py', 'thermal.py')
    T = json.load(open(os.path.join(d, 'thermal.json')))
    full = {r['name']: r for r in T['heat']['full']['rows']}
    assert abs(full['U1']['P_W'] - 2.1) < 1e-9, full['U1']                                  # (12 - 5) x 0.3
    assert abs(full['L1']['P_W'] - 1.5 ** 2 * 0.030) < 1e-9, full['L1']                     # from path_budget --json
    assert abs(full['U2']['P_W'] - (5.0 * (1 / 0.9 - 1) - 1.5 ** 2 * 0.030)) < 1e-9, full['U2']   # efficiency minus L1
    assert abs(full['R1']['P_W'] - 1.6 ** 2 * 0.05) < 1e-9, full['R1']
    assert 'output cable' not in full, 'an off-board path element must not heat the board'
    assert full['D1']['P_W'] is None and 'not in thermal.sources' in full['D1']['why'], full['D1']
    assert full['copper not_a_run']['P_W'] is None, full['copper not_a_run']
    cov = ' '.join(T['coverage']['warnings'])
    assert 'D1' in cov and 'UNKNOWN' in cov, cov
    # energy balance and h sensitivity
    b = {(r['corner'], r['h']): r for r in T['board']}
    for k, r in b.items():
        assert abs(r['avg_solver'] - r['avg_analytic']) / r['avg_analytic'] < 0.005, r
    assert b[('full', 'low')]['peak']['rise'] > b[('full', 'nominal')]['peak']['rise'] > b[('full', 'high')]['peak']['rise']
    u1 = [p for p in T['parts'] if p['ref'] == 'U1' and p['corner'] == 'full'][0]
    assert u1['T']['nominal']['board_rise'] > b[('full', 'nominal')]['avg_solver'] * 1.5, u1     # heat trapped at U1
    assert u1['T']['nominal']['Tj'] > u1['T']['nominal']['T_board'], u1
    # exposed pads
    ep = {(e['ref'], e['pad']): e for e in T['exposed_pads']}
    assert 'no copper on any other layer' in ep[('U1', '4')]['flag'], ep[('U1', '4')]
    u2 = ep[('U2', '9')]
    assert u2['vias_in_pad'] == 4 and u2['recommended'] == 9 and '4 via(s)' in u2['flag'], u2
    # judged on the solved step (vias beside the pad count; via-in-pad is a decision), not on the rule-of-thumb count
    assert u2['step_K'] >= 3 and 'solved' in u2['flag'] and 'beside the pad' in u2['flag'] and 'by decision' in u2['flag'], u2
    # a part with a thermal pad takes its loss there, not spread over every pin
    assert any(w.startswith('U2: heat placed on its thermal pad 9') for w in T['coverage']['warnings']), T['coverage']['warnings']
    # the pour under U1 reaches B.Cu only through FR4
    pu = [p for p in T['pours'] if p['ref'] == 'U1' and p['net'] == '+5V'][0]
    assert pu['vias'] == 0 and 'FR4' in pu['flag'] and pu['dT_K'] > 10, pu
    # Q1 sits on a ground island with one via: a heat finding, not only an EMC one
    weak = [w for w in T['stitching']['weak'] if 'Q1' in w['parts']]
    assert weak and weak[0]['heat'], T['stitching']['weak']
    assert T['what_if'] and T['what_if']['added'] > 0, T['what_if']
    md = open(os.path.join(d, 'thermal.md')).read()
    assert md.index('Coverage and warnings') < md.index('Heat sources per corner') < md.index('Board temperature')
    assert '**UNKNOWN**' in md and 'heat: a part at or above' in md
    assert os.path.exists(os.path.join(d, 'maps', 'thermal_full.png'))


def test_no_thermal_config_is_loud():
    d = tempfile.mkdtemp()
    build(d)
    cfg = json.load(open(os.path.join(d, 'review_config.json'))); cfg.pop('thermal')
    json.dump(cfg, open(os.path.join(d, 'review_config.json'), 'w'))
    run(d, 'planes.py', 'thermal.py')
    T = json.load(open(os.path.join(d, 'thermal.json')))
    cov = ' '.join(T['coverage']['warnings'])
    assert 'no "thermal" section' in cov, cov
    names = {r['name'] for r in T['heat']['default']['rows'] if r['P_W'] is None}
    assert {'U1', 'U2', 'L1', 'Q1', 'D1', 'R1'} <= names, names                          # every candidate listed as UNKNOWN
    assert any(e['ref'] == 'U2' and e['vias_in_pad'] == 4 for e in T['exposed_pads'])     # vias still measured


if __name__ == '__main__':
    if not os.path.exists(PY):
        print('SKIP: no analysis python at', PY); sys.exit(0)
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:4000])
    sys.exit(1 if fails else 0)
