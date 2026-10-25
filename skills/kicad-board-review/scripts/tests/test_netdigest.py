"""netdigest.py's pin audits on a small kicadxml netlist (plain python 3):   python3 tests/test_netdigest.py
A chip-select / strobe between two ICs with no pull resistor to a rail is listed for a reset-state decision (its level
while either chip is in reset or unprogrammed is the chips' internal defaults); one with a pull-up is not."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NET = '''<?xml version="1.0" encoding="UTF-8"?>
<export version="E"><components>
<comp ref="U1"><value>MCU</value><footprint>QFN</footprint></comp>
<comp ref="U2"><value>BRIDGE</value><footprint>QFN</footprint></comp>
<comp ref="R1"><value>10k</value><footprint>R_0402</footprint></comp>
</components><nets>
<net code="1" name="+3V3"><node ref="U1" pin="1" pinfunction="VDD" pintype="power_in"/><node ref="U2" pin="1" pinfunction="VCC" pintype="power_in"/><node ref="R1" pin="1" pintype="passive"/></net>
<net code="2" name="GND"><node ref="U1" pin="2" pinfunction="GND" pintype="power_in"/><node ref="U2" pin="2" pinfunction="GND" pintype="power_in"/></net>
<net code="3" name="/RD_N"><node ref="U1" pin="3" pinfunction="GPIO3" pintype="bidirectional"/><node ref="U2" pin="3" pinfunction="RD#" pintype="input"/></net>
<net code="4" name="/CS"><node ref="U1" pin="4" pinfunction="GPIO4" pintype="bidirectional"/><node ref="U2" pin="4" pinfunction="~{CS}" pintype="input"/><node ref="R1" pin="2" pintype="passive"/></net>
<net code="5" name="/DATA"><node ref="U1" pin="5" pinfunction="GPIO5" pintype="bidirectional"/><node ref="U2" pin="5" pinfunction="D0" pintype="bidirectional"/></net>
</nets></export>'''


def test_control_lines_without_pull_need_a_reset_decision():
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'net.xml'), 'w').write(NET.replace('RD#', 'RD'))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'netdigest.py'), d, 't'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    md = open(os.path.join(d, 'netlist.md')).read()
    sec = md[md.index('### Control lines between ICs'):md.index('### BOM parts')]
    assert '/RD_N joins U1.3 GPIO3, U2.3 RD' in sec, sec          # no pull: a decision per state is needed
    assert '/CS' not in sec, sec                                  # pulled to +3V3 by R1
    assert '/DATA' not in sec, sec                                # a data line, not a control line


if __name__ == '__main__':
    test_control_lines_without_pull_need_a_reset_decision(); print('PASS')
