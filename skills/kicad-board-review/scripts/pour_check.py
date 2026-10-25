# Quick plane checks to run right after a zone, pour, via-field or placement edit (seconds, not the full pack):
#   python pour_check.py BOARD.kicad_pcb [--window x0,y0,x1,y1] [--min-area 0.5] [--min-vias 2]
#   python pour_check.py PACK [...]                     (a pack whose board.json is current)
# BOARD mode copies the board (and its .kicad_pro) to a temporary folder, refills the zones there with kicad-cli
# (never the original), dumps it with KiCad's python and checks the copy.
#  1. Every pour piece has at least --min-vias vias (or plated holes) of its own net that land on that net's copper on
#     another layer (its plane). A piece with one is WEAK, with none ISOLATED. Pieces of nets that have no copper on any
#     other layer are counted, not judged. A grid stitcher skips spots that collide with tracks, so a pour piece lying
#     under a bundle of lanes, or a sliver created by a new part, ends with one via or none: this is where it shows.
#  2. Tracks over nothing: every signal track in the window whose nearest copper layer has no copper under it for
#     0.15 mm or more (a reference strip that stops at the layer-change vias leaves the stubs over the gap).
# Exit 1 if anything is found. It does not replace the pack (planes.py, emc.py): it is the check after each edit.
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if len(sys.argv) > 1 and sys.argv[1].endswith('.kicad_pcb'):
    src = os.path.abspath(sys.argv[1]); tmp = tempfile.mkdtemp(prefix='pour_check_')
    name = os.path.basename(src)
    shutil.copy(src, os.path.join(tmp, name))
    pro = os.path.splitext(src)[0] + '.kicad_pro'
    if os.path.exists(pro): shutil.copy(pro, os.path.join(tmp, os.path.basename(pro)))
    sys.path.insert(0, HERE)
    from interp import kicad_python
    cli = os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
    r = subprocess.run([cli, 'pcb', 'drc', '--refill-zones', '--save-board', '--format', 'json', '-o', os.path.join(tmp, 'drc.json'),
                        os.path.join(tmp, name)], capture_output=True, text=True)
    if not os.path.exists(os.path.join(tmp, 'drc.json')):
        sys.exit('kicad-cli could not refill the copy (%s): stopping - checking stale fills would look like a pass' % (r.stderr or r.stdout)[-300:])
    kpy = kicad_python()
    if not kpy: sys.exit('no KiCad python with pcbnew (set KICAD_PYTHON)')
    r = subprocess.run([kpy, os.path.join(HERE, 'boarddump.py'), os.path.join(tmp, name), tmp], capture_output=True, text=True)
    if not os.path.exists(os.path.join(tmp, 'board.json')):
        sys.exit('boarddump.py failed: %s' % r.stderr[-300:])
    sys.argv[1] = tmp
from common import *  # noqa: E402

args = sys.argv[2:]
def opt(k, d):
    return args[args.index(k) + 1] if k in args else d
WIN = box(*map(float, opt('--window', None).split(','))) if '--window' in args else None
MIN_A = float(opt('--min-area', 0.5)); MIN_V = int(opt('--min-vias', 2))
_cu, _land = {}, {}
def copper_c(net, L):
    if (net, L) not in _cu: _cu[(net, L)] = copper(net, L)
    return _cu[(net, L)]
def landing(net, L):
    """the net's copper on L that a via can land on: fills, tracks and pads (not the vias' own rings)"""
    if (net, L) not in _land:
        g = [zone_fill(net, L)] + [track_geom(t) for t in B['tracks'] if t['net'] == net and t['layer'] == L]
        g += [pg for _, _, pg in pad_geoms(net, L)]
        _land[(net, L)] = unary_union([x for x in g if not x.is_empty])
    return _land[(net, L)]
