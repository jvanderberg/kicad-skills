"""board_lint.py SILK OUTLINE on footprints without a courtyard (needs KiCad's python and footprint library):
    python3 tests/test_board_lint_outline.py
An EasyEDA footprint has no courtyard, so its silkscreen outline is its placement boundary. DRC's silk_overlap sees
only crossing lines: a part sitting wholly inside another's outline passes it. board_lint reports any overlap of the
outline-and-pads rectangles; a pin-1 dot outside the outline does not count, and a part whose outline was removed
(placed tighter on purpose) is checked by its body and pads and listed as spaced by rule of thumb, even when
strip_outline.py kept its cathode bar (known by the property strip_outline writes). A part without an outline is still
checked by its F.Fab body (BODY OVERLAP), and courtyards are read per footprint, not per reference (two REF**).
A silk text box is not outline, and a mark on a rotated part is measured in the footprint's own frame (as
strip_outline.py measures it). strip_outline.py refuses to overwrite its input (case-different or linked --to),
same-named inputs, and a different footprint of the same name left in --to by an earlier run."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from kicad_sexpr import Board, Node, Sym, new_footprint, save

FPLIB = next((d for d in ('/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints', '/usr/share/kicad/footprints')
              if os.path.isdir(d)), None)
KICAD_PYTHON = next((c for c in (os.environ.get('KICAD_PYTHON', ''),
                                 '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3')
                     if c and os.path.exists(c)), None)


def _box(fp, half_w, half_h, layer):
    c = [(-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h)]
    for (x0, y0), (x1, y1) in zip(c, c[1:] + c[:1]):
        fp.append(Node('fp_line', Node('start', x0, y0), Node('end', x1, y1),
                       Node('stroke', Node('width', 0.15 if layer == 'F.SilkS' else 0.1), Node('type', Sym('solid'))),
                       Node('layer', layer)))


def easyeda(d, name, half_w, half_h, pads, outline=True, dot=None, fab=None, bar=None):
    """a footprint as JLCImport writes one: pads, an F.SilkS outline (no courtyard), optionally a pin-1 dot, an F.Fab
    body (half width, half height) and a cathode bar inside the outline (x, half length)"""
    fp = new_footprint(name)
    if outline:
        _box(fp, half_w, half_h, 'F.SilkS')
    if fab:
        _box(fp, fab[0], fab[1], 'F.Fab')
    if bar:
        fp.append(Node('fp_line', Node('start', bar[0], -bar[1]), Node('end', bar[0], bar[1]),
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


def lint(pcb):
    r = subprocess.run([KICAD_PYTHON, os.path.join(HERE, 'board_lint.py'), pcb, '--no-models', '--no-silk', '--no-paste',
                        '--no-via-in-pad', '--no-hardware'], capture_output=True, text=True)
    return r, r.stdout.splitlines()


def pairs_of(lines, kind):
    return {tuple(l.split()[2:5:2]) for l in lines if l.startswith(kind)}


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
    assert '(property "Silk outline" "removed by strip_outline.py"' in open(os.path.join(out, 'DIODE.kicad_mod')).read()


def _strip(*args):
    return subprocess.run([sys.executable, os.path.join(HERE, 'strip_outline.py')] + list(args), capture_output=True, text=True)


def test_strip_outline_never_overwrites_its_input():
    """--to naming the source library another way (other case on a case-insensitive disk, a link) is refused and the
    original is left as it was"""
    d = tempfile.mkdtemp()
    src = os.path.join(d, 'JLCImport.pretty'); os.makedirs(src)
    p = easyeda(src, 'CHIP', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])
    before = open(p).read()
    other = os.path.join(d, 'jlcimport.pretty')
    insensitive = os.path.exists(other)
    r = _strip(p, '--to', other)
    if insensitive:                                       # macOS / Windows default: the same folder
        assert r.returncode != 0 and 'separate library' in r.stderr, r.stdout + r.stderr
    else:
        assert r.returncode == 0, r.stdout + r.stderr
    assert open(p).read() == before
    link = os.path.join(d, 'Link.pretty'); os.symlink(src, link)
    r = _strip(p, '--to', link)
    assert r.returncode != 0 and 'separate library' in r.stderr, r.stdout + r.stderr
    assert open(p).read() == before


def test_strip_outline_refuses_same_named_inputs():
    """two inputs with one file name from different libraries would write the same output: refused, nothing written"""
    d = tempfile.mkdtemp()
    a, b = os.path.join(d, 'A.pretty'), os.path.join(d, 'B.pretty'); os.makedirs(a); os.makedirs(b)
    pa = easyeda(a, 'CHIP', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])
    pb = easyeda(b, 'CHIP', 2.0, 0.5, [(-1.5, 0, 0.5, 0.5), (1.5, 0, 0.5, 0.5)])
    out = os.path.join(d, 'NoOutline.pretty')
    r = _strip(pa, pb, '--to', out)
    assert r.returncode != 0 and 'both be written' in r.stderr, r.stdout + r.stderr
    assert not os.path.exists(os.path.join(out, 'CHIP.kicad_mod'))
    r = _strip(pa, pa, '--to', out)                       # the same file twice is one copy
    assert r.returncode == 0 and r.stdout.count('wrote') == 1, r.stdout + r.stderr


def test_strip_outline_refuses_cross_run_overwrite():
    """a later run from another library must not replace a different footprint of the same name in the destination
    (every part set to NoOutline:CHIP would get its pads); running again on the same footprint rewrites the same file"""
    d = tempfile.mkdtemp()
    a, b = os.path.join(d, 'A.pretty'), os.path.join(d, 'B.pretty'); os.makedirs(a); os.makedirs(b)
    pa = easyeda(a, 'CHIP', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])
    pb = easyeda(b, 'CHIP', 2.0, 0.5, [(-1.5, 0, 0.5, 0.5), (1.5, 0, 0.5, 0.5)])
    out = os.path.join(d, 'NoOutline.pretty')
    copy = os.path.join(out, 'CHIP.kicad_mod')
    r = _strip(pa, '--to', out)
    assert r.returncode == 0, r.stdout + r.stderr
    first = open(copy).read()
    for args in ((pb, '--to', out), (pb, '--to', out, '--dry-run')):
        r = _strip(*args)
        assert r.returncode != 0 and 'pads differ' in r.stderr and 'separate library' in r.stderr, r.stdout + r.stderr
        assert open(copy).read() == first
    r = _strip(pa, '--to', out)                           # the same source again: allowed, same file
    assert r.returncode == 0 and open(copy).read() == first, r.stdout + r.stderr
    c = os.path.join(d, 'C.pretty'); os.makedirs(c)       # same pads, other silk (an identical land pattern): allowed
    pc = easyeda(c, 'CHIP', 1.2, 0.6, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])
    assert _strip(pc, '--to', out).returncode == 0
    hand = easyeda(out, 'HAND', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])   # not a strip_outline copy
    before = open(hand).read()
    src = easyeda(a, 'HAND', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])
    r = _strip(src, '--to', out)
    assert r.returncode != 0 and 'not a strip_outline.py copy' in r.stderr, r.stdout + r.stderr
    assert open(hand).read() == before


def test_silk_text_box_is_not_outline():
    """a silk text box (PCB_TEXTBOX derives from PCB_SHAPE in KiCad 10) is text, not outline: it does not enlarge the
    part's area, as strip_outline.py leaves fp_text_box alone"""
    if not (FPLIB and KICAD_PYTHON):
        print('  (skipped: no KiCad python / footprint library)'); return
    from kicad_sexpr import load
    d = tempfile.mkdtemp()
    p = easyeda(d, 'CHIP_TB', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])
    fp = load(p)
    fp.append(Node('fp_text_box', 'note', Node('start', -1.0, 2.0), Node('end', 1.0, 4.0),
                   Node('margins', 0.25, 0.25, 0.25, 0.25), Node('layer', 'F.SilkS'),
                   Node('effects', Node('font', Node('size', 0.4, 0.4), Node('thickness', 0.1))),
                   Node('border', Sym('yes')), Node('stroke', Node('width', 0.1), Node('type', Sym('solid')))))
    save(fp, p)
    bare = easyeda(d, 'CHIP_BARE', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)], outline=False)
    b = Board.new(copper_layers=2)
    b.add_footprint(p, 'T:CHIP_TB', 'U1', 'X', (100, 100))
    b.add_footprint(bare, 'T:CHIP_BARE', 'C1', '1u', (100, 103))     # under U1's text box, clear of its outline
    pcb = os.path.join(d, 't.kicad_pcb'); b.save(pcb)
    r, lines = lint(pcb)
    assert any('silk outline checked' in l and l.endswith(': U1') for l in lines), r.stdout + r.stderr  # it loaded
    assert not any(l.startswith(('SILK OUTLINE', 'BODY OVERLAP')) for l in lines), r.stdout + r.stderr
    assert r.returncode == 0, r.stdout
    out = os.path.join(d, 'NoOutline.pretty')
    r = _strip(p, '--to', out)
    assert r.returncode == 0 and '4 outline shape(s) removed' in r.stdout, r.stdout + r.stderr
    assert load(os.path.join(out, 'CHIP_TB.kicad_mod')).find('fp_text_box') is not None


