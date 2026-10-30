"""new_board.py writes each pad's pin name and type, as KiCad's "Update PCB from schematic" does: (pinfunction ...)
verbatim from the netlist for a named pin, none for an unnamed one, (pintype ...) for every pin. JLCImport's placement
solver pairs a polarised part's pads by those names; with none it assumes KiCad's pad-1 convention and warns on every
diode and LED (a generated USB-UART board had 0 pinfunction entries). Uses KiCad's footprint library (skipped without
it):  python3 tests/test_new_board_pins.py"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from kicad_sexpr import Board

NETLIST = '''<export version="E"><components>
<comp ref="D1"><value>RED</value><footprint>LED_SMD:LED_0603_1608Metric</footprint>
<sheetpath names="/" tstamps="/"/><tstamps>00000000-0000-0000-0000-000000000001</tstamps></comp>
<comp ref="R1"><value>1k</value><footprint>Resistor_SMD:R_0402_1005Metric</footprint>
<sheetpath names="/" tstamps="/"/><tstamps>00000000-0000-0000-0000-000000000002</tstamps></comp>
<comp ref="J1"><value>HDR</value><footprint>Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical</footprint>
<sheetpath names="/" tstamps="/"/><tstamps>00000000-0000-0000-0000-000000000003</tstamps></comp>
</components><nets>
<net code="1" name="GND"><node ref="D1" pin="1" pinfunction="K" pintype="passive"/><node ref="J1" pin="2" pinfunction="Pin_2_2" pintype="passive"/></net>
<net code="2" name="Net-(D1-A)"><node ref="D1" pin="2" pinfunction="A" pintype="passive"/><node ref="R1" pin="2" pintype="passive"/></net>
<net code="3" name="+3V3"><node ref="R1" pin="1" pintype="passive"/><node ref="J1" pin="1" pinfunction="Pin_1_1" pintype="passive"/></net>
</nets></export>'''


def pads(pcb):
    out = {}
    for fp in Board.load(pcb).footprints():
        for p in fp.pads():
            g = lambda h: str(p.get(h)) if p.get(h) is not None else None
            out[(fp.ref, str(p[1]))] = (str(p.find('net')[1]) if p.find('net') is not None else None, g('pinfunction'), g('pintype'))
    return out


def test_pads_carry_pin_names_and_types():
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'net.xml'), 'w').write(NETLIST)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'new_board.py'), os.path.join(d, 'net.xml'), os.path.join(d, 't.kicad_pcb')],
                       capture_output=True, text=True)
    if r.returncode and 'footprint' in r.stderr:
        print('skip: no KiCad footprint library (%s)' % r.stderr.strip()); return
    assert r.returncode == 0, r.stderr
    P = pads(os.path.join(d, 't.kicad_pcb'))
    assert P[('D1', '1')] == ('GND', 'K', 'passive') and P[('D1', '2')] == ('Net-(D1-A)', 'A', 'passive'), P
    assert P[('R1', '1')] == ('+3V3', None, 'passive'), P                        # unnamed pin: no pinfunction
    assert P[('J1', '1')] == ('+3V3', 'Pin_1_1', 'passive'), P                   # KiCad's suffixed name, verbatim
    text = open(os.path.join(d, 't.kicad_pcb')).read()
    assert text.count('(pinfunction "K")') == 1 and text.count('(pintype "passive")') == 6, text.count('(pintype')


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
