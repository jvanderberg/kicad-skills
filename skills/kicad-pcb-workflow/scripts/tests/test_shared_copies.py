"""Helpers each skill carries its own copy of (the skill folders are self-contained) stay identical:
    python3 tests/test_shared_copies.py"""
import filecmp, os
SKILLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
COPIES = {'projfiles.py': ('kicad-pcb-workflow', 'kicad-board-review', 'pcb-part-selection'),
          'kicad_locks.py': ('kicad-pcb-workflow', 'kicad-board-review', 'pcb-part-selection'),
          'jlcversion.py': ('kicad-pcb-workflow', 'kicad-board-review', 'pcb-part-selection'),
          'interp.py': ('kicad-pcb-workflow', 'kicad-board-review'),
          'preflight.py': ('kicad-pcb-workflow', 'kicad-board-review'),
          'drc_summary.py': ('kicad-pcb-workflow', 'kicad-board-review'),
          'skills_rev.py': ('kicad-pcb-workflow', 'kicad-board-review'),
          'kicad_env.sh': ('kicad-pcb-workflow', 'kicad-board-review')}


def test_copies_identical():
    bad = []
    for name, skills in COPIES.items():
        paths = [os.path.join(SKILLS, s, 'scripts', name) for s in skills]
        bad += ['%s missing' % p for p in paths if not os.path.exists(p)]
        bad += ['%s differs from %s' % (p, paths[0]) for p in paths[1:] if os.path.exists(p) and not filecmp.cmp(paths[0], p, shallow=False)]
    assert not bad, bad


if __name__ == '__main__':
    test_copies_identical(); print('PASS')
