#!/usr/bin/env python3
"""Pin the kicad-skills revision (and KiCad version) a project builds with, and check it before every build.

  skills_rev.py show                         # this checkout: revision, clean or not, published or not
  skills_rev.py pin PROJECT_DIR              # write PROJECT_DIR/kicad-skills.lock (refuses a dirty or unpublished rev)
  skills_rev.py check PROJECT_DIR            # exit 1 unless this checkout and kicad-cli match the project's lock

A project that imports kicad-skills' writers (kicad_sexpr, schgen, new_board, router...) gets byte-identical
regeneration only from the revision it was built with: on one board a build against GitHub main wrote random uuids
(an ~18,000-line diff for an unchanged design) because the deterministic writer existed only on an unpublished local
branch. The lock names the exact commit; `check` fails when the checkout in use differs from it, has uncommitted
changes under skills/, or KiCad's major.minor differs (KiCad's version decides the canonical file form).

kicad-skills.lock (JSON, committed with the project, found by projfiles.py's convention):
  {"kicad_skills": {"rev": "<40-hex commit>", "url": "https://github.com/jvanderberg/kicad-skills"}, "kicad": "10.0"}

From a project build (e.g. tools/kskills.py, see assets/kskills.py):
  import skills_rev; skills_rev.require(PROJECT_DIR)      # raises SystemExit with the fix when it does not match
To build an old project with its own revision without touching your main checkout:
  git -C <kicad-skills> worktree add ~/git/kicad-skills-<rev> <rev>   and point the project at that folder
"""
import json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def git(*a, cwd=HERE):
    r = subprocess.run(['git', *a], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip()


def checkout(skills_dir=None):
    """(repo root, rev, dirty files under skills/, remote branches containing rev) of the kicad-skills checkout"""
    d = skills_dir or HERE
    rc, root = git('rev-parse', '--show-toplevel', cwd=d)
    if rc:
        return None, None, [], []
    _, rev = git('rev-parse', 'HEAD', cwd=root)
    _, st = git('status', '--porcelain', '--', 'skills', cwd=root)
    dirty = [l[3:] for l in st.splitlines() if l.strip() and not l[3:].endswith(('.pyc',)) and '__pycache__' not in l]
    _, br = git('branch', '-r', '--contains', rev, cwd=root)
    return root, rev, dirty, [b.strip() for b in br.splitlines() if b.strip()]


def kicad_version():
    c = os.environ.get('KICAD_CLI') or ('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
                                        if os.path.exists('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli') else shutil.which('kicad-cli'))
    if not c:
        return None
    try:
        t = subprocess.run([c, 'version'], capture_output=True, text=True, timeout=60).stdout
    except OSError:
        return None
    m = re.search(r'(\d+)\.(\d+)', t)
    return '%s.%s' % m.groups() if m else None


def lock_path(project_dir):
    sys.path.insert(0, HERE)
    import projfiles
    return projfiles.find(project_dir, 'kicad-skills.lock')[0]


def check_project(project_dir, skills_dir=None):
    """(ok, message)"""
    lp = lock_path(project_dir)
    if not lp:
        return False, 'no kicad-skills.lock for %s: run skills_rev.py pin %s once, and commit it' % (project_dir, project_dir)
    lock = json.load(open(lp))
    want = lock.get('kicad_skills', {}).get('rev', '')
    root, rev, dirty, remote = checkout(skills_dir)
    if not root:
        return False, '%s is not a git checkout of kicad-skills: cannot prove its revision' % (skills_dir or HERE)
    probs = []
    if rev != want:
        probs.append('this checkout (%s) is at %s, the project is pinned to %s (%s): `git -C %s worktree add <dir> %s` and point the '
                     'project there, or re-pin after checking the rebuild diff' % (root, rev[:12], want[:12], lp, root, want[:12]))
    if dirty:
        probs.append('uncommitted changes under skills/: %s' % ', '.join(dirty[:6]))
    kv, kw = kicad_version(), lock.get('kicad')
    if kw and kv and kv != kw:
        probs.append('KiCad %s here, %s in the lock (canonical file form differs between versions)' % (kv, kw))
    if probs:
        return False, '; '.join(probs)
    return True, 'kicad-skills %s (%s) and KiCad %s as pinned in %s' % (rev[:12], 'published' if remote else 'NOT on any remote branch', kv or '?', lp)


def require(project_dir, skills_dir=None):
    ok, msg = check_project(project_dir, skills_dir)
    if not ok:
        raise SystemExit('kicad-skills revision check failed: ' + msg)
    return msg


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('show', 'pin', 'check'):
        sys.exit(__doc__)
    if sys.argv[1] == 'show':
        root, rev, dirty, remote = checkout()
        print('%s at %s; %s; %s; KiCad %s' % (root, rev, 'clean' if not dirty else 'DIRTY: ' + ', '.join(dirty[:8]),
                                             'on ' + ', '.join(remote[:3]) if remote else 'NOT on any remote branch (unpublished)', kicad_version()))
        return
    proj = sys.argv[2]
    if sys.argv[1] == 'check':
        ok, msg = check_project(proj)
        print(('ok: ' if ok else 'FAIL: ') + msg)
        sys.exit(0 if ok else 1)
    root, rev, dirty, remote = checkout()
    if dirty:
        sys.exit('refusing to pin: uncommitted changes under skills/ in %s (%s)' % (root, ', '.join(dirty[:6])))
    if not remote and '--allow-unpublished' not in sys.argv:
        sys.exit('refusing to pin %s: it is on no remote branch, so nobody else (and no fresh clone) can build with it. '
                 'Push it first, or pass --allow-unpublished for a local experiment' % rev[:12])
    _, url = git('config', '--get', 'remote.origin.url', cwd=root)
    out = os.path.join(proj, 'kicad-skills.lock') if os.path.isdir(proj) else proj
    json.dump({'kicad_skills': {'rev': rev, 'url': url}, 'kicad': kicad_version()}, open(out, 'w'), indent=1)
    open(out, 'a').write('\n')
    print('pinned kicad-skills %s and KiCad %s in %s' % (rev[:12], kicad_version(), out))


if __name__ == '__main__':
    main()
