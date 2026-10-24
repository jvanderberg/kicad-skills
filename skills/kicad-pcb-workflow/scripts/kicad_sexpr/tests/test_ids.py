"""Stable uuids: deterministic regeneration, ids kept from a previous version of the file, links kept consistent.
KiCad is the judge where it reorders things: `kicad-cli pcb drc --refill-zones --save-board` sorts board items by
uuid, so random ids reshuffle a whole board on every rebuild."""
import difflib
import os
import shutil
import uuid

from helpers import cli, drc, footprints_dir, symbols_dir, tmpdir
from kicad_sexpr import Board, Project, Schematic, SymbolLibrary, Uuids, board_ids, dumps, load, loads, save

R0402 = 'Resistor_SMD:R_0402_1005Metric'


def _fp():
    return os.path.join(footprints_dir(), 'Resistor_SMD.pretty', 'R_0402_1005Metric.kicad_mod')


def _board(path, extra=False, previous=None, twin_segments=False):
    b = Board.new(4, previous=previous)
    r1 = b.add_footprint(_fp(), R0402, 'R1', '10k', (110, 110), 90, pad_nets={'1': 'A', '2': 'GND'},
                         fields={'LCSC': 'C25744'})
    if extra:                                   # off the board and outside every zone: changes nothing else
        b.add_footprint(_fp(), R0402, 'R9', '1k', (150, 140), 0)
    r2 = b.add_footprint(_fp(), R0402, 'R2', '10k', (120, 110), 30, side='B', pad_nets={'1': 'A', '2': 'GND'})
    a1, a2 = r1.pad_position(1), r2.pad_position(1)
    b.track([a1, (a1[0], 106), (115, 106)], 0.25, 'F.Cu', 'A')
    b.via((115, 106), 0.6, 0.3, 'A')
    b.track([(115, 106), (a2[0], 106), a2], 0.25, 'B.Cu', 'A')
    if twin_segments:                           # two identical segments: an ambiguous key
        b.segment((101, 101), (103, 101), 0.2, 'F.Cu', 'A')
        b.segment((101, 101), (103, 101), 0.2, 'F.Cu', 'A')
    outline = [(100, 100), (130, 100), (130, 120), (100, 120)]
    b.zone('GND', 'In1.Cu', outline, name='GND_PLANE')
    b.zone('GND', 'B.Cu', [(101, 112), (129, 112), (129, 119), (101, 119)])
    b.via((105, 115), 0.6, 0.3, 'GND', free=True)
    b.rule_area('F.Cu', [(101, 116), (104, 116), (104, 119), (101, 119)], name='NO_POUR')
    b.gr_text('TOP', (105, 102), 'F.SilkS')
    b.outline_rect(100, 100, 30, 20, corner_radius=1.0)
    b.save(path)
    Project.new(os.path.splitext(path)[0] + '.kicad_pro').save()
    return b


def _changed(a, b):
    d = [ln for ln in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm='', n=0)
         if ln[:1] in '+-' and not ln.startswith(('+++', '---'))]
    return [ln for ln in d if ln[0] == '-'], [ln[1:] for ln in d if ln[0] == '+']


def _refill(path):
    r = cli('pcb', 'drc', '--refill-zones', '--save-board', '-o', path + '.drc.json', path)
    assert os.path.exists(path + '.drc.json'), r.stdout + r.stderr
    return open(path).read()


def test_regeneration_is_byte_identical_also_after_kicad_refill():
    d1, d2 = tmpdir('det1'), tmpdir('det2')
    p1, p2 = os.path.join(d1, 'b.kicad_pcb'), os.path.join(d2, 'b.kicad_pcb')
    _board(p1)
    _board(p2)
    assert open(p1).read() == open(p2).read()
    assert _refill(p1) == _refill(p2)


def test_adding_a_footprint_changes_only_its_lines():
    d1, d2 = tmpdir('add1'), tmpdir('add2')
    p1, p2 = os.path.join(d1, 'b.kicad_pcb'), os.path.join(d2, 'b.kicad_pcb')
    _board(p1)
    _board(p2, extra=True)
    for a, b in ((open(p1).read(), open(p2).read()), (_refill(p1), _refill(p2))):
        removed, added = _changed(a, b)
        assert not removed, removed[:5]
        tb = loads(b)
        r9 = [f for f in tb.nodes('footprint') if any(p[1] == 'Reference' and p[2] == 'R9' for p in f.nodes('property'))]
        assert len(r9) == 1
        tb.remove_node(r9[0])
        assert dumps(tb) == a                                   # everything else is byte-identical
        assert len(added) == len(dumps(r9[0]).splitlines())     # the diff is exactly R9's block


