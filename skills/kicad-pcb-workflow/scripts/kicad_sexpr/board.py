"""Boards (.kicad_pcb) and footprints (.kicad_mod): load / create, place library footprints, typed builders for
tracks, vias, zones, rule areas, graphics, text, outline and stackup; generic access to everything else.

Coordinates are millimetres, y pointing down. Angles are degrees, positive = counter-clockwise on screen.
Net names are written exactly as given: use ``common.board_net_name()`` for names taken from a netlist export.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .common import (FOOTPRINT_VERSION, PCB_VERSION, IdMap, Point, Uuids, duplicate_uuids, font_effects, header,
                     norm_angle, pt_key, r6, rotate, stroke, xy_list)
from .sexp import Node, Sym, load, loads, save

__all__ = ['Board', 'Footprint', 'new_footprint', 'load_footprint', 'flip_footprint_data', 'flip_layer', 'StackupLayer',
           'stackup', 'copper_layer_names', 'fp_line', 'fp_rect', 'board_ids', 'board_item_key', 'fp_item_key']

# Top-level order KiCad writes; new items go next to their kind.
_ORDER = ['version', 'generator', 'generator_version', 'general', 'paper', 'title_block', 'layers', 'setup',
          'property', 'net', 'footprint', 'gr_arc', 'gr_line', 'gr_rect', 'gr_circle', 'gr_poly', 'gr_curve',
          'gr_bbox', 'image', 'gr_text', 'gr_text_box', 'table', 'dimension', 'target', 'segment', 'arc', 'via',
          'zone', 'group', 'generated', 'embedded_fonts', 'embedded_files']


def copper_layer_names(n: int) -> List[str]:
    """['F.Cu', 'In1.Cu', ..., 'B.Cu'] for an n-layer board."""
    if n < 1:
        raise ValueError('need at least one copper layer')
    if n == 1:
        return ['F.Cu']
    return ['F.Cu'] + ['In%d.Cu' % i for i in range(1, n - 1)] + ['B.Cu']


def _layer_table(copper: int) -> Node:
    """The (layers ...) table as KiCad 10 writes it (ids: F.Cu 0, B.Cu 2, In<k>.Cu 2k+2; read from real boards)."""
    t = Node('layers')
    for name in copper_layer_names(copper):
        lid = 0 if name == 'F.Cu' else 2 if name == 'B.Cu' else 2 * int(name[2:-3]) + 2
        t.append(Node(str(lid), name, Sym('signal')))
    for lid, name, alias in ((9, 'F.Adhes', 'F.Adhesive'), (11, 'B.Adhes', 'B.Adhesive'), (13, 'F.Paste', None),
                             (15, 'B.Paste', None), (5, 'F.SilkS', 'F.Silkscreen'), (7, 'B.SilkS', 'B.Silkscreen'),
                             (1, 'F.Mask', None), (3, 'B.Mask', None), (17, 'Dwgs.User', 'User.Drawings'),
                             (19, 'Cmts.User', 'User.Comments'), (21, 'Eco1.User', 'User.Eco1'),
                             (23, 'Eco2.User', 'User.Eco2'), (25, 'Edge.Cuts', None), (27, 'Margin', None),
                             (31, 'F.CrtYd', 'F.Courtyard'), (29, 'B.CrtYd', 'B.Courtyard'), (35, 'F.Fab', None),
                             (33, 'B.Fab', None), (39, 'User.1', None), (41, 'User.2', None), (43, 'User.3', None),
                             (45, 'User.4', None)):
        n = Node(str(lid), name, Sym('user'))
        if alias:
            n.append(alias)
        t.append(n)
    return t


def _default_setup() -> Node:
    """The (setup ...) block pcbnew 10.0.1 writes for a new board (copied from a board it saved)."""
    return loads('''(setup (pad_to_mask_clearance 0) (allow_soldermask_bridges_in_footprints no)
 (tenting (front yes) (back yes)) (covering (front no) (back no)) (plugging (front no) (back no)) (capping no)
 (filling no)
 (pcbplotparams (layerselection 0x00000000_00000000_55555555_5755f5ff)
  (plot_on_all_layers_selection 0x00000000_00000000_00000000_00000000) (disableapertmacros no)
  (usegerberextensions no) (usegerberattributes yes) (usegerberadvancedattributes yes) (creategerberjobfile yes)
  (dashed_line_dash_ratio 12) (dashed_line_gap_ratio 3) (svgprecision 4) (plotframeref no) (mode 1)
  (useauxorigin no) (pdf_front_fp_property_popups yes) (pdf_back_fp_property_popups yes) (pdf_metadata yes)
  (pdf_single_document no) (dxfpolygonmode yes) (dxfimperialunits yes) (dxfusepcbnewfont yes) (psnegative no)
  (psa4output no) (plot_black_and_white yes) (sketchpadsonfab no) (plotpadnumbers no) (hidednponfab no)
  (sketchdnponfab yes) (crossoutdnponfab yes) (subtractmaskfromsilk no) (outputformat 1) (mirror no)
  (drillshape 1) (scaleselection 1) (outputdirectory "")))''')


# -------------------------------------------------------------------- stackup

class StackupLayer:
    """One row of the physical stackup. kind: 'copper', 'core', 'prepreg', or a KiCad type string such as
    'Top Solder Mask'. name: the board layer ('F.Cu', 'F.Mask', ...) or 'dielectric N'."""

    def __init__(self, name: str, kind: str, thickness: Optional[float] = None, material: Optional[str] = None,
                 epsilon_r: Optional[float] = None, loss_tangent: Optional[float] = None,
                 color: Optional[str] = None) -> None:
        self.name, self.kind, self.thickness = name, kind, thickness
        self.material, self.epsilon_r, self.loss_tangent, self.color = material, epsilon_r, loss_tangent, color

    def node(self) -> Node:
        n = Node('layer', self.name, Node('type', self.kind))
        if self.color is not None:
            n.append(Node('color', self.color))
        if self.thickness is not None:
            n.append(Node('thickness', self.thickness))
        if self.material is not None:
            n.append(Node('material', self.material))
        if self.epsilon_r is not None:
            n.append(Node('epsilon_r', self.epsilon_r))
        if self.loss_tangent is not None:
            n.append(Node('loss_tangent', self.loss_tangent))
        return n


def stackup(copper_thickness: Sequence[float],
            dielectrics: Sequence[Tuple[str, float, str, float, Optional[float]]],
            mask_thickness: float = 0.01, mask_material: str = 'LPI', mask_er: float = 3.8,
            finish: str = 'ENIG', dielectric_constraints: bool = False,
            mask_loss_tangent: Optional[float] = 0) -> Node:
    """``(stackup ...)`` for an n-layer board: silk, paste, mask, copper/dielectric pairs, mask, paste, silk.

    copper_thickness: per copper layer, top to bottom (mm). dielectrics: per gap, top to bottom,
    (kind 'core'|'prepreg', thickness mm, material, epsilon_r, loss_tangent). A loss tangent of None (dielectric
    or ``mask_loss_tangent``) leaves the entry out, for a manufacturer table that gives none; KiCad 10.0.1 then uses its
    defaults (0.02 for a dielectric, 0 for solder mask; checked by re-saving in the tests).
    The layout matches the stackup block pcbnew writes (checked against KiCad 10 boards)."""
    n = len(copper_thickness)
    if len(dielectrics) != n - 1:
        raise ValueError('%d copper layers need %d dielectrics' % (n, n - 1))
    names = copper_layer_names(n)
    rows = [StackupLayer('F.SilkS', 'Top Silk Screen'), StackupLayer('F.Paste', 'Top Solder Paste'),
            StackupLayer('F.Mask', 'Top Solder Mask', mask_thickness, mask_material, mask_er, mask_loss_tangent)]
    for i, name in enumerate(names):
        rows.append(StackupLayer(name, 'copper', copper_thickness[i]))
        if i < n - 1:
            kind, th, mat, er, tan = dielectrics[i]
            rows.append(StackupLayer('dielectric %d' % (i + 1), kind, th, mat, er, tan))
    rows += [StackupLayer('B.Mask', 'Bottom Solder Mask', mask_thickness, mask_material, mask_er, mask_loss_tangent),
             StackupLayer('B.Paste', 'Bottom Solder Paste'), StackupLayer('B.SilkS', 'Bottom Silk Screen')]
    s = Node('stackup', *[r.node() for r in rows])
    s.append(Node('copper_finish', finish))
    s.append(Node('dielectric_constraints', dielectric_constraints))
    return s


# -------------------------------------------------------------------- footprints

def load_footprint(path: str) -> Node:
    """A footprint from a .kicad_mod file (or a library dir + name: ``load_footprint(lib_dir + '/X.kicad_mod')``)."""
    return load(path)


def flip_layer(name: str) -> str:
    """Front <-> back for a layer name (F.Cu <-> B.Cu, F.SilkS <-> B.SilkS, ...); inner and user layers unchanged."""
    if name.startswith('F.'):
        return 'B.' + name[2:]
    if name.startswith('B.'):
        return 'F.' + name[2:]
    return name


_POINT_HEADS = ('start', 'end', 'mid', 'center', 'xy', 'at')
_TEXT_HEADS = ('property', 'fp_text', 'fp_text_box')


def flip_footprint_data(fp: Node) -> None:
    """Flip a footprint's local data to the back side in place, the way pcbnew's SetLayerAndFlip() writes it
    (mirror top-bottom: local y negated, layers swapped, text mirrored and turned 180 degrees, pad angles negated).
    Checked against pcbnew output for library footprints with arcs, polygons, custom pads and zones (tests).
    Angles here are local (footprint at 0 degrees)."""
    def walk(n: Node, in_text: bool, in_pad: bool, unlocked: bool = False) -> None:
        h = n.head
        if h in _TEXT_HEADS:
            u = n.find('unlocked')
            unlocked = u is not None and str(u[1]) == 'yes'
        if h == 'model':
            return
        if h in ('layer', 'layers'):
            for i in range(1, len(n)):
                if isinstance(n[i], str):
                    n[i] = flip_layer(str(n[i])) if not isinstance(n[i], Sym) else Sym(flip_layer(str(n[i])))
            return
        if h in _POINT_HEADS and len(n) >= 3:
            n[2] = r6(-n.number(2))
            if h == 'at' and len(n) >= 4:
                a = n.number(3)
                if in_text:
                    # pcbnew 10.0.1, measured on library footprints: 0<->180 and 90/270 kept for unlocked texts;
                    # locked texts (the default) additionally end up in [180, 360)
                    b = norm_angle(180 - a)
                    if not unlocked and b < 180:
                        b = norm_angle(b + 180)
                    n[3] = b
                elif in_pad:
                    n[3] = norm_angle(-a)
        if h == 'offset' and in_pad and len(n) >= 3:       # drill offset
            n[2] = r6(-n.number(2))
        if h == 'chamfer':
            swap = {'top_left': 'bottom_left', 'bottom_left': 'top_left', 'top_right': 'bottom_right',
                    'bottom_right': 'top_right'}
            for i in range(1, len(n)):
                n[i] = Sym(swap.get(str(n[i]), str(n[i])))
        if h in _TEXT_HEADS:
            # pcbnew mirrors a text exactly when it ends up on a back layer (texts on user layers stay unmirrored)
            lay = n.find('layer')
            back = lay is not None and flip_layer(str(lay[1])).startswith('B.')
            eff = n.find('effects')
            if eff is not None:
                j = eff.find('justify')
                has = j is not None and 'mirror' in [str(v) for v in j[1:]]
                if back and not has:
                    if j is None:
                        eff.append(Node('justify', Sym('mirror')))
                    else:
                        j.append(Sym('mirror'))
                elif not back and has and j is not None:
                    j.remove(next(v for v in j[1:] if str(v) == 'mirror'))
                    if len(j) == 1:
                        eff.remove_node(j)
        for c in n[1:]:
            if isinstance(c, Node):
                walk(c, in_text or h in _TEXT_HEADS, in_pad or h == 'pad', unlocked)
    for c in fp[1:]:
        if isinstance(c, Node):
            walk(c, False, False)
    # a mirrored arc keeps its direction: KiCad swaps start and end
    for arc in list(fp.walk('fp_arc')) + list(fp.walk('gr_arc')):
        s, e = arc.find('start'), arc.find('end')
        if s is not None and e is not None:
            s[1:], e[1:] = e[1:], s[1:]


# -------------------------------------------------------------------- stable item keys (for uuids)

_GRAPHICS = ('line', 'rect', 'circle', 'arc', 'poly', 'curve', 'bbox')


def _layers_text(n: Node) -> str:
    c = n.find('layer') or n.find('layers')
    return ','.join(str(v) for v in c[1:]) if c is not None else ''


def _points(n: Node, heads: Sequence[str] = ('start', 'mid', 'end', 'center', 'xy')) -> List[Point]:
    return [(g.number(1), g.number(2)) for g in n.walk() if g.head in heads and g is not n and len(g) > 2]


def _zone_key(n: Node, prefix: str = '') -> str:
    """A named zone is keyed by kind, net, layers and name (its outline can change without a new id); an unnamed
    one also by its outline."""
    name = n.get('name')
    poly = n.find('polygon')
    where = ('name:%s' % name) if name else pt_key(*(_points(poly, ('xy',)) if poly is not None else []))
    if n.find('keepout') is not None:
        return '%srule_area/%s/%s' % (prefix, _layers_text(n), where)
    return '%szone/%s/%s/%s' % (prefix, n.get('net', ''), _layers_text(n), where)


def fp_item_key(c: Node) -> str:
    """Stable name of an item inside a footprint (local coordinates): ``property:Value``, ``pad:3@-0.48,0``,
    ``fp_text:user:${REFERENCE}@F.Fab``, ``fp_line/F.SilkS/<points>``."""
    h = c.head
    if h == 'property':
        return 'property:%s' % c[1]
    if h == 'pad':
        at = c.find('at')
        return 'pad:%s@%s' % (c[1], pt_key((at.number(1), at.number(2))) if at is not None else '')
    if h == 'fp_text':
        return 'fp_text:%s:%s@%s' % (c[1], c[2] if len(c) > 2 else '', _layers_text(c))
    if h == 'zone':
        return _zone_key(c)
    if h.startswith('fp_'):
        return '%s/%s/%s' % (h, _layers_text(c), pt_key(*_points(c)))
    return h


def board_item_key(n: Node) -> Optional[str]:
    """Stable name of a top-level board item: ``footprint/R1``, ``segment/GND/F.Cu/<ends>``, ``via/GND/<at>``,
    ``zone/GND/In1.Cu/name:GND_PLANE``, ``rule_area/F.Cu/name:X``, ``gr_line/Edge.Cuts/<ends>``,
    ``gr_text/F.SilkS/TEXT/<at>``; None for kinds no builder makes."""
    h = n.head
    if h == 'footprint':
        ref = next((str(p[2]) for p in n.nodes('property') if p[1] == 'Reference'), '')
        return 'footprint/%s' % ref
    if h in ('segment', 'arc'):
        return '%s/%s/%s/%s' % (h, n.get('net', ''), _layers_text(n), pt_key(*_points(n)))
    if h == 'via':
        at = n.need('at')
        return 'via/%s/%s' % (n.get('net', ''), pt_key((at.number(1), at.number(2))))
    if h == 'zone':
        return _zone_key(n)
    if h == 'gr_text':
        at = n.need('at')
        return 'gr_text/%s/%s/%s' % (_layers_text(n), n[1], pt_key((at.number(1), at.number(2))))
    if h.startswith('gr_') and h[3:] in _GRAPHICS:
        return '%s/%s/%s' % (h, _layers_text(n), pt_key(*_points(n)))
    return None


def board_ids(tree: Node) -> IdMap:
    """{stable key: uuid} for every item of a board that a builder could make again (footprints and the items
    inside them, tracks, vias, zones, rule areas, graphics, texts). Give it to ``Board.reuse_ids``."""
    m = IdMap()
    for n in tree.nodes():
        k = board_item_key(n)
        if k is None:
            continue
        u = n.find('uuid')
        if u is not None and len(u) > 1:
            m.put(k, str(u[1]))
        if n.head == 'footprint':
            for c in n.nodes():
                cu = c.find('uuid')
                if cu is not None and len(cu) > 1:
                    m.put(k + '/' + fp_item_key(c), str(cu[1]))
    return m


class Footprint:
    """A footprint placed on a board (wraps its node)."""

    def __init__(self, board: 'Board', node: Node) -> None:
        self.board = board
        self.node = node

    @property
    def lib_id(self) -> str:
        return str(self.node[1])

    @property
    def ref(self) -> str:
        return self.field_value('Reference')

    @property
    def value(self) -> str:
        return self.field_value('Value')

    @property
    def at(self) -> Point:
        a = self.node.need('at')
        return a.number(1), a.number(2)

    @property
    def angle(self) -> float:
        return self.node.need('at').number(3, 0.0)

    @property
    def side(self) -> str:
        return 'B' if str(self.node.get('layer')) == 'B.Cu' else 'F'

    def field(self, name: str) -> Optional[Node]:
        for p in self.node.nodes('property'):
            if p[1] == name:
                return p
        return None

    def field_value(self, name: str) -> str:
        f = self.field(name)
        return str(f[2]) if f is not None else ''

    def set_field(self, name: str, value: str, hide: Optional[bool] = None, layer: Optional[str] = None,
                  at: Optional[Point] = None, size: float = 1.0, thickness: float = 0.15,
                  position: Optional[int] = None) -> Node:
        """Set (or add, hidden on F.Fab/B.Fab by default) a footprint property. ``at`` is local (unrotated).
        A new property goes after the last property, or at index ``position`` of the footprint node."""
        f = self.field(name)
        if f is None:
            fab = 'B.Fab' if self.side == 'B' else 'F.Fab'
            x, y = at if at is not None else (0.0, 0.0)
            f = Node('property', name, value, Node('at', x, y, norm_angle(self.angle)), Node('layer', layer or fab))
            if hide is None or hide:
                f.append(Node('hide', True))
            f.append(Node('uuid', self.board.uuids.new('footprint/%s/property:%s' % (self.ref, name))))
            eff = font_effects(size, thickness)
            if self.side == 'B':
                eff.append(Node('justify', Sym('mirror')))
            f.append(eff)
            props = self.node.nodes('property')
            if position is None:
                position = self.node.index(props[-1]) + 1 if props else 3
            self.node.insert(position, f)
            return f
        f[2] = value
        if hide is not None:
            f.remove_all('hide')
            if hide:
                anchor = f.find('layer') or f.need('at')
                f.insert(f.index(anchor) + 1, Node('hide', True))
        if layer is not None:
            f.set('layer', layer)
        if at is not None:
            a = f.need('at')
            a[1], a[2] = at[0], at[1]
        return f

    def pads(self, number: Optional[str] = None) -> List[Node]:
        return [p for p in self.node.nodes('pad') if number is None or str(p[1]) == str(number)]

    def pad_position(self, number: Union[str, int], index: int = 0) -> Point:
        """Board position of a pad centre (footprint rotation applied; back-side data is already flipped)."""
        p = self.pads(str(number))
        if not p:
            raise KeyError('%s has no pad %s' % (self.ref, number))
        a = p[index].need('at')
        dx, dy = rotate(a.number(1), a.number(2), self.angle)
        return r6(self.at[0] + dx), r6(self.at[1] + dy)

    def pad_net(self, number: Union[str, int]) -> str:
        p = self.pads(str(number))
        return str(p[0].get('net', '')) if p else ''

    def set_pad_net(self, number: Union[str, int], net: Optional[str], pinfunction: Optional[str] = None,
                    pintype: Optional[str] = None) -> int:
        """Set the net of every pad with this number (None removes it). Returns how many pads changed."""
        pads = self.pads(str(number))
        for p in pads:
            p.remove_all('net')
            p.remove_all('pinfunction')
            p.remove_all('pintype')
            extra = []
            if net is not None:
                extra.append(Node('net', net))
                if pinfunction is not None:
                    extra.append(Node('pinfunction', pinfunction))
                if pintype is not None:
                    extra.append(Node('pintype', pintype))
            u = p.find('uuid')
            pos = p.index(u) if u is not None else len(p)
            for k, e in enumerate(extra):
                p.insert(pos + k, e)
        return len(pads)


class Board:
    """One .kicad_pcb file."""

    def __init__(self, tree: Node, path: Optional[str] = None) -> None:
        if tree[0] != 'kicad_pcb':
            raise ValueError('not a board: %s' % tree[0])
        self.tree = tree
        self.path = path
        self.uuids = Uuids(seed='kicad_pcb')       # stable ids: see reuse_ids() and common.Uuids
        self.uuids.scan(tree)

    def reuse_ids(self, previous: Union[str, Node, 'Board']) -> IdMap:
        """Take the ids of a previous version of this board (path, tree or Board): every item a builder makes from
        now on whose stable key (board_item_key / fp_item_key) matches an item there gets that item's uuid, so a
        regenerated board keeps its parts' ids (committed files, GUI edits). Items with no match get ids derived
        from their key. Returns the map; ``.ambiguous`` lists keys that occurred more than once there."""
        tree = previous.tree if isinstance(previous, Board) else load(previous) if isinstance(previous, str) else previous
        m = board_ids(tree)
        self.uuids.reuse = m
        return m

    def _fill_uuid(self, n: Node, key: Optional[str] = None) -> Node:
        """Give the node's placeholder ``(uuid "")`` its stable id."""
        u = n.need('uuid')
        u[1] = self.uuids.new(key or board_item_key(n))
        return n

    # ---------------------------------------------------------------- create / load / save
    @classmethod
    def new(cls, copper_layers: int = 2, thickness: float = 1.6, paper: str = 'A4',
            previous: Optional[Union[str, Node, 'Board']] = None) -> 'Board':
        """An empty board with KiCad 10's layer table and default setup (no stackup block; see set_stackup).
        ``previous``: an earlier version of this board whose item ids are reused (see reuse_ids)."""
        t = header('kicad_pcb', PCB_VERSION, 'pcbnew')
        t.append(Node('general', Node('thickness', thickness), Node('legacy_teardrops', False)))
        t.append(Node('paper', paper))
        t.append(_layer_table(copper_layers))
        t.append(_default_setup())
        t.append(Node('embedded_fonts', False))
        b = cls(t)
        if previous is not None:
            b.reuse_ids(previous)
        return b

    @classmethod
    def load(cls, path: str) -> 'Board':
        return cls(load(path), path)

    def save(self, path: Optional[str] = None) -> None:
        problems = self.validate()
        if problems:
            raise ValueError('refusing to write an invalid board:\n  ' + '\n  '.join(problems))
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
        refs: Dict[str, int] = {}
        for f in self.footprints():
            r = f.ref
            if r and not r.startswith('REF**'):
                refs[r] = refs.get(r, 0) + 1
        dup = sorted(r for r, n in refs.items() if n > 1)
        if dup:
            out.append('duplicate footprint references: %s' % dup[:10])
        layers = set(self.layer_names())
        for n in self.tree.nodes():
            if n.head in ('segment', 'arc', 'via', 'zone') or n.head.startswith('gr_'):
                for ln in n.walk('layer'):
                    if len(ln) > 1 and str(ln[1]) not in layers and '*' not in str(ln[1]):
                        out.append('%s on unknown layer %s' % (n.head, ln[1]))
                        break
        return out

    # ---------------------------------------------------------------- generic
    def add(self, node: Node) -> Node:
        """Insert any top-level item next to the items of its kind. A placeholder ``(uuid "")`` gets the item's
        stable id."""
        u = node.find('uuid')
        if u is not None and len(u) > 1 and u[1] == '':
            self._fill_uuid(node)
        head = node.head
        kids = [(i, c) for i, c in enumerate(self.tree) if i > 0 and isinstance(c, Node)]
        same = [i for i, c in kids if c.head == head]
        if same:
            self.tree.insert(same[-1] + 1, node)
            return node
        rank = _ORDER.index(head) if head in _ORDER else _ORDER.index('zone')
        for i, c in kids:
            if c.head in _ORDER and _ORDER.index(c.head) > rank:
                self.tree.insert(i, node)
                return node
        self.tree.append(node)
        return node

    def items(self, head: str) -> List[Node]:
        return self.tree.nodes(head)

    def layer_names(self) -> List[str]:
        lt = self.tree.find('layers')
        return [str(n[1]) for n in lt.nodes()] if lt is not None else []

    def copper_layers(self) -> List[str]:
        lt = self.tree.find('layers')
        return [str(n[1]) for n in lt.nodes() if str(n[1]).endswith('.Cu')] if lt is not None else []

    def nets(self) -> List[str]:
        """Every net name used by pads, tracks, vias and zones."""
        s = set()
        for n in self.tree.walk('net'):
            if len(n) > 1:
                s.add(str(n[-1]))
        s.discard('')
        return sorted(s)

    # ---------------------------------------------------------------- setup
    def set_stackup(self, stack: Node) -> None:
        """Replace (or add) the (stackup ...) block inside (setup ...)."""
        setup = self.tree.find('setup')
        if setup is None:
            setup = self.add(_default_setup())
        setup.remove_all('stackup')
        setup.insert(1, stack)

    def set_thickness(self, mm: float) -> None:
        self.tree.need('general').set('thickness', mm)

    # ---------------------------------------------------------------- footprints
    def footprints(self) -> List[Footprint]:
        return [Footprint(self, n) for n in self.tree.nodes('footprint')]

    def footprint(self, ref: str) -> Footprint:
        for f in self.footprints():
            if f.ref == ref:
                return f
        raise KeyError('no footprint %s' % ref)

    def add_footprint(self, source: Union[Node, str], lib_id: str, ref: str, value: str, at: Point,
                      angle: float = 0, side: str = 'F', fields: Optional[Dict[str, str]] = None,
                      pad_nets: Optional[Dict[str, str]] = None, path: Optional[str] = None,
                      sheetname: Optional[str] = None, sheetfile: Optional[str] = None,
                      hide_reference: Optional[bool] = None, uuid: Optional[str] = None) -> Footprint:
        """Place a library footprint (a .kicad_mod path or its parsed node).

        lib_id "Lib:Name" is written as the footprint id. ``path`` links it to its schematic symbol
        ("/<symbol uuid>", or "/<sheet uuid>/<symbol uuid>" on a sub-sheet). ``fields`` become hidden properties
        (existing library properties of the same name get the value). ``pad_nets`` maps pad number -> net name.
        side 'B' flips the footprint to the back the way pcbnew does. Every item gets a stable uuid: the one it had in
        the previous board (reuse_ids), else one derived from the reference and the item (``uuid`` sets the
        footprint's own id explicitly)."""
        fp = load(source) if isinstance(source, str) else source.deepcopy()
        if fp[0] != 'footprint':
            raise ValueError('not a footprint: %s' % fp[0])
        fp[1] = lib_id
        for h in ('version', 'generator', 'generator_version', 'uuid', 'at', 'path', 'sheetname', 'sheetfile',
                  'locked', 'placed', 'tedit'):
            fp.remove_all(h)
        key = 'footprint/%s' % ref
        for u in fp.walk('uuid'):                     # library ids are placeholders until the footprint is final
            del u[1:]
            u.append('')
        if side == 'B':
            flip_footprint_data(fp)
        elif side != 'F':
            raise ValueError("side must be 'F' or 'B'")
        lay = fp.find('layer')
        if lay is None:
            lay = Node('layer', 'F.Cu')
            fp.insert(2, lay)
        li = fp.index(lay)
        fa = norm_angle(angle, signed=True)
        at_node = Node('at', r6(at[0]), r6(at[1]))
        if fa != 0:
            at_node.append(fa)
        fp.insert(li + 1, Node('uuid', self.uuids.take(uuid) if uuid else self.uuids.new(key)))
        fp.insert(li + 2, at_node)
        # every item with its own uuid needs one (KiCad 10 boards give each property/graphic/pad a uuid)
        for c in fp.nodes():
            if c.head in ('property', 'fp_text', 'fp_text_box', 'pad', 'fp_line', 'fp_rect', 'fp_circle', 'fp_arc',
                          'fp_poly', 'fp_curve', 'zone', 'group', 'dimension') and c.find('uuid') is None:
                if c.head == 'property' or c.head == 'fp_text':
                    eff = c.find('effects')
                    pos = c.index(eff) if eff is not None else len(c)
                    c.insert(pos, Node('uuid', ''))
                else:
                    c.append(Node('uuid', ''))
        # text and pad angles are stored absolute (footprint angle + local angle)
        for c in fp.nodes():
            if c.head in ('property', 'fp_text', 'fp_text_box'):
                a = c.find('at')
                if a is not None:
                    local = a.number(3, 0.0)
                    del a[3:]
                    a.append(norm_angle(fa + local))
            elif c.head == 'pad':
                a = c.need('at')
                local = a.number(3, 0.0)
                del a[3:]
                tot = norm_angle(fa + local)
                if tot != 0:
                    a.append(tot)
        # pcbnew gives every placed footprint Datasheet and Description fields (empty if the library has none)
        props = fp.nodes('property')
        names = [str(p[1]) for p in props]
        after = next((p for p in props if p[1] == 'Value'), props[-1] if props else None)
        pos = fp.index(after) + 1 if after is not None else fp.index(lay) + 3
        for k in ('Datasheet', 'Description'):
            if k not in names:
                fab = 'B.Fab' if side == 'B' else 'F.Fab'
                eff = font_effects(1.27)
                if side == 'B':
                    eff.append(Node('justify', Sym('mirror')))
                fp.insert(pos, Node('property', k, '', Node('at', 0, 0, norm_angle(fa + (180 if side == 'B' else 0))),
                                    Node('layer', fab), Node('hide', True),
                                    Node('uuid', ''), eff))
                pos += 1
        if fa % 90 != 0:
            # pcbnew cannot keep a rectangle at a non-right angle: it stores it as a 4-point polygon
            for c in fp.nodes('fp_rect'):
                s, e = c.need('start'), c.need('end')
                xs = sorted([s.number(1), e.number(1)])
                ys = sorted([s.number(2), e.number(2)])
                if xs[0] == xs[1] or ys[0] == ys[1]:      # pcbnew drops a zero-area rectangle here
                    fp.remove_node(c)
                    continue
                # corners start from (min x, min y) on the front and from (max x, max y) on the back
                (sx, ex), (sy, ey) = (xs, ys) if side == 'F' else (xs[::-1], ys[::-1])
                c[0] = Sym('fp_poly')
                c[c.index(s)] = xy_list([(sx, sy), (ex, sy), (ex, ey), (sx, ey)])
                c.remove_node(e)
        # zones inside a footprint are stored in board coordinates (everything else is footprint-local)
        for z in fp.nodes('zone'):
            for xy in z.walk('xy'):
                dx, dy = rotate(xy.number(1), xy.number(2), fa)
                xy[1], xy[2] = r6(at[0] + dx), r6(at[1] + dy)
        # rule areas inside footprints: keep only this board's copper layers, in pcbnew's order
        cu = self.copper_layers()
        if cu:
            canon = [x for x in ('F.Cu', 'B.Cu') if x in cu] + [x for x in cu if x not in ('F.Cu', 'B.Cu')]
            for z in fp.nodes('zone'):
                ln = z.find('layers')
                if ln is None:
                    continue
                names = [str(v) for v in ln[1:]]
                if '*.Cu' in names or 'F&B.Cu' in names:
                    continue
                keep = [x for x in canon if x in names] + [x for x in names if not x.endswith('.Cu')]
                del ln[1:]
                ln.extend(keep)
        f = Footprint(self, fp)
        f.set_field('Reference', ref)
        f.set_field('Value', value)
        if hide_reference is not None:
            f.set_field('Reference', ref, hide=hide_reference)
        # new fields go right after the mandatory ones, before the library's own extra fields (as pcbnew orders them)
        props = fp.nodes('property')
        mandatory = [p for p in props if p[1] in ('Reference', 'Value', 'Footprint', 'Datasheet', 'Description')]
        pos = fp.index(mandatory[-1]) + 1 if mandatory else None
        for k, v in (fields or {}).items():
            if f.field(k) is None and pos is not None:
                f.set_field(k, v, position=pos)
                pos += 1
            else:
                f.set_field(k, v)
        anchor = fp.find('attr') or fp.find('duplicate_pad_numbers_are_jumpers')
        extra = []
        if path is not None:
            extra.append(Node('path', path))
        if sheetname is not None:
            extra.append(Node('sheetname', sheetname))
        if sheetfile is not None:
            extra.append(Node('sheetfile', sheetfile))
        if extra:
            if anchor is not None:
                pos = fp.index(anchor)
            else:
                props = fp.nodes('property')
                pos = fp.index(props[-1]) + 1 if props else len(fp)
            for j, item in enumerate(extra):
                fp.insert(pos + j, item)
        for num, net in (pad_nets or {}).items():
            f.set_pad_net(num, net)
        for c in fp.nodes():                          # the footprint is final: stable ids for its items
            u = c.find('uuid')
            if u is not None and len(u) > 1 and u[1] == '':
                u[1] = self.uuids.new(key + '/' + fp_item_key(c))
        for i, u in enumerate(fp.walk('uuid')):       # anything deeper (rare): keyed by position
            if len(u) > 1 and u[1] == '':
                u[1] = self.uuids.new('%s/deep[%d]' % (key, i))
        self.add(fp)
        return f

    # ---------------------------------------------------------------- copper
    def segment(self, start: Point, end: Point, width: float, layer: str, net: str, key: Optional[str] = None) -> Node:
        return self.add(self._fill_uuid(Node('segment', Node('start', r6(start[0]), r6(start[1])),
                                             Node('end', r6(end[0]), r6(end[1])), Node('width', width),
                                             Node('layer', layer), Node('net', net), Node('uuid', '')), key))

    def track(self, points: Sequence[Point], width: float, layer: str, net: str) -> List[Node]:
        """Consecutive segments through the points (zero-length steps skipped)."""
        out = []
        for a, b in zip(points, points[1:]):
            if (r6(a[0]), r6(a[1])) != (r6(b[0]), r6(b[1])):
                out.append(self.segment(a, b, width, layer, net))
        return out

    def arc(self, start: Point, mid: Point, end: Point, width: float, layer: str, net: str,
            key: Optional[str] = None) -> Node:
        return self.add(self._fill_uuid(Node('arc', Node('start', r6(start[0]), r6(start[1])),
                                             Node('mid', r6(mid[0]), r6(mid[1])), Node('end', r6(end[0]), r6(end[1])),
                                             Node('width', width), Node('layer', layer), Node('net', net),
                                             Node('uuid', '')), key))

    def via(self, at: Point, size: float, drill: float, net: str, layers: Tuple[str, str] = ('F.Cu', 'B.Cu'),
            free: bool = False, via_type: Optional[str] = None, key: Optional[str] = None) -> Node:
        """A via. ``free=True`` writes ``(free yes)``: KiCad then keeps the given net instead of re-deriving it from
        what the via touches (use it for stitching / thermal vias). via_type: None (through), 'blind', 'micro'."""
        n = Node('via')
        if via_type:
            n.append(Sym(via_type))
        n.extend([Node('at', r6(at[0]), r6(at[1])), Node('size', size), Node('drill', drill),
                  Node('layers', layers[0], layers[1])])
        if free:
            n.append(Node('free', True))
        n.extend([Node('net', net), Node('uuid', '')])
        return self.add(self._fill_uuid(n, key))

    def zone(self, net: str, layers: Union[str, Sequence[str]], polygon: Sequence[Point], priority: int = 0,
             name: str = '', clearance: float = 0.2, min_thickness: float = 0.2, connect_pads: Optional[str] = 'yes',
             thermal_gap: float = 0.3, thermal_bridge_width: float = 0.4, island_removal_mode: int = 0,
             hatch: Tuple[str, float] = ('edge', 0.5), filled: bool = False, key: Optional[str] = None) -> Node:
        """A copper zone. connect_pads: 'yes' (solid), None (thermal reliefs), 'no', 'thru_hole_only'.
        Leave filled=False and let ``kicad-cli pcb drc --refill-zones --save-board`` fill it."""
        n = Node('zone', Node('net', net))
        n.extend(self._zone_layers(layers))
        n.append(Node('uuid', ''))
        if name:
            n.append(Node('name', name))
        n.append(Node('hatch', Sym(hatch[0]), hatch[1]))
        if priority:
            n.append(Node('priority', priority))
        cp = Node('connect_pads')
        if connect_pads is not None:
            cp.append(Sym(connect_pads))
        cp.append(Node('clearance', clearance))
        n.append(cp)
        n.append(Node('min_thickness', min_thickness))
        fill = Node('fill')
        if filled:
            fill.append(Sym('yes'))
        fill.extend([Node('thermal_gap', thermal_gap), Node('thermal_bridge_width', thermal_bridge_width),
                     Node('island_removal_mode', island_removal_mode)])
        n.append(fill)
        n.append(Node('polygon', xy_list(polygon)))
        return self.add(self._fill_uuid(n, key))

    def rule_area(self, layers: Union[str, Sequence[str]], polygon: Sequence[Point], name: str = '',
                  tracks: bool = True, vias: bool = True, pads: bool = True, copperpour: bool = False,
                  footprints: bool = True, key: Optional[str] = None) -> Node:
        """A keepout rule area. Each flag says whether that item type is *allowed* inside (default: only copper
        pours are kept out). Written in the form pcbnew 10 saves."""
        def a(ok: bool) -> Sym:
            return Sym('allowed' if ok else 'not_allowed')
        n = Node('zone')
        n.extend(self._zone_layers(layers))
        n.append(Node('uuid', ''))
        if name:
            n.append(Node('name', name))
        n.extend([Node('hatch', Sym('edge'), 0.5), Node('connect_pads', Node('clearance', 0)),
                  Node('min_thickness', 0.25),
                  Node('keepout', Node('tracks', a(tracks)), Node('vias', a(vias)), Node('pads', a(pads)),
                       Node('copperpour', a(copperpour)), Node('footprints', a(footprints))),
                  Node('placement', Node('enabled', False), Node('sheetname', '')),
                  Node('fill', Node('thermal_gap', 0.5), Node('thermal_bridge_width', 0.5),
                       Node('island_removal_mode', 0)),
                  Node('polygon', xy_list(polygon))])
        return self.add(self._fill_uuid(n, key))

    @staticmethod
    def _zone_layers(layers: Union[str, Sequence[str]]) -> List[Node]:
        if isinstance(layers, str):
            layers = [layers]
        if len(layers) == 1:
            return [Node('layer', layers[0])]
        return [Node('layers', *layers)]

    # ---------------------------------------------------------------- graphics
    def _gr(self, head: str, geo: List[Node], layer: str, width: float, fill: Optional[bool],
            net: Optional[str] = None, type_: str = 'default') -> Node:
        n = Node(head, *geo, stroke(width, type_))
        if fill is not None:
            n.append(Node('fill', fill))
        n.append(Node('layer', layer))
        if net is not None:
            n.append(Node('net', net))
        n.append(Node('uuid', ''))
        return self.add(self._fill_uuid(n))

    def gr_line(self, start: Point, end: Point, layer: str, width: float = 0.1) -> Node:
        return self._gr('gr_line', [Node('start', r6(start[0]), r6(start[1])), Node('end', r6(end[0]), r6(end[1]))],
                        layer, width, None)

    def gr_arc(self, start: Point, mid: Point, end: Point, layer: str, width: float = 0.1) -> Node:
        return self._gr('gr_arc', [Node('start', r6(start[0]), r6(start[1])), Node('mid', r6(mid[0]), r6(mid[1])),
                                   Node('end', r6(end[0]), r6(end[1]))], layer, width, None)

    def gr_circle(self, center: Point, radius: float, layer: str, width: float = 0.1, fill: bool = False) -> Node:
        return self._gr('gr_circle', [Node('center', r6(center[0]), r6(center[1])),
                                      Node('end', r6(center[0] + radius), r6(center[1]))], layer, width, fill)

    def gr_rect(self, start: Point, end: Point, layer: str, width: float = 0.1, fill: bool = False) -> Node:
        return self._gr('gr_rect', [Node('start', r6(start[0]), r6(start[1])), Node('end', r6(end[0]), r6(end[1]))],
                        layer, width, fill)

    def gr_poly(self, points: Sequence[Point], layer: str, width: float = 0.1, fill: bool = True,
                net: Optional[str] = None) -> Node:
        return self._gr('gr_poly', [xy_list(points)], layer, width, fill, net)

    def gr_text(self, text: str, at: Point, layer: str, size: float = 1.0, thickness: float = 0.15,
                angle: float = 0, mirror: Optional[bool] = None, justify: Sequence[str] = (),
                bold: bool = False) -> Node:
        """Board text. Text on a B.* layer is mirrored unless mirror=False. Newlines are escaped on output."""
        if mirror is None:
            mirror = layer.startswith('B.')
        j = list(justify) + (['mirror'] if mirror else [])
        return self.add(self._fill_uuid(Node('gr_text', text, Node('at', r6(at[0]), r6(at[1]), norm_angle(angle)),
                                             Node('layer', layer), Node('uuid', ''),
                                             font_effects(size, thickness, bold=bold, justify=j))))

    def outline_rect(self, x: float, y: float, w: float, h: float, corner_radius: float = 0,
                     width: float = 0.1, layer: str = 'Edge.Cuts') -> List[Node]:
        """Board outline: a rectangle from (x, y) of size w x h, optionally with rounded corners."""
        r = corner_radius
        out = []
        if r <= 0:
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
            for a, b in zip(pts, pts[1:]):
                out.append(self.gr_line(a, b, layer, width))
            return out
        k = r * (1 - math.sqrt(0.5))
        out.append(self.gr_line((x + r, y), (x + w - r, y), layer, width))
        out.append(self.gr_arc((x + w - r, y), (x + w - k, y + k), (x + w, y + r), layer, width))
        out.append(self.gr_line((x + w, y + r), (x + w, y + h - r), layer, width))
        out.append(self.gr_arc((x + w, y + h - r), (x + w - k, y + h - k), (x + w - r, y + h), layer, width))
        out.append(self.gr_line((x + w - r, y + h), (x + r, y + h), layer, width))
        out.append(self.gr_arc((x + r, y + h), (x + k, y + h - k), (x, y + h - r), layer, width))
        out.append(self.gr_line((x, y + h - r), (x, y + r), layer, width))
        out.append(self.gr_arc((x, y + r), (x + k, y + k), (x + r, y), layer, width))
        return out


