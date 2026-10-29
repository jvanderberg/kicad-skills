"""Copper layers the board renames ("Top Layer", "Inner1", ... as EasyEDA imports set them) (needs the analysis venv;
the end-to-end test also needs KiCad's python):   python3 tests/test_layer_names.py
- boarddump.py names layers canonically everywhere (layers, pads, tracks, zones), as the stackup block and the
  .kicad_pcb items do, and keeps the board's own names in layer_names: emc.py and report.py run on it (they raised
  KeyError 'Top Layer' when layers held the user names and the stackup the canonical ones);
- a board.json from the older dump (user names in layers) is a coverage warning with an assumed stackup, not a crash;
- review_config.json may name a layer by the board's own name."""
import json, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'tests'))
from test_pack_checks import PY, build, run  # noqa: E402

KICAD_PYTHON = next((c for c in (os.environ.get('KICAD_PYTHON', ''),
                                 '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3')
                     if c and os.path.exists(c)), None)
USER = {'F.Cu': 'Top Layer', 'In1.Cu': 'Inner1', 'In2.Cu': 'Inner2', 'B.Cu': 'Bottom Layer'}


def _rename(d, layers_only):
    """the synthetic pack's board.json as boarddump.py wrote it before (user names in every layer field), or as it
    writes it now (canonical names plus layer_names)"""
    p = os.path.join(d, 'board.json')
    B = json.load(open(p))
    if layers_only:
        B['layer_names'] = USER
    else:
        u = lambda L: USER.get(L, L)
        B['layers'] = [u(L) for L in B['layers']]
        for t in B['tracks']: t['layer'] = u(t['layer'])
        for f in B['footprints']:
            for q in f['pads']: q['layers'] = [u(L) for L in q['layers']]
        for z in B['zones']:
            z['layers'] = [u(L) for L in z['layers']]
            z['filled'] = {u(L): v for L, v in z['filled'].items()}
    json.dump(B, open(p, 'w'))


def test_old_dump_with_user_names_warns_instead_of_crashing():
    d = tempfile.mkdtemp()
    build(d)
    _rename(d, layers_only=False)
    run(d, 'planes.py', 'emc.py', 'report.py')
    emc = open(os.path.join(d, 'emc.md')).read()
    assert "stackup does not name copper layer(s) ['Top Layer', 'Inner1', 'Inner2', 'Bottom Layer']" in emc, emc[:2000]


def test_config_may_name_a_layer_by_the_boards_own_name():
    d = tempfile.mkdtemp()
    build(d)
    _rename(d, layers_only=True)
    cfg = json.load(open(os.path.join(d, 'review_config.json')))
    cfg['islands'][0]['layer'] = 'Top Layer'
    json.dump(cfg, open(os.path.join(d, 'review_config.json'), 'w'))
    run(d, 'islands.py', 'planes.py', 'emc.py', 'report.py')
    isl = json.load(open(os.path.join(d, 'islands.json')))
    assert isl['islands'][0]['status'].startswith('ok'), isl
    assert 'F.Cu (Top Layer)' in open(os.path.join(d, 'board_overview.md')).read()
    assert 'stackup does not name' not in open(os.path.join(d, 'emc.md')).read()


def test_boarddump_of_a_board_with_user_layer_names():
    if not KICAD_PYTHON:
        print('  (skipped: no KiCad python)'); return
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'kicad-pcb-workflow', 'scripts'))
    from kicad_sexpr import Board, dumps, stackup
    b = Board.new(4)
    b.set_stackup(stackup([0.035, 0.0152, 0.0152, 0.035], [('prepreg', 0.2104, '7628', 4.4, 0.02), ('core', 1.065, 'FR4', 4.6, 0.02),
                                                         ('prepreg', 0.2104, '7628', 4.4, 0.02)]))
    b.outline_rect(0, 0, 30, 20)
    b.segment((5, 5), (25, 5), 0.25, 'F.Cu', 'SIG')
    b.segment((5, 15), (25, 15), 0.25, 'In2.Cu', 'SIG2')
    b.zone('GND', 'In1.Cu', [(0, 0), (30, 0), (30, 20), (0, 20)])
    t = dumps(b.tree)
    for c, u in USER.items():
        n = '(%d "%s" signal)' % ({'F.Cu': 0, 'In1.Cu': 4, 'In2.Cu': 6, 'B.Cu': 2}[c], c)
        assert n in t, n
        t = t.replace(n, n[:-1] + ' "%s")' % u)
    d = tempfile.mkdtemp()
    pcb = os.path.join(d, 'named.kicad_pcb')
    open(pcb, 'w').write(t)
    pack = os.path.join(d, 'pack')
    r = subprocess.run([KICAD_PYTHON, os.path.join(HERE, 'boarddump.py'), pcb, pack], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    B = json.load(open(os.path.join(pack, 'board.json')))
    assert B['layers'] == ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'], B['layers']
    assert B['layer_names'] == USER, B['layer_names']
    assert [s['name'] for s in B['stackup'] if s['type'] == 'copper'] == B['layers']
    assert sorted(t_['layer'] for t_ in B['tracks']) == ['F.Cu', 'In2.Cu']
    assert [z['layers'] for z in B['zones']] == [['In1.Cu']]
    run(pack, 'planes.py', 'emc.py', 'report.py')                   # emc.py raised KeyError: 'Top Layer'
    assert 'stackup does not name' not in open(os.path.join(pack, 'emc.md')).read()
    assert 'F.Cu (Top Layer) 35 um' in open(os.path.join(pack, 'board_overview.md')).read()


if __name__ == '__main__':
    for t in (test_old_dump_with_user_names_warns_instead_of_crashing, test_config_may_name_a_layer_by_the_boards_own_name,
              test_boarddump_of_a_board_with_user_layer_names):
        t(); print('PASS', t.__name__)
