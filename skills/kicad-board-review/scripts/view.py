# Render one copper layer of board.json in a window, nets coloured and labelled, with a coordinate grid.
#   python view.py board.json LAYER x0 y0 x1 y1 out.png [grid_mm] [--nets NET1,NET2]
# Use it to LOOK at what you changed: a clean DRC does not tell you a trace cuts a plane or a pour has a sliver.
# Ground is light grey, so cuts in it stand out. Then open the PNG with the Read tool and actually inspect it.
import sys, json, hashlib, math
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MP
from shapely.geometry import Polygon, box
args = [a for a in sys.argv[1:] if not a.startswith('--')]
only = None
if '--nets' in sys.argv: only = set(sys.argv[sys.argv.index('--nets') + 1].split(',')); args = [a for a in args if a != sys.argv[sys.argv.index('--nets') + 1]]
bj, L, x0, y0, x1, y1, out = args[0], args[1], *map(float, args[2:6]), args[6]
gstep = float(args[7]) if len(args) > 7 else 2.0
B = json.load(open(bj)); W = box(x0, y0, x1, y1)
def col(net):
    if only is not None and net not in only: return (0.93, 0.93, 0.93)
    if 'GND' in net: return (0.75, 0.75, 0.75)
    if net == '': return (0.9, 0.9, 0.5)
    h = int(hashlib.md5(net.encode()).hexdigest()[:6], 16)
    return (0.25 + 0.6 * ((h >> 16) & 255) / 255, 0.25 + 0.6 * ((h >> 8) & 255) / 255, 0.25 + 0.6 * (h & 255) / 255)
sc = 30 / max(x1 - x0, y1 - y0)
fig, ax = plt.subplots(figsize=(max((x1 - x0) * sc / 2.2, 3), max((y1 - y0) * sc / 2.2, 3)))
labels = []
short = lambda n: n.split('/')[-1]
for z in B['zones']:
    if z['keepout'] or L not in z['filled']: continue
    for ring, holes in z['filled'][L]:
        if len(ring) < 3: continue
        p = Polygon(ring, [h for h in holes if len(h) >= 3])
        if not p.is_valid: p = p.buffer(0)
        if not p.intersects(W): continue
        ax.add_patch(MP(ring, closed=True, fc=col(z['net']) + (0.55,), ec='none'))
        for h in holes: ax.add_patch(MP(h, closed=True, fc='white', ec='none'))
        ip = p.intersection(W)
        if ip.area > 1 and 'GND' not in z['net']: c = ip.representative_point(); labels.append((c.x, c.y, short(z['net']), 7, 'k'))
for t in B['tracks']:
    if t['layer'] != L: continue
    xs = [t['a'][0], t['b'][0]]; ys = [t['a'][1], t['b'][1]]
    if not (min(xs) < x1 and max(xs) > x0 and min(ys) < y1 and max(ys) > y0): continue
    lw = t['w'] * 72 / 25.4 * fig.get_size_inches()[0] / ((x1 - x0) / 25.4)
    pts = [t['a'], t['m'], t['b']] if t.get('arc') else [t['a'], t['b']]
    ax.plot([q[0] for q in pts], [q[1] for q in pts], '-', color=col(t['net']), lw=max(lw, 0.5), solid_capstyle='round')
    if math.dist(t['a'], t['b']) > 1.5 and 'GND' not in t['net']:
        labels.append(((t['a'][0] + t['b'][0]) / 2, (t['a'][1] + t['b'][1]) / 2, short(t['net']), 5, 'b'))
for f in B['footprints']:
    for p in f['pads']:
        if L not in p['layers'] or not (x0 <= p['x'] <= x1 and y0 <= p['y'] <= y1): continue
        for ring, holes in p['poly']: ax.add_patch(MP(ring, closed=True, fc=col(p['net']), ec='k', lw=0.3))
    if x0 <= f['x'] <= x1 and y0 <= f['y'] <= y1 and any(L in p['layers'] for p in f['pads']):
        labels.append((f['x'], f['y'], f['ref'], 7, 'r'))
for v in B['vias']:
    if x0 <= v['x'] <= x1 and y0 <= v['y'] <= y1:
        ax.add_patch(plt.Circle((v['x'], v['y']), v['size'] / 2, fc=col(v['net']), ec='k', lw=0.3))
for x, y, s, fs, c in labels: ax.text(x, y, s, fontsize=fs, color=c, ha='center', va='center')
ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.set_aspect('equal')
ax.set_xticks(np.arange(math.ceil(x0 / gstep) * gstep, x1, gstep)); ax.set_yticks(np.arange(math.ceil(y0 / gstep) * gstep, y1, gstep))
ax.tick_params(labelsize=6); ax.grid(True, lw=0.2); ax.set_title(L, fontsize=9)
fig.tight_layout(); fig.savefig(out, dpi=110); print(out)
