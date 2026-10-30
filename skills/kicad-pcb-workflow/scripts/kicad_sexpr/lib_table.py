"""Library tables (sym-lib-table, fp-lib-table, design-block-lib-table): which file each library nickname names.

A project table registers project libraries as ``${KIPRJMOD}/...`` so the project opens on any machine. ``add()``
turns a path inside the project into that form, refuses a path outside it (copy the library into the project instead),
does nothing when the same nickname already names the same file (re-running a generator changes nothing), and refuses
to re-point a nickname or to give one file a second nickname. Paths are compared after expansion and normalisation,
so ``/abs/proj/X.pretty``, ``$(KIPRJMOD)/X.pretty/`` and ``${KIPRJMOD}/X.pretty`` are one file. ``save()`` writes
KiCad 10's own layout (one row per line, via ``dumps``), so a table KiCad saved comes back byte-identical.

KiCad 10's table parser reads a quoted string up to the next ``"`` and takes everything in it literally (no escapes).
A ``"`` in any field therefore ends the string early and KiCad drops the whole table, and a ``\`` or control
character cannot round-trip (the writer escapes it, KiCad reads the escape as written). ``add()`` refuses them in
every field (backslashes in a uri become ``/``, as KiCad writes them), and ``save()`` refuses a table read from a file
that holds a backslash, since its strings would not come back as KiCad read them.

Resolution follows KiCad's LIBRARY_MANAGER: rows are read in order (global table, then the project's), a later row for
a nickname replaces an earlier one, a disabled row still replaces it (the library is then unavailable), and a
``Table`` row is expanded in place unless it is disabled.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterator, List, Mapping, NamedTuple, Optional, Set, Tuple

from .sexp import Node, SexpError, load, save

__all__ = ['LibRow', 'LibTable', 'LIB_TABLE_VERSION', 'TABLE_FILES', 'expand_uri', 'find_project_dir', 'global_table',
           'kicad_env', 'resolve_libraries']

LIB_TABLE_VERSION = 7                   # what KiCad 10.0 writes (LIBRARY_TABLE::Format)
TABLE_HEADS = {'sym': 'sym_lib_table', 'fp': 'fp_lib_table', 'design_block': 'design_block_lib_table'}
TABLE_FILES = {'sym': 'sym-lib-table', 'fp': 'fp-lib-table', 'design_block': 'design-block-lib-table'}
TABLE_TYPE = 'Table'                    # KiCad 10: a row whose uri is another library table
LIB_SUFFIX = {'sym': '.kicad_sym', 'fp': '.pretty', 'design_block': '.kicad_blocks'}   # for type "KiCad" rows
_VAR = re.compile(r'\$\{(\w+)\}|\$\((\w+)\)')
# KiCad's install folders: every machine with KiCad has them (KICADn_3RD_PARTY is per machine: not portable)
_STOCK_VAR = re.compile(r'KICAD\d+_(SYMBOL_DIR|FOOTPRINT_DIR|3DMODEL_DIR|TEMPLATE_DIR)$')


class LibRow(NamedTuple):
    name: str
    type: str
    uri: str
    options: str = ''
    descr: str = ''
    disabled: bool = False
    hidden: bool = False


def _row(n: Node) -> LibRow:
    return LibRow(str(n.get('name', '')), str(n.get('type', '')), str(n.get('uri', '')), str(n.get('options', '')),
                  str(n.get('descr', '')), n.find('disabled') is not None, n.find('hidden') is not None)


def _slash(p: str) -> str:
    return p.replace('\\', '/')


def kicad_env(env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """The variables KiCad expands in tables: the user's path variables (kicad_common.json), KiCad's install folders
    (KICAD10_SYMBOL_DIR, ..._FOOTPRINT_DIR, ..._3DMODEL_DIR and the 9 names), then ``env`` (default: the process
    environment), which wins."""
    v: Dict[str, str] = {}
    home = os.path.expanduser('~')
    for base in (os.path.join(home, 'Library', 'Preferences', 'kicad'), os.path.join(home, '.config', 'kicad'),
                 os.path.join(os.environ.get('APPDATA', ''), 'kicad')):
        c = os.path.join(base, '10.0', 'kicad_common.json')
        if os.path.isfile(c):
            try:
                with open(c, encoding='utf-8') as f:
                    v.update((json.load(f).get('environment') or {}).get('vars') or {})
            except ValueError:
                pass
    for share in ('/Applications/KiCad/KiCad.app/Contents/SharedSupport', '/usr/share/kicad', '/usr/local/share/kicad',
                  'C:/Program Files/KiCad/10.0/share/kicad'):
        if os.path.isdir(os.path.join(share, 'symbols')):
            for var, sub in (('SYMBOL_DIR', 'symbols'), ('FOOTPRINT_DIR', 'footprints'), ('3DMODEL_DIR', '3dmodels'),
                             ('TEMPLATE_DIR', 'template')):
                for ver in ('10', '9'):
                    v.setdefault('KICAD%s_%s' % (ver, var), os.path.join(share, sub))
            break
    v.update(os.environ if env is None else env)
    return v


def expand_uri(uri: str, project_dir: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> str:
    """``${VAR}`` and ``$(VAR)`` expanded from ``env`` (default: ``kicad_env()``), ``KIPRJMOD`` = ``project_dir``.
    An unknown variable is left as written."""
    vals = dict(kicad_env() if env is None else env)
    if project_dir is not None:
        vals['KIPRJMOD'] = _slash(os.path.abspath(project_dir))
    return _VAR.sub(lambda m: vals.get(m.group(1) or m.group(2), m.group(0)), uri)


def _canon(path: str) -> str:
    """One spelling per file: normalised, symlinks resolved, forward slashes, no trailing slash. A path that still
    holds a variable is only normalised."""
    p = os.path.normpath(_slash(path))
    return _slash(p if _VAR.search(p) else os.path.realpath(p)).rstrip('/') or '/'


def global_table(kind: str) -> Optional[str]:
    """The user's global table of ``kind`` ('sym', 'fp', 'design_block'): KiCad 10's, else 9's; None if neither."""
    home = os.path.expanduser('~')
    bases = [os.path.join(home, 'Library', 'Preferences', 'kicad'), os.path.join(home, '.config', 'kicad'),
             os.path.join(os.environ.get('APPDATA', ''), 'kicad')]
    for ver in ('10.0', '9.0'):
        for b in bases:
            p = os.path.join(b, ver, TABLE_FILES[kind])
            if os.path.isfile(p):
                return p
    return None


