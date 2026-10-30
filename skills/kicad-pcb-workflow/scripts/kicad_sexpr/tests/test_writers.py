"""The higher-level writers built on kicad_sexpr (symgen, schgen, new_board, board_setup, router, add_courtyard),
run end to end on a small design and judged by KiCad: ERC and netlist for the schematic, DRC with schematic parity
for the board, library upgrade for footprints and symbols. Each one must also regenerate byte-identically."""
import json
import os
import shutil
import subprocess
import sys

from helpers import KICAD_PYTHON, Skip, cli, drc, erc, footprints_dir, netlist, symbols_dir, tmpdir
from kicad_sexpr import Board, Project, load, save

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SCRIPTS)
VENV_PY = os.environ.get('PY') or os.path.join(os.environ.get('KICAD_SKILLS_VENV', os.path.expanduser(
    '~/.cache/kicad-skills/venv')), 'bin', 'python')
BOARDDUMP = os.path.join(os.path.dirname(os.path.dirname(SCRIPTS)), 'kicad-board-review', 'scripts', 'boarddump.py')


def _run(*cmd):
    r = subprocess.run(list(cmd), capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=SCRIPTS))
    return r.returncode, r.stdout + r.stderr


def _schematic(d):
    """A small sheet: redrawn LDO (symgen.ic), a FET renumbered from Device:Q_NMOS (symgen.fet), passives, power
    symbols, labels, a global label, multi-line text, a no-connect. Returns the sheet path."""
    import schgen
    import symgen
    from schgen import Sch, SymLib, kicad_symbol_dir
    S = kicad_symbol_dir()
    syms = {'LDO': symgen.ic('LDO', 5.08, left=[('VIN', ['1'], symgen.PI), ('EN', ['3'], symgen.IN)],
                             right=[('VOUT', ['5'], symgen.PO), ('NC', ['4'], symgen.NC)],
                             bottom=[('GND', ['2'], symgen.PI)], desc='test "LDO"'),
            'NFET': symgen.fet(SymLib('Device', S + '/Device.kicad_sym').get('Q_NMOS'), 'NFET', D=['3'], G=['1'],
                               S=['2'], desc='SOT-23')}
    if not os.path.exists(os.path.join(d, 'w.kicad_pro')):
        Project.new(os.path.join(d, 'w.kicad_pro')).save()     # kicad-cli reads the project's sym-lib-table
    lib = os.path.join(d, 'w.kicad_sym')
    table = symgen.save_library(syms, lib, 'W', generator='w_test')   # writes w.kicad_sym, registers W
    assert open(table).read() == ('(sym_lib_table\n\t(version 7)\n\t(lib (name "W") (type "KiCad") '
                                  '(uri "${KIPRJMOD}/w.kicad_sym") (options "") (descr ""))\n)\n')
    s = Sch('w', paper='A4', title='writers "test"', rev='1', date='2026-10-24')
    s.lib('Device', S + '/Device.kicad_sym')
    s.lib('power', S + '/power.kicad_sym')
    s.lib('W', lib)
    u1 = s.add('W:LDO', 'U1', 'LDO', 76.2, 63.5, footprint='Package_TO_SOT_SMD:SOT-23-5', lcsc='C1')
    c1 = s.add('Device:C', 'C1', '1u', 55.88, 68.58, footprint='Capacitor_SMD:C_0402_1005Metric',
               lcsc='C52923', fields={'Voltage': '25V', '_visible': ['Voltage']})
    r1 = s.add('Device:R', 'R1', '10k', 99.06, 68.58, footprint='Resistor_SMD:R_0402_1005Metric', lcsc='C25744')
    r2 = s.add('Device:R', 'R2', '100k', 106.68, 80.01, footprint='Resistor_SMD:R_0402_1005Metric', lcsc='C25741')
    q1 = s.add('W:NFET', 'Q1', 'NFET', 116.84, 76.2, footprint='Package_TO_SOT_SMD:SOT-23',
              fields={'Datasheet': 'https://www.example.com/nfet.pdf'})   # every BOM part carries a datasheet (R22)
    vin, en = u1.p('VIN'), u1.p('EN')
    s.wire(vin, (55.88, vin[1]), c1.p(1))
    s.wire(en, (60.96, en[1]), (60.96, vin[1]))
    s.power('VIN', 55.88, vin[1] - 5.08)
    s.wire((55.88, vin[1] - 5.08), (55.88, vin[1]))
    s.power('GND', *c1.p(2))
    s.power('GND', *u1.p('GND'))
    vo = u1.p('VOUT')
    s.wire(vo, (99.06, vo[1]), r1.p(1))
    s.label('VOUT', 93.98, vo[1])
    s.nc(u1.p('NC'))
    g = q1.p('G')
    s.wire(r1.p(2), (99.06, g[1]), r2.p(1))
    s.wire(r2.p(1), g)
    s.power('GND', *r2.p(2))
    s.power('GND', *q1.p('S'))
    d3 = q1.p('D')
    s.wire(d3, (d3[0], d3[1] - 5.08))
    s.label('OUT', d3[0], d3[1] - 5.08, kind='global_label', shape='output')
    s.text('gate pull-down\nR2 = 100k', 101.6, 88.9, bold=True)
    for i, net in enumerate(('VIN', 'GND')):
        x = 139.7 + 10.16 * i
        s.add('power:PWR_FLAG', '#FLG%02d' % (i + 1), 'PWR_FLAG', x, 50.8, in_bom=False, on_board=False)
        s.wire((x, 50.8), (x, 55.88))
        s.power(net, x, 55.88, 180 if net != 'GND' else 0)
    assert not s.collisions(), s.collisions()
    p = os.path.join(d, 'w.kicad_sch')
    s.write(p)
    assert schgen.find_merges(s, {'GND': ['C1.2', 'U1.2', 'R2.2', 'Q1.2']}) == []
    return p


