"""schgen hierarchical designs, and every tool downstream of them:  python3 tests/test_schgen_hierarchy.py
A root sheet with sheet blocks, a sub-sheet used once and one used several times (one file, one set of symbol ids,
one reference per instance), nested sheets. KiCad is the judge where it is installed (the tests that need it say so
and return early without it): ERC, the netlist against a sheet-template netspec, a board from new_board.py with DRC
schematic parity, KiCad re-saves, byte-identical regeneration; then partfields, nc_audit, refparts and board_diff on
the hierarchical result. The demo design is examples/hierarchy_demo.py."""
import collections, json, os, shutil, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'examples'))
import hierarchy_demo, netspec, partfields, symgen  # noqa: E402
from schgen import Sch, find_merges, kicad_symbol_dir  # noqa: E402
from kicad_sexpr import dumps, load  # noqa: E402

CLI = next((c for c in (os.environ.get('KICAD_CLI'), shutil.which('kicad-cli'),
                        '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli') if c and os.path.exists(c)), None)


def kicad(*args):
    return subprocess.run([CLI] + list(args), capture_output=True, text=True, timeout=600)


def script(name, *args):
    return subprocess.run([sys.executable, os.path.join(HERE, name)] + list(args), capture_output=True, text=True)


def export_netlist(sch):
    out = os.path.join(os.path.dirname(sch), 'net.xml')
    r = kicad('sch', 'export', 'netlist', '--format', 'kicadxml', '-o', out, sch)
    assert os.path.exists(out), r.stdout + r.stderr
    return out


def components(xml):
    """{ref: (sheet path names, sheet path uuids, symbol uuid)}"""
    out = {}
    for c in ET.parse(xml).getroot().find('components'):
        sp = c.find('sheetpath')
        out[c.get('ref')] = (sp.get('names'), sp.get('tstamps'), c.findtext('tstamps'))
    return out


def erc(sch):
    out = sch + '.erc.json'
    kicad('sch', 'erc', '--severity-all', '--format', 'json', '-o', out, sch)
    d = json.load(open(out))
    return collections.Counter(v['type'] for s in d['sheets'] for v in s['violations'])


def drc(pcb):
    out = pcb + '.drc.json'
    kicad('pcb', 'drc', '--schematic-parity', '--severity-all', '--format', 'json', '-o', out, pcb)
    d = json.load(open(out))
    return collections.Counter(v['type'] for v in d['violations']), len(d['schematic_parity']), d


def files(d):
    return {f: open(os.path.join(d, f), 'rb').read() for f in sorted(os.listdir(d)) if f.endswith('.kicad_sch')}


def items(path):
    """the top-level items of a file as text, order aside (KiCad sorts some kinds when it saves)"""
    return collections.Counter(dumps(n) for n in load(path).nodes())


# ---------------------------------------------------------------- the generator itself (no KiCad needed)

def test_instances_references_and_pages():
    d = tempfile.mkdtemp()
    root = hierarchy_demo.write(d)
    inst = {p: refs for p, s, refs in root.instances()}
    assert list(inst) == ['/', '/power/', '/ch1/', '/ch2/', '/ch3/'], list(inst)
    assert inst['/ch2/'] == {'R1': 'R201', 'R2': 'R202', 'R3': 'R203', 'C1': 'C201', 'J1': 'J201'}, inst['/ch2/']
    assert inst['/power/'] == {'U1': 'U1', 'C1': 'C1', 'C2': 'C2'}
    t = load(os.path.join(d, 'demo.kicad_sch'))
    blocks = {str(p[2]): b for b in t.nodes('sheet') for p in b.nodes('property') if p[1] == 'Sheetname'}
    pages = {n: [(str(x[1]), str(x.get('page'))) for x in b.walk('path')] for n, b in blocks.items()}
    rp = '/' + str(t.get('uuid'))
    assert pages == {'power': [(rp, '2')], 'ch1': [(rp, '3')], 'ch2': [(rp, '4')], 'ch3': [(rp, '5')]}, pages
    ch = load(os.path.join(d, 'channel.kicad_sch'))
    want = ['%s/%s' % (rp, blocks['ch%d' % k].get('uuid')) for k in (1, 2, 3)]
    refs, pwr = {}, []
    for s in ch.nodes('symbol'):
        paths = [(str(p[1]), str(p.find('reference')[1])) for p in s.walk('path')]
        assert [p for p, _ in paths] == want, paths
        prop = next(str(p[2]) for p in s.nodes('property') if p[1] == 'Reference')
        assert prop == paths[0][1], (prop, paths)              # the Reference property is the first instance's
        (pwr if prop.startswith('#') else refs.setdefault(prop, [])).extend(r for _, r in paths)
    assert refs['R101'] == ['R101', 'R201', 'R301'] and refs['J101'] == ['J101', 'J201', 'J301'], refs
    allpwr = pwr + [str(p.find('reference')[1]) for f in ('demo', 'power')
                    for s in load(os.path.join(d, f + '.kicad_sch')).nodes('symbol') for p in s.walk('path')
                    if str(p.find('reference')[1]).startswith('#')]
    assert len(allpwr) == len(set(allpwr)), sorted(allpwr)    # power symbols numbered across the design
    assert load(os.path.join(d, 'channel.kicad_sch')).find('sheet_instances') is None


