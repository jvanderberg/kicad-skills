"""new_board.py --labels: one label for a footprint, or one per pad at the pad's centre + offset (a header's pins),
from a hand-written netlist with a KiCad library header (skipped without KiCad's footprints):
  python3 tests/test_new_board_labels.py"""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from kicad_sexpr import load

NETLIST = '''<export version="E"><components>
<comp ref="J3"><value>UART</value><footprint>Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical</footprint>
<sheetpath names="/" tstamps="/"/><tstamps>00000000-0000-0000-0000-000000000003</tstamps></comp>
<comp ref="J4"><value>PWR</value><footprint>Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical</footprint>
<sheetpath names="/" tstamps="/"/><tstamps>00000000-0000-0000-0000-000000000004</tstamps></comp>
</components><nets><net code="1" name="GND"><node ref="J3" pin="1"/><node ref="J4" pin="2"/></net></nets></export>
'''


def build(labels):
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'net.xml'), 'w').write(NETLIST)
    json.dump({'J3': [5.0, 5.0, 90], 'J4': [15.0, 5.0, 0]}, open(os.path.join(d, 'place.json'), 'w'))
    json.dump(labels, open(os.path.join(d, 'labels.json'), 'w'))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'new_board.py'), os.path.join(d, 'net.xml'), os.path.join(d, 't.kicad_pcb'),
                        '--origin', '100,100', '--placement', os.path.join(d, 'place.json'), '--labels', os.path.join(d, 'labels.json')],
                       capture_output=True, text=True)
    return r, os.path.join(d, 't.kicad_pcb')


def test_label_per_pad():
    r, pcb = build({'J3': {'pads': {'1': 'GND', '2': 'TX', '3': 'RX'}, 'dy': 2.0, 'size': 0.8, 'sides': 'F'},
                    'J4': ['PWR', 0, -3]})
    if r.returncode and 'footprint' in r.stderr:
        print('skip: no KiCad footprint library (%s)' % r.stderr.strip()); return
    assert r.returncode == 0, r.stderr
    texts = {}
    for t in load(pcb).nodes('gr_text'):
        texts.setdefault(str(t[1]), []).append((t.need('at').number(1), t.need('at').number(2), str(t.need('layer')[1])))
    # each label 2 mm below its pad's centre on the placed, rotated header, on F.SilkS only
    from kicad_sexpr import Board
    fp = Board.load(pcb).footprint('J3')
    for num, name in (('1', 'GND'), ('2', 'TX'), ('3', 'RX')):
        x, y = fp.pad_position(num)
        assert texts[name] == [(x, y + 2.0, 'F.SilkS')], (name, texts[name], (x, y))
    assert sorted(l for *_, l in texts['PWR']) == ['B.SilkS', 'F.SilkS'], texts['PWR']     # the one-label form: both sides
    r, _ = build({'J3': {'pads': {'9': 'X'}}})
    assert r.returncode == 1 and 'no pad 9' in r.stderr, r.stderr
    r, _ = build({'J3': {'pins': {'1': 'X'}}})
    assert r.returncode == 1 and 'unknown keys: pins' in r.stderr, r.stderr


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