def test_symgen_and_schgen_erc_netlist_and_regeneration():
    d = tmpdir('wsch')
    p = _schematic(d)
    nets = {k: sorted(v) for k, v in netlist(p).items()}
    assert nets['GND'] == ['C1.2', 'Q1.2', 'R2.2', 'U1.2']
    assert nets['VIN'] == ['C1.1', 'U1.1', 'U1.3']
    assert nets['unconnected-(U1-NC-Pad4)'] == ['U1.4']
    assert nets['/VOUT'] == ['R1.1', 'U1.5']
    assert nets['OUT'] == ['Q1.3']
    assert sorted(v for k, v in nets.items() if k.startswith('Net-(')) == [['Q1.1', 'R1.2', 'R2.1']]
    assert erc(p) == {'isolated_pin_label': 1}                # the one-pin OUT label, on purpose
    r = cli('sym', 'upgrade', '--force', os.path.join(d, 'w.kicad_sym'))
    assert r.returncode == 0, r.stdout + r.stderr
    first = open(p).read()
    d2 = tmpdir('wsch2')
    assert open(_schematic(d2)).read() == first              # from scratch: same bytes
    assert open(_schematic(d)).read() == first               # over the previous file (ids reused): same bytes


PLAN = '''
def build(r):
    r.track('F.Cu', 0.25, ('R1', '2'), ('R2', '1'))
    r.via_near('R2', '2')
    r.zone('GND', 'B.Cu', [(100.3, 100.3), (129.7, 100.3), (129.7, 119.7), (100.3, 119.7)], name='GND_B')
    r.keepout('B.Cu', [(101, 101), (104, 101), (104, 104), (101, 104)], name='NO_POUR')
'''


