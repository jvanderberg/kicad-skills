"""sourcing.py, part_gate.py, bom_check.py and derived_check.py against a fake jlcimport-cli (no network, no KiCad):
    python3 -m pytest -q tests          (LCSC_LIVE=1 also runs the real lookups in test_live_regions)
The fake CLI fails any search without --region, so every test also proves no lookup relies on the CLI's own default."""
import json, os, subprocess, sys, tempfile, textwrap
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import derived_check, part_gate, sourcing  # noqa: E402

# what the two warehouses said on 2026-10-25 (real values: the SiSS80DN is stocked in cn only)
STOCK = {
    'global': {'C3289423': ('SISS80DN-T1-GE3', '', '1.0409'), 'C316138': ('DMN1004UFV-7', '317', '0.3254'),
               'C25076': ('0402WGF1000TCE', '900000', '0.0005')},
    'cn': {'C3289423': ('SISS80DN-T1-GE3', '12000', '8.814'), 'C316138': ('DMN1004UFV-7', '317', '1.9877'),
           'C25076': ('0402WGF1000TCE', '800000', '0.003')},
}

FAKE = textwrap.dedent('''\
    #!%s
    import json, os, sys
    a = sys.argv[1:]
    open(os.environ['FAKE_LOG'], 'a').write(json.dumps(a) + '\\n')
    if '--region' not in a:
        sys.stderr.write('fake: no --region given, would use the config default\\n'); sys.exit(3)
    region = a[a.index('--region') + 1]; kw = a[1]; n = int(a[a.index('-n') + 1])
    data = json.load(open(os.environ['FAKE_DATA']))[region]
    print('LCSC,Type,Price,Stock,Part,Package,Brand,Description')
    # like the catalogue: the first n matches in its own order (an entry's 5th field: keywords it also matches),
    # then sorted by stock as jlcimport-cli does
    hits = [(c, e) for c, e in data.items() if kw == c or kw.upper() in e[0].upper() or kw in (e[4] if len(e) > 4 else [])][:n]
    for c, e in sorted(hits, key=lambda h: -int(h[1][1] or 0)):
        print('%%s,Extended,%%s,%%s,%%s,PKG,%%s,desc' %% (c, e[2], e[1], e[0], e[3] if len(e) > 3 else 'Brand'))
''') % sys.executable


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cli = tmp_path / 'jlcimport-cli'; cli.write_text(FAKE); cli.chmod(0o755)
    (tmp_path / 'data.json').write_text(json.dumps(STOCK))
    log = tmp_path / 'log.txt'; log.write_text('')
    monkeypatch.setenv('FAKE_DATA', str(tmp_path / 'data.json')); monkeypatch.setenv('FAKE_LOG', str(log))
    proj = tmp_path / 'proj'; (proj / 'docs').mkdir(parents=True); (proj / 'hardware').mkdir(); (proj / '.git').mkdir()
    return dict(cli=str(cli), log=log, proj=proj, tmp=tmp_path)


def calls(env):
    return [json.loads(l) for l in env['log'].read_text().splitlines() if l]