def test_regeneration_is_byte_identical():
    a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
    hierarchy_demo.write(a)
    hierarchy_demo.write(b)
    assert files(a) == files(b)                               # from scratch, twice
    before = files(a)
    hierarchy_demo.write(a)                                   # over itself (previous='auto' reuses every id)
    assert files(a) == before
    c = tempfile.mkdtemp()                                    # previous= an earlier root sheet elsewhere
    root, _ = hierarchy_demo.build()
    root.write(os.path.join(c, 'demo.kicad_sch'), previous=os.path.join(a, 'demo.kicad_sch'))
    assert files(c) == before


def test_duplicate_references_are_refused():
    """the same sheet placed twice without refs: refused before any file is written, naming both instances"""
    root, _ = hierarchy_demo.build(n=2)
    root.blocks[-1].refs = 100                                # ch2 now clashes with ch1 (also 100)
    d = tempfile.mkdtemp()
    try:
        root.write(os.path.join(d, 'demo.kicad_sch'))
        raise AssertionError('duplicate references were written')
    except ValueError as e:
        assert 'R101 in /ch1/ (R1 on channel.kicad_sch), /ch2/ (R1 on channel.kicad_sch)' in str(e), e
    assert os.listdir(d) == []
    sub = root.blocks[0].child
    try:
        sub.write(os.path.join(d, 'x.kicad_sch'))
        raise AssertionError('a sub-sheet was written on its own')
    except ValueError as e:
        assert 'write the root sheet' in str(e), e


def test_sheet_pins_follow_hierarchical_labels():
    root = Sch('t', paper='A4')
    root.lib('power', os.path.join(kicad_symbol_dir(), 'power.kicad_sym'))
    sub = root.sub('s.kicad_sch')
    sub.hlabel('A', 50.8, 50.8, 180, 'input')
    sub.hlabel('Y', 76.2, 50.8, 0, 'output')
    sub.hlabel('IO', 50.8, 55.88, 180, 'bidirectional')
    b = root.sheet(sub, 'u1', 101.6, 50.8)
    assert [(q['name'], q['side']) for q in b.pins] == [('A', 'left'), ('IO', 'left'), ('Y', 'right')], b.pins
    assert b.p('A') == (101.6, 53.34) and b.p('IO') == (101.6, 55.88) and b.p('Y') == (round(101.6 + b.w, 4), 53.34)
    try:
        b.p('NOPE'); raise AssertionError
    except KeyError as e:
        assert 'A' in str(e) and 'Y' in str(e)
    b2 = root.sheet(sub, 'u2', 101.6, 76.2, left=['A'], right=['IO', 'Y'])
    assert [(q['name'], q['side']) for q in b2.pins] == [('A', 'left'), ('IO', 'right'), ('Y', 'right')]
    for bad in (dict(left=['A'], right=['Y']), dict(left=['A', 'A'], right=['IO', 'Y']), dict(left=['A', 'Z'])):
        try:
            root.sheet(sub, 'bad', 0, 0, **bad); raise AssertionError(bad)
        except ValueError:
            pass
    try:
        root.sheet(sub, 'u1', 0, 0); raise AssertionError('duplicate sheet name accepted')
    except ValueError:
        pass
    # unconnected pins and a wire through a block are drawing faults
    msgs = root.collisions()
    assert sum('is not connected' in m for m in msgs) == 6, msgs
    root.wire((96.52, 53.34), b.p('A'))
    root.wire((106.68, 45.72), (106.68, 66.04))
    msgs = root.collisions()
    assert sum('is not connected' in m for m in msgs) == 5 and any('crosses sheet block u1' in m for m in msgs), msgs
    # find_merges knows sheet pins as BLOCK/LABEL
    root.wire(b.p('IO'), (96.52, 55.88), (96.52, 53.34))
    m = find_merges(root, {'X': ['u1/A'], 'Z': ['u1/IO']})
    assert m == ["MERGE ['Z'] + ['X'] via wire (96.52, 55.88)-(96.52, 53.34)"], m
    # a label drawn after the block was placed: write() refuses the stale block
    sub.hlabel('LATE', 76.2, 60.96, 0, 'output')
    try:
        root.write(os.path.join(tempfile.mkdtemp(), 't.kicad_sch')); raise AssertionError
    except ValueError as e:
        assert 'LATE' in str(e) and 'place the block after drawing the labels' in str(e), e


