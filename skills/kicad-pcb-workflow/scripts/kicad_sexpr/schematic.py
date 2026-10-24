"""Schematic sheets (.kicad_sch): load / create, typed builders for the common items, generic access to the rest.

Coordinates are millimetres in sheet coordinates (y pointing down). Builders return the ``Node`` they inserted, so
anything a builder does not expose can still be set on the node (``sch.label(...).set('fields_autoplaced', True)``).
Items with no builder are added with ``sch.add(Node(...))``; every item already in a loaded file is kept as is.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple, Union

from .common import (SCH_VERSION, Point, Uuids, duplicate_uuids, font_effects, header, norm_angle, rotate, stroke)
from .sexp import Node, Sym, load, save
from .symbol_lib import Pin, SymbolLibrary, pins_of

__all__ = ['Schematic', 'SchSymbol', 'symbol_point']

# KiCad writes top-level schematic items grouped in this order; new items are inserted next to their kind.
_ORDER = ['version', 'generator', 'generator_version', 'uuid', 'paper', 'title_block', 'lib_symbols', 'bus_alias',
          'text', 'junction', 'no_connect', 'bus_entry', 'wire', 'bus', 'image', 'polyline', 'arc', 'circle',
          'rectangle', 'bezier', 'text_box', 'table', 'label', 'global_label', 'hierarchical_label', 'netclass_flag',
          'directive_label', 'rule_area', 'symbol', 'sheet', 'sheet_instances', 'symbol_instances', 'group',
          'embedded_fonts', 'embedded_files']


def _sch_round(v: float) -> float:
    return round(v, 4) + 0.0          # schematic internal unit is 100 nm


def symbol_point(lx: float, ly: float, at: Point, angle: float = 0, mirror: Optional[str] = None) -> Point:
    """Sheet position of a point given in library coordinates (y up) of a symbol placed at ``at`` with
    ``(at x y angle)`` and optional ``(mirror x|y)``: rotate first, then mirror (``x`` flips up/down,
    ``y`` flips left/right). Checked against kicad-cli netlists for all 8 orientations (tests)."""
    vx, vy = rotate(lx, -ly, angle)
    if mirror == 'x':
        vy = -vy
    elif mirror == 'y':
        vx = -vx
    elif mirror is not None:
        raise ValueError("mirror must be None, 'x' or 'y'")
    return _sch_round(at[0] + vx), _sch_round(at[1] + vy)


class SchSymbol:
    """A placed symbol: its node plus the embedded library symbol, for pin positions and field edits."""

    def __init__(self, sch: 'Schematic', node: Node) -> None:
        self.sch = sch
        self.node = node

    # ---------------------------------------------------------------- basics
    @property
    def lib_id(self) -> str:
        return str(self.node.get('lib_id'))

    @property
    def lib(self) -> Node:
        return self.sch.lib_symbol(self.lib_id)

    @property
    def at(self) -> Point:
        a = self.node.need('at')
        return a.number(1), a.number(2)

    @property
    def angle(self) -> float:
        return self.node.need('at').number(3, 0.0)

    @property
    def mirror(self) -> Optional[str]:
        m = self.node.get('mirror')
        return str(m) if m is not None else None

    @property
    def unit(self) -> int:
        return int(self.node.get('unit', 1))  # type: ignore[arg-type]

    @property
    def ref(self) -> str:
        return self.field_value('Reference')

    @property
    def value(self) -> str:
        return self.field_value('Value')

    @property
    def uuid(self) -> str:
        return str(self.node.get('uuid'))

    # ---------------------------------------------------------------- pins
    def lib_pins(self) -> List[Pin]:
        return pins_of(self.lib, self.unit, int(self.node.get('body_style', 1)))  # type: ignore[arg-type]

    def pin(self, key: Union[str, int]) -> Point:
        """Sheet position of a pin's connection point, by number or (unique) name, after rotation and mirror."""
        k = str(key)
        pins = self.lib_pins()
        cand = [p for p in pins if p.number == k] or [p for p in pins if p.name == k]
        if not cand:
            raise KeyError('%s has no pin %s' % (self.ref, k))
        if len({(p.x, p.y) for p in cand}) > 1:
            raise KeyError('%s: pin key %s is ambiguous (%s)' % (self.ref, k, [p.number for p in cand]))
        p = cand[0]
        return symbol_point(p.x, p.y, self.at, self.angle, self.mirror)

    def pins(self) -> Dict[str, Point]:
        """{pin number: sheet position} for the placed unit."""
        return {p.number: symbol_point(p.x, p.y, self.at, self.angle, self.mirror) for p in self.lib_pins()}

    # ---------------------------------------------------------------- fields
    def field(self, name: str) -> Optional[Node]:
        for p in self.node.nodes('property'):
            if p[1] == name:
                return p
        return None

    def fields(self) -> Dict[str, str]:
        """{name: value} of every property (what a footprint must carry for schematic parity, minus Reference,
        Value and Footprint)."""
        return {str(p[1]): str(p[2]) for p in self.node.nodes('property')}

    def field_value(self, name: str) -> str:
        f = self.field(name)
        return str(f[2]) if f is not None else ''

    def set_field(self, name: str, value: Optional[str] = None, at: Optional[Point] = None,
                  angle: Optional[float] = None, hide: Optional[bool] = None,
                  justify: Optional[Sequence[str]] = None, size: Optional[float] = None) -> Node:
        """Create or change a property. A new property is hidden and sits on the symbol origin unless told otherwise.
        Setting the Reference also updates the instances block."""
        f = self.field(name)
        if f is None:
            if value is None:
                value = ''
            x, y = at if at is not None else self.at
            f = Node('property', name, value, Node('at', _sch_round(x), _sch_round(y), angle or 0),
                     Node('hide', True), Node('show_name', False), Node('do_not_autoplace', False), font_effects(1.27))
            props = self.node.nodes('property')
            pos = self.node.index(props[-1]) + 1 if props else len(self.node)
            self.node.insert(pos, f)
            if hide is None:
                hide = True
        if value is not None:
            f[2] = value
            if name == 'Reference':
                for r in self.node.walk('reference'):
                    r[1] = value
        a = f.need('at')
        if at is not None:
            a[1], a[2] = _sch_round(at[0]), _sch_round(at[1])
        if angle is not None:
            del a[3:]
            a.append(norm_angle(angle))
        if hide is not None:
            f.remove_all('hide')
            if hide:
                f.insert(f.index(a) + 1, Node('hide', True))
        eff = f.find('effects')
        if eff is None:
            eff = font_effects(1.27)
            f.append(eff)
        if justify is not None:
            eff.remove_all('justify')
            j = [Sym(v) for v in justify if v != 'center']
            if j:
                eff.insert_after_last('font', Node('justify', *j))
        if size is not None:
            eff.need('font').set('size', size, size)
        return f

    def move(self, at: Point) -> None:
        """Move the symbol and its fields together."""
        dx, dy = at[0] - self.at[0], at[1] - self.at[1]
        a = self.node.need('at')
        a[1], a[2] = _sch_round(at[0]), _sch_round(at[1])
        for p in self.node.nodes('property'):
            pa = p.need('at')
            pa[1], pa[2] = _sch_round(pa.number(1) + dx), _sch_round(pa.number(2) + dy)


