"""schgen T-taps:  python3 tests/test_schgen_taps.py
A shunt part's pin on the interior of a rail wire (the ladder layout) is a collision until declared with s.tap();
then it is not reported, the written sheet has a junction there, and a tap that touches no wire is reported."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import symgen
from schgen import Sch
from kicad_sexpr import load


def sheet():
    s = Sch('t', paper='A4')
    r = symgen.ic('R', 2.54, left=[('~', ['1'], symgen.PA)], right=[('~', ['2'], symgen.PA)], ref='R',
                  datasheet='https://example.com/r.pdf')
    s.lib('P', lib=symgen.library({'R': r}))
    c1 = s.add('P:R', 'R1', '10k', 50.8, 50.8, footprint='Resistor_SMD:R_0402_1005Metric')
    x, y = c1.p(1)
    s.wire((x, y - 7.62), (x, y + 7.62))                   # the rail passes straight through R1's pin 1
    return s, (x, y)


def test_declared_tap_is_not_a_collision():
    s, pt = sheet()
    assert any('pin R1.1' in m for m in s.collisions()), s.collisions()
    s.tap(pt)
    assert not s.collisions(), s.collisions()
    out = os.path.join(tempfile.mkdtemp(), 't.kicad_sch')
    s.write(out)
    js = [(j.need('at').number(1), j.need('at').number(2)) for j in load(out).nodes('junction')]
    assert any(abs(a - pt[0]) < 1e-6 and abs(b - pt[1]) < 1e-6 for a, b in js), (js, pt)


def test_tap_off_every_wire_is_reported():
    s, (x, y) = sheet()
    s.tap((x, y), (x + 25.4, y))
    assert s.collisions() == ['tap at %s touches no wire' % ((x + 25.4, y),)], s.collisions()


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
