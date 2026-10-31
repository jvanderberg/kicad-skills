"""sourcing.py, part_gate.py, bom_check.py and derived_check.py against a fake jlcimport-cli (no network, no KiCad):
    python3 -m pytest -q tests          (LCSC_LIVE=1 also runs the real lookups in test_live_regions)
The fake CLI fails any search without --region, so every test also proves no lookup relies on the CLI's own default."""
import http.client, json, os, subprocess, sys, textwrap
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
    if a == ['--version']:
        sys.exit(0 if os.environ.get('FAKE_VERSION') and not print('jlcimport-cli ' + os.environ['FAKE_VERSION']) else 2)
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


# the product pages ti.com answered on 2026-10-30 (anything else 404); TLV70033 and TLV1117LV33 are ti.com's own
# redirects to TLV700 and TLV1117LV, so those order codes resolve without taking a voltage code out
TI_PAGES = {'TLV755P', 'TLV767', 'SN74LV1T04', 'TLV700', 'TLV70033', 'TPS7A20', 'TLV1117LV', 'TLV1117LV33', 'TPS61089',
            'TPS61088-Q1', 'TPS62840', 'TPS54360', 'LMS3655-Q1', 'LMG3410R050'}
V18, V33 = "'18' as a voltage code", "'33' as a voltage code"      # what ti_resolve says it dropped


@pytest.fixture()
def ti_pages(monkeypatch):
    """ti_lifecycle answered from a set of pages and ti_orderable_confirmed from a set of (page, order code) pairs
    (empty: every part-details request is a 404); every request is recorded"""
    pages, details, asked = set(TI_PAGES), set(), []

    def life(c):
        asked.append(c)
        return 'ACTIVE' if c in pages else 'SUSPECT (product page HTTP 404)'

    def confirmed(page, order):
        asked.append('%s/part-details/%s' % (page, order))
        return (page, order) in details
    monkeypatch.setattr(part_gate, 'ti_lifecycle', life)
    monkeypatch.setattr(part_gate, 'ti_orderable_confirmed', confirmed)
    return pages, asked, details


def test_ti_device_page_for_order_codes(ti_pages):
    """fixed-voltage order codes carry the voltage mid-name (TLV755+18+P+DRVR -> page TLV755P), SN74 logic is TI"""
    got = {n: part_gate.ti_resolve(n) for n in ('TLV75518PDRVR', 'TLV75518PDBVR', 'TLV76718DRVR', 'SN74LV1T04DBVR',
                                                 'TLV70033DDCR', 'TPS7A2033PDBVR', 'TLV1117LV33DCYR', 'TPS61089RNRR',
                                                 'TPS61088QRHLRQ1', 'TPS99999RGTR')}
    assert got['TLV75518PDRVR'] == got['TLV75518PDBVR'] == ('ACTIVE', 'TLV755P', V18, False)
    assert got['TLV76718DRVR'] == ('ACTIVE', 'TLV767', V18, False)
    assert got['SN74LV1T04DBVR'] == ('ACTIVE', 'SN74LV1T04', None, False)
    assert got['TPS7A2033PDBVR'] == ('ACTIVE', 'TPS7A20', V33, False)
    assert got['TLV70033DDCR'] == ('ACTIVE', 'TLV70033', None, False)
    assert got['TLV1117LV33DCYR'] == ('ACTIVE', 'TLV1117LV33', None, False)
    assert got['TPS61089RNRR'] == ('ACTIVE', 'TPS61089', None, False) and got['TPS61088QRHLRQ1'][1] == 'TPS61088-Q1'
    assert got['TPS99999RGTR'][0].startswith('SUSPECT')
    # the plain trims are still tried before a voltage code is taken out
    c = [n for n, _ in part_gate.ti_candidates('TLV75518PDRVR')]
    assert c.index('TLV75518') < c.index('TLV755PDRVR') and 'TLV7PDRVR' not in c
    assert all(part_gate.is_ti(n) for n in ('SN74LV1T04DBVR', 'SN65HVD230DR', 'TXS0108EPWR', 'TXB0104RUTR', 'ISO7721DR',
                                            'ISOW7841DWER', 'OPA333AIDBVR', 'REF3033AIDBZR', 'TMP117AIDRVR'))
    assert not any(part_gate.is_ti(n) for n in ('ISO1H811G', 'REF02', 'REF195', 'TMP36', 'CL21A106KAYNNNE', 'XC6206P332MR'))