def test_new_board_board_setup_router_pipeline():
    if not KICAD_PYTHON:
        raise Skip('KiCad python not found (boarddump needs pcbnew)')
    if not os.path.exists(VENV_PY) or subprocess.run([VENV_PY, '-c', 'import shapely']).returncode:
        raise Skip('analysis venv with shapely not found (set PY)')
    outs = []
    for run in ('a', 'b'):
        d = tmpdir('wpcb' + run)
        sch = _schematic(d)
        net = os.path.join(d, 'net.xml')
        cli('sch', 'export', 'netlist', '--format', 'kicadxml', '-o', net, sch)
        place = os.path.join(d, 'place.json')
        json.dump({'U1': [8, 10, 0], 'C1': [3, 10, 90], 'R1': [15, 6, 270], 'R2': [15, 14, 270], 'Q1': [22, 10, 0]},
                  open(place, 'w'))
        labels = os.path.join(d, 'labels.json')
        json.dump({'Q1': ['OUT', 0, -3]}, open(labels, 'w'))
        pcb = os.path.join(d, 'w.kicad_pcb')
        rc, out = _run(sys.executable, os.path.join(SCRIPTS, 'new_board.py'), net, pcb, '--layers', '2', '--outline',
                       '30x20', '--origin', '100,100', '--corner-r', '1', '--placement', place, '--labels', labels,
                       '--refs', 'fab')
        assert rc == 0 and '5 footprints (5 placed, 0 staged)' in out, out
        rc, out = _run(sys.executable, os.path.join(SCRIPTS, 'board_setup.py'), d, '--stackup', 'JLC-2L-1.6',
                       '--class', 'Power:track=0.5,clearance=0.2', '--assign', 'Power=GND,VIN')
        assert rc == 0, out
        pro = Project.load(os.path.join(d, 'w.kicad_pro'))
        assert pro.assignments() == {'GND': ['Power'], 'VIN': ['Power']}
        pack = os.path.join(d, 'pack')
        rc, out = _run(KICAD_PYTHON, BOARDDUMP, pcb, pack)
        plan = os.path.join(d, 'plan.py')
        open(plan, 'w').write(PLAN)
        rc, out = _run(VENV_PY, os.path.join(SCRIPTS, 'router.py'), 'apply', pcb, os.path.join(pack, 'board.json'), plan)
        assert 'wrote' in out and '1 segments' not in out, out
        outs.append((open(sch).read(), open(pcb).read()))
        b = load(pcb)
        assert len(b.nodes('footprint')) == 5 and len(b.nodes('segment')) == 2 and len(b.nodes('via')) == 1
        assert len(b.nodes('zone')) == 2 and str(b.find('general').get('thickness')) == '1.6'
        fp = Board(b).footprint('U1')
        assert fp.field_value('LCSC') == 'C1' and fp.field('Reference').find('hide') is not None
        r = drc(pcb, parity=True)
        assert r['parity'] == 0, r['raw']['schematic_parity']
        bad = {k: v for k, v in r['violations'].items()
               if k in ('clearance', 'shorting_items', 'tracks_crossing', 'hole_clearance', 'copper_edge_clearance',
                        'net_conflict', 'via_dangling', 'track_dangling', 'invalid_outline')}
        assert not bad, bad
        # rerun new_board over its own output: the same footprints, the same bytes up to the routing
        before = load(pcb)
        rc, out = _run(sys.executable, os.path.join(SCRIPTS, 'new_board.py'), net, pcb, '--layers', '2', '--outline',
                       '30x20', '--origin', '100,100', '--corner-r', '1', '--placement', place, '--labels', labels,
                       '--refs', 'fab')
        assert rc == 0 and ' ids kept' in out, out
        again = load(pcb)
        assert [str(f.get('uuid')) for f in again.nodes('footprint')] == [str(f.get('uuid')) for f in
                                                                          before.nodes('footprint')]
    assert outs[0] == outs[1]                                # two from-scratch pipelines: byte-identical


def test_add_courtyard_on_footprints_without_one():
    d = tmpdir('wcrt')
    lib = os.path.join(d, 'T.pretty')
    os.makedirs(lib)
    src = os.path.join(footprints_dir(), 'Package_TO_SOT_SMD.pretty', 'SOT-23.kicad_mod')
    fp = load(src)
    for n in list(fp.nodes()):
        if n.get('layer') == 'F.CrtYd':
            fp.remove_node(n)
    p = os.path.join(lib, 'SOT-23.kicad_mod')
    save(fp, p)
    rc, out = _run(sys.executable, os.path.join(SCRIPTS, 'add_courtyard.py'), lib)
    assert rc == 0 and 'added' in out, out
    first = open(p).read()
    rects = [n for n in load(p).nodes('fp_rect') if n.get('layer') == 'F.CrtYd']
    assert len(rects) == 1 and str(rects[0].need('stroke').get('width')) == '0.05'
    rc, out = _run(sys.executable, os.path.join(SCRIPTS, 'add_courtyard.py'), lib)
    assert 'has courtyard' in out and open(p).read() == first
    shutil.copy(src, os.path.join(d, 'orig.kicad_mod'))
    save(fp, p)
    _run(sys.executable, os.path.join(SCRIPTS, 'add_courtyard.py'), lib)
    assert open(p).read() == first                           # deterministic id
    r = cli('fp', 'upgrade', '--force', lib)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len([n for n in load(p).nodes('fp_rect') if n.get('layer') == 'F.CrtYd']) == 1


def test_fpcheck_reads_through_the_layer():
    rc, out = _run(sys.executable, os.path.join(SCRIPTS, 'fpcheck.py'), 'Package_SON:Texas_DQK', '--symbol',
                   os.path.join(symbols_dir(), 'Device.kicad_sym') + ':Q_NMOS')
    assert rc == 1 and 'pads with no symbol pin' in out and 'courtyard 2.' in out, out
