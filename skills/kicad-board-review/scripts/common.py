# Shared loading and geometry helpers for the analysis scripts (run in a venv with numpy, scipy, shapely>=2, matplotlib).
# Every script takes the pack directory as its first argument; it must hold board.json (boarddump.py), netlist.json
# (netdigest.py) and review_config.json (written by hand per board, see assets/review_config.example.json).
import json, math, re, os, sys, collections
import numpy as np
import shapely
from shapely.geometry import Polygon, LineString, Point, MultiPolygon, box
from shapely.ops import unary_union

PACK = os.path.abspath(sys.argv[1]) + os.sep if len(sys.argv) > 1 else os.getcwd() + os.sep
B = json.load(open(os.environ.get('BOARD', PACK + 'board.json')))
NL = json.load(open(PACK + 'netlist.json')) if os.path.exists(PACK + 'netlist.json') else dict(components={}, nets={})
CFG = json.load(open(PACK + 'review_config.json')) if os.path.exists(PACK + 'review_config.json') else {}
LAYERS = B['layers']
FP = {f['ref']: f for f in B['footprints']}
NETS = NL['nets']
# Coverage warnings: anything a script could not classify, fell back to a default for, or skipped goes here, and every
# report prints them at the top. "Nothing found" is only a pass when the coverage says the inputs were seen.
WARN = []
if not CFG: WARN.append('no review_config.json in the pack: built-in defaults used (ground from the netlist, name-pattern classes, no hot loops configured, no power runs)')
elif CFG.get('starter'): WARN.append('review_config.json is the STARTER written by make_pack.sh/topology.py: its derived entries are unreviewed and it has no power runs')
from topology import Topology
TOPO = Topology(NL, CFG) if NETS else None
if TOPO is None: WARN.append('no netlist.json: nothing derived from topology (switch nodes, hot loops, ground)')
else: WARN += TOPO.warnings + ['underived: ' + u for u in TOPO.underived]
GND = set(CFG.get('ground_nets') or (TOPO.ground if TOPO and TOPO.ground else ['GND']))
if not CFG.get('ground_nets'): WARN.append('ground_nets not configured: using %s (%s)' % (sorted(GND), 'derived from the netlist' if TOPO and TOPO.ground else 'built-in default'))
_routed = {t['net'] for t in B['tracks']} | {z['net'] for z in B['zones'] if not z['keepout']} | {p['net'] for f in B['footprints'] for p in f['pads']}
if not GND & _routed: WARN.append('none of the ground nets %s has copper on the board: every ground-based check (reference planes, stitching, slots, hot-loop returns) is empty' % sorted(GND))

# stackup: copper thickness and z of each copper layer, dielectric height to the nearest copper neighbours
def _stack():
    z, out, prev = 0.0, {}, None
    st = B.get('stackup') or []
    for s in st:
        if s['type'] == 'copper':
            out[s['name']] = dict(z=z, t=s['thickness_mm'] or 0.035)
            z += s['thickness_mm'] or 0.035
        else:
            z += s['thickness_mm']
    if not out:   # no stackup in the file: assume 1.6 mm, 1 oz everywhere
        n = len(LAYERS)
        out = {L: dict(z=1.6 * i / max(n - 1, 1), t=0.035) for i, L in enumerate(LAYERS)}
    er = [s['er'] for s in st if s.get('er')]
    return out, (sum(er) / len(er) if er else 4.5)
STACK, ER = _stack()
def neighbours(L):
    """copper layers adjacent to L in the stackup, nearest first, with the dielectric height (mm)"""
    zs = sorted(LAYERS, key=lambda l: STACK[l]['z'])
    i = zs.index(L); out = []
    for j in (i - 1, i + 1):
        if 0 <= j < len(zs):
            o = zs[j]
            h = abs(STACK[o]['z'] - STACK[L]['z']) - (STACK[o]['t'] if j < i else STACK[L]['t'])
            out.append((o, max(h, 0.01)))
    return sorted(out, key=lambda t: t[1])

def polys(pl):
    out = []
    for ring, holes in pl:
        if len(ring) < 3: continue
        p = Polygon(ring, [h for h in holes if len(h) >= 3])
        if not p.is_valid: p = p.buffer(0)
        out.append(p)
    return out

EDGE = unary_union(polys(B['edge']))

def track_geom(t):
    if t.get('arc'):
        return LineString([t['a'], t['m'], t['b']]).buffer(t['w'] / 2, 8)
    if t['a'] == t['b']: return Point(t['a']).buffer(t['w'] / 2, 8)
    return LineString([t['a'], t['b']]).buffer(t['w'] / 2, 8)