def test_ti_candidates_short_and_capped(ti_pages):
    """LMS/LMG names: the prefix is LMS/LMG, not LM, so LMS3655's first digit group is not cut to LMS36; ordinary trims
    only drop letters; no part asks ti.com more than MAX_TI_REQUESTS times, even when no page exists at all"""
    names = lambda n: [c for c, _ in part_gate.ti_candidates(n)]
    lms, lmg = names('LMS3655AQRNLRQ1'), names('LMG3410R050RWHR')
    assert not any(c.startswith('LMS36A') or c in ('LMS36', 'LMS36-Q1') for c in lms), lms
    assert lmg == ['LMG3410R050RWHR', 'LMG3410R050RWH', 'LMG3410R050RW', 'LMG3410R050R', 'LMG3410R050'], lmg
    assert names('TPS61089RNRR') == ['TPS61089RNRR', 'TPS61089RNR', 'TPS61089RN', 'TPS61089R', 'TPS61089']
    for n in ('TPS62840DLCR', 'TPS54360DDAR', 'TPS61089RNRR'):    # 40, 60, 89 end device numbers, not voltages
        assert part_gate._without_voltage(n) == [] and all(code is None for _, code in part_gate.ti_candidates(n)), n
    pages, asked, _ = ti_pages
    pages.clear()
    for n in ('LMS3655AQRNLRQ1', 'LMG3410R050RWHR', 'TLV75518PDRVR', 'TPS7A2033PDBVR', 'TLV1117LV33DCYR',
              'SN74LVC1G04DBVR', 'TPS61088QRHLRQ1', 'TPS61230ADRRR', 'TLV1117LV33QDCYRQ1', 'LP5907MFX-3.3/NOPB',
              'TPS7A2033PDBVR-EXTRA-LONG-SUFFIX'):
        c = names(n)
        assert len(c) == len(set(c)), (n, c)
        del asked[:]
        assert part_gate.ti_resolve(n)[0].startswith('SUSPECT') and len(asked) <= part_gate.MAX_TI_REQUESTS, (n, asked)


def test_ti_budget_keeps_room_for_the_confirmation(ti_pages, monkeypatch):
    """ti_resolve owns the request count: a guess that would need a part-details confirmation is only asked for while
    both requests fit in MAX_TI_REQUESTS, so a page that could not be confirmed is never reported"""
    _, asked, details = ti_pages
    details.add(('TLV755P', 'TLV75518PDRVR'))
    for cap, want in ((12, ('ACTIVE', 'TLV755P', V18, True)), (11, None)):      # TLV755P is guess 11, its check 12
        monkeypatch.setattr(part_gate, 'MAX_TI_REQUESTS', cap)
        del asked[:]
        got = part_gate.ti_resolve('TLV75518PDRVR')
        assert len(asked) <= cap, (cap, asked)
        if want:
            assert got == want and len(asked) == 12, (got, asked)
        else:
            assert got[0].startswith('SUSPECT') and 'TLV755P' not in asked, (got, asked)


def test_ti_device_number_not_cut_to_another_device(ti_pages):
    """a discontinued TPS62840 (its own page gone) is SUSPECT, not "ACTIVE (as TPS628)": the 40 of a five-digit device
    number is not a voltage code, even when a page by the shorter name exists"""
    pages, asked, _ = ti_pages
    pages -= {'TPS62840', 'TPS54360'}
    pages |= {'TPS628', 'TPS543'}
    for n in ('TPS62840DLCR', 'TPS54360DDAR'):
        st, page, code, ok = part_gate.ti_resolve(n)
        assert st.startswith('SUSPECT') and page == n and code is None and not ok, (n, st, page)
        assert part_gate.gate_flag(part_gate.lifecycle_text(n, st, page, code, ok)) == 'LIFECYCLE'
    assert not {'TPS628', 'TPS543'} & set(asked), asked


