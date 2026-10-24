"""Project (.kicad_pro) helpers: net classes, assignments, rules and KiCad's JSON layout."""
import json
import os

from helpers import corpus, tmpdir
from kicad_sexpr import Project


def test_netclasses_assignments_and_layout():
    d = tmpdir('pro')
    p = Project.new(os.path.join(d, 'x.kicad_pro'))
    p.netclass('Default', clearance=0.15, track_width=0.2)
    pw = p.netclass('Power', clearance=0.2, track_width=0.8)
    assert pw['priority'] == 0 and pw['via_diameter'] == 0.6 and pw['wire_width'] == 6
    p.assign('VBUS', 'Power')
    p.add_pattern('*D+', 'USB')
    p.set_rules(min_clearance=0.15, min_hole_to_hole=0.25)
    p.set_track_widths([0.2, 0.5])
    p.save()
    text = open(p.path).read()
    assert text.endswith('}\n') and text == json.dumps(json.loads(text), indent=2, sort_keys=True) + '\n'
    q = Project.load(p.path)
    names = [c['name'] for c in q.netclasses()]
    assert names == ['Default', 'Power']
    ns = q.data['net_settings']
    assert ns['netclass_assignments'] == {'VBUS': 'Power'}
    assert ns['netclass_patterns'] == [{'netclass': 'USB', 'pattern': '*D+'}]
    assert q.data['board']['design_settings']['track_widths'] == [0.0, 0.2, 0.5]
    q.clear_assignments()
    assert q.data['net_settings']['netclass_assignments'] == {} and q.data['net_settings']['netclass_patterns'] == []


def test_kicad_saved_projects_rewrite_byte_identical():
    """Optional: KICAD_SEXPR_PRO_CORPUS='/path/**/*.kicad_pro' -- KiCad-saved projects load and save unchanged."""
    from helpers import Skip
    files = corpus('KICAD_SEXPR_PRO_CORPUS')
    if not files:
        raise Skip('KICAD_SEXPR_PRO_CORPUS not set')
    d = tmpdir('procorpus')
    for f in files:
        out = os.path.join(d, os.path.basename(f))
        Project.load(f).save(out)
        assert open(out).read() == open(f).read(), f
