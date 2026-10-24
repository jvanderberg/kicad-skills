#!/usr/bin/env python3
"""The README example: a wired RC block on a schematic and a matching two-part board with a track, a via, a GND
zone, a keepout and an outline. Usage: python3 quickstart.py OUT_DIR  (then open OUT_DIR/demo.kicad_pro)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from kicad_sexpr import Board, Project, Schematic, SymbolLibrary, stackup  # noqa: E402

KICAD = os.environ.get('KICAD_SHARE', '/Applications/KiCad/KiCad.app/Contents/SharedSupport')
out = sys.argv[1]
os.makedirs(out, exist_ok=True)

# ------------------------------------------------------------------ schematic
lib = {n: SymbolLibrary.load(os.path.join(KICAD, 'symbols', n + '.kicad_sym'), n)
       for n in ('Device', 'power', 'Connector')}

sch = Schematic.new('demo', paper='A4', title='RC filter', date='2026-10-24', rev='1')
j1 = sch.add_symbol('Connector:Conn_01x03_Pin', 'J1', 'IN/OUT/GND', (38.1, 53.34), lib=lib['Connector'],
                    footprint='Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical')
r1 = sch.add_symbol('Device:R', 'R1', '10k', (55.88, 50.8), angle=90, lib=lib['Device'],
                    footprint='Resistor_SMD:R_0402_1005Metric', fields={'LCSC': 'C25744'})
c1 = sch.add_symbol('Device:C', 'C1', '100n', (63.5, 55.88), lib=lib['Device'],
                    footprint='Capacitor_SMD:C_0402_1005Metric')
c1.set_field('Value', at=(66.04, 57.15))                      # fields can be moved, shown, hidden, turned
# pin() is a pin's connection point after rotation / mirror, so wires land exactly on pins
sch.wire(j1.pin(1), r1.pin(1))                                # IN
sch.label('IN', j1.pin(1))
out_x = c1.pin(1)[0]
sch.wire(r1.pin(2), (out_x, r1.pin(2)[1]), c1.pin(1))         # OUT
sch.wire(j1.pin(2), (45.72, j1.pin(2)[1]), (45.72, 45.72), (out_x, 45.72), (out_x, r1.pin(2)[1]))
sch.junction((out_x, r1.pin(2)[1]))
sch.label('OUT', (45.72, j1.pin(2)[1]))
gnd = sch.power('power:GND', (c1.pin(2)[0], c1.pin(2)[1] + 5.08), lib=lib['power'])
sch.wire(c1.pin(2), gnd.pin(1))
x3 = j1.pin(3)[0] + 2.54
sch.wire(j1.pin(3), (x3, j1.pin(3)[1]), (x3, j1.pin(3)[1] + 5.08))
sch.power('power:GND', (x3, j1.pin(3)[1] + 5.08))
flag = sch.add_symbol('power:PWR_FLAG', '#FLG01', 'PWR_FLAG', (76.2, 60.96), lib=lib['power'],
                      in_bom=False, on_board=False)
sch.wire(flag.pin(1), (76.2, gnd.pin(1)[1]), gnd.pin(1))
sch.junction(gnd.pin(1))
sch.text('fc = 159 Hz\n(R1 x C1)', (38.1, 73.66))           # newlines are escaped on output, never written raw
sch.save(os.path.join(out, 'demo.kicad_sch'))

# ------------------------------------------------------------------ board
# Net names as the netlist names them: local labels on the root sheet are "/IN", "/OUT"; power symbols "GND".
fp = os.path.join(KICAD, 'footprints')
b = Board.new(copper_layers=2)
b.set_stackup(stackup([0.035, 0.035], [('core', 1.51, 'FR4', 4.5, 0.02)]))


def place(ref, lib_dir, name, at, angle, nets):
    s = sch.symbol(ref)
    fields = {k: v for k, v in s.fields().items() if k not in ('Reference', 'Value', 'Footprint')}
    return b.add_footprint(os.path.join(fp, lib_dir + '.pretty', name + '.kicad_mod'), lib_dir + ':' + name,
                           ref, s.value, at, angle, path='/' + s.uuid, fields=fields, pad_nets=nets)


J1 = place('J1', 'Connector_PinHeader_2.54mm', 'PinHeader_1x03_P2.54mm_Vertical', (104, 106), 0,
           {'1': '/IN', '2': '/OUT', '3': 'GND'})
R1 = place('R1', 'Resistor_SMD', 'R_0402_1005Metric', (108, 106), 0, {'1': '/IN', '2': '/OUT'})
C1 = place('C1', 'Capacitor_SMD', 'C_0402_1005Metric', (108, 110), 0, {'1': '/OUT', '2': 'GND'})
b.track([J1.pad_position(1), R1.pad_position(1)], 0.25, 'F.Cu', '/IN')
bend = (C1.pad_position(1)[0], J1.pad_position(2)[1])
b.track([J1.pad_position(2), bend, C1.pad_position(1)], 0.25, 'F.Cu', '/OUT')
b.track([R1.pad_position(2), bend], 0.25, 'F.Cu', '/OUT')
b.track([C1.pad_position(2), (110, 110)], 0.25, 'F.Cu', 'GND')
b.via((110, 110), 0.6, 0.3, 'GND', free=True)                 # into the B.Cu ground pour
b.zone('GND', 'B.Cu', [(100, 100), (120, 100), (120, 120), (100, 120)], name='GND')
b.rule_area('B.Cu', [(114, 113), (118, 113), (118, 117), (114, 117)], name='no pour')
b.gr_text('RC', (113, 104), 'F.SilkS')
b.outline_rect(100, 100, 20, 20, corner_radius=1)
b.save(os.path.join(out, 'demo.kicad_pcb'))

pro = Project.new(os.path.join(out, 'demo.kicad_pro'))
pro.netclass('Default', clearance=0.15, track_width=0.25)
pro.save()
print('wrote', out)