def test_voltage_stripped_page_is_unconfirmed_and_fails_the_gate(env, ti_pages, monkeypatch, capsys):
    """TLV75518PDRVR's page is TLV755P, found only by taking '18' out, and its part-details page is not found (the
    fixture's default): ACTIVE?, not ACTIVE, and part_gate exits 1 even with stock; a page reached by trimming letters stays plain ACTIVE and passes"""
    st = part_gate.ti_resolve('TLV75518PDRVR')
    life = part_gate.lifecycle_text('TLV75518PDRVR', *st)
    assert life == "ACTIVE? (as TLV755P, found only by dropping '18' as a voltage code: confirm the device)", life
    assert part_gate.gate_flag(life) == 'LIFECYCLE UNCONFIRMED'
    plain = part_gate.lifecycle_text('TPS61089RNRR', *part_gate.ti_resolve('TPS61089RNRR'))
    assert plain == 'ACTIVE (as TPS61089)' and part_gate.gate_flag(plain) is None
    data = json.loads(json.dumps(STOCK))
    data['global'].update({'C2861882': ('TLV75518PDRVR', '50000', '0.1'), 'C843404': ('TPS61089RNRR', '50000', '0.9')})
    (env['tmp'] / 'data.json').write_text(json.dumps(data))
    write_sourcing(env)

    def gate(name):          # in-process, so ti_lifecycle stays the fake one
        monkeypatch.setattr(sys, 'argv', ['part_gate.py', name, '--project', str(env['proj']), '--cli', env['cli']])
        with pytest.raises(SystemExit) as e:
            part_gate.main()
        return e.value.code, capsys.readouterr().out
    rc, out = gate('TLV75518PDRVR')
    assert rc == 1 and 'ACTIVE? (as TLV755P' in out and '<-- LIFECYCLE UNCONFIRMED' in out, out
    rc, out = gate('TPS61089RNRR')
    assert rc == 0 and 'ACTIVE (as TPS61089)' in out and '<--' not in out, out


def test_voltage_stripped_page_confirmed_by_part_details(env, ti_pages, monkeypatch, capsys):
    """ti.com/product/<page>/part-details/<order code> answering 200 confirms a page found by dropping a voltage code:
    plain ACTIVE naming both, and the gate passes; a 404 keeps ACTIVE?. The request is one of MAX_TI_REQUESTS."""
    _, asked, details = ti_pages
    details |= {('TLV755P', 'TLV75518PDRVR'), ('TPS7A20', 'TPS7A2033PDBVR')}     # TLV767/TLV76718DRVR: 404 here
    got = {}
    for n in ('TLV75518PDRVR', 'TPS7A2033PDBVR', 'TLV76718DRVR', 'TPS61089RNRR'):
        del asked[:]
        got[n] = part_gate.ti_resolve(n)
        assert len(asked) <= part_gate.MAX_TI_REQUESTS, (n, asked)
        if got[n][2]:
            assert asked[-1] == '%s/part-details/%s' % (got[n][1], n), asked
        else:
            assert not any('part-details' in a for a in asked), asked     # only asked after dropping a code
    assert got['TLV75518PDRVR'] == ('ACTIVE', 'TLV755P', V18, True)
    assert got['TPS7A2033PDBVR'] == ('ACTIVE', 'TPS7A20', V33, True)             # its page is request 12, the check 13
    assert got['TLV76718DRVR'] == ('ACTIVE', 'TLV767', V18, False)
    life = part_gate.lifecycle_text('TLV75518PDRVR', *got['TLV75518PDRVR'])
    assert life == 'ACTIVE (as TLV755P; ti.com lists TLV75518PDRVR under it)' and part_gate.gate_flag(life) is None, life
    life = part_gate.lifecycle_text('TLV76718DRVR', *got['TLV76718DRVR'])
    assert life.startswith('ACTIVE? (as TLV767') and part_gate.gate_flag(life) == 'LIFECYCLE UNCONFIRMED', life
    data = json.loads(json.dumps(STOCK)); data['global']['C2868686'] = ('TLV75518PDRVR', '50000', '0.42')
    (env['tmp'] / 'data.json').write_text(json.dumps(data))
    write_sourcing(env)
    monkeypatch.setattr(sys, 'argv', ['part_gate.py', 'TLV75518PDRVR', '--project', str(env['proj']), '--cli', env['cli']])
    with pytest.raises(SystemExit) as e:
        part_gate.main()
    out = capsys.readouterr().out
    assert e.value.code == 0 and 'ACTIVE (as TLV755P; ti.com lists TLV75518PDRVR under it)' in out and '<--' not in out, out


