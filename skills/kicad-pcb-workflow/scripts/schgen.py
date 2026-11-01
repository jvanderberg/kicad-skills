#!/usr/bin/env python3
"""Generate a KiCad 10 schematic as wire-drawn blocks, from python (no GUI). Library; plain python 3, no dependencies.

  from schgen import Sch, kicad_symbol_dir
  s = Sch('myproject', paper='A3', title='My board', rev='1')
  s.lib('Device', kicad_symbol_dir() + '/Device.kicad_sym'); s.lib('power', kicad_symbol_dir() + '/power.kicad_sym')
  s.lib('Proj', 'proj.kicad_sym')                       # your own / redrawn symbols (symgen.py)
  u1 = s.add('Proj:LDO', 'U1', 'TLV75533', 60.96, 50.8, footprint='Package_TO_SOT_SMD:SOT-23-5', lcsc='C...')
  c1 = s.add('Device:C', 'C1', '1u', 45.72, 55.88, footprint='Capacitor_SMD:C_0402_1005Metric')
  s.wire(u1.p('VIN'), (45.72, 50.8), c1.p(1))           # pins by number or unique name; orthogonal segments only
  s.power('GND', *c1.p(2))                              # power symbols for rails and ground, not labels
  s.label('VBUS', 30.48, 50.8)                          # labels only between blocks
  s.tap(c2.p(1), c3.p(1))                               # shunt parts hanging off one rail wire, on purpose
  print(s.collisions())                                 # geometric mistakes, before writing
  print(find_merges(s, INTENDED_NETS))                  # where two intended nets touch, with coordinates
  s.write('myproject.kicad_sch')

Coordinates are mm, y down (sheet coordinates), snapped to the 1.27 mm grid. Wires are split at every T-tap and
junctions are added wherever three or more ends meet, so the drawing connects the way it looks. After writing:
`netspec.py check`, `kicad-cli sch erc`, then render the PDF and look.

Hierarchical designs (references/new-design.md "Large designs"): a sub-sheet is a Sch of its own, sharing the root's
project and libraries; its hierarchical labels are the pins of the sheet blocks that place it, once or many times:
  port = s.sub('port.kicad_sch', title='Port')           # parts, wires, power, labels, taps, collisions(), find_merges
  port.hlabel('DIN', 50.8, 60.96, 180, shape='input')    # the sheet's interface (input / output / bidirectional / ...)
  for k in range(16):                                    # one file, 16 instances, each with its own references
      b = s.sheet(port, 'port%d' % (k + 1), 101.6, 25.4 + 12.7 * k, refs=100 * (k + 1))    # R1 -> R101, R201, ...
      s.wire(u1.p('GPIO%d' % k), b.p('DIN'))             # a sheet pin's point, wired like a part pin
  s.write('myproject.kicad_sch')                         # the root, and every sub-sheet file next to it
A power symbol is one global net in every instance: a supply that differs per instance (each bank's own input) comes
in through a hierarchical label instead.
refs= is an int offset, a dict {local: reference} or a function; nested sheets compose them. write() refuses a
reference used twice anywhere in the design, numbers power symbols across it (they stay global nets), writes each
sub-sheet once with one (instances (project (path "/<root>/<block>" (reference ..) (unit ..)))) entry per instance
and the page numbers in the sheet blocks, and keys ids by sub-sheet file and local reference, so an unchanged design
rewrites the same bytes. s.instances() lists every instance's sheet path and reference map (for netspec.py's sheet
templates). find_merges() on a parent names a sheet pin 'BLOCK/LABEL'.
"""
import math, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import Schematic, SymbolLibrary, loads, pins_of  # noqa: E402
from partfields import blank, resolve_datasheet  # noqa: E402

G = 1.27


def snap(v):
    return round(round(v / G) * G, 4)


def kicad_symbol_dir():
    """KiCad's bundled symbol libraries ($KICAD10_SYMBOL_DIR / $KICAD9_SYMBOL_DIR, else the usual install paths)."""
    for c in (os.environ.get('KICAD10_SYMBOL_DIR'), os.environ.get('KICAD9_SYMBOL_DIR'),
              '/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols', '/usr/share/kicad/symbols',
              'C:/Program Files/KiCad/10.0/share/kicad/symbols', 'C:/Program Files/KiCad/9.0/share/kicad/symbols'):
        if c and os.path.isdir(c):
            return c
    cli = shutil.which('kicad-cli')
    if cli:
        c = os.path.join(os.path.dirname(os.path.dirname(cli)), 'share', 'kicad', 'symbols')
        if os.path.isdir(c):
            return c
    raise FileNotFoundError('KiCad symbol directory not found: set KICAD10_SYMBOL_DIR')


# ---------------------------------------------------------------- symbol libraries (read through kicad_sexpr)

def _sym(sym):
    return loads(sym) if isinstance(sym, str) else sym


class SymLib:
    """A .kicad_sym library (from a file or its text). get(name) returns the symbol as a kicad_sexpr node
    (derived symbols flattened, a fresh copy each call)."""

    def __init__(self, nickname, path=None, text=None, lib=None):
        self.nick = nickname
        self.lib = lib if lib is not None else SymbolLibrary.from_text(text, nickname) if text is not None else SymbolLibrary.load(path, nickname)

    def names(self):
        return self.lib.names()

    def get(self, name):
        if name not in self.lib.names():
            raise KeyError('symbol %s not in library %s' % (name, self.nick))
        return self.lib.get(name)


