#!/usr/bin/env python3
"""A hierarchical design written by schgen: a root sheet, a power sheet used once and a channel sheet used 3 times.

  python3 examples/hierarchy_demo.py OUT_DIR [CHANNELS]

Writes OUT_DIR/demo.kicad_sch (root: input connector, data and feedback connectors, PWR_FLAGs), power.kicad_sch
(AMS1117-3.3 with its capacitors; hierarchical label VIN) and channel.kicad_sch (series resistor, divider, output
connector, decoupling; hierarchical labels DIN in, FB out), placed as ch1..chN with references offset by 100 per
instance (R1 -> R101, R201, ...), plus demo.kicad_pro, netspec.json (the intended nets in the sheet-template form
netspec.py reads, so each repeated sheet's nets are written once) and place.json (new_board.py --placement). The test suite checks the result with KiCad
(tests/test_schgen_hierarchy.py): ERC, the netlist against netspec.json, a board from new_board.py with DRC schematic
parity, a KiCad re-save, and byte-identical regeneration.
"""
import json, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from schgen import Sch, find_merges, kicad_symbol_dir  # noqa: E402

R0402, C0402, C0805 = 'Resistor_SMD:R_0402_1005Metric', 'Capacitor_SMD:C_0402_1005Metric', 'Capacitor_SMD:C_0805_2012Metric'
HDR = 'Connector_PinHeader_2.54mm:PinHeader_1x%02d_P2.54mm_Vertical'

# intended nets of each sheet, in its own (local) references; 'BLOCK/LABEL' is a sheet pin of a block on that sheet
POWER_NETS = {'VIN': ['U1.3', 'C1.1'], '+3V3': ['U1.2', 'C2.1'], 'GND': ['U1.1', 'C1.2', 'C2.2']}
CHANNEL_NETS = {'DIN': ['R1.1'], 'DOUT': ['R1.2', 'R2.1', 'J1.2'], 'FB': ['R2.2', 'R3.1'],
                '+3V3': ['J1.1', 'C1.1'], 'GND': ['J1.3', 'R3.2', 'C1.2']}


def root_nets(n):
    nets = {'VIN': ['J1.1', 'power/VIN'], 'GND': ['J1.2']}
    for k in range(1, n + 1):
        nets['D%d' % k] = ['J2.%d' % k, 'ch%d/DIN' % k]
        nets['FB%d' % k] = ['J3.%d' % k, 'ch%d/FB' % k]
    return nets


def power_sheet(root):
    s = root.sub('power.kicad_sch', title='Power: 3.3 V LDO')
    s.hlabel('VIN', 50.8, 60.96, 180, shape='input')
    u1 = s.add('Regulator_Linear:AMS1117-3.3', 'U1', 'AMS1117-3.3', 88.9, 60.96, lcsc='C6186')
    c1 = s.add('Device:C', 'C1', '10u', 66.04, 66.04, footprint=C0805, lcsc='C15850')
    c2 = s.add('Device:C', 'C2', '10u', 104.14, 66.04, footprint=C0805, lcsc='C15850')
    s.wire((50.8, 60.96), u1.p('VI'))
    s.wire((66.04, 60.96), c1.p(1))
    s.wire(u1.p('VO'), (109.22, 60.96), (109.22, 58.42))
    s.wire((104.14, 60.96), c2.p(1))
    s.power('+3V3', 109.22, 58.42, lib_id='power:+3V3')
    for pt in (c1.p(2), u1.p('GND'), c2.p(2)):
        s.wire(pt, (pt[0], 72.39))
        s.power('GND', pt[0], 72.39)
    return s


def channel_sheet(root):
    s = root.sub('channel.kicad_sch', title='Output channel')
    s.hlabel('DIN', 50.8, 60.96, 180, shape='input')
    s.hlabel('FB', 101.6, 72.39, 0, shape='output')
    r1 = s.add('Device:R', 'R1', '33', 63.5, 60.96, rot=90, footprint=R0402, lcsc='C25105')
    r2 = s.add('Device:R', 'R2', '10k', 76.2, 66.04, footprint=R0402, lcsc='C25744')
    r3 = s.add('Device:R', 'R3', '10k', 76.2, 76.2, footprint=R0402, lcsc='C25744')
    c1 = s.add('Device:C', 'C1', '100n', 63.5, 76.2, footprint=C0402, lcsc='C1525')
    j1 = s.add('Connector_Generic:Conn_01x03', 'J1', 'OUT', 93.98, 60.96, footprint=HDR % 3, lcsc='C2337')
    s.wire((50.8, 60.96), r1.p(1))
    s.wire(r1.p(2), (72.39, 60.96))
    s.wire((72.39, 60.96), (76.2, 60.96), j1.p(2))
    s.label('DOUT', 72.39, 60.96)
    s.wire((76.2, 60.96), r2.p(1))
    s.wire(r2.p(2), r3.p(1))
    s.wire((76.2, 72.39), (101.6, 72.39))
    s.wire(j1.p(1), (83.82, 58.42), (83.82, 53.34))
    s.power('+3V3', 83.82, 53.34, lib_id='power:+3V3')
    s.wire(j1.p(3), (83.82, 63.5), (83.82, 68.58))
    s.power('GND', 83.82, 68.58)
    s.wire(c1.p(1), (63.5, 69.85))
    s.power('+3V3', 63.5, 69.85, lib_id='power:+3V3')
    for pt in (c1.p(2), r3.p(2)):
        s.wire(pt, (pt[0], 82.55))
        s.power('GND', pt[0], 82.55)
    return s


