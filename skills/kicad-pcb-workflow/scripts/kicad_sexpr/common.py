"""Rules shared by every KiCad file type: version headers, uuids, net-name escaping, geometry helpers.

Version numbers are the ones KiCad 10.0.1 writes (read from files it saved): boards and footprints 20260206,
schematics 20260306, symbol libraries 20251024.
"""
from __future__ import annotations

import math
import uuid as _uuid
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .sexp import Node, Sym, fmt_num, num

KICAD_VERSION = '10.0'
PCB_VERSION = 20260206
FOOTPRINT_VERSION = 20260206
SCH_VERSION = 20260306
SYMBOL_LIB_VERSION = 20251024

Point = Tuple[float, float]


def header(kind: str, version: int, generator: str) -> Node:
    """``(kind (version N) (generator "...") (generator_version "10.0"))`` -- the start of every KiCad 10 file."""
    return Node(kind, Node('version', version), Node('generator', generator),
                Node('generator_version', KICAD_VERSION))


# -------------------------------------------------------------------- uuids

# Fixed namespace for derived uuids (uuid5). Never change it: every generated file's ids depend on it.
UUID_NAMESPACE = _uuid.UUID('6b1f3c1e-6a43-5c0f-9a52-4b6963616473')


class IdMap(Dict[str, str]):
    """{stable key: uuid} read from an existing file, so a regenerated file keeps the ids its items already had
    (KiCad GUI edits and committed files included). Two items with the same key get ``key``, ``key#2``, ... in file
    order (the same suffixes the builders use) and the key is listed in ``ambiguous``."""

    def __init__(self) -> None:
        super().__init__()
        self.ambiguous: List[str] = []

    def put(self, key: str, uuid: str) -> None:
        k, n = key, 1
        while k in self:
            n += 1
            k = '%s#%d' % (key, n)
        if n == 2:
            self.ambiguous.append(key)
        self[k] = uuid


class Uuids:
    """uuids that are unique within one document (existing uuids are registered when a file is loaded).

    With a ``seed`` (what Board and Schematic use) ids are stable: ``new(key)`` takes a key that names the item
    (``footprint/R1``, ``segment/GND/F.Cu/1,2/3,4``) and returns, in this order,
    1. the uuid that key had in the previous version of the file (``reuse``, an IdMap; see Board.reuse_ids /
       Schematic.reuse_ids), so parts keep their ids across regenerations and GUI edits;
    2. otherwise uuid5 of the seed and the key: regenerating from scratch gives the same ids, and adding an item
       does not shift anyone else's.
    A key whose id is already taken gets ``#2``, ``#3``, ... appended: never a duplicate. Calls without a key get
    ``~anon/<n>`` (deterministic, but shifted by insertions, so builders always pass keys). Without a seed, ids are
    random (uuid4)."""

    def __init__(self, existing: Iterable[str] = (), seed: Optional[str] = None,
                 reuse: Optional[Dict[str, str]] = None) -> None:
        self.used: Set[str] = set(existing)
        self.seed = seed
        self.reuse: Dict[str, str] = reuse if reuse is not None else {}
        self.reused = 0
        self._anon = 0

    def new(self, key: Optional[str] = None) -> str:
        if self.seed is None:
            while True:
                u = str(_uuid.uuid4())
                if u not in self.used:
                    self.used.add(u)
                    return u
        if key is None:
            self._anon += 1
            key = '~anon/%d' % self._anon
        k, n = key, 1
        while True:
            old = self.reuse.get(k)
            if old is not None and old not in self.used:
                self.used.add(old)
                self.reused += 1
                return old
            if old is None:
                u = str(_uuid.uuid5(UUID_NAMESPACE, self.seed + '\n' + k))
                if u not in self.used:
                    self.used.add(u)
                    return u
            n += 1
            k = '%s#%d' % (key, n)

    def take(self, u: str) -> str:
        """Register an explicit uuid; raises if the document already uses it."""
        u = str(_uuid.UUID(u))
        if u in self.used:
            raise ValueError('uuid %s is already used in this document' % u)
        self.used.add(u)
        return u

    def node(self, key: Optional[str] = None) -> Node:
        return Node('uuid', self.new(key))

    def scan(self, tree: Node) -> None:
        for n in tree.walk('uuid'):
            if len(n) > 1:
                self.used.add(str(n[1]))


def pt_key(*points: Point) -> str:
    """Stable text for coordinates in a uuid key: '1.27,2.54/3,4', rounded to 1 um so that a position pcbnew stored
    as 135.349999 matches 135.35 (items closer than that are told apart by the #2 suffix)."""
    return '/'.join('%s,%s' % (fmt_num(round(x, 3) + 0.0), fmt_num(round(y, 3) + 0.0)) for x, y in points)