def sh(*a, cwd=None):
    r = subprocess.run([sys.executable, *a], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def write_sourcing(env, **kw):
    d = dict(assembler='JLCPCB', region='global', boards=5, attrition=0.1); d.update(kw)
    (env['proj'] / 'docs' / 'sourcing.json').write_text(json.dumps(d))


def test_no_context_stops_instead_of_defaulting(env):
    with pytest.raises(sourcing.SourcingError, match='no sourcing context'):
        sourcing.resolve(str(env['proj'] / 'hardware'))
    rc, out = sh(os.path.join(HERE, 'part_gate.py'), 'C316138', '--project', str(env['proj']), '--cli', env['cli'])
    assert rc == 1 and 'no sourcing context' in out and calls(env) == []        # nothing looked up at all


def test_region_from_project_file_found_from_subfolder(env):
    write_sourcing(env)
    ctx = sourcing.resolve(str(env['proj'] / 'hardware'))
    assert ctx['region'] == 'global' and ctx['source'].endswith('docs/sourcing.json')
    assert 'region global' in sourcing.header(ctx) and 'USD' in sourcing.header(ctx)
    row, flags, note = sourcing.check_part('C3289423', ctx, per_board=3, cli=env['cli'])
    assert row['stock'] == 0 and flags == ['STOCK 0 < need 17 (global)']
    assert note.startswith('cn has 12,000 - does not count')
    assert all(c[c.index('--region') + 1] in ('global', 'cn') for c in calls(env))


def test_explicit_region_overrides_and_says_so(env):
    write_sourcing(env)
    ctx = sourcing.resolve(str(env['proj']), region='cn')
    assert ctx['region'] == 'cn' and any('overrides' in n for n in ctx['notes'])
    row, flags, _ = sourcing.check_part('C3289423', ctx, 3, env['cli'])
    assert row['stock'] == 12000 and not flags and row['currency'] == 'CNY'


def test_bad_file_is_refused(env):
    (env['proj'] / 'docs' / 'sourcing.json').write_text(json.dumps(dict(assembler='JLCPCB', regoin='global')))
    with pytest.raises(sourcing.SourcingError, match='unknown keys'):
        sourcing.resolve(str(env['proj']))
    (env['proj'] / 'docs' / 'sourcing.json').write_text(json.dumps(dict(assembler='JLCPCB', region='eu')))
    with pytest.raises(sourcing.SourcingError, match='not one of'):
        sourcing.resolve(str(env['proj']))


def test_policy_and_named_exception(env):
    write_sourcing(env, min_stock=1000, exceptions=[dict(lcsc='C316138', reason='only source', approved='user, 2026-10-25')])
    ctx = sourcing.resolve(str(env['proj']))
    _, flags, note = sourcing.check_part('C316138', ctx, 3, env['cli'])
    assert not flags and 'policy exception: only source' in note
    ctx['exceptions'] = []
    _, flags, _ = sourcing.check_part('C316138', ctx, 3, env['cli'])
    assert flags == ['POLICY 317 < 1000 listed (global)']


def test_part_gate_c_numbers(env):
    write_sourcing(env)
    rc, out = sh(os.path.join(HERE, 'part_gate.py'), 'C3289423', 'C316138', '--per-board', '3', '--cli', env['cli'],
                 cwd=str(env['proj'] / 'hardware'))
    assert rc == 1, out
    first = out.splitlines()[0]
    assert first.startswith('Sourcing: JLCPCB, region global') and 'stock as of' in first
    l1 = next(l for l in out.splitlines() if l.startswith('C3289423'))
    assert 'STOCK 0 < 17 in global' in l1 and 'cn has 12,000 - does not count' in l1
    l2 = next(l for l in out.splitlines() if l.startswith('C316138'))
    assert '317 in stock' in l2 and '<--' not in l2


NETLIST = '''<?xml version="1.0" encoding="UTF-8"?>
<export version="E"><components>
%s
</components></export>'''


def comp(ref, value, lcsc, ds='https://www.lcsc.com/datasheet/%s.pdf', fp='Package_SON:PowerDI3333-8', mpn=''):
    fields = '<field name="LCSC">%s</field>' % lcsc if lcsc else ''
    fields += '<field name="Datasheet">%s</field>' % ((ds % lcsc) if '%s' in ds else ds)
    if mpn:
        fields += '<field name="MPN">%s</field>' % mpn
    return '<comp ref="%s"><value>%s</value><footprint>%s</footprint><fields>%s</fields></comp>' % (ref, value, fp, fields)


def netlist(env, comps):
    p = env['tmp'] / 'net.xml'; p.write_text(NETLIST % '\n'.join(comps)); return str(p)


def test_bom_check_region_summary_and_derived(env):
    write_sourcing(env)
    sch = env['proj'] / 'hardware' / 'x.kicad_sch'; sch.write_text('')
    xml = netlist(env, [comp(q, 'SISS80DN', 'C3289423') for q in ('Q1', 'Q2', 'Q3')] +
                  [comp('R7', '100', 'C25076', ds='~', fp='Resistor_SMD:R_0402_1005Metric'), comp('U3', 'HY2113-GB3A', '', mpn='HY2113-GB3A')])
    (env['proj'] / 'docs' / 'design-values.json').write_text(json.dumps({'values': [dict(
        name='Discharge over-current trip', value='12.5 A', where='docs/power-design.md s5', approved='user, 2026-10-24',
        depends_on=[dict(ref='Q2', part='C3289423', param='R_DS(on) max Vgs 2.5 V', used='3.0 mOhm'),
                    dict(ref='U3', part='HY2113-GB3A', param='V_OCD', used='75 mV')])]}))
    out_json = env['tmp'] / 'bom.json'
    rc, out = sh(os.path.join(HERE, 'bom_check.py'), str(sch), '--netlist', xml, '--cli', env['cli'], '--json', str(out_json))
    assert rc == 1, out
    assert out.splitlines()[0].startswith('Sourcing: JLCPCB, region global')
    assert 'STOCK 0 < need 17 (global)' in out and 'cn has 12,000 - does not count' in out
    # the summary counts each thing under its own name (it used to print the two counts swapped)
    assert '2 unique LCSC parts, 2 with problems, 2 extended, 1 without a datasheet link, 1 parts without an LCSC number: U3' in out, out
    assert 'Derived values' in out and '0 problem' not in out and 'STALE' not in out      # parts unchanged: nothing stale
    j = json.load(open(out_json))
    assert j['region'] == 'global' and j['parts'][0]['region'] == 'global' and j['date']
    # swap Q2 for the substitute: the stock check passes for it, the trip current goes stale
    xml = netlist(env, [comp('Q1', 'SISS80DN', 'C3289423'), comp('Q2', 'DMN1004UFV', 'C316138'), comp('Q3', 'SISS80DN', 'C3289423'),
                        comp('U3', 'HY2113-GB3A', '', mpn='HY2113-GB3A')])
    rc, out = sh(os.path.join(HERE, 'bom_check.py'), str(sch), '--netlist', xml, '--cli', env['cli'])
    stale = [l for l in out.splitlines() if 'STALE' in l]
    assert rc == 1 and len(stale) == 1 and 'Q2 is now C316138' in stale[0] and '3.0 mOhm' in stale[0] and 'R26' in stale[0], out
    assert all('--region' in c for c in calls(env) if c[0] == 'search')


def test_bom_check_ics_need_a_local_datasheet(env):
    """every IC's datasheet is saved in the project (docs/datasheets): found by MPN or value in the file name"""
    write_sourcing(env)
    sch = env['proj'] / 'hardware' / 'x.kicad_sch'; sch.write_text('')
    xml = netlist(env, [comp('U1', 'TPS63802', 'C316138', mpn='TPS63802DLAR'), comp('U2', 'HY2113-GB3A', '', mpn='HY2113-GB3A'),
                        comp('R7', '100', 'C25076', fp='Resistor_SMD:R_0402_1005Metric')])
    rc, out = sh(os.path.join(HERE, 'bom_check.py'), str(sch), '--netlist', xml, '--cli', env['cli'], '--no-derived')
    assert 'no docs/datasheets folder found' in out and 'NO LOCAL DATASHEET U1' in out and 'NO LOCAL DATASHEET U2' in out and rc == 1, out
    dd = env['proj'] / 'docs' / 'datasheets'; dd.mkdir()
    (dd / 'tps63802.pdf').write_bytes(b'%PDF'); (dd / 'HY2113-GB3A_protector.pdf').write_bytes(b'%PDF')
    rc, out = sh(os.path.join(HERE, 'bom_check.py'), str(sch), '--netlist', xml, '--cli', env['cli'], '--no-derived')
    assert 'every IC has one' in out and 'NO LOCAL DATASHEET' not in out and rc == 0, out


def test_derived_check_deps_coverage_and_incomplete(env):
    parts = {'Q2': dict(lcsc='C316138', mpn='', value='DMN1004UFV', footprint=''), 'U3': dict(lcsc='', mpn='HY2113-GB3A', value='HY2113', footprint=''),
             'L1': dict(lcsc='C1', mpn='', value='1u', footprint='')}
    data = {'values': [dict(name='trip', value='12.5 A', depends_on=[dict(ref='Q2', part='C3289423', param='Rds', used='3 mOhm'),
                                                                   dict(ref='U3', part='hy2113-gb3a', param='V_OCD', used='75 mV'),
                                                                   dict(part='cell', param='R_int', used='20 mOhm')]),
                       dict(name='snubber', value='1 nF')]}
    probs, cov = derived_check.check(data, parts)
    assert any(p.startswith('STALE: Q2 is now C316138') for p in probs)
    assert not any('U3' in p for p in probs)                              # MPN matches, case-insensitive
    assert any(p.startswith('INCOMPLETE value snubber') for p in probs)
    assert '1 not checkable' in cov and 'no value names L1' in cov
    out = derived_check.deps(data, parts, {'U3'})
    assert len(out) == 1 and out[0].startswith('trip = 12.5 A') and 'V_OCD' in out[0]
    parts.pop('Q2')
    probs, _ = derived_check.check(data, parts)
    assert any('Q2 is not on the schematic any more' in p for p in probs)


def test_ti_device_page_for_order_codes():
    """fixed-voltage order codes carry the voltage mid-name (TLV755+18+P+DRVR -> page TLV755P), SN74 logic is TI;
    the pages are what ti.com answered on 2026-10-30 (anything else 404)"""
    pages = {'TLV755P', 'TLV767', 'SN74LV1T04', 'TLV700', 'TPS7A20', 'TLV1117LV', 'TPS61089', 'TPS61088-Q1'}
    life = lambda c: 'ACTIVE' if c in pages else 'SUSPECT (product page HTTP 404)'
    orig = part_gate.ti_lifecycle
    part_gate.ti_lifecycle = life
    try:
        got = {n: part_gate.ti_resolve(n) for n in ('TLV75518PDRVR', 'TLV75518PDBVR', 'TLV76718DRVR', 'SN74LV1T04DBVR',
                                                     'TLV70033DDCR', 'TPS7A2033PDBVR', 'TLV1117LV33DCYR', 'TPS61089RNRR',
                                                     'TPS61088QRHLRQ1', 'TPS99999RGTR')}
    finally:
        part_gate.ti_lifecycle = orig
    assert got['TLV75518PDRVR'] == got['TLV75518PDBVR'] == ('ACTIVE', 'TLV755P')
    assert got['TLV76718DRVR'] == ('ACTIVE', 'TLV767') and got['SN74LV1T04DBVR'] == ('ACTIVE', 'SN74LV1T04')
    assert got['TLV70033DDCR'][1] == 'TLV700' and got['TPS7A2033PDBVR'][1] == 'TPS7A20' and got['TLV1117LV33DCYR'][1] == 'TLV1117LV'
    assert got['TPS61089RNRR'][1] == 'TPS61089' and got['TPS61088QRHLRQ1'][1] == 'TPS61088-Q1'
    assert got['TPS99999RGTR'][0].startswith('SUSPECT')
    # the plain trims are still tried before a voltage code is taken out
    c = part_gate.ti_candidates('TLV75518PDRVR')
    assert c.index('TLV75518') < c.index('TLV755PDRVR') and 'TLV7PDRVR' not in c
    assert all(part_gate.is_ti(n) for n in ('SN74LV1T04DBVR', 'SN65HVD230DR', 'TXS0108EPWR', 'TXB0104RUTR', 'ISO7721DR',
                                            'ISOW7841DWER', 'OPA333AIDBVR', 'REF3033AIDBZR', 'TMP117AIDRVR'))
    assert not any(part_gate.is_ti(n) for n in ('ISO1H811G', 'REF02', 'REF195', 'TMP36', 'CL21A106KAYNNNE', 'XC6206P332MR'))


MPN_DATA = {'global': {  # the catalogue's order for "CL21A106KAYNNNE" on 2026-10-30: placeholder, cross-reference, Samsung
    'C9900069401': ('CL21A106KAYNNNE', '', '0.0399', 'JLCPCB Assembly'),
    'C5137488': ('FCC0805X106K250FT', '173608', '0.041', 'FOJAN', ['CL21A106KAYNNNE', 'CL21A106KAYNNNX']),
    'C15850': ('CL21A106KAYNNNE', '8411453', '0.0437', 'Samsung Electro-Mechanics'),
    'C9900184415': ('USB_C_Receptacle_USB2.0_16P', '', '0.0399', 'JLCPCB Assembly', ['USB Type-C 16P receptacle SMD'])}, 'cn': {}}


def test_search_exact_mpn_first_no_placeholders(env):
    """an MPN search answers with that MPN (not the catalogue's first pick, a cross-reference), placeholders are left
    out, a part number with no exact match and a 0-result phrase both say what happened"""
    (env['tmp'] / 'data.json').write_text(json.dumps(MPN_DATA))
    rows = sourcing.search('CL21A106KAYNNNE', 'global', env['cli'], n=1)
    assert [r['lcsc'] for r in rows] == ['C15850'], rows
    assert all(c[c.index('-n') + 1] == '30' for c in calls(env))         # fetched deep enough to find it
    assert sourcing.lookup('C9900069401', 'global', env['cli'])['lcsc'] == 'C9900069401'   # its own C-number still finds it
    run = lambda *q: sh(os.path.join(HERE, 'sourcing.py'), 'search', *q, '--region', 'global', '--cli', env['cli'], '-n', '1')
    rc, out = run('CL21A106KAYNNNE')
    assert rc == 0 and 'C15850' in out and 'C5137488' not in out and 'C9900069401' not in out, out
    assert '1 "JLCPCB Assembly" placeholder' in out and 'no result is' not in out, out
    rc, out = run('CL21A106KAYNNNE', '--placeholders')
    assert 'placeholder' not in out and '1 result(s)' in out, out
    rc, out = run('CL21A106KAYNNNX')
    assert 'C5137488' in out and 'note: no result is CL21A106KAYNNNX itself' in out and 'cross-reference' in out, out
    rc, out = run('USB Type-C 16P receptacle SMD')
    assert '0 result(s)' in out and 'matches keywords and part numbers, not descriptions' in out, out


def test_bom_check_one_part_on_two_bom_lines(env):
    """one LCSC number on parts with different Values (or footprints) is two order-BOM lines: JLC fits neither"""
    data = json.loads(json.dumps(STOCK)); data['global']['C2286'] = ('KT-0603R', '7277385', '0.0077')
    (env['tmp'] / 'data.json').write_text(json.dumps(data))
    write_sourcing(env)
    sch = env['proj'] / 'hardware' / 'x.kicad_sch'; sch.write_text('')
    led = 'LED_SMD:LED_0603_1608Metric'
    run = lambda comps: sh(os.path.join(HERE, 'bom_check.py'), str(sch), '--netlist', netlist(env, comps), '--cli', env['cli'],
                           '--no-derived', '--no-local-datasheets')
    rc, out = run([comp('D1', 'TX (red)', 'C2286', fp=led), comp('D2', 'RX (red)', 'C2286', fp=led)])
    assert rc == 1 and 'SPLIT: 2 BOM lines for one part (D1 "TX (red)" / D2 "RX (red)")' in out and 'footprint' not in out.split('SPLIT')[1].splitlines()[0], out
    rc, out = run([comp('D1', 'red', 'C2286', fp=led), comp('D2', 'red', 'C2286', fp='LED_SMD:LED_0805_2012Metric')])
    assert rc == 1 and 'D2 "red" LED_0805_2012Metric' in out and 'one Value and footprint' in out, out
    rc, out = run([comp('D1', 'red', 'C2286', fp=led), comp('D2', 'red', 'C2286', fp=led)])
    assert rc == 0 and 'SPLIT' not in out, out


@pytest.mark.skipif(not os.environ.get('LCSC_LIVE'), reason='set LCSC_LIVE=1 to query LCSC for real')
def test_live_regions():
    """the real case: C3289423 stocked in cn only, C316138 stocked in global (2026-10-25; stock moves)"""
    g = sourcing.lookup('C3289423', 'global'); c = sourcing.lookup('C3289423', 'cn')
    assert g is not None and g['stock'] == 0 and c['stock'] > 0
    assert sourcing.lookup('C316138', 'global')['stock'] > 0
