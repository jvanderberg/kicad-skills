# Turn the analysis JSON into PACK/board_overview.md, PACK/power.md and PACK/emc.md.   python report.py PACK
# These, with netlist.md, are what a reviewer reads. Keep every claim traceable to coordinates so it can be checked.
import glob
from common import *

def j(name):
    p = PACK + name
    return json.load(open(p)) if os.path.exists(p) else None
P, E = j('planes.json'), j('emc.json')
runs = {os.path.basename(f)[len('power_runs'):-5].lstrip('_') or 'default': {r['name']: r for r in json.load(open(f))['runs']}
        for f in sorted(glob.glob(PACK + 'power_runs*.json'))}

# ---------------- overview
x0, y0, x1, y1 = B['edge_bbox']
o = ['# Board overview', '', '- Source: `%s`' % B.get('source', '?'),
     '- Outline %.1f x %.1f mm, bbox (%.2f, %.2f)-(%.2f, %.2f). KiCad coordinates: mm, y grows downward.' % (x1 - x0, y1 - y0, x0, y0, x1, y1),
     '- Copper layers (top to bottom): %s' % ', '.join('%s %.0f um at z=%.3f mm' % (L, STACK[L]['t'] * 1e3, STACK[L]['z']) for L in LAYERS),
     '- Reference layer per layer (nearest copper, dielectric height): %s' % '; '.join('%s -> %s' % (L, ', '.join('%s %.2f mm' % nh for nh in neighbours(L))) for L in LAYERS),
     '- %d footprints (%d on the back), %d track segments, %d vias.' % (len(B['footprints']), sum(f['side'] == 'B' for f in B['footprints']), len(B['tracks']), len(B['vias'])),
     '- Check with the fab what the copper really is: a file saying 35 um inside often ships as 0.5 oz (17.5 um).', '']
if P:
    o += ['## Copper per layer', '', '| Layer | Track mm | Zone fills (net: mm^2, % of board, pieces) |', '|---|---|---|']
    for L in LAYERS:
        z = P['layers'][L]
        o.append('| %s | %.0f | %s |' % (L, z['track_mm_total'], '; '.join('%s: %.0f, %.1f%%, %d' % (r['net'], r['area_mm2'], r['pct'], r['pieces']) for r in z['zones'][:12])))
vs = collections.Counter((v['size'], v['drill']) for v in B['vias'])
o += ['', '## Vias', '', ', '.join('%g/%g mm: %d' % (k[0], k[1], n) for k, n in sorted(vs.items())),
      '', 'By net (top 20): ' + ', '.join('%s %d' % kv for kv in collections.Counter(v['net'] for v in B['vias']).most_common(20))]
tw = collections.defaultdict(float)
for t in B['tracks']: tw[(t['layer'], t['w'])] += seg_len(t)
o += ['', '## Track widths (mm of track per width)', ''] + ['- %s: ' % L + ', '.join('%g mm: %.0f' % (w, l) for (LL, w), l in sorted(tw.items()) if LL == L) for L in LAYERS]
o += ['', '## Parts with more than 3 pads', '', '| Ref | Value | Footprint | x | y | rot | side |', '|---|---|---|---|---|---|---|']
for f in sorted(B['footprints'], key=lambda f: natkey(f['ref'])):
    if len(f['pads']) > 3: o.append('| %s | %s | %s | %.2f | %.2f | %g | %s |' % (f['ref'], f['value'], f['fp'], f['x'], f['y'], f['rot'], f['side']))
open(PACK + 'board_overview.md', 'w').write('\n'.join(o) + '\n')

# ---------------- power
p = ['# Power distribution and planes', '',
     'Method: resistive-grid DC solve per net over the saved copper (zone fills, tracks, pads) on every layer, joined by via barrels (20 um plating) '
     'and plated pads. Copper at 20 C (+0.39 %/C). The source pad is 0 V; each sink draws its current; "drop" is the mean voltage over the sink pad. '
     'Hotspots: current per mm of copper width above 75 % of a rough IPC-2221 isolated-trace limit (outer 3.2 A/mm, inner 1.6 A/mm), pessimistic for planes. '
     'Component drops (fuses, FETs, shunts, connectors) are not included.', '']
for tag, rr in runs.items():
    p += ['## Runs: %s' % tag, '', '| Run | What | Copper loss (W) | Worst drop (mV) | Busiest via (A) | Hotspots over limit |', '|---|---|---|---|---|---|']
    for name, r in rr.items():
        hs = [h for h in r['hotspots'] if h['over']]
        worst = max([s['drop_mV'] for s in r['sinks'] if s['amps'] != 0] or [0])
        p.append('| %s | %s | %.2f | %s | %s | %s |' % (name, r['title'], r['P_W'], '%.1f' % worst if worst < 1e5 else 'ARTEFACT, re-run',
                 '%.2f @ %.1f,%.1f' % (r['via_amps'][0][2], r['via_amps'][0][0], r['via_amps'][0][1]) if r.get('via_amps') else '-',
                 '; '.join('%s %.1f @ %.1f,%.1f' % (h['layer'], h['A_per_mm'], h['x'], h['y']) for h in hs[:4]) or '-'))
    p.append('')
    for name, r in rr.items():
        if len(r['sinks']) > 1:
            p.append('- %s per sink (mV): %s' % (name, ', '.join('%s.%s %.0f' % (s['ref'], s['pad'], s['drop_mV']) for s in r['sinks'])))
    p.append('')
