"""refparts.py against a synthetic buck that differs from any one board:  python3 tests/test_refparts.py
The datasheet asks for a bootstrap cap, a 100 nF high-frequency input cap at VIN and a 10 uF bulk input cap. The
design has the bulk cap only (twice: 10 uF) and no bootstrap cap: the HF entry must not be satisfied by a bulk cap,
and one schematic part must not satisfy two datasheet parts."""
import os, subprocess, sys, tempfile, json
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import refparts
import xml.etree.ElementTree as ET

NET = '''<export version="E"><components>
<comp ref="U1"><value>BUCK1</value></comp><comp ref="C1"><value>10uF</value></comp><comp ref="L1"><value>2.2uH</value></comp>
</components><nets>
<net code="1" name="VIN"><node ref="U1" pin="1" pinfunction="VIN_1" pintype="power_in"/><node ref="C1" pin="1" pintype="passive"/></net>
<net code="2" name="GND"><node ref="U1" pin="2" pinfunction="GND_2" pintype="power_in"/><node ref="C1" pin="2" pintype="passive"/></net>
<net code="3" name="Net-(L1-Pad1)"><node ref="U1" pin="3" pinfunction="SW_3" pintype="power_out"/><node ref="L1" pin="1" pintype="passive"/></net>
<net code="4" name="Net-(U1-BST)"><node ref="U1" pin="4" pinfunction="BST_4" pintype="passive"/></net>
<net code="5" name="+3V3"><node ref="L1" pin="2" pintype="passive"/></net>
</nets></export>'''
SPEC = {'U1': {'part': 'BUCK1', 'source': 'synthetic datasheet fig. 1', 'parts': [
    {'role': 'bulk input cap', 'kind': 'C', 'between': ['VIN', 'GND'], 'value': '10u'},
    {'role': 'HF input cap at VIN', 'kind': 'C', 'between': ['VIN', 'GND'], 'value': '100n', 'tol': 0.5},
    {'role': 'second bulk input cap', 'kind': 'C', 'between': ['VIN', 'GND'], 'value': '10u'},
    {'role': 'bootstrap', 'kind': 'C', 'between': ['BST', 'SW'], 'value': '100n'}]}}


def test_missing_and_wrong_value_are_named():
    rows = refparts.check(SPEC, *refparts.load_netlist(ET.fromstring(NET)), {})
    st = {r['role']: r['status'] for r in rows}
    assert st['bulk input cap'].startswith('ok: C1'), st
    assert st['HF input cap at VIN'].startswith('MISSING') and 'C1, which is "bulk input cap"' in st['HF input cap at VIN'], st
    assert st['second bulk input cap'].startswith('MISSING'), st          # C1 already used once
    assert st['bootstrap'].startswith('MISSING: no C between Net-(U1-BST) and Net-(L1-Pad1)'), st


def test_cli_exit_status():
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'net.xml'), 'w').write(NET); json.dump(SPEC, open(os.path.join(d, 'reference-parts.json'), 'w'))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'refparts.py'), os.path.join(d, 'net.xml')], capture_output=True, text=True)
    assert r.returncode == 1 and '4 required parts, 3 not satisfied' in r.stdout, (r.stdout, r.stderr)
    assert 'found by search' in r.stderr


# a sheet placed twice (/b1/, /b2/), in KiCad's netlist form: one symbol uuid per part, each instance's sheet path.
# The bank rail enters each instance through a hierarchical label and the parent names it (/BANK1, /BANK2).
def comp(ref, uuid, sheet):
    return ('<comp ref="%s"><value>%s</value><property name="Sheetfile" value="%s"/><sheetpath names="%s" '
            'tstamps="/%s/"/><tstamps>%s</tstamps></comp>' % (ref, {'C': '100n', 'R': '33'}.get(ref[0], 'IC'),
                                                             'b.kicad_sch' if sheet != '/' else 'top.kicad_sch', sheet,
                                                             sheet.strip('/') or 'root', uuid))


