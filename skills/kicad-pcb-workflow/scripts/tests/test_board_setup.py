"""board_setup.py: --class errors name the valid keys; the jlc rules allow only vias JLC makes at no extra charge
(0.45 / 0.2 mm on 4+ layers, 0.45 / 0.3 on 2):  python3 tests/test_board_setup.py"""
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


def test_jlc_rules_allow_only_free_vias():
    """JLC's quote page: a hole < 0.3 mm is charged unless the via is >= 0.45 mm on a multilayer board"""
    import tempfile
    for layers, drill in ((4, 0.2), (2, 0.3)):
        p = Project.new(os.path.join(tempfile.mkdtemp(), 't.kicad_pro'))
        board_setup.apply_project(p, 'jlc', [], {}, [], layers)
        ds = p.design_settings()
        assert ds['rules']['min_through_hole_diameter'] == drill and ds['rules']['min_via_diameter'] >= 0.45, (layers, ds['rules'])
        assert all(v['drill'] == 0 or v['drill'] >= drill and v['diameter'] >= 0.45 for v in ds['via_dimensions']), ds['via_dimensions']
        assert {'diameter': 0.45, 'drill': drill} in ds['via_dimensions'], ds['via_dimensions']


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
