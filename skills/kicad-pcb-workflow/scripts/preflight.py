#!/usr/bin/env python3
"""Check every tool the skills' scripts need, before a session depends on them.

  preflight.py [--for workflow,review,parts,power | all] [--project DIR]

Prints one row per dependency: found / version / what needs it / how to install, and exits 1 when anything a chosen
skill requires is missing or too old. With --project it also checks the project's pinned kicad-skills revision
(kicad-skills.lock, see skills_rev.py) and its sourcing context (sourcing.json: assembler and LCSC region; required
for the parts skill, since stock differs by region and jlcimport-cli's own default region is whatever its KiCad
plugin last used). A script that fails halfway because a tool was never installed wastes the run
and can leave half-written outputs; one that silently skips a step reports a pass it did not earn.
Identical copies in kicad-pcb-workflow/scripts and kicad-board-review/scripts (with skills_rev.py); keep them in sync.
"""
import argparse, glob, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def first(cands):
    for c in cands:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None


def kicad_cli():
    return first([os.environ.get('KICAD_CLI'), '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli', shutil.which('kicad-cli'),
                  'C:/Program Files/KiCad/10.0/bin/kicad-cli.exe', 'C:/Program Files/KiCad/9.0/bin/kicad-cli.exe'])


def kicad_python():
    for c in [os.environ.get('KICAD_PYTHON'),
              '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3',
              'C:/Program Files/KiCad/10.0/bin/python.exe', 'C:/Program Files/KiCad/9.0/bin/python.exe', '/usr/bin/python3']:
        if c and os.path.exists(c) and run([c, '-c', 'import pcbnew'])[0] == 0:
            return c
    return None


def checks():
    """(name, needed by, required-for set, function returning (ok, detail), install hint)"""
    out = []
    v = sys.version_info
    out.append(('python3 >= 3.9', {'workflow', 'review', 'parts', 'power'}, lambda: (v >= (3, 9), '%d.%d.%d' % v[:3]), 'python.org / your package manager'))

    def cli():
        c = kicad_cli()
        if not c:
            return False, 'not found (set KICAD_CLI)'
        rc, t = run([c, 'version'])
        m = re.search(r'(\d+)\.(\d+)', t)
        ok = bool(m) and int(m.group(1)) >= 9
        return ok, '%s at %s%s' % (t.splitlines()[0] if t else '?', c, '' if not m or int(m.group(1)) >= 10 else
                                    ' (KiCad 9: generated files will not match KiCad 10 canonical form)')
    out.append(('kicad-cli (KiCad 9/10)', {'workflow', 'review', 'parts'}, cli, 'kicad.org/download; or set KICAD_CLI'))

    def kpy():
        c = kicad_python()
        if not c:
            return False, 'no python with pcbnew (set KICAD_PYTHON)'
        rc, t = run([c, '-c', 'import pcbnew; print(pcbnew.Version())'])
        return rc == 0, '%s (pcbnew %s)' % (c, t.splitlines()[-1] if t else '?')
    out.append(("KiCad's python with pcbnew", {'review', 'workflow'}, kpy, 'comes with KiCad; set KICAD_PYTHON'))

    def venv():
        py = os.environ.get('PY') or os.path.join(os.environ.get('KICAD_SKILLS_VENV', os.path.expanduser('~/.cache/kicad-skills/venv')), 'bin', 'python')
        if not os.path.exists(py):
            return False, '%s missing (kicad_env.sh creates it on first use)' % py
        rc, t = run([py, '-c', 'import numpy, scipy, matplotlib, shapely; print(shapely.__version__)'])
        ok = rc == 0 and int(t.split('.')[0]) >= 2
        return ok, '%s, shapely %s' % (py, t if rc == 0 else 'MISSING: ' + t.splitlines()[-1][:80])
    out.append(('analysis venv (numpy scipy shapely>=2 matplotlib)', {'review'}, venv,
                'source kicad-board-review/scripts/kicad_env.sh (creates ~/.cache/kicad-skills/venv)'))

    for tool, need, hint in (('rsvg-convert', {'workflow'}, 'brew install librsvg / apt install librsvg2-bin (render.py)'),
                             ('pdftotext', {'parts', 'power'}, 'brew install poppler / apt install poppler-utils (datasheet.py)'),
                             ('pdftoppm', {'parts', 'power'}, 'poppler (datasheet.py page)'),
                             ('pdfinfo', {'parts', 'power'}, 'poppler'),
                             ('git', {'workflow', 'review'}, 'git-scm.com (board_diff.py, skills_rev.py)'),
                             ('rsync', {'workflow', 'review'}, 'check.sh / make_pack.sh copy the project with it')):
        out.append((tool, need, (lambda t=tool: (bool(shutil.which(t)), shutil.which(t) or 'not on PATH')), hint))

    def jlc():
        c = os.environ.get('JLCIMPORT_CLI') or shutil.which('jlcimport-cli') or first(glob.glob(os.path.expanduser('~/.local/bin/jlcimport-cli')))
        if not c:
            return False, 'not on PATH'
        rc, t = run([c, 'search', '--help'])
        rv, vt = run([c, '--version'])
        return '--region' in t, '%s %s%s' % (c, vt.splitlines()[0] if rv == 0 and vt else '', '' if '--region' in t else ' (no search --region: needs v1.6.0+)')
    out.append(('jlcimport-cli >= 1.6.0', {'parts'}, jlc, 'pipx install git+https://github.com/jvanderberg/kicad_jlcimport'))

    def jlc_production():
        c = os.environ.get('JLCIMPORT_CLI') or shutil.which('jlcimport-cli') or first(glob.glob(os.path.expanduser('~/.local/bin/jlcimport-cli')))
        if not c:
            return False, 'no jlcimport-cli'
        rc, t = run([c, 'production', '--help'])
        if rc != 0 or '--check-only' not in t:
            return False, '%s has no production command (v1.6.7 and older)' % c
        # main builds between the production command (PR #121) and v1.7.0 report 1.6.7 and put one LCSC part on several
        # BOM lines when Values differ (JLC then fits none of them); v1.7.0 puts each part on one line (PR #126)
        try:
            with open(c, 'rb') as f:
                first = f.readline().decode('utf-8', 'replace')
        except OSError:
            first = ''
        rv, vt = run(first[2:].split() + ['-c', "from importlib.metadata import version; print(version('kicad-jlcimport'))"]) \
            if first.startswith('#!') and 'python' in first else (1, '')
        m = re.search(r'(\d+)\.(\d+)\.(\d+)', vt) if rv == 0 else None
        if m and tuple(int(x) for x in m.groups()) < (1, 7, 0):
            return False, '%s %s: a build of main from before v1.7.0 (its order BOM splits one part over lines by Value)' % (c, m.group(0))
        return True, '%s %s' % (c, m.group(0) if m else '(version unknown)')
    # optional (needed by nothing): the order files and placement check, JLCImport v1.7.0 or later
    out.append(('jlcimport-cli production (order files)', set(), jlc_production,
                'pipx install --force git+https://github.com/jvanderberg/kicad_jlcimport (v1.7.0 or later)'))
    return out