def instances(nets, sheets=('/b1/', '/b2/')):
    """the netlist of U, C, R on each instance sheet (U101, C101, R101 on the first, U201 ... on the second, ...) plus
    C9 (+5V to GND) on the root; nets: {name: ['U101.4', ...]}"""
    parts = [comp('%s%d01' % (p, k), p.lower() * 2, sh) for k, sh in enumerate(sheets, 1) for p in 'UCR'] + \
        [comp('C9', 'c9', '/')]
    fn = {'1': 'GND', '2': 'OUT', '3': 'CLR', '4': 'VCC'}
    net = lambda name, pins: '<net name="%s">%s</net>' % (name, ''.join(
        '<node ref="%s" pin="%s"%s/>' % (r, n, ' pinfunction="%s"' % fn[n] if r[0] == 'U' else '')
        for r, n in (p.split('.') for p in pins)))
    return ET.fromstring('<export version="E"><components>%s</components><nets>%s</nets></export>' % (
        ''.join(parts), ''.join(net(k, v) for k, v in nets.items())))


BASE = {'/b1/OUT': ['R101.2', 'U101.2'], '/b2/OUT': ['R201.2', 'U201.2'], '+5V': ['C9.1', 'U101.4', 'U201.4']}


def rows_for(spec, nets, sheets=('/b1/', '/b2/')):
    root = instances(nets, sheets)
    comps, pins = refparts.load_netlist(root)
    sib = refparts.siblings(root)
    extra = (sib,) if 'sib' in refparts.check.__code__.co_varnames else ()       # (older check() had no sib)
    rows = refparts.check(refparts.expand_instances(spec, sib, pins), comps, pins, {}, *extra)
    return {(r['ic'], r['role']): r['status'] for r in rows}


def test_instance_nets_the_ic_has_no_pin_on():
    """re-check finding 1: U has no pin on the bank rail; /BANK1 still reaches U201's instance as /BANK2, through
    C101.1 -> C201.1: no false pass on bank 1's C101, no false MISSING for U201's series resistor"""
    nets = dict(BASE, **{'/BANK1': ['C101.1', 'R101.1'], '/BANK2': ['C201.1', 'R201.1'],
                         'GND': ['C101.2', 'C201.2', 'C9.2', 'U101.1', 'U201.1', 'U101.3', 'U201.3']})
    st = rows_for({'U101': {'parts': [
        {'role': 'bank cap', 'kind': 'C', 'between': ['net:/BANK1', 'GND'], 'value': '100n'},
        {'role': 'series R', 'kind': 'R', 'between': ['net:/BANK1', 'net:/b1/OUT'], 'value': '33'}]}}, nets)
    assert st[('U101', 'bank cap')].startswith('ok: C101') and st[('U201', 'bank cap')].startswith('ok: C201'), st
    assert st[('U101', 'series R')].startswith('ok: R101') and st[('U201', 'series R')].startswith('ok: R201'), st


def test_a_net_wired_differently_in_another_instance_is_ambiguous():
    """re-check finding 2: on b1, U101's CLR is on the bank rail with C101; the parent ties b2's CLR to GND. The entry
    does not carry over (it became "pin:3", and with "pin:a,b" one pad on GND satisfied both endpoints)"""
    nets = dict(BASE, **{'/BANK1': ['C101.1', 'U101.3'], '/BANK2': ['C201.1'],
                         'GND': ['C101.2', 'C201.2', 'C9.2', 'U101.1', 'U201.1', 'U201.3']})
    st = rows_for({'U101': {'parts': [{'role': 'rail cap', 'kind': 'C', 'between': ['net:/BANK1', 'GND'],
                                       'value': '100n'}]}}, nets)
    assert st[('U101', 'rail cap')].startswith('ok: C101'), st
    assert st[('U201', 'rail cap')].startswith('AMBIGUOUS') and '/BANK2 (C101.1)' in st[('U201', 'rail cap')] \
        and 'GND (U101.3)' in st[('U201', 'rail cap')], st
    st = rows_for({'U101': {'parts': [{'role': 'two nets', 'kind': 'C', 'between': ['pin:1,3', 'net:+5V']}]}}, nets)
    assert st[('U101', 'two nets')].startswith('AMBIGUOUS: endpoint pin:1,3 of U101 is on 2 nets'), st   # GND, /BANK1
    st = rows_for({'C9': {'parts': [{'role': 'both on GND', 'kind': 'C', 'between': ['GND', 'net:GND']}]}}, nets)
    assert st[('C9', 'both on GND')].startswith('MISSING'), st          # one pad on GND does not count twice


