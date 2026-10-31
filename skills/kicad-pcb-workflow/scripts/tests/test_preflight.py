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


if __name__ == '__main__':
    test_no_tools_on_path_reports_missing(); print('PASS')
