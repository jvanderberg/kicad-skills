#!/usr/bin/env python3
"""Register a project library in the project's sym-lib-table / fp-lib-table, or list what a table resolves to.

  libtable.py add PROJECT_DIR sym NICKNAME LIB.kicad_sym [--descr TEXT] [--replace]
  libtable.py add PROJECT_DIR fp  NICKNAME LIB.pretty    [--descr TEXT] [--replace]
  libtable.py remove PROJECT_DIR sym|fp NICKNAME
  libtable.py list PROJECT_DIR [sym|fp] [--global]        # nickname -> resolved path; exit 1 if any is MISSING

PROJECT_DIR is the folder that holds the .kicad_pro (KiCad reads the tables there and nowhere else). add writes the
entry as ${KIPRJMOD}/... (LIB may be absolute or relative to PROJECT_DIR), refuses a library outside the project
(copy it in first), a file that does not exist or is the wrong kind, and a '"' in any field (KiCad 10 cannot read
one); it does nothing if the nickname already names that file, and refuses to re-point a nickname (--replace does,
keeping the row's other settings) or to give one file a second nickname. add and remove refuse while a KiCad editor
holds the project: KiCad reads the project's library tables when it opens the project, so ask the user to close it
and reopen it afterwards. jlcimport-cli registers its own library (import ... --lib-name): do not add that one.
list reads the tables in KiCad's order (the global table first with --global, each Table row followed by the rows of
the table it names; later rows win, disabled rows hide) and marks rows MISSING (the file is not there), UNRESOLVED (a
variable is not set here), disabled, or shadowed by a later row.
Python code uses the same thing directly: kicad_sexpr.LibTable, or symgen.save_library() for redrawn symbols.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import TABLE_FILES, LibTable, global_table, kicad_env  # noqa: E402
from kicad_sexpr.lib_table import TABLE_TYPE  # noqa: E402
import kicad_locks  # noqa: E402


def _editable(prj):
    if not any(f.endswith('.kicad_pro') for f in os.listdir(prj)):
        sys.exit('not changed: %s holds no .kicad_pro, so KiCad would never read a table there' % prj)
    state, _, lines = kicad_locks.status(prj)
    if state in ('OPEN', 'BUSY', 'UNSURE'):
        print('\n'.join(lines))
        sys.exit('not changed: close the project in KiCad first (it reads library tables when the project opens)')


def _list(prj, kinds, with_global):
    env = kicad_env()
    rc = 0
    for kind in kinds:
        tables = ([global_table(kind)] if with_global else []) + [os.path.join(prj, TABLE_FILES[kind])]
        rows = []                                   # (table, row, expanded uri), in KiCad's reading order
        for path in tables:
            if not path or not os.path.exists(path):
                print('%s: (none)' % (path or 'global %s table' % kind))
                continue
            rows.extend(LibTable.load(path, prj).walk(env, prj))   # Table rows followed by what they hold
        last = {r.name: i for i, (_, r, _) in enumerate(rows) if r.type != TABLE_TYPE}
        shown = None
        for i, (path, r, where) in enumerate(rows):
            if path != shown:
                print(path)
                shown = path
            if r.disabled:
                flag = 'disabled'
            elif r.type != TABLE_TYPE and last[r.name] != i:
                flag = 'shadowed by a later row'
            elif '${' in where or '$(' in where:
                flag = 'UNRESOLVED'
            elif not os.path.exists(where):
                flag = 'MISSING'
                rc = 1
            else:
                flag = 'table' if r.type == TABLE_TYPE else ''
            print('  %-24s %s%s' % (r.name, where, '  ' + flag if flag else ''))
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    a_add = sub.add_parser('add')
    a_add.add_argument('project_dir'); a_add.add_argument('kind', choices=['sym', 'fp'])
    a_add.add_argument('nickname'); a_add.add_argument('library')
    a_add.add_argument('--descr'); a_add.add_argument('--replace', action='store_true')
    a_rm = sub.add_parser('remove')
    a_rm.add_argument('project_dir'); a_rm.add_argument('kind', choices=['sym', 'fp']); a_rm.add_argument('nickname')
    a_ls = sub.add_parser('list')
    a_ls.add_argument('project_dir'); a_ls.add_argument('kind', nargs='?', choices=['sym', 'fp'])
    a_ls.add_argument('--global', dest='glob', action='store_true', help='also list the user\'s global table')
    a = ap.parse_args()
    prj = os.path.abspath(a.project_dir)
    if not os.path.isdir(prj):
        sys.exit('%s is not a folder' % prj)
    try:
        if a.cmd == 'list':
            sys.exit(_list(prj, [a.kind] if a.kind else ['sym', 'fp'], a.glob))
        _editable(prj)
        t = LibTable.for_project(prj, a.kind)
        if a.cmd == 'remove':
            if not t.remove(a.nickname):
                sys.exit('not changed: %s is not in %s' % (a.nickname, t.path))
            t.save()
            print('wrote %s: removed %s' % (t.path, a.nickname))
            return
        changed = t.add(a.nickname, a.library, descr=a.descr, replace=a.replace)   # relative = to PROJECT_DIR
    except ValueError as e:
        sys.exit('not changed: %s' % e)
    if changed:
        t.save()
        print('wrote %s: %s -> %s' % (t.path, a.nickname, t.row(a.nickname).uri))
    else:
        print('%s already names %s in %s (unchanged)' % (a.nickname, t.row(a.nickname).uri, t.path))


if __name__ == '__main__':
    main()
