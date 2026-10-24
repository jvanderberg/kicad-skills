# DC drop, copper loss, current-density hotspots and per-via current for power paths.
#
# Batch (runs from review_config.json "power_runs", writes PACK/power_runs_<tag>.json and maps/*.png):
#   python power.py PACK [--inner-um 17.5] [--tag 05oz]
# One-off question ("does this shunt have enough vias?", "what does the regulator see from one input alone?"):
#   python power.py PACK --net +12V --source F1:2 --sink J2:1=2.5 --sink J3:1=2.5 [--h 0.1] [--vias 12]
#
# A run: {"name", "net", "title", "source": ["REF:PAD", ...], "sinks": [["REF:PAD", amps], ...] or
#         "sinks_auto": {"ref": "^J\\d+$", "pad": "1", "total_amps": 10}, "h": 0.15, "region": [x0, y0, x1, y1]}
# Negative amps inject current (use it for a GND return: the input terminal's ground is the source, outputs inject).
import argparse, time
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fem import *

ap = argparse.ArgumentParser()
ap.add_argument('pack'); ap.add_argument('--inner-um', type=float); ap.add_argument('--tag', default='')
ap.add_argument('--net'); ap.add_argument('--source', action='append', default=[]); ap.add_argument('--sink', action='append', default=[])
ap.add_argument('--h', type=float, default=0.15); ap.add_argument('--vias', type=int, default=10)
a = ap.parse_args()
T_IN = a.inner_um * 1e-6 if a.inner_um else None
# IPC-2221 isolated 1 mm trace at about 20 C rise: external ~3.2 A, internal ~half. Planes spread heat far better, so
# anything over these is "look here", not a failure.
THR_OUT, THR_IN = 3.2, 1.6
def thr(L): return THR_OUT if L in ('F.Cu', 'B.Cu') else THR_IN

def sinks_of(run):
    if 'sinks' in run: return [(refpad(s), float(i)) for s, i in run['sinks']]
    s = run['sinks_auto']; rx = re.compile(s['ref'])
    pads = sorted({(r, p) for r, p, _, _ in NETS.get(run['net'], []) if rx.search(r) and p == s['pad']}, key=lambda t: natkey(t[0]))
    assert pads, ('sinks_auto matched nothing', run)
    return [(rp, s['total_amps'] / len(pads)) for rp in pads]

def plot(res, name, tag):
    os.makedirs(PACK + 'maps', exist_ok=True)
    g = res['grid']; Ls = [L for L in LAYERS if (res['_idx'][L] >= 0).any()]
    fig, axs = plt.subplots(1, len(Ls), figsize=(5 * len(Ls), 4), squeeze=False)
    ext = [g['x0'], g['x0'] + g['shape'][1] * g['h'], g['y0'] + g['shape'][0] * g['h'], g['y0']]
    for ax, L in zip(axs[0], Ls):
        A = np.where(res['_idx'][L] >= 0, res['_hot'][L], np.nan)
        im = ax.imshow(A, extent=ext, cmap='inferno', vmin=0, vmax=max(thr(L), np.nanmax(A) if np.isfinite(A).any() else 1))
        ax.set_title('%s %s (A/mm)' % (name, L), fontsize=8); fig.colorbar(im, ax=ax, shrink=0.7)
    fig.tight_layout(); fig.savefig(PACK + 'maps/%s%s.png' % (name, ('_' + tag) if tag else ''), dpi=80); plt.close(fig)

def run(r, tag='', plotit=True):
    t0 = time.time()
    region = box(*r['region']) if r.get('region') else None
    res = solve(r['net'], [refpad(s) for s in r['source']], sinks_of(r), h=r.get('h', 0.15), t_in=T_IN, region=region)
    hs = hotspots(res, min(THR_OUT, THR_IN) * 0.75, top=10)
    if plotit: plot(res, r['name'], tag)
    worst = max([s['drop_mV'] for s in res['sinks'] if s['amps'] != 0] or [0])
    if worst > 1e5: print('  !! %s: a sink reports %.3g mV, almost certainly a grid artefact; re-run with h=%.2f' % (r['name'], worst, r.get('h', 0.15) * 0.95))
    print('%-14s %-18s cells %7d  P %.2f W  worst drop %.1f mV  max via %.2f A  (%.0fs)' % (
        r['name'], r['net'][:18], res['cells'], res['P_W'], worst, res['via_amps'][0][2] if res['via_amps'] else 0, time.time() - t0), flush=True)
    return dict(name=r['name'], net=r['net'], title=r.get('title', ''), cells=res['cells'], vias=res['vias'], P_W=res['P_W'], sinks=res['sinks'],
                via_amps=res['via_amps'][:20],
                hotspots=[dict(layer=L, A_per_mm=pk, x=x, y=y, extent_mm=e, over=pk > thr(L)) for L, pk, x, y, e in hs])

if a.net:
    r = dict(name='adhoc', net=a.net, source=a.source, h=a.h,
             sinks=[[s.split('=')[0], float(s.split('=')[1])] for s in a.sink])
    out = run(r, plotit=False)
    for s in out['sinks']: print('  %s:%s %.2f A  drop %.1f mV' % (s['ref'], s['pad'], s['amps'], s['drop_mV']))
    print('  busiest vias (x, y, A):')
    for x, y, i in out['via_amps'][:a.vias]: print('    (%.2f, %.2f)  %.2f A' % (x, y, i))
else:
    runs = [run(r, a.tag) for r in CFG.get('power_runs', [])]
    json.dump(dict(t_in=T_IN, runs=runs), open(PACK + 'power_runs%s.json' % (('_' + a.tag) if a.tag else ''), 'w'), indent=1)
