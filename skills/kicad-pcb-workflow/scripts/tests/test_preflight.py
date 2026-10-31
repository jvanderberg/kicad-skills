"""preflight.py on a machine without the tools (python3 tests/test_preflight.py): every check reports, none crashes.
A fresh setup is what preflight is for, so a missing jlcimport-cli must read MISSING, not a traceback."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_tools_on_path_reports_missing():
    env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent'}
    for what in ('parts', 'board'):
        r = subprocess.run([sys.executable, os.path.join(HERE, 'preflight.py'), '--for', what], capture_output=True, text=True, env=env)
        assert 'Traceback' not in r.stderr, r.stderr
        assert 'jlcimport-cli production (order files)' in r.stdout and 'no jlcimport-cli' in r.stdout, r.stdout


def test_unknown_jlcimport_version_is_unknown_not_old():
    """a launcher that is not a python script (a shell wrapper, a frozen .exe) has no readable version: preflight says
    so and passes, as bom_check.py notes it (jlcversion.py), instead of calling it older than v1.7.0"""
    import tempfile
    d = tempfile.mkdtemp()
    cli = os.path.join(d, 'jlcimport-cli')
    with open(cli, 'w') as f:
        f.write('#!/bin/sh\n[ "$1" = production ] && echo "usage: production [--check-only]" && exit 0\nexit 2\n')
    os.chmod(cli, 0o755)
    env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'JLCIMPORT_CLI': cli}
    r = subprocess.run([sys.executable, os.path.join(HERE, 'preflight.py'), '--for', 'parts'], capture_output=True, text=True, env=env)
    line = next(l for l in r.stdout.splitlines() if l.startswith('jlcimport-cli production'))
    assert 'version unknown' in line and 'before v1.7.0' not in line and ' ok ' in line, r.stdout + r.stderr
    sys.path.insert(0, HERE)
    import jlcversion
    assert jlcversion.cli_version(cli) is None


if __name__ == '__main__':
    test_no_tools_on_path_reports_missing(); test_unknown_jlcimport_version_is_unknown_not_old(); print('PASS')
