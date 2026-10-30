"""Library tables (fp-lib-table, sym-lib-table): add or update a library entry without formatting text.

  from kicad_sexpr import add_library
  add_library('hardware/fp-lib-table', 'proj', '${KIPRJMOD}/proj.pretty')      # creates the table if there is none
  add_library('hardware/sym-lib-table', 'proj', '${KIPRJMOD}/proj.kicad_sym')

The table kind (fp_lib_table / sym_lib_table) comes from the file name. An entry with the same name is updated in
place, other entries and their order are kept, and the file is only written when something changed, so re-running a
generator leaves a table KiCad saved byte-identical.
"""
from __future__ import annotations

import os
from typing import List

from .sexp import Node, load, save

__all__ = ['add_library', 'library_names']

TABLE_VERSION = 7          # KiCad 9 / 10 write (version 7)


def _kind(path: str) -> str:
    name = os.path.basename(path)
    if name not in ('fp-lib-table', 'sym-lib-table'):
        raise ValueError('%s: a library table is named fp-lib-table or sym-lib-table' % path)
    return name.replace('-', '_')


def library_names(path: str) -> List[str]:
    """Nicknames in a library table, in file order ([] when there is no table)."""
    if not os.path.exists(path):
        return []
    return [str(lib.get('name')) for lib in load(path).nodes('lib')]


def add_library(path: str, name: str, uri: str, type_: str = 'KiCad', options: str = '', descr: str = '') -> bool:
    """Add library ``name`` at ``uri`` to the table at ``path`` (created if missing), or update the entry of that name.
    Returns True when the file was written."""
    kind = _kind(path)
    table = load(path) if os.path.exists(path) else Node(kind, Node('version', TABLE_VERSION))
    if table.head != kind:
        raise ValueError('%s holds (%s ...), not (%s ...)' % (path, table.head, kind))
    want = dict(name=name, type=type_, uri=uri, options=options, descr=descr)
    entry = next((lib for lib in table.nodes('lib') if str(lib.get('name')) == name), None)
    if entry is None:
        table.append(Node('lib', *(Node(k, v) for k, v in want.items())))
    elif all(str(entry.get(k, '')) == v for k, v in want.items()):
        return False
    else:
        for k, v in want.items():
            entry.set(k, v)
    save(table, path)
    return True
