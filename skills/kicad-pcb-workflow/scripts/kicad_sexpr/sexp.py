"""Generic, lossless s-expression tree for KiCad files, with KiCad's own output formatting.

Every KiCad text format (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod, .kicad_wks, fp-lib-table, ...) is one
s-expression. This module reads any of them into a tree of plain Python values and writes the tree back the way
KiCad does: for a file KiCad itself saved, ``dumps(loads(text)) == text`` byte for byte (the test suite checks this
on real KiCad 10 boards, schematics, symbol and footprint libraries).

Tree model (deliberately small, no per-object classes, so no KiCad token is ever "unknown"):

* ``Node``   a list whose first element is the head keyword: ``Node('at', 10, 20, 90)`` is ``(at 10 20 90)``.
* ``Sym``    a bare (unquoted) token, e.g. ``yes``, ``smd``, ``F.Cu`` in a layers list, or a number as written.
* ``str``    a quoted string. Escaping (``\\``, ``"``, newline, CR) is done only here, on output.
* ``int`` / ``float`` / ``bool``  convenience values for building: numbers are written KiCad-style
  (no exponent, no trailing zeros, at most 6 decimals), ``True``/``False`` as ``yes``/``no``.

Numbers read from a file stay ``Sym`` (their original text), so an untouched value is written back unchanged.
Use ``num()`` to read one as a number.
"""
from __future__ import annotations

import re
from typing import Iterator, List, Optional, Union

__all__ = ['Sym', 'Node', 'Atom', 'Item', 'loads', 'dumps', 'load', 'save', 'num', 'fmt_num', 'quote', 'unquote',
           'SexpError']


class SexpError(ValueError):
    pass


class Sym(str):
    """A bare token. ``Sym('yes')`` is written ``yes``; the plain string ``'yes'`` is written ``"yes"``."""

    __slots__ = ()

    def __repr__(self) -> str:
        return 'Sym(%s)' % str.__repr__(self)


Atom = Union[Sym, str, int, float, bool]
Item = Union['Node', Atom]


