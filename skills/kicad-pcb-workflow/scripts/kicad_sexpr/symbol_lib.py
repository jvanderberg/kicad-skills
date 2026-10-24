"""Symbol libraries (.kicad_sym): read symbols (derived symbols flattened), list pins, build new symbols.

A library symbol is a ``(symbol "Name" ...)`` node whose graphics and pins live in unit sub-symbols named
``Name_<unit>_<body style>`` (unit 0 / body style 0 = shared by all). Library coordinates have y pointing *up*.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from .common import SYMBOL_LIB_VERSION, font_effects, header, stroke
from .sexp import Node, Sym, load, loads, save

__all__ = ['Pin', 'SymbolLibrary', 'pins_of', 'flatten', 'lib_symbol', 'lib_pin', 'lib_rectangle', 'lib_polyline',
           'lib_property']


class Pin(NamedTuple):
    number: str
    name: str
    etype: str          # input, output, bidirectional, tri_state, passive, free, unspecified, power_in, ...
    shape: str          # line, inverted, clock, ...
    x: float            # connection point, library coordinates (y up)
    y: float
    angle: float        # direction from the connection point towards the body
    length: float
    unit: int           # 0 = all units
    body_style: int     # 0 = all body styles
    hidden: bool


def _unit_of(sub_name: str) -> Tuple[int, int]:
    parts = sub_name.rsplit('_', 2)
    try:
        return int(parts[-2]), int(parts[-1])
    except (ValueError, IndexError):
        return 0, 0


def pins_of(sym: Node, unit: Optional[int] = None, body_style: Optional[int] = 1) -> List[Pin]:
    """Pins of a (flattened) library symbol. ``unit``/``body_style`` None = all; otherwise the pins drawn for that
    unit and body style (shared unit-0 / style-0 pins included)."""
    out: List[Pin] = []
    for sub in sym.nodes('symbol'):
        u, b = _unit_of(str(sub[1]))
        if unit is not None and u not in (0, unit):
            continue
        if body_style is not None and b not in (0, body_style):
            continue
        for p in sub.nodes('pin'):
            at = p.find('at')
            name = p.find('name')
            number = p.find('number')
            hide = p.find('hide')
            out.append(Pin(number=str(number[1]) if number is not None else '',
                           name=str(name[1]) if name is not None else '',
                           etype=str(p[1]), shape=str(p[2]) if len(p) > 2 and not isinstance(p[2], Node) else 'line',
                           x=float(at[1]), y=float(at[2]), angle=float(at[3]) if len(at) > 3 else 0.0,  # type: ignore
                           length=float(p.get('length', 0)),  # type: ignore[arg-type]
                           unit=u, body_style=b,
                           hidden=hide is not None and str(hide[1]) != 'no'))
    return out


def _rename(sym: Node, new_name: str) -> Node:
    old = str(sym[1])
    out = sym.deepcopy()
    out[1] = new_name
    base = new_name.split(':', 1)[-1]
    for sub in out.nodes('symbol'):
        sname = str(sub[1])
        if sname.startswith(old.split(':', 1)[-1] + '_'):
            sub[1] = base + sname[len(old.split(':', 1)[-1]):]
    return out


def flatten(sym: Node, lookup: Dict[str, Node]) -> Node:
    """A self-contained copy of ``sym``: a derived symbol (``(extends "Parent")``) becomes the parent's body and pins
    with the child's properties and flags on top (what a schematic's lib_symbols needs)."""
    ext = sym.find('extends')
    if ext is None:
        return sym.deepcopy()
    parent = flatten(lookup[str(ext[1])], lookup)
    out = _rename(parent, str(sym[1]))
    for c in sym[2:]:
        if not isinstance(c, Node) or c[0] in ('extends',):
            continue
        if c[0] == 'property':
            mine = [p for p in out.nodes('property') if p[1] == c[1]]
            if mine:
                idx = out.index(mine[0])
                out[idx] = c.deepcopy()
            else:
                last = out.nodes('property')
                pos = out.index(last[-1]) + 1 if last else len(out)
                out.insert(pos, c.deepcopy())
        elif c[0] == 'symbol':
            out.append(c.deepcopy())
        else:
            existing = out.find(str(c[0]))
            if existing is not None:
                out[out.index(existing)] = c.deepcopy()
            else:
                out.append(c.deepcopy())
    return out


class SymbolLibrary:
    """A .kicad_sym file. ``get(name)`` returns a flattened deep copy; edit ``tree`` directly for anything else."""

    def __init__(self, tree: Node, nickname: str = '', path: Optional[str] = None) -> None:
        if tree[0] != 'kicad_symbol_lib':
            raise ValueError('not a symbol library: %s' % tree[0])
        self.tree = tree
        self.nickname = nickname
        self.path = path

    @classmethod
    def load(cls, path: str, nickname: str = '') -> 'SymbolLibrary':
        return cls(load(path), nickname, path)

    @classmethod
    def from_text(cls, text: str, nickname: str = '') -> 'SymbolLibrary':
        return cls(loads(text), nickname)

    @classmethod
    def new(cls, nickname: str = '') -> 'SymbolLibrary':
        return cls(header('kicad_symbol_lib', SYMBOL_LIB_VERSION, 'kicad_symbol_editor'), nickname)

    def _index(self) -> Dict[str, Node]:
        return {str(s[1]): s for s in self.tree.nodes('symbol')}

    def names(self) -> List[str]:
        return [str(s[1]) for s in self.tree.nodes('symbol')]

    def raw(self, name: str) -> Node:
        idx = self._index()
        if name not in idx:
            raise KeyError('symbol %r not in library %s' % (name, self.nickname or self.path))
        return idx[name]

    def get(self, name: str) -> Node:
        self.raw(name)
        return flatten(self._index()[name], self._index())

    def pins(self, name: str, unit: Optional[int] = None, body_style: Optional[int] = 1) -> List[Pin]:
        return pins_of(self.get(name), unit, body_style)

    def add(self, sym: Node, replace: bool = True) -> None:
        name = str(sym[1])
        idx = self._index()
        if name in idx:
            if not replace:
                raise ValueError('symbol %r already in library' % name)
            self.tree[self.tree.index(idx[name])] = sym
        else:
            self.tree.insert_before('embedded_fonts', sym) if self.tree.find('embedded_fonts') is not None \
                else self.tree.append(sym)

    def save(self, path: Optional[str] = None) -> None:
        save(self.tree, path or self.path or '')


# -------------------------------------------------------------------- building library symbols

def lib_property(name: str, value: str, x: float = 0, y: float = 0, angle: float = 0, hide: bool = False,
                 size: float = 1.27, justify: Iterable[str] = ()) -> Node:
    p = Node('property', name, value, Node('at', x, y, angle), Node('show_name', False),
             Node('do_not_autoplace', False))
    if hide:
        p.append(Node('hide', True))
    p.append(font_effects(size, justify=justify))
    return p


def lib_pin(etype: str, x: float, y: float, angle: float, name: str, number: str, length: float = 2.54,
            shape: str = 'line', hide: bool = False, size: float = 1.27) -> Node:
    """``(pin <etype> <shape> (at x y angle) (length l) [(hide yes)] (name ...) (number ...))``; (x, y) is the
    connection point and ``angle`` points from it towards the body (0 = pin on the left side, pointing right)."""
    p = Node('pin', Sym(etype), Sym(shape), Node('at', x, y, angle), Node('length', length))
    if hide:
        p.append(Node('hide', True))
    p.append(Node('name', name, font_effects(size)))
    p.append(Node('number', number, font_effects(size)))
    return p


def lib_rectangle(x1: float, y1: float, x2: float, y2: float, width: float = 0.254, fill: str = 'background') -> Node:
    return Node('rectangle', Node('start', x1, y1), Node('end', x2, y2), stroke(width),
                Node('fill', Node('type', Sym(fill))))


def lib_polyline(points: Sequence[Tuple[float, float]], width: float = 0.254, fill: str = 'none') -> Node:
    return Node('polyline', Node('pts', *[Node('xy', x, y) for x, y in points]), stroke(width),
                Node('fill', Node('type', Sym(fill))))


def lib_symbol(name: str, properties: Sequence[Node], units: Dict[Tuple[int, int], Sequence[Node]],
               pin_names_offset: Optional[float] = 0.508, hide_pin_names: bool = False,
               hide_pin_numbers: bool = False, power: bool = False, in_bom: bool = True, on_board: bool = True,
               exclude_from_sim: bool = False) -> Node:
    """A complete library symbol. ``units`` maps (unit, body_style) to the graphics and pins of that sub-symbol;
    use (0, 1) for body graphics shared by all units and (1, 1) for unit 1's pins."""
    s = Node('symbol', name)
    if power:
        s.append(Node('power'))
    if hide_pin_numbers:
        s.append(Node('pin_numbers', Node('hide', True)))
    if pin_names_offset is not None or hide_pin_names:
        pn = Node('pin_names')
        if pin_names_offset is not None:
            pn.append(Node('offset', pin_names_offset))
        if hide_pin_names:
            pn.append(Node('hide', True))
        s.append(pn)
    s.extend([Node('exclude_from_sim', exclude_from_sim), Node('in_bom', in_bom), Node('on_board', on_board),
              Node('in_pos_files', True), Node('duplicate_pin_numbers_are_jumpers', False)])
    s.extend(properties)
    for (u, b), items in sorted(units.items()):
        s.append(Node('symbol', '%s_%d_%d' % (name, u, b), *items))
    s.append(Node('embedded_fonts', False))
    return s

