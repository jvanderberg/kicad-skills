# DC drop, copper loss, current-density hotspots and per-via current for power paths.
#
# Batch (runs from review_config.json "power_runs", writes PACK/power_runs_<tag>.json, maps/*.png and maps/*_loss.npz,
# where each run's copper loss sits - thermal.py places it as heat along the copper):
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
    if not pads:
        pads = sorted({(f['ref'], str(q['num'])) for f in B['footprints'] for q in f['pads']
                       if q['net'] == run['net'] and rx.search(f['ref']) and str(q['num']) == s['pad']}, key=lambda t: natkey(t[0]))
    return [(rp, s['total_amps'] / len(pads)) for rp in pads]

# nets with copper on the board, and where each pad sits now (for "the run names a net the board no longer has")
NET_COPPER = {t['net'] for t in B['tracks']} | {z['net'] for z in B['zones'] if not z['keepout']} | \
             {q['net'] for f in B['footprints'] for q in f['pads']} | {v['net'] for v in B['vias']}
PAD_NET = {(f['ref'], str(q['num'])): q['net'] for f in B['footprints'] for q in f['pads']}

def run_problems(r):
    """why this run cannot be solved on this board (empty list: it can). Nets are renamed when parts change (KiCad
    names an unnamed net after one of its pads, e.g. Net-(J3-Pad1) becomes Net-(Q1-D) after a part swap), and refs and
    pads come and go: each is reported by name instead of crashing the solver or silently dropping the run (R16)."""
    out = []
    for k in ('name', 'net', 'source'):
        if not r.get(k): out.append('run has no "%s"' % k)
    if out: return out
    if 'sinks' not in r and 'sinks_auto' not in r: return ['run has neither "sinks" nor "sinks_auto"']
    net = r['net']
    ends = [('source', s) for s in r['source']] + [('sink', s) for s, _ in r.get('sinks', [])]
    if net not in NET_COPPER:
        now = sorted({'%s -> %s' % (s, PAD_NET[refpad(s)]) for _, s in ends if refpad(s) in PAD_NET})
        out.append('net %s is not on the board%s' % (net, ('; the run\'s pads are now on: ' + ', '.join(now) +
                   ' (renamed after a part change? update "net" in review_config.json)') if now else ''))
    for role, s in ends:
        rp = refpad(s)
        if rp[0] not in FP: out.append('%s %s: no part %s on the board' % (role, s, rp[0]))
        elif rp not in PAD_NET: out.append('%s %s: %s has no pad %s' % (role, s, rp[0], rp[1]))
        elif PAD_NET[rp] != net and net in NET_COPPER: out.append('%s %s is on net %s, not %s' % (role, s, PAD_NET[rp], net))
    if not out and 'sinks_auto' in r and not sinks_of(r):
        out.append('sinks_auto %s matched no pad on net %s' % (r['sinks_auto'], net))
    return out

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
    if plotit:
        plot(res, r['name'], tag)
        # where the copper loss sits, for thermal.py (a power run's loss is a heat source spread along its copper)
        g = res['grid']
        np.savez_compressed(PACK + 'maps/%s%s_loss.npz' % (r['name'], ('_' + tag) if tag else ''), x0=g['x0'], y0=g['y0'], h=g['h'],
                            layers=np.array(list(res['_loss'])), **{'L%d' % i: res['_loss'][L] for i, L in enumerate(res['_loss'])})
    worst = max([s['drop_mV'] for s in res['sinks'] if s['amps'] != 0] or [0])
    if worst > 1e5: print('  !! %s: a sink reports %.3g mV, almost certainly a grid artefact; re-run with h=%.2f' % (r['name'], worst, r.get('h', 0.15) * 0.95))
    itot_ = sum(abs(i) for _, i in sinks_of(r))
    print('%-14s %-18s cells %7d  P %.2f W  worst drop %.1f mV  R_eff %.1f mOhm  max via %.2f A  (%.0fs)' % (
        r['name'], r['net'][:18], res['cells'], res['P_W'], worst, 1e3 * res['P_W'] / itot_ ** 2 if itot_ else 0, res['via_amps'][0][2] if res['via_amps'] else 0, time.time() - t0), flush=True)
    itot = sum(abs(s['amps']) for s in res['sinks'])
    # effective copper resistance of the run: the resistance that dissipates the same loss at the total current. Feed it
    # to path_budget.py (pcb-power-supply) as the copper element of the path, next to the FETs, fuse and wiring.
    r_eff = 1e3 * res['P_W'] / itot ** 2 if itot else None
    return dict(name=r['name'], net=r['net'], title=r.get('title', ''), cells=res['cells'], vias=res['vias'], P_W=res['P_W'], I_total=itot,
                R_eff_mohm=round(r_eff, 3) if r_eff is not None else None, sinks=res['sinks'],
                via_amps=res['via_amps'][:20],
                hotspots=[dict(layer=L, A_per_mm=pk, x=x, y=y, extent_mm=e, over=pk > thr(L)) for L, pk, x, y, e in hs])

if a.net:
    r = dict(name='adhoc', net=a.net, source=a.source, h=a.h,
             sinks=[[s.split('=')[0], float(s.split('=')[1])] for s in a.sink])
    bad = run_problems(r)
    if bad: sys.exit('power.py: cannot solve this run:\n  ' + '\n  '.join(bad))
    out = run(r, plotit=False)
    for s in out['sinks']: print('  %s:%s %.2f A  drop %.1f mV' % (s['ref'], s['pad'], s['amps'], s['drop_mV']))
    print('  busiest vias (x, y, A):')
    for x, y, i in out['via_amps'][:a.vias]: print('    (%.2f, %.2f)  %.2f A' % (x, y, i))
else:
    if not CFG.get('power_runs'): print('  !! no power_runs in review_config.json: no DC results (power.md will say so)')
    runs, not_run = [], []
    for r in CFG.get('power_runs', []):
        bad = run_problems(r)
        if not bad:
            try:
                runs.append(run(r, a.tag)); continue
            except (AssertionError, ValueError) as e:      # the solver's own checks (no cells on a pad, empty copper)
                bad = ['solver: %s' % (e,)]
        nm = r.get('name', '?')
        print('  !! power run %s NOT RUN: %s' % (nm, '; '.join(bad)), flush=True)
        not_run.append(dict(name=nm, net=r.get('net'), title=r.get('title', ''), reasons=bad))
    json.dump(dict(t_in=T_IN, runs=runs, not_run=not_run), open(PACK + 'power_runs%s.json' % (('_' + a.tag) if a.tag else ''), 'w'), indent=1)
    if not_run: print('  !! %d of %d power runs NOT RUN (listed in power.md\'s coverage)' % (len(not_run), len(not_run) + len(runs)))
