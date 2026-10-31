"""islands.py, decoupling.py, the diff-pair geometry in emc.py and the configuration coverage warnings, on a synthetic
4-layer pack (needs the analysis venv):   python3 tests/test_pack_checks.py
The decoupling tests take their copper connectivity from KiCad: the synthetic board is written as a .kicad_pcb, filled
and checked by kicad-cli DRC and dumped by boarddump.py (through_kicad; skipped without KiCad).
- a declared single-point ground island merged into the main pour is a FAIL naming the other pads it now holds; kept
  apart with one allowed via it is ok; with none declared the coverage says the check did not run;
- each IC supply pin gets its nearest capacitor by copper path, with an inductance estimate from microstrip per-length
  inductance (not the free-wire 1 nH/mm); a cap 18 mm of track away is flagged;
- the path joins a via dropped mid-way on a track and a pad a track runs straight across (no vertex there), as KiCad does;
- copper joins where the shapes overlap (KiCad 10: centre distance under the sum of half-widths) for a via beside a
  track, a wide track ending beside a thin one and a track ending short of a pad; a blind via joins only the layers it
  spans;
- two same-net tracks crossing mid-span (no vertex there) join, and two parallel ones join just inside the
  sum of their half-widths and not just outside; crossing tracks on different layers do not;
- a pad on a pour by thermal-relief spokes only (centre outside the fill), a track crossing a pour with no vertex in it,
  two pads whose copper overlaps with neither centre in the other and a track touching an arc beyond its chords all
  join, as KiCad joins them; a pin with no copper to its capacitor is a FAIL, and the unconnected count of the links
  is KiCad's and DRC's;
- with no connectivity in board.json (an older dump) decoupling says NOT CHECKED; a blind via without its span is a
  warning, and common.copper() puts a blind via only on the layers it spans;
- a differential pair with the ground pour 0.15 mm from it is flagged as partly coplanar;
- a net_classes pattern that matches nothing, and a connector net that falls through to "slow", are warnings."""
import json, math, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.environ.get('PY') or os.path.expanduser('~/.cache/kicad-skills/venv/bin/python')
KICAD_PYTHON = next((c for c in (os.environ.get('KICAD_PYTHON', ''),
                                 '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3')
                     if c and os.path.exists(c)), None)
KICAD_CLI = next((c for c in (os.environ.get('KICAD_CLI', ''), '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli',
                              shutil.which('kicad-cli') or '') if c and os.path.exists(c)), None)
try:                                    # under pytest a missing KiCad is a SKIP, not a silent PASS
    import pytest
    Skip = pytest.skip.Exception
except ImportError:
    class Skip(Exception):
        pass


def rect(x0, y0, x1, y1): return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def pad(num, net, x, y, w=0.6, h=0.6, layer='F.Cu', rot=0):
    return dict(num=num, net=net, x=x, y=y, layers=[layer], th=False, drill=0, rot=rot,
                poly=[[rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2), []]])


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


