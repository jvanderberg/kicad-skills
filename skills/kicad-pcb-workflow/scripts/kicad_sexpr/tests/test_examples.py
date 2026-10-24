"""The README quickstart must produce a project KiCad accepts cleanly: ERC 0, DRC 0, 0 unconnected, parity 0."""
import os
import subprocess
import sys

from helpers import HERE, SHARE, drc, erc, need_share, tmpdir


def test_quickstart_is_clean():
    need_share()
    d = tmpdir('quickstart')
    script = os.path.join(os.path.dirname(HERE), 'examples', 'quickstart.py')
    r = subprocess.run([sys.executable, script, d], capture_output=True, text=True,
                       env=dict(os.environ, KICAD_SHARE=SHARE))
    assert r.returncode == 0, r.stderr
    assert erc(os.path.join(d, 'demo.kicad_sch')) == {}
    res = drc(os.path.join(d, 'demo.kicad_pcb'), refill=True, parity=True)
    assert res['violations'] == {} and res['unconnected'] == 0 and res['parity'] == 0, res['violations']
