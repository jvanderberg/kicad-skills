"""new_board.py --labels: one label for a footprint (list form, or the dict form with size and sides), one per pad at
the pad's centre + offset (a header's pins), and free texts at board positions ("_texts"), from a hand-written
netlist with a KiCad library header (skipped without KiCad's footprints):
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


def build(labels, d=None, previous=None):
    d = d or tempfile.mkdtemp()
    open(os.path.join(d, 'net.xml'), 'w').write(NETLIST)
    json.dump({'J3': [5.0, 5.0, 90], 'J4': [15.0, 5.0, 0]}, open(os.path.join(d, 'place.json'), 'w'))
    json.dump(labels, open(os.path.join(d, 'labels.json'), 'w'))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'new_board.py'), os.path.join(d, 'net.xml'), os.path.join(d, 't.kicad_pcb'),
                        '--origin', '100,100', '--placement', os.path.join(d, 'place.json'), '--labels', os.path.join(d, 'labels.json')]
                       + (['--previous', previous] if previous else []), capture_output=True, text=True)
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



def texts_of(pcb):
    """{text: [(x, y, layer, height, mirrored, angle)]} of the board's gr_text items"""
    out = {}
    for t in load(pcb).nodes('gr_text'):
        at, eff = t.need('at'), t.need('effects')
        j = eff.find('justify')
        out.setdefault(str(t[1]), []).append((at.number(1), at.number(2), str(t.need('layer')[1]),
                                              eff.need('font').need('size').number(1),
                                              j is not None and 'mirror' in [str(v) for v in j[1:]], at.number(3, 0.0)))
    return out


def test_label_options_and_free_texts():
    labels = {'J4': {'text': 'PWR', 'dx': 0, 'dy': -3, 'size': 0.8, 'sides': 'F'},
              'J3': ['UART', 0, 4, 90],
              '_texts': [{'text': 'VIO: 1 SHUNT', 'at': [12.5, 9], 'rot': 90, 'size': 1.2},
                         {'text': 'rev 1', 'at': [2, 3], 'sides': 'B'}]}
    r, pcb = build(labels)
    if r.returncode and 'footprint' in r.stderr:
        print('skip: no KiCad footprint library (%s)' % r.stderr.strip()); return
    assert r.returncode == 0, r.stderr
    t = texts_of(pcb)
    # the per-footprint dict form: its size and side, at the footprint + (dx, dy), reference hidden as the list form does
    assert t['PWR'] == [(115.0, 102.0, 'F.SilkS', 0.8, False, 0.0)], t['PWR']
    from kicad_sexpr import Board
    assert Board.load(pcb).footprint('J4').field('Reference').find('hide') is not None
    # the list form unchanged: 1.0 mm on both sides, mirrored on the bottom
    assert sorted(t['UART']) == [(105.0, 109.0, 'B.SilkS', 1.0, True, 90.0), (105.0, 109.0, 'F.SilkS', 1.0, False, 90.0)], t['UART']
    # free texts: at --origin + "at", both sides by default, or only the bottom (mirrored)
    assert sorted(t['VIO: 1 SHUNT']) == [(112.5, 109.0, 'B.SilkS', 1.2, True, 90.0),
                                         (112.5, 109.0, 'F.SilkS', 1.2, False, 90.0)], t['VIO: 1 SHUNT']
    assert t['rev 1'] == [(102.0, 103.0, 'B.SilkS', 1.0, True, 0.0)], t['rev 1']
    # text under 1 mm is written with a note, not refused
    assert 'note: --labels text under 1.0 mm' in r.stdout and 'J4 0.80 mm' in r.stdout, r.stdout
    # deterministic: regenerating over the board, or from scratch elsewhere, gives the same bytes
    first = open(pcb).read()
    r2, pcb2 = build(labels, d=os.path.dirname(pcb))
    assert r2.returncode == 0 and open(pcb2).read() == first, r2.stderr
    r3, pcb3 = build(labels, previous='none')
    assert r3.returncode == 0 and open(pcb3).read() == first, r3.stderr


