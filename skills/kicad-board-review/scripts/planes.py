# Plane summary: copper coverage per layer and net, ground-plane pieces, slots (and what cuts them), stitching density,
# edge stitching gaps, weakly stitched ground islands. Writes PACK/planes.json.   python planes.py PACK
# A hole in a ground pour is split into what fills it: another net's pour (reported as a pour, with its own area - a
# deliberate shape, not a cut) and the slots that remain once that pour and its clearance are taken out, each slot with
# its own size and contents. The bounding box of a merged hole is never reported as one slot.
from common import *

board_area = EDGE.area
out = dict(board_area_mm2=board_area, bbox=B['edge_bbox'], layers={})
for L in LAYERS:
    rows = []
    for net, g in sorted(all_zone_fill(L).items(), key=lambda kv: -kv[1].area):
        if g.is_empty: continue
        pieces = list(g.geoms) if hasattr(g, 'geoms') else [g]
        rows.append(dict(net=net, area_mm2=round(g.area, 1), pct=round(100 * g.area / board_area, 1), pieces=len(pieces), bbox=[round(v, 1) for v in g.bounds]))
    tr = collections.defaultdict(float)
    for t in B['tracks']:
        if t['layer'] == L: tr[t['net']] += seg_len(t)
    out['layers'][L] = dict(zones=rows, track_mm_total=round(sum(tr.values()), 1), track_nets=len(tr),
                            longest_tracks=sorted(([n, round(v, 1)] for n, v in tr.items()), key=lambda r: -r[1])[:15])

gvias = [(v['x'], v['y']) for v in B['vias'] if v['net'] in GND]
gpads_th = [(p['x'], p['y']) for f in B['footprints'] for p in f['pads'] if p['net'] in GND and p['th']]
stitch = shapely.points(np.array(gvias + gpads_th)) if gvias + gpads_th else shapely.points(np.zeros((0, 2)))
def what_is_inside(hole, L):
    nets = collections.Counter()
    for t in B['tracks']:
        if t['layer'] == L and hole.intersects(track_geom(t)): nets[t['net']] += 1
    vs = collections.Counter(v['net'] for v in B['vias'] if hole.contains(Point(v['x'], v['y'])))
    ps = collections.Counter(f['ref'] for f in B['footprints'] for p in f['pads'] if p['th'] and hole.contains(Point(p['x'], p['y'])))
    zn = [n for n, g in all_zone_fill(L).items() if n not in GND and not g.is_empty and g.intersects(hole.buffer(-0.05))]
    return dict(tracks=dict(nets), vias=dict(vs), th_pads=dict(ps), other_zones=zn)
ZCLR = {}
for z in B['zones']:
    if not z['keepout']: ZCLR[z['net']] = max(ZCLR.get(z['net'], 0), z.get('clearance') or 0)
def rect_dims(g):
    mrr = g.minimum_rotated_rectangle
    if mrr.geom_type != 'Polygon': return 0.0, 0.0
    xs, ys = mrr.exterior.xy
    e = sorted({round(math.dist((xs[i], ys[i]), (xs[i + 1], ys[i + 1])), 2) for i in range(4)})
    return max(e), min(e)
def split_hole(hp, L):
    """(other-net pours inside the hole, slot pieces left after removing them plus clearance)"""
    pours, cut = [], []
    for n, g in all_zone_fill(L).items():
        if n in GND or g.is_empty: continue
        inside = g.intersection(hp)
        if inside.area < 0.5: continue
        clr = max([ZCLR.get(n, 0)] + [ZCLR.get(x, 0) for x in GND] + [0.2]) + 0.15   # zone clearance (0.2 if unknown) + margin
        pours.append(dict(net=n, area_mm2=round(inside.area, 1), bbox=[round(v, 1) for v in inside.bounds]))
        cut.append(inside.buffer(clr, 4))
    rest = hp.difference(unary_union(cut)) if cut else hp
    slots = []
    for sp_ in (list(rest.geoms) if hasattr(rest, 'geoms') else [rest]):
        if sp_.is_empty or sp_.area < 1.0: continue
        ln, wd = rect_dims(sp_)
        fill = sp_.area / max(sp_.minimum_rotated_rectangle.area, 1e-9)
        # a compact hole is a slot (length x width); a thin branching shape is a network of track corridors, whose
        # real size is its mean width (2A/P) and total corridor length (P/2), not its bounding box
        shape = 'slot' if fill > 0.4 else 'corridor network'
        ins = what_is_inside(sp_, L)
        if cut and not (ins['tracks'] or ins['vias'] or ins['th_pads']) and 2 * sp_.area / sp_.length < 0.5:
            continue                    # the clearance ring left around a removed pour, not a cut
        e = dict(shape=shape, area_mm2=round(sp_.area, 1), length_mm=ln, width_mm=wd, bbox=[round(v, 1) for v in sp_.bounds],
                 inside=ins if ln > 3 else None)
        if shape != 'slot': e.update(mean_width_mm=round(2 * sp_.area / sp_.length, 2), corridor_mm=round(sp_.length / 2, 1))
        slots.append(e)
    return sorted(pours, key=lambda p: -p['area_mm2']), sorted(slots, key=lambda h: -h['length_mm'])
