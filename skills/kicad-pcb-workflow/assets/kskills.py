"""Template for a project's tools/kskills.py: put kicad-skills' scripts on sys.path and refuse to build with any
revision other than the one in the project's kicad-skills.lock (skills_rev.py). Copy it into the project's tools/,
import it before any kicad-skills module, and commit kicad-skills.lock next to it (or in docs/).

  KICAD_SKILLS=<checkout or worktree of kicad-skills>   (default ~/git/kicad-skills, else the newest Claude Code
                                                        plugin install, ~/.claude/plugins/cache/*/kicad-skills/<version>)
  KICAD_SKILLS_UNPINNED=1                               skip the check for one experimental run (it says so)
A plugin install is not a git checkout: skills_rev.py pins it by plugin version and a hash of its files instead.
"""
import glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))           # the project's repository root


def _default():
    git = os.path.expanduser('~/git/kicad-skills')
    if os.path.isdir(git):
        return git
    found = glob.glob(os.path.expanduser('~/.claude/plugins/cache/*/kicad-skills/*/skills'))
    key = lambda p: [int(n) for n in re.findall(r'\d+', os.path.basename(os.path.dirname(p)))]
    return os.path.dirname(max(found, key=key)) if found else git


SKILLS = os.environ.get('KICAD_SKILLS') or _default()
SCRIPTS = os.path.join(SKILLS, 'skills', 'kicad-pcb-workflow', 'scripts')
if not os.path.isdir(SCRIPTS):
    raise SystemExit('kicad-skills not found at %s: set KICAD_SKILLS' % SKILLS)
# appended, not prepended: the project's own tools/ (sys.path[0]) must win over generic module names in scripts/
if SCRIPTS not in sys.path:
    sys.path.append(SCRIPTS)
import skills_rev  # noqa: E402

if os.environ.get('KICAD_SKILLS_UNPINNED'):
    print('kskills: KICAD_SKILLS_UNPINNED set - building with %s UNCHECKED' % SKILLS, file=sys.stderr)
else:
    print('kskills: ' + skills_rev.require(ROOT, SCRIPTS), file=sys.stderr)
