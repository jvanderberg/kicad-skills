"""add_courtyard.py: a courtyard by IPC-7351B / KLC F5.3 class on footprints shaped like JLCImport's EasyEDA imports
(no F.Fab body, silk outside the pads, the package name in descr / tags):  python3 tests/test_add_courtyard.py
With kicad-cli: board_setup.py's rules make DRC report the footprint before the courtyard is added, and not after."""
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import add_courtyard, board_setup
from fpcheck import parse_package
from kicad_sexpr import Board, Node, Project, Sym, fp_line, load, new_footprint, save


def pad(num, x, y, w, h, shape='rect', kind='smd'):
    layers = ('*.Cu', '*.Mask') if kind == 'thru_hole' else ('F.Cu', 'F.Mask', 'F.Paste')
    items = [Node('at', x, y), Node('size', w, h)] + ([Node('drill', 1.0)] if kind == 'thru_hole' else [])
    return Node('pad', num, Sym(kind), Sym(shape), *items, Node('layers', *layers))


def easyeda(name, package, pads, silk=None, lcsc='C25744'):
    """A footprint as JLCImport writes one: package name in descr and tags, LCSC property, silk box, no courtyard"""
    fp = new_footprint(name, descr='%s; %s; MAKER' % (name, package), tags='%s %s %s MAKER' % (name, lcsc, package))
    fp.append(Node('property', 'LCSC', lcsc, Node('at', 0, 0, 0), Node('layer', 'F.Fab')))
    if silk:
        x0, y0, x1, y1 = silk
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            fp.append(fp_line(a, b, 'F.SilkS', width=0.15))
    fp.extend(pads)
    return fp


def courtyard(path):
    rects = [n for n in load(path).nodes('fp_rect') if str(n.get('layer')) == 'F.CrtYd']
    assert len(rects) == 1, path
    s, e = rects[0].find('start'), rects[0].find('end')
    return (s.number(1), s.number(2), e.number(1), e.number(2))


def write(d, fp):
    p = os.path.join(d, str(fp[1]) + '.kicad_mod')
    save(fp, p)
    return p


def close(a, b):
    return all(abs(x - y) < 1e-6 for x, y in zip(a, b))


def test_classes_and_bodies():
    d = tempfile.mkdtemp()
    # 0402: pads span 1.43 mm, body 1.0 x 0.5 from "R0402", silk well outside: small, 0.15 mm, silk ignored
    r = write(d, easyeda('R0402_PART', 'R0402', [pad('1', -0.4328, 0, 0.5657, 0.54), pad('2', 0.4328, 0, 0.5657, 0.54)],
                         silk=(-0.944, -0.4986, 0.944, 0.4986)))
    # SOT-23 body from L x W, long side along the silk's
    q = write(d, easyeda('SOT_PART', 'SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR',
                         [pad('1', -0.95, 1.1, 0.6, 0.9), pad('2', 0.95, 1.1, 0.6, 0.9), pad('3', 0, -1.1, 0.6, 0.9)],
                         silk=(-1.5, -0.7, 1.5, 0.7)))
    c = write(d, easyeda('CONN_PART', 'CONN-SMD_2P-P2.00_S2B-PH-SM4-TB', [pad('1', -1, 0, 1, 3), pad('2', 1, 0, 1, 3)],
                         silk=(-3, -2, 3, 4)))
    balls = [pad('%s%d' % (r_, c_), (c_ - 2) * 0.4, (ord(r_) - 66) * 0.4, 0.25, 0.25, 'circle') for r_ in 'ABC' for c_ in (1, 2, 3)]
    g = write(d, easyeda('BALL_PART', 'XYZ-9', balls))                        # no BGA in the name: found by its pads
    for p in (r, q, c, g):
        print(add_courtyard.process(p, False))
    assert close(courtyard(r), (-0.87, -0.42, 0.87, 0.42)), courtyard(r)      # pads +- 0.716 / 0.27, + 0.15, outward
    assert close(courtyard(q), (-1.7, -1.8, 1.7, 1.8)), courtyard(q)          # body 2.9 wide, pads 3.1 tall, + 0.25
    assert close(courtyard(c), (-3.5, -2.5, 3.5, 4.5)), courtyard(c)          # connector: silk body + 0.5
    assert close(courtyard(g), (-1.53, -1.53, 1.53, 1.53)), courtyard(g)      # ball grid: + 1.0


