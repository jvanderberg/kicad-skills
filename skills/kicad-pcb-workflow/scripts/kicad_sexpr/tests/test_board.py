"""Board builders, checked by KiCad (kicad-cli DRC with zone refill, re-save) and against pcbnew's own placement."""
import collections
import json
import os
import subprocess

from helpers import KICAD_PYTHON, Skip, drc, footprints_dir, resave, tmpdir
from kicad_sexpr import Board, Node, Project, Schematic, Sym, board_net_name, dumps, load, stackup

FP = footprints_dir


def _r0402():
    return os.path.join(FP(), 'Resistor_SMD.pretty', 'R_0402_1005Metric.kicad_mod')


def _build(d, clearance=None):
    b = Board.new(copper_layers=4)
    b.set_stackup(stackup([0.035, 0.0152, 0.0152, 0.035],
                          [('prepreg', 0.2104, '7628', 4.4, 0.02), ('core', 1.065, 'FR4', 4.6, 0.02),
                           ('prepreg', 0.2104, '7628', 4.4, 0.02)]))
    odd = board_net_name('Net-(R3-EN/UVLO)')
    r1 = b.add_footprint(_r0402(), 'Resistor_SMD:R_0402_1005Metric', 'R1', '10k', (110, 110), 270,
                         pad_nets={'1': 'A', '2': 'GND'}, fields={'LCSC': 'C25744'})
    r2 = b.add_footprint(_r0402(), 'Resistor_SMD:R_0402_1005Metric', 'R2', '10k', (120, 110), 30, side='B',
                         pad_nets={'1': 'A', '2': 'GND'})
    b.add_footprint(_r0402(), 'Resistor_SMD:R_0402_1005Metric', 'R3', '1k', (115, 104), 0,
                    pad_nets={'1': odd, '2': 'GND'})
    a1, a2 = r1.pad_position(1), r2.pad_position(1)
    b.track([a1, (a1[0], 107), (115, 107)], 0.25, 'F.Cu', 'A')
    b.via((115, 107), 0.6, 0.3, 'A')
    b.track([(115, 107), (a2[0], 107), a2], 0.25, 'B.Cu', 'A')
    b.arc((a1[0], 113.5), (a1[0] + 1, 114.5), (a1[0] + 2, 113.5), 0.25, 'In1.Cu', 'GND')
    outline = [(100, 100), (130, 100), (130, 120), (100, 120)]
    b.zone('GND', 'F.Cu', outline, priority=0, name='GND_F', connect_pads=None)
    b.zone('GND', ['In1.Cu', 'B.Cu'], outline, priority=1, name='GND_IN_B', connect_pads='yes')
    b.via((105, 115), 0.6, 0.3, 'GND', free=True)
    b.rule_area('F.Cu', [(101, 116), (104, 116), (104, 119), (101, 119)], name='NO_POUR')
    b.gr_text('TOP "1"', (105, 102), 'F.SilkS')
    b.gr_text('BOTTOM\nTWO LINES', (125, 117), 'B.SilkS')
    b.outline_rect(100, 100, 30, 20, corner_radius=1.0)
    p = os.path.join(d, 'b.kicad_pcb')
    b.save(p)
    pro = Project.new(os.path.join(d, 'b.kicad_pro'))
    if clearance is not None:
        pro.netclass('Default', clearance=clearance)
    pro.save()
    return b, p


def test_board_from_scratch_passes_drc_and_survives_resave():
    d = tmpdir('board')
    b, p = _build(d)
    r = drc(p)
    bad = {k: v for k, v in r['violations'].items()
           if k in ('clearance', 'shorting_items', 'tracks_crossing', 'track_dangling', 'via_dangling',
                    'copper_edge_clearance', 'invalid_outline', 'hole_clearance', 'malformed_courtyard',
                    'net_conflict', 'zones_intersect', 'starved_thermal')}
    assert not bad and r['unconnected'] == 0, r['violations']
    t = resave(p)
    k = load(p)
    for head in ('footprint', 'segment', 'arc', 'via', 'zone', 'gr_text', 'gr_line', 'gr_arc'):
        assert len(k.nodes(head)) == len(b.tree.nodes(head)), head
    assert '(net "Net-(R3-EN{slash}UVLO)")' in t
    assert any(z.find('keepout') is not None and z.get('name') == 'NO_POUR' for z in k.nodes('zone'))
    assert k.find('setup').find('stackup') is not None
    texts = {str(n[1]) for n in k.nodes('gr_text')}
    assert texts == {'TOP "1"', 'BOTTOM\nTWO LINES'}
    # and a load/save of KiCad's own output through the API is byte-identical
    b2 = Board.load(p)
    b2.save()
    assert open(p).read() == t


