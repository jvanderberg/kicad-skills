# Same-net isolation on the FILLED copper: does each declared island (a single-point power ground, a quiet analog
# ground, a local pour that must meet its net only at named points) stay its own piece, joined to the rest of its net
# only where it is allowed to be? Writes PACK/islands.json.      python islands.py PACK
#
# DRC, the hot-loop table and any check by net name cannot see this: a merge is same-net copper, so it is legal. A
# copied reference layout that kept the block's own pours but not the other-net copper that fenced them off merges the
# island into the main pour, and every rule that says "isolated" or "single point" still reads "Met".
#
# review_config.json:
#   "islands": [{"name": "buck power ground", "net": "GND", "layer": "F.Cu",
#                "pads": ["U3:9", "C5:2", "C6:2"],      every pad that belongs to the island (on that layer)
#                "allowed_vias": 1,                      vias / plated holes inside the island that join other layers
#                "join_at": [[112.4, 80.2]]}]            optional: where those joins may be (0.5 mm tolerance)
# A piece that holds another pad of the net, or more joins than allowed, or joins elsewhere, is a FAIL with what it
# found; a declared pad missing from the board is NOT CHECKED. With no islands declared, the coverage says the check
# did not run.
from common import *

ISL = CFG.get('islands') or []
rows = []
if not ISL:
    sw = len(TOPO.switching_ics) if TOPO else 0
    WARN.append('same-net isolation NOT CHECKED: no "islands" in review_config.json. A single-point or quiet ground merged '
                'into the main pour is same-net copper, invisible to DRC and to the hot-loop table%s; declare each island '
                '(net, layer, its pads, allowed joins) from the datasheet layout rules' % (
                    ' (%d switching IC(s) on this board)' % sw if sw else ''))
holes = [(v['x'], v['y'], v['net'], 'via %.2f/%.2f' % (v['size'], v['drill'])) for v in B['vias']]
holes += [(p['x'], p['y'], p['net'], 'plated hole %s.%s' % (f['ref'], p['num'])) for f in B['footprints'] for p in f['pads'] if p['th']]
for k, isl in enumerate(ISL):
    name = isl.get('name') or 'island %d' % (k + 1)
    net, L = isl.get('net'), layer_key(isl.get('layer', LAYERS[0]))
    row = dict(name=name, net=net, layer=L, pads=isl.get('pads', []), allowed_vias=int(isl.get('allowed_vias', 0)))
    rows.append(row)
    missing, pgs = [], []
    for s in isl.get('pads', []):
        r, n = refpad(s)
        ps = [p for p in FP.get(r, {}).get('pads', []) if str(p['num']) == n and L in p['layers']]
        if not ps: missing.append(s); continue
        for p in ps:
            if p['net'] != net: missing.append('%s (on %s, not %s)' % (s, p['net'], net))
            else: pgs.append(unary_union(polys(p['poly'])) if p['poly'] else Point(p['x'], p['y']).buffer(0.1))
    if L not in LAYERS or not net or not pgs or missing:
        row['status'] = 'NOT CHECKED: ' + ('; '.join('pad %s not found on %s' % (m, L) for m in missing) if missing else
                                           'needs "net", "layer" and its "pads"')
        WARN.append('island %s: %s' % (name, row['status'])); continue
    g = copper(net, L)
    pieces = list(g.geoms) if hasattr(g, 'geoms') else [g]
    mine = [pc for pc in pieces if any(pc.intersects(pg) for pg in pgs)]
    piece = unary_union(mine)
    shapely.prepare(piece)
    declared = {refpad(s) for s in isl.get('pads', [])}
    others = sorted({'%s.%s' % (f['ref'], p['num']) for f in B['footprints'] for p in f['pads']
                     if p['net'] == net and L in p['layers'] and (f['ref'], str(p['num'])) not in declared
                     and piece.intersects(Point(p['x'], p['y']))}, key=natkey)
    joins = [dict(at=[round(x, 2), round(y, 2)], what=w) for x, y, n_, w in holes if n_ == net and piece.contains(Point(x, y))]
    ja = isl.get('join_at') or []
    stray = [j for j in joins if ja and not any(math.dist(j['at'], q) <= 0.5 for q in ja)]
    total = sum(pc.area for pc in pieces)
    row.update(pieces=len(mine), area_mm2=round(piece.area, 2), share_of_net_on_layer=round(piece.area / total, 3) if total else 0,
               other_pads=others, joins=joins, bbox=[round(v, 2) for v in piece.bounds])
    fails = []
    if len(mine) > 1: fails.append('the declared pads lie on %d separate pieces' % len(mine))
    if others: fails.append('merged: the piece also holds %d other %s pad(s) on %s (%s%s) - it is not isolated' % (
        len(others), net, L, ', '.join(others[:8]), ' ...' if len(others) > 8 else ''))
    if len(joins) > row['allowed_vias']: fails.append('%d via(s)/plated hole(s) join it to other layers, %d allowed' % (len(joins), row['allowed_vias']))
    if stray: fails.append('joins outside join_at: %s' % ', '.join(str(j['at']) for j in stray[:6]))
    row['status'] = 'FAIL: ' + '; '.join(fails) if fails else 'ok: one piece, %.1f mm^2, %d join(s) (%d allowed), no other pad of %s' % (
        piece.area, len(joins), row['allowed_vias'], net)
    if fails: WARN.append('island %s (%s on %s): %s' % (name, net, L, row['status']))
json.dump(dict(coverage=dict(warnings=WARN, declared=len(ISL)), islands=rows), open(PACK + 'islands.json', 'w'), indent=1)
for w in WARN: print('  !!', w)
print('islands ok: %d declared, %d failing' % (len(rows), sum(r.get('status', '').startswith('FAIL') for r in rows)))
