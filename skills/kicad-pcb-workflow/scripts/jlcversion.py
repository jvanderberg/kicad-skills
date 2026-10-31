"""The installed JLCImport's version, for preflight.py and bom_check.py. Plain python 3, no dependencies; identical
copies in kicad-pcb-workflow, kicad-board-review and pcb-part-selection (tests/test_shared_copies.py).

jlcimport-cli has no --version option (v1.7.0). A pipx install is a python script whose first line names its venv's
python, so the version is read from that python's package metadata (`kicad-jlcimport`); `--version` is tried only
after that, for a future CLI that has it. Builds of main between the production command (PR #121) and v1.7.0 report
1.6.7. A launcher that is not a python script (a shell wrapper, a frozen .exe) gives None: unknown, which callers
report as unknown, never as old or new.
"""
import re, subprocess

ONE_BOM_LINE = (1, 7, 0)   # from v1.7.0 (PR #126) the order BOM puts each LCSC number on one line, whatever its Values


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return r.stdout if r.returncode == 0 else ''


def cli_version(cli):
    """(major, minor, patch) of the JLCImport behind the jlcimport-cli at `cli`, or None when it cannot be read"""
    if not cli:
        return None
    try:
        with open(cli, 'rb') as f:
            shebang = f.readline().decode('utf-8', 'replace')
    except OSError:
        shebang = ''
    probes = []
    if shebang.startswith('#!') and 'python' in shebang:
        probes.append(shebang[2:].split() + ['-c', "from importlib.metadata import version; print(version('kicad-jlcimport'))"])
    probes.append([cli, '--version'])
    for cmd in probes:
        m = re.search(r'(\d+)\.(\d+)\.(\d+)', _run(cmd))
        if m:
            return tuple(int(x) for x in m.groups())
    return None


def text(version):
    return 'version unknown' if version is None else '%d.%d.%d' % version