def test_rotated_mark_is_still_a_mark():
    """a filled 0.8 mm square pin-1 mark on a part at 45 degrees is a mark (1.13 mm board bounding box, 0.8 mm in the
    footprint's own frame, where strip_outline.py measures it): a neighbour beside the mark is not a SILK OUTLINE"""
    if not (FPLIB and KICAD_PYTHON):
        print('  (skipped: no KiCad python / footprint library)'); return
    from kicad_sexpr import load
    d = tempfile.mkdtemp()
    p = easyeda(d, 'CHIP_SQ', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])
    fp = load(p)
    fp.append(Node('fp_rect', Node('start', 2.65, -0.35), Node('end', 3.35, 0.35),   # 0.8 x 0.8 with its stroke
                   Node('stroke', Node('width', 0.1), Node('type', Sym('solid'))), Node('fill', Sym('solid')),
                   Node('layer', 'F.SilkS')))
    save(fp, p)
    bare = easyeda(d, 'CHIP_BARE', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)], outline=False)
    b = Board.new(copper_layers=2)
    b.add_footprint(p, 'T:CHIP_SQ', 'U1', 'X', (100, 100), angle=45)  # the mark lands at (102.12, 97.88)
    b.add_footprint(bare, 'T:CHIP_BARE', 'C1', '1u', (102.3, 99.0))   # just below the mark, clear of U1's outline
    pcb = os.path.join(d, 'r.kicad_pcb'); b.save(pcb)
    r, lines = lint(pcb)
    assert any('silk outline checked' in l and l.endswith(': U1') for l in lines), r.stdout + r.stderr
    assert not any(l.startswith(('SILK OUTLINE', 'BODY OVERLAP')) for l in lines), r.stdout + r.stderr
    assert r.returncode == 0, r.stdout
    r = _strip(p, '--to', os.path.join(d, 'NoOutline.pretty'))      # the same shape is a mark to strip_outline.py
    assert r.returncode == 0 and '4 outline shape(s) removed, 1 mark(s)' in r.stdout, r.stdout + r.stderr
    b = Board.new(copper_layers=2)                                    # and a 1.2 mm square is outline at 45 degrees too
    fp[-1] = Node('fp_rect', Node('start', 2.45, -0.55), Node('end', 3.55, 0.55),
                  Node('stroke', Node('width', 0.1), Node('type', Sym('solid'))), Node('fill', Sym('solid')),
                  Node('layer', 'F.SilkS'))
    save(fp, p)
    b.add_footprint(p, 'T:CHIP_SQ', 'U1', 'X', (100, 100), angle=45)
    b.add_footprint(bare, 'T:CHIP_BARE', 'C1', '1u', (102.3, 99.0))
    b.save(pcb)
    r, lines = lint(pcb)
    assert pairs_of(lines, 'SILK OUTLINE') == {('U1', 'C1')}, r.stdout + r.stderr


