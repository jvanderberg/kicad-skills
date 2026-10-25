#!/usr/bin/env python3
"""Is KiCad holding a project open, or is a lock file only left over? And: remove the locks a script caused.

  kicad_locks.py status PROJECT_DIR [--clean]     # exit 0 safe to edit, 1 open / busy, 2 cannot tell
  kicad_locks.py run DIR -- kicad-cli ARGS ...    # run a command, then remove the lock files it left in DIR

A lock file (~NAME.kicad_pro.lck, ~NAME.kicad_pcb.lck, ...) is not evidence that KiCad is open: kicad-cli (render, DRC,
export) can leave one behind, and a crashed editor leaves one too. The lock holds only a user and host name. What
shows an open project is a running KiCad editor (kicad, pcbnew, eeschema - not kicad-cli) that holds the folder: its
working directory or an open file or directory handle in it (KiCad watches the project folder). status says which:
  OPEN   an editor (pid N) holds files in the folder: ask the user to save and close it          exit 1
  BUSY   a kicad-cli process is working on files in the folder: wait for it                       exit 1
  STALE  lock files, no KiCad process holds the folder: safe to edit; --clean deletes them       exit 0
  UNSURE lock files and an editor is running whose open files cannot be read (no lsof, no process list, another user):
         ask the user whether this project is open                                             exit 2
  CLOSED nothing                                                                                exit 0
Never tell the user "you have KiCad open" from a lock file alone.

Library (scripts that call kicad-cli on a user's files):
  from kicad_locks import cli_run, cleanup_locks
  cli_run([kicad_cli, 'pcb', 'render', ..., board], board)       # subprocess.run + removes locks it created
  with cleanup_locks(sheet_dir): ...                              # any block that runs kicad-cli
Only lock files that did not exist before the block are removed, and only while no editor holds the folder (an
editor opened meanwhile owns its lock). Shell scripts do the same with  trap '... run/clean ...' EXIT  (check.sh).
Plain python 3, no dependencies; lsof (macOS, Linux) or /proc (Linux) for the process check.
Identical copies in kicad-pcb-workflow/scripts, kicad-board-review/scripts and pcb-part-selection/scripts (each skill
folder is self-contained).
"""
import contextlib, glob, os, re, shutil, subprocess, sys

LOCK_GLOBS = ('~*.lck', '*.lck', '.~lock*')
EDITOR_RX = re.compile(r'(KiCad\.app/Contents/MacOS/(kicad|pcbnew|eeschema)$)|((^|/)(kicad|pcbnew|eeschema)(\.exe)?$)')
CLI_RX = re.compile(r'(^|/)kicad-cli(\.exe)?$')


def locks(d):
    d = os.path.abspath(d)
    out = set()
    for g in LOCK_GLOBS:
        out.update(glob.glob(os.path.join(d, g)))
    return sorted(out)


def _procs():
    """[(pid, executable path)] of KiCad editors and kicad-cli processes, or None when processes cannot be listed"""
    try:
        r = subprocess.run(['ps', '-axo', 'pid=,comm='], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = []
    for line in r.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            out.append((int(parts[0]), parts[1].strip()))
    return [(p, c) for p, c in out if EDITOR_RX.search(c) or CLI_RX.search(c)]


def _held_paths(pid):
    """paths a process holds (cwd and open files/directories), or None if they cannot be read"""
    if os.path.isdir('/proc/%d' % pid):
        try:
            paths = [os.readlink('/proc/%d/cwd' % pid)]
            fd = '/proc/%d/fd' % pid
            for f in os.listdir(fd):
                try:
                    paths.append(os.readlink(os.path.join(fd, f)))
                except OSError:
                    pass
            return paths
        except OSError:
            return None
    if not shutil.which('lsof'):
        return None
    try:
        r = subprocess.run(['lsof', '-a', '-p', str(pid), '-Fn'], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode not in (0, 1):
        return None
    return [line[1:] for line in r.stdout.splitlines() if line.startswith('n')]


def _inside(path, d):
    return path == d or path.startswith(d + os.sep)


def holders(d):
    """(editors holding d, cli processes holding d, editors whose files could not be read): lists of (pid, command)"""
    d = os.path.realpath(d)
    ed, cli, unknown = [], [], []
    procs = _procs()
    if procs is None:
        return ed, cli, [(0, 'process list unavailable')]
    for pid, cmd in procs:
        if pid == os.getpid():
            continue
        paths = _held_paths(pid)
        if paths is None:
            if EDITOR_RX.search(cmd):
                unknown.append((pid, cmd))
            continue
        if any(_inside(os.path.realpath(p) if os.path.exists(p) else p, d) for p in paths):
            (cli if CLI_RX.search(cmd) else ed).append((pid, cmd))
    return ed, cli, unknown


def status(d):
    """(state, exit code, message lines)"""
    lk = locks(d)
    ed, cli, unknown = holders(d)
    if ed:
        return 'OPEN', 1, ['OPEN: KiCad %s holds files in %s - ask the user to save and close it, then re-read the files' % (
            ', '.join('pid %d (%s)' % e for e in ed), d)] + ['  lock: ' + x for x in lk]
    if cli:
        return 'BUSY', 1, ['BUSY: kicad-cli %s is working on files in %s - wait for it to finish' % (
            ', '.join('pid %d' % p for p, _ in cli), d)]
    if lk and unknown:
        return 'UNSURE', 2, ['UNSURE: lock files in %s and KiCad processes that cannot be inspected (%s): ask the user '
                             'whether this project is open; do not assume it is' % (
                                 d, ', '.join('pid %d %s' % u for u in unknown))] + ['  lock: ' + x for x in lk]
    if lk:
        return 'STALE', 0, ['STALE: no KiCad process holds %s; these lock files were left by kicad-cli or a crashed session '
                            '(safe to delete; --clean does): %s' % (d, ' '.join(os.path.basename(x) for x in lk))]
    return 'CLOSED', 0, ['not open: safe to edit (no KiCad process holds %s, no lock files)' % d]


@contextlib.contextmanager
def cleanup_locks(*paths):
    """remove lock files that appear in the folders of `paths` while the block runs (not ones that were there)"""
    dirs = sorted({os.path.abspath(p if os.path.isdir(p) else os.path.dirname(os.path.abspath(p))) for p in paths})
    before = {d: set(locks(d)) for d in dirs}
    try:
        yield
    finally:
        for d in dirs:
            new = [x for x in locks(d) if x not in before[d]]
            if new and not holders(d)[0]:
                for x in new:
                    try:
                        os.remove(x)
                    except OSError:
                        pass


def cli_run(cmd, *paths, **kw):
    """subprocess.run(cmd, **kw), removing the lock files it left next to `paths` (default: the last argument)"""
    with cleanup_locks(*(paths or (cmd[-1],))):
        return subprocess.run(cmd, **kw)


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == 'status':
        state, rc, lines = status(a[1])
        for line in lines:
            print(line)
        if state == 'STALE' and '--clean' in a:
            lk = locks(a[1])
            for x in lk:
                os.remove(x)
            print('removed %d stale lock file(s)' % len(lk))
        sys.exit(rc)
    if len(a) >= 3 and a[0] == 'run' and '--' in a:
        d, cmd = a[1], a[a.index('--') + 1:]
        sys.exit(cli_run(cmd, d).returncode)
    sys.exit(__doc__.split('\n\n')[0] + '\nusage: kicad_locks.py status DIR [--clean] | run DIR -- CMD ...')


if __name__ == '__main__':
    main()