def test_netspec_templates_expand():
    root, _ = hierarchy_demo.build()
    spec = hierarchy_demo.netspec(root)
    flat, sheet_of, origin = netspec.expand(spec)
    assert sorted(flat['D2']) == ['J2.2', 'R201.1'] and sorted(flat['FB3']) == ['J3.3', 'R302.2', 'R303.1'], flat
    assert sorted(flat['/ch1/DOUT']) == ['J101.2', 'R101.2', 'R102.1'], flat
    assert 'R303.2' in flat['GND'] and 'U1.1' in flat['GND'] and 'C301.1' in flat['+3V3'], flat
    assert sheet_of['R201'] == '/ch2/' and origin['R201.1'] == 'ch2:R1.1', (sheet_of, origin)
    assert netspec.expand({'A': ['R1.1']}) == ({'A': ['R1.1']}, {}, {})          # a flat spec stays as it is
    for bad, msg in ((dict(spec, nets=dict(spec['nets'], X=['ch9/DIN'])), 'no instance ch9'),
                     (dict(spec, nets=dict(spec['nets'], X=['ch1/NOPE'])), 'has no net NOPE'),
                     (dict(spec, nets=dict(spec['nets'], X=['ch1/DIN'])), 'joins top-level nets D1, X')):
        try:
            netspec.expand(bad); raise AssertionError(msg)
        except netspec.SpecError as e:
            assert msg in str(e), e


def test_netspec_reports_a_per_instance_rail_drawn_as_a_power_symbol():
    """two bank sheets that each draw their own supply as a VBANK power symbol: KiCad makes it one net (power symbols
    are global), the template spec keeps it per instance, and the check says SHORT"""
    xml = ET.fromstring('''<export version="E"><components>
<comp ref="C101"><value>1u</value><sheetpath names="/b1/" tstamps="/a/"/><tstamps>c</tstamps></comp>
<comp ref="C201"><value>1u</value><sheetpath names="/b2/" tstamps="/b/"/><tstamps>c</tstamps></comp>
</components><nets>
<net code="1" name="VBANK"><node ref="C101" pin="1" pintype="passive"/><node ref="C201" pin="1" pintype="passive"/></net>
<net code="2" name="GND"><node ref="C101" pin="2" pintype="passive"/><node ref="C201" pin="2" pintype="passive"/></net>
</nets></export>''')
    spec = {'global': ['GND'], 'nets': {},
            'sheets': {'bank': {'nets': {'VBANK': ['C1.1'], 'GND': ['C1.2']}, 'instances': {'b1': 100, 'b2': 200}}}}
    errs = netspec.check(spec, xml)
    assert errs == ['SHORT    KiCad net "VBANK" joins /b1/VBANK: C101.1, /b2/VBANK: C201.1'], errs


# ---------------------------------------------------------------- KiCad is the judge

def demo_project(n=3):
    d = tempfile.mkdtemp()
    hierarchy_demo.write(d, n)
    return d


