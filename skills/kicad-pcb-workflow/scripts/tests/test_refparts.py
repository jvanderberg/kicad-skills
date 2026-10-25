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


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
