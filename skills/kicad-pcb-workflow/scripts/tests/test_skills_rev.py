"""skills_rev.py in a throw-away kicad-skills clone:  python3 tests/test_skills_rev.py
pin refuses an unpublished commit; check passes on the pinned commit, fails on a dirty tree and on another commit."""
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True)


def test_pin_and_check():
    repo = tempfile.mkdtemp(); scripts = os.path.join(repo, 'skills', 'kicad-pcb-workflow', 'scripts'); os.makedirs(scripts)
    for f in ('skills_rev.py', 'projfiles.py'):
        shutil.copy(os.path.join(HERE, f), scripts)
    g = lambda *a: sh(repo, 'git', '-c', 'user.name=t', '-c', 'user.email=t@t', *a)
    g('init', '-q'); g('add', '.'); g('commit', '-qm', 'one')
    proj = tempfile.mkdtemp(); os.makedirs(os.path.join(proj, '.git'))
    rev = os.path.join(scripts, 'skills_rev.py')
    r = sh(proj, sys.executable, rev, 'pin', proj)
    assert r.returncode == 1 and 'no remote branch' in (r.stdout + r.stderr), r
    assert sh(proj, sys.executable, rev, 'pin', proj, '--allow-unpublished').returncode == 0
    r = sh(proj, sys.executable, rev, 'check', proj)
    assert r.returncode == 0 and r.stdout.startswith('ok'), r.stdout
    open(os.path.join(scripts, 'projfiles.py'), 'a').write('# local edit\n')
    r = sh(proj, sys.executable, rev, 'check', proj)
    assert r.returncode == 1 and 'uncommitted changes' in r.stdout, r.stdout
    g('commit', '-qam', 'two')
    r = sh(proj, sys.executable, rev, 'check', proj)
    assert r.returncode == 1 and 'pinned to' in r.stdout and 'worktree add' in r.stdout, r.stdout


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
