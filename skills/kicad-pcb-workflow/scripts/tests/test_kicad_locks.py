"""kicad_locks.py: a lock file alone is not "KiCad is open" (plain python 3):   python3 tests/test_kicad_locks.py
A stale lock with no KiCad process holding the folder is STALE (safe; --clean removes it); a process named like the
editor whose working directory is the folder is OPEN; cleanup_locks removes only locks that appear during its block."""
import os, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kicad_locks


def run(*a):
    r = subprocess.run([sys.executable, os.path.join(HERE, 'kicad_locks.py'), *a], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_stale_lock_is_not_open():
    d = tempfile.mkdtemp()
    open(os.path.join(d, '~p.kicad_pro.lck'), 'w').write('{"hostname":"h","username":"u"}')
    rc, out = run('status', d)
    assert rc == 0 and out.startswith('STALE') and 'not open' not in out, out
    rc, out = run('status', d, '--clean')
    assert rc == 0 and 'removed 1 stale lock' in out and not os.listdir(d), out
    rc, out = run('status', d)
    assert rc == 0 and 'not open' in out, out


def test_editor_holding_the_folder_is_open():
    """a process the editor pattern matches (here a stand-in whose listed command is the editor's), with its working
    directory in the folder, is OPEN; a lock file is not needed for that, and another folder stays CLOSED"""
    if not (shutil.which('lsof') or os.path.isdir('/proc')):
        print('  (skipped: no lsof)'); return
    d = os.path.realpath(tempfile.mkdtemp())
    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], cwd=d)
    real = kicad_locks._procs
    kicad_locks._procs = lambda: [(p.pid, '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad')]
    try:
        time.sleep(0.3)
        state, rc, lines = kicad_locks.status(d)
        assert state == 'OPEN' and rc == 1 and 'pid %d' % p.pid in lines[0], lines
        assert kicad_locks.status(tempfile.mkdtemp())[0] == 'CLOSED'
        kicad_locks._procs = lambda: None                      # no process list at all: a lock is UNSURE, never OPEN
        open(os.path.join(d, '~p.kicad_pro.lck'), 'w').write('x')
        assert kicad_locks.status(d)[0] == 'UNSURE'
    finally:
        kicad_locks._procs = real
        p.kill(); p.wait()


def test_cleanup_removes_only_new_locks():
    d = tempfile.mkdtemp()
    old = os.path.join(d, '~old.kicad_pcb.lck'); open(old, 'w').write('x')
    with kicad_locks.cleanup_locks(os.path.join(d, 'board.kicad_pcb')):
        open(os.path.join(d, '~new.kicad_pro.lck'), 'w').write('x')       # what kicad-cli leaves behind
    assert os.listdir(d) == ['~old.kicad_pcb.lck'], os.listdir(d)
    r = kicad_locks.cli_run([sys.executable, '-c', 'open(%r, "w").write("x")' % os.path.join(d, '~cli.lck')], d)
    assert r.returncode == 0 and os.listdir(d) == ['~old.kicad_pcb.lck'], os.listdir(d)


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