def test_demo_erc_netlist_board_parity_and_resave():
    if not CLI:
        print('  (skipped: no kicad-cli)'); return
    d = demo_project()
    sch, pcb = os.path.join(d, 'demo.kicad_sch'), os.path.join(d, 'demo.kicad_pcb')
    assert erc(sch) == {}, erc(sch)                                       # no errors and no warnings
    xml = export_netlist(sch)
    r = script('netspec.py', 'check', os.path.join(d, 'netspec.json'), xml)
    assert r.returncode == 0 and 'matches' in r.stdout, r.stdout + r.stderr
    comps = components(xml)
    assert {k: v[0] for k, v in comps.items() if k.endswith('01') and len(k) > 2} == {
        'R101': '/ch1/', 'C101': '/ch1/', 'J101': '/ch1/', 'R201': '/ch2/', 'C201': '/ch2/', 'J201': '/ch2/',
        'R301': '/ch3/', 'C301': '/ch3/', 'J301': '/ch3/'}, comps
    assert len({comps[r][2] for r in ('R101', 'R201', 'R301')}) == 1          # one symbol, three instances
    assert len({comps[r][1] for r in ('R101', 'R201', 'R301')}) == 3
    # a wrong instance map in the spec is caught: ch2 and ch3 swapped
    spec = json.load(open(os.path.join(d, 'netspec.json')))
    spec['sheets']['channel']['instances'].update(ch2=300, ch3=200)
    bad = netspec.check(spec, ET.parse(xml).getroot())
    assert any(e.startswith('MISPLACED R301 is on /ch3/') for e in bad), bad
    assert any(e.startswith('SHORT') for e in bad), bad
    # the board: one footprint per instance, linked by sheet path, DRC schematic parity clean
    r = script('new_board.py', xml, pcb, '--layers', '2', '--outline', '80x60', '--placement', os.path.join(d, 'place.json'))
    assert r.returncode == 0, r.stderr
    fps = {}
    for f in load(pcb).nodes('footprint'):
        ref = next(str(p[2]) for p in f.nodes('property') if p[1] == 'Reference')
        fps[ref] = (str(f.get('path')), str(f.get('sheetname')), str(f.get('sheetfile')))
    assert len(fps) == 21, sorted(fps)
    for ref, (names, tstamps, uuid) in comps.items():
        assert fps[ref][0] == tstamps + uuid, (ref, fps[ref], tstamps, uuid)
        assert fps[ref][1] == names, (ref, fps[ref])
    assert fps['R201'][2] == 'channel.kicad_sch' and fps['J1'][1:] == ('/', 'demo.kicad_sch'), fps
    viol, parity, raw = drc(pcb)
    assert parity == 0, raw['schematic_parity']
    assert set(viol) == set(), viol                            # only the unrouted connections (not violations)
    res = partfields.check(sch, pcb)
    assert not res['problems'] and res['parts'] == 21, res
    # pcb-part-selection's BOM check counts every instance (it reads the same netlist)
    sys.path.insert(0, os.path.join(HERE, '..', '..', 'pcb-part-selection', 'scripts'))
    import bom_check
    groups, missing = bom_check.bom_groups(xml)
    assert groups['C25744']['refs'] == ['R102', 'R103', 'R202', 'R203', 'R302', 'R303'] and not missing, groups
    assert groups['C1525']['refs'] == ['C101', 'C201', 'C301'] and len(groups['C2337']['refs']) == 6, groups
    # KiCad re-saves every file: nothing is lost (only the order of some items changes), the board keeps its links
    before = {f: items(os.path.join(d, f)) for f in ('demo.kicad_sch', 'power.kicad_sch', 'channel.kicad_sch')}
    orig = files(d)
    for f in before:
        r = kicad('sch', 'upgrade', '--force', os.path.join(d, f))
        assert r.returncode == 0, r.stdout + r.stderr
        assert items(os.path.join(d, f)) == before[f], f
    pcb_items = items(pcb)
    assert kicad('pcb', 'upgrade', '--force', pcb).returncode == 0
    assert items(pcb) == pcb_items
    r = script('netspec.py', 'check', os.path.join(d, 'netspec.json'), export_netlist(sch))
    assert r.returncode == 0, r.stdout
    assert drc(pcb)[1] == 0
    # regenerating over KiCad's saved files gives the generator's bytes again (every id kept)
    hierarchy_demo.write(d)
    assert files(d) == orig