def test_label_errors():
    for labels, msg in (({'J4': ['PWR', 0, -3, 0, 0.8]}, 'for a size or side use {"text"'),
                        ({'J4': {'text': 'PWR', 'sides': 'T'}}, '"sides" is "F", "B" or "FB"'),
                        ({'J4': {'text': 'PWR', 'size': 0}}, '"size" is the text height'),
                        ({'J4': {'text': 'PWR', 'side': 'F'}}, 'unknown keys: side'),
                        ({'_texts': [{'text': 'X', 'at': [1]}]}, '_texts[0]: expected {"text"'),
                        ({'_texts': {'text': 'X'}}, '_texts: expected a list'),
                        ({'J9': ['X', 0, 0]}, 'no footprint J9')):
        r, _ = build(labels)
        if r.returncode and ('fp-lib-table' in r.stderr or 'not found (' in r.stderr):
            print('skip: no KiCad footprint library (%s)' % r.stderr.strip()); return
        assert r.returncode == 1 and msg in r.stderr, (labels, r.stderr)


def test_label_wrong_types_are_clean_errors():
    """a wrong JSON type anywhere in --labels is a message and exit 1, never a traceback"""
    cases = (
        ({'_texts': [['X', 1, 2]]}, '_texts[0]: expected {"text"'),         # was TypeError in sorted()
        ({'_texts': ['X']}, '_texts[0]: expected {"text"'),                 # was "unknown keys: X"
        ({'_texts': [{'text': 5, 'at': [1, 2]}]}, '_texts[0]: expected {"text"'),
        ({'_texts': [{'text': 'X', 'at': [1, '2']}]}, '_texts[0]: expected {"text"'),
        ({'_texts': [{'text': 'X', 'at': [True, 2]}]}, '_texts[0]: expected {"text"'),
        ({'_texts': [{'text': 'X', 'at': [1, 2], 'rot': '90'}]}, '_texts[0]: "rot" is a number (degrees), not "90"'),
        ({'_texts': [{'text': 'X', 'at': [1, 2], 'size': '1'}]}, '_texts[0]: "size" is the text height'),
        ({'_texts': [{'text': 'X', 'at': [1, 2], 'sides': ['F']}]}, '_texts[0]: "sides" is "F", "B" or "FB"'),
        ({'J4': {'text': 'A', 'dx': '1'}}, 'J4: "dx" is a number (mm), not "1"'),   # was TypeError in fp.at[0] + '1'
        ({'J4': {'text': 'A', 'dy': None}}, 'J4: "dy" is a number (mm), not null'),
        ({'J4': {'text': 'A', 'rot': [90]}}, 'J4: "rot" is a number (degrees)'),
        ({'J4': {'text': 'A', 'size': True}}, 'J4: "size" is the text height'),
        ({'J4': {'text': 7}}, 'J4: expected {"text"'),
        ({'J3': {'pads': {'1': 'GND'}, 'dx': '0'}}, 'J3: "dx" is a number (mm)'),
        ({'J3': {'pads': {'1': 'GND'}, 'rot': 'up'}}, 'J3: "rot" is a number (degrees)'),
        ({'J3': {'pads': {'1': 'GND'}, 'sides': 'X'}}, 'J3: "sides" is "F", "B" or "FB"'),
        ({'J3': {'pads': {'1': 'GND'}, 'size': -1}}, 'J3: "size" is the text height'),
        ({'J3': {'pads': {'1': 3}}}, "J3: pad 1's label is a string, not 3"),
        ({'J3': {'pads': ['GND']}}, 'J3: expected {"pads"'),
        ({'J4': ['PWR', '0', -3]}, 'J4: expected ["TEXT", dx, dy]'),
        ({'J4': ['PWR', 0, -3, '90']}, 'J4: expected ["TEXT", dx, dy]'),
        ({'J4': [5, 0, -3]}, 'J4: expected ["TEXT", dx, dy]'),
        ({'J4': 'PWR'}, 'J4: expected ["TEXT", dx, dy]'),
        (['J4', 'PWR'], '--labels: expected an object'),
    )
    for labels, msg in cases:
        r, _ = build(labels)
        if r.returncode and ('fp-lib-table' in r.stderr or 'not found (' in r.stderr):
            print('skip: no KiCad footprint library (%s)' % r.stderr.strip()); return
        assert r.returncode == 1 and 'Traceback' not in r.stderr and msg in r.stderr, (labels, r.stderr)


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
