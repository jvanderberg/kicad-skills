"""fpcheck.py --pads on custom pads: the copper extent (anchor + primitives), not the anchor's (size ...), marked
custom:  python3 tests/test_fpcheck_custom_pads.py"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fpcheck import pads
from kicad_sexpr import Node, Sym, load, new_footprint, save

# TYPE-C-31-M-12 (LCSC C165948) as JLCImport writes it, header and pads verbatim (other graphics left out): VBUS/GND
# are custom pads, a 0.1 mm anchor + a 0.6 x 1.3 mm polygon
TYPE_C = '''(footprint "TYPE-C-31-M-12"
  (version 20241229)
  (generator "JLCImport")
  (generator_version "1.0")
  (layer "F.Cu")
  (descr "TYPE-C-31-M-12; USB-C_SMD-TYPE-C-31-M-12_1")
  (attr smd)
  (pad "A5" smd rect (at -1.25 -2.474) (size 0.3 1.3) (layers "F.Cu" "F.Mask" "F.Paste") (uuid "c39a5621-7b4a-4f65-85a9-f7cfdf1a55a4"))
  (pad "A4B9" smd custom (at -2.4 -2.474) (size 0.1 0.1)
    (layers "F.Cu" "F.Mask" "F.Paste")
    (options (clearance outline) (anchor rect))
    (primitives
      (gr_poly (pts (xy 0.3 0.65) (xy 0.3 -0.65) (xy 0.3 -0.65) (xy 0 -0.65) (xy 0 -0.65) (xy 0 -0.65) (xy 0 -0.65) (xy -0.3 -0.65) (xy -0.3 -0.65) (xy -0.3 0.65) (xy -0.3 0.65) (xy 0.000127 0.65) (xy 0.000127 0.65) (xy 0.000127 0.65) (xy 0.000127 0.65) (xy 0.3 0.65)) (width 0) (fill yes))
    ) (uuid "fe0efe52-0848-4e88-969f-b924c7a56812"))
  (pad "" np_thru_hole circle (at -2.9 -1.205611) (size 0.6 0.6) (drill 0.6) (layers "*.Cu" "*.Mask") (uuid "316f0458-0e0c-4c81-b0f1-e8e1b03ad615"))
)
'''


def run(path, *args):
    return subprocess.run([sys.executable, os.path.join(HERE, 'fpcheck.py'), path, '--pads'] + list(args),
                          capture_output=True, text=True)


def line_of(out, num):
    return next(l for l in out.splitlines() if l.split()[:2] == ['pad', num])


def test_type_c_custom_pads():
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'TYPE-C-31-M-12.kicad_mod')
    open(p, 'w').write(TYPE_C)
    r = run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    vbus = line_of(r.stdout, 'A4B9')
    assert '( -2.400,  -2.474)  0.60 x 1.30' in vbus and 'custom: anchor 0.10 x 0.10' in vbus, vbus
    assert 'from the anchor' not in vbus, vbus                     # the polygon is centred on the anchor
    plain = line_of(r.stdout, 'A5')
    assert '0.30 x 1.30' in plain and 'custom' not in plain, plain


def test_synthetic_custom_pad():
    """an anchor with an off-centre polygon, a stroked line, a circle and an arc: the extent is their union (strokes
    included), its centre offset from the anchor is printed, and the pad span note uses the extent, rotated"""
    fp = new_footprint('X_CUSTOM', descr='test')
    prims = lambda: Node('primitives',
                 Node('gr_poly', Node('pts', Node('xy', 0, -0.2), Node('xy', 1.0, -0.2), Node('xy', 1.0, 0.2),
                                      Node('xy', 0, 0.2)), Node('width', 0), Node('fill', Sym('yes'))),
                 Node('gr_line', Node('start', 0, 0), Node('end', 0, 0.8), Node('width', 0.2)),   # y to 0.9 with stroke
                 Node('gr_circle', Node('center', -0.5, 0), Node('end', -0.3, 0), Node('width', 0), Node('fill', Sym('yes'))),
                 # half circle of radius 0.5 round (0, 0) through (0, -0.5): its top reaches y = -0.5 (not a corner)
                 Node('gr_arc', Node('start', -0.5, 0), Node('mid', 0, -0.5), Node('end', 0.5, 0), Node('width', 0)))
    fp.append(Node('pad', '1', Sym('smd'), Sym('custom'), Node('at', 0, 0), Node('size', 0.2, 0.2),
                   Node('layers', 'F.Cu', 'F.Mask', 'F.Paste'),
                   Node('options', Node('clearance', Sym('outline')), Node('anchor', Sym('rect'))), prims()))
    fp.append(Node('pad', '2', Sym('smd'), Sym('custom'), Node('at', 5, 0, 90), Node('size', 0.2, 0.2),
                   Node('layers', 'F.Cu', 'F.Mask', 'F.Paste'),
                   Node('options', Node('clearance', Sym('outline')), Node('anchor', Sym('rect'))), prims()))
    d = tempfile.mkdtemp()
    path = os.path.join(d, 'X_CUSTOM.kicad_mod')
    save(fp, path)
    # extent: x from -0.7 (circle) to 1.0 (polygon), y from -0.5 (arc top) to 0.9 (line + half its stroke)
    p1 = next(p for p in pads(load(path)) if p.number == '1')
    assert (round(p1.w, 3), round(p1.h, 3), round(p1.dx, 3), round(p1.dy, 3)) == (1.7, 1.4, 0.15, 0.2), p1
    assert (p1.anchor_w, p1.anchor_h, p1.shape) == (0.2, 0.2, 'custom'), p1
    r = run(path, '--package', 'X(6x2)')
    assert r.returncode == 0, r.stdout + r.stderr
    l1 = line_of(r.stdout, '1')
    assert '1.70 x 1.40' in l1 and 'custom: anchor 0.20 x 0.20' in l1 and '(+0.150, +0.200) from the anchor' in l1, l1
    # span: pad 1 x -0.7 .. 1.0; pad 2 at x 5 turned 90 deg (y -> -x): x 5 - 0.5 .. 5 + 0.9 = 5.9, so 6.60 wide;
    # y: pad 1 -0.5 .. 0.9, pad 2 -1.0 .. 0.7 -> 1.90 high
    assert 'pads span 6.60 x 1.90 mm' in r.stdout, r.stdout


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
