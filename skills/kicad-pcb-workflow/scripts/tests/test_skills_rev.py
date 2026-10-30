"""skills_rev.py in a throw-away kicad-skills clone:  python3 tests/test_skills_rev.py
pin refuses an unpublished commit; check passes on the pinned commit, fails on a dirty tree and on another commit."""
import json, os, shutil, subprocess, sys, tempfile
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


def test_plugin_install_pinned_by_its_files():
    """a plugin cache folder (no .git): pinned by plugin version and a hash of skills/, not refused"""
    root = tempfile.mkdtemp(); scripts = os.path.join(root, 'skills', 'kicad-pcb-workflow', 'scripts'); os.makedirs(scripts)
    os.makedirs(os.path.join(root, '.claude-plugin'))
    open(os.path.join(root, '.claude-plugin', 'plugin.json'), 'w').write('{"name": "kicad-skills", "version": "0.1.0"}')
    for f in ('skills_rev.py', 'projfiles.py'):
        shutil.copy(os.path.join(HERE, f), scripts)
    assert sh(root, 'git', 'rev-parse', '--show-toplevel').returncode != 0, 'temp dir is inside a git repository'
    proj = tempfile.mkdtemp(); os.makedirs(os.path.join(proj, '.git'))
    rev = os.path.join(scripts, 'skills_rev.py')
    r = sh(proj, sys.executable, rev, 'pin', proj)
    assert r.returncode == 0 and 'plugin 0.1.0' in r.stdout, r.stdout + r.stderr
    lock = json.load(open(os.path.join(proj, 'kicad-skills.lock')))['kicad_skills']
    assert lock['plugin_version'] == '0.1.0' and len(lock['tree']) == 64, lock
    os.makedirs(os.path.join(scripts, '__pycache__')); open(os.path.join(scripts, '__pycache__', 'x.pyc'), 'w').write('x')
    r = sh(proj, sys.executable, rev, 'check', proj)
    assert r.returncode == 0 and r.stdout.startswith('ok') and 'plugin 0.1.0' in r.stdout, r.stdout + r.stderr
    open(os.path.join(scripts, 'projfiles.py'), 'a').write('# an update that kept the version number\n')
    r = sh(proj, sys.executable, rev, 'check', proj)
    assert r.returncode == 1 and 'different files under skills/' in r.stdout, r.stdout
    json.dump({'kicad_skills': {'rev': 'a' * 40}}, open(os.path.join(proj, 'kicad-skills.lock'), 'w'))
    r = sh(proj, sys.executable, rev, 'check', proj)                   # pinned to a commit: say how to get it
    assert r.returncode == 1 and 'not a git checkout' in r.stdout and 'git checkout aaaaaaaaaaaa' in r.stdout, r.stdout


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
