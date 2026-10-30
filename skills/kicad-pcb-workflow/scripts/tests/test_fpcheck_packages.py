"""fpcheck.py on EasyEDA footprints as JLCImport writes them:  python3 tests/test_fpcheck_packages.py
Package strings (LCSC's and EasyEDA's) give the lead count, not a family number; a footprint with no courtyard (most
EasyEDA ones) is a note, not a problem; filled F.Fab polarity marks are not a body outline."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fpcheck import parse_package
from kicad_sexpr import Node, Sym, new_footprint, save


def test_lead_counts():
    for s, leads in (('SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR', 3), ('SOT-23', None), ('SOD-123', None), ('SOT-223', None),
                     ('SOT-23-6L', 6), ('TSOT-23-6', 6), ('SC-70-5', 5), ('TO-252-2(DPAK)', 2), ('VQFN-20-EP(3.6x4.6)', 20),
                     ('LQFN-56_L7.0-W7.0-P0.4-EP', 56), ('DFN-8L(2x2)', 8), ('HDR-TH_3P-P2.54-V-M-1', None), ('0402', None)):
        assert parse_package(s)[0] == leads, (s, parse_package(s))
    assert parse_package('SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR')[2] == (2.9, 1.3)
    assert parse_package('VQFN-20-EP(3.6x4.6)') == (20, True, (3.6, 4.6))


def test_easyeda_footprint_without_courtyard():
    d = tempfile.mkdtemp()
    fp = new_footprint('Q_PART', descr='AO3400A; SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR; AOS')
    for n, x, y in (('1', -0.95, 1.1), ('2', 0.95, 1.1), ('3', 0, -1.1)):
        fp.append(Node('pad', n, Sym('smd'), Sym('rect'), Node('at', x, y), Node('size', 0.6, 0.9),
                       Node('layers', 'F.Cu', 'F.Mask', 'F.Paste')))
    fp.append(Node('fp_circle', Node('center', 1.46, 1.1), Node('end', 1.56, 1.1), Node('fill', Sym('solid')),
                   Node('layer', 'F.Fab')))                                       # pin-1 dot, as EasyEDA draws it
    p = os.path.join(d, 'Q_PART.kicad_mod')
    save(fp, p)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fpcheck.py'), p, '--package', 'SOT-23-3'],
                       capture_output=True, text=True)
    assert r.returncode == 0 and 'PROBLEM' not in r.stdout, r.stdout + r.stderr
    assert 'note: no F.CrtYd courtyard' in r.stdout and 'F.Fab body none' in r.stdout, r.stdout


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
