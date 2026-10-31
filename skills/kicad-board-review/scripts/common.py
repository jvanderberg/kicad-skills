# Shared loading and geometry helpers for the analysis scripts (run in a venv with numpy, scipy, shapely>=2, matplotlib).
# Every script takes the pack directory as its first argument; it must hold board.json (boarddump.py), netlist.json
# (netdigest.py) and review_config.json (written by hand per board, see assets/review_config.example.json).
import json, math, re, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from interp import need; need('numpy', 'scipy', 'shapely')   # started with plain python3: re-run under the venv
import numpy as np
import shapely
from shapely.geometry import Polygon, LineString, Point, MultiPolygon, box
from shapely.ops import unary_union

PACK = os.path.abspath(sys.argv[1]) + os.sep if len(sys.argv) > 1 else os.getcwd() + os.sep
B = json.load(open(os.environ.get('BOARD', PACK + 'board.json')))
NL = json.load(open(PACK + 'netlist.json')) if os.path.exists(PACK + 'netlist.json') else dict(components={}, nets={})
CFG = json.load(open(PACK + 'review_config.json')) if os.path.exists(PACK + 'review_config.json') else {}


def _diff_pairs(cfg):
    """review_config "diff_pairs" as [{nets: [a, b], target_ohm}]; anything else is a config error that says the forms"""
    out = []
    for i, pr in enumerate(cfg.get('diff_pairs') or []):
        nets = pr.get('nets') if isinstance(pr, dict) else pr
        extra = sorted(set(pr) - {'nets', 'target_ohm'}) if isinstance(pr, dict) else []
        if not (isinstance(nets, list) and len(nets) == 2 and all(isinstance(n, str) for n in nets)) or extra:
            raise SystemExit('review_config.json diff_pairs entry %d is %s: write ["NET_P", "NET_N"] or {"nets": ["NET_P", '
                             '"NET_N"], "target_ohm": 90}%s' % (i + 1, json.dumps(pr), ' (unknown keys: %s)' % ', '.join(extra) if extra else ''))
        out.append(dict(nets=nets, target_ohm=pr.get('target_ohm') if isinstance(pr, dict) else None))
    return out


DIFF_PAIRS = _diff_pairs(CFG)
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
    missing = [L for L in LAYERS if L not in out]
    if missing:   # no stackup in the file, or one that does not name these layers: assume 1.6 mm, 1 oz everywhere
        if out:
            WARN.append('stackup does not name copper layer(s) %s (stackup has %s; a board.json from an older boarddump.py '
                        'used user layer names: re-run make_pack.sh): assumed 1.6 mm, 1 oz, evenly spaced' % (missing, list(out)))
        n = len(LAYERS)
        out = {L: dict(z=1.6 * i / max(n - 1, 1), t=0.035) for i, L in enumerate(LAYERS)}
    er = [s['er'] for s in st if s.get('er')]
    return out, (sum(er) / len(er) if er else 4.5)
STACK, ER = _stack()
LAYER_NAMES = B.get('layer_names') or {}     # canonical -> the board's own name, when it renames a layer
def layer_key(name):
    """a layer named in review_config.json, canonical (F.Cu) or the board's own name (Top Layer) -> its canonical name"""
    return name if name in LAYERS else next((c for c, u in LAYER_NAMES.items() if u == name), name)
def layer_label(L):
    u = LAYER_NAMES.get(L)
    return '%s (%s)' % (L, u) if u and u != L else L
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