def pin_list(sym):
    """Pins of a library symbol (node or text): list of dict(num, name, type, x, y, rot) in symbol coordinates
    (y up), every unit, body style 1."""
    return [dict(type=p.etype, x=p.x, y=p.y, rot=p.angle, name=p.name, num=p.number) for p in pins_of(_sym(sym), None, 1)]


def body_rect(sym):
    """First rectangle of the symbol body (x0, y0, x1, y1) in symbol coordinates, or None."""
    for r in _sym(sym).walk('rectangle'):
        s, e = r.need('start'), r.need('end')
        return (s.number(1), s.number(2), e.number(1), e.number(2))
    return None


# ---------------------------------------------------------------- schematic

class Part:
    def __init__(self, sch, lib_id, ref, value, x, y, rot, pins, fields, footprint, in_bom, on_board, dnp, mirror=None,
                 in_pos_files=True):
        self.sch, self.lib_id, self.ref, self.value = sch, lib_id, ref, value
        self.x, self.y, self.rot, self.mirror = snap(x), snap(y), rot, mirror
        self.pins, self.fields, self.footprint = pins, fields, footprint
        self.in_bom, self.on_board, self.dnp, self.in_pos_files = in_bom, on_board, dnp, in_pos_files
        self.uuid = None                  # the symbol's uuid, set by Sch.write()

    def xf(self, sx, sy):
        """symbol coordinates (y up) -> sheet coordinates (y down), with this part's rotation and mirror"""
        vx, vy = sx, -sy
        a = math.radians(self.rot)
        x = vx * math.cos(a) + vy * math.sin(a)
        y = -vx * math.sin(a) + vy * math.cos(a)
        if self.mirror == 'x':
            y = -y
        elif self.mirror == 'y':
            x = -x
        return (snap(self.x + x), snap(self.y + y))

    def p(self, key):
        """Connection point of a pin, by number or (unique) name."""
        cands = [q for q in self.pins if q['num'] == str(key)] or [q for q in self.pins if q['name'] == str(key)]
        if not cands:
            raise KeyError('%s has no pin %s' % (self.ref, key))
        if len({(q['x'], q['y']) for q in cands}) > 1:
            raise KeyError('%s: pin name %s is not unique; use the number' % (self.ref, key))
        return self.xf(cands[0]['x'], cands[0]['y'])

    def body(self):
        """sheet-coordinate bounding box of the symbol's body rectangle, or None"""
        r = body_rect(self.sch.used[self.lib_id])
        if not r:
            return None
        a, b = self.xf(r[0], r[1]), self.xf(r[2], r[3])
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


class SheetBlock:
    """One instance of a sub-sheet, drawn on its parent as a sheet block (Sch.sheet()). p(name) is the connection
    point of the sheet pin that carries the sub-sheet's hierarchical label `name`."""

    def __init__(self, parent, child, name, x, y, w, h, refs, pins):
        self.parent, self.child, self.name = parent, child, name
        self.x, self.y, self.w, self.h = snap(x), snap(y), snap(w), snap(h)
        self.refs = refs
        self.pins = pins                  # [dict(name, shape, x, y, side)]
        self.uuid = None                  # the block's uuid (the sub-sheet instance path ends with it), set by write()

    def p(self, name):
        for q in self.pins:
            if q['name'] == name:
                return (q['x'], q['y'])
        raise KeyError('sheet %s has no pin %s (its sheet %s has hierarchical labels %s)' % (
            self.name, name, self.child.file, [n for n, _ in self.child.ports()]))

    def body(self):
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    def map_ref(self, ref):
        """The reference a part of the sub-sheet gets in this instance: refs=None keeps it, an int adds an offset to
        its number (R1 + 100 = R101), a dict renames ({'R1': 'R7'}; others kept), a function maps it."""
        r = self.refs
        if r is None:
            return ref
        if isinstance(r, bool):
            raise TypeError('sheet %s: refs must be an int offset, a dict or a function, not %r' % (self.name, r))
        if isinstance(r, int):
            m = re.match(r'^(.*?)(\d+)$', ref)
            if not m:
                raise ValueError('sheet %s: reference %s has no number to offset by %d: give refs as a dict or a '
                                 'function' % (self.name, ref, r))
            return '%s%d' % (m.group(1), int(m.group(2)) + r)
        if isinstance(r, dict):
            return r.get(ref, ref)
        if callable(r):
            return r(ref)
        raise TypeError('sheet %s: refs must be an int offset, a dict or a function, not %r' % (self.name, r))


def _on_interior(pt, a, b):
    return (a[0] == b[0] == pt[0] and min(a[1], b[1]) < pt[1] < max(a[1], b[1])) or \
           (a[1] == b[1] == pt[1] and min(a[0], b[0]) < pt[0] < max(a[0], b[0]))