def test_netclass_clearance_from_project():
    """Two tracks 0.25 mm apart: DRC flags them with a 0.3 mm Default clearance and not with 0.2 mm, so the
    .kicad_pro written by Project is the one KiCad uses."""
    for clr, expect in ((0.3, True), (0.2, False)):
        d = tmpdir('clr')
        b = Board.new(2)
        b.outline_rect(0, 0, 20, 10)
        b.segment((2, 4), (18, 4), 0.25, 'F.Cu', 'N1')
        b.segment((2, 4.5), (18, 4.5), 0.25, 'F.Cu', 'N2')
        p = os.path.join(d, 'c.kicad_pcb')
        b.save(p)
        pro = Project.new(os.path.join(d, 'c.kicad_pro'))
        pro.netclass('Default', clearance=clr)
        pro.save()
        v = drc(p, refill=False)['violations']
        assert ('clearance' in v) == expect, (clr, v)


def test_read_modify_write_keeps_everything_else():
    d = tmpdir('rmw')
    _, p = _build(d)
    before = resave(p)
    b = Board.load(p)
    f = b.footprint('R3')
    f.set_pad_net(1, 'A2')
    f.set_field('Value', '2k2')
    b.segment((112, 104), (114, 104), 0.2, 'F.Cu', 'A2')
    b.save()
    after = open(p).read()
    import difflib
    changed = [ln for ln in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm='', n=0)
               if ln[:1] in '+-' and not ln.startswith(('+++', '---'))]
    assert len(changed) <= 12, changed                  # the 3 edits, nothing reformatted
    r = drc(p, refill=False)
    assert 'shorting_items' not in r['violations']


def test_validate_catches_duplicates_and_bad_layers():
    b = Board.new(2)
    b.add_footprint(_r0402(), 'Resistor_SMD:R_0402_1005Metric', 'R1', '1k', (10, 10))
    b.add_footprint(_r0402(), 'Resistor_SMD:R_0402_1005Metric', 'R1', '1k', (20, 10))
    b.segment((0, 0), (1, 0), 0.2, 'In1.Cu', 'X')
    probs = b.validate()
    assert any('duplicate footprint references' in x for x in probs)
    assert any('unknown layer In1.Cu' in x for x in probs)


def test_validate_follows_kicads_duplicate_rule_for_logos():
    """Two logos (G***, as bitmap2component and EasyEDA imports write them) and two board-only graphics sharing a
    reference are not duplicates: save() writes the board, and KiCad's parity check agrees for the board-only ones."""
    b = Board.new(2)
    for i, (ref, attr) in enumerate([('G***', ()), ('G***', ()), ('LOGO1', ('board_only', 'exclude_from_bom')),
                                     ('LOGO1', ('board_only', 'exclude_from_bom'))]):
        f = b.add_footprint(_r0402(), 'Resistor_SMD:R_0402_1005Metric', ref, 'x', (10 + 5 * i, 10))
        f.node.need('attr').extend(Sym(a) for a in attr)
        assert f.board_only == bool(attr)
    assert b.validate() == []
    d = tmpdir('logos')
    p = os.path.join(d, 'logos.kicad_pcb')
    b.save(p)
    Schematic.new('logos').save(os.path.join(d, 'logos.kicad_sch'))
    par = collections.Counter(v['type'] for v in drc(p, refill=False, parity=True)['raw'].get('schematic_parity', []))
    assert par['duplicate_footprints'] == 1 and par['extra_footprint'] == 2   # only the two plain G*** (DRC's job)
    for x in (40, 45):                                  # the same reference, not board-only: a duplicate
        b.add_footprint(_r0402(), 'Resistor_SMD:R_0402_1005Metric', 'LOGO2', 'x', (x, 10))
    assert any("duplicate footprint references: ['LOGO2']" in x for x in b.validate())


# -------------------------------------------------------------------- placement vs pcbnew