def through_kicad(d):
    """the synthetic pack's board made real: written as a .kicad_pcb (kicad_sexpr), its zones filled and the board
    checked by kicad-cli DRC (PACK/drc.json), then dumped back over board.json by boarddump.py, so the copper and its
    connectivity are KiCad's own. Pads are rectangles (their poly's extent, turned by "rot"); a zone takes its outline
    and "connect" (None: thermal reliefs, KiCad's default; else solid) - KiCad fills it."""
    if not (KICAD_PYTHON and KICAD_CLI):
        raise Skip('no KiCad (KICAD_PYTHON / KICAD_CLI)')
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'kicad-pcb-workflow', 'scripts'))
    from kicad_sexpr import Board, loads, stackup
    S = json.load(open(os.path.join(d, 'board.json')))
    b = Board.new(4)
    b.set_stackup(stackup([0.035, 0.0175, 0.0175, 0.035], [('prepreg', 0.2, '7628', 4.4, 0.02), ('core', 1.065, 'FR4', 4.4, 0.02),
                                                         ('prepreg', 0.2, '7628', 4.4, 0.02)]))
    x0, y0, x1, y1 = S['edge_bbox']
    b.outline_rect(x0, y0, x1 - x0, y1 - y0)
    for f in S['footprints']:
        pads = []
        for p in f['pads']:
            xs, ys = [q[0] for q in p['poly'][0][0]], [q[1] for q in p['poly'][0][0]]
            pads.append('(pad "%s" smd rect (at %g %g %g) (size %g %g) (layers "%s"))' % (
                p['num'], p['x'] - f['x'], p['y'] - f['y'], p.get('rot', 0), max(xs) - min(xs), max(ys) - min(ys), p['layers'][0]))
        b.add_footprint(loads('(footprint "T:%s" (layer "F.Cu") (attr smd) %s)' % (f['fp'], ' '.join(pads))), 'T:' + f['fp'],
                        f['ref'], f['value'], (f['x'], f['y']), pad_nets={p['num']: p['net'] for p in f['pads']})
    for t in S['tracks']:
        if t.get('arc'): b.arc(t['a'], t['m'], t['b'], t['w'], t['layer'], t['net'])
        else: b.segment(t['a'], t['b'], t['w'], t['layer'], t['net'])
    for v in S['vias']:
        b.via((v['x'], v['y']), v['size'], v['drill'], v['net'], layers=tuple(v.get('layers') or ('F.Cu', 'B.Cu')),
              via_type={'blind': 'blind', 'microvia': 'micro'}.get(v.get('type_name')))
    for z in S['zones']:
        b.zone(z['net'], z['layers'], z['outline'][0][0], connect_pads=z.get('connect', 'yes'), clearance=z.get('clearance', 0.2))
    pcb = os.path.join(d, 'board.kicad_pcb')
    b.save(pcb)
    subprocess.run([KICAD_CLI, 'pcb', 'drc', '--refill-zones', '--save-board', '--format', 'json', '-o',
                    os.path.join(d, 'drc.json'), pcb], capture_output=True)
    assert os.path.exists(os.path.join(d, 'drc.json')), 'kicad-cli DRC wrote no report'
    r = subprocess.run([KICAD_PYTHON, os.path.join(HERE, 'boarddump.py'), pcb, d], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.load(open(os.path.join(d, 'board.json')))


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
    d = tempfile.mkdtemp(); build(d); through_kicad(d)
    run(d, 'decoupling.py')
    rows = {(r['ic'], r['pin']): r for r in json.load(open(os.path.join(d, 'decoupling.json')))['pins']}
    a, b = rows[('U1', '1')], rows[('U1', '8')]
    assert a['cap'] == 'C1' and abs(a['track_mm'] - 2.0) < 0.05 and a['status'] == 'ok', a
    assert b['cap'] == 'C3' and abs(b['track_mm'] - 22.0) < 0.05 and b['status'].startswith('FLAG'), b
    # 0.3 mm over 0.2 mm of prepreg: about 0.3 nH/mm, nowhere near the free-wire 1 nH/mm
    assert 0.15 * b['track_mm'] < b['est_nH'] < 0.5 * b['track_mm'], b
    assert ('U1', '2') not in rows, 'ground pins are not supply pins'


def test_decoupling_joins_mid_segment_vias_and_pads():
    """KiCad joins a via dropped on a straight run, and a pad a track runs across, with no vertex on the track there
    (skill-issues #5: a false "no capacitor reachable"). VBUS: U2.1 -> via (10, 6) -> In2.Cu track (8, 6)-(22, 6), with
    both vias mid-way along it -> via (20, 6) -> C2. VDD: U2.3 -> a track ending on another (T-join) that runs straight
    across C3.1 and on past it."""
    d = tempfile.mkdtemp()
    fps = [dict(ref='U2', value='LDO', fp='SOT', lib='', x=10, y=10, rot=0, side='F',
                pads=[pad('1', 'VBUS', 10, 10), pad('2', 'GND', 10, 11), pad('3', 'VDD', 30, 10)]),
           dict(ref='C2', value='1uF', fp='C_0402', lib='', x=20, y=10.5, rot=0, side='F', pads=[pad('1', 'VBUS', 20, 10), pad('2', 'GND', 20, 11)]),
           dict(ref='C3', value='1uF', fp='C_0402', lib='', x=36, y=14.5, rot=0, side='F', pads=[pad('1', 'VDD', 36, 14), pad('2', 'GND', 36, 15)])]
    tracks = [dict(a=[10, 10], b=[10, 6], w=0.3, layer='F.Cu', net='VBUS'),
              dict(a=[8, 6], b=[22, 6], w=0.3, layer='In2.Cu', net='VBUS'),       # no vertex at either via
              dict(a=[20, 6], b=[20, 10], w=0.3, layer='F.Cu', net='VBUS'),
              dict(a=[30, 10], b=[30, 14], w=0.3, layer='F.Cu', net='VDD'),        # ends mid-way on the next one
              dict(a=[26, 14], b=[40, 14], w=0.3, layer='F.Cu', net='VDD')]        # straight across C3.1
    vias = [dict(x=10, y=6, net='VBUS', size=0.6, drill=0.3, type=4, type_name='through'),
            dict(x=20, y=6, net='VBUS', size=0.6, drill=0.3, type=4, type_name='through')]
    edge = rect(0, 0, 45, 20)
    board = dict(source='synthetic', layers=['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'], stackup=STACK, netclass={}, vias=vias,
                 edge=[[edge, []]], edge_bbox=[0, 0, 45, 20], footprints=fps, tracks=tracks, zones=[])
    comps, nets = {}, {}
    for f in fps:
        comps[f['ref']] = dict(ref=f['ref'], value=f['value'], fp=f['fp'], pins={})
        for p in f['pads']:
            pt = 'power_in' if f['ref'] == 'U2' else 'passive'
            comps[f['ref']]['pins'][p['num']] = [p['net'], '', pt]
            nets.setdefault(p['net'], []).append([f['ref'], p['num'], '', pt])
    cfg = dict(ground_nets=['GND'], decoupling=dict(max_mm=20))
    for n, v in (('board.json', board), ('netlist.json', dict(components=comps, nets=nets)), ('review_config.json', cfg)):
        json.dump(v, open(os.path.join(d, n), 'w'))
    through_kicad(d)
    out = run(d, 'decoupling.py')
    rows = {(r['ic'], r['pin']): r for r in json.load(open(os.path.join(d, 'decoupling.json')))['pins']}
    a, b = rows[('U2', '1')], rows[('U2', '3')]
    assert a['status'] == 'ok' and a['cap'] == 'C2' and abs(a['track_mm'] - 18.0) < 0.05 and a['via_hops'] > 0, a
    assert b['status'] == 'ok' and b['cap'] == 'C3' and abs(b['track_mm'] - 10.0) < 0.05, b
    assert 'no capacitor reachable' not in out, out


def test_decoupling_joins_where_copper_overlaps_and_vias_only_on_their_span():
    """KiCad joins copper whose shapes overlap - centre distance under the sum of the half-widths (KiCad 10
    BuildConnectivity, measured: a 0.6 mm via 0.449 mm off a 0.3 mm track joins, 0.45 does not; a 1.0 mm track ending
    0.649 mm from a 0.3 mm one joins, 0.65 does not; a 0.3 mm track ending 0.149 mm outside a pad joins, 0.15 does not)
    - and a blind via joins only the layers it spans. Each pair of nets is the same layout just inside / just outside
    the boundary; U1's pin reaches its capacitor only through that join."""
    d = tempfile.mkdtemp()
    u1, caps, tracks, vias = [], [], [], []

    def cap(ref, net, x, y, layer):
        caps.append(dict(ref=ref, value='1uF', fp='C_0402', lib='', x=x, y=y + 0.5, rot=0, side=layer[0],
                         pads=[pad('1', net, x, y, layer=layer), pad('2', 'GND', x, y + 1, layer=layer)]))

    def via(net, x, y, size=0.6, **kw):
        vias.append(dict(x=x, y=y, net=net, size=size, drill=0.3, type=4, type_name='through', **kw))
    for i, (net, off) in enumerate((('VA', 0.44), ('VAX', 0.46))):   # a 0.6 via beside a 0.3 track, on to B.Cu
        x = 25 * i
        u1.append(pad(str(1 + i), net, x + 5, 5))
        tracks += [dict(a=[x + 5, 5], b=[x + 15, 5], w=0.3, layer='F.Cu', net=net),
                   dict(a=[x + 10, 5 + off], b=[x + 10, 9], w=0.3, layer='B.Cu', net=net)]
        via(net, x + 10, 5 + off); cap('C%d' % (1 + i), net, x + 10, 9, 'B.Cu')
    for i, (net, off) in enumerate((('VT', 0.64), ('VTX', 0.66))):   # a 1.0 track ending beside a 0.3 one
        x = 25 * i
        u1.append(pad(str(3 + i), net, x + 5, 15))
        tracks += [dict(a=[x + 5, 15], b=[x + 15, 15], w=0.3, layer='F.Cu', net=net),
                   dict(a=[x + 10, 15 + off], b=[x + 10, 19], w=1.0, layer='F.Cu', net=net)]
        cap('C%d' % (3 + i), net, x + 10, 19, 'F.Cu')
    for i, (net, gap) in enumerate((('VP', 0.10), ('VPX', 0.16))):   # a 0.3 track ending short of a 0.6 pad
        x = 25 * i
        u1.append(pad(str(5 + i), net, x + 5, 25))
        tracks.append(dict(a=[x + 5, 25], b=[x + 14.7 - gap, 25], w=0.3, layer='F.Cu', net=net))
        cap('C%d' % (5 + i), net, x + 15, 25, 'F.Cu')
    # a blind F.Cu-In1.Cu via the F.Cu track ends on: a B.Cu track under it does not join (VB), an In1.Cu one does (VBI)
    for i, (net, layer) in enumerate((('VB', 'B.Cu'), ('VBI', 'In1.Cu'))):
        x = 25 * i
        u1.append(pad(str(7 + i), net, x + 5, 35))
        tracks += [dict(a=[x + 5, 35], b=[x + 10, 35], w=0.3, layer='F.Cu', net=net),
                   dict(a=[x + 8, 35], b=[x + 15, 35], w=0.3, layer=layer, net=net)]
        vias.append(dict(x=x + 10, y=35, net=net, size=0.6, drill=0.3, type=1, type_name='blind', layers=['F.Cu', 'In1.Cu']))
        if layer == 'In1.Cu': via(net, x + 15, 35)
        cap('C%d' % (7 + i), net, x + 15, 35, 'B.Cu')
    fps = [dict(ref='U1', value='PMIC', fp='QFN', lib='', x=20, y=20, rot=0, side='F', pads=u1)] + caps
    edge = rect(0, 0, 45, 45)
    board = dict(source='synthetic', layers=['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'], stackup=STACK, netclass={}, vias=vias,
                 edge=[[edge, []]], edge_bbox=[0, 0, 45, 45], footprints=fps, tracks=tracks, zones=[])
    comps, nets = {}, {}
    for f in fps:
        comps[f['ref']] = dict(ref=f['ref'], value=f['value'], fp=f['fp'], pins={})
        for p in f['pads']:
            pt = 'power_in' if f['ref'] == 'U1' else 'passive'
            comps[f['ref']]['pins'][p['num']] = [p['net'], '', pt]
            nets.setdefault(p['net'], []).append([f['ref'], p['num'], '', pt])
    cfg = dict(ground_nets=['GND'], decoupling=dict(max_mm=20))
    for n, v in (('board.json', board), ('netlist.json', dict(components=comps, nets=nets)), ('review_config.json', cfg)):
        json.dump(v, open(os.path.join(d, n), 'w'))
    through_kicad(d)
    run(d, 'decoupling.py')
    D = json.load(open(os.path.join(d, 'decoupling.json')))
    rows = {r['net']: r for r in D['pins']}
    # via hops count layer pairs: a through via is 3, the blind F.Cu-In1.Cu via 1 plus 2 down the through via
    for net, mm, hops in (('VA', 9.0, 3), ('VT', 9.0, 0), ('VP', 10.0, 0), ('VBI', 10.0, 3)):
        r = rows[net]
        assert 'cap' in r and abs(r['track_mm'] - mm) < 0.05 and r['via_hops'] == hops, r   # (FLAG: no ground vias)
    for net in ('VAX', 'VTX', 'VPX', 'VB'):
        assert rows[net]['status'].startswith('FAIL: no capacitor reachable'), rows[net]
    c = D['coverage']['connectivity']
    assert c['unconnected_links'] == c['unconnected_kicad'] == c['unconnected_drc'] > 0, c


def test_decoupling_joins_tracks_whose_copper_overlaps_mid_span():
    """Two same-net tracks on one layer that cross mid-span - no shared vertex, neither ending on the other - are one
    piece of copper (KiCad 10 BuildConnectivity, measured: crossing 0.3 mm tracks join; two parallel 0.3 mm tracks
    0.29999 mm apart join, 0.3 mm apart do not). VX: U1.1's track crosses the one to C1 on F.Cu; VXB: the same with
    the cap track on B.Cu (no join). VL / VLX: a 0.3 mm track alongside U1's, 0.29 / 0.31 mm off it."""
    d = tempfile.mkdtemp()
    u1, caps, tracks = [], [], []

    def cap(ref, net, x, y, layer):
        caps.append(dict(ref=ref, value='1uF', fp='C_0402', lib='', x=x, y=y + 0.5, rot=0, side=layer[0],
                         pads=[pad('1', net, x, y, layer=layer), pad('2', 'GND', x, y + 1, layer=layer)]))
    for i, (net, layer) in enumerate((('VX', 'F.Cu'), ('VXB', 'B.Cu'))):     # crossing at (x + 10, 5)
        x = 25 * i
        u1.append(pad(str(1 + i), net, x + 5, 5))
        tracks += [dict(a=[x + 5, 5], b=[x + 15, 5], w=0.3, layer='F.Cu', net=net),
                   dict(a=[x + 10, 0.5], b=[x + 10, 10], w=0.3, layer=layer, net=net)]
        cap('C%d' % (1 + i), net, x + 10, 10, layer)
    for i, (net, gap) in enumerate((('VL', 0.29), ('VLX', 0.31))):            # parallel, overlapping by 0.01 mm or not
        x = 25 * i
        u1.append(pad(str(3 + i), net, x + 5, 15))
        tracks += [dict(a=[x + 5, 15], b=[x + 15, 15], w=0.3, layer='F.Cu', net=net),
                   dict(a=[x + 8, 15 + gap], b=[x + 12, 15 + gap], w=0.3, layer='F.Cu', net=net),
                   dict(a=[x + 12, 15 + gap], b=[x + 12, 19], w=0.3, layer='F.Cu', net=net)]
        cap('C%d' % (3 + i), net, x + 12, 19, 'F.Cu')
    fps = [dict(ref='U1', value='PMIC', fp='QFN', lib='', x=20, y=30, rot=0, side='F', pads=u1)] + caps
    edge = rect(0, 0, 45, 35)
    board = dict(source='synthetic', layers=['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'], stackup=STACK, netclass={}, vias=[],
                 edge=[[edge, []]], edge_bbox=[0, 0, 45, 35], footprints=fps, tracks=tracks, zones=[])
    comps, nets = {}, {}
    for f in fps:
        comps[f['ref']] = dict(ref=f['ref'], value=f['value'], fp=f['fp'], pins={})
        for p in f['pads']:
            pt = 'power_in' if f['ref'] == 'U1' else 'passive'
            comps[f['ref']]['pins'][p['num']] = [p['net'], '', pt]
            nets.setdefault(p['net'], []).append([f['ref'], p['num'], '', pt])
    cfg = dict(ground_nets=['GND'], decoupling=dict(max_mm=20))
    for n, v in (('board.json', board), ('netlist.json', dict(components=comps, nets=nets)), ('review_config.json', cfg)):
        json.dump(v, open(os.path.join(d, n), 'w'))
    through_kicad(d)
    run(d, 'decoupling.py')
    rows = {r['net']: r for r in json.load(open(os.path.join(d, 'decoupling.json')))['pins']}
    for net, mm in (('VX', 10.0), ('VL', 11.0)):
        r = rows[net]
        assert 'cap' in r and abs(r['track_mm'] - mm) < 0.05 and r['via_hops'] == 0, r
    for net in ('VXB', 'VLX'):
        assert rows[net]['status'].startswith('FAIL: no capacitor reachable'), rows[net]


def test_decoupling_keeps_every_fill_piece_of_a_net():
    """A net poured as four separate F.Cu pieces, each holding one IC pin and its capacitor: every pin reaches its
    capacitor across its own piece. Pieces were keyed by id() of shapely's throwaway .geoms objects, so a piece could
    take the id of one freed two steps earlier and drop it (pico-stretch2's U6.8: "no capacitor reachable")."""
    d = tempfile.mkdtemp()
    u1, caps, zones = [], [], []
    for i in range(4):
        x = 10 * i
        u1.append(pad(str(1 + i), 'VZ', x + 5, 5))
        caps.append(dict(ref='C%d' % (1 + i), value='1uF', fp='C_0402', lib='', x=x + 8, y=5.5, rot=0, side='F',
                         pads=[pad('1', 'VZ', x + 8, 5), pad('2', 'GND', x + 8, 6.5)]))
        zones.append(zone('VZ', 'F.Cu', rect(x + 4, 4, x + 9, 6)))
    u1.append(pad('9', 'GND', 20, 15))
    fps = [dict(ref='U1', value='MCU', fp='QFN', lib='', x=20, y=10, rot=0, side='F', pads=u1)] + caps
    edge = rect(0, 0, 45, 20)
    board = dict(source='synthetic', layers=['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'], stackup=STACK, netclass={}, vias=[],
                 edge=[[edge, []]], edge_bbox=[0, 0, 45, 20], footprints=fps, tracks=[], zones=zones)
    comps, nets = {}, {}
    for f in fps:
        comps[f['ref']] = dict(ref=f['ref'], value=f['value'], fp=f['fp'], pins={})
        for p in f['pads']:
            pt = 'power_in' if f['ref'] == 'U1' else 'passive'
            comps[f['ref']]['pins'][p['num']] = [p['net'], '', pt]
            nets.setdefault(p['net'], []).append([f['ref'], p['num'], '', pt])
    cfg = dict(ground_nets=['GND'], decoupling=dict(max_mm=20))
    for n, v in (('board.json', board), ('netlist.json', dict(components=comps, nets=nets)), ('review_config.json', cfg)):
        json.dump(v, open(os.path.join(d, n), 'w'))
    through_kicad(d)
    run(d, 'decoupling.py')
    rows = {(r['ic'], r['pin']): r for r in json.load(open(os.path.join(d, 'decoupling.json')))['pins']}
    for i in range(4):
        r = rows[('U1', str(1 + i))]
        assert r.get('cap') == 'C%d' % (1 + i) and abs(r['plane_mm'] - 3.0) < 0.05, r


def _inside(pt, ring):
    """point in a ring (ray casting); KiCad saves fills fractured, holes cut into the one ring"""
    x, y = pt; n = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0): n = not n
    return n


