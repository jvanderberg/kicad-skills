"""paste_clear.py on a thermal-via exposed pad laid out like KiCad's QFN-24 _ThermalVias footprint (four 1.17 mm
paste windows at +-0.675 mm over a 3 x 3 grid of 0.2 mm drills at 1.1 mm pitch):  python3 tests/test_paste_clear.py
Every window ends up clear of every drill by the margin, the drills move to JLC's 0.3 mm tier with --drill, and the
paste coverage stays in the usual 40-60 %. With KiCad's library installed, the real footprint is checked too."""
import math, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fpcheck import fp_dir
from kicad_sexpr import Node, Sym, load, new_footprint, save
from paste_clear import _drill, _rect


def thermal_qfn():
    fp = new_footprint('QFN_TV', descr='test')
    fp.append(Node('pad', '25', Sym('smd'), Sym('rect'), Node('at', 0, 0), Node('size', 2.7, 2.7), Node('layers', 'F.Cu', 'F.Mask')))
    for x in (-0.675, 0.675):
        for y in (-0.675, 0.675):
            fp.append(Node('pad', '', Sym('smd'), Sym('roundrect'), Node('at', x, y), Node('size', 1.17, 1.17),
                           Node('layers', 'F.Paste'), Node('roundrect_rratio', 0.213675)))
    for x in (-1.1, 0, 1.1):
        for y in (-1.1, 0, 1.1):
            fp.append(Node('pad', '25', Sym('thru_hole'), Sym('circle'), Node('at', x, y), Node('size', 0.5, 0.5),
                           Node('drill', 0.2), Node('layers', '*.Cu')))
    return fp


def clear(path, drill, margin=0.05):
    fp = load(path)
    holes = [(p.need('at').number(1), p.need('at').number(2), _drill(p.need('drill')) / 2) for p in fp.nodes('pad') if p.find('drill')]
    assert holes and all(abs(2 * r - drill) < 1e-9 for _, _, r in holes), holes
    wins = [_rect(p) for p in fp.nodes('pad') if [str(v) for v in p.need('layers')[1:]] == ['F.Paste']]
    for w in wins:
        for x, y, r in holes:
            d = math.hypot(max(w[0] - x, 0, x - w[2]), max(w[1] - y, 0, y - w[3]))
            assert d >= r + margin - 1e-6, ('window', w, 'drill at', (x, y), d)
    return sum((w[2] - w[0]) * (w[3] - w[1]) for w in wins), len(wins)


def run(src, out, *args):
    return subprocess.run([sys.executable, os.path.join(HERE, 'paste_clear.py'), src, out, *args], capture_output=True, text=True)


def test_windows_clear_the_drills():
    d = tempfile.mkdtemp()
    src = os.path.join(d, 'QFN_TV.kicad_mod'); save(thermal_qfn(), src)
    out = os.path.join(d, 'lib.pretty', 'QFN_TV_Drill0.3.kicad_mod')
    r = run(src, out, '--drill', '0.3')
    assert r.returncode == 0 and 'PROBLEM' not in r.stdout, r.stdout + r.stderr
    area, n = clear(out, 0.3)
    assert n == 4 and 0.40 <= area / 2.7 ** 2 <= 0.60, (area, n)
    assert 'paste coverage 45 %' in r.stdout, r.stdout
    assert str(load(out)[1]) == 'QFN_TV_Drill0.3'
    r = run(src, out)                                            # drills left at 0.2 mm: windows still clear them
    assert r.returncode == 0, r.stdout + r.stderr
    clear(out, 0.2)


def test_kicad_thermalvias_footprint():
    lib = fp_dir()
    src = os.path.join(lib or '', 'Package_DFN_QFN.pretty', 'QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm_ThermalVias.kicad_mod')
    if not os.path.exists(src):
        print('skip: no KiCad footprint library'); return
    out = os.path.join(tempfile.mkdtemp(), 'QFN24.kicad_mod')
    r = run(src, out, '--drill', '0.3')
    assert r.returncode == 0, r.stdout + r.stderr
    area, n = clear(out, 0.3)
    assert n == 4 and 0.40 <= area / 2.7 ** 2 <= 0.60, (area, n)


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