SPECS = [
    ('Package_TO_SOT_SMD', 'SOT-23-6', 0, 'F'), ('Package_TO_SOT_SMD', 'SOT-23-6', 30, 'F'),
    ('Package_TO_SOT_SMD', 'SOT-23-6', 30, 'B'), ('Package_TO_SOT_SMD', 'SOT-23-6', -90, 'B'),
    ('Inductor_SMD', 'L_Bourns_SDR0604', 45, 'B'), ('Inductor_SMD', 'L_Bourns_SDR0604', 45, 'F'),
    ('Package_LGA', 'ST_CCLGA-7L_2.8x2.8mm_P1.15mm_H1.95mm', 90, 'B'),
    ('Battery', 'BatteryHolder_Keystone_1057_1x2032', 0, 'B'), ('Diode_SMD', 'D_QFN_3.3x3.3mm_P0.65mm', 270, 'B'),
    ('TerminalBlock_WAGO', 'TerminalBlock_WAGO_804-309_1x09_P7.50mm_45Degree', 15, 'B'),
    ('Package_QFP', 'LQFP-52-1EP_10x10mm_P0.65mm_EP4.8x4.8mm', 90, 'B'),
    ('RF_Antenna', 'Astrocast_AST50127-00', 0, 'B'), ('RF_Module', 'ESP32-S3-WROOM-1', -90, 'B'),
    ('RF_Module', 'ESP32-S3-WROOM-1', 30, 'F'), ('Sensor_Current', 'LEM_CKSR', -45, 'B'),
    ('Module', 'Flipper_Zero_Angled', 90, 'B'), ('LED_SMD', 'LED_Kingbright_KPBD-3224', -45, 'B'),
    ('Battery', 'Battery_Panasonic_CR2032-VS1N_Vertical_CircularHoles', 90, 'B'),
    ('Relay_THT', 'Relay_Socket_DPDT_Omron_PLE08-0', 0, 'B'),
    ('Connector_USB', 'USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal', 90, 'F'),
]

PCBNEW_SCRIPT = r'''
import pcbnew, sys, json
F = sys.argv[1]
specs = json.load(open(sys.argv[2]))
b = pcbnew.CreateEmptyBoard(); b.SetCopperLayerCount(4)
pads = {}
for i, (lib, name, rot, side) in enumerate(specs):
    f = pcbnew.FootprintLoad(F + '/' + lib + '.pretty', name); f.SetFPID(pcbnew.LIB_ID(lib, name)); b.Add(f)
    f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(20 + 30 * i), pcbnew.FromMM(50)))
    if side == 'B':
        f.SetLayerAndFlip(pcbnew.B_Cu)
    f.SetOrientationDegrees(rot); f.SetReference('X%d' % i); f.SetValue('V%d' % i)
    pads['X%d' % i] = [(p.GetNumber(), pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
                       for p in f.Pads()]
pcbnew.SaveBoard(sys.argv[3], b)
json.dump(pads, open(sys.argv[4], 'w'))
'''


def _norm(n, tol):
    out = Node(n[0])
    for c in n[1:]:
        if isinstance(c, Node):
            if c[0] != 'uuid':
                out.append(_norm(c, tol))
        elif isinstance(c, bool):
            out.append('yes' if c else 'no')
        else:
            try:
                out.append(round(float(c) / tol) * tol + 0.0)
            except ValueError:
                out.append(str(c))
    return out


def test_footprint_placement_matches_pcbnew():
    """Place library footprints front/back at several angles with the layer and with pcbnew; every item of every
    footprint must match (uuids ignored, 2 um tolerance for pcbnew's nm rounding, item order ignored), and
    Footprint.pad_position() must give pcbnew's pad centres."""
    if not KICAD_PYTHON:
        raise Skip('KiCad python with pcbnew not found (set KICAD_PYTHON)')
    d = tmpdir('pcbnew')
    sp, script = os.path.join(d, 'specs.json'), os.path.join(d, 'mk.py')
    json.dump(SPECS, open(sp, 'w'))
    open(script, 'w').write(PCBNEW_SCRIPT)
    ref_pcb, ref_pads = os.path.join(d, 'pcbnew.kicad_pcb'), os.path.join(d, 'pads.json')
    subprocess.run([KICAD_PYTHON, script, FP(), sp, ref_pcb, ref_pads], capture_output=True, timeout=600)
    assert os.path.exists(ref_pcb)
    mine = Board.new(4)
    for i, (lib, name, rot, side) in enumerate(SPECS):
        mine.add_footprint(os.path.join(FP(), lib + '.pretty', name + '.kicad_mod'), '%s:%s' % (lib, name),
                           'X%d' % i, 'V%d' % i, (20 + 30 * i, 50), rot, side)
    theirs = Board.load(ref_pcb)
    pads = json.load(open(ref_pads))
    bad = []
    for i, spec in enumerate(SPECS):
        a, b = mine.footprint('X%d' % i), theirs.footprint('X%d' % i)
        for tol in (0.002, 0.003):                       # two grids, so a value on a rounding edge still matches
            ca = collections.Counter(dumps(_norm(c, tol)) for c in a.node.nodes() if c.head != 'uuid')
            cb = collections.Counter(dumps(_norm(c, tol)) for c in b.node.nodes() if c.head != 'uuid')
            if ca == cb:
                break
        else:
            bad.append((spec, list((ca - cb))[:1], list((cb - ca))[:1]))
        for num, x, y in pads['X%d' % i]:
            idx = [k for k, p in enumerate(a.pads(num))]
            got = [a.pad_position(num, k) for k in idx]
            assert any(abs(gx - x) < 0.002 and abs(gy - y) < 0.002 for gx, gy in got), (spec, num, got, (x, y))
            got_t = [b.pad_position(num, k) for k in range(len(b.pads(num)))]
            assert any(abs(gx - x) < 0.002 and abs(gy - y) < 0.002 for gx, gy in got_t), (spec, num)
    assert not bad, bad