def test_decoupling_joins_what_kicad_joins_beyond_the_old_geometry():
    """Each net here was a false "no capacitor reachable" on the geometric graph (PR #10's open gaps) and joins in KiCad.
    VTH: U1.1 and C1.1 each at an edge of a thermal-relief pour (KiCad's default), joined by a spoke, both centres
    outside the fill. VCR: U1.2's track crosses a pour with no vertex inside it; C2 sits on the pour. VOV: U1.3
    and C3.1 overlap at a corner, neither centre inside the other. VARC: C4's track ends on U1.4's arc where the arc
    bulges 1.46 mm beyond its chords; the path is measured along the arc. VNC: U1.5 and C5 with no copper between
    them, a FAIL. Unconnected, for the links, KiCad and DRC alike: VNC 2 (a floating VNC track counts), GND 4 (five
    unjoined ground pads); pours with no pad, track or via on them (VZ: one alone, two
    overlapping) are not counted."""
    d = tempfile.mkdtemp()
    u1 = [pad('1', 'VTH', 1.8, 7, 1, 1), pad('2', 'VCR', 16, 6), pad('3', 'VOV', 40, 6, 1, 1), pad('4', 'VARC', 50, 20),
          pad('5', 'VNC', 70, 5)]
    fps = [dict(ref='U1', value='PMIC', fp='QFN', lib='', x=40, y=25, rot=0, side='F', pads=u1)]
    for ref, net, x, y, w in (('C1', 'VTH', 9, 12.2, 1), ('C2', 'VCR', 25, 9, 0.6), ('C3', 'VOV', 40.8, 6.8, 1),
                              ('C4', 'VARC', 49, 14, 0.6), ('C5', 'VNC', 75, 5, 0.6)):
        fps.append(dict(ref=ref, value='1uF', fp='C', lib='', x=x, y=y + 0.75, rot=0, side='F',
                        pads=[pad('1', net, x, y, w, w), pad('2', 'GND', x, y + 1.5)]))
    q = 5 - 5 * 0.5 ** 0.5                                   # the arc's point at 135 degrees about its centre (55, 20)
    tracks = [dict(a=[16, 6], b=[34, 6], w=0.3, layer='F.Cu', net='VCR'),
              dict(a=[50, 20], m=[55, 15], b=[60, 20], w=0.3, layer='F.Cu', net='VARC', arc=True),
              dict(a=[50 + q, 15 + q], b=[49, 14], w=0.3, layer='F.Cu', net='VARC'),
              dict(a=[65, 12], b=[75, 12], w=0.3, layer='F.Cu', net='VNC')]
    zones = [dict(zone('VTH', 'F.Cu', rect(2, 2, 12, 12)), connect=None), zone('VCR', 'F.Cu', rect(20, 2, 30, 10)),
             zone('VZ', 'F.Cu', rect(65, 20, 75, 28)), zone('VZ', 'F.Cu', rect(55, 22, 62, 28)),
             zone('VZ', 'F.Cu', rect(60, 23, 64, 27))]
    board = dict(source='synthetic', layers=['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'], stackup=STACK, netclass={}, vias=[],
                 edge=[[rect(0, 0, 80, 30), []]], edge_bbox=[0, 0, 80, 30], footprints=fps, tracks=tracks, zones=zones)
    comps, nets = {}, {}
    for f in fps:
        comps[f['ref']] = dict(ref=f['ref'], value=f['value'], fp=f['fp'], pins={})
        for p in f['pads']:
            pt = 'power_in' if f['ref'] == 'U1' else 'passive'
            comps[f['ref']]['pins'][p['num']] = [p['net'], '', pt]
            nets.setdefault(p['net'], []).append([f['ref'], p['num'], '', pt])
    cfg = dict(ground_nets=['GND'], decoupling=dict(max_mm=20))
    for n, v in (('board.json', board), ('netlist.json', dict(components=comps, nets=nets)), ('review_config.json', cfg)):
        json.dump(v, open(os.path.join(d, n), 'w'))
    B = through_kicad(d)
    fill = [ring for z in B['zones'] if z['net'] == 'VTH' for ring, _ in z['filled']['F.Cu']]
    assert fill and not any(_inside(c, r) for c in ((1.8, 7), (9, 12.2)) for r in fill), 'a pad centre inside the VTH fill'
    run(d, 'decoupling.py')
    D = json.load(open(os.path.join(d, 'decoupling.json')))
    rows = {r['net']: r for r in D['pins']}
    th, cr, ov, ar = rows['VTH'], rows['VCR'], rows['VOV'], rows['VARC']
    assert th.get('cap') == 'C1' and th['track_mm'] == 0 and abs(th['plane_mm'] - math.dist((1.8, 7), (9, 12.2))) < 0.05, th
    assert cr.get('cap') == 'C2' and abs(cr['track_mm'] - 4.0) < 0.2 and abs(cr['path_mm'] - (4 + 34 ** 0.5)) < 0.2, cr
    assert ov.get('cap') == 'C3' and abs(ov['track_mm'] - 0.8 * 2 ** 0.5) < 0.01 and ov['plane_mm'] == 0, ov
    assert ar.get('cap') == 'C4' and abs(ar['track_mm'] - (5 * math.pi / 4 + math.dist((50 + q, 15 + q), (49, 14)))) < 0.01, ar
    assert rows['VNC']['status'].startswith('FAIL: no capacitor reachable'), rows['VNC']
    c = D['coverage']['connectivity']
    assert c['unconnected_links'] == c['unconnected_kicad'] == c['unconnected_drc'] == 6, c
    # a link between two nets (a hand-edited board.json) is ignored with a warning, not followed or a crash
    B['connectivity']['links'].append(['p0.0', 'p1.1'])                  # U1.1 (VTH) to C1.2 (GND)
    json.dump(B, open(os.path.join(d, 'board.json'), 'w'))
    run(d, 'decoupling.py')
    D = json.load(open(os.path.join(d, 'decoupling.json')))
    assert any('1 connectivity links name items not in board.json or on two nets' in w for w in D['coverage']['warnings'])
    assert {r['net']: r for r in D['pins']}['VTH'].get('cap') == 'C1'
    # pour_check.py dumps without the connectivity it does not use
    r = subprocess.run([KICAD_PYTHON, os.path.join(HERE, 'boarddump.py'), os.path.join(d, 'board.kicad_pcb'),
                        os.path.join(d, 'nc'), '--no-connectivity'], capture_output=True, text=True)
    assert 'connectivity' not in json.load(open(os.path.join(d, 'nc', 'board.json'))), r.stderr[-1500:]