class Sch:
    def __init__(self, project, paper='A3', title='', rev='', date='', file=None):
        self.project, self.paper, self.title, self.rev, self.date = project, paper, title, rev, date
        self.file = file                  # a sub-sheet's file name (next to the root sheet); None for the root
        self.blocks = []                  # sheet blocks drawn on this sheet (sheet())
        self.placed_in = []               # the blocks that instantiate this sheet (it is a sub-sheet if any)
        self.uuid = None                  # the sheet's uuid, set by write()
        self.libs, self.used = {}, {}
        self.parts, self.wires, self.labels, self.noconnects, self.texts, self.extra_junctions = [], [], [], [], [], []
        self.taps = set()                 # points declared as intended T-taps (tap())
        self.pwr_n = 0
        self.accepted = {}                # (ref, field) -> reason a BOM part may be written without that field
        self.field_sources = {}           # ref -> where its Datasheet came from

    def accept_missing(self, ref, field, reason):
        """Let write() keep a BOM part with a blank field (e.g. a bare test pad has no datasheet). By name, with a
        reason; listed by write()."""
        self.accepted[(ref, field)] = reason

    def lib(self, nickname, path=None, text=None, lib=None):
        """a symbol library by file, by text, or as a kicad_sexpr SymbolLibrary (e.g. symgen.library(...))"""
        self.libs[nickname] = SymLib(nickname, path, text, lib)

    def libsym(self, lib_id):
        """The library symbol 'Lib:Name' as a kicad_sexpr node (a fresh copy)."""
        nick, name = lib_id.split(':', 1)
        return self.libs[nick].get(name)

    symtext = libsym                      # older name

    def add(self, lib_id, ref, value, x, y, rot=0, footprint='', lcsc='', fields=None, in_bom=True, on_board=True,
            dnp=False, mirror=None, in_pos_files=None):
        """fields: extra properties (hidden). Keys starting with '_' are layout hints: _ref_at, _val_at (x, y),
        _just, _hide_value, _visible (list of field names shown under the value).
        Assembly method per part, decided here and carried to the board by new_board.py: assembled (defaults),
        hand-soldered (in_bom=False: in_pos_files follows it unless given), not fitted (dnp=True)."""
        t = self.used.get(lib_id) or self.libsym(lib_id)
        self.used[lib_id] = t
        f = dict(fields or {})
        if lcsc:
            f['LCSC'] = lcsc
        p = Part(self, lib_id, ref, value, x, y, rot, pin_list(t), f, footprint, in_bom, on_board, dnp, mirror,
                 (in_bom or ref.startswith('#')) if in_pos_files is None else in_pos_files)
        self.parts.append(p)
        return p

    def power(self, net, x, y, rot=0, lib_id=None):
        """Power symbol at (x, y): power:GND by default for GND (points down), power:VCC (value = net) otherwise."""
        if lib_id is None:
            lib_id = 'power:GND' if net == 'GND' else 'power:VCC'
        self.pwr_n += 1
        return self.add(lib_id, '#PWR%03d' % self.pwr_n, net, x, y, rot, in_bom=False, on_board=False)

    def wire(self, *pts):
        pts = [(snap(a), snap(b)) for a, b in pts]
        for a, b in zip(pts, pts[1:]):
            if a != b:
                assert a[0] == b[0] or a[1] == b[1], 'non-orthogonal wire %s -> %s' % (a, b)
                self.wires.append((a, b))

    def tap(self, *pts):
        """Declare intended T-taps: pin points that sit on the interior of a wire on purpose, e.g. the shunt parts of a
        ladder hanging off one rail wire: s.tap(c1.p(1), c2.p(1)). write() joins them with a junction as it does every
        pin on a wire; collisions() stops reporting them, and reports a declared tap that touches no wire."""
        self.taps.update((snap(x), snap(y)) for x, y in pts)

    def hv(self, a, b):
        """L-shaped wire: horizontal first, then vertical."""
        self.wire(a, (b[0], a[1]), b)

    def vh(self, a, b):
        """L-shaped wire: vertical first, then horizontal."""
        self.wire(a, (a[0], b[1]), b)

    def label(self, name, x, y, rot=0, kind='label', shape='passive'):
        self.labels.append((kind, name, snap(x), snap(y), rot, shape))

    # ------------------------------------------------------------ hierarchy

    def sub(self, file, paper='A4', title='', rev=None, date=None):
        """A sub-sheet of this design, written to `file` next to the root sheet: a Sch of its own (parts, wires,
        power, labels, taps, collisions(), find_merges) that shares this sheet's project and symbol libraries. Its
        hierarchical labels (hlabel()) become the pins of every sheet block that places it (sheet())."""
        if not file.endswith('.kicad_sch') or os.path.basename(file) != file:
            raise ValueError('sub-sheet file %r: a plain file name ending .kicad_sch (it is written next to the root '
                             'sheet)' % file)
        c = Sch(self.project, paper, title, self.rev if rev is None else rev, self.date if date is None else date,
                file=file)
        c.libs = self.libs
        return c

    def hlabel(self, name, x, y, rot=0, shape='bidirectional'):
        """Hierarchical label (shape input, output, bidirectional, tri_state, passive): a signal that leaves this
        sub-sheet through the pin of the same name on its sheet blocks. Anchor = connection point, as label()."""
        if shape not in ('input', 'output', 'bidirectional', 'tri_state', 'passive'):
            raise ValueError('hierarchical label %s: shape %r' % (name, shape))
        self.labels.append(('hierarchical_label', name, snap(x), snap(y), rot, shape))

    def ports(self):
        """[(name, shape)] of this sheet's hierarchical labels, one per name, in the order first drawn."""
        out = {}
        for kind, name, x, y, rot, shape in self.labels:
            if kind == 'hierarchical_label':
                if name in out and out[name] != shape:
                    raise ValueError('%s: hierarchical label %s drawn as %s and as %s' % (self.file, name, out[name], shape))
                out.setdefault(name, shape)
        return list(out.items())

    def sheet(self, child, name, x, y, w=None, h=None, refs=None, left=None, right=None):
        """Place one instance of sub-sheet `child` (from sub()) as a sheet block with its top-left corner at (x, y).
        The same child may be placed any number of times (one file, N instances); each instance needs its own
        references, from `refs`: an int offset (R1 -> R101 with 100), a dict {local: final}, or a function. With
        nested sheets the mappings compose, innermost first. Every non-power reference in the design must be unique:
        write() refuses duplicates and says which instances clash. Power symbols (#PWR, #FLG) are numbered across
        the design by write() and stay global nets.
        Pins: one per hierarchical label of the child, input/bidirectional/passive/tri_state on the left edge and
        output on the right (`left` / `right` lists of names override), 2.54 mm apart from 2.54 mm below the top.
        Size: w x h, by default sized to fit the pins. Returns the SheetBlock; block.p('NAME') is a pin's point."""
        if not isinstance(child, Sch) or not child.file:
            raise ValueError('sheet %s: the child must be a sub-sheet made with sub(file)' % name)
        if child is self:
            raise ValueError('sheet %s: a sheet cannot contain itself' % name)
        if child.project != self.project:
            raise ValueError('sheet %s: sub-sheet project %r is not %r' % (name, child.project, self.project))
        if not name or '/' in name or any(b.name == name for b in self.blocks):
            raise ValueError('sheet name %r: names are unique on a sheet and contain no "/"' % name)
        if refs is not None and (isinstance(refs, bool) or not (isinstance(refs, (int, dict)) or callable(refs))):
            raise TypeError('sheet %s: refs must be an int offset, a dict or a function, not %r' % (name, refs))
        ports = child.ports()
        shapes = dict(ports)
        if left is None and right is None:
            left = [n for n, sh in ports if sh != 'output']
            right = [n for n, sh in ports if sh == 'output']
        elif left is None:
            left = [n for n, _ in ports if n not in right]
        elif right is None:
            right = [n for n, _ in ports if n not in left]
        both = list(left) + list(right)
        if sorted(both) != sorted(shapes) or len(set(both)) != len(both):
            raise ValueError('sheet %s: left %s + right %s must name each hierarchical label of %s once: %s' % (
                name, left, right, child.file, sorted(shapes)))
        n = max(len(left), len(right), 1)
        if h is None:
            h = (n + 1) * G * 2
        if snap(h) < (n + 1) * G * 2 - 1e-6:
            raise ValueError('sheet %s: height %s holds no %d pins 2.54 mm apart' % (name, h, n))
        if w is None:
            chars = max((len(a) for a in left), default=0) + max((len(a) for a in right), default=0)
            w = max(20.32, math.ceil((chars * 1.27 + 7.62) / 2.54) * 2.54)
        x, y, w = snap(x), snap(y), snap(w)
        pins = [dict(name=a, shape=shapes[a], x=x, y=snap(y + 2.54 * (i + 1)), side='left') for i, a in enumerate(left)]
        pins += [dict(name=a, shape=shapes[a], x=snap(x + w), y=snap(y + 2.54 * (i + 1)), side='right')
                 for i, a in enumerate(right)]
        b = SheetBlock(self, child, name, x, y, w, h, refs, pins)
        self.blocks.append(b)
        child.placed_in.append(b)
        return b

    def _walk(self):
        """[(sheet, chain of blocks from the root)] for every sheet instance below this root, in page order."""
        out = []

        def visit(s, chain):
            above = [self] + [b.child for b in chain[:-1]]
            if chain and any(a is s for a in above):
                raise ValueError('sheet %s contains itself (%s)' % (s.file, '/'.join(b.name for b in chain)))
            out.append((s, chain))
            for b in s.blocks:
                visit(b.child, chain + [b])
        visit(self, [])
        return out

    def _refs(self, s, chain, counters):
        """{id(part): reference} of sheet s in the instance reached by chain (power symbols numbered by counters)"""
        m = {}
        for p in s.parts:
            if p.ref.startswith('#'):
                pre = re.match(r'#[A-Za-z_]*', p.ref).group(0)
                counters[pre] = counters.get(pre, 0) + 1
                m[id(p)] = '%s%03d' % (pre, counters[pre])
                continue
            r = p.ref
            for b in reversed(chain):
                r = b.map_ref(r)
            if not isinstance(r, str) or not r or r.startswith('#') or r != r.strip():
                raise ValueError('sheet %s maps %s to the reference %r' % ('/'.join(b.name for b in chain), p.ref, r))
            m[id(p)] = r
        return m

    def instances(self):
        """[(sheet path, sheet, {local reference: reference in this instance})] for every sheet instance of the
        design under this root sheet, in page order: '/' is the root, '/port1/' a block named port1 on it,
        '/bank/port1/' one nested below. The references are the ones write() puts in the files (and KiCad in the
        netlist); netspec.py's sheet specs take them as {"refs": {...}} or as the same int offset."""
        counters, out = {}, []
        for s, chain in self._walk():
            m = self._refs(s, chain, counters)
            out.append(('/' + ''.join(b.name + '/' for b in chain), s,
                        {p.ref: m[id(p)] for p in s.parts if not p.ref.startswith('#')}))
        return out

    def nc(self, pt):
        self.noconnects.append((snap(pt[0]), snap(pt[1])))

    def text(self, s, x, y, size=1.27, bold=False):
        self.texts.append((s, snap(x), snap(y), size, bold))

    # ------------------------------------------------------------ geometry checks

    def _pin_points(self):
        return [(p, q, p.p(q['num'])) for p in self.parts for q in p.pins]

    def _sheet_pin_points(self):
        return [(b, q, (q['x'], q['y'])) for b in self.blocks for q in b.pins]

    def _junctions(self):
        ends = {}
        for a, b in self.wires:
            ends[a] = ends.get(a, 0) + 1
            ends[b] = ends.get(b, 0) + 1
        pin_pts = {pt for _, _, pt in self._pin_points() + self._sheet_pin_points()}
        for pt in list(ends):
            if pt in pin_pts:
                ends[pt] += 1
        js = {pt for pt, n in ends.items() if n >= 3}
        for pt in ends:
            if any(_on_interior(pt, a, b) for a, b in self.wires):
                js.add(pt)
        return sorted(js | set(self.extra_junctions))

    def pin_on_wire_interior(self):
        """Pins that sit on the interior of a wire (they connect to it - usually a mistake unless intended)."""
        return [(p.ref, q['num'], pt) for p, q, pt in self._pin_points() if any(_on_interior(pt, a, b) for a, b in self.wires)]

    def collisions(self):
        """Drawing faults visible from geometry alone, as messages (empty = none found):
        pins on another wire's interior, collinear wires that overlap, wires crossing a part's body rectangle,
        two parts' bodies overlapping. Run before write(); then find_merges() with the intended nets."""
        out = ['pin %s.%s at %s lies on the interior of a wire (it connects to it; s.tap(point) if intended)' % x
               for x in self.pin_on_wire_interior() if x[2] not in self.taps]
        out += ['tap at %s touches no wire' % (pt,) for pt in sorted(self.taps)
                if not any(pt in (a, b) or _on_interior(pt, a, b) for a, b in self.wires)]
        for i, (a, b) in enumerate(self.wires):
            for c, d in self.wires[i + 1:]:
                if a[0] == b[0] == c[0] == d[0]:
                    lo, hi = max(min(a[1], b[1]), min(c[1], d[1])), min(max(a[1], b[1]), max(c[1], d[1]))
                elif a[1] == b[1] == c[1] == d[1]:
                    lo, hi = max(min(a[0], b[0]), min(c[0], d[0])), min(max(a[0], b[0]), max(c[0], d[0]))
                else:
                    continue
                if hi - lo > 1e-6:
                    out.append('wires %s-%s and %s-%s overlap along their length' % (a, b, c, d))
        bodies = [(p, p.body()) for p in self.parts if not p.ref.startswith('#')]
        bodies = [(p, bb) for p, bb in bodies if bb]
        for p, (x0, y0, x1, y1) in bodies:
            for a, b in self.wires:
                if a[1] == b[1] and y0 < a[1] < y1 and min(a[0], b[0]) < x1 and max(a[0], b[0]) > x0 or \
                   a[0] == b[0] and x0 < a[0] < x1 and min(a[1], b[1]) < y1 and max(a[1], b[1]) > y0:
                    out.append('wire %s-%s crosses the body of %s' % (a, b, p.ref))
        for i, (p, b1) in enumerate(bodies):
            for q, b2 in bodies[i + 1:]:
                if b1[0] < b2[2] and b2[0] < b1[2] and b1[1] < b2[3] and b2[1] < b1[3]:
                    out.append('bodies of %s and %s overlap' % (p.ref, q.ref))
        # sheet blocks: their pins connect like part pins; their rectangles are bodies
        ends = {a for w in self.wires for a in w} | {(x, y) for _, _, x, y, _, _ in self.labels} | \
            {pt for _, _, pt in self._pin_points()}
        for b, q, pt in self._sheet_pin_points():
            if pt not in self.taps and any(_on_interior(pt, a, c) for a, c in self.wires):
                out.append('sheet pin %s/%s at %s lies on the interior of a wire (it connects to it; s.tap(point) if '
                           'intended)' % (b.name, q['name'], pt))
            elif pt not in ends and not any(_on_interior(pt, a, c) for a, c in self.wires):
                out.append('sheet pin %s/%s at %s is not connected (no wire, label or pin there)' % (b.name, q['name'], pt))
        blocks = [(b, b.body()) for b in self.blocks]
        for b, (x0, y0, x1, y1) in blocks:
            for a, c in self.wires:
                if a[1] == c[1] and y0 < a[1] < y1 and min(a[0], c[0]) < x1 and max(a[0], c[0]) > x0 or \
                   a[0] == c[0] and x0 < a[0] < x1 and min(a[1], c[1]) < y1 and max(a[1], c[1]) > y0:
                    out.append('wire %s-%s crosses sheet block %s' % (a, c, b.name))
            for p, (u0, v0, u1, v1) in bodies:
                if u0 < x1 and x0 < u1 and v0 < y1 and y0 < v1:
                    out.append('body of %s overlaps sheet block %s' % (p.ref, b.name))
        for i, (b, r1) in enumerate(blocks):
            for c, r2 in blocks[i + 1:]:
                if r1[0] < r2[2] and r2[0] < r1[2] and r1[1] < r2[3] and r2[1] < r1[3]:
                    out.append('sheet blocks %s and %s overlap' % (b.name, c.name))
        return out

    # ------------------------------------------------------------ output

    def _field_spots(self, p):
        """Default (ref x, y, value x, y, angle, justify) for a placed part."""
        n = len({q['num'] for q in p.pins})
        if p.ref.startswith('#'):
            if p.rot == 180:
                return p.x, p.y + 5.08, p.x, p.y + 5.08, 0, 'center'
            return p.x, p.y - 3.81, p.x, p.y - 3.81, 0, 'center'
        if n == 2:
            if p.rot in (90, 270):
                return p.x, p.y - 2.54, p.x, p.y + 2.54, 90, 'center'
            if p.fields.get('_visible'):
                return p.x + 2.54, p.y - 2.54, p.x + 2.54, p.y, 0, 'left'
            return p.x + 2.54, p.y - 1.27, p.x + 2.54, p.y + 1.27, 0, 'left'
        r = body_rect(self.used[p.lib_id])
        if r and p.rot == 0 and not p.mirror:
            x1, y1, x2, y2 = r
            left, top, bot = p.x + min(x1, x2), p.y - max(y1, y2), p.y - min(y1, y2)
            return left, top - 1.27, left, bot + 2.54, 0, 'left'
        return p.x + 3.81, p.y - 3.81, p.x + 3.81, p.y + 3.81, 90 if p.rot in (90, 270) else 0, 'left'

    def carried_fields(self, p):
        """The part's fields with everything its library symbol carries that the caller did not override: Footprint,
        Datasheet, Description and any custom property (LCSC, MPN, Manufacturer from an imported symbol). Datasheet
        falls back to the LCSC datasheet URL. Data that exists upstream is never dropped here."""
        lib = {str(q[1]): str(q[2]) for q in self.used[p.lib_id].nodes('property') if not str(q[1]).startswith('ki_')}
        f = {k: v for k, v in lib.items() if k not in ('Reference', 'Value') and not blank(v)}
        f.update({k: v for k, v in p.fields.items() if not (k in ('Datasheet', 'Description') and blank(v))})
        part_lib = any(not blank(lib.get(k)) for k in ('LCSC', 'LCSC Part', 'MPN', 'Manufacturer Part'))
        ds, src = resolve_datasheet(p.fields.get('Datasheet'), lib.get('Datasheet'), f, library_is_part=part_lib)
        if ds:
            f['Datasheet'] = ds
        self.field_sources[p.ref] = src
        fp = p.footprint or f.get('Footprint', '')
        f.pop('Footprint', None)
        return f, fp

    def missing_fields(self):
        """[(ref, field)] for BOM parts that would be written without a datasheet link, minus accepted ones"""
        out = []
        for p in self.parts:
            if p.ref.startswith('#') or not p.in_bom or not p.on_board:
                continue
            f, _ = self.carried_fields(p)
            if blank(f.get('Datasheet')) and (p.ref, 'Datasheet') not in self.accepted:
                out.append((p.ref, 'Datasheet'))
        return out

    def _place(self, sch, p, instances=None):
        """Add part p to a kicad_sexpr Schematic: the field set and layout this generator decides (Reference, Value,
        Footprint, Datasheet, then the extra fields hidden, then the _visible ones stacked under the value).
        instances: [(instance path, reference)] on a sheet of a hierarchical design (the first one is the Reference
        property, as KiCad writes it; the symbol's id is keyed by the local reference, so it does not move when an
        instance's references are renumbered)."""
        visible = p.fields.get('_visible', [])
        allf, footprint = self.carried_fields(p)
        # a library Description goes where KiCad puts it; one the caller gave stays in the caller's field order
        desc = allf.pop('Description', None) if blank(p.fields.get('Description')) else None
        extra = [k for k in allf if k != 'Datasheet' and not k.startswith('_') and k not in visible]
        names = ['Reference', 'Value', 'Footprint', 'Datasheet'] + extra
        assert len(names) == len(set(names)), '%s: duplicate property names %s' % (p.ref, names)
        fields = {k: allf[k] for k in extra + list(visible)}
        hier = dict(instances=instances, key=None if p.ref.startswith('#') else 'symbol/%s/1' % p.ref) if instances else {}
        s = sch.add_symbol(p.lib_id, instances[0][1] if instances else p.ref, p.value, (p.x, p.y), p.rot, p.mirror,
                           footprint=footprint,
                           datasheet=allf.get('Datasheet', ''), description=desc, fields=fields, in_bom=p.in_bom,
                           on_board=p.on_board, dnp=p.dnp, in_pos_files=p.in_pos_files, lib_fields=('Reference', 'Value', 'Footprint', 'Datasheet', 'Description'),
                           **hier)
        p.uuid = s.uuid
        rx, ry, vx, vy, ang, just = self._field_spots(p)
        rx, ry = p.fields.get('_ref_at', (rx, ry))
        vx, vy = p.fields.get('_val_at', (vx, vy))
        just = p.fields.get('_just', just)

        def put(k, x, y, hide):
            s.set_field(k, at=(snap(x), snap(y)), angle=ang, justify=[just], hide=hide)
        put('Reference', rx, ry, p.ref.startswith('#'))
        put('Value', vx, vy, p.fields.get('_hide_value', p.lib_id == 'power:GND'))
        for k in ['Footprint', 'Datasheet'] + (['Description'] if desc is not None else []) + extra:
            put(k, p.x, p.y, True)
        for i, k in enumerate(visible):
            put(k, vx, vy + 2.54 * (i + 1), False)

    def split_wires(self):
        """The wires split at every pin point and wire end lying on their interior (T-taps become real joints)."""
        pts = {a for w in self.wires for a in w} | {pt for _, _, pt in self._pin_points() + self._sheet_pin_points()}
        out = []
        for a, b in self.wires:
            cuts = [pt for pt in pts if pt not in (a, b) and _on_interior(pt, a, b)]
            seq = sorted([a, b] + cuts, key=lambda q: (q[0] - a[0]) ** 2 + (q[1] - a[1]) ** 2)
            out += [(u, v) for u, v in zip(seq, seq[1:]) if u != v]
        return out

    def _check_fields(self, where=None):
        miss = self.missing_fields()
        if miss:
            raise ValueError('%sBOM parts with no datasheet link anywhere upstream (not in the call, not in the library '
                             'symbol, no LCSC number): %s. Give fields={"Datasheet": url} (the manufacturer\'s page for the '
                             'exact part), an LCSC number, or Sch.accept_missing(ref, "Datasheet", reason).'
                             % ('%s: ' % where if where else '', ', '.join(r for r, _ in miss)))
        for (r, k), why in sorted(self.accepted.items()):
            print('schgen: %s%s written without %s (accepted: %s)' % ('%s: ' % where if where else '', r, k, why))

    def _emit(self, sch, refs_of=None):
        """Everything drawn on this sheet except its sheet blocks, into the kicad_sexpr Schematic sch.
        refs_of(part) -> [(instance path, reference)] in a hierarchical design (None: a single flat sheet)."""
        self.wires = self.split_wires()
        for lib_id, sym in sorted(self.used.items()):
            sch.embed_symbol(lib_id, sym)
        for pt in self._junctions():
            sch.junction(pt)
        for pt in self.noconnects:
            sch.no_connect(pt)
        for a, b in self.wires:
            sch.wire(a, b)
        for kind, name, x, y, rot, shape in self.labels:
            if kind == 'label':
                sch.label(name, (x, y), rot)
            elif kind == 'hierarchical_label':
                sch.hierarchical_label(name, (x, y), rot, shape)
            else:
                sch.global_label(name, (x, y), rot, shape)
        for s, x, y, size, bold in self.texts:
            sch.text(s, (x, y), size=size, bold=bold)
        for p in self.parts:
            self._place(sch, p, refs_of(p) if refs_of else None)

    def write(self, path, previous='auto'):
        """Write the sheet through kicad_sexpr (which owns the syntax, uuids and KiCad 10 layout).
        Ids are stable: items keep the uuid they had in ``previous`` (default: the file being overwritten, if it
        exists; None = from scratch), matched by reference / position; new items get ids derived from their key, so
        an unchanged design rewrites the same bytes and board footprints stay linked to their symbols.
        A root sheet with sheet blocks writes the whole design: itself at `path` and every sub-sheet file next to it
        (``previous`` is then 'auto', None, or an earlier root sheet whose folder holds the earlier sub-sheets)."""
        if self.placed_in:
            raise ValueError('%s is a sub-sheet (sheet block %s): write the root sheet, which writes every sheet file'
                             % (self.file, self.placed_in[0].name))
        if self.blocks:
            return self._write_design(path, previous)
        self._check_fields()
        if previous == 'auto':
            previous = path if os.path.exists(path) else None
        sch = Schematic.new(self.project, paper=self.paper, title=self.title, date=self.date, rev=self.rev,
                            previous=previous)
        self.uuid = sch.uuid
        self._emit(sch)
        sch.save(path)

    def _write_design(self, path, previous):
        """write() for a root sheet with sheet blocks: every sheet file, every instance's references and pages."""
        walk = self._walk()
        sheets = []
        for s, _ in walk:
            if not any(s is t for t in sheets):
                sheets.append(s)
        root_file = os.path.basename(path)
        files = {}
        for s in sheets[1:]:
            if s.file == root_file or files.setdefault(s.file, s) is not s:
                raise ValueError('two different sheets would be written to %s' % s.file)
        for s in sheets:
            ports = dict(s.ports()) if s is not self else {}
            for b in s.placed_in:
                got = {q['name']: q['shape'] for q in b.pins}
                if got != ports:
                    raise ValueError('sheet block %s has pins %s but %s now has hierarchical labels %s: place the block '
                                     'after drawing the labels' % (b.name, sorted(got.items()), s.file, sorted(ports.items())))
            s._check_fields(s.file or root_file)
        here = os.path.dirname(os.path.abspath(path))
        target = {id(s): path if s is self else os.path.join(here, s.file) for s in sheets}

        def prev_of(s):
            if previous == 'auto':
                return target[id(s)] if os.path.exists(target[id(s)]) else None
            if previous is None:
                return None
            if s is self:
                return previous
            old = os.path.join(os.path.dirname(os.path.abspath(previous)), s.file)
            return old if os.path.exists(old) else None
        schs = {}
        for s in sheets:
            if s is self:
                schs[id(s)] = Schematic.new(self.project, paper=self.paper, title=self.title, date=self.date,
                                            rev=self.rev, previous=prev_of(s))
            else:
                schs[id(s)] = Schematic.new(self.project, paper=s.paper, title=s.title, date=s.date, rev=s.rev,
                                            root=False, file=s.file, previous=prev_of(s))
            s.uuid = schs[id(s)].uuid
        nodes = {}
        for s in sheets:
            for b in s.blocks:
                nodes[id(b)] = schs[id(s)].sheet(
                    b.name, b.child.file, (b.x, b.y), (b.w, b.h), instances=[],
                    pins=[(q['name'], q['shape'], (q['x'], q['y']), 180 if q['side'] == 'left' else 0) for q in b.pins])
                b.uuid = str(nodes[id(b)].get('uuid'))
        # instance paths and pages in page order (root = page 1), references per instance
        counters, refs, seen = {}, {id(s): [] for s in sheets}, {}
        for page, (s, chain) in enumerate(walk, 1):
            ipath = '/' + self.uuid + ''.join('/' + b.uuid for b in chain)
            if chain:
                b = chain[-1]
                schs[id(b.parent)].sheet_instance(nodes[id(b)], ipath.rsplit('/', 1)[0], str(page))
            m = self._refs(s, chain, counters)
            refs[id(s)].append((ipath, m))
            where = '/' + ''.join(b.name + '/' for b in chain)
            for p in s.parts:
                if not p.ref.startswith('#'):
                    seen.setdefault(m[id(p)], []).append('%s (%s on %s)' % (where, p.ref, s.file or root_file))
        dup = {r: w for r, w in seen.items() if len(w) > 1}
        if dup:
            raise ValueError('duplicate references in the design: %s. Each instance of a sheet used more than once '
                             'needs its own references: sheet(..., refs=100 * k) (an offset), a dict or a function.' % (
                                 '; '.join('%s in %s' % (r, ', '.join(w)) for r, w in sorted(dup.items())[:8])))
        for s in sheets:
            insts = refs[id(s)]
            s._emit(schs[id(s)], lambda p, insts=insts: [(ipath, m[id(p)]) for ipath, m in insts])
        bad = ['%s: %s' % (s.file or root_file, m) for s in sheets for m in schs[id(s)].validate()]
        if bad:                                   # nothing is written unless every file is valid
            raise ValueError('refusing to write an invalid design:\n  ' + '\n  '.join(bad))
        for s in sheets:
            schs[id(s)].save(target[id(s)])


