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
  {"kicad_skills": {"rev": "<40-hex commit>", "tree": "<sha256>", "url": "https://github.com/jvanderberg/kicad-skills"},
   "kicad": "10.0"}

A Claude Code plugin install (~/.claude/plugins/cache/<marketplace>/kicad-skills/<version>) is not a git checkout. There
the lock holds the plugin version from .claude-plugin/plugin.json and "tree", a sha256 of every file under skills/
(caches and .pyc excluded), and `check` compares the tree: the version alone does not prove the files (they change
between releases that keep the number). A git pin records the tree too, so a plugin install with the same files as
the pinned commit passes, and a project pinned from a plugin can be rebuilt from any checkout with identical skills/.

From a project build (e.g. tools/kskills.py, see assets/kskills.py):
  import skills_rev; skills_rev.require(PROJECT_DIR)      # raises SystemExit with the fix when it does not match
To build an old project with its own revision without touching your main checkout:
  git -C <kicad-skills> worktree add ~/git/kicad-skills-<rev> <rev>   and point the project at that folder
"""
import hashlib, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def git(*a, cwd=HERE):
    r = subprocess.run(['git', *a], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.rstrip()     # not strip(): status --porcelain lines start with a space


def tree_hash(root):
    """sha256 of every file under root/skills (relative path and bytes), without caches: __pycache__ and hidden folders
    (.pytest_cache changes on every test run), .pyc and .DS_Store"""
    h = hashlib.sha256()
    base = os.path.join(root, 'skills')
    for d, dirs, files in os.walk(base):
        dirs[:] = sorted(x for x in dirs if x != '__pycache__' and not x.startswith('.'))
        for f in sorted(files):
            if f.endswith('.pyc') or f == '.DS_Store':
                continue
            h.update(os.path.relpath(os.path.join(d, f), base).replace(os.sep, '/').encode() + b'\0')
            h.update(open(os.path.join(d, f), 'rb').read() + b'\0')
    return h.hexdigest()


def plugin(skills_dir=None):
    """(root, plugin.json) of a kicad-skills plugin install holding this scripts directory, or (None, None)"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(skills_dir or HERE))))
    try:
        return root, json.load(open(os.path.join(root, '.claude-plugin', 'plugin.json')))
    except (OSError, ValueError):
        return None, None


def checkout(skills_dir=None):
    """(repo root, rev, dirty files under skills/, remote branches containing rev) of the kicad-skills checkout"""
    d = skills_dir or HERE
    rc, root = git('rev-parse', '--show-toplevel', cwd=d)
    # only a repository whose root holds these skills: a plugin install under a dotfiles repository (~ or ~/.claude
    # tracked in git) is not a kicad-skills checkout, and pinning that repository's commit would prove nothing
    if rc or not os.path.samefile(root, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(d))))):
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
    ks = lock.get('kicad_skills', {})
    want = ks.get('rev', '')
    root, rev, dirty, remote = checkout(skills_dir)
    probs = []
    if not root or not want:
        # a plugin install (no git), or a project pinned from one: the files under skills/ are the proof
        if root:
            here = 'the checkout %s' % root
        else:
            root, meta = plugin(skills_dir)
            if not root:
                return False, '%s is neither a git checkout nor a plugin install of kicad-skills: cannot prove its revision' % (
                    skills_dir or HERE)
            here, rev = 'the kicad-skills plugin %s at %s' % (meta.get('version', '?'), root), 'plugin %s' % meta.get('version', '?')
        if not ks.get('tree'):
            return False, ('%s is not a git checkout, and the project is pinned to commit %s (%s): clone kicad-skills, '
                           '`git checkout %s` and set KICAD_SKILLS to it, or re-pin with this install (skills_rev.py pin) '
                           'after checking the rebuild diff' % (here, want[:12], lp, want[:12]))
        if tree_hash(root) != ks['tree']:
            probs.append('%s has different files under skills/ from the pinned %s (%s): install that version or check out '
                         'the pinned commit and set KICAD_SKILLS, or re-pin after checking the rebuild diff' % (
                             here, 'plugin %s' % ks['plugin_version'] if ks.get('plugin_version') else 'commit %s' % want[:12], lp))
        dirty, remote = [], True              # the tree compares every file, edited or not
    elif rev != want:
        probs.append('this checkout (%s) is at %s, the project is pinned to %s (%s): `git -C %s worktree add <dir> %s` and point the '
                     'project there, or re-pin after checking the rebuild diff' % (root, rev[:12], want[:12], lp, root, want[:12]))
    if dirty:
        probs.append('uncommitted changes under skills/: %s' % ', '.join(dirty[:6]))
    kv, kw = kicad_version(), lock.get('kicad')
    if kw and kv and kv != kw:
        probs.append('KiCad %s here, %s in the lock (canonical file form differs between versions)' % (kv, kw))
    if probs:
        return False, '; '.join(probs)
    return True, 'kicad-skills %s (%s) and KiCad %s as pinned in %s' % (rev if rev.startswith('plugin') else rev[:12],
                                                                         'published' if remote else 'NOT on any remote branch', kv or '?', lp)


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
        if not root and plugin()[0]:
            print('kicad-skills plugin %s at %s (not a git checkout); tree %s; KiCad %s' % (
                plugin()[1].get('version', '?'), plugin()[0], tree_hash(plugin()[0])[:12], kicad_version()))
            return
        print('%s at %s; %s; %s; KiCad %s' % (root, rev, 'clean' if not dirty else 'DIRTY: ' + ', '.join(dirty[:8]),
                                             'on ' + ', '.join(remote[:3]) if remote else 'NOT on any remote branch (unpublished)', kicad_version()))
        return
    proj = sys.argv[2]
    if sys.argv[1] == 'check':
        ok, msg = check_project(proj)
        print(('ok: ' if ok else 'FAIL: ') + msg)
        sys.exit(0 if ok else 1)
    root, rev, dirty, remote = checkout()
    out = os.path.join(proj, 'kicad-skills.lock') if os.path.isdir(proj) else proj
    if not root:
        root, meta = plugin()
        if not root:
            sys.exit('%s is neither a git checkout nor a plugin install of kicad-skills' % HERE)
        json.dump({'kicad_skills': {'plugin_version': meta.get('version'), 'tree': tree_hash(root), 'url': meta.get('repository', '')},
                   'kicad': kicad_version()}, open(out, 'w'), indent=1)
        open(out, 'a').write('\n')
        print('pinned the kicad-skills plugin %s (tree %s) and KiCad %s in %s' % (
            meta.get('version'), tree_hash(root)[:12], kicad_version(), out))
        return
    if dirty:
        sys.exit('refusing to pin: uncommitted changes under skills/ in %s (%s)' % (root, ', '.join(dirty[:6])))
    if not remote and '--allow-unpublished' not in sys.argv:
        sys.exit('refusing to pin %s: it is on no remote branch, so nobody else (and no fresh clone) can build with it. '
                 'Push it first, or pass --allow-unpublished for a local experiment' % rev[:12])
    _, url = git('config', '--get', 'remote.origin.url', cwd=root)
    json.dump({'kicad_skills': {'rev': rev, 'tree': tree_hash(root), 'url': url}, 'kicad': kicad_version()}, open(out, 'w'), indent=1)
    open(out, 'a').write('\n')
    print('pinned kicad-skills %s and KiCad %s in %s' % (rev[:12], kicad_version(), out))


if __name__ == '__main__':
    main()