def test_decoupling_without_connectivity_and_via_spans():
    """a board.json from an older boarddump.py (no "connectivity", a micro via without its span): decoupling says NOT
    CHECKED and why, and the spanless via is a warning. A via joins only the layers it spans: common.copper() puts a
    blind via only on them, an In1.Cu-B.Cu via under the F.Cu ground island is not one of its joins (islands.py), and
    an In1.Cu-In2.Cu via under the isolated F.Cu ground strip does not tie it to the plane (pour_check.py)"""
    d = tempfile.mkdtemp(); build(d)
    B = json.load(open(os.path.join(d, 'board.json')))
    B['vias'] += [dict(x=40, y=29, net='GND', size=0.4, drill=0.2, type=2, type_name='microvia'),
                  dict(x=30, y=29, net='VBL', size=0.6, drill=0.3, type=1, type_name='blind', layers=['F.Cu', 'In1.Cu']),
                  dict(x=8.55, y=11.2, net='GND', size=0.3, drill=0.15, type=1, type_name='blind', layers=['In1.Cu', 'B.Cu']),
                  dict(x=20, y=26.5, net='GND', size=0.3, drill=0.15, type=1, type_name='buried', layers=['In1.Cu', 'In2.Cu'])]
    json.dump(B, open(os.path.join(d, 'board.json'), 'w'))
    run(d, 'decoupling.py', 'islands.py')
    r = json.load(open(os.path.join(d, 'islands.json')))['islands'][0]
    assert r['status'].startswith('ok') and len(r['joins']) == 1, r
    r = subprocess.run([PY, os.path.join(HERE, 'pour_check.py'), d], capture_output=True, text=True)
    assert any(l.startswith('ISOLATED GND') and '25.3' in l for l in r.stdout.splitlines()), r.stdout
    assert '1 blind/buried/micro vias with no layer span' in r.stdout, r.stdout
    D = json.load(open(os.path.join(d, 'decoupling.json')))
    assert D['pins'] and all(r['status'] == 'NOT CHECKED: board.json has no connectivity' for r in D['pins']), D['pins']
    w = D['coverage']['warnings']
    assert any('no "connectivity"' in x for x in w) and any('1 blind/buried/micro vias with no layer span' in x for x in w), w
    code = ('import sys; sys.path.insert(0, sys.argv[1]); sys.argv = sys.argv[1:]; from common import *; '
            'print(" ".join(L for L in LAYERS if not copper("VBL", L).is_empty)); '
            'a = dict(a=[0, 0], m=[5, -5], b=[10, 0], w=0.2, layer="F.Cu", net="X", arc=True); '
            'print(round(seg_len(a), 3), track_geom(a).contains(Point(5 - 5 * 0.5 ** 0.5, -5 * 0.5 ** 0.5)))')
    r = subprocess.run([PY, '-c', code, HERE, d], capture_output=True, text=True)
    out = r.stdout.splitlines()
    assert out[0].split() == ['F.Cu', 'In1.Cu'], r.stdout + r.stderr[-1500:]
    n, bulge = out[1].split()                                   # an arc is its arc, not its two chords (14.14 mm)
    assert abs(float(n) - 5 * math.pi) < 0.005 and bulge == 'True', out


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
    assert any('through one via (0.45/0.2 mm) at [7.6, 11.6]' in f for f in h['electrical_flags']), h   # where, not only how much
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
            except Skip as e:
                print('SKIP', k, e)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:3000])
    sys.exit(1 if fails else 0)