def find_merges(sch, intended, symmetric=('R', 'C', 'L', 'FB', 'F')):
    """Union-find over the drawn geometry (wire ends, pin points, power symbols, labels). intended: {net: ['REF.PIN']}
    with the sheet's own (local) references; on a sheet with sheet blocks, 'BLOCK/LABEL' names a sheet pin.
    Returns one message per wire, pin, label or power symbol that joins two different intended nets, with
    coordinates, so a short found by netspec.py can be located in the drawing. Two-pin passive parts (reference
    prefix in `symmetric`, both pins passive) may be drawn either way round: their pins are tagged after the geometry
    is joined, in the orientation that conflicts least. PWR_FLAG symbols are not net names."""
    owner = {p: n for n, ps in intended.items() for p in ps}
    parent, tags, msgs = {}, {}, []

    def f(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b, why):
        ra, rb = f(a), f(b)
        if ra == rb:
            return
        ta, tb = tags.get(ra, set()), tags.get(rb, set())
        if ta and tb and ta != tb:
            msgs.append('MERGE %s + %s via %s' % (sorted(ta), sorted(tb), why))
        parent[ra] = rb
        tags[rb] = ta | tb

    def tag(pt, key, n):
        r = f(pt)
        if tags.get(r) and n not in tags[r]:
            msgs.append('MERGE %s + %s at pin %s %s' % (sorted(tags[r]), n, key, pt[1:]))
        tags[r] = tags.get(r, set()) | {n}

    def is_sym(p):
        return re.match(r'[A-Za-z]*', p.ref).group(0) in symmetric and len(p.pins) == 2 and \
            all(q['type'] == 'passive' for q in p.pins)
    later = []
    for p in sch.parts:
        if p.ref.startswith('#'):
            if p.value != 'PWR_FLAG':
                for q in p.pins:
                    pt = ('pt',) + p.p(q['num'])
                    union(pt, ('name', p.value), 'power symbol %s at %s' % (p.value, pt[1:]))
            continue
        if is_sym(p):
            later.append(p)
            continue
        for q in p.pins:
            key = '%s.%s' % (p.ref, q['num'])
            if key in owner:
                tag(('pt',) + p.p(q['num']), key, owner[key])
    for b in getattr(sch, 'blocks', []):
        for q in b.pins:
            key = '%s/%s' % (b.name, q['name'])           # a sheet pin is named BLOCK/LABEL in `intended`
            if key in owner:
                tag(('pt', q['x'], q['y']), key, owner[key])
    for kind, name, x, y, rot, shape in sch.labels:
        union(('pt', x, y), ('name', name), 'label %s at %s' % (name, (x, y)))
    for a, b in sch.split_wires():
        union(('pt',) + a, ('pt',) + b, 'wire %s-%s' % (a, b))
    for p in later:
        k1, k2 = '%s.%s' % (p.ref, p.pins[0]['num']), '%s.%s' % (p.ref, p.pins[1]['num'])
        n1, n2 = owner.get(k1), owner.get(k2)
        pt1, pt2 = ('pt',) + p.p(p.pins[0]['num']), ('pt',) + p.p(p.pins[1]['num'])
        bad = lambda pt, n: n is not None and bool(tags.get(f(pt))) and n not in tags[f(pt)]
        if bad(pt1, n1) + bad(pt2, n2) > bad(pt1, n2) + bad(pt2, n1):
            n1, n2 = n2, n1
        if n1:
            tag(pt1, k1, n1)
        if n2:
            tag(pt2, k2, n2)
    return msgs