def test_a_global_net_stays_global_when_a_strap_differs():
    """third re-check, finding 1: CLR is strapped to +5V on b1 and to the instance's own rail on b2. "net:+5V" is +5V in
    every instance (a global net), not carried onto b2's rail through the strap pin (a false pass on C201); "net:GND"
    likewise (it gave a false AMBIGUOUS)"""
    nets = {'/b1/OUT': ['R101.2', 'U101.2'], '/b2/OUT': ['R201.2', 'U201.2'],
            '+5V': ['C9.1', 'U101.3'], '/BANK1': ['C101.1', 'U101.4'], '/BANK2': ['C201.1', 'U201.4', 'U201.3'],
            'GND': ['C101.2', 'C201.2', 'C9.2', 'U101.1', 'U201.1']}
    st = rows_for({'U101': {'parts': [{'role': '+5V cap', 'kind': 'C', 'between': ['net:+5V', 'GND'], 'value': '100n'},
                                      {'role': 'VCC cap', 'kind': 'C', 'between': ['VCC', 'net:GND'], 'value': '100n'}]}},
                  nets)
    assert st[('U101', '+5V cap')].startswith('ok: C9') and st[('U201', '+5V cap')].startswith('ok: C9'), st
    assert st[('U101', 'VCC cap')].startswith('ok: C101') and st[('U201', 'VCC cap')].startswith('ok: C201'), st
    nets['GND'].remove('U101.1'); nets['GND'].append('U101.3'); nets['+5V'].remove('U101.3'); nets['+5V'].append('U101.1')
    st = rows_for({'U101': {'parts': [{'role': 'VCC cap', 'kind': 'C', 'between': ['VCC', 'net:GND'], 'value': '100n'}]}},
                  nets)                                          # b1's CLR on GND, b2's on its own rail
    assert st[('U201', 'VCC cap')].startswith('ok: C201'), st


def test_only_its_own_instance_parts_satisfy_an_ic():
    """third re-check, finding 2: two instances on one shared bank rail, b2's cap deleted. U201 must not pass on
    C101 (b1's), nor U101 on C201; a root part still counts. Nested: the same between /g1/l1/ and /g1/l2/, /g2/l1/."""
    nets = {'/b1/OUT': ['R101.2', 'U101.2'], '/b2/OUT': ['R201.2', 'U201.2'], '+5V': ['C9.1'],
            '/BANK1': ['C101.1', 'U101.4', 'U201.4'], 'GND': ['C101.2', 'C9.2', 'U101.1', 'U201.1']}
    spec = {'U101': {'parts': [{'role': 'bypass', 'kind': 'C', 'between': ['VCC', 'GND'], 'value': '100n'}]}}
    st = rows_for(spec, nets)
    assert st[('U101', 'bypass')].startswith('ok: C101') and st[('U201', 'bypass')].startswith('MISSING'), st
    st = rows_for({'U201': spec['U101']}, dict(nets, **{'/BANK1': ['C201.1', 'U101.4', 'U201.4'],
                                                       'GND': ['C201.2', 'C9.2', 'U101.1', 'U201.1']}))
    assert st[('U201', 'bypass')].startswith('ok: C201') and st[('U101', 'bypass')].startswith('MISSING'), st
    st = rows_for(spec, dict(nets, **{'+5V': [], '/BANK1': ['C9.1', 'C101.1', 'U101.4', 'U201.4']}))
    assert st[('U201', 'bypass')].startswith('ok: C9'), st             # the parent's part is everyone's
    sheets = ('/g1/l1/', '/g1/l2/', '/g2/l1/')
    nested = {'/BANK1': ['C101.1', 'U101.4', 'U201.4', 'U301.4'], 'GND': ['C101.2', 'U101.1', 'U201.1', 'U301.1']}
    st = rows_for(spec, nested, sheets)
    assert st[('U101', 'bypass')].startswith('ok: C101'), st
    assert st[('U201', 'bypass')].startswith('MISSING') and st[('U301', 'bypass')].startswith('MISSING'), st


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