def centreline(t):
    """a track's centreline: its segment, or an arc as a polyline within 1 um of the true arc"""
    if not t.get('arc'): return LineString([t['a'], t['b']])
    (ax, ay), (mx, my), (bx, by) = t['a'], t['m'], t['b']
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-9: return LineString([t['a'], t['b']])
    s2 = lambda x, y: x * x + y * y
    cx = (s2(ax, ay) * (my - by) + s2(mx, my) * (by - ay) + s2(bx, by) * (ay - my)) / d
    cy = (s2(ax, ay) * (bx - mx) + s2(mx, my) * (ax - bx) + s2(bx, by) * (mx - ax)) / d
    r = math.hypot(ax - cx, ay - cy)
    t0, tm, t1 = (math.atan2(y - cy, x - cx) for x, y in (t['a'], t['m'], t['b']))
    sw = (t1 - t0) % (2 * math.pi)
    if (tm - t0) % (2 * math.pi) > sw: sw -= 2 * math.pi        # the way round that passes through the mid point
    n = min(max(math.ceil(abs(sw) / (2 * math.acos(1 - 0.001 / r))) if r > 0.001 else 2, 2), 720)
    pts = [(cx + r * math.cos(t0 + sw * i / n), cy + r * math.sin(t0 + sw * i / n)) for i in range(n + 1)]
    return LineString([tuple(t['a'])] + pts[1:-1] + [tuple(t['b'])])

def track_geom(t):
    if t['a'] == t['b'] and not t.get('arc'): return Point(t['a']).buffer(t['w'] / 2, 8)
    return centreline(t).buffer(t['w'] / 2, 8)

def rect_dims(g):
    """(length, width) of a shape's minimum rotated rectangle"""
    mrr = g.minimum_rotated_rectangle
    if mrr.geom_type != 'Polygon': return 0.0, 0.0
    xs, ys = mrr.exterior.xy
    e = sorted({round(math.dist((xs[i], ys[i]), (xs[i + 1], ys[i + 1])), 2) for i in range(4)})
    return max(e), min(e)

def seg_len(t):
    return centreline(t).length if t.get('arc') else math.dist(t['a'], t['b'])

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

_SPANLESS = [v for v in B['vias'] if v.get('type_name') not in (None, 'through') and not v.get('layers')]
SPAN_WARNING = ('%d blind/buried/micro vias with no layer span in board.json (an older boarddump.py), treated as through '
                'vias (they may join layers they do not reach): re-run make_pack.sh' % len(_SPANLESS)) if _SPANLESS else None
if SPAN_WARNING: WARN.append(SPAN_WARNING)

def via_span(v):
    """the copper layers a via joins, top to bottom: the run between the outermost layers board.json records for it
    (all of them for a through via, or one without a record)"""
    ix = sorted(LAYERS.index(L) for L in v.get('layers') or () if L in LAYERS)
    return LAYERS[ix[0]:ix[-1] + 1] if ix else list(LAYERS)

def copper(net, layer):
    """a net's copper on one layer, merged: fill, tracks, pads and the vias that span the layer"""
    g = [zone_fill(net, layer)]
    g += [track_geom(t) for t in B['tracks'] if t['net'] == net and t['layer'] == layer]
    g += [pg for _, _, pg in pad_geoms(net, layer)]
    g += [Point(v['x'], v['y']).buffer(v['size'] / 2, 8) for v in B['vias'] if v['net'] == net and layer in via_span(v)]
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

# every configured pattern and named object must match something on this board: a pattern for a net name that does
# not exist leaves the nets it was meant for unclassified, silently (R16)
_ALL_NETS = set(NETS) | {t['net'] for t in B['tracks']} | {p['net'] for f in B['footprints'] for p in f['pads']}
for i, r in enumerate(CFG.get('net_classes', [])):
    rx = _rules[i][0]
    if not any(rx.search(n) for n in _ALL_NETS if n):
        WARN.append('net_classes rule %d "%s" (class %s) matched 0 nets: the nets it was written for are unclassified '
                    '(renamed? typo? sheet prefix "/"?)' % (i + 1, r['match'], r['class']))
for pr in DIFF_PAIRS:
    pr = pr['nets']
    gone = [n for n in pr if n not in _ALL_NETS]
    if gone: WARN.append('diff_pairs %s: %s not on this board - the pair is not checked' % (' / '.join(pr), ', '.join(gone)))
