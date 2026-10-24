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
GND = set(CFG.get('ground_nets', ['GND']))

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
def cls(n):
    if n == '' or n in GND: return 'power'
    for rx, c in _rules:
        if rx.search(n): return c
    if re.search(r'(^|[^A-Z])(GND|VCC|VDD|VIN|VBUS|VSYS|\+\d|\d+V\d*$|3V3|5V)', n): return 'power'
    return 'slow'