def build(n=3):
    """(root Sch, {sheet: (Sch, intended nets)}): the whole design, not yet written"""
    root = Sch('demo', paper='A4', title='Hierarchy demo', rev='1', date='2026-10-31')
    d = kicad_symbol_dir()
    for lib in ('Device', 'power', 'Connector_Generic', 'Regulator_Linear'):
        root.lib(lib, os.path.join(d, lib + '.kicad_sym'))
    power, channel = power_sheet(root), channel_sheet(root)
    j1 = root.add('Connector_Generic:Conn_01x02', 'J1', 'PWR_IN', 25.4, 50.8, mirror='y', footprint=HDR % 2, lcsc='C2337')
    pb = root.sheet(power, 'power', 50.8, 48.26)
    root.wire(j1.p(1), pb.p('VIN'))
    flag = root.add('power:PWR_FLAG', '#FLG01', 'PWR_FLAG', 40.64, 50.8, in_bom=False, on_board=False)
    root.tap(flag.p(1))
    root.wire(j1.p(2), (38.1, 53.34), (38.1, 58.42))
    root.power('GND', 38.1, 58.42)
    flag = root.add('power:PWR_FLAG', '#FLG02', 'PWR_FLAG', 33.02, 53.34, rot=180, in_bom=False, on_board=False)
    root.tap(flag.p(1))
    j2 = root.add('Connector_Generic:Conn_01x%02d' % n, 'J2', 'DATA_IN', 63.5, 66.04, mirror='y', footprint=HDR % n,
                  lcsc='C2337')
    j3 = root.add('Connector_Generic:Conn_01x%02d' % n, 'J3', 'FB_OUT', 160.02, 66.04, footprint=HDR % n, lcsc='C2337')
    for k in range(n):
        b = root.sheet(channel, 'ch%d' % (k + 1), 101.6, 76.2 + 12.7 * k, h=7.62, refs=100 * (k + 1))
        din, fb = b.p('DIN'), b.p('FB')
        a = j2.p(k + 1)
        root.wire(a, (91.44 - 5.08 * k, a[1]), (91.44 - 5.08 * k, din[1]), din)
        c = j3.p(k + 1)
        root.wire(fb, (132.08 + 5.08 * k, fb[1]), (132.08 + 5.08 * k, c[1]), c)
    return root, {'root': (root, root_nets(n)), 'power': (power, POWER_NETS), 'channel': (channel, CHANNEL_NETS)}


def netspec(root, n=3):
    """the intended netlist in netspec.py's sheet-template form: each sheet's nets once, its instances by reference
    map (taken from the generator, so the spec and the drawing cannot disagree on references)"""
    inst = {path.strip('/'): refs for path, s, refs in root.instances() if s.file}
    return {'global': ['GND', '+3V3'],
            'nets': root_nets(n),
            'sheets': {'power': {'nets': POWER_NETS, 'instances': {'power': {'refs': inst['power']}}},
                       'channel': {'nets': CHANNEL_NETS, 'instances': {'ch%d' % k: 100 * k for k in range(1, n + 1)}}}}


def placement(n=3):
    """new_board.py --placement for the demo board (mm from the outline's top-left; 80 x 60 mm holds 3 channels)"""
    pl = {'J1': [5, 8, 0], 'J2': [12, 8, 0], 'J3': [19, 8, 0], 'C1': [30, 8, 0], 'U1': [40, 8, 0], 'C2': [50, 8, 0]}
    for k in range(1, n + 1):
        y = 12 + 12 * k
        pl.update({'J%d01' % k: [5, y, 0], 'R%d01' % k: [15, y, 0], 'R%d02' % k: [20, y, 0], 'R%d03' % k: [25, y, 0],
                   'C%d01' % k: [30, y, 0]})
    return pl


def write(out, n=3):
    root, sheets = build(n)
    problems = []
    for name, (s, nets) in sheets.items():
        problems += ['%s: %s' % (name, m) for m in s.collisions() + find_merges(s, nets)]
    if problems:
        raise SystemExit('\n'.join(problems))
    os.makedirs(out, exist_ok=True)
    root.write(os.path.join(out, 'demo.kicad_sch'))
    pro = os.path.join(out, 'demo.kicad_pro')
    if not os.path.exists(pro):
        from kicad_sexpr import Project
        Project.new(pro).save()
    with open(os.path.join(out, 'netspec.json'), 'w') as f:
        json.dump(netspec(root, n), f, indent=1)
    with open(os.path.join(out, 'place.json'), 'w') as f:
        json.dump(placement(n), f, indent=1)
    return root


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    write(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    print('wrote %s' % sys.argv[1])