def gate_run(env, monkeypatch, capsys, name, stock_mpn):
    """part_gate.main() in-process (so the fake ti_lifecycle stays) on one name with 50,000 in stock:
    (exit code, output)"""
    data = json.loads(json.dumps(STOCK)); data['global']['C999001'] = (stock_mpn, '50000', '0.1')
    (env['tmp'] / 'data.json').write_text(json.dumps(data))
    write_sourcing(env)
    monkeypatch.setattr(sys, 'argv', ['part_gate.py', name, '--project', str(env['proj']), '--cli', env['cli']])
    with pytest.raises(SystemExit) as e:
        part_gate.main()
    return e.value.code, capsys.readouterr().out


def test_ti_voltage_after_a_dash_or_dot(ti_pages):
    """LP5907MFX-3.3/NOPB, LP2985-33DBVR, LP5912-3.3DRVR carry the voltage after a "-": their pages (LP5907, LP2985,
    LP5912) are found by cutting at the first "-", "." or "/", which may name another device, so they count only when
    ti.com lists the orderable under the page (as it did on 2026-10-30, the "/" sent as is); no guess with a "/" is
    asked for"""
    pages, asked, details = ti_pages
    pages |= {'LP5907', 'LP2985', 'LP5912'}
    want = {'LP5907MFX-3.3/NOPB': ('LP5907', "the suffix '-3.3/NOPB'"),
            'LP2985-33DBVR': ('LP2985', "the suffix '-33DBVR'"), 'LP5912-3.3DRVR': ('LP5912', "the suffix '-3.3DRVR'")}
    for n, (page, why) in want.items():           # not listed under the page: ACTIVE?, fails the gate
        del asked[:]
        got = part_gate.ti_resolve(n)
        assert got == ('ACTIVE', page, why, False), (n, got)
        assert asked[-1] == '%s/part-details/%s' % (page, n) and len(asked) <= part_gate.MAX_TI_REQUESTS, asked
        assert not any('/' in a for a in asked[:-1]), asked
        life = part_gate.lifecycle_text(n, *got)
        assert life.startswith('ACTIVE? (as %s' % page) and part_gate.gate_flag(life) == 'LIFECYCLE UNCONFIRMED', life
    details |= {(page, n) for n, (page, _) in want.items()}
    for n, (page, why) in want.items():           # listed: plain ACTIVE naming both, passes
        got = part_gate.ti_resolve(n)
        life = part_gate.lifecycle_text(n, *got)
        assert got == ('ACTIVE', page, why, True) and part_gate.gate_flag(life) is None, (n, got)
        assert life == 'ACTIVE (as %s; ti.com lists %s under it)' % (page, n), life