holes = [(v['x'], v['y'], v['net']) for v in B['vias']] + [(p['x'], p['y'], p['net']) for f in B['footprints'] for p in f['pads'] if p['th']]
found, local, checked = [], set(), 0
for L in LAYERS:
    nets = sorted({z['net'] for z in B['zones'] if not z['keepout'] and L in z['filled'] and z['net']}, key=natkey)
    for net in nets:
        zf = zone_fill(net, L)
        if zf.is_empty: continue
        others = [L2 for L2 in LAYERS if L2 != L and not landing(net, L2).is_empty]
        g = copper_c(net, L)
        for pc in (g.geoms if hasattr(g, 'geoms') else [g]):
            fill = pc.intersection(zf).area
            if fill < MIN_A or (WIN is not None and not pc.intersects(WIN)): continue
            if not others: local.add(net); continue
            checked += 1
            shapely.prepare(pc)
            n = 0
            for x, y, hn in holes:
                if hn != net or not pc.contains(Point(x, y)): continue
                if any(landing(net, L2).intersects(Point(x, y)) for L2 in others): n += 1
            if n < MIN_V:
                c = pc.representative_point()
                found.append('%s %s pour piece on %s, %.1f mm^2 at (%.2f, %.2f) bbox %s: %d via(s) to its plane (%s), %d needed' % (
                    'ISOLATED' if n == 0 else 'WEAK    ', net, L, fill, c.x, c.y, [round(v, 1) for v in pc.bounds], n, ', '.join(others), MIN_V))
# tracks over nothing on the nearest copper layer (the plane's own antipad around the track's via or plated pad is not
# a gap: a span that touches it and is shorter than 1.6 mm is the expected entry, as in emc.py)
_own = collections.defaultdict(list)
for f in B['footprints']:
    for p in f['pads']:
        if p['th'] and p['net']: _own[p['net']].append(Point(p['x'], p['y']).buffer(max(p['drill'], 0.3) / 2 + 1.0))
for v in B['vias']: _own[v['net']].append(Point(v['x'], v['y']).buffer(v['drill'] / 2 + 0.6))
_own = {k: unary_union(v) for k, v in _own.items()}
void = []
for t in B['tracks']:
    if t['net'] in GND or t['a'] == t['b'] or (WIN is not None and not track_geom(t).intersects(WIN)): continue
    nb = neighbours(t['layer'])
    if not nb: continue
    ref = nb[0][0]
    under = unary_union([g for g in all_zone_fill(ref).values() if not g.is_empty])
    a, b = np.array(t['a']), np.array(t['b']); d = float(np.linalg.norm(b - a)); k = max(int(d / 0.05), 1)
    P = a[None, :] + (b - a)[None, :] * np.linspace(0, 1, k + 1)[:, None]
    ok = shapely.contains_xy(under, P[:, 0], P[:, 1]) if not under.is_empty else np.zeros(len(P), bool)
    i = 0
    while i < len(ok):
        if ok[i]: i += 1; continue
        j = i
        while j + 1 < len(ok) and not ok[j + 1]: j += 1
        span = (j - i) * d / k
        seg = LineString([P[i], P[j]]) if j > i else Point(P[i])
        entry = t['net'] in _own and seg.distance(_own[t['net']]) < 0.05 and span < 1.6
        if span >= 0.15 and not entry:
            void.append('OVER VOID %s on %s: %.2f mm with no copper on %s from (%.2f, %.2f) to (%.2f, %.2f)' % (
                t['net'], t['layer'], span, ref, P[i, 0], P[i, 1], P[j, 0], P[j, 1]))
        i = j + 1
for line in found + void: print(line)
print('%d pour piece(s) checked%s: %d weak or isolated (fewer than %d vias to their plane); %d track span(s) over nothing; '
      'nets with no copper on another layer (not judged): %s' % (checked, ' in the window' if WIN is not None else '', len(found),
                                                                MIN_V, len(void), ', '.join(sorted(local, key=natkey)) or 'none'))
sys.exit(1 if found or void else 0)