if TOPO:
    _cx = collections.defaultdict(set)
    for n, nodes in NETS.items():
        for r, *_ in nodes:
            if TOPO.kind.get(r) == 'connector': _cx[n].add(r)
    _slow_cx = sorted((n for n in _cx if n and not n.startswith('unconnected-') and cls_how(n)[1] == 'fell through'), key=natkey)
    if _slow_cx:
        WARN.append('%d net(s) that reach a connector fell through to "slow" (no reference, crosstalk or edge checks; a cable '
                    'makes them antennas and ESD entry points): %s - classify each one (its interface speed from the '
                    'chip\'s datasheet, or "slow_ext" on purpose)' % (len(_slow_cx), ', '.join('%s (%s)' % (n, ','.join(sorted(_cx[n]))) for n in _slow_cx[:20])))

def classification_coverage():
    """per class: the routed nets in it and how they got there; the 'slow' ones are what the SI checks skip"""
    rows = collections.defaultdict(list)
    tl = collections.Counter()
    for t in B['tracks']: tl[t['net']] += seg_len(t)
    for n in sorted({t['net'] for t in B['tracks']}, key=natkey):
        c, how = cls_how(n); rows[c].append(dict(net=n, how=how, track_mm=round(tl[n], 1)))
    return {c: sorted(v, key=lambda r: -r['track_mm']) for c, v in rows.items()}

# ---- transmission-line estimates (closed form; zero-thickness copper over the nearest plane)
C_MM_NS = 299.792458
def microstrip(w, h, er=None):
    """(Z0 ohm, effective permittivity) of a microstrip, Hammerstad"""
    er = ER if er is None else er
    u = w / h
    if u < 1:
        ee = (er + 1) / 2 + (er - 1) / 2 * ((1 + 12 / u) ** -0.5 + 0.04 * (1 - u) ** 2)
        return 60 / math.sqrt(ee) * math.log(8 / u + u / 4), ee
    ee = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / u) ** -0.5
    return 120 * math.pi / (math.sqrt(ee) * (u + 1.393 + 0.667 * math.log(u + 1.444))), ee
def nh_per_mm(w, h, er=None):
    """loop inductance per mm of a track over its plane: Z0 x sqrt(eps_eff) / c (about 0.2-0.4 nH/mm for outer-layer
    tracks over a close plane; the free-wire ~1 nH/mm figure overstates it 3-4x)"""
    z0, ee = microstrip(w, h, er)
    return z0 * math.sqrt(ee) / C_MM_NS
def via_nh(span_mm, drill_mm):
    """partial inductance of a via barrel over span_mm (0.2 h (ln(4h/d) + 1) nH, h and d in mm)"""
    if span_mm <= 0: return 0.0
    return 0.2 * span_mm * (math.log(4 * span_mm / drill_mm) + 1)
def zdiff_edge(z0, s, h):
    """edge-coupled microstrip differential impedance from the single-ended Z0 (IPC-2141 form)"""
    return 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))
def cpwg(w, g, h, er=None):
    """(Z0, eps_eff) of a grounded coplanar line: width w, gap g to same-layer ground each side, plane h below"""
    from scipy.special import ellipk
    er = ER if er is None else er
    K = lambda k: ellipk(k * k)
    k1 = w / (w + 2 * g); k1p = math.sqrt(1 - k1 * k1)
    k3 = math.tanh(math.pi * w / (4 * h)) / math.tanh(math.pi * (w + 2 * g) / (4 * h)); k3p = math.sqrt(1 - k3 * k3)
    q = K(k3) / K(k3p) * K(k1p) / K(k1)
    ee = (1 + er * q) / (1 + q)
    return 60 * math.pi / math.sqrt(ee) / (K(k1) / K(k1p) + K(k3) / K(k3p)), ee

_UNIT = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, '\u00b5': 1e-6, 'm': 1e-3, '': 1.0, 'k': 1e3, 'M': 1e6}
def parse_value(s):
    """'4.7uF' / '100n' / '1u 25V' / '2R2' -> float in base units (None if not a number)"""
    m = re.match(r'\s*([\d.]+)\s*([pnu\u00b5mkM]?)', (s or '').replace('R', '.') if re.match(r'^\d+R\d', s or '') else (s or ''))
    if not m: return None
    try: return float(m.group(1)) * _UNIT[m.group(2)]
    except ValueError: return None
