#!/usr/bin/env python3
"""The right python for each script, found one way: KiCad's python for pcbnew, the analysis venv for numpy / scipy /
shapely / matplotlib, and KiCad's python with the venv's packages for a script that needs both.

  interp.py which                          # the interpreters found, their versions, and which modules each has
  interp.py run SCRIPT.py [ARGS ...]       # run an ad hoc script that imports pcbnew AND shapely/numpy
  from interp import need; need('shapely')  # first lines of a script: re-runs it under an interpreter that has them

Which script needs what (the skills' text names the same):
  pcbnew        board_lint.py, boarddump.py                              -> KiCad's python ($KICAD_PYTHON)
  shapely etc.  router.py, planes/emc/power/thermal/region/view/...      -> the analysis venv ($PY)
  neither       everything else                                         -> any python 3
A script started with the wrong interpreter (plain `python3 router.py ...`) re-executes itself with the right one
instead of failing on the import; set KICAD_PYTHON / PY to choose them. Two interpreters are combined only when their
major.minor versions match (compiled packages are tied to one version); otherwise it stops and says how to make a venv
from KiCad's own python (`$KICAD_PYTHON -m venv --system-site-packages DIR`, then install numpy scipy shapely there).
Plain python 3, no dependencies. Identical copies in kicad-pcb-workflow/scripts and kicad-board-review/scripts.
"""
import importlib.util, json, os, subprocess, sys

KICAD_PY = ('/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3',
            'C:/Program Files/KiCad/10.0/bin/python.exe', 'C:/Program Files/KiCad/9.0/bin/python.exe', '/usr/bin/python3')
ANALYSIS = ('numpy', 'scipy', 'shapely', 'matplotlib')


def _venv():
    return os.environ.get('KICAD_SKILLS_VENV') or os.path.expanduser('~/.cache/kicad-skills/venv')


def _probe(py, mods):
    """{'version': 'X.Y', 'site': [...], mod: bool ...} for interpreter py, or None"""
    code = ('import importlib.util, json, site, sys; print(json.dumps(dict(version="{}.{}".format(*sys.version_info[:2]), '
            'site=[p for p in site.getsitepackages() if "site-packages" in p], '
            '**{m: importlib.util.find_spec(m) is not None for m in ' + repr(list(mods)) + '})))')
    try:
        r = subprocess.run([py, '-c', code], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def kicad_python():
    for c in (os.environ.get('KICAD_PYTHON'),) + KICAD_PY:
        if c and os.path.exists(c):
            p = _probe(c, ['pcbnew'])
            if p and p['pcbnew']:
                return c
    return None


def analysis_python():
    for c in (os.environ.get('PY'), os.path.join(_venv(), 'bin', 'python'), os.path.join(_venv(), 'Scripts', 'python.exe')):
        if c and os.path.exists(c):
            return c
    return None


def _has(mods):
    return [m for m in mods if importlib.util.find_spec(m) is None]


def combined_env(kpy, apy):
    """environment that gives KiCad's python the analysis venv's packages, or (None, reason)"""
    pk, pa = _probe(kpy, []), _probe(apy, [])
    if not pk or not pa:
        return None, 'could not run %s' % (apy if pk else kpy)
    if pk['version'] != pa['version']:
        return None, ('KiCad\'s python is %s and the analysis venv\'s is %s: their compiled packages cannot be mixed. Make a venv '
                      'from KiCad\'s python: "%s" -m venv --system-site-packages DIR && DIR/bin/pip install numpy scipy shapely '
                      'matplotlib, then PY=DIR/bin/python' % (pk['version'], pa['version'], kpy))
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([p for p in [env.get('PYTHONPATH')] if p] + pa['site'])
    return env, ''


def need(*mods):
    """make sure this process can import mods; otherwise re-run the calling script under an interpreter that can"""
    missing = _has(mods)
    if not missing:
        return
    script = os.path.abspath(sys.argv[0])
    if os.environ.get('KSKILLS_REEXEC'):
        sys.exit('%s needs %s, which %s (python %d.%d) cannot import even after re-running under the interpreter '
                 'interp.py chose: set KICAD_PYTHON / PY (interp.py which)' % (
                     os.path.basename(script), ', '.join(missing), sys.executable, *sys.version_info[:2]))
    want_k = 'pcbnew' in missing or 'pcbnew' in mods
    want_a = any(m != 'pcbnew' for m in mods)
    kpy, apy = (kicad_python() if want_k else None), (analysis_python() if want_a else None)
    env = dict(os.environ, KSKILLS_REEXEC='1')
    if want_k and want_a:
        if not (kpy and apy):
            sys.exit('%s needs pcbnew and %s: %s' % (os.path.basename(script), ', '.join(m for m in mods if m != 'pcbnew'),
                                                     'no KiCad python found (set KICAD_PYTHON)' if not kpy else
                                                     'no analysis venv found (kicad_env.sh creates it; or set PY)'))
        e2, why = combined_env(kpy, apy)
        if e2 is None:
            sys.exit('%s: %s' % (os.path.basename(script), why))
        env.update(e2); env['KSKILLS_REEXEC'] = '1'
        target = kpy
    else:
        target = kpy if want_k else apy
        if not target:
            sys.exit('%s needs %s: %s' % (os.path.basename(script), ', '.join(missing),
                                          'no KiCad python with pcbnew found (set KICAD_PYTHON)' if want_k else
                                          'no analysis venv found (source kicad_env.sh once to create it, or set PY)'))
    sys.stderr.write('(%s: re-running under %s for %s)\n' % (os.path.basename(script), target, ', '.join(missing)))
    sys.stderr.flush()
    os.execve(target, [target, script] + sys.argv[1:], env)


def main():
    a = sys.argv[1:]
    if a[:1] == ['which']:
        k, p = kicad_python(), analysis_python()
        for name, py, mods in (('KiCad python (pcbnew)', k, ['pcbnew']), ('analysis venv', p, list(ANALYSIS))):
            info = _probe(py, mods) if py else None
            print('%-22s %s%s' % (name + ':', py or 'NOT FOUND', '  (python %s; %s)' % (
                info['version'], ', '.join('%s %s' % (m, 'yes' if info[m] else 'NO') for m in mods)) if info else ''))
        if k and p:
            env, why = combined_env(k, p)
            print('%-22s %s' % ('both in one process:', 'yes (interp.py run SCRIPT)' if env else 'no: ' + why))
        return
    if len(a) >= 2 and a[0] == 'run':
        k, p = kicad_python(), analysis_python()
        if not (k and p):
            sys.exit('interp.py run needs KiCad\'s python and the analysis venv: %s' % ('set KICAD_PYTHON' if not k else 'set PY'))
        env, why = combined_env(k, p)
        if env is None:
            sys.exit('interp.py run: ' + why)
        env['KSKILLS_REEXEC'] = '1'
        os.execve(k, [k] + a[1:], env)
    sys.exit(__doc__.split('\n\n')[0] + '\nusage: interp.py which | run SCRIPT.py [ARGS]')


if __name__ == '__main__':
    main()
