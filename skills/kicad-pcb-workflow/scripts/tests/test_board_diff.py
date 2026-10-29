"""board_diff.py: a board below the repository root, run from another folder, with a field-only change; HEAD against a
scratch copy outside the repository (the copy-back check in SKILL.md section 4):
    python3 tests/test_board_diff.py     (needs git and KiCad's footprint library for R_0402)"""
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from kicad_sexpr import Board

FPLIB = next((d for d in ('/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints', '/usr/share/kicad/footprints')
              if os.path.isdir(d)), None)


def git(cwd, *a):
    subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)


def test_field_change_below_repo_root():
    if not FPLIB:
        print('  (skipped: no KiCad footprint library)'); return
    root = tempfile.mkdtemp(); hw = os.path.join(root, 'hardware'); os.makedirs(hw)
    b = Board.new(copper_layers=2)
    f = b.add_footprint(os.path.join(FPLIB, 'Resistor_SMD.pretty', 'R_0402_1005Metric.kicad_mod'), 'Resistor_SMD:R_0402_1005Metric',
                        'R7', '330', (100, 100), fields={'LCSC': 'C25104'})
    f.set_pad_net('1', 'VDD'); f.set_pad_net('2', 'GND')
    pcb = os.path.join(hw, 'x.kicad_pcb'); b.save(pcb)
    git(root, 'init', '-q'); git(root, 'add', '.'); git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base')
    run = lambda *a: subprocess.run([sys.executable, os.path.join(HERE, 'board_diff.py'), *a], capture_output=True, text=True,
                                    cwd=tempfile.gettempdir())                      # a cwd outside the repository
    r = run('HEAD', pcb)
    assert r.returncode == 0 and '0 unexpected' in r.stdout, (r.stdout, r.stderr)
    assert 'Compared: 1 footprints' in r.stdout, r.stdout
    b2 = Board.load(pcb); fp = b2.footprint('R7')
    fp.set_field('Value', '100'); fp.set_field('LCSC', 'C25076'); b2.save(pcb)
    r = run('HEAD', pcb)
    assert r.returncode == 1, r.stdout
    line = [l for l in r.stdout.splitlines() if l.startswith('- R7')][0]
    assert "field Value '330' -> '100'" in line and "field LCSC 'C25104' -> 'C25076'" in line and 'UNEXPECTED' in line, line
    r = run('HEAD', pcb, '--expect-refs', 'R7')
    assert r.returncode == 0, r.stdout



def test_head_against_a_scratch_copy_outside_the_repo():
    if not FPLIB:
        print('  (skipped: no KiCad footprint library)'); return
    root = tempfile.mkdtemp(); hw = os.path.join(root, 'hardware'); os.makedirs(hw)
    b = Board.new(copper_layers=2)
    b.add_footprint(os.path.join(FPLIB, 'Resistor_SMD.pretty', 'R_0402_1005Metric.kicad_mod'), 'Resistor_SMD:R_0402_1005Metric',
                    'R7', '330', (100, 100))
    pcb = os.path.join(hw, 'x.kicad_pcb'); b.save(pcb)
    git(root, 'init', '-q'); git(root, 'add', '.'); git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base')
    scratch = os.path.join(tempfile.mkdtemp(), 'proj'); os.makedirs(scratch)
    new = os.path.join(scratch, 'x.kicad_pcb'); shutil.copy(pcb, new)
    b2 = Board.load(new); b2.footprint('R7').set_field('Value', '100'); b2.save(new)
    run = lambda cwd, *a: subprocess.run([sys.executable, os.path.join(HERE, 'board_diff.py'), *a], capture_output=True,
                                         text=True, cwd=cwd)
    for cwd, extra in ((hw, ()), (root, ()), (tempfile.gettempdir(), ('--repo', root)), (tempfile.gettempdir(), ('--repo', hw))):
        r = run(cwd, 'HEAD', new, '--expect-refs', 'R7', *extra)
        assert r.returncode == 0, (cwd, extra, r.stdout, r.stderr)
        assert 'OLD = HEAD:hardware/x.kicad_pcb in %s ' % os.path.realpath(root) in r.stdout, r.stdout
        assert "field Value '330' -> '100'" in r.stdout, r.stdout
    r = run(tempfile.gettempdir(), 'HEAD:hardware/x.kicad_pcb', new, '--repo', root, '--expect-refs', 'R7')
    assert r.returncode == 0 and "field Value '330' -> '100'" in r.stdout, (r.stdout, r.stderr)
    r = run(scratch, 'HEAD', new)                                       # no repository anywhere: says what to give
    assert r.returncode and '--repo DIR' in r.stderr, r.stderr
    os.makedirs(os.path.join(root, 'old')); shutil.copy(pcb, os.path.join(root, 'old', 'x.kicad_pcb'))
    git(root, 'add', '.'); git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'two')
    r = run(root, 'HEAD', new)                                          # two of that name, neither in the current folder
    assert r.returncode and 'several files of that name (hardware/x.kicad_pcb, old/x.kicad_pcb)' in r.stderr, r.stderr
    r = run(hw, 'HEAD', new, '--expect-refs', 'R7')                     # the one in the current folder
    assert r.returncode == 0 and 'OLD = HEAD:hardware/x.kicad_pcb' in r.stdout, (r.stdout, r.stderr)


if __name__ == '__main__':
    fails = 0
    for k, fn in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                fn(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
