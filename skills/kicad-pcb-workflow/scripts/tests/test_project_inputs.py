"""Project-input discovery and the pin audit, on synthetic files:  python3 tests/test_project_inputs.py
- projfiles.py finds docs/pin-decisions.json at the repository root for a project in hardware/ (not the repo root)
- nc_audit.py treats a pin the symbol types no_connect like any other unused pin: it needs a note, and the datasheet
  pin-table line is shown next to it (a part whose NC pins must be grounded and one whose NC pins must float)."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import projfiles

NET = '''<export version="E"><components>
<comp ref="U1"><value>BOOSTER</value></comp><comp ref="U2"><value>SENSOR</value></comp></components><nets>
<net code="1" name="unconnected-(U1-NC-Pad11)"><node ref="U1" pin="11" pinfunction="NC" pintype="no_connect"/></net>
<net code="2" name="unconnected-(U2-DNC-Pad3)"><node ref="U2" pin="3" pinfunction="DNC" pintype="no_connect"/></net>
<net code="3" name="GND"><node ref="U1" pin="1" pinfunction="GND" pintype="power_in"/><node ref="U2" pin="1" pinfunction="GND" pintype="power_in"/></net>
</nets></export>'''
DS1 = 'Pin Functions\nNAME   NO.   I/O   DESCRIPTION\n          No connection inside. Connect these pins to the ground plane\nNC     11, 12  -\n          for thermal dissipation\n'
DS2 = 'Pin Functions\nDNC    3    -   Do not connect. Must be left floating (factory test)\n'


def tree():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, '.git')); os.makedirs(os.path.join(root, 'hardware')); os.makedirs(os.path.join(root, 'docs'))
    open(os.path.join(root, 'hardware', 'net.xml'), 'w').write(NET)
    open(os.path.join(root, 'ds1.txt'), 'w').write(DS1); open(os.path.join(root, 'ds2.txt'), 'w').write(DS2)
    return root


def nc(root, *args):
    return subprocess.run([sys.executable, os.path.join(HERE, 'nc_audit.py'), os.path.join(root, 'hardware', 'net.xml'), *args],
                          capture_output=True, text=True)


def test_projfiles_finds_repo_root_docs_from_hardware():
    root = tree()
    json.dump({}, open(os.path.join(root, 'docs', 'pin-decisions.json'), 'w'))
    p, looked, _ = projfiles.find(os.path.join(root, 'hardware'), 'pin-decisions.json')
    assert p == os.path.join(root, 'docs', 'pin-decisions.json'), (p, looked)
    p, looked, _ = projfiles.find(os.path.join(root, 'hardware'), 'review_config.json')
    assert p is None and looked[-1] == os.path.join(root, 'docs', 'review_config.json'), looked   # stops at the repo root


def test_symbol_nc_pins_need_notes_and_show_pin_table():
    root = tree()
    r = nc(root, '--require-notes', '--datasheet', 'U1=%s/ds1.txt' % root, '--datasheet', 'SENSOR=%s/ds2.txt' % root)
    assert r.returncode == 1, r.stdout                      # symbol-NC pins without a note fail --require-notes
    assert '2 without a decision' in r.stdout, r.stdout
    assert 'Connect these pins to the ground plane' in r.stdout and 'Must be left floating' in r.stdout, r.stdout
    assert 'no pin-decisions.json found' in r.stderr, r.stderr
    json.dump({'U1.11': 'NC: ground per pin table (thermal)', 'U2.3': 'DNC: left floating per pin table'},
              open(os.path.join(root, 'docs', 'pin-decisions.json'), 'w'))
    r = nc(root, '--require-notes')                         # found by discovery, no --notes needed
    assert r.returncode == 0 and '0 without a decision' in r.stdout, (r.stdout, r.stderr)
    assert 'found by search' in r.stderr, r.stderr


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
