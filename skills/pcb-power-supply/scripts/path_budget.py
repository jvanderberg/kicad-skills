#!/usr/bin/env python3
"""Solve a power path's operating point with the source's and the path's own resistance, at every corner, and
compare the result with every element's limit - latching ones first.

  path_budget.py PATH.json [--md out.md]

A design current written as P / (eff x V_source) assumes an ideal source and a zero-ohm path. A real path (cell or
cable resistance, protector FETs, fuse, charger BATFET, copper, connectors, wires) lowers the voltage at the load, and
a constant-power load (any switching converter) then draws MORE current, which lowers the voltage further. The
operating point is the solution of  I x (V_source - I x R_path) = P_in + I_cc x (V_source - I x R_path),  and it can
cross a current trip or a UVLO the naive figure clears - or have no solution at all (the source cannot deliver that
power through that resistance: P_max = V^2 / 4R). Example (labelled): a 15 W load at 88.5 % from a 3.0 V cell is
5.6 A by P/(eff V) but 6.7 A through ~72 mOhm, past a charger's 6.0 A BATFET trip that latches until USB returns.

PATH.json:
  {"name": "...",
   "source": {"name": "1S2P cell", "V": {"empty": 3.0, "nominal": 3.6, "full": 4.2}, "R": {"typ": 0.02, "max": 0.04}},
   "path": [{"name": "protector FETs", "R": {"typ": 0.016, "max": 0.024},
             "limits": [{"what": "protector OCD trip", "I_max": 8.0, "t_trip_s": 0.02, "latches": "until load removed"}]},
            {"name": "copper BAT", "from_power_run": "PACK/power_runs_inner_35um.json:bat_fuse_charger"},
            {"name": "charger BATFET", "R": {"typ": 0.0195, "max": 0.025},
             "limits": [{"what": "IBATFET_OCP (min)", "I_max": 6.0, "latches": "BATFET off until VBUS returns"}]}],
   "loads": [{"name": "12 V boost", "P_out": 6.0, "eff": 0.88}, {"name": "MCU", "I": 0.05}],
   "node_limits": [{"what": "boost UVLO (max rising)", "V_min": 2.5}],
   "transients": [{"name": "5 V load switch turn-on", "C": 2e-4, "dv_dt": 5000, "duration_s": 0.001}]}
  R: one number or {corner: ohms}; every R corner is combined with every source V corner. from_power_run takes the
  copper's effective resistance from kicad-board-review's power.py output (R_eff_mohm, or P/I^2). Limits: I_max
  (steady, and transient when t_trip_s is absent or shorter than the transient; "continuous": true = steady only),
  P_max (watts in that element), latches (what it takes to recover: these are listed first). Transients add C x dV/dt (or "I_add") for duration_s.
Output: per corner the current, the node voltage, every element's current/dissipation against its limits, the
largest load power that crosses no limit at that corner, and the lowest source voltage that carries the full load.
Exit status 1 if any limit is crossed or the operating point does not exist.
"""
import argparse, itertools, json, math, os, sys


def corners(v):
    return v if isinstance(v, dict) else {'': v}


def run_r(spec):
    path, name = spec.rsplit(':', 1)
    d = json.load(open(path))
    r = next((r for r in d['runs'] if r['name'] == name), None)
    if r is None:
        raise SystemExit('power run %s not in %s' % (name, path))
    if r.get('R_eff_mohm') is not None:
        return r['R_eff_mohm'] / 1e3
    itot = sum(abs(s['amps']) for s in r['sinks'])
    return r['P_W'] / itot ** 2


def operating_point(V, R, P, Icc):
    """total current and node voltage for constant-power P plus constant-current Icc through R; None = no solution"""
    if R <= 0:
        return (Icc + P / V, V) if V > 0 else None
    b = V + R * Icc
    disc = b * b - 4 * R * (Icc * V + P)
    if disc < 0:
        return None
    I = (b - math.sqrt(disc)) / (2 * R)
    return I, V - I * R


