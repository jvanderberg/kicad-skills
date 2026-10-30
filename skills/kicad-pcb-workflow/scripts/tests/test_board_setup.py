"""board_setup.py: --class errors name the valid keys; the jlc rules keep every drill in JLC's base-price via tier
(0.3 mm; a 0.2 mm drill quoted about 4x on a small 4-layer board):  python3 tests/test_board_setup.py"""
import os, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import board_setup
from kicad_sexpr import Project


def test_class_keys():
    assert board_setup.parse_class('Power:track=0.8,clearance=0.2,via=0.8,drill=0.4') == (
        'Power', dict(track_width=0.8, clearance=0.2, via_diameter=0.8, via_drill=0.4))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'board_setup.py'), 'x.kicad_pro', '--class', 'Power:track_width=0.5'],
                       capture_output=True, text=True)
    assert r.returncode == 1 and 'Traceback' not in r.stderr, r.stderr
    assert 'unknown key "track_width"' in r.stderr and 'track, clearance, via, drill' in r.stderr, r.stderr


def test_jlc_rules_keep_drills_in_the_base_tier():
    import tempfile
    p = Project.new(os.path.join(tempfile.mkdtemp(), 't.kicad_pro'))
    board_setup.apply_project(p, 'jlc', [], {}, [])
    ds = p.design_settings()
    assert ds['rules']['min_through_hole_diameter'] >= 0.3 and ds['rules']['min_via_diameter'] >= 0.45, ds['rules']
    assert all(v['drill'] == 0 or v['drill'] >= 0.3 for v in ds['via_dimensions']), ds['via_dimensions']


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
