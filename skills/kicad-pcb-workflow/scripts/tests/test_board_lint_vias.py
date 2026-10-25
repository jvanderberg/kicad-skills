"""board_lint.py VIA IN PAD on a generated board (needs KiCad's python and footprint library):
    python3 tests/test_board_lint_vias.py
A via on a pad of its own net passes DRC (same-net copper is exempt from clearance) and wicks solder from the joint;
board_lint reports it whichever tool placed it. Vias in an exposed pad are NOTE lines (usually intended)."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from kicad_sexpr import Board

FPLIB = next((d for d in ('/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints', '/usr/share/kicad/footprints')
              if os.path.isdir(d)), None)
KICAD_PYTHON = next((c for c in (os.environ.get('KICAD_PYTHON', ''),
                                 '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3')
                     if c and os.path.exists(c)), None)


def test_via_in_same_net_pad():
    if not (FPLIB and KICAD_PYTHON):
        print('  (skipped: no KiCad python / footprint library)'); return
    d = tempfile.mkdtemp()
    b = Board.new(copper_layers=2)
    r1 = b.add_footprint(os.path.join(FPLIB, 'Resistor_SMD.pretty', 'R_0603_1608Metric.kicad_mod'), 'Resistor_SMD:R_0603_1608Metric',
                         'R1', '10k', (100, 100))
    r1.set_pad_net('1', 'VDD'); r1.set_pad_net('2', 'GND')
    u1 = b.add_footprint(os.path.join(FPLIB, 'Package_DFN_QFN.pretty', 'QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm.kicad_mod'),
                         'Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm', 'U1', 'X', (110, 100))
    for n in [str(i) for i in range(1, 17)]:
        u1.set_pad_net(n, 'SIG%s' % n)
    u1.set_pad_net('17', 'GND')
    x2, y2 = r1.pad_position('2')
    b.via((x2, y2), 0.6, 0.3, 'GND')                 # on R1's ground pad: VIA IN PAD
    b.via((x2 + 1.2, y2), 0.6, 0.3, 'GND')           # clear of every pad: fine
    b.via((110, 100), 0.45, 0.2, 'GND')              # in U1's exposed pad: NOTE
    pcb = os.path.join(d, 'v.kicad_pcb'); b.save(pcb)
    r = subprocess.run([KICAD_PYTHON, os.path.join(HERE, 'board_lint.py'), pcb, '--no-models', '--no-courtyard', '--no-silk', '--no-paste'],
                       capture_output=True, text=True)
    lines = r.stdout.splitlines()
    vip = [l for l in lines if l.startswith('VIA IN PAD')]
    assert len(vip) == 1 and 'pad R1.2' in vip[0] and 'centre on' in vip[0], r.stdout + r.stderr
    assert any(l.startswith('NOTE') and 'U1.17' in l for l in lines), r.stdout
    assert r.returncode == 1 and '1 problem(s), 1 note(s)' in r.stdout, r.stdout
    r = subprocess.run([KICAD_PYTHON, os.path.join(HERE, 'board_lint.py'), pcb, '--no-models', '--no-courtyard', '--no-silk',
                        '--no-via-in-pad', '--no-paste'], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_paste_on_holes_and_hardware():
    """KiCad's own thermal-via QFN puts a paste window over each via drill: PASTE ON HOLE (until the vias are declared
    filled and capped); a track inside a mounting hole's hardware radius on the back is UNDER HARDWARE, one outside it
    is not, and a pour of the declared hardware net is not mentioned"""
    if not (FPLIB and KICAD_PYTHON):
        print('  (skipped: no KiCad python / footprint library)'); return
    d = tempfile.mkdtemp()
    b = Board.new(copper_layers=2)
    u = b.add_footprint(os.path.join(FPLIB, 'Package_DFN_QFN.pretty', 'QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm_ThermalVias.kicad_mod'),
                        'Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm_ThermalVias', 'U1', 'X', (110, 100))
    for n in [str(i) for i in range(1, 17)]:
        u.set_pad_net(n, 'SIG%s' % n)
    u.set_pad_net('17', 'GND')
    b.add_footprint(os.path.join(FPLIB, 'MountingHole.pretty', 'MountingHole_3.2mm_M3.kicad_mod'), 'MountingHole:MountingHole_3.2mm_M3',
                    'H1', 'M3', (130, 100))
    b.segment((127, 97.5), (127, 102.5), 0.2, 'B.Cu', 'SIG1')        # edge 2.9 mm from the hole centre: under a 3.7 mm radius
    b.segment((135, 95), (135, 105), 0.2, 'F.Cu', 'SIG2')            # 5 mm away: clear
    pcb = os.path.join(d, 'p.kicad_pcb'); b.save(pcb)
    base = [KICAD_PYTHON, os.path.join(HERE, 'board_lint.py'), pcb, '--no-models', '--no-courtyard', '--no-silk', '--no-via-in-pad']
    r = subprocess.run(base, capture_output=True, text=True)
    lines = r.stdout.splitlines()
    poh = [l for l in lines if l.startswith('PASTE ON HOLE')]
    assert len(poh) == 4 and all('U1' in l and 'drill of pad U1.17' in l for l in poh), r.stdout + r.stderr
    hw = [l for l in lines if l.startswith('UNDER HARDWARE')]
    assert len(hw) == 1 and 'SIG1' in hw[0] and 'B.Cu' in hw[0] and 'H1' in hw[0], r.stdout
    assert any(l.startswith('NOTE') and 'paste coverage' in l and 'U1.17' in l for l in lines), r.stdout
    assert r.returncode == 1, r.stdout
    r = subprocess.run(base + ['--hardware-r', '2.5'], capture_output=True, text=True)
    assert not any(l.startswith('UNDER HARDWARE') for l in r.stdout.splitlines()), r.stdout
    r = subprocess.run(base + ['--vias-filled', 'U1', '--no-hardware'], capture_output=True, text=True)
    assert 'PASTE ON HOLE' not in r.stdout and r.returncode == 0, r.stdout       # filled and capped by decision


if __name__ == '__main__':
    fails = 0
    for k, fn in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                fn(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