def jlcimport_default_region():
    """the region jlcimport-cli's search uses when --region is missing: its config file (written by the KiCad plugin's
    region menu), else global"""
    base = {'darwin': '~/Library/Preferences/kicad', 'win32': os.path.join(os.environ.get('APPDATA', ''), 'kicad')}.get(sys.platform, '~/.config/kicad')
    p = os.path.join(os.path.expanduser(base), 'jlcimport.json')
    try:
        import json
        return json.load(open(p)).get('region', 'global'), p
    except (OSError, ValueError):
        return 'global', None


def sourcing_check(project):
    """(ok, message): the project's sourcing.json names assembler and region; jlcimport's own default noted"""
    import json
    sys.path.insert(0, HERE)
    import projfiles
    p, msg = projfiles.describe(project, 'sourcing.json')
    dflt, cfgp = jlcimport_default_region()
    tail = "; jlcimport-cli's default region is %s (%s): the skills' scripts always pass --region, never run its search by hand without it" % (
        dflt, cfgp or 'built in')
    if not p:
        return False, msg + ' - create it: pcb-part-selection/scripts/sourcing.py init <project> --assembler JLCPCB --region global' + tail
    try:
        d = json.load(open(p))
    except (OSError, ValueError) as e:
        return False, '%s unreadable: %s' % (p, e)
    if not d.get('assembler') or d.get('region') not in ('global', 'cn'):
        return False, '%s must name "assembler" and "region" (global | cn)' % p
    return True, '%s: %s, region %s%s' % (p, d['assembler'], d['region'], tail if dflt != d['region'] else '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--for', dest='skills', default='all'); ap.add_argument('--project')
    a = ap.parse_args()
    want = {'workflow', 'review', 'parts', 'power'} if a.skills == 'all' else set(a.skills.split(','))
    bad = 0
    print('%-50s %-8s %s' % ('dependency', 'status', 'detail'))
    for name, need, fn, hint in checks():
        ok, detail = fn()
        req = bool(need & want)
        st = 'ok' if ok else ('MISSING' if req else 'optional')
        bad += (not ok) and req
        print('%-50s %-8s %s%s' % (name, st, detail, '' if ok else '\n%50s          install: %s (needed by: %s)' % ('', hint, ', '.join(sorted(need)) or 'nothing required')))
    if a.project:
        sys.path.insert(0, HERE)
        try:
            import skills_rev
            ok, msg = skills_rev.check_project(a.project)
        except ImportError:
            ok, msg = False, 'skills_rev.py is not next to this script: cannot check the pinned revision'
        print('%-50s %-8s %s' % ('kicad-skills revision (kicad-skills.lock)', 'ok' if ok else 'MISMATCH', msg))
        bad += not ok
        ok, msg = sourcing_check(a.project)
        req = 'parts' in want
        print('%-50s %-8s %s' % ('sourcing context (sourcing.json)', 'ok' if ok else ('MISSING' if req else 'optional'), msg))
        bad += (not ok) and req
    print('\n%s' % ('all required tools present' if not bad else '%d required item(s) missing or wrong: fix them before running the skills\' scripts' % bad))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