def duplicate_uuids(tree: Node) -> List[str]:
    """uuids that appear more than once (KiCad silently re-assigns them, breaking schematic/board links)."""
    c = Counter(str(n[1]) for n in tree.walk('uuid') if len(n) > 1)
    return sorted(u for u, k in c.items() if k > 1)


def refresh_uuids(tree: Node, uuids: Uuids, prefix: str = '') -> None:
    """Give every ``(uuid ...)`` below ``tree`` a fresh value (for copies of library or existing items), keyed by
    ``prefix`` and the item's position (head + ordinal path)."""
    def walk(n: Node, path: str) -> None:
        seen: Dict[str, int] = {}
        for c in n[1:]:
            if not isinstance(c, Node):
                continue
            if c.head == 'uuid':
                del c[1:]
                c.append(uuids.new(path))
                continue
            k = seen.get(c.head, 0)
            seen[c.head] = k + 1
            walk(c, '%s/%s[%d]' % (path, c.head, k))
    walk(tree, prefix)


# -------------------------------------------------------------------- strings

def check_text(s: str) -> str:
    """Strings are escaped on output (sexp.quote); this only rejects values KiCad cannot represent at all."""
    if '\x00' in s:
        raise ValueError('NUL character in %r' % s)
    return s


def board_net_name(netlist_name: str) -> str:
    """Net name as a .kicad_pcb stores it, from the name in a kicad-cli netlist export.

    KiCad writes '/' inside auto-generated names as ``{slash}`` (``Net-(U1-EN/UVLO)`` is stored
    ``Net-(U1-EN{slash}UVLO)``); a board that spells it with '/' gets DRC ``net_conflict`` / parity errors.
    Only names starting ``Net-(`` or ``unconnected-(`` are changed: in hierarchical names ('/sheet/NET') the
    slashes are sheet separators and stay as they are."""
    if netlist_name.startswith(('Net-(', 'unconnected-(')):
        return netlist_name.replace('/', '{slash}')
    return netlist_name


# -------------------------------------------------------------------- geometry

def norm_angle(a: float, signed: bool = False) -> float:
    """Angle in degrees normalised to [0, 360), or to (-180, 180] with signed=True."""
    a = math.fmod(a, 360.0)
    if a < 0:
        a += 360.0
    if signed and a > 180.0:
        a -= 360.0
    a = round(a, 6)
    if a == 360.0:
        a = 0.0
    return a + 0.0


def rotate(x: float, y: float, angle: float) -> Point:
    """Rotate a point (y pointing down, as in KiCad sheet/board coordinates) by ``angle`` degrees, positive =
    counter-clockwise on screen. This is how KiCad turns a footprint's local pad offset into a board position."""
    if angle % 360 == 0:
        return x, y
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    return x * c + y * s, -x * s + y * c


def r6(v: float) -> float:
    """Round to KiCad's board resolution (1 nm) and drop -0."""
    return round(v, 6) + 0.0


def xy_list(points: Iterable[Point]) -> Node:
    """``(pts (xy x y) ...)``"""
    return Node('pts', *[Node('xy', r6(x), r6(y)) for x, y in points])


def stroke(width: float = 0, type_: str = 'default') -> Node:
    return Node('stroke', Node('width', width), Node('type', Sym(type_)))


def font_effects(size: float = 1.27, thickness: Optional[float] = None, bold: bool = False, italic: bool = False,
                 justify: Iterable[str] = (), hide: bool = False) -> Node:
    """``(effects (font (size s s) [(thickness t)] [(bold yes)] [(italic yes)]) [(justify ...)] [(hide yes)])``"""
    font = Node('font', Node('size', size, size))
    if thickness is not None:
        font.append(Node('thickness', thickness))
    if bold:
        font.append(Node('bold', True))
    if italic:
        font.append(Node('italic', True))
    eff = Node('effects', font)
    j = [Sym(v) for v in justify]
    if j:
        eff.append(Node('justify', *j))
    if hide:
        eff.append(Node('hide', True))
    return eff


def atoms_to_floats(n: Optional[Node], count: int) -> List[float]:
    if n is None:
        return [0.0] * count
    out = [num(v) for v in n[1:1 + count]]
    return out + [0.0] * (count - len(out))


def props_of(node: Node) -> Dict[str, Node]:
    """``{name: (property name value ...)}`` for a symbol / footprint node."""
    return {str(p[1]): p for p in node.nodes('property')}