def test_check_sh_on_a_hierarchical_project():
    """check.sh (ERC, DRC with schematic parity, board_lint, nc_audit, partfields) on the demo project"""
    kpy = '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3'
    if not CLI or not (os.environ.get('KICAD_PYTHON') or os.path.exists(kpy)):
        print('  (skipped: no kicad-cli / KiCad python)'); return
    d = demo_project()
    xml = export_netlist(os.path.join(d, 'demo.kicad_sch'))
    assert script('new_board.py', xml, os.path.join(d, 'demo.kicad_pcb'), '--layers', '2', '--outline', '80x60',
                  '--placement', os.path.join(d, 'place.json')).returncode == 0
    os.remove(xml)
    out = tempfile.mkdtemp()
    r = subprocess.run(['bash', os.path.join(HERE, 'check.sh'), d, out], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    for f in ('demo.kicad_sch', 'power.kicad_sch', 'channel.kicad_sch'):
        assert '%s: ok' % os.path.join(d, f) in r.stdout, r.stdout
    erc_md = open(os.path.join(out, 'erc.md')).read()
    assert erc_md.count('|') == 8, erc_md                     # the table header only: no ERC finding at all
    assert 'schematic parity issues: 0' in r.stdout and '21 BOM parts, 21 with a datasheet link' in r.stdout, r.stdout
    assert '0 problem(s), 0 accepted' in r.stdout and '21 footprints checked: 0 problem(s)' in r.stdout, r.stdout
    drc_md = open(os.path.join(out, 'drc.md')).read()
    assert [l for l in drc_md.splitlines() if l.startswith('| error') or l.startswith('| warning')] == [
        '| error | unconnected_items | 37 |'], drc_md        # the board is not routed: nothing else


def buf_design(n=2, far=False):
    """a sub-sheet with a small IC (strapped EN, unused OUT, an NC pin) placed n times"""
    BUF = symgen.ic('BUF', 7.62, left=[('IN', ['1'], symgen.IN), ('EN', ['5'], symgen.IN)],
                    right=[('OUT', ['4'], symgen.OUT), ('NC', ['6'], symgen.NC)], top=[('VCC', ['2'], symgen.PI)],
                    bottom=[('GND', ['3'], symgen.PI)], footprint='Package_TO_SOT_SMD:SOT-23-6',
                    datasheet='https://example.com/buf.pdf')
    root = Sch('b', paper='A4')
    root.lib('P', lib=symgen.library({'BUF': BUF}))
    for lib in ('Device', 'power', 'Connector_Generic'):
        root.lib(lib, os.path.join(kicad_symbol_dir(), lib + '.kicad_sym'))
    s = root.sub('buf.kicad_sch')
    u = s.add('P:BUF', 'U1', 'BUF', 88.9, 63.5, lcsc='C1')
    c = s.add('Device:C', 'C1', '100n', 109.22, 63.5, footprint='Capacitor_SMD:C_0402_1005Metric', lcsc='C1525')
    s.hlabel('IN', 66.04, u.p('IN')[1], 180, 'input')
    s.wire((66.04, u.p('IN')[1]), u.p('IN'))
    en = u.p('EN')
    s.wire(en, (71.12, en[1]), (71.12, 50.8))
    s.power('+3V3', 71.12, 50.8, lib_id='power:+3V3')
    s.wire(u.p('VCC'), (u.p('VCC')[0], 50.8))
    s.power('+3V3', u.p('VCC')[0], 50.8, lib_id='power:+3V3')
    s.wire(u.p('GND'), (u.p('GND')[0], u.p('GND')[1] + 2.54))
    s.power('GND', u.p('GND')[0], u.p('GND')[1] + 2.54)
    s.nc(u.p('OUT'))
    s.nc(u.p('NC'))
    s.wire(c.p(1), (c.p(1)[0], 50.8))
    s.power('+3V3', c.p(1)[0], 50.8, lib_id='power:+3V3')
    s.wire(c.p(2), (c.p(2)[0], c.p(2)[1] + 2.54))
    s.power('GND', c.p(2)[0], c.p(2)[1] + 2.54)
    j = root.add('Connector_Generic:Conn_01x%02d' % n, 'J1', 'IN', 50.8, 50.8, mirror='y',
                 footprint='Connector_PinHeader_2.54mm:PinHeader_1x%02d_P2.54mm_Vertical' % n, lcsc='C2337')
    for k in range(n):
        b = root.sheet(s, 'b%d' % (k + 1), 101.6, 45.72 + 12.7 * k, refs=100 * (k + 1))
        a = j.p(k + 1)
        root.wire(a, (76.2 + 2.54 * k, a[1]), (76.2 + 2.54 * k, b.p('IN')[1]), b.p('IN'))
    place = {'J1': [5, 5, 0]}
    for k in range(1, n + 1):
        place.update({'U%d01' % k: [15, 10 * k, 0], 'C%d01' % k: [20 if not (far and k == n) else 45, 10 * k, 0]})
    return root, place


def test_nc_audit_and_refparts_cover_every_instance():
    if not CLI:
        print('  (skipped: no kicad-cli)'); return
    d = tempfile.mkdtemp()
    root, place = buf_design(far=True)
    root.write(os.path.join(d, 'b.kicad_sch'))
    xml = export_netlist(os.path.join(d, 'b.kicad_sch'))
    # nc_audit: one row per decision of the repeated sheet, a note for one instance covers the others
    notes = os.path.join(d, 'notes.json')
    json.dump({'U101.5': 'EN tied high: always on (ds p3)', 'U201.4': 'OUT unused in this test',
               'U101.6': 'NC: leave open (ds p2)'}, open(notes, 'w'))
    r = script('nc_audit.py', xml, '--notes', notes, '--require-notes')
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [l for l in r.stdout.splitlines() if l.startswith('| U')]
    assert len(rows) == 3, r.stdout
    assert any(l.startswith('| U101.5 (and U201.5) |') and 'tied to +3V3' in l and 'always on' in l for l in rows), rows
    assert any(l.startswith('| U101.4 (and U201.4) |') and 'OUT unused' in l for l in rows), rows
    assert '3 pins listed (6 counting every sheet instance), 0 without a decision' in r.stdout, r.stdout
    # refparts: the entry written for U101 is checked on U201 as well, each with its own placement
    pl = os.path.join(d, 'place.json')
    json.dump(place, open(pl, 'w'))
    pcb = os.path.join(d, 'b.kicad_pcb')
    assert script('new_board.py', xml, pcb, '--layers', '2', '--outline', '60x40', '--placement', pl).returncode == 0
    spec = os.path.join(d, 'reference-parts.json')
    json.dump({'U101': {'part': 'BUF', 'parts': [{'role': 'VCC bypass', 'kind': 'C', 'between': ['VCC', 'GND'],
                                                   'value': '100n', 'max_mm': 8}]}}, open(spec, 'w'))
    r = script('refparts.py', xml, pcb, '--spec', spec)
    assert r.returncode == 1, r.stdout
    rows = {l.split('|')[1].strip(): l.split('|')[4].strip() for l in r.stdout.splitlines() if l.startswith('| U')}
    assert rows['U101'].startswith('ok: C101'), r.stdout
    # U201's own bypass cap was placed far away: its row fails on its own board position (+3V3 and GND are global,
    # so the nearest 100n across them, wherever it is, is the candidate - here U101's, still too far)
    assert rows['U201'].startswith('FAR:'), r.stdout


def test_nested_sheets():
    """root -> group x2 (refs +1000, +2000) -> leaf x2 (refs +100, +200): references compose innermost first, every
    instance has its own sheet path and page, and the nested template spec checks against KiCad's netlist"""
    root = Sch('n', paper='A4')
    for lib in ('Device', 'Connector_Generic'):
        root.lib(lib, os.path.join(kicad_symbol_dir(), lib + '.kicad_sym'))
    leaf = root.sub('leaf.kicad_sch')
    r1 = leaf.add('Device:R', 'R1', '1k', 63.5, 50.8, rot=90, footprint='Resistor_SMD:R_0402_1005Metric', lcsc='C11702')
    leaf.hlabel('A', 50.8, 50.8, 180, 'passive')
    leaf.hlabel('B', 76.2, 50.8, 0, 'passive')
    leaf.wire((50.8, 50.8), r1.p(1))
    leaf.wire(r1.p(2), (76.2, 50.8))
    grp = root.sub('group.kicad_sch')
    grp.hlabel('IN', 40.64, 53.34, 180, 'passive')
    grp.hlabel('OUT', 152.4, 53.34, 0, 'passive')
    l1 = grp.sheet(leaf, 'l1', 60.96, 50.8, refs=100, right=['B'])
    l2 = grp.sheet(leaf, 'l2', 101.6, 50.8, refs=200, right=['B'])
    grp.wire((40.64, 53.34), l1.p('A'))
    grp.wire(l1.p('B'), l2.p('A'))
    grp.wire(l2.p('B'), (152.4, 53.34))
    j = root.add('Connector_Generic:Conn_01x04', 'J1', 'J', 50.8, 50.8, mirror='y',
                 footprint='Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical', lcsc='C2337')
    for k, off in ((0, 1000), (1, 2000)):
        g = root.sheet(grp, 'g%d' % (k + 1), 101.6, 45.72 + 15.24 * k, refs=off, right=['OUT'])
        a, b = j.p(2 * k + 1), j.p(2 * k + 2)
        root.wire(a, (76.2 - 5.08 * k, a[1]), (76.2 - 5.08 * k, g.p('IN')[1]), g.p('IN'))
        root.wire(b, (66.04 - 5.08 * k, b[1]), (66.04 - 5.08 * k, g.p('IN')[1] + 7.62),
                  (g.p('OUT')[0] + 5.08, g.p('IN')[1] + 7.62), (g.p('OUT')[0] + 5.08, g.p('OUT')[1]), g.p('OUT'))
    msgs = [m for s in (root, grp, leaf) for m in s.collisions()]
    assert not msgs, msgs
    inst = root.instances()
    assert [(p, refs) for p, s, refs in inst if s is leaf] == [
        ('/g1/l1/', {'R1': 'R1101'}), ('/g1/l2/', {'R1': 'R1201'}), ('/g2/l1/', {'R1': 'R2101'}),
        ('/g2/l2/', {'R1': 'R2201'})], inst
    d = tempfile.mkdtemp()
    root.write(os.path.join(d, 'n.kicad_sch'))
    g = load(os.path.join(d, 'group.kicad_sch'))
    pages = sorted(int(x.get('page')) for b in g.nodes('sheet') for x in b.walk('path'))
    assert pages == [3, 4, 6, 7], pages                        # root 1, g1 2, its leaves 3-4, g2 5, its leaves 6-7
    if not CLI:
        print('  (KiCad part skipped: no kicad-cli)'); return
    sch = os.path.join(d, 'n.kicad_sch')
    assert not erc(sch).get('error'), erc(sch)
    xml = export_netlist(sch)
    comps = components(xml)
    assert {k: v[0] for k, v in comps.items() if k != 'J1'} == {
        'R1101': '/g1/l1/', 'R1201': '/g1/l2/', 'R2101': '/g2/l1/', 'R2201': '/g2/l2/'}, comps
    spec = {'nets': {'IN1': ['J1.1', 'g1/IN'], 'OUT1': ['J1.2', 'g1/OUT'],
                     'IN2': ['J1.3', 'g2/IN'], 'OUT2': ['J1.4', 'g2/OUT']},
            'sheets': {'group': {'nets': {'IN': ['l1/A'], 'MID': ['l1/B', 'l2/A'], 'OUT': ['l2/B']},
                                 'instances': {'g1': 1000, 'g2': 2000}},
                       'leaf': {'nets': {'A': ['R1.1'], 'B': ['R1.2']},
                                'instances': {'g1/l1': 1100, 'g1/l2': 1200, 'g2/l1': 2100, 'g2/l2': 2200}}}}
    errs = netspec.check(spec, ET.parse(xml).getroot())
    assert not errs, errs


def test_board_diff_lists_instance_references():
    d = tempfile.mkdtemp()
    hierarchy_demo.write(d)
    old = os.path.join(d, 'channel.old.kicad_sch')
    shutil.copy(os.path.join(d, 'channel.kicad_sch'), old)
    root, _ = hierarchy_demo.build()
    root.blocks[-1].refs = 700                                 # ch3: R301 -> R701, ...
    root.write(os.path.join(d, 'demo.kicad_sch'))
    r = script('board_diff.py', old, os.path.join(d, 'channel.kicad_sch'))
    assert r.returncode == 1, r.stdout
    lines = [l for l in r.stdout.splitlines() if l.startswith('- R101')]
    assert lines and "'R301' -> 'R701'" in lines[0] and 'UNEXPECTED' in lines[0], r.stdout
    r = script('board_diff.py', old, os.path.join(d, 'channel.kicad_sch'), '--expect-refs', 'R101,R102,R103,C101,J101')
    assert r.returncode == 0, r.stdout
    assert script('sexp.py', 'get', os.path.join(d, 'channel.kicad_sch'), 'R702').stdout.startswith('(symbol')


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
