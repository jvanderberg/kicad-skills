"""planes.py / emc.py / report.py on a synthetic 4-layer pack (no KiCad needed; needs the analysis venv's shapely):
    python3 tests/test_pack_synthetic.py      (uses $PY or ~/.cache/kicad-skills/venv/bin/python)
Checks the reporting rules: an other-net pour inside a ground hole is reported as a pour, not as a board-sized slot;
each remaining slot has its own size; a span over nothing outranks a span over another net's plane, which outranks
one with ground pour on both sides; a missing hot-loop IC or an absent ground net is a warning, not a silent skip."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.environ.get('PY') or os.path.expanduser('~/.cache/kicad-skills/venv/bin/python')


def rect(x0, y0, x1, y1): return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def pad(num, net, x, y, w=0.6, h=0.6, layer='F.Cu'):
    return dict(num=num, net=net, x=x, y=y, layers=[layer], th=False, drill=0, poly=[[rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2), []]])


def zone(net, layer, ring, holes=()):
    return dict(net=net, name='', prio=0, keepout=False, layers=[layer], outline=[[ring, []]], min_w=0.2, clearance=0.2,
                filled={layer: [[ring, list(holes)]]})


def build(d, ground='GND'):
    edge = rect(0, 0, 60, 40)
    board = dict(source='synthetic', layers=['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'], stackup=[], netclass={}, vias=[], edge=[[edge, []]],
                 edge_bbox=[0, 0, 60, 40],
                 footprints=[dict(ref='C1', value='1uF', fp='C_0402', lib='', x=40, y=8, rot=0, side='F',
                                  pads=[pad('1', 'VSYS', 39.5, 8), pad('2', ground, 40.5, 8)])],
                 tracks=[dict(a=[30.3, 5.4], b=[49.7, 5.4], w=0.2, layer='B.Cu', net='SIG1'),
                         dict(a=[5, 30], b=[20, 30], w=0.2, layer='F.Cu', net='SIG2')],
                 zones=[zone(ground, 'In1.Cu', edge, [rect(4, 29, 21, 31)]),
                        zone('VSYS', 'In2.Cu', edge),
                        zone(ground, 'B.Cu', edge, [rect(10, 10, 25, 20), rect(30, 5, 50, 5.8)]),
                        zone('VBAT', 'B.Cu', rect(10.5, 10.5, 24.5, 19.5))])
    nl = dict(components={'C1': dict(ref='C1', value='1uF', fp='C_0402', pins={'1': ['VSYS', '', 'passive'], '2': [ground, '', 'passive']})},
              nets={'VSYS': [['C1', '1', '', 'passive']], ground: [['C1', '2', '', 'passive']], 'SIG1': [], 'SIG2': []})
    cfg = dict(ground_nets=['GND'], net_classes=[{'match': '^SIG', 'class': 'spi'}], fast_classes=['spi'],
               hot_loops=[dict(ic='U9', in_net='VSYS', gnd_net='GND', label='missing IC')])
    for n, v in (('board.json', board), ('netlist.json', nl), ('review_config.json', cfg)):
        json.dump(v, open(os.path.join(d, n), 'w'))


def run(d, *scripts):
    out = ''
    for s in scripts:
        r = subprocess.run([PY, os.path.join(HERE, s), d], capture_output=True, text=True)
        assert r.returncode == 0, (s, r.stderr[-2000:])
        out += r.stdout
    return out


def test_pours_slots_severity_and_warnings():
    d = tempfile.mkdtemp()
    build(d)
    out = run(d, 'planes.py', 'emc.py', 'report.py')
    P = json.load(open(os.path.join(d, 'planes.json')))
    pc = P['gnd']['B.Cu']['pieces'][0]
    assert [x['net'] for x in pc['other_net_pours']] == ['VBAT'], pc['other_net_pours']
    assert len(pc['holes']) == 1, pc['holes']                                # the VBAT pour's hole is not a slot
    h = pc['holes'][0]
    assert h['shape'] == 'slot' and abs(h['length_mm'] - 20) < 0.1 and abs(h['width_mm'] - 0.8) < 0.1, h
    E = json.load(open(os.path.join(d, 'emc.json')))
    sev = {r['net']: r['severity'] for r in E['reference']}
    assert sev == {'SIG1': 'low', 'SIG2': 'high'}, sev                        # coplanar ground lowers it; a void is high
    s1 = [r for r in E['reference'] if r['net'] == 'SIG1'][0]['spans'][0]
    assert s1['ref'] == 'VSYS' and s1['nearest_decap']['ref'] == 'C1', s1
    st = E['coverage']['hot_loops'][0]
    assert st['status'].startswith('NOT CHECKED'), st
    assert 'U9 is not on the board' in out
    md = open(os.path.join(d, 'emc.md')).read()
    assert md.index('Coverage and warnings') < md.index('Fast nets off'), 'coverage must come first'
    pm = open(os.path.join(d, 'power.md')).read()
    assert 'No DC runs in this pack' in pm and 'VBAT' in pm


def test_power_run_on_a_missing_net_is_reported_not_crashed():
    """a power run whose net was renamed after a part swap (KiCad: Net-(J3-Pad1) -> Net-(Q1-D)), or whose pads are
    gone, is listed as NOT RUN with the reason and the pads' current nets; the other runs still solve (R16)"""
    d = tempfile.mkdtemp()
    build(d)
    b = json.load(open(os.path.join(d, 'board.json')))
    b['footprints'].append(dict(ref='R1', value='0R', fp='R_0603', lib='', x=30, y=8, rot=0, side='F',
                                pads=[pad('1', 'VSYS', 30.5, 8), pad('2', 'GND', 29.5, 8)]))
    b['tracks'].append(dict(a=[30.5, 8], b=[39.5, 8], w=0.5, layer='F.Cu', net='VSYS'))
    json.dump(b, open(os.path.join(d, 'board.json'), 'w'))
    cfg = json.load(open(os.path.join(d, 'review_config.json')))
    cfg['power_runs'] = [dict(name='vsys_ok', net='VSYS', source=['C1:1'], sinks=[['R1:1', 1.0]]),
                         dict(name='renamed', net='Net-(J3-Pad1)', source=['C1:1'], sinks=[['R1:1', 1.0]]),
                         dict(name='gone', net='VSYS', source=['J9:1'], sinks=[['R1:7', 1.0]])]
    json.dump(cfg, open(os.path.join(d, 'review_config.json'), 'w'))
    out = run(d, 'power.py', 'planes.py', 'report.py')
    pr = json.load(open(os.path.join(d, 'power_runs.json')))
    assert [r['name'] for r in pr['runs']] == ['vsys_ok'], pr['runs']
    nr = {r['name']: r['reasons'] for r in pr['not_run']}
    assert set(nr) == {'renamed', 'gone'}, nr
    assert 'net Net-(J3-Pad1) is not on the board' in nr['renamed'][0] and 'C1:1 -> VSYS' in nr['renamed'][0], nr
    assert any('no part J9' in x for x in nr['gone']) and any('R1 has no pad 7' in x for x in nr['gone']), nr
    assert 'power run renamed NOT RUN' in out and '2 of 3 power runs NOT RUN' in out, out
    pm = open(os.path.join(d, 'power.md')).read()
    assert pm.index('power run renamed NOT RUN') < pm.index('## Runs'), 'not-run runs belong in the coverage, first'
    assert '| renamed |  | **NOT RUN** |' in pm, pm


def test_absent_ground_net_is_loud():
    d = tempfile.mkdtemp()
    build(d, ground='0V')                 # board ground is called 0V; the config still says GND
    out = run(d, 'planes.py')
    assert 'ground_nets' in out and 'not in the netlist' in out, out
    assert 'has copper on the board' in out, out


if __name__ == '__main__':
    if not os.path.exists(PY):
        print('SKIP: no analysis python at', PY); sys.exit(0)
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:3000])
    sys.exit(1 if fails else 0)
