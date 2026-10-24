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
  print(s.collisions())                                 # geometric mistakes, before writing
  print(find_merges(s, INTENDED_NETS))                  # where two intended nets touch, with coordinates
  s.write('myproject.kicad_sch')

Coordinates are mm, y down (sheet coordinates), snapped to the 1.27 mm grid. Wires are split at every T-tap and
junctions are added wherever three or more ends meet, so the drawing connects the way it looks. Single sheet: symbol
instances use the root path. After writing: `netspec.py check`, `kicad-cli sch erc`, then render the PDF and look.
"""
import math, os, re, shutil, uuid

G = 1.27


def snap(v):
    return round(round(v / G) * G, 4)


def uid():
    return str(uuid.uuid4())


def kstr(s):
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


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


# ---------------------------------------------------------------- symbol libraries

def _blocks(text, head):
    """Yield (name, start, end) for top-level '(symbol "name"' blocks in a .kicad_sym text."""
    i, depth, n, in_str, starts = 0, 0, len(text), False, []
    while i < n:
        c = text[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == '(':
            if depth == 1 and text.startswith(head, i):
                starts.append(i)
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 1 and starts and starts[-1] is not None:
                s = starts[-1]
                yield re.match(r'\(symbol "([^"]+)"', text[s:]).group(1), s, i + 1
                starts[-1] = None
        i += 1


class SymLib:
    def __init__(self, nickname, path=None, text=None):
        self.nick = nickname
        text = text if text is not None else open(path, encoding='utf-8').read()
        self.raw = {name: text[s:e] for name, s, e in _blocks(text, '(symbol "')}

    def get(self, name):
        if name not in self.raw:
            raise KeyError('symbol %s not in library %s' % (name, self.nick))
        return self.raw[name]


def pin_list(sym_text):
    """Pins of a symbol block: list of dict(num, name, type, x, y, rot) in symbol coordinates (y up)."""
    out = []
    for m in re.finditer(r'\(pin (\w+) \w+\s*\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)(.*?)\(name "([^"]*)"(.*?)\(number "([^"]*)"',
                         sym_text, re.S):
        out.append(dict(type=m.group(1), x=float(m.group(2)), y=float(m.group(3)), rot=float(m.group(4) or 0),
                        name=m.group(6), num=m.group(8)))
    return out


def body_rect(sym_text):
    """First rectangle of the symbol body (x0, y0, x1, y1) in symbol coordinates, or None."""
    m = re.search(r'\(rectangle\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)', sym_text)
    return tuple(float(v) for v in m.groups()) if m else None


def embed(lib_id, sym_text):
    """Rename a library symbol block for the schematic's lib_symbols section."""
    name = re.match(r'\(symbol "([^"]+)"', sym_text).group(1)
    return sym_text.replace('(symbol "%s"' % name, '(symbol "%s"' % lib_id, 1)


# ---------------------------------------------------------------- schematic

class Part:
    def __init__(self, sch, lib_id, ref, value, x, y, rot, pins, fields, footprint, in_bom, on_board, dnp, mirror=None):
        self.sch, self.lib_id, self.ref, self.value = sch, lib_id, ref, value
        self.x, self.y, self.rot, self.mirror = snap(x), snap(y), rot, mirror
        self.pins, self.fields, self.footprint = pins, fields, footprint
        self.in_bom, self.on_board, self.dnp = in_bom, on_board, dnp
        self.uuid = uid()

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
        r = body_rect(self.sch.symtext(self.lib_id))
        if not r:
            return None
        a, b = self.xf(r[0], r[1]), self.xf(r[2], r[3])
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _on_interior(pt, a, b):
    return (a[0] == b[0] == pt[0] and min(a[1], b[1]) < pt[1] < max(a[1], b[1])) or \
           (a[1] == b[1] == pt[1] and min(a[0], b[0]) < pt[0] < max(a[0], b[0]))


# ------------------------------------------------- s-expression writers (one per object type)

def junction_sexpr(pt):
    return '\t(junction\n\t\t(at %s %s)\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n\t\t(uuid "%s")\n\t)\n' % (pt[0], pt[1], uid())


def no_connect_sexpr(pt):
    return '\t(no_connect\n\t\t(at %s %s)\n\t\t(uuid "%s")\n\t)\n' % (pt[0], pt[1], uid())


def wire_sexpr(a, b):
    return ('\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n'
            '\t\t)\n\t\t(uuid "%s")\n\t)\n') % (a[0], a[1], b[0], b[1], uid())