def test_other_builders_survive_kicad_resave():
    """Micro / blind vias, circles, rectangles, filled copper polygons: KiCad loads and re-saves all of them."""
    d = tmpdir('misc')
    b = Board.new(4)
    b.via((10, 10), 0.3, 0.1, 'N', layers=('F.Cu', 'In1.Cu'), via_type='micro')
    b.via((12, 10), 0.45, 0.2, 'N', layers=('F.Cu', 'In2.Cu'), via_type='blind')
    b.gr_circle((20, 20), 2, 'F.SilkS')
    b.gr_rect((25, 25), (30, 28), 'F.Fab')
    b.gr_poly([(1, 1), (3, 1), (3, 3)], 'F.Cu', net='N')
    b.outline_rect(0, 0, 40, 40)
    p = os.path.join(d, 'm.kicad_pcb')
    b.save(p)
    k = load(p)
    resave(p)
    k2 = load(p)
    for head in ('via', 'gr_circle', 'gr_rect', 'gr_poly', 'gr_line'):
        assert len(k2.nodes(head)) == len(k.nodes(head)), head
    assert sorted(str(v[1]) for v in k2.nodes('via')) == ['blind', 'micro']


def test_stackup_without_loss_tangents():
    """A manufacturer table without loss tangents: stackup(..., None) leaves them out and KiCad reads its defaults
    (re-save shows 0 for the mask, 0.02 for the dielectric) with every other value as written."""
    from kicad_sexpr import stackup as mk
    d = tmpdir('stackup_nolt')
    b = Board.new(2)
    s = mk([0.035, 0.035], [('core', 1.51, 'FR4', 4.6, None)], mask_loss_tangent=None, finish='None')
    assert not list(s.walk('loss_tangent'))
    b.set_stackup(s)
    b.set_thickness(1.6)
    b.outline_rect(0, 0, 10, 10)
    p = os.path.join(d, 's.kicad_pcb')
    b.save(p)
    resave(p)
    k = load(p).find('setup').find('stackup')
    rows = {str(r[1]): r for r in k.nodes('layer')}
    assert str(rows['dielectric 1'].get('thickness')) == '1.51' and str(rows['dielectric 1'].get('epsilon_r')) == '4.6'
    assert str(rows['dielectric 1'].get('loss_tangent')) == '0.02' and str(rows['F.Mask'].get('loss_tangent')) == '0'
    assert str(k.get('copper_finish')) == 'None'


def test_fp_rect_courtyard_is_used_by_drc():
    """A courtyard made with fp_rect: KiCad keeps it (library upgrade) and DRC reports two such footprints
    overlapping (courtyards_overlap), so it is a real courtyard."""
    from kicad_sexpr import Uuids, fp_line, fp_rect, save
    from helpers import cli
    d = tmpdir('fprect')
    lib = os.path.join(d, 'T.pretty')
    os.makedirs(lib)
    fp = load(_r0402())
    for n in list(fp.nodes()):
        if n.get('layer') == 'F.CrtYd':
            fp.remove_node(n)
    u = Uuids(seed='kicad_mod:test')
    fp.insert_before('pad', fp_rect((-1, -0.6), (1, 0.6), 'F.CrtYd', uuids=u))
    fp.insert_before('pad', fp_line((-0.5, 0.8), (0.5, 0.8), 'F.SilkS', uuids=u))
    p = os.path.join(lib, 'R_test.kicad_mod')
    save(fp, p)
    r = cli('fp', 'upgrade', '--force', lib)
    assert r.returncode == 0, r.stdout + r.stderr
    k = load(p)
    assert len([n for n in k.nodes('fp_rect') if n.get('layer') == 'F.CrtYd']) == 1
    assert len([n for n in k.nodes('fp_line') if n.get('layer') == 'F.SilkS']) == len(
        [n for n in fp.nodes('fp_line') if n.get('layer') == 'F.SilkS'])
    b = Board.new(2)
    b.add_footprint(p, 'T:R_test', 'R1', '1k', (10, 10), pad_nets={'1': 'A', '2': 'B'})
    b.add_footprint(p, 'T:R_test', 'R2', '1k', (11.5, 10), pad_nets={'1': 'C', '2': 'D'})
    b.outline_rect(0, 0, 20, 20)
    pcb = os.path.join(d, 'c.kicad_pcb')
    b.save(pcb)
    assert drc(pcb, refill=False)['violations'].get('courtyards_overlap', 0) >= 1