def cause(ins):
    if not ins: return 'small'
    out = []
    if ins['other_zones']: out.append('pour of ' + ', '.join(ins['other_zones'][:3]))
    if ins['tracks']: out.append('tracks ' + ', '.join(list(ins['tracks'])[:4]))
    if ins['vias']: out.append('%d vias (%s)' % (sum(ins['vias'].values()), ', '.join(list(ins['vias'])[:2])))
    if ins['th_pads']: out.append('TH pads of ' + ', '.join(list(ins['th_pads'])[:3]))
    return '; '.join(out) or 'clearance only'
if P:
    p += ['## Ground planes', '']
    for L in LAYERS:
        g = P['gnd'][L]
        if not g['pieces']: continue
        p.append('- %s: %.0f mm^2 (%.1f %% of board), %d pieces. Largest slots: %s' % (L, g['total_mm2'], g['pct'], len(g['pieces']), '; '.join(
            '%.1fx%.1f mm at %s: %s' % (h['length_mm'], h['width_mm'], h['bbox'], cause(h['inside']))
            for pc in g['pieces'][:1] for h in pc['holes'][:5]) or 'none'))
    p += ['', '- Weakly stitched ground pieces (<2 vias): %d. %s' % (len(P['weakly_stitched_gnd_pieces']), '; '.join('%s %.0f mm^2 at %s' % (w['layer'], w['area_mm2'], w['bbox']) for w in P['weakly_stitched_gnd_pieces'][:8])),
          '- Edge stitching: %d ground vias within 3 mm of the edge; gaps over 10 mm: %s' % (P['edge_stitch']['vias_within_3mm'], ', '.join('%.0f mm from %s' % (g['gap_mm'], g['from_xy']) for g in P['edge_stitch']['gaps_over_10mm'][:8]) or 'none')]
    for L, rows in P.get('inner_layer_tracks', {}).items():
        if rows: p.append('- Tracks on inner layer %s (each one cuts that plane): %s' % (L, ', '.join('%s %.0f mm (%s)' % tuple(r) for r in rows[:20])))
open(PACK + 'power.md', 'w').write('\n'.join(p) + '\n')

# ---------------- emc
if E:
    e = ['# EMC and signal integrity (geometry heuristics)', '', 'Notes: ' + '; '.join(E['notes'].values()), '',
         '## Fast nets off their reference plane', '', '| Net | Class | Layer | Ref | Length mm | Off ground (what, mm) | Longest spans |', '|---|---|---|---|---|---|---|']
    for r in E['reference']:
        if r['cls'] in FAST and r['not_over_gnd']:
            e.append('| %s | %s | %s | %s | %.1f | %s | %s |' % (r['net'], r['cls'], r['layer'], r['ref_layer'], r['length'], ', '.join('%s %.1f' % kv for kv in r['not_over_gnd'].items()),
                     '; '.join('%.1f mm over %s at %s' % (s['len'], s['ref'], s['at']) for s in r['spans'][:3])))
    e += ['', '## Crosstalk (top 30 by coupled length x k)', '', '| Net | Other | Layers | Kind | Coupled mm | Centre mm | k | NEXT est % | At |', '|---|---|---|---|---|---|---|---|---|']
    for r in E['crosstalk'][:30]:
        e.append('| %s | %s | %s/%s | %s | %.1f | %.3f | %.2f | %.1f | %s |' % (r['net'], r['other'], r['layer'], r['other_layer'], r['kind'], r['coupled_mm'], r['min_centre_mm'], r['coupling_k'], r['next_est_pct'], r['at']))
    far = sorted([v for v in E['layer_changes'] if v['cls'] in FAST and len(set(v['ref_layers'])) > 1], key=lambda v: -v['nearest_gnd_via_mm'])
    e += ['', '## Fast-net layer changes that switch reference, farthest from a ground via first', '']
    e += ['- %s (%s) at %s, layers %s, nearest ground via %.2f mm' % (v['net'], v['cls'], v['at'], v['layers'], v['nearest_gnd_via_mm']) for v in far[:25]] or ['- none']
    e += ['', '## Fast nets within 1 mm of the board edge', ''] + (['- %s %s %.2f mm at %s' % (r['net'], r['layer'], r['dist_mm'], r['at']) for r in E['edge_proximity'][:30]] or ['- none'])
    e += ['', '## Switching nodes (copper mm^2 per layer)', ''] + (['- %s: %s' % (n, v) for n, v in E['switch_copper'].items()] or ['- none configured'])
    e += ['', '## Hot loops (IC pin -> cap -> IC ground)', '', '| IC | Loop | Cap | Value | Pin-cap mm | Gnd-cap mm | Loop area mm^2 |', '|---|---|---|---|---|---|---|']
    e += ['| %s | %s | %s | %s | %.2f | %.2f | %.1f |' % (l['ic'], l['loop'], l['cap'], l['cap_value'], l['pin_to_cap_mm'], l['gnd_pin_to_cap_mm'], l['plan_loop_area_mm2']) for l in E['hot_loops']]
    e += ['', '## Fast-net inventory', '', '| Net | Class | Pins | Length mm | Per layer | Vias | Z0 (layer@width: ohm) |', '|---|---|---|---|---|---|---|']
    e += ['| %s | %s | %s | %.1f | %s | %d | %s |' % (r['net'], r['cls'], ' '.join(r['pins'][:6]), r['length_mm'], r['per_layer'], r['vias'], r['z0_ohm']) for r in E['fast_nets']]
    if E['diff_pairs']:
        e += ['', '## Differential pairs', ''] + ['- %s: lengths %s mm, skew %.2f mm' % (' / '.join(d['pair']), d['len_mm'], d['skew_mm']) for d in E['diff_pairs']]
    open(PACK + 'emc.md', 'w').write('\n'.join(e) + '\n')
print('report ok ->', ', '.join(n for n in ('board_overview.md', 'power.md', 'emc.md') if os.path.exists(PACK + n)))