class Node(List['Item']):
    """``(head item item ...)``. A ``list`` subclass: index, slice, append and iterate as usual; ``self[0]`` is the
    head ``Sym``. The helpers below cover the common KiCad idioms (find a child by head, read or set its values)."""

    def __init__(self, head: str, *items: Item) -> None:
        super().__init__()
        self.append(Sym(head))
        self.extend(items)

    # ---------------------------------------------------------------- reading
    @property
    def head(self) -> str:
        return str(self[0])

    @property
    def args(self) -> List[Item]:
        """Everything after the head."""
        return list(self[1:])

    def nodes(self, head: Optional[str] = None) -> List['Node']:
        """Direct child nodes (optionally only those with this head)."""
        return [c for c in self[1:] if isinstance(c, Node) and (head is None or c[0] == head)]

    def find(self, head: str) -> Optional['Node']:
        """First direct child ``(head ...)``, or None."""
        for c in self[1:]:
            if isinstance(c, Node) and c[0] == head:
                return c
        return None

    def need(self, head: str) -> 'Node':
        """First direct child ``(head ...)``; raises KeyError when there is none (use when the child must exist)."""
        c = self.find(head)
        if c is None:
            raise KeyError('(%s ...) has no (%s ...)' % (self.head, head))
        return c

    def number(self, index: int = 1, default: Optional[float] = None) -> float:
        """Item ``index`` of this node as a float: ``node.need('at').number(2)`` is the y of ``(at x y)``."""
        if len(self) <= index:
            if default is None:
                raise IndexError('(%s ...) has no item %d' % (self.head, index))
            return default
        return num(self[index])

    def find_all(self, head: str) -> List['Node']:
        return self.nodes(head)

    def walk(self, head: Optional[str] = None) -> Iterator['Node']:
        """This node and every node below it, depth first (optionally only those with this head)."""
        stack: List[Node] = [self]
        while stack:
            n = stack.pop()
            if head is None or n[0] == head:
                yield n
            stack.extend(reversed([c for c in n[1:] if isinstance(c, Node)]))

    def get(self, head: str, default: Optional[Item] = None, index: int = 1) -> Optional[Item]:
        """Value ``index`` of the first child ``(head ...)``: ``fp.get('layer') -> 'F.Cu'``."""
        c = self.find(head)
        if c is None or len(c) <= index:
            return default
        return c[index]

    def atoms(self) -> List[Atom]:
        """The non-node items after the head."""
        return [c for c in self[1:] if not isinstance(c, Node)]

    # ---------------------------------------------------------------- editing
    def set(self, head: str, *values: Item) -> 'Node':
        """Replace the values of the first child ``(head ...)`` (keeping its position), or append a new one.
        Returns the child."""
        c = self.find(head)
        if c is None:
            c = Node(head, *values)
            self.append(c)
        else:
            del c[1:]
            c.extend(values)
        return c

    def remove_all(self, head: str) -> int:
        """Remove every direct child ``(head ...)``; returns how many were removed."""
        keep = [c for c in self[1:] if not (isinstance(c, Node) and c[0] == head)]
        n = len(self) - 1 - len(keep)
        del self[1:]
        self.extend(keep)
        return n

    def remove_node(self, node: 'Node') -> None:
        """Remove this exact child object (identity, not equality)."""
        for i in range(1, len(self)):
            if self[i] is node:
                del self[i]
                return
        raise ValueError('node is not a direct child')

    def insert_before(self, head: str, node: 'Node') -> None:
        """Insert ``node`` before the first direct child with this head (append if there is none)."""
        for i in range(1, len(self)):
            c = self[i]
            if isinstance(c, Node) and c[0] == head:
                self.insert(i, node)
                return
        self.append(node)

    def insert_after_last(self, head: str, node: 'Node') -> None:
        """Insert ``node`` after the last direct child with this head (append if there is none)."""
        idx = None
        for i in range(1, len(self)):
            c = self[i]
            if isinstance(c, Node) and c[0] == head:
                idx = i
        if idx is None:
            self.append(node)
        else:
            self.insert(idx + 1, node)

    def deepcopy(self) -> 'Node':
        out = Node(str(self[0]))
        for c in self[1:]:
            out.append(c.deepcopy() if isinstance(c, Node) else c)
        return out

    def __repr__(self) -> str:
        return 'Node(%s)' % ', '.join(repr(c) for c in self)

    def __str__(self) -> str:
        return dumps(self).rstrip('\n')


# -------------------------------------------------------------------- atoms

def fmt_num(v: Union[int, float]) -> str:
    """KiCad-style number: ``1``, ``0.25``, ``-3.81`` (no exponent, at most 6 decimals, no ``-0``)."""
    if isinstance(v, bool):
        raise TypeError('bool is not a number here')
    if isinstance(v, int):
        return str(v)
    if v != v or v in (float('inf'), float('-inf')):
        raise ValueError('cannot write %r to a KiCad file' % v)
    s = ('%.6f' % v).rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def num(a: Item) -> float:
    """An atom as a number (``Sym('1.27') -> 1.27``)."""
    if isinstance(a, bool) or isinstance(a, Node):
        raise TypeError('not a number: %r' % (a,))
    return float(a)


def quote(s: str) -> str:
    """Quote a string the way KiCad's OUTPUTFORMATTER::Quotes does: escape backslash, double quote, newline and CR."""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r') + '"'


_UNESC = {'n': '\n', 'r': '\r', 't': '\t', '\\': '\\', '"': '"'}