def test_duplicate_references():
    """two footprints with one reference (REF**): each is checked by its own courtyard / outline. Reading courtyards by
    reference gave the first REF** the second's courtyard (in board coordinates, far away), hiding its overlap"""
    if not (FPLIB and KICAD_PYTHON):
        print('  (skipped: no KiCad python / footprint library)'); return
    d = tempfile.mkdtemp()
    chip = easyeda(d, 'CHIP', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)])
    r0603 = os.path.join(FPLIB, 'Resistor_SMD.pretty', 'R_0603_1608Metric.kicad_mod')
    b = Board.new(copper_layers=2)
    b.add_footprint(chip, 'T:CHIP', 'REF**', '1u', (100, 100))                              # outline, no courtyard
    b.add_footprint(r0603, 'Resistor_SMD:R_0603_1608Metric', 'REF**', '1k', (130, 100))     # courtyard, far away
    b.add_footprint(chip, 'T:CHIP', 'C1', '1u', (100.8, 100))                               # on the first REF**
    pcb = os.path.join(d, 'dup.kicad_pcb'); b.save(pcb)
    r, lines = lint(pcb)
    assert pairs_of(lines, 'SILK OUTLINE') == {('REF**', 'C1')}, r.stdout + r.stderr
    assert r.returncode == 1, r.stdout