class Schematic:
    """One .kicad_sch sheet."""

    def __init__(self, tree: Node, path: Optional[str] = None, project: Optional[str] = None,
                 instance_path: Optional[str] = None) -> None:
        if tree[0] != 'kicad_sch':
            raise ValueError('not a schematic: %s' % tree[0])
        self.tree = tree
        self.path = path
        self.uuids = Uuids()
        self.uuids.scan(tree)
        self.project = project or self._guess_project()
        # instance path of this sheet: "/<root uuid>" for a root sheet, "/<root uuid>/<sheet uuid>" for a sub-sheet
        self.instance_path = instance_path or self._guess_instance_path()
        self._pwr = 0

    # ---------------------------------------------------------------- create / load / save
    @classmethod
    def new(cls, project: str, paper: str = 'A4', title: str = '', date: str = '', rev: str = '',
            company: str = '', comments: Sequence[str] = (), instance_path: Optional[str] = None,
            root: bool = True) -> 'Schematic':
        """An empty sheet. ``project`` is the project name used in symbol instances (the .kicad_pro stem).
        Sub-sheets (root=False) need ``instance_path`` = "/<root sheet uuid>/<sheet block uuid>"."""
        t = header('kicad_sch', SCH_VERSION, 'eeschema')
        u = Uuids()
        t.append(Node('uuid', u.new()))
        t.append(Node('paper', paper))
        if title or date or rev or company or comments:
            tb = Node('title_block')
            for k, v in (('title', title), ('date', date), ('rev', rev), ('company', company)):
                if v:
                    tb.append(Node(k, v))
            for i, c in enumerate(comments, 1):
                tb.append(Node('comment', i, c))
            t.append(tb)
        t.append(Node('lib_symbols'))
        if root:
            t.append(Node('sheet_instances', Node('path', '/', Node('page', '1'))))
        t.append(Node('embedded_fonts', False))
        s = cls(t, None, project, instance_path)
        s.uuids = u
        return s

    @classmethod
    def load(cls, path: str, project: Optional[str] = None, instance_path: Optional[str] = None) -> 'Schematic':
        return cls(load(path), path, project, instance_path)

    def save(self, path: Optional[str] = None) -> None:
        """Validate (unique uuids, unique references on this sheet) and write in KiCad's format."""
        problems = self.validate()
        if problems:
            raise ValueError('refusing to write an invalid schematic:\n  ' + '\n  '.join(problems))
        target = path or self.path
        if not target:
            raise ValueError('no path given')
        save(self.tree, target)
        self.path = target

    def validate(self) -> List[str]:
        out = []
        d = duplicate_uuids(self.tree)
        if d:
            out.append('%d duplicated uuids, e.g. %s' % (len(d), d[:3]))
        refs: Dict[Tuple[str, int], int] = {}
        for s in self.symbols():
            if s.ref.startswith('#'):
                continue
            k = (s.ref, s.unit)
            refs[k] = refs.get(k, 0) + 1
        dup = sorted('%s unit %d' % k for k, n in refs.items() if n > 1)
        if dup:
            out.append('duplicate references: %s' % dup[:10])
        for s in self.symbols():
            if s.lib_id not in self._lib_index():
                out.append('%s uses %s, which is not in lib_symbols' % (s.ref, s.lib_id))
        return out

    def _guess_project(self) -> str:
        for p in self.tree.walk('project'):
            return str(p[1])
        if self.path:
            return os.path.splitext(os.path.basename(self.path))[0]
        return ''

    def _guess_instance_path(self) -> str:
        for p in self.tree.walk('path'):
            if len(p) > 1 and str(p[1]).startswith('/') and p.find('reference') is not None:
                return str(p[1])
        return '/' + self.uuid

    @property
    def uuid(self) -> str:
        return str(self.tree.get('uuid'))

    # ---------------------------------------------------------------- generic
    def add(self, node: Node) -> Node:
        """Insert any top-level item next to the items of its kind (KiCad's grouping)."""
        head = node.head
        kids = [(i, c) for i, c in enumerate(self.tree) if i > 0 and isinstance(c, Node)]
        same = [i for i, c in kids if c.head == head]
        if same:
            self.tree.insert(same[-1] + 1, node)
            return node
        rank = _ORDER.index(head) if head in _ORDER else _ORDER.index('symbol')
        for i, c in kids:
            if c.head in _ORDER and _ORDER.index(c.head) > rank:
                self.tree.insert(i, node)
                return node
        self.tree.append(node)
        return node

    def items(self, head: str) -> List[Node]:
        return self.tree.nodes(head)

    # ---------------------------------------------------------------- library symbols
    def _lib_index(self) -> Dict[str, Node]:
        ls = self.tree.find('lib_symbols')
        return {str(s[1]): s for s in ls.nodes('symbol')} if ls is not None else {}

    def lib_symbol(self, lib_id: str) -> Node:
        idx = self._lib_index()
        if lib_id not in idx:
            raise KeyError('%s is not embedded in this schematic (call embed_symbol first)' % lib_id)
        return idx[lib_id]

    def embed_symbol(self, lib_id: str, source: Union[Node, SymbolLibrary], replace: bool = False) -> Node:
        """Copy a library symbol into lib_symbols as ``lib_id`` ("Lib:Name"). ``source`` is a symbol node or a
        SymbolLibrary (the part after ':' is looked up, derived symbols flattened). Kept sorted by name."""
        ls = self.tree.find('lib_symbols')
        if ls is None:
            ls = self.add(Node('lib_symbols'))
        idx = self._lib_index()
        if lib_id in idx and not replace:
            return idx[lib_id]
        name = lib_id.split(':', 1)[1] if ':' in lib_id else lib_id
        sym = source.get(name) if isinstance(source, SymbolLibrary) else source.deepcopy()
        old = str(sym[1]).split(':', 1)[-1]
        sym[1] = lib_id
        for sub in sym.nodes('symbol'):                   # unit sub-symbols keep the bare name: "R_0_1"
            sname = str(sub[1])
            if sname.startswith(old + '_'):
                sub[1] = name + sname[len(old):]
        if lib_id in idx:
            ls[ls.index(idx[lib_id])] = sym
            return sym
        names = [str(s[1]) for s in ls.nodes('symbol')]
        pos = len(ls)
        for i, n in enumerate(names):
            if n > lib_id:
                pos = ls.index(ls.nodes('symbol')[i])
                break
        ls.insert(pos, sym)
        return sym

    # ---------------------------------------------------------------- symbols
    def symbols(self) -> List[SchSymbol]:
        return [SchSymbol(self, n) for n in self.tree.nodes('symbol')]

    def symbol(self, ref: str, unit: Optional[int] = None) -> SchSymbol:
        for s in self.symbols():
            if s.ref == ref and (unit is None or s.unit == unit):
                return s
        raise KeyError('no symbol %s on this sheet' % ref)

    def add_symbol(self, lib_id: str, ref: str, value: str, at: Point, angle: float = 0,
                   mirror: Optional[str] = None, unit: int = 1, body_style: int = 1,
                   footprint: Optional[str] = None, datasheet: Optional[str] = None,
                   description: Optional[str] = None, fields: Optional[Dict[str, str]] = None,
                   lib: Optional[Union[Node, SymbolLibrary]] = None, in_bom: bool = True, on_board: bool = True,
                   dnp: bool = False, exclude_from_sim: bool = False, in_pos_files: bool = True) -> SchSymbol:
        """Place a symbol. Its library symbol must be embedded already, or given as ``lib``. Fields start where the
        library puts them (offsets rotated/mirrored with the symbol, text angles as in the library); extra
        ``fields`` are added hidden. Move or show fields afterwards with ``SchSymbol.set_field``."""
        if lib is not None:
            self.embed_symbol(lib_id, lib)
        libsym = self.lib_symbol(lib_id)
        x, y = _sch_round(at[0]), _sch_round(at[1])
        n = Node('symbol', Node('lib_id', lib_id), Node('at', x, y, norm_angle(angle)))
        if mirror:
            n.append(Node('mirror', Sym(mirror)))
        n.extend([Node('unit', unit), Node('body_style', body_style), Node('exclude_from_sim', exclude_from_sim),
                  Node('in_bom', in_bom), Node('on_board', on_board), Node('in_pos_files', in_pos_files),
                  Node('dnp', dnp), Node('uuid', self.uuids.new())])
        values = {'Reference': ref, 'Value': value}
        for k, v in (('Footprint', footprint), ('Datasheet', datasheet), ('Description', description)):
            if v is not None:
                values[k] = v
        seen = set()
        for lp in libsym.nodes('property'):
            name = str(lp[1])
            if name.startswith('ki_'):
                continue
            seen.add(name)
            la = lp.need('at')
            lx, ly = la.number(1), la.number(2)
            px, py = symbol_point(lx, ly, (x, y), angle, mirror)
            p = Node('property', name, values.get(name, str(lp[2])),
                     Node('at', px, py, la.number(3, 0.0)))
            hidden = lp.find('hide')
            if hidden is not None and str(hidden[1]) != 'no':
                p.append(Node('hide', True))
            p.append(Node('show_name', False))
            p.append(Node('do_not_autoplace', False))
            eff = lp.find('effects')
            p.append(eff.deepcopy() if eff is not None else font_effects(1.27))
            n.append(p)
        for k in ('Footprint', 'Datasheet', 'Description'):
            if k in values and k not in seen:
                n.append(Node('property', k, values[k], Node('at', x, y, 0), Node('hide', True),
                              Node('show_name', False), Node('do_not_autoplace', False), font_effects(1.27)))
        for k, v in (fields or {}).items():
            n.append(Node('property', k, v, Node('at', x, y, 0), Node('hide', True), Node('show_name', False),
                          Node('do_not_autoplace', False), font_effects(1.27)))
        nums = []
        for pin in pins_of(libsym, unit, body_style):
            if pin.number not in nums:
                nums.append(pin.number)
        for num in nums:
            n.append(Node('pin', num, Node('uuid', self.uuids.new())))
        n.append(Node('instances', Node('project', self.project,
                                        Node('path', self.instance_path, Node('reference', ref), Node('unit', unit)))))
        self.add(n)
        return SchSymbol(self, n)

    def power(self, lib_id: str, at: Point, angle: float = 0, value: Optional[str] = None,
              lib: Optional[Union[Node, SymbolLibrary]] = None, ref: Optional[str] = None) -> SchSymbol:
        """A power symbol (``power:GND``, ``power:+3V3``, ...). Its Value names the net (default: the symbol's own
        Value). The reference ``#PWRnnn`` is chosen unique on this sheet and hidden."""
        if lib is not None:
            self.embed_symbol(lib_id, lib)
        libsym = self.lib_symbol(lib_id)
        if value is None:
            value = next((str(p[2]) for p in libsym.nodes('property') if p[1] == 'Value'), lib_id.split(':')[-1])
        if ref is None:
            used = {s.ref for s in self.symbols()}
            while True:
                self._pwr += 1
                ref = '#PWR%03d' % self._pwr
                if ref not in used:
                    break
        s = self.add_symbol(lib_id, ref, value, at, angle, in_bom=False, on_board=False)
        s.set_field('Reference', hide=True)
        return s

    # ---------------------------------------------------------------- connectivity items
    def wire(self, *points: Point, width: float = 0) -> List[Node]:
        """A wire through the points (one ``wire`` item per segment, as KiCad stores them)."""
        out = []
        pts = [(_sch_round(a), _sch_round(b)) for a, b in points]
        for a, b in zip(pts, pts[1:]):
            if a == b:
                continue
            out.append(self.add(Node('wire', Node('pts', Node('xy', a[0], a[1]), Node('xy', b[0], b[1])),
                                     stroke(width), Node('uuid', self.uuids.new()))))
        return out

    def bus(self, *points: Point, width: float = 0) -> List[Node]:
        out = []
        pts = [(_sch_round(a), _sch_round(b)) for a, b in points]
        for a, b in zip(pts, pts[1:]):
            if a != b:
                out.append(self.add(Node('bus', Node('pts', Node('xy', a[0], a[1]), Node('xy', b[0], b[1])),
                                         stroke(width), Node('uuid', self.uuids.new()))))
        return out

    def junction(self, at: Point, diameter: float = 0) -> Node:
        return self.add(Node('junction', Node('at', _sch_round(at[0]), _sch_round(at[1])), Node('diameter', diameter),
                             Node('color', 0, 0, 0, 0), Node('uuid', self.uuids.new())))

    def no_connect(self, at: Point) -> Node:
        return self.add(Node('no_connect', Node('at', _sch_round(at[0]), _sch_round(at[1])),
                             Node('uuid', self.uuids.new())))

    @staticmethod
    def _label_justify(angle: float) -> str:
        return 'left' if norm_angle(angle) in (0.0, 90.0) else 'right'

    def label(self, text: str, at: Point, angle: float = 0, size: float = 1.27) -> Node:
        """Local net label; its anchor (``at``) is the connection point."""
        return self.add(Node('label', text, Node('at', _sch_round(at[0]), _sch_round(at[1]), norm_angle(angle)),
                             font_effects(size, justify=(self._label_justify(angle), 'bottom')),
                             Node('uuid', self.uuids.new())))

    def global_label(self, text: str, at: Point, angle: float = 0, shape: str = 'bidirectional',
                     size: float = 1.27) -> Node:
        """Global label (shape: input, output, bidirectional, tri_state, passive)."""
        x, y = _sch_round(at[0]), _sch_round(at[1])
        return self.add(Node('global_label', text, Node('shape', Sym(shape)), Node('at', x, y, norm_angle(angle)),
                             font_effects(size, justify=(self._label_justify(angle),)),
                             Node('uuid', self.uuids.new()),
                             Node('property', 'Intersheetrefs', '${INTERSHEET_REFS}', Node('at', x, y, 0),
                                  Node('hide', True), Node('show_name', False), Node('do_not_autoplace', False),
                                  font_effects(1.27))))

    def hierarchical_label(self, text: str, at: Point, angle: float = 0, shape: str = 'bidirectional',
                           size: float = 1.27) -> Node:
        return self.add(Node('hierarchical_label', text, Node('shape', Sym(shape)),
                             Node('at', _sch_round(at[0]), _sch_round(at[1]), norm_angle(angle)),
                             font_effects(size, justify=(self._label_justify(angle),)),
                             Node('uuid', self.uuids.new())))

    def text(self, text: str, at: Point, size: float = 1.27, angle: float = 0, bold: bool = False,
             italic: bool = False, justify: Sequence[str] = ('left', 'bottom')) -> Node:
        """Free text. Newlines are fine: they are escaped on output, never written raw."""
        return self.add(Node('text', text, Node('exclude_from_sim', False),
                             Node('at', _sch_round(at[0]), _sch_round(at[1]), norm_angle(angle)),
                             font_effects(size, bold=bold, italic=italic, justify=justify),
                             Node('uuid', self.uuids.new())))

    def polyline(self, points: Sequence[Point], width: float = 0, type_: str = 'default') -> Node:
        """Graphic line (no electrical meaning)."""
        return self.add(Node('polyline', Node('pts', *[Node('xy', _sch_round(a), _sch_round(b)) for a, b in points]),
                             stroke(width, type_), Node('uuid', self.uuids.new())))

    def sheet(self, name: str, file: str, at: Point, size: Tuple[float, float],
              pins: Sequence[Tuple[str, str, Point, float]] = (), page: str = '2') -> Node:
        """A hierarchical sheet block. pins: (name, shape, position, angle) -- angle 180 = left edge, 0 = right.
        Returns the node; its uuid is the second part of the sub-sheet's instance path."""
        x, y = _sch_round(at[0]), _sch_round(at[1])
        n = Node('sheet', Node('at', x, y), Node('size', size[0], size[1]), Node('exclude_from_sim', False),
                 Node('in_bom', True), Node('on_board', True), Node('dnp', False), stroke(0.254, 'solid'),
                 Node('fill', Node('color', 0, 0, 0, 0)), Node('uuid', self.uuids.new()),
                 Node('property', 'Sheetname', name, Node('at', x, _sch_round(y - 2.54), 0), Node('show_name', False),
                      Node('do_not_autoplace', False), font_effects(1.27)),
                 Node('property', 'Sheetfile', file, Node('at', x, _sch_round(y + size[1] + 2.54), 0),
                      Node('show_name', False), Node('do_not_autoplace', False), font_effects(1.27)))
        for pname, shape, (px, py), pangle in pins:
            n.append(Node('pin', pname, Sym(shape), Node('at', _sch_round(px), _sch_round(py), norm_angle(pangle)),
                          Node('uuid', self.uuids.new()),
                          font_effects(1.27, justify=('left' if norm_angle(pangle) == 180 else 'right',))))
        n.append(Node('instances', Node('project', self.project,
                                        Node('path', self.instance_path, Node('page', page)))))
        return self.add(n)