def test_previous_ids_are_kept_and_links_stay_consistent():
    """A board whose ids were assigned elsewhere (random, as pcbnew or the GUI do): regenerating it with previous=
    keeps every id, so the file comes back byte-identical; footprints keep their symbol links."""
    d = tmpdir('prev')
    p = os.path.join(d, 'b.kicad_pcb')
    _board(p, twin_segments=True)
    t = load(p)
    for n in t.walk('uuid'):
        n[1] = str(uuid.uuid4())
    old = os.path.join(d, 'old.kicad_pcb')
    save(t, old)
    q = os.path.join(d, 'new.kicad_pcb')
    b = _board(q, previous=old, twin_segments=True)
    assert open(q).read() == open(old).read()
    assert b.uuids.reused == len(list(t.walk('uuid')))
    ids = board_ids(t)
    assert len(ids.ambiguous) == 1 and ids.ambiguous[0].startswith('segment/A/F.Cu/101,101/103,101')
    # an id never goes to two items, even when the previous file maps the same key twice to one uuid
    u = Uuids(seed='x', reuse={'k': 'b5f4e0f6-0000-4000-8000-000000000001',
                               'k#2': 'b5f4e0f6-0000-4000-8000-000000000001'})
    assert len({u.new('k'), u.new('k')}) == 2


def test_schematic_symbol_ids_and_board_paths():
    """Symbols keep their ids across regenerations (from scratch: derived; with previous: taken over by reference),
    so the board's (path "/<symbol uuid>") links stay valid: schematic parity 0 after regenerating the sheet."""
    lib = SymbolLibrary.load(os.path.join(symbols_dir(), 'Device.kicad_sym'), 'Device')
    pwr = SymbolLibrary.load(os.path.join(symbols_dir(), 'power.kicad_sym'), 'power')

    def sheet(path, previous=None, value='10k'):
        s = Schematic.new('p', previous=previous)
        r = s.add_symbol('Device:R', 'R1', value, (50.8, 50.8), lib=lib, footprint=R0402)
        g = s.power('power:GND', (50.8, 58.42), lib=pwr)
        s.wire(r.pin(2), g.pin(1))
        s.label('A', r.pin(1))
        s.save(path)
        return s

    d = tmpdir('schids')
    p = os.path.join(d, 'p.kicad_sch')
    s1 = sheet(p)
    first = open(p).read()
    p2 = os.path.join(tmpdir('schids2'), 'p.kicad_sch')
    sheet(p2)
    assert open(p2).read() == first
    # foreign ids (as a hand-drawn sheet has), then a regeneration that changes a value: ids kept, one line differs
    t = load(p)
    root = str(t.get('uuid'))
    for n in t.walk('uuid'):
        n[1] = str(uuid.uuid4())
    for n in t.walk('path'):                                    # keep the sheet's instance paths consistent
        n[1] = str(n[1]).replace(root, str(t.get('uuid')))
    save(t, p)
    before = open(p).read()
    s2 = sheet(p, previous=p, value='22k')
    removed, added = _changed(before, open(p).read())
    assert len(removed) == len(added) == 1 and '22k' in added[0], (removed, added)
    sym = s2.symbol('R1').uuid
    assert sym != s1.symbol('R1').uuid and sym == str(load(p).nodes('symbol')[0].get('uuid'))
    b = Board.new(2)
    fields = {k: v for k, v in s2.symbol('R1').fields().items() if k not in ('Reference', 'Value', 'Footprint')}
    b.add_footprint(_fp(), R0402, 'R1', '22k', (110, 110), path='/' + sym, pad_nets={'1': '/A', '2': 'GND'},
                    fields=fields)
    b.outline_rect(100, 100, 20, 20)
    b.save(os.path.join(d, 'p.kicad_pcb'))
    Project.new(os.path.join(d, 'p.kicad_pro')).save()
    assert drc(os.path.join(d, 'p.kicad_pcb'), parity=True)['parity'] == 0


def test_loaded_files_keep_their_ids():
    d = tmpdir('keep')
    p = os.path.join(d, 'b.kicad_pcb')
    _board(p)
    t = load(p)
    for n in t.walk('uuid'):
        n[1] = str(uuid.uuid4())
    save(t, p)
    before = {str(n[1]) for n in load(p).walk('uuid')}
    b = Board.load(p)
    b.segment((102, 102), (104, 102), 0.2, 'F.Cu', 'A')
    b.save()
    after = {str(n[1]) for n in load(p).walk('uuid')}
    assert before < after and len(after - before) == 1
    shutil.rmtree(d)


def test_explicit_uuid_and_key():
    b = Board.new(2)
    u = '12345678-1234-4234-8234-123456789abc'
    f = b.add_footprint(_fp(), R0402, 'R1', '1k', (10, 10), uuid=u)
    assert str(f.node.get('uuid')) == u
    s1 = b.segment((0, 0), (1, 0), 0.2, 'F.Cu', 'A', key='my/segment')
    s2 = b.segment((0, 1), (1, 1), 0.2, 'F.Cu', 'A', key='my/segment')
    assert s1.get('uuid') != s2.get('uuid')
    try:
        b.add_footprint(_fp(), R0402, 'R2', '1k', (20, 10), uuid=u)
        raise AssertionError('duplicate explicit uuid accepted')
    except ValueError:
        pass