def label_sexpr(kind, name, x, y, rot, shape):
    just = 'left' if rot in (0, 90) else 'right'
    if kind == 'label':
        return ('\t(label %s\n\t\t(at %s %s %s)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
                '\t\t\t(justify %s bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)\n') % (kstr(name), x, y, rot, just, uid())
    return ('\t(global_label %s\n\t\t(shape %s)\n\t\t(at %s %s %s)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n'
            '\t\t\t)\n\t\t\t(justify %s)\n\t\t)\n\t\t(uuid "%s")\n\t)\n') % (kstr(name), shape, x, y, rot, just, uid())


def text_sexpr(s, x, y, size, bold):
    return ('\t(text %s\n\t\t(exclude_from_sim no)\n\t\t(at %s %s 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size %s %s)%s\n'
            '\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)\n') % (
        kstr(s), x, y, size, size, '\n\t\t\t\t(bold yes)' if bold else '', uid())


def property_sexpr(key, value, x, y, ang, just='center', hidden=False):
    return ('\t\t(property %s %s\n\t\t\t(at %s %s %s)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
            '\t\t\t\t)%s%s\n\t\t\t)\n\t\t)\n') % (kstr(key), kstr(value), snap(x), snap(y), ang,
                                                '' if just == 'center' else '\n\t\t\t\t(justify %s)' % just,
                                                '\n\t\t\t\t(hide yes)' if hidden else '')


