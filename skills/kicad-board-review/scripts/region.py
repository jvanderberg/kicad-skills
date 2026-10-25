# List pads, zone outlines, tracks and vias inside a box on one layer, with exact coordinates.
#   python region.py PACK LAYER x0 y0 x1 y1
# Use before placing or routing anything: find free space from real numbers, not from eyeballing a render.
from common import *
L = sys.argv[2]; x0, y0, x1, y1 = map(float, sys.argv[3:7]); W = box(x0, y0, x1, y1)
for f in B['footprints']:
    for p in f['pads']:
        if L in p['layers']:
            g = unary_union(polys(p['poly']))
            if g.intersects(W):
                print('PAD  %-6s %-3s %-20s x %.2f-%.2f y %.2f-%.2f%s' % (f['ref'], p['num'], p['net'][:20], g.bounds[0], g.bounds[2], g.bounds[1], g.bounds[3], ' TH' if p['th'] else ''))
for z in B['zones']:
    if L in z['layers']:
        for ring, _ in z['outline']:                     # every outline polygon of the zone, not only the first
            if len(ring) < 3: continue
            if Polygon(ring).intersects(W): print('%s %-16s prio %s outline %s' % ('KEEP' if z['keepout'] else 'ZONE', z['net'][:16] or z['name'], z['prio'], [[round(c, 2) for c in q] for q in ring]))
for t in B['tracks']:
    if t['layer'] == L and track_geom(t).intersects(W):
        print('TRK  %-20s %s -> %s w %.2f' % (t['net'][:20], [round(c, 2) for c in t['a']], [round(c, 2) for c in t['b']], t['w']))
for v in B['vias']:
    if W.contains(Point(v['x'], v['y'])): print('VIA  %-20s %.2f %.2f %.2f/%.2f' % (v['net'][:20], v['x'], v['y'], v['size'], v['drill']))
