"""board_lint.py SILK OUTLINE on footprints without a courtyard (needs KiCad's python and footprint library):
    python3 tests/test_board_lint_outline.py
An EasyEDA footprint has no courtyard, so its silkscreen outline is its placement boundary. DRC's silk_overlap sees
only crossing lines: a part sitting wholly inside another's outline passes it. board_lint reports any overlap of the
outline-and-pads rectangles; a pin-1 dot outside the outline does not count, and a part whose outline was removed
(placed tighter on purpose) is checked by its pads and listed as spaced by rule of thumb."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from kicad_sexpr import Board, Node, Sym, new_footprint, save

FPLIB = next((d for d in ('/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints', '/usr/share/kicad/footprints')
              if os.path.isdir(d)), None)
KICAD_PYTHON = next((c for c in (os.environ.get('KICAD_PYTHON', ''),
                                 '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3')
                     if c and os.path.exists(c)), None)


def easyeda(d, name, half_w, half_h, pads, outline=True, dot=None):
    """a footprint as JLCImport writes one: pads, an F.SilkS outline (no courtyard), optionally a pin-1 dot"""
    fp = new_footprint(name)
    if outline:
        c = [(-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h)]
        for (x0, y0), (x1, y1) in zip(c, c[1:] + c[:1]):
            fp.append(Node('fp_line', Node('start', x0, y0), Node('end', x1, y1),
                           Node('stroke', Node('width', 0.15), Node('type', Sym('solid'))), Node('layer', 'F.SilkS')))
    if dot:
        fp.append(Node('fp_circle', Node('center', *dot), Node('end', dot[0] + 0.15, dot[1]),
                       Node('stroke', Node('width', 0.15), Node('type', Sym('solid'))), Node('fill', Sym('solid')),
                       Node('layer', 'F.SilkS')))
    for n, (x, y, w, h) in enumerate(pads, 1):
        fp.append(Node('pad', str(n), Sym('smd'), Sym('rect'), Node('at', x, y), Node('size', w, h),
                       Node('layers', 'F.Cu', 'F.Mask', 'F.Paste')))
    p = os.path.join(d, name + '.kicad_mod')
    save(fp, p)
    return p


def test_silk_outline_overlaps():
    if not (FPLIB and KICAD_PYTHON):
        print('  (skipped: no KiCad python / footprint library)'); return
    d = tempfile.mkdtemp()
    big = easyeda(d, 'BIG', 3.0, 3.0, [(x, y, 0.6, 0.6) for x in (-2.5, 2.5) for y in (-2.5, 2.5)], dot=(3.35, -2.5))
    chip = easyeda(d, 'CHIP', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])
    bare = easyeda(d, 'CHIP_BARE', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)], outline=False)
    r0603 = os.path.join(FPLIB, 'Resistor_SMD.pretty', 'R_0603_1608Metric.kicad_mod')
    b = Board.new(copper_layers=2)
    b.add_footprint(big, 'T:BIG', 'U1', 'X', (100, 100))
    b.add_footprint(chip, 'T:CHIP', 'C1', '1u', (100, 100))          # wholly inside U1's outline: no line crosses
    b.add_footprint(chip, 'T:CHIP', 'C2', '1u', (104.5, 97.5))       # clear of U1's outline, beside its pin-1 dot
    b.add_footprint(r0603, 'Resistor_SMD:R_0603_1608Metric', 'R1', '1k', (106.6, 97.5))   # courtyard on C2's outline
    b.add_footprint(bare, 'T:CHIP_BARE', 'C3', '1u', (100, 104.0))   # outline removed: pads 0.7 mm from U1's outline
    b.add_footprint(r0603, 'Resistor_SMD:R_0603_1608Metric', 'R2', '1k', (120, 100))
    b.add_footprint(r0603, 'Resistor_SMD:R_0603_1608Metric', 'R3', '1k', (120.5, 100))    # two courtyards: DRC's
    pcb = os.path.join(d, 'o.kicad_pcb'); b.save(pcb)
    r = subprocess.run([KICAD_PYTHON, os.path.join(HERE, 'board_lint.py'), pcb, '--no-models', '--no-silk', '--no-paste',
                        '--no-via-in-pad', '--no-hardware'], capture_output=True, text=True)
    lines = r.stdout.splitlines()
    so = [l for l in lines if l.startswith('SILK OUTLINE')]
    pairs = {tuple(l.split()[2:5:2]) for l in so}
    assert pairs == {('U1', 'C1'), ('C2', 'R1')}, r.stdout + r.stderr
    assert any('R1 by its courtyard' in l for l in so), r.stdout
    assert any(l.startswith('NOTE') and 'no silk outline' in l and l.endswith(': C3') for l in lines), r.stdout
    assert r.returncode == 1 and '2 problem(s)' in r.stdout, r.stdout
    r = subprocess.run([KICAD_PYTHON, os.path.join(HERE, 'board_lint.py'), pcb, '--no-models', '--no-silk', '--no-paste',
                        '--no-via-in-pad', '--no-hardware', '--no-courtyard'], capture_output=True, text=True)
    assert 'SILK OUTLINE' not in r.stdout and r.returncode == 0, r.stdout


def test_strip_outline_keeps_marks():
    """strip_outline.py removes the outline and keeps the pin-1 dot and a cathode bar drawn inside the outline; the
    copy keeps its file and footprint name (JLCImport's production export knows JLC's footprint by name)"""
    d = tempfile.mkdtemp()
    src = os.path.join(d, 'JLCImport.pretty'); os.makedirs(src)
    p = easyeda(src, 'DIODE', 1.5, 0.8, [(-1.2, 0, 0.6, 0.8), (1.2, 0, 0.6, 0.8)], dot=(-2.0, 0.6))
    from kicad_sexpr import load
    fp = load(p)
    fp.append(Node('fp_line', Node('start', -0.3, -0.5), Node('end', -0.3, 0.5),        # cathode bar, inside
                   Node('stroke', Node('width', 0.15), Node('type', Sym('solid'))), Node('layer', 'F.SilkS')))
    save(fp, p)
    out = os.path.join(d, 'NoOutline.pretty')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'strip_outline.py'), p, '--to', out], capture_output=True, text=True)
    assert r.returncode == 0 and '4 outline shape(s) removed, 2 mark(s)' in r.stdout, r.stdout + r.stderr
    q = load(os.path.join(out, 'DIODE.kicad_mod'))
    assert str(q[1]) == 'DIODE', q[1]
    silk = [g for g in q.nodes() if g.head.startswith('fp_') and g.find('layer') is not None and g.find('layer')[1] == 'F.SilkS']
    assert sorted(g.head for g in silk) == ['fp_circle', 'fp_line'], [g.head for g in silk]
    assert len(q.nodes('pad')) == 2
    r = subprocess.run([sys.executable, os.path.join(HERE, 'strip_outline.py'), p, '--to', src], capture_output=True, text=True)
    assert r.returncode != 0 and 'separate library' in r.stderr, r.stdout + r.stderr


if __name__ == '__main__':
    fails = 0
    for k, fn in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                fn(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