gnd = {}
for L in LAYERS:
    g = unary_union([zone_fill(n, L) for n in GND])
    pieces = [p for p in (list(g.geoms) if hasattr(g, 'geoms') else [g]) if not p.is_empty]
    P = []
    for p in sorted(pieces, key=lambda p: -p.area):
        holes, pours = [], []
        for h in p.interiors:
            hp = Polygon(h)
            if hp.area < 1.0: continue          # via antipads and small pad clearances
            po, sl = split_hole(hp, L)
            for x in po: x['hole_bbox'] = [round(v, 1) for v in hp.bounds]
            pours += po; holes += sl
        holes.sort(key=lambda h: -h['length_mm'])
        P.append(dict(area_mm2=round(p.area, 1), bbox=[round(v, 1) for v in p.bounds], stitch_vias=int(shapely.contains(p, stitch).sum()),
                      other_net_pours=sorted(pours, key=lambda x: -x['area_mm2']), holes_total=len(holes), holes=holes[:25]))
        if len(holes) > 25: WARN.append('%s ground piece at %s: %d slots, only the 25 longest are listed' % (L, P[-1]['bbox'], len(holes)))
    if not pieces: WARN.append('no ground copper (zones on %s) on %s' % (sorted(GND), L))
    gnd[L] = dict(total_mm2=round(g.area, 1), pct=round(100 * g.area / board_area, 1), pieces=P)
out['gnd'] = gnd

x0, y0, x1, y1 = B['edge_bbox']
grid = []
for gy in np.arange(y0, y1, 10):
    grid.append([int(sum(1 for (x, y) in gvias if gx <= x < gx + 10 and gy <= y < gy + 10)) if EDGE.intersects(box(gx, gy, gx + 10, gy + 10)) else -1
                 for gx in np.arange(x0, x1, 10)])
out['stitch_grid_10mm'] = dict(x0=x0, y0=y0, rows=grid)
ring = EDGE.exterior if hasattr(EDGE, 'exterior') else max(EDGE.geoms, key=lambda p: p.area).exterior
near = sorted(ring.project(Point(x, y)) for (x, y) in gvias + gpads_th if ring.distance(Point(x, y)) < 3.0)
gaps = []
if near:
    Ltot = ring.length
    for a_, b_ in zip(near, near[1:] + [near[0] + Ltot]):
        if b_ - a_ > 10:
            pa = ring.interpolate(a_ % Ltot); pb = ring.interpolate(b_ % Ltot)
            gaps.append(dict(gap_mm=round(b_ - a_, 1), from_xy=[round(pa.x, 1), round(pa.y, 1)], to_xy=[round(pb.x, 1), round(pb.y, 1)]))
out['edge_stitch'] = dict(vias_within_3mm=len(near), perimeter_mm=round(ring.length, 1), gaps_over_10mm=sorted(gaps, key=lambda g: -g['gap_mm']))
out['weakly_stitched_gnd_pieces'] = [dict(layer=L, **{k: p[k] for k in ('area_mm2', 'bbox', 'stitch_vias')})
                                     for L in LAYERS for p in gnd[L]['pieces'] if p['stitch_vias'] < 2 and p['area_mm2'] > 2]
# signal copper on inner layers: list it, because a track on a plane layer cuts that plane
out['inner_layer_tracks'] = {}
for L in LAYERS[1:-1]:
    tl = collections.defaultdict(float)
    for t in B['tracks']:
        if t['layer'] == L: tl[t['net']] += seg_len(t)
    out['inner_layer_tracks'][L] = sorted(([n, round(v, 1), cls(n)] for n, v in tl.items()), key=lambda r: -r[1])
out['coverage'] = dict(warnings=WARN, ground_nets=sorted(GND), min_hole_mm2=1.0, slot_contents_listed_over_mm=3)
json.dump(out, open(PACK + 'planes.json', 'w'), indent=1)
for w in WARN: print('  !!', w)
print('planes ok', {L: (gnd[L]['pct'], len(gnd[L]['pieces'])) for L in LAYERS}, len(gaps), 'edge gaps', len(out['weakly_stitched_gnd_pieces']), 'weak pieces')