def evaluate(spec, scale=1.0, Vsrc=None, Rset=None, extra_I=0.0, duration=None):
    """one corner: dict(I, V_node, rows=[...], fails=[...]) or dict(collapse=...)"""
    P = scale * sum(l['P_out'] / l.get('eff', 1.0) for l in spec['loads'] if 'P_out' in l)
    Icc = scale * sum(l.get('I', 0.0) for l in spec['loads']) + extra_I
    R = sum(Rset.values())
    op = operating_point(Vsrc, R, P, Icc)
    if op is None:
        return dict(collapse='no operating point: %.2f W cannot pass %.1f mOhm from %.2f V (at most %.2f W)' % (
            P + Icc * Vsrc, R * 1e3, Vsrc, Vsrc * Vsrc / (4 * R)), fails=[('collapse', True)])
    I, Vn = op
    fails, rows = [], []
    for el in spec['path']:
        r = Rset[el['name']]
        rows.append(dict(name=el['name'], R_mohm=r * 1e3, I=I, P_W=I * I * r))
        for lim in el.get('limits', []):
            if duration is not None and (lim.get('continuous') or (lim.get('t_trip_s') is not None and duration < lim['t_trip_s'])):
                continue                                  # a continuous rating or a slower trip does not see a short pulse
            if 'I_max' in lim and I > lim['I_max']:
                fails.append(('%s: %s %.2f A > %.2f A%s' % (el['name'], lim['what'], I, lim['I_max'],
                              ' -> LATCHES: %s' % lim['latches'] if lim.get('latches') else ''), bool(lim.get('latches'))))
            if 'P_max' in lim and I * I * r > lim['P_max']:
                fails.append(('%s: %s %.2f W > %.2f W' % (el['name'], lim['what'], I * I * r, lim['P_max']), bool(lim.get('latches'))))
    for lim in spec.get('node_limits', []):
        if Vn < lim['V_min']:
            fails.append(('node %.2f V < %s %.2f V%s' % (Vn, lim['what'], lim['V_min'], ' -> LATCHES: %s' % lim['latches'] if lim.get('latches') else ''),
                          bool(lim.get('latches'))))
    return dict(I=I, V_node=Vn, rows=rows, fails=fails)


def bisect(f, lo, hi, n=50):
    """largest x in [lo, hi] with f(x) true, assuming f true at lo"""
    for _ in range(n):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if f(m) else (lo, m)
    return lo


def solve(spec):
    src = spec['source']
    Vc = corners(src['V'])
    Rs = {'source ' + src.get('name', ''): corners(src.get('R', 0.0))}
    for el in spec['path']:
        Rs[el['name']] = {'': run_r(el['from_power_run'])} if 'from_power_run' in el else corners(el.get('R', 0.0))
    spec = dict(spec, path=[dict(name='source ' + src.get('name', ''), limits=src.get('limits', []))] + spec['path'])
    rnames = sorted({k for v in Rs.values() for k in v if k}) or ['']
    out = []
    for vname, rname in itertools.product(Vc, rnames):
        Rset = {n: v.get(rname, v.get('', next(iter(v.values())))) for n, v in Rs.items()}
        V = Vc[vname]
        e = evaluate(spec, 1.0, V, Rset)
        ptot = sum(l['P_out'] for l in spec['loads'] if 'P_out' in l)
        ok = lambda s: not evaluate(spec, s, V, Rset)['fails']
        e['P_out_max'] = bisect(ok, 0.0, 4.0) * ptot if ok(0.0) else 0.0
        e['V_src_min'] = None
        if spec['loads']:
            lo, hi = 0.5, 60.0
            if not evaluate(spec, 1.0, hi, Rset)['fails']:
                for _ in range(50):
                    m = (lo + hi) / 2
                    lo, hi = (lo, m) if not evaluate(spec, 1.0, m, Rset)['fails'] else (m, hi)
                e['V_src_min'] = hi
        e['transients'] = []
        for t in spec.get('transients', []):
            add = t.get('I_add', t.get('C', 0.0) * t.get('dv_dt', 0.0))
            te = evaluate(spec, 1.0, V, Rset, extra_I=add, duration=t.get('duration_s'))
            e['transients'].append(dict(name=t['name'], I_add=add, I=te.get('I'), V_node=te.get('V_node'), fails=te['fails'],
                                        collapse=te.get('collapse')))
        out.append(dict(source=vname, V=V, R_corner=rname, R_total_mohm=sum(Rset.values()) * 1e3, **e))
    return out