class Sch:
    def __init__(self, project, paper='A3', title='', rev='', date=''):
        self.project, self.paper, self.title, self.rev, self.date = project, paper, title, rev, date
        self.uuid = uid()
        self.libs, self.used = {}, {}
        self.parts, self.wires, self.labels, self.noconnects, self.texts, self.extra_junctions = [], [], [], [], [], []
        self.pwr_n = 0

    def lib(self, nickname, path=None, text=None):
        self.libs[nickname] = SymLib(nickname, path, text)

    def symtext(self, lib_id):
        nick, name = lib_id.split(':', 1)
        return self.libs[nick].get(name)

    def add(self, lib_id, ref, value, x, y, rot=0, footprint='', lcsc='', fields=None, in_bom=True, on_board=True,
            dnp=False, mirror=None):
        """fields: extra properties (hidden). Keys starting with '_' are layout hints: _ref_at, _val_at (x, y),
        _just, _hide_value, _visible (list of field names shown under the value)."""
        t = self.symtext(lib_id)
        self.used[lib_id] = t
        f = dict(fields or {})
        if lcsc:
            f['LCSC'] = lcsc
        p = Part(self, lib_id, ref, value, x, y, rot, pin_list(t), f, footprint, in_bom, on_board, dnp, mirror)
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

    def hv(self, a, b):
        """L-shaped wire: horizontal first, then vertical."""
        self.wire(a, (b[0], a[1]), b)

    def vh(self, a, b):
        """L-shaped wire: vertical first, then horizontal."""
        self.wire(a, (a[0], b[1]), b)

    def label(self, name, x, y, rot=0, kind='label', shape='passive'):
        self.labels.append((kind, name, snap(x), snap(y), rot, shape))

    def nc(self, pt):
        self.noconnects.append((snap(pt[0]), snap(pt[1])))

    def text(self, s, x, y, size=1.27, bold=False):
        self.texts.append((s, snap(x), snap(y), size, bold))

    # ------------------------------------------------------------ geometry checks

    def _pin_points(self):
        return [(p, q, p.p(q['num'])) for p in self.parts for q in p.pins]

    def _junctions(self):
        ends = {}
        for a, b in self.wires:
            ends[a] = ends.get(a, 0) + 1
            ends[b] = ends.get(b, 0) + 1
        pin_pts = {pt for _, _, pt in self._pin_points()}
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
        out = ['pin %s.%s at %s lies on the interior of a wire (it connects to it)' % x for x in self.pin_on_wire_interior()]
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
        r = body_rect(self.symtext(p.lib_id))
        if r and p.rot == 0 and not p.mirror:
            x1, y1, x2, y2 = r
            left, top, bot = p.x + min(x1, x2), p.y - max(y1, y2), p.y - min(y1, y2)
            return left, top - 1.27, left, bot + 2.54, 0, 'left'
        return p.x + 3.81, p.y - 3.81, p.x + 3.81, p.y + 3.81, 90 if p.rot in (90, 270) else 0, 'left'

    def symbol_sexpr(self, p):
        props = [('Reference', p.ref), ('Value', p.value), ('Footprint', p.footprint), ('Datasheet', p.fields.get('Datasheet', ''))]
        props += [(k, v) for k, v in p.fields.items() if k != 'Datasheet' and not k.startswith('_') and k not in p.fields.get('_visible', [])]
        names = [k for k, _ in props]
        assert len(names) == len(set(names)), '%s: duplicate property names %s' % (p.ref, names)
        out = ['\t(symbol\n\t\t(lib_id %s)\n\t\t(at %s %s %s)\n%s\t\t(unit 1)\n\t\t(exclude_from_sim no)\n'
               '\t\t(in_bom %s)\n\t\t(on_board %s)\n\t\t(dnp %s)\n\t\t(uuid "%s")\n' % (
                   kstr(p.lib_id), p.x, p.y, p.rot, '\t\t(mirror %s)\n' % p.mirror if p.mirror else '',
                   'yes' if p.in_bom else 'no', 'yes' if p.on_board else 'no', 'yes' if p.dnp else 'no', p.uuid)]
        rx, ry, vx, vy, ang, just = self._field_spots(p)
        rx, ry = p.fields.get('_ref_at', (rx, ry))
        vx, vy = p.fields.get('_val_at', (vx, vy))
        just = p.fields.get('_just', just)
        for k, v in props:
            if k == 'Reference':
                out.append(property_sexpr(k, v, rx, ry, ang, just, p.ref.startswith('#')))
            elif k == 'Value':
                out.append(property_sexpr(k, v, vx, vy, ang, just, p.fields.get('_hide_value', p.lib_id == 'power:GND')))
            else:
                out.append(property_sexpr(k, v, p.x, p.y, ang, just, True))
        for i, k in enumerate(p.fields.get('_visible', [])):     # extra visible fields stacked under the value
            out.append(property_sexpr(k, p.fields[k], vx, vy + 2.54 * (i + 1), ang, just, False))
        for q in p.pins:
            out.append('\t\t(pin %s\n\t\t\t(uuid "%s")\n\t\t)\n' % (kstr(q['num']), uid()))
        out.append('\t\t(instances\n\t\t\t(project %s\n\t\t\t\t(path "/%s"\n\t\t\t\t\t(reference %s)\n'
                   '\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n' % (kstr(self.project), self.uuid, kstr(p.ref)))
        return ''.join(out)

    def split_wires(self):
        """The wires split at every pin point and wire end lying on their interior (T-taps become real joints)."""
        pts = {a for w in self.wires for a in w} | {pt for _, _, pt in self._pin_points()}
        out = []
        for a, b in self.wires:
            cuts = [pt for pt in pts if pt not in (a, b) and _on_interior(pt, a, b)]
            seq = sorted([a, b] + cuts, key=lambda q: (q[0] - a[0]) ** 2 + (q[1] - a[1]) ** 2)
            out += [(u, v) for u, v in zip(seq, seq[1:]) if u != v]
        return out

    def write(self, path):
        self.wires = self.split_wires()
        o = ['(kicad_sch\n\t(version 20260306)\n\t(generator "eeschema")\n\t(generator_version "10.0")\n',
             '\t(uuid "%s")\n\t(paper "%s")\n' % (self.uuid, self.paper),
             '\t(title_block\n\t\t(title %s)\n\t\t(date %s)\n\t\t(rev %s)\n\t)\n' % (kstr(self.title), kstr(self.date), kstr(self.rev)),
             '\t(lib_symbols\n']
        for lib_id, t in sorted(self.used.items()):
            o.append('\t\t' + embed(lib_id, t).replace('\n', '\n\t\t').rstrip('\t') + '\n')
        o.append('\t)\n')
        o += [junction_sexpr(pt) for pt in self._junctions()]
        o += [no_connect_sexpr(pt) for pt in self.noconnects]
        o += [wire_sexpr(a, b) for a, b in self.wires]
        o += [label_sexpr(*lb) for lb in self.labels]
        o += [text_sexpr(*tx) for tx in self.texts]
        o += [self.symbol_sexpr(p) for p in self.parts]
        o.append('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n\t(embedded_fonts no)\n)\n')
        open(path, 'w', encoding='utf-8').write(''.join(o))


def find_merges(sch, intended, symmetric=('R', 'C', 'L', 'FB', 'F')):
    """Union-find over the drawn geometry (wire ends, pin points, power symbols, labels). intended: {net: ['REF.PIN']}.
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