def find_project_dir(path: str) -> Optional[str]:
    """The nearest folder at or above ``path`` (a file or folder) that holds a .kicad_pro, else None."""
    d = os.path.abspath(path)
    if not os.path.isdir(d):
        d = os.path.dirname(d)
    while True:
        try:
            if any(f.endswith('.kicad_pro') for f in os.listdir(d)):
                return d
        except OSError:
            pass
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def _check_field(what: str, value: str) -> None:
    bad = [c for c in value if c in '"\\' or ord(c) < 0x20]
    if bad:
        raise ValueError('%s %r contains %r: KiCad 10 reads table strings literally up to the next \'"\' (a \'"\' '
                         'makes it drop the whole table; a backslash or control character does not come back as '
                         'written)' % (what, value, bad[0]))


class LibTable:
    """One library table file. With ``project_dir`` set (``for_project``, or ``load`` of a table that sits next to a
    .kicad_pro) ``add()`` enforces project-relative uris."""

    def __init__(self, tree: Node, path: Optional[str] = None, project_dir: Optional[str] = None) -> None:
        kinds = {h: k for k, h in TABLE_HEADS.items()}
        if tree.head not in kinds:
            raise ValueError('not a library table: %s' % tree.head)
        self.tree = tree
        self.kind = kinds[tree.head]
        self.path = path
        self.project_dir = os.path.abspath(project_dir) if project_dir else None
        self.has_backslash = False      # set by load(): the file's strings are not safe to rewrite

    @classmethod
    def load(cls, path: str, project_dir: Optional[str] = None) -> 'LibTable':
        """A table file. ``project_dir`` defaults to the table's folder when that folder holds a .kicad_pro (a
        project table); a file of 0 or 1 bytes is an empty table, as in KiCad."""
        folder = os.path.dirname(os.path.abspath(path))
        if project_dir is None and any(f.endswith('.kicad_pro') for f in os.listdir(folder)):
            project_dir = folder
        if os.path.getsize(path) <= 1:
            kind = {f: k for k, f in TABLE_FILES.items()}.get(os.path.basename(path))
            if kind is None:
                raise ValueError('%s is empty and its name does not say which kind of table it is' % path)
            return cls.new(kind, path, project_dir)
        try:
            t = cls(load(path), path, project_dir)
        except SexpError as e:
            raise ValueError('%s: %s' % (path, e))
        with open(path, encoding='utf-8') as f:
            t.has_backslash = '\\' in f.read()
        return t

    @classmethod
    def new(cls, kind: str, path: Optional[str] = None, project_dir: Optional[str] = None) -> 'LibTable':
        if kind not in TABLE_HEADS:
            raise ValueError('kind must be one of %s' % ', '.join(TABLE_HEADS))
        return cls(Node(TABLE_HEADS[kind], Node('version', LIB_TABLE_VERSION)), path, project_dir)

    @classmethod
    def for_project(cls, project_dir: str, kind: str) -> 'LibTable':
        """The project's table of ``kind`` (``PROJECT_DIR/sym-lib-table`` ...): loaded if it exists, else empty."""
        p = os.path.join(project_dir, TABLE_FILES[kind])
        t = cls.load(p, project_dir) if os.path.exists(p) else cls.new(kind, p, project_dir)
        if t.kind != kind:
            raise ValueError('%s holds a %s table, not a %s one' % (p, t.tree.head, TABLE_HEADS[kind]))
        return t

    # ------------------------------------------------------------------ reading
    def rows(self) -> List[LibRow]:
        return [_row(n) for n in self.tree.nodes('lib')]

    def row(self, name: str) -> Optional[LibRow]:
        """The row KiCad uses for ``name`` (the last one, if the table lists it twice)."""
        found = [r for r in self.rows() if r.name == name]
        return found[-1] if found else None

    def names(self) -> List[str]:
        return list(dict.fromkeys(r.name for r in self.rows()))

    def _prj(self) -> Optional[str]:
        return self.project_dir or (os.path.dirname(os.path.abspath(self.path)) if self.path else None)

    def walk(self, env: Optional[Mapping[str, str]] = None, project_dir: Optional[str] = None,
             _seen: Optional[Set[str]] = None) -> Iterator[Tuple[str, LibRow, str]]:
        """(table path, row, expanded uri) for every row in KiCad's reading order: a ``Table`` row is followed by
        the rows of the table it names (unless it is disabled or already read). KIPRJMOD = ``project_dir``, else
        the table's project folder."""
        prj = project_dir or self._prj()
        vals = kicad_env(env)
        seen = _seen if _seen is not None else set()
        here = os.path.abspath(self.path) if self.path else ''
        if here:
            seen.add(here)
        for r in self.rows():
            uri = expand_uri(r.uri, prj, vals)
            yield here, r, uri
            if r.type == TABLE_TYPE and not r.disabled:
                sub = os.path.abspath(uri)
                if sub not in seen and os.path.isfile(sub):
                    yield from LibTable.load(sub, prj).walk(vals, prj, seen)

    def resolve(self, env: Optional[Mapping[str, str]] = None,
                project_dir: Optional[str] = None) -> Dict[str, Optional[str]]:
        """{nickname: library path} as KiCad resolves this table (``walk()`` order): a later row replaces an earlier
        one, a disabled row maps its nickname to None (it still hides an earlier row). ``resolve_libraries()``
        merges the global and project tables and drops the None entries."""
        out: Dict[str, Optional[str]] = {}
        for _, r, uri in self.walk(env, project_dir):
            if r.type != TABLE_TYPE:
                out[r.name] = None if r.disabled else uri
        return out

    # ------------------------------------------------------------------ writing
    def _in_project(self, full: str, original: str) -> str:
        assert self.project_dir is not None
        rel = os.path.relpath(_canon(full), _canon(self.project_dir))
        if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
            raise ValueError('%s is outside the project %s: copy the library into the project and register the '
                             'copy (a project table must open on any machine)' % (original, self.project_dir))
        if rel == os.curdir:
            raise ValueError('%s is the project folder itself, not a library' % original)
        return '${KIPRJMOD}/' + _slash(rel)

    def project_uri(self, path: str) -> str:
        """The uri to store for ``path``. In a project table: ``${KIPRJMOD}/...`` for anything inside the project
        (absolute, relative to the project folder, or already written with ``${KIPRJMOD}`` / ``$(KIPRJMOD)``), a
        KiCad install-folder variable (``${KICAD10_FOOTPRINT_DIR}/...``) kept as written, anything else refused."""
        if self.project_dir is None:
            return _slash(path).rstrip('/')
        vars_used = [m.group(1) or m.group(2) for m in _VAR.finditer(path)]
        if vars_used and vars_used[0] != 'KIPRJMOD':
            if all(_STOCK_VAR.match(v) for v in vars_used):
                return _slash(path).rstrip('/')
            raise ValueError('%s uses %s: a project table may use ${KIPRJMOD} and KiCad\'s install folders '
                             '(KICADn_SYMBOL_DIR, _FOOTPRINT_DIR, _3DMODEL_DIR, _TEMPLATE_DIR) only; any other variable '
                             'differs between machines' % (path, ', '.join(vars_used)))
        if vars_used:                                           # ${KIPRJMOD}/... or $(KIPRJMOD)/...
            full = expand_uri(path, self.project_dir, {})
            if _VAR.search(full):
                raise ValueError('%s: only one leading ${KIPRJMOD} is supported in a project uri' % path)
        else:
            full = os.path.join(self.project_dir, path)
        return self._in_project(full, path)

    def _same_file(self, a: str, b: str) -> bool:
        prj = self._prj()
        return _canon(expand_uri(a, prj, {})) == _canon(expand_uri(b, prj, {}))

    def add(self, name: str, uri: str, type: Optional[str] = None, options: Optional[str] = None,
            descr: Optional[str] = None, replace: bool = False, must_exist: bool = True) -> bool:
        """Register ``name`` -> ``uri``. True if the table changed; False if ``name`` already names this file.
        Raises if ``name`` names another file (``replace=True`` re-points it, keeping its other settings), if this
        file already has another nickname, if the file does not exist (``must_exist=False`` when you write it right
        after), or if a field holds a character KiCad cannot read. ``type`` defaults to "KiCad"."""
        if not name or name != name.strip() or any(c in name for c in ':\\') or any(ord(c) < 0x20 for c in name):
            raise ValueError('bad library nickname %r (KiCad allows no ":", "\\" or control characters; leading and '
                             'trailing spaces are refused here)' % name)
        uri = _slash(uri)
        for what, v in (('nickname', name), ('uri', uri), ('type', type or ''), ('options', options or ''),
                        ('descr', descr or '')):
            _check_field(what, v)
        uri = self.project_uri(uri)
        rows = self.tree.nodes('lib')
        mine = [n for n in rows if str(n.get('name', '')) == name]
        lib_type = type or (str(mine[-1].get('type', 'KiCad')) if mine else 'KiCad')
        if lib_type == 'KiCad' and not uri.rstrip('/').endswith(LIB_SUFFIX[self.kind]):
            raise ValueError('%s is not a %s library (expected a %s %s)' % (
                uri, self.kind, LIB_SUFFIX[self.kind], 'folder' if self.kind == 'fp' else 'file'))
        target = expand_uri(uri, self._prj())
        if must_exist and not _VAR.search(target) and not os.path.exists(target):
            raise ValueError('%s does not exist' % target)
        for n in rows:
            if str(n.get('name', '')) != name and self._same_file(str(n.get('uri', '')), uri):
                raise ValueError('%s is already registered as "%s"; use that nickname (or remove it first) - two '
                                 'nicknames for one library file split its references' % (uri, n.get('name')))
        if mine:
            n = mine[-1]                                        # the row KiCad uses
            given = [(h, v) for h, v in (('type', type), ('options', options), ('descr', descr))
                     if v is not None and str(n.get(h, '')) != v]
            if self._same_file(str(n.get('uri', '')), uri):
                for head, v in given:                           # same file: only the settings asked for change
                    n.set(head, v)
                return bool(given)
            if not replace:
                raise ValueError('nickname "%s" already names %s (asked for %s); re-pointing it must be explicit '
                                 '(replace)' % (name, n.get('uri'), uri))
            n.set('uri', uri)
            for head, v in (('type', type), ('options', options), ('descr', descr)):
                if v is not None:
                    n.set(head, v)
            return True
        self.tree.append(Node('lib', Node('name', name), Node('type', lib_type), Node('uri', uri),
                              Node('options', options or ''), Node('descr', descr or '')))
        return True

    def remove(self, name: str) -> bool:
        """Remove every row for ``name``. True if there was one."""
        mine = [n for n in self.tree.nodes('lib') if str(n.get('name', '')) == name]
        for n in mine:
            self.tree.remove_node(n)
        return bool(mine)

    def save(self, path: Optional[str] = None) -> None:
        target = path or self.path
        if not target:
            raise ValueError('no path given')
        if self.has_backslash:
            raise ValueError('%s holds a backslash: KiCad reads table strings literally, so rewriting it would change '
                             'them. Replace the backslashes with "/" (KiCad writes uris that way) and run again'
                             % self.path)
        save(self.tree, target)
        self.path = target


def resolve_libraries(project_dir: str, kind: str, env: Optional[Mapping[str, str]] = None,
                      include_global: bool = True) -> Dict[str, str]:
    """{nickname: library path} the way KiCad sees the project: the global table, then the project's (a project row
    replaces a global one of the same nickname; a disabled one removes it)."""
    vals = kicad_env(env)
    out: Dict[str, Optional[str]] = {}
    paths = ([global_table(kind)] if include_global else []) + [os.path.join(project_dir, TABLE_FILES[kind])]
    for p in paths:
        if p and os.path.isfile(p):
            out.update(LibTable.load(p, project_dir).resolve(vals, os.path.abspath(project_dir)))
    return {k: v for k, v in out.items() if v is not None}