def report(spec, res):
    naive = sum(l['P_out'] / l.get('eff', 1.0) for l in spec['loads'] if 'P_out' in l)
    L = ['# Path budget: %s' % spec.get('name', ''), '',
         'Loads: %s. Naive current P/(eff x V) ignores the path; the rows below solve I x (V - I R) = P.' % ', '.join(
             '%s %s' % (l['name'], '%.2f W out at %.0f %%' % (l['P_out'], 100 * l.get('eff', 1)) if 'P_out' in l else '%.3f A' % l['I']) for l in spec['loads']), '',
         '| Source | R corner | R total mOhm | Naive I (A) | Solved I (A) | Node V | Max load W at this corner | Min source V for full load | Result |',
         '|---|---|---|---|---|---|---|---|---|']
    bad = 0
    for r in res:
        fails = sorted(r['fails'], key=lambda f: not f[1])
        bad += bool(fails)
        L.append('| %s %.2f V | %s | %.1f | %.2f | %s | %s | %.1f | %s | %s |' % (
            r['source'], r['V'], r['R_corner'] or '-', r['R_total_mohm'], naive / r['V'],
            '%.2f' % r['I'] if 'I' in r else '-', '%.2f' % r['V_node'] if 'V_node' in r else '-', r['P_out_max'],
            '%.2f' % r['V_src_min'] if r['V_src_min'] else '-',
            r.get('collapse') or ('; '.join(('**' + f + '**') if latch else f for f, latch in fails) or 'ok')))
    if any(r['transients'] for r in res):
        L += ['', '## Transients (added to the steady load at each corner)', '', '| Source | R corner | Transient | Added A | Total A | Node V | Result |', '|---|---|---|---|---|---|---|']
        for r in res:
            for t in r['transients']:
                bad += bool(t['fails'])
                L.append('| %s %.2f V | %s | %s | %.2f | %s | %s | %s |' % (r['source'], r['V'], r['R_corner'] or '-', t['name'], t['I_add'],
                         '%.2f' % t['I'] if t['I'] is not None else '-', '%.2f' % t['V_node'] if t['V_node'] is not None else '-',
                         t['collapse'] or '; '.join(('**' + f + '**') if latch else f for f, latch in sorted(t['fails'], key=lambda f: not f[1])) or 'ok'))
    if res and 'rows' in res[0]:
        L += ['', '## Elements at the worst corner (highest current)', '', '| Element | R mOhm | I (A) | P (W) | Limits |', '|---|---|---|---|---|']
        w = max((r for r in res if 'I' in r), key=lambda r: r['I'], default=None)
        if w:
            lims = {el['name']: el.get('limits', []) for el in [dict(name='source ' + spec['source'].get('name', ''), limits=spec['source'].get('limits', []))] + spec['path']}
            for row in w['rows']:
                L.append('| %s | %.1f | %.2f | %.3f | %s |' % (row['name'], row['R_mohm'], row['I'], row['P_W'], '; '.join(
                    '%s %s%s' % (l['what'], ('%.2f A' % l['I_max']) if 'I_max' in l else '%.2f W' % l['P_max'], ' (latches)' if l.get('latches') else '')
                    for l in lims.get(row['name'], [])) or '-'))
    L += ['', '%d corner(s) or transient(s) cross a limit or have no operating point' % bad]
    return '\n'.join(L), bad


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('path'); ap.add_argument('--md')
    a = ap.parse_args()
    spec = json.load(open(a.path))
    os.chdir(os.path.dirname(os.path.abspath(a.path)))      # from_power_run paths are relative to the spec file
    txt, bad = report(spec, solve(spec))
    print(txt)
    if a.md:
        open(a.md, 'w').write(txt + '\n')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