def test_stripped_part_keeps_inner_symbol_but_is_rule_of_thumb():
    """a strip_outline.py copy that kept its cathode bar is listed as spaced by rule of thumb, and its area is its body
    and pads, not the bar"""
    if not (FPLIB and KICAD_PYTHON):
        print('  (skipped: no KiCad python / footprint library)'); return
    d = tempfile.mkdtemp()
    src = os.path.join(d, 'JLCImport.pretty'); os.makedirs(src)
    p = easyeda(src, 'DIODE', 1.8, 1.2, [(-1.2, 0, 0.6, 0.8), (1.2, 0, 0.6, 0.8)], bar=(-0.3, 1.0))
    out = os.path.join(d, 'NoOutline.pretty')
    r = _strip(p, '--to', out)
    assert r.returncode == 0 and '4 outline shape(s) removed, 1 mark(s)' in r.stdout, r.stdout + r.stderr
    bare = easyeda(d, 'CHIP_BARE', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)], outline=False)
    b = Board.new(copper_layers=2)
    b.add_footprint(os.path.join(out, 'DIODE.kicad_mod'), 'NoOutline:DIODE', 'D1', 'D', (100, 100))
    b.add_footprint(bare, 'T:CHIP_BARE', 'C1', '1u', (99.7, 98.8))   # over the bar's end, clear of D1's pads
    pcb = os.path.join(d, 's.kicad_pcb'); b.save(pcb)
    r, lines = lint(pcb)
    assert not any(l.startswith(('SILK OUTLINE', 'BODY OVERLAP')) for l in lines), r.stdout + r.stderr
    rule = [l for l in lines if l.startswith('NOTE') and 'no silk outline' in l]
    assert rule and 'D1' in rule[0].split(': ')[-1].split(), r.stdout
    assert not any('silk outline checked' in l for l in lines), r.stdout
    assert r.returncode == 0, r.stdout


def test_bare_body_overhang():
    """a footprint with neither courtyard nor outline is checked by its F.Fab body too: a custom QFN whose body overhangs
    its pads onto a neighbour's pads is reported"""
    if not (FPLIB and KICAD_PYTHON):
        print('  (skipped: no KiCad python / footprint library)'); return
    d = tempfile.mkdtemp()
    qfn = easyeda(d, 'QFN_CUSTOM', 0, 0, [(x, y, 0.5, 0.5) for x in (-1.0, 1.0) for y in (-1.0, 1.0)], outline=False,
                  fab=(2.5, 2.5))                         # pads within 1.25 mm, body 2.5 mm each way
    bare = easyeda(d, 'CHIP_BARE', 1.0, 0.5, [(-0.5, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5)], outline=False)
    b = Board.new(copper_layers=2)
    b.add_footprint(qfn, 'T:QFN_CUSTOM', 'U1', 'X', (100, 100))
    b.add_footprint(bare, 'T:CHIP_BARE', 'C1', '1u', (102.0, 100))   # pads under U1's body, clear of its pads
    pcb = os.path.join(d, 'q.kicad_pcb'); b.save(pcb)
    r, lines = lint(pcb)
    assert pairs_of(lines, 'BODY OVERLAP') == {('U1', 'C1')}, r.stdout + r.stderr
    assert any(l.startswith('NOTE') and 'no silk outline' in l and l.endswith(': U1 C1') for l in lines), r.stdout
    assert r.returncode == 1, r.stdout


if __name__ == '__main__':
    fails = 0
    for k, fn in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                fn(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