def unquote(tok: str) -> str:
    """Inverse of quote() for a token read from a file (including the quotes)."""
    body = tok[1:-1]
    if '\\' not in body:
        return body
    out = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == '\\' and i + 1 < n:
            e = body[i + 1]
            if e in _UNESC:
                out.append(_UNESC[e])
            else:                       # unknown escape: keep it literally
                out.append(c + e)
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _atom_text(a: Atom) -> str:
    if isinstance(a, Sym):
        return str(a)
    if isinstance(a, bool):
        return 'yes' if a else 'no'
    if isinstance(a, str):
        return quote(a)
    if isinstance(a, (int, float)):
        return fmt_num(a)
    raise TypeError('cannot write %r (%s) to a KiCad file' % (a, type(a).__name__))


# -------------------------------------------------------------------- parse

_TOKEN = re.compile(r'\s+|(\()|(\))|("(?:[^"\\]|\\.)*")|([^\s()"]+)', re.S)


def loads(text: str) -> Node:
    """Parse one KiCad s-expression document (any file type) into a Node tree."""
    stack: List[Node] = []
    root: Optional[Node] = None
    pos = 0
    n = len(text)
    m = _TOKEN.match
    while pos < n:
        mo = m(text, pos)
        if mo is None:
            raise SexpError('unexpected character %r at offset %d' % (text[pos], pos))
        pos = mo.end()
        if mo.lastindex is None:            # whitespace
            continue
        k = mo.lastindex
        if k == 1:
            # head token follows directly
            node = Node.__new__(Node)
            list.__init__(node)
            if stack:
                stack[-1].append(node)
            elif root is None:
                root = node
            else:
                raise SexpError('more than one top-level expression (offset %d)' % mo.start())
            stack.append(node)
        elif k == 2:
            if not stack:
                raise SexpError('unmatched ")" at offset %d' % mo.start())
            done = stack.pop()
            if not done or not isinstance(done[0], Sym):
                raise SexpError('list without a head keyword at offset %d' % mo.start())
        else:
            tok = mo.group(k)
            if not stack:
                raise SexpError('atom outside any list at offset %d' % mo.start())
            stack[-1].append(unquote(tok) if k == 3 else Sym(tok))
    if stack:
        raise SexpError('%d unclosed "(" at end of input' % len(stack))
    if root is None:
        raise SexpError('empty document')
    return root


def load(path: str) -> Node:
    with open(path, encoding='utf-8') as f:
        return loads(f.read())


# -------------------------------------------------------------------- write

_XY_LIMIT = 99          # KiCad keeps consecutive (xy ...) on one line until this column
_WRAP = 72              # ... and wraps long runs of atoms after this column


def _tokens(node: Node, out: List[str]) -> None:
    out.append('(')
    for c in node:
        if isinstance(c, Node):
            _tokens(c, out)
        else:
            out.append(_atom_text(c))
    out.append(')')


def dumps(node: Node) -> str:
    """Write a tree exactly as KiCad 10 formats its files (a port of KiCad's KICAD_FORMAT::Prettify)."""
    toks: List[str] = []
    _tokens(node, toks)
    out: List[str] = []
    depth = 0
    col = 0
    in_xy = False
    multi = False
    last = ''
    for i, t in enumerate(toks):
        if t == '(':
            cur_xy = toks[i + 1] == 'xy'
            if not out:
                out.append('(')
                col += 1
            elif in_xy and cur_xy and col < _XY_LIMIT:
                out.append(' (')
                col += 2
            else:
                out.append('\n' + '\t' * depth + '(')
                col = depth + 1
            in_xy = cur_xy
            depth += 1
        elif t == ')':
            depth -= 1
            if last == ')' or multi:
                out.append('\n' + '\t' * depth + ')')
                col = depth + 1
                multi = False
            else:
                out.append(')')
                col += 1
        else:
            if last != '(' and depth > 0:
                if in_xy or col < _WRAP:
                    out.append(' ')
                    col += 1
                else:
                    out.append('\n' + '\t' * depth)
                    col = depth
                    multi = True
            out.append(t)
            col += len(t.encode('utf-8'))
        last = t if t in ('(', ')') else 'a'
    out.append('\n')
    return ''.join(out)


def save(node: Node, path: str) -> None:
    text = dumps(node)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