def new_footprint(name: str, layer: str = 'F.Cu', descr: str = '', tags: str = '', attr: Sequence[str] = ('smd',),
                  items: Iterable[Node] = ()) -> Node:
    """A library footprint (.kicad_mod) skeleton with Reference/Value properties; append pads and graphics."""
    fp = Node('footprint', name, Node('version', FOOTPRINT_VERSION), Node('generator', 'pcbnew'),
              Node('generator_version', '10.0'), Node('layer', layer))
    if descr:
        fp.append(Node('descr', descr))
    if tags:
        fp.append(Node('tags', tags))
    for pname, val, y, lay in (('Reference', 'REF**', -2, 'F.SilkS'), ('Value', name, 2, 'F.Fab')):
        fp.append(Node('property', pname, val, Node('at', 0, y, 0), Node('layer', lay), font_effects(1, 0.15)))
    fp.append(Node('attr', *[Sym(a) for a in attr]))
    fp.extend(items)
    fp.append(Node('embedded_fonts', False))
    return fp



def _fp_graphic(head: str, geo: List[Node], layer: str, width: float, type_: str, fill: Optional[bool],
                uuids: Optional[Uuids]) -> Node:
    n = Node(head, *geo, stroke(width, type_))
    if fill is not None:
        n.append(Node('fill', fill))
    n.append(Node('layer', layer))
    if uuids is not None:
        n.append(Node('uuid', uuids.new(fp_item_key(n))))
    return n


def fp_line(start: Point, end: Point, layer: str, width: float = 0.12, type_: str = 'solid',
            uuids: Optional[Uuids] = None) -> Node:
    """A footprint line (footprint-local coordinates), for a library footprint node. ``uuids``: give one (scanned
    from the footprint: ``u = Uuids(seed='kicad_mod:' + name); u.scan(fp)``) to write a derived uuid; KiCad's own
    library files have none."""
    return _fp_graphic('fp_line', [Node('start', r6(start[0]), r6(start[1])), Node('end', r6(end[0]), r6(end[1]))],
                       layer, width, type_, None, uuids)


def fp_rect(start: Point, end: Point, layer: str, width: float = 0.05, fill: bool = False, type_: str = 'solid',
            uuids: Optional[Uuids] = None) -> Node:
    """A footprint rectangle in the layout KiCad 10 library footprints use (courtyards: F.CrtYd, width 0.05).
    Insert it into a library footprint node (e.g. ``fp.insert_before('pad', fp_rect(...))``)."""
    return _fp_graphic('fp_rect', [Node('start', r6(start[0]), r6(start[1])), Node('end', r6(end[0]), r6(end[1]))],
                       layer, width, type_, fill, uuids)