def test_fab_outline_forced_class_rerun_and_existing():
    d = tempfile.mkdtemp()
    fp = new_footprint('KICAD_STYLE', items=[pad('1', -2, 0, 1, 1), pad('2', 2, 0, 1, 1)])
    fp.append(fp_line((-1.5, -3), (1.5, -3), 'F.Fab', width=0.1)); fp.append(fp_line((-1.5, 3), (1.5, 3), 'F.Fab', width=0.1))
    p = write(d, fp)
    assert add_courtyard.process(p, True, cls='wide').startswith('would add')
    add_courtyard.process(p, False, cls='wide')
    assert close(courtyard(p), (-3.0, -3.5, 3.0, 3.5)), courtyard(p)          # F.Fab body 3 x 6 with the pads, + 0.5
    before = open(p).read()
    assert add_courtyard.process(p, False).startswith('has courtyard')
    assert open(p).read() == before


def test_project_dir_takes_project_libraries_only():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, 'JLCImport.pretty')); os.makedirs(os.path.join(d, 'elsewhere.pretty'))
    open(os.path.join(d, 'p.kicad_pro'), 'w').write('{}\n')
    t = Node('fp_lib_table', Node('version', 7),
             Node('lib', Node('name', 'JLCImport'), Node('type', 'KiCad'), Node('uri', '${KIPRJMOD}/JLCImport.pretty')),
             Node('lib', Node('name', 'Other'), Node('type', 'KiCad'), Node('uri', '/somewhere/Other.pretty')))
    save(t, os.path.join(d, 'fp-lib-table'))
    a = write(os.path.join(d, 'JLCImport.pretty'), easyeda('A', 'R0603', [pad('1', -0.8, 0, 0.8, 0.9), pad('2', 0.8, 0, 0.8, 0.9)]))
    b = write(os.path.join(d, 'elsewhere.pretty'), easyeda('B', 'R0603', [pad('1', -0.8, 0, 0.8, 0.9), pad('2', 0.8, 0, 0.8, 0.9)]))
    assert add_courtyard.project_libraries(d) == [os.path.join(d, 'JLCImport.pretty')]
    r = subprocess.run([sys.executable, os.path.join(HERE, 'add_courtyard.py'), d], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'F.CrtYd' in open(a).read() and 'F.CrtYd' not in open(b).read(), r.stdout
    assert close(courtyard(a), (-1.45, -0.7, 1.45, 0.7)), courtyard(a)        # 0603 body 1.6 x 0.8: default 0.25


def test_fpcheck_reads_package_names():
    assert parse_package('SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR') == (3, False, (2.9, 1.3))
    assert parse_package('SOT-23')[0] is None and parse_package('SOD-123')[0] is None
    assert parse_package('VQFN-20-EP(3.6x4.6)') == (20, True, (3.6, 4.6))
    assert parse_package('TO-252-2(DPAK)')[0] == 2 and parse_package('LQFN-56_L7.0-W7.0-P0.4-EP')[:2] == (56, True)


def test_drc_reports_missing_courtyard_until_added():
    cli = os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
    if not os.path.exists(cli):
        print('  (skipped: no kicad-cli)'); return
    d = tempfile.mkdtemp()
    fp = write(d, easyeda('Q_PART', 'SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR',
                          [pad('1', -0.95, 1.1, 0.6, 0.9), pad('2', 0.95, 1.1, 0.6, 0.9), pad('3', 0, -1.1, 0.6, 0.9)]))
    pro = os.path.join(d, 't.kicad_pro')
    Project.new(pro).save()
    project = board_setup.apply_project(Project.load(pro), 'jlc', [], {}, [])
    project.save()

    def missing():
        b = Board.new(copper_layers=2)
        b.add_footprint(fp, 'L:Q_PART', 'Q1', 'X', (100, 100))
        b.save(os.path.join(d, 't.kicad_pcb'))
        subprocess.run([cli, 'pcb', 'drc', '--severity-all', '--format', 'json', '-o', os.path.join(d, 'drc.json'),
                        os.path.join(d, 't.kicad_pcb')], capture_output=True)
        import json
        return [v for v in json.load(open(os.path.join(d, 'drc.json')))['violations'] if v['type'] == 'missing_courtyard']
    assert len(missing()) == 1
    add_courtyard.process(fp, False)
    assert missing() == []


if __name__ == '__main__':
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            f(); print('ok', k)