def rect_dims(g):
    """(length, width) of a shape's minimum rotated rectangle"""
    mrr = g.minimum_rotated_rectangle
    if mrr.geom_type != 'Polygon': return 0.0, 0.0
    xs, ys = mrr.exterior.xy
    e = sorted({round(math.dist((xs[i], ys[i]), (xs[i + 1], ys[i + 1])), 2) for i in range(4)})
    return max(e), min(e)

def seg_len(t):
    return math.dist(t['a'], t['m']) + math.dist(t['m'], t['b']) if t.get('arc') else math.dist(t['a'], t['b'])

_zone_cache = {}
def zone_fill(net, layer):
    k = (net, layer)
    if k not in _zone_cache:
        ps = []
        for z in B['zones']:
            if z['keepout'] or z['net'] != net: continue
            if layer in z['filled']: ps += polys(z['filled'][layer])
        _zone_cache[k] = unary_union(ps) if ps else Polygon()
    return _zone_cache[k]

def all_zone_fill(layer):
    nets = {z['net'] for z in B['zones'] if not z['keepout'] and layer in z['filled']}
    return {n: zone_fill(n, layer) for n in nets}

def pad_geoms(net=None, layer=None):
    for f in B['footprints']:
        for p in f['pads']:
            if net is not None and p['net'] != net: continue
            if layer is not None and layer not in p['layers']: continue
            ps = polys(p['poly'])
            if ps: yield f, p, unary_union(ps)

def copper(net, layer):
    g = [zone_fill(net, layer)]
    g += [track_geom(t) for t in B['tracks'] if t['net'] == net and t['layer'] == layer]
    g += [pg for _, _, pg in pad_geoms(net, layer)]
    g += [Point(v['x'], v['y']).buffer(v['size'] / 2, 8) for v in B['vias'] if v['net'] == net]
    return unary_union([x for x in g if not x.is_empty])

def natkey(s): return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]

def refpad(s):
    """'U1:7' -> ('U1', '7')"""
    r, p = s.split(':', 1); return r, p

# net classification from review_config.json: first matching rule wins
_rules = [(re.compile(r['match']), r['class']) for r in CFG.get('net_classes', [])]
FAST = set(CFG.get('fast_classes', ['usb', 'clock', 'spi', 'qspi', 'switch', 'ethernet', 'hdmi', 'lvds', 'ddr']))
def cls_how(n):
    """(class, how it was decided). Order: ground, an explicit net_classes rule, a switch node derived from the netlist
    (inductor + switch pin / active part with no capacitor to ground), the built-in power-name pattern, else 'slow'."""
    if n == '' or n in GND: return 'power', 'ground'
    for i, (rx, c) in enumerate(_rules):
        if rx.search(n): return c, 'rule %d' % (i + 1)
    if TOPO and n in TOPO.switch_nodes: return 'switch', 'derived: ' + TOPO.switch_nodes[n]['why']
    if re.search(r'(^|[^A-Z])(GND|VCC|VDD|VIN|VBUS|VSYS|\+\d|\d+V\d*$|3V3|5V)', n): return 'power', 'power-name default'
    return 'slow', 'fell through'
def cls(n): return cls_how(n)[0]
if TOPO:
    for n, e in TOPO.switch_nodes.items():
        c, how = cls_how(n)
        if c != 'switch': WARN.append('%s is a switch node (%s) but %s classes it "%s": its copper, crosstalk and reference checks use that class' % (n, e['why'], how, c))
    if TOPO.switch_nodes and 'switch' not in FAST: WARN.append('"switch" is not in fast_classes: switch nodes get no crosstalk/reference checks')

def classification_coverage():
    """per class: the routed nets in it and how they got there; the 'slow' ones are what the SI checks skip"""
    rows = collections.defaultdict(list)
    tl = collections.Counter()
    for t in B['tracks']: tl[t['net']] += seg_len(t)
    for n in sorted({t['net'] for t in B['tracks']}, key=natkey):
        c, how = cls_how(n); rows[c].append(dict(net=n, how=how, track_mm=round(tl[n], 1)))
    return {c: sorted(v, key=lambda r: -r['track_mm']) for c, v in rows.items()}

_UNIT = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, '\u00b5': 1e-6, 'm': 1e-3, '': 1.0, 'k': 1e3, 'M': 1e6}
def parse_value(s):
    """'4.7uF' / '100n' / '1u 25V' / '2R2' -> float in base units (None if not a number)"""
    m = re.match(r'\s*([\d.]+)\s*([pnu\u00b5mkM]?)', (s or '').replace('R', '.') if re.match(r'^\d+R\d', s or '') else (s or ''))
    if not m: return None
    try: return float(m.group(1)) * _UNIT[m.group(2)]
    except ValueError: return None
