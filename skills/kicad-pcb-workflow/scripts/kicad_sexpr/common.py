"""Rules shared by every KiCad file type: version headers, uuids, net-name escaping, geometry helpers.

Version numbers are the ones KiCad 10.0.1 writes (read from files it saved): boards and footprints 20260206,
schematics 20260306, symbol libraries 20251024.
"""
from __future__ import annotations

import math
import uuid as _uuid
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .sexp import Node, Sym, num

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

class Uuids:
    """Fresh uuids that are unique within one document (existing uuids are registered when a file is loaded)."""

    def __init__(self, existing: Iterable[str] = ()) -> None:
        self.used: Set[str] = set(existing)

    def new(self) -> str:
        while True:
            u = str(_uuid.uuid4())
            if u not in self.used:
                self.used.add(u)
                return u

    def node(self) -> Node:
        return Node('uuid', self.new())

    def scan(self, tree: Node) -> None:
        for n in tree.walk('uuid'):
            if len(n) > 1:
                self.used.add(str(n[1]))


def duplicate_uuids(tree: Node) -> List[str]:
    """uuids that appear more than once (KiCad silently re-assigns them, breaking schematic/board links)."""
    c = Counter(str(n[1]) for n in tree.walk('uuid') if len(n) > 1)
    return sorted(u for u, k in c.items() if k > 1)


def refresh_uuids(tree: Node, uuids: Uuids) -> None:
    """Give every ``(uuid ...)`` below ``tree`` a fresh value (for copies of library or existing items)."""
    for n in tree.walk('uuid'):
        del n[1:]
        n.append(uuids.new())


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
