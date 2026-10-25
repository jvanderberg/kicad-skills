"""The minipc-power before-case (its review skipped heat): run only when MINIPC_PACK points at a pack built by
make_pack.sh (this branch, so power runs saved their loss maps) from minipc-power commit 947e64b with the review's own
review_config.json (power runs, no "thermal" section):
    MINIPC_PACK=/path/to/pack python3 tests/test_thermal_minipc.py
Checks, on a copy of the pack: (1) with the review's config, the tools now say heat was NOT CHECKED and list the
battery-path FETs and the charger as UNKNOWN heat sources instead of saying nothing, and report the stitching the pack
measured; (2) with the thermal inputs the review should have had (tests/data/minipc_thermal.json: datasheet R_DS(on),
the solved path current from path_budget.py), the battery path's series loss is in the table and exceeds the converter
loss at the 15 W empty-cell corner, and the board temperatures are reported at every h."""
import glob, json, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.environ.get('PY') or os.path.expanduser('~/.cache/kicad-skills/venv/bin/python')
PB = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'pcb-power-supply', 'scripts', 'path_budget.py')
PACK = os.environ.get('MINIPC_PACK')
FIX = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'minipc_thermal.json')))


def copy_pack():
    import pytest
    if not PACK or not os.path.exists(os.path.join(PACK, 'board.json')):
        pytest.skip('MINIPC_PACK not set (a make_pack.sh pack of minipc-power 947e64b)')
    if not os.path.exists(PY):
        pytest.skip('no analysis python at %s' % PY)
    d = tempfile.mkdtemp()
    for f in ['board.json', 'netlist.json', 'planes.json', 'review_config.json'] + [os.path.basename(p) for p in glob.glob(os.path.join(PACK, 'power_runs*.json'))]:
        shutil.copy(os.path.join(PACK, f), d)
    os.makedirs(os.path.join(d, 'maps'))
    for f in glob.glob(os.path.join(PACK, 'maps', '*_loss.npz')): shutil.copy(f, os.path.join(d, 'maps'))
    cfg = json.load(open(os.path.join(d, 'review_config.json'))); cfg.pop('thermal', None)
    json.dump(cfg, open(os.path.join(d, 'review_config.json'), 'w'))
    return d


def thermal(d):
    r = subprocess.run([PY, os.path.join(HERE, 'thermal.py'), d, '--no-maps'], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
    return json.load(open(os.path.join(d, 'thermal.json'))), open(os.path.join(d, 'thermal.md')).read()


def test_before_heat_not_checked_is_reported():
    d = copy_pack()
    T, md = thermal(d)
    assert any(f['severity'] == 'high' and 'heat NOT CHECKED' in f['text'] for f in T['findings']), T['findings']
    unknown = {r['name'] for r in T['heat']['default']['rows'] if r['P_W'] is None}
    assert {'Q1', 'Q2', 'Q3', 'U2', 'F1', 'U4', 'U5', 'U6'} <= unknown, unknown
    es = T['stitching']['edge']
    assert es['vias_within_3mm'] == 6 and max(g['gap_mm'] for g in es['gaps_over_10mm']) > 50, es
    assert len(T['stitching']['weak']) == 2 and all(w['stitch_vias'] == 1 for w in T['stitching']['weak']), T['stitching']['weak']
    assert 'Ground stitching' in md and '57 mm' in md


def test_with_thermal_inputs_battery_path_heat_is_in_the_table():
    d = copy_pack()
    for name, spec in FIX['path_budgets'].items():
        json.dump(spec, open(os.path.join(d, name), 'w'))
        subprocess.run([sys.executable, PB, os.path.join(d, name), '--json', os.path.join(d, name.replace('.json', '_out.json'))], capture_output=True)
    tc = json.loads(json.dumps(FIX['thermal']).replace('.json"', '_out.json"'))
    cfg = json.load(open(os.path.join(d, 'review_config.json'))); cfg['thermal'] = tc
    json.dump(cfg, open(os.path.join(d, 'review_config.json'), 'w'))
    T, md = thermal(d)
    h = T['heat']['discharge_15W_empty']
    by = h['by_ref']
    for q in ('Q1', 'Q2', 'Q3'):
        assert 0.5 < by[q] < 0.8, (q, by[q])                            # ~6.6 A^2 x 10.4 mOhm x 1.4
    assert abs(by['U2'] - 6.6 ** 2 * 0.0195) < 0.05, by['U2']          # BATFET at the solved current
    assert h['groups']['battery path'] > 2.5 and h['groups']['battery path'] > 2 * h['groups']['converters'], h['groups']
    cond, conv = T['conduction_vs_conversion_W']['discharge_15W_empty']
    assert cond > conv, (cond, conv)
    assert any('series path, not the converters' in f['text'] for f in T['findings'])
    b = {(r['corner'], r['h']): r for r in T['board']}
    for k, r in b.items():
        assert abs(r['avg_solver'] - r['avg_analytic']) / max(r['avg_analytic'], 1e-9) < 0.01, r
    assert b[('discharge_15W_empty', 'low')]['peak']['rise'] > b[('discharge_15W_empty', 'high')]['peak']['rise']
    assert any(f['severity'] == 'high' and f['text'].startswith('corner discharge_15W_empty') for f in T['findings'])
    pads = {(e['ref'], e['pad']): e for e in T['exposed_pads']}
    assert pads[('U5', '21')]['vias_in_pad'] == 8 and pads[('U5', '21')]['severity'] == 'ok', pads[('U5', '21')]
    assert pads[('U2', '25')]['vias_in_pad'] == 9, pads[('U2', '25')]
    fet_pours = [p for p in T['pours'] if p['net'] in ('Net-(Q2-D-Pad1)', 'Net-(U3-VSS)')]
    assert fet_pours and all(p['vias'] == 0 and p['dT_K'] > 5 for p in fet_pours), fet_pours
    assert md.index('Findings, ranked') < md.index('Heat sources per corner')


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                if type(e).__name__ == 'Skipped': print('SKIP', k, e); continue
                fails += 1; print('FAIL', k, repr(e)[:3000])
    sys.exit(1 if fails else 0)
