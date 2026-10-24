"""Project (.kicad_pro) helpers: net classes, assignments, rules and KiCad's JSON layout."""
import json
import os

from helpers import corpus, drc, tmpdir
from kicad_sexpr import Board, Project

KICAD_SAVED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'kicad10_saved.kicad_pro')


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
    assert ns['netclass_assignments'] == {'VBUS': ['Power']}
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


def test_kicad_saved_project_round_trips_byte_identical():
    """tests/data/kicad10_saved.kicad_pro is minipc-power's project as KiCad 10.0.1 saved it (net classes, 19
    list-form assignments, rules): load + save through the layer gives the same bytes."""
    d = tmpdir('prosaved')
    out = os.path.join(d, 'x.kicad_pro')
    Project.load(KICAD_SAVED).save(out)
    assert open(out, encoding='utf-8').read() == open(KICAD_SAVED, encoding='utf-8').read()


def test_assignments_written_as_kicad_writes_them():
    """KiCad 10 stores netclass_assignments as lists ("+12V": ["Power"]) and rewrites strings to lists on save.
    Assigning the KiCad-saved file's nets through the layer must give exactly KiCad's structure; strings in older
    files are read as one class; a second class is appended, a repeated one is not."""
    kicad = Project.load(KICAD_SAVED)
    want = kicad.data['net_settings']['netclass_assignments']
    assert want and all(isinstance(v, list) for v in want.values())
    p = Project.new(os.path.join(tmpdir('proassign'), 'x.kicad_pro'))
    for net, classes in want.items():
        for c in classes:
            p.assign(net, c)
            p.assign(net, c)                                  # no duplicates
    assert p.data['net_settings']['netclass_assignments'] == want
    assert json.dumps(p.data['net_settings']['netclass_assignments'], indent=2, sort_keys=True) == \
        json.dumps(want, indent=2, sort_keys=True)
    old = Project({'net_settings': {'classes': [], 'netclass_assignments': {'VBUS': 'Power'}}})
    assert old.assignments() == {'VBUS': ['Power']}
    old.assign('VBUS', 'HighCurrent')
    old.assign('GND', 'Power')
    assert old.data['net_settings']['netclass_assignments'] == {'VBUS': ['Power', 'HighCurrent'], 'GND': ['Power']}


def test_list_assignment_is_used_by_kicad_drc():
    """A net put in a 0.3 mm class with assign() (list form): DRC flags a 0.25 mm gap to it; unassigned it does not."""
    for assign, expect in ((True, True), (False, False)):
        d = tmpdir('proassigndrc')
        b = Board.new(2)
        b.outline_rect(0, 0, 20, 10)
        b.segment((2, 4), (18, 4), 0.25, 'F.Cu', 'N1')
        b.segment((2, 4.5), (18, 4.5), 0.25, 'F.Cu', 'N2')
        p = os.path.join(d, 'c.kicad_pcb')
        b.save(p)
        pro = Project.new(os.path.join(d, 'c.kicad_pro'))
        pro.netclass('Default', clearance=0.2)
        pro.netclass('Wide', clearance=0.3)
        if assign:
            pro.assign('N1', 'Wide')
        pro.save()
        assert json.load(open(pro.path))['net_settings']['netclass_assignments'] == ({'N1': ['Wide']} if assign else None)
        v = drc(p, refill=False)['violations']
        assert ('clearance' in v) == expect, (assign, v)
