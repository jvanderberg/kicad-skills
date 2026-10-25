"""interp.py: a script started with the wrong python re-runs itself under the one that has its imports, and says so;
the helper runs KiCad's python with the analysis venv's packages:   python3 tests/test_interp.py"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import interp


def test_router_reexecs_under_the_analysis_venv():
    if interp.analysis_python() is None:
        print('  (skipped: no analysis venv)'); return
    env = {k: v for k, v in os.environ.items() if k != 'KSKILLS_REEXEC'}
    r = subprocess.run(['/usr/bin/env', '-i', 'HOME=' + os.path.expanduser('~'), 'PATH=/usr/bin:/bin', sys.executable,
                        os.path.join(HERE, 'router.py'), '--help'], capture_output=True, text=True, env=env)
    if 'shapely' in r.stderr and 're-running' not in r.stderr and r.returncode:
        raise AssertionError(r.stderr)
    assert r.returncode == 0 and 'usage' in r.stdout.lower(), r.stdout + r.stderr


def test_missing_module_after_reexec_stops_clearly():
    d = tempfile.mkdtemp(); s = os.path.join(d, 's.py')
    open(s, 'w').write('import sys; sys.path.insert(0, %r)\nfrom interp import need\nneed("no_such_module_xyz")\n' % HERE)
    r = subprocess.run([sys.executable, s], capture_output=True, text=True, env=dict(os.environ, KSKILLS_REEXEC='1'))
    assert r.returncode != 0 and 'no_such_module_xyz' in r.stderr and 'interp.py which' in r.stderr, r.stderr


def test_run_combines_pcbnew_and_shapely():
    k, a = interp.kicad_python(), interp.analysis_python()
    if not (k and a) or interp.combined_env(k, a)[0] is None:
        print('  (skipped: no KiCad python + analysis venv of the same version)'); return
    d = tempfile.mkdtemp(); s = os.path.join(d, 'both.py')
    open(s, 'w').write('import pcbnew, shapely\nprint("both", shapely.__version__)\n')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'interp.py'), 'run', s], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith('both'), r.stdout + r.stderr


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
