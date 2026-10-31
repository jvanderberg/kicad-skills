"""board_setup.py net class assignments:  python3 tests/test_board_setup_assign.py
- the --assign / --pattern of a run are the complete set: a net taken out of a class on a re-run leaves it, a pattern
  no longer given is dropped, and the run lists what it dropped; --keep-assignments adds to the existing ones
- an assigned name that is not a net of the board next to the .kicad_pro (SW for Net-(U3-SW)) and a pattern that
  matches no net are warnings, as is a missing board."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from kicad_sexpr import Board, Project

NETS = ['GND', 'VBUS', '3V3', 'Net-(U3-SW)', '/USB_D+', '/USB_D-']


def project(with_board=True):
    d = tempfile.mkdtemp()
    Project.new(os.path.join(d, 'p.kicad_pro')).save()
    if with_board:
        b = Board.new()
        for i, n in enumerate(NETS):
            b.segment((100, 100 + i), (110, 100 + i), 0.2, 'F.Cu', n)
        b.save(os.path.join(d, 'p.kicad_pcb'))
    return d


def run(d, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, 'board_setup.py'), os.path.join(d, 'p.kicad_pro'),
                        '--class', 'Power:track=0.8,clearance=0.2', '--class', 'USB:track=0.3'] + list(args),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout, r.stderr, Project.load(os.path.join(d, 'p.kicad_pro'))


def test_rerun_replaces_assignments_and_patterns():
    d = project()
    out, err, p = run(d, '--assign', 'Power=VBUS,GND,3V3', '--pattern', 'USB=/USB_D*')
    assert p.assignments() == {'VBUS': ['Power'], 'GND': ['Power'], '3V3': ['Power']}, p.assignments()
    assert p.data['net_settings']['netclass_patterns'] == [{'netclass': 'USB', 'pattern': '/USB_D*'}]
    assert 'dropped' not in out and not err, (out, err)
    out, err, p = run(d, '--assign', 'Power=VBUS,3V3')                       # GND and the pattern taken out
    assert p.assignments() == {'VBUS': ['Power'], '3V3': ['Power']}, p.assignments()
    assert p.data['net_settings']['netclass_patterns'] == []
    assert 'dropped (not given on this run): GND (Power), pattern /USB_D* (USB)' in out, out
    out, err, p = run(d, '--assign', 'Power=VBUS,3V3')                       # same command: same file, nothing dropped
    assert 'dropped' not in out, out
    out, err, p = run(d, '--keep-assignments', '--assign', 'Power=GND')      # one-off addition
    assert p.assignments() == {'VBUS': ['Power'], '3V3': ['Power'], 'GND': ['Power']}, p.assignments()
    assert 'existing ones kept' in out and 'dropped' not in out, out
    out, err, p = run(d)                                                      # none given: none left
    assert p.assignments() == {} and 'dropped' in out, (p.assignments(), out)


def test_assigned_names_that_are_not_nets_warn():
    d = project()
    out, err, p = run(d, '--assign', 'Power=VBUS,SW,GND', '--pattern', 'USB=USB_D*', '--pattern', 'Power=+*V*')
    assert p.assignments()['SW'] == ['Power']                                # written all the same
    assert 'WARNING: --assign SW: no net of that name on the board (did you mean Net-(U3-SW)?)' in err, err
    assert 'WARNING: --pattern USB_D*: matches no net on the board' in err, err   # the nets are /USB_D+, /USB_D-
    assert 'WARNING: --pattern +*V*' in err and 'VBUS' not in err and 'GND' not in err, err
    out, err, p = run(d, '--assign', 'Power=VBUS,GND,3V3,Net-(U3-SW)', '--pattern', 'USB=/USB_D*')
    assert not err, err


def test_missing_board_warns():
    d = project(with_board=False)
    out, err, p = run(d, '--assign', 'Power=VBUS')
    assert 'WARNING: no board at' in err and p.assignments() == {'VBUS': ['Power']}, err


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                import traceback; traceback.print_exc()
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