def test_unreadable_status_on_a_dropped_page_fails_the_gate(env, ti_pages, monkeypatch, capsys):
    """a page found only by dropping a voltage code whose status cannot be read (403, 500, timeout, no status tag) is
    not confirmed (no part-details request is spent on it) and fails the gate: any "?" status does, lower case too"""
    assert part_gate.gate_flag(part_gate.lifecycle_text('TLV75518PDRVR', 'unknown (HTTP 403)', 'TLV755PDRVR', '18',
                                                        False)) == 'LIFECYCLE UNCONFIRMED'
    _, asked, details = ti_pages
    details.add(('TLV755PDRVR', 'TLV75518PDRVR'))
    fake = part_gate.ti_lifecycle
    for status in ('unknown (HTTP 403)', 'unknown (TimeoutError: timed out)',
                   'unknown (no status tag on https://www.ti.com/product/TLV755PDRVR)'):
        monkeypatch.setattr(part_gate, 'ti_lifecycle', lambda c, st=status: st if c == 'TLV755PDRVR' else fake(c))
        del asked[:]
        got = part_gate.ti_resolve('TLV75518PDRVR')
        assert got == (status, 'TLV755PDRVR', V18, False) and not any('part-details' in a for a in asked), (got, asked)
        life = part_gate.lifecycle_text('TLV75518PDRVR', *got)
        assert life.startswith(status + '? (as TLV755PDRVR') and part_gate.gate_flag(life) == 'LIFECYCLE UNCONFIRMED'
    rc, out = gate_run(env, monkeypatch, capsys, 'TLV75518PDRVR', 'TLV75518PDRVR')
    assert rc == 1 and '<-- LIFECYCLE UNCONFIRMED' in out, out


def test_ti_automotive_device_pages(ti_pages):
    """an automotive orderable (...Q1) tries its -Q1 device pages first, the voltage-dropped ones too
    (TPS7A1633QDGNRQ1 -> TPS7A16-Q1, TPS7B6933QDBVRQ1 -> TPS7B69-Q1, TLV75533PQWDRBRQ1 -> TLV755P-Q1), in a few
    requests; when no -Q1 page exists, the plain page it falls back to is another device: ACTIVE? unless ti.com lists
    the orderable under it"""
    pages, asked, details = ti_pages
    pages |= {'TPS7A16-Q1', 'TPS7B69-Q1', 'TLV755P-Q1', 'TPS7A16', 'TPS7B69', 'TPS61088'}
    want = {'TPS7A1633QDGNRQ1': 'TPS7A16-Q1', 'TPS7B6933QDBVRQ1': 'TPS7B69-Q1', 'TLV75533PQWDRBRQ1': 'TLV755P-Q1'}
    details |= {(page, n) for n, page in want.items()}
    for n, page in want.items():
        del asked[:]
        got = part_gate.ti_resolve(n)
        assert got == ('ACTIVE', page, V33, True) and len(asked) <= 4, (n, got, asked)
        assert part_gate.gate_flag(part_gate.lifecycle_text(n, *got)) is None
    pages -= set(want.values()) | {'TPS61088-Q1'}
    plain = {'TPS7A1633QDGNRQ1': 'TPS7A16', 'TPS7B6933QDBVRQ1': 'TPS7B69', 'TLV75533PQWDRBRQ1': 'TLV755P',
             'TPS61088QRHLRQ1': 'TPS61088'}
    for n, page in plain.items():
        st, got, why, ok = part_gate.ti_resolve(n)
        assert (st, got, ok) == ('ACTIVE', page, False) and why.endswith('the automotive grade (Q1)'), (n, got, why)
        life = part_gate.lifecycle_text(n, st, got, why, ok)
        assert life.startswith('ACTIVE? (as %s' % page) and part_gate.gate_flag(life) == 'LIFECYCLE UNCONFIRMED', life
    details.add(('TPS61088', 'TPS61088QRHLRQ1'))      # listed under the plain page after all: confirmed
    assert part_gate.ti_resolve('TPS61088QRHLRQ1') == ('ACTIVE', 'TPS61088', 'the automotive grade (Q1)', True)


