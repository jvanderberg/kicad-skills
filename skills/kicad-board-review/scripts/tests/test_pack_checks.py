"""islands.py, decoupling.py, the diff-pair geometry in emc.py and the configuration coverage warnings, on a synthetic
4-layer pack (no KiCad; needs the analysis venv):   python3 tests/test_pack_checks.py
- a declared single-point ground island merged into the main pour is a FAIL naming the other pads it now holds; kept
  apart with one allowed via it is ok; with none declared the coverage says the check did not run;
- each IC supply pin gets its nearest capacitor by copper path, with an inductance estimate from microstrip per-length
  inductance (not the free-wire 1 nH/mm); a cap 18 mm of track away is flagged;
- a differential pair with the ground pour 0.15 mm from it is flagged as partly coplanar;
- a net_classes pattern that matches nothing, and a connector net that falls through to "slow", are warnings."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.environ.get('PY') or os.path.expanduser('~/.cache/kicad-skills/venv/bin/python')


def rect(x0, y0, x1, y1): return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def pad(num, net, x, y, w=0.6, h=0.6, layer='F.Cu'):
    return dict(num=num, net=net, x=x, y=y, layers=[layer], th=False, drill=0, poly=[[rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2), []]])


def zone(net, layer, ring, holes=()):
    return dict(net=net, name='', prio=0, keepout=False, layers=[layer], outline=[[ring, []]], min_w=0.2, clearance=0.2,
                filled={layer: [[ring, list(holes)]]})


STACK = [dict(name='F.Cu', type='copper', thickness_mm=0.035, er=None), dict(name='dielectric 1', type='prepreg', thickness_mm=0.2, er=4.4),
         dict(name='In1.Cu', type='copper', thickness_mm=0.0175, er=None), dict(name='dielectric 2', type='core', thickness_mm=1.065, er=4.4),
         dict(name='In2.Cu', type='copper', thickness_mm=0.0175, er=None), dict(name='dielectric 3', type='prepreg', thickness_mm=0.2, er=4.4),
         dict(name='B.Cu', type='copper', thickness_mm=0.035, er=None)]


def build(d, merged=False, islands=True, diff_pairs=None, en_net='EN', split_gnd=False, hot_loop=False):
    u1 = [pad('1', 'VDD', 10, 10), pad('2', 'GND', 10, 11), pad('3', 'USB_DP', 10, 12), pad('4', 'USB_DN', 10, 13),
          pad('5', en_net, 10, 14), pad('6', 'GND', 12, 14), pad('7', 'GND', 12, 13), pad('8', 'VCORE', 12, 10)]
    fps = [dict(ref='U1', value='MCU', fp='QFN', lib='', x=11, y=12, rot=0, side='F', pads=u1),
           dict(ref='C1', value='100nF', fp='C_0402', lib='', x=8, y=10.5, rot=0, side='F', pads=[pad('1', 'VDD', 8, 10), pad('2', 'GND', 8, 11)]),
           dict(ref='C3', value='1uF', fp='C_0402', lib='', x=30, y=10.5, rot=0, side='F', pads=[pad('1', 'VCORE', 30, 10), pad('2', 'GND', 30, 11)]),
           dict(ref='J1', value='CONN', fp='Conn', lib='', x=2, y=20, rot=0, side='F', pads=[pad('1', 'EXT_SIG', 2, 20), pad('2', 'GND', 2, 21)])]
    tracks = [dict(a=[10, 10], b=[8, 10], w=0.3, layer='F.Cu', net='VDD'),                      # 2 mm to C1
              dict(a=[12, 10], b=[12, 8], w=0.3, layer='F.Cu', net='VCORE'),                    # 2 + 18 + 2 mm to C3
              dict(a=[12, 8], b=[30, 8], w=0.3, layer='F.Cu', net='VCORE'),
              dict(a=[30, 8], b=[30, 10], w=0.3, layer='F.Cu', net='VCORE'),
              dict(a=[5, 25.0], b=[35, 25.0], w=0.3, layer='F.Cu', net='USB_DP'),               # pair: 0.15 gap
              dict(a=[5, 24.55], b=[35, 24.55], w=0.3, layer='F.Cu', net='USB_DN'),
              dict(a=[2, 20], b=[20, 20], w=0.2, layer='F.Cu', net='EXT_SIG')]
    edge = rect(0, 0, 40, 30)
    isl = rect(7.4, 10.6, 10.4, 11.4)                                    # U1.2 + C1.2 power-ground island on F.Cu
    main = rect(14, 10.6, 38, 12) if not merged else rect(7.4, 10.6, 38, 12)     # main F.Cu ground pour (holds C3.2)
    zones = [zone('GND', 'F.Cu', isl), zone('GND', 'F.Cu', main), zone('GND', 'In1.Cu', edge), zone('GND', 'F.Cu', rect(2, 25.30, 38, 28))]
    vias = [dict(x=9.0, y=11.0, net='GND', size=0.45, drill=0.2, type=4, type_name='through'),       # the island's one join
            dict(x=20.0, y=11.3, net='GND', size=0.45, drill=0.2, type=4, type_name='through'),
            dict(x=8.0, y=12.8, net='GND', size=0.45, drill=0.2, type=4, type_name='through')]
    if split_gnd:      # U1.2 and C1.2 each on their own F.Cu scrap, joined only through In1 (a strap under the IC split them)
        zones[0] = zone('GND', 'F.Cu', rect(7.2, 10.6, 8.4, 11.9))
        zones.append(zone('GND', 'F.Cu', rect(9.6, 10.6, 10.9, 11.45)))
        vias[0] = dict(x=7.6, y=11.6, net='GND', size=0.45, drill=0.2, type=4, type_name='through')
        vias.append(dict(x=10.6, y=11.2, net='GND', size=0.45, drill=0.2, type=4, type_name='through'))
    board = dict(source='synthetic', layers=['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'], stackup=STACK, netclass={}, vias=vias, edge=[[edge, []]],
                 edge_bbox=[0, 0, 40, 30], footprints=fps, tracks=tracks, zones=zones)
    pt = {('U1', '1'): 'power_in', ('U1', '8'): 'power_in', ('U1', '2'): 'power_in', ('U1', '6'): 'power_in', ('U1', '7'): 'power_in',
          ('U1', '5'): 'input'}
    fn = {('U1', '1'): 'VDD', ('U1', '8'): 'VCORE', ('U1', '2'): 'GND', ('U1', '6'): 'GND', ('U1', '7'): 'GND', ('U1', '5'): 'EN'}
    comps, nets = {}, {}
    for f in fps:
        comps[f['ref']] = dict(ref=f['ref'], value=f['value'], fp=f['fp'], pins={})
        for p in f['pads']:
            k = (f['ref'], p['num'])
            comps[f['ref']]['pins'][p['num']] = [p['net'], fn.get(k, ''), pt.get(k, 'passive')]
            nets.setdefault(p['net'], []).append([f['ref'], p['num'], fn.get(k, ''), pt.get(k, 'passive')])
    cfg = dict(ground_nets=['GND'], net_classes=[{'match': '^USB_', 'class': 'usb'}, {'match': '^NOPE_', 'class': 'spi'}],
               fast_classes=['usb'], diff_pairs=diff_pairs or [{'nets': ['USB_DP', 'USB_DN'], 'target_ohm': 90}])
    if hot_loop:
        cfg['hot_loops'] = [dict(ic='U1', in_net='VDD', gnd_net='GND', label='U1 input loop')]
    if islands:
        cfg['islands'] = [dict(name='power ground', net='GND', layer='F.Cu', pads=['U1:2', 'C1:2'], allowed_vias=1)]
    for n, v in (('board.json', board), ('netlist.json', dict(components=comps, nets=nets)), ('review_config.json', cfg)):
        json.dump(v, open(os.path.join(d, n), 'w'))


def run(d, *scripts):
    out = ''
    for s in scripts:
        r = subprocess.run([PY, os.path.join(HERE, s), d], capture_output=True, text=True)
        assert r.returncode == 0, (s, r.stdout[-1500:], r.stderr[-2000:])
        out += r.stdout
    return out


def test_island_kept_apart_or_merged():
    d = tempfile.mkdtemp(); build(d)
    run(d, 'islands.py')
    r = json.load(open(os.path.join(d, 'islands.json')))['islands'][0]
    assert r['status'].startswith('ok') and len(r['joins']) == 1, r
    d = tempfile.mkdtemp(); build(d, merged=True)
    out = run(d, 'islands.py')
    r = json.load(open(os.path.join(d, 'islands.json')))['islands'][0]
    assert r['status'].startswith('FAIL') and 'merged' in r['status'] and 'C3.2' in r['other_pads'], r
    assert 'island power ground' in out
    d = tempfile.mkdtemp(); build(d, islands=False)
    out = run(d, 'islands.py')
    assert 'same-net isolation NOT CHECKED' in out, out


def test_decoupling_by_path_with_microstrip_inductance():
    d = tempfile.mkdtemp(); build(d)
    run(d, 'decoupling.py')
    rows = {(r['ic'], r['pin']): r for r in json.load(open(os.path.join(d, 'decoupling.json')))['pins']}
    a, b = rows[('U1', '1')], rows[('U1', '8')]
    assert a['cap'] == 'C1' and abs(a['track_mm'] - 2.0) < 0.05 and a['status'] == 'ok', a
    assert b['cap'] == 'C3' and abs(b['track_mm'] - 22.0) < 0.05 and b['status'].startswith('FLAG'), b
    # 0.3 mm over 0.2 mm of prepreg: about 0.3 nH/mm, nowhere near the free-wire 1 nH/mm
    assert 0.15 * b['track_mm'] < b['est_nH'] < 0.5 * b['track_mm'], b
    assert ('U1', '2') not in rows, 'ground pins are not supply pins'


def test_diff_pair_coplanar_and_coverage_warnings():
    d = tempfile.mkdtemp(); build(d)
    out = run(d, 'planes.py', 'islands.py', 'emc.py', 'decoupling.py', 'report.py')
    E = json.load(open(os.path.join(d, 'emc.json')))
    g = E['diff_pairs'][0]['geometry'][0]
    assert abs(g['gap_mm'] - 0.15) < 0.01 and abs(g['pour_gap_min_mm'] - 0.15) < 0.02 and 'coplanar' in g['flag'], g
    assert 60 < g['zdiff_ohm'] < 110, g
    w = E['coverage']['warnings']
    assert any('rule 2 "^NOPE_"' in x and 'matched 0 nets' in x for x in w), w
    assert any('reach a connector fell through to "slow"' in x and 'EXT_SIG' in x for x in w), w
    md = open(os.path.join(d, 'emc.md')).read()
    assert 'Same-net isolation' in md and 'Decoupling: nearest capacitor' in md and 'coplanar' in md, md[-3000:]


def test_diff_pair_entry_with_unknown_keys_is_a_config_error():
    """{"pair": [...]} instead of {"nets": [...]}: a message naming the accepted forms, not a TypeError"""
    d = tempfile.mkdtemp(); build(d, diff_pairs=[{'pair': ['USB_DP', 'USB_DN'], 'target_ohm': 90}])
    r = subprocess.run([PY, os.path.join(HERE, 'emc.py'), d], capture_output=True, text=True)
    assert r.returncode != 0 and 'Traceback' not in r.stderr, r.stderr[-2000:]
    assert 'diff_pairs entry 1' in r.stderr and '{"nets": ["NET_P", "NET_N"], "target_ohm": 90}' in r.stderr and 'pair' in r.stderr, r.stderr
    d = tempfile.mkdtemp(); build(d, diff_pairs=[['USB_DP', 'USB_DN']])                  # the short form still works
    run(d, 'emc.py')
    assert json.load(open(os.path.join(d, 'emc.json')))['diff_pairs'][0]['target_ohm'] is None


def test_hot_loop_return_through_vias_is_flagged():
    """the cap's ground pad and the IC's GND pin close together but joined only through In1: geometry passes, the
    solve shows the whole return leaving F.Cu, and the loop is FLAG, not ok; joined on F.Cu it stays ok"""
    d = tempfile.mkdtemp(); build(d, islands=False, hot_loop=True)
    run(d, 'emc.py')
    h = json.load(open(os.path.join(d, 'emc.json')))['coverage']['hot_loops'][0]
    assert h['status'] == 'ok' and h['gnd_return']['via_share'] < 0.2 and not h['electrical_flags'], h
    d = tempfile.mkdtemp(); build(d, islands=False, hot_loop=True, split_gnd=True)
    out = run(d, 'emc.py', 'report.py')
    h = json.load(open(os.path.join(d, 'emc.json')))['coverage']['hot_loops'][0]
    assert h['status'].startswith('FLAG') and h['gnd_return']['via_share'] > 0.9, h
    assert any('leaves F.Cu through vias' in f and 'C1 and U1.GND pin' in f for f in h['electrical_flags']), h
    assert 'leaves F.Cu through vias' in open(os.path.join(d, 'emc.md')).read()


def test_decoupling_skips_logic_inputs_strapped_to_a_rail():
    """EN typed input and tied to VDD is not a supply pin; VDD's own pins still are"""
    d = tempfile.mkdtemp(); build(d, en_net='VDD')
    run(d, 'decoupling.py')
    pins = {(r['ic'], r['pin']) for r in json.load(open(os.path.join(d, 'decoupling.json')))['pins']}
    assert ('U1', '1') in pins and ('U1', '5') not in pins, pins


def test_pour_check_weak_and_isolated_pieces():
    """the quick check after a zone edit: every pour piece needs 2 vias to its plane"""
    d = tempfile.mkdtemp(); build(d)
    r = subprocess.run([PY, os.path.join(HERE, 'pour_check.py'), d], capture_output=True, text=True)
    lines = r.stdout.splitlines()
    assert r.returncode == 1, r.stdout + r.stderr
    assert any(l.startswith('ISOLATED GND') and '25.3' in l for l in lines), r.stdout     # the strip beside the pair: no via
    assert sum(l.startswith('WEAK') for l in lines) == 2, r.stdout                        # island and main pour: one via each
    r = subprocess.run([PY, os.path.join(HERE, 'pour_check.py'), d, '--window', '0,24,40,30'], capture_output=True, text=True)
    assert '2 pour piece(s) checked in the window: 1 weak' in r.stdout and '(In1.Cu)' in r.stdout, r.stdout


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