def test_ti_requests_that_break_off_are_reported_not_raised(monkeypatch):
    """a response cut short (http.client.IncompleteRead) or a malformed one is "unknown" for a product page and "not
    confirmed" for part-details, not a crash"""
    class Cut:
        def geturl(self):
            return 'https://www.ti.com/product/TLV755P/part-details/TLV75518PDRVR'

        def read(self, n):
            raise http.client.IncompleteRead(b'<html>', 1000)

    def bad_status(req, timeout):
        raise http.client.BadStatusLine('HTTP/1.1 ???')
    for opener in (lambda req, timeout: Cut(), bad_status):
        monkeypatch.setattr(part_gate.urllib.request, 'urlopen', opener)
        assert part_gate.ti_orderable_confirmed('TLV755P', 'TLV75518PDRVR') is False
        st = part_gate.ti_lifecycle('TLV755P')
        assert st.startswith('unknown (') and ('IncompleteRead' in st or 'BadStatusLine' in st), st


def test_lookup_fetches_only_a_few_rows(env):
    """an exact C-number lookup asks the catalogue for a few rows (LOOKUP_FETCH), not the 30 a ranked search fetches"""
    write_sourcing(env)
    ctx = sourcing.resolve(str(env['proj']))
    assert sourcing.lookup('C316138', 'global', env['cli'])['part'] == 'DMN1004UFV-7'
    sourcing.check_part('C3289423', ctx, 3, env['cli'])           # short in global: both regions looked up
    ns = [c[c.index('-n') + 1] for c in calls(env)]
    assert len(ns) == 3 and all(int(n) <= 5 for n in ns), ns


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
    """one LCSC number on parts with different Values is two order-BOM lines before jlcimport-cli v1.7.0 (JLC fits
    neither); on different footprints it is a wrong part or footprint whatever the version"""
    data = json.loads(json.dumps(STOCK)); data['global']['C2286'] = ('KT-0603R', '7277385', '0.0077')
    (env['tmp'] / 'data.json').write_text(json.dumps(data))
    write_sourcing(env)
    sch = env['proj'] / 'hardware' / 'x.kicad_sch'; sch.write_text('')
    led = 'LED_SMD:LED_0603_1608Metric'
    run = lambda comps: sh(os.path.join(HERE, 'bom_check.py'), str(sch), '--netlist', netlist(env, comps), '--cli', env['cli'],
                           '--no-derived', '--no-local-datasheets')
    rc, out = run([comp('D1', 'TX (red)', 'C2286', fp=led), comp('D2', 'RX (red)', 'C2286', fp=led)])
    assert rc == 1 and 'SPLIT: 2 BOM lines for one part (D1 "TX (red)" LED_0603_1608Metric / D2 "RX (red)"' in out \
        and 'of unknown version' in out, out
    for v, flagged in (('1.6.7', True), ('1.7.0', False), ('1.8.2', False)):
        os.environ['FAKE_VERSION'] = v
        try:
            rc, out = run([comp('D1', 'TX (red)', 'C2286', fp=led), comp('D2', 'RX (red)', 'C2286', fp=led)])
        finally:
            del os.environ['FAKE_VERSION']
        assert (rc == 1 and '%s (older than v1.7.0)' % v in out) if flagged else (rc == 0 and 'SPLIT' not in out), (v, out)
    rc, out = run([comp('D1', 'red', 'C2286', fp=led), comp('D2', 'red', 'C2286', fp='LED_SMD:LED_0805_2012Metric')])
    assert rc == 1 and 'one LCSC number on 2 footprints' in out and 'D2 "red" LED_0805_2012Metric' in out, out
    rc, out = run([comp('D1', 'red', 'C2286', fp=led), comp('D2', 'red', 'C2286', fp=led)])
    assert rc == 0 and 'SPLIT' not in out, out


@pytest.mark.skipif(not os.environ.get('LCSC_LIVE'), reason='set LCSC_LIVE=1 to query LCSC for real')
def test_live_regions():
    """the real case: C3289423 stocked in cn only, C316138 stocked in global (2026-10-25; stock moves)"""
    g = sourcing.lookup('C3289423', 'global'); c = sourcing.lookup('C3289423', 'cn')
    assert g is not None and g['stock'] == 0 and c['stock'] > 0
    assert sourcing.lookup('C316138', 'global')['stock'] > 0
