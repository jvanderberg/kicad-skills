# Heat-source table: the loss in every part at every operating corner, from review_config.json "thermal".
# Pure python (no board.json): thermal.py feeds it the board's parts and the pack's power runs; tests call it directly.
#
# A part is in the table because the board has it, not because someone remembered it: every candidate (ICs, FETs,
# inductors, fuses, diodes, resistors of 1 ohm or less, ferrite beads, and any part on a power run's source or sink)
# that has no entry in "sources" is listed as UNKNOWN, and an entry whose inputs are missing at a corner is UNKNOWN at
# that corner. Nothing is dropped for being unknown (R16).
#
# "thermal": {
#   "ambient_C": 50,                                   air around the board (inside the enclosure, if there is one)
#   "h_W_m2K": "enclosed" | "bare" | {"low": 5, "nominal": 7, "high": 10},
#                                                      effective film coefficient, convection + radiation, each face:
#                                                      "enclosed" = 5 / 7 / 10, still air inside a closed box (its walls
#                                                      sit near the board's temperature, so radiation removes little);
#                                                      "bare" = 9 / 12 / 16, a bare board in still room air (radiation
#                                                      to the room adds about 6-7 W/m^2K at 50-70 C, emissivity 0.9).
#                                                      Which one applies is a question about the enclosure, not a default:
#                                                      on a bare USB-UART board the closed-box range read 76 C average and
#                                                      a part "over 85 C"; the bare-board range gave 56-68 C and no part
#                                                      over a limit.
#   "list_threshold_W": 0.05, "hot_part_W": 0.25,
#   "corners": {"<name>": {"title": "...", "currents": {"I_bat": 6.6 | {"run": "<power run>"} |
#                                                        {"path_budget": "pb.json", "source": "empty", "R_corner": "typ"}}}},
#   "sources": [
#     {"ref": "Q1", "what": "reverse-block FET", "kind": "i2r", "R_ohm": 0.0104, "R_hot_factor": 1.4, "I": "I_bat", "basis": "..."},
#     {"ref": "U4", "kind": "converter", "P_out": {"<corner>": 6.0}, "eff": 0.95, "eff_includes": ["L2"]},
#     {"ref": "U7", "kind": "linear", "V_in": 12, "V_out": 5, "I": 0.3},
#     {"ref": "U8", "kind": "fixed", "P_W": {"<corner>": 0.25}, "basis": "WEBENCH IC loss"},
#     {"copper_run": "bat_fuse_charger", "I": "I_bat"},             copper loss of a power run, scaled by (I / I_run)^2
#     {"kind": "path", "from": {"<corner>": {"path_budget": "pb.json", "source": "empty", "R_corner": "typ"}},
#      "R_hot_factor": {"Q1": 1.4}, "group": "battery path"},     one row per element of a solved path_budget.py corner
#                                                                  (pcb-power-supply, --json); elements name their "ref"
#     {"ref": "U1", "kind": "negligible", "why": "PD controller, a few mA"},
#     {"ref": "U3", "kind": "unknown", "why": "no data yet"}],
#   "parts": {"U2": {"psi_jb": 9.2, "Tj_max_C": 110, "basis": "datasheet thermal table"}},
#   "pads": {"U5:21": {"vias": 8, "basis": "datasheet layout figure"}}}
# Any number can be one value for every corner or {"<corner>": value}; a corner missing from such a dict is UNKNOWN
# there (write 0 for "off at this corner"). "group" on an entry names its subtotal (default: "conduction" for i2r and
# copper, "conversion" for converter/linear/fixed), so the series-path loss is shown next to the converter loss.
import json, os, re

CANDIDATE_PREFIXES = ('U', 'IC', 'Q', 'M', 'L', 'F', 'FB', 'D', 'LED', 'T', 'K', 'PS', 'VR', 'RT')
KINDS = ('i2r', 'converter', 'linear', 'fixed', 'copper', 'path', 'negligible', 'unknown')
ALPHA_CU = 0.00393
H_PRESETS = {'enclosed': {'low': 5.0, 'nominal': 7.0, 'high': 10.0},       # still air inside a closed box
             'bare': {'low': 9.0, 'nominal': 12.0, 'high': 16.0}}         # a bare board in still room air
DEFAULTS = dict(ambient_C=None, h_W_m2K=dict(H_PRESETS['enclosed']), list_threshold_W=0.05, hot_part_W=0.25)


def film(h):
    """review_config thermal.h_W_m2K -> {name: W/m^2K}: a preset name ("enclosed", "bare"), one number, or a dict;
    None -> the enclosed preset (the caller says it was assumed)"""
    if h is None:
        return dict(H_PRESETS['enclosed'])
    if isinstance(h, str):
        if h not in H_PRESETS:
            raise SystemExit('thermal.h_W_m2K "%s": use "enclosed" (%s), "bare" (%s), a number or {"low": .., "nominal": .., "high": ..}' % (
                h, ' / '.join('%g' % v for v in H_PRESETS['enclosed'].values()), ' / '.join('%g' % v for v in H_PRESETS['bare'].values())))
        return dict(H_PRESETS[h])
    return dict(h) if isinstance(h, dict) else {'nominal': float(h)}


def prefix(ref):
    m = re.match(r'[A-Za-z]+', ref or '')
    return m.group(0).upper() if m else ''


def parse_ohms(v):
    """'0R01' / '10m' / '0.005' / '2.2k' -> ohms (None if not a resistance)"""
    s = (v or '').strip().replace('Ω', '').replace('ohm', '').replace('Ohm', '')
    m = re.match(r'^(\d+)R(\d*)$', s)
    if m: return float(m.group(1) + '.' + (m.group(2) or '0'))
    m = re.match(r'^([\d.]+)\s*([mkM]?)', s)
    if not m: return None
    try: return float(m.group(1)) * {'m': 1e-3, '': 1.0, 'k': 1e3, 'M': 1e6}[m.group(2)]
    except ValueError: return None


def candidates(footprints, run_refs=()):
    """{ref: why} for every part that can dissipate real heat, by structure: part type, low-value resistors, parts on a
    power run's ends. Test pads and mounting holes carry no loss of their own."""
    out = {}
    for f in footprints:
        ref, fp = f['ref'], f.get('fp', '')
        if re.search(r'TestPoint|MountingHole|Fiducial', fp, re.I) or ref.startswith('#'): continue
        p = prefix(ref)
        if p in CANDIDATE_PREFIXES: out[ref] = 'part type %s' % p
        elif p == 'R':
            r = parse_ohms(f.get('value'))
            if r is not None and r <= 1.0: out[ref] = 'resistor %s (<= 1 ohm: a shunt or series element)' % f.get('value')
        if ref in run_refs and ref not in out: out[ref] = 'on a power run'
    return out


def at(v, corner):
    """(value, None) or (None, why) for one corner"""
    if isinstance(v, dict):
        if corner in v: return v[corner], None
        if '*' in v: return v['*'], None
        return None, 'not given for corner %s' % corner
    if v is None: return None, 'missing'
    return v, None


class Context:
    """what the table needs from the pack: power runs {name: {P_W, I_total, tag}} and a base dir for path_budget files"""
    def __init__(self, runs=None, base_dirs=('.',)):
        self.runs = runs or {}; self.base_dirs = list(base_dirs); self.files_used = {}; self._pb = {}

    def path_budget(self, path):
        for d in self.base_dirs:
            p = path if os.path.isabs(path) else os.path.join(d, path)
            if os.path.exists(p):
                if p not in self._pb: self._pb[p] = json.load(open(p))
                self.files_used[path] = p
                return self._pb[p], None
        return None, 'path_budget file %s not found (looked in %s)' % (path, ', '.join(self.base_dirs))


def resolve_current(spec, corner, ccfg, ctx, depth=0):
    """(amps, basis) or (None, why). spec: number, {corner: ...}, a name in the corner's currents, {"run": name},
    {"path_budget": file, "source": corner-name, "R_corner": name}"""
    if depth > 4: return None, 'current reference loop'
    if isinstance(spec, dict) and not ({'run', 'path_budget'} & set(spec)):
        spec, why = at(spec, corner)
        if why: return None, why
    if isinstance(spec, (int, float)): return float(spec), '%.3g A' % spec
    if isinstance(spec, str):
        cur = (ccfg or {}).get('currents', {})
        if spec not in cur: return None, 'current "%s" not defined at corner %s' % (spec, corner)
        I, b = resolve_current(cur[spec], corner, ccfg, ctx, depth + 1)
        return I, ('%s = %s' % (spec, b)) if I is not None else b
    if isinstance(spec, dict) and 'run' in spec:
        r = ctx.runs.get(spec['run'])
        if not r: return None, 'power run %s not in the pack' % spec['run']
        return r['I_total'], 'power run %s (%.2f A)' % (spec['run'], r['I_total'])
    if isinstance(spec, dict) and 'path_budget' in spec:
        d, why = ctx.path_budget(spec['path_budget'])
        if why: return None, why
        rows = [c for c in d.get('corners', []) if c.get('source') == spec.get('source') and (c.get('R_corner') or '') == (spec.get('R_corner') or '')]
        if not rows: return None, 'no corner source=%s R_corner=%s in %s' % (spec.get('source'), spec.get('R_corner'), spec['path_budget'])
        c = rows[0]
        if c.get('I') is None: return None, 'no operating point at %s/%s in %s (%s)' % (spec.get('source'), spec.get('R_corner'), spec['path_budget'], c.get('collapse', ''))
        return c['I'], 'path_budget %s %s/%s: %.2f A at %.2f V' % (os.path.basename(spec['path_budget']), spec.get('source'), spec.get('R_corner'), c['I'], c['V_node'])
    return None, 'unreadable current %r' % (spec,)


def entry_name(e):
    return e.get('ref') or ('copper ' + e['copper_run'] if e.get('copper_run') else '?')


def evaluate(tcfg, corner, ctx):
    """rows for one corner: dict(ref, what, kind, group, P_W (None = UNKNOWN), basis, assumed, why)"""
    ccfg = (tcfg.get('corners') or {}).get(corner, {})
    rows = []
    computed = {}                    # ref -> i2r loss at this corner, for converters whose efficiency already includes it
    entries = tcfg.get('sources', [])
    for e in entries:
        kind = 'copper' if e.get('copper_run') and 'kind' not in e else e.get('kind', 'unknown')
        row = dict(ref=e.get('ref'), name=entry_name(e), what=e.get('what', ''), kind=kind, P_W=None, basis=e.get('basis', ''),
                   assumed=bool(e.get('assumed')), why='', net=None, _e=e, group=e.get('group') or (
                       'conduction' if kind in ('i2r', 'copper') else 'conversion' if kind in ('converter', 'linear', 'fixed') else kind))
        if kind not in KINDS:
            row['why'] = 'unknown kind "%s"' % kind
        elif kind == 'unknown':
            row['why'] = e.get('why', 'loss not known')
        elif kind == 'negligible':
            row['P_W'] = 0.0; row['why'] = e.get('why') or 'NO REASON GIVEN'
        elif kind == 'i2r':
            R, w1 = at(e.get('R_ohm'), corner); I, w2 = resolve_current(e.get('I'), corner, ccfg, ctx)
            k, _ = at(e.get('R_hot_factor', 1.0), corner)
            if R is None or I is None: row['why'] = w1 or w2
            else:
                row['P_W'] = I * I * R * k
                row['inputs'] = '%.2f A^2 x %.1f mOhm%s' % (I, R * 1e3, ' x %.2f hot' % k if k != 1 else '')
                row['I_basis'] = w2
                if e.get('ref'): computed[e['ref']] = computed.get(e['ref'], 0.0) + row['P_W']
        elif kind == 'linear':
            vi, w1 = at(e.get('V_in'), corner); vo, w2 = at(e.get('V_out'), corner); I, w3 = resolve_current(e.get('I'), corner, ccfg, ctx)
            iq, _ = at(e.get('I_q', 0.0), corner)
            if None in (vi, vo, I): row['why'] = w1 or w2 or w3
            else:
                row['P_W'] = (vi - vo) * I + vi * iq
                row['inputs'] = '(%.2f - %.2f) V x %.3f A' % (vi, vo, I)
        elif kind == 'fixed':
            p, w = at(e.get('P_W'), corner)
            if p is None: row['why'] = w
            else: row['P_W'] = float(p); row['inputs'] = 'given %.3g W' % p
        elif kind == 'copper':
            r = ctx.runs.get(e.get('copper_run'))
            if not r: row['why'] = 'power run %s not in the pack' % e.get('copper_run')
            else:
                row['net'] = r.get('net')
                if e.get('I') is None:
                    I, w = r['I_total'], None; row['I_basis'] = 'the run\'s own current'
                else:
                    I, w = resolve_current(e.get('I'), corner, ccfg, ctx); row['I_basis'] = w
                if I is None: row['why'] = w
                else:
                    tc = tcfg.get('copper_temp_C', tcfg.get('ambient_C') or 20.0)
                    s = (I / r['I_total']) ** 2 if r['I_total'] else 0.0
                    row['P_W'] = r['P_W'] * s * (1 + ALPHA_CU * (tc - 20))
                    row['inputs'] = '%.3f W at %.2f A (%s) x (%.2f / %.2f)^2, copper at %g C' % (r['P_W'], r['I_total'], r.get('tag', ''), I, r['I_total'], tc)
                    row['run'] = e['copper_run']
        elif kind == 'path':
            spec = (e.get('from') or {}).get(corner, (e.get('from') or {}).get('*'))
            if spec is None: row['why'] = 'not given for corner %s' % corner
            else:
                d, why = ctx.path_budget(spec['path_budget'])
                c = None
                if not why:
                    c = next((c for c in d.get('corners', []) if c.get('source') == spec.get('source') and (c.get('R_corner') or '') == (spec.get('R_corner') or '')), None)
                    if c is None: why = 'no corner source=%s R_corner=%s in %s' % (spec.get('source'), spec.get('R_corner'), spec['path_budget'])
                    elif c.get('I') is None: why = 'no operating point at %s/%s in %s (%s)' % (spec.get('source'), spec.get('R_corner'), spec['path_budget'], c.get('collapse', ''))
                if why: row['why'] = why
                else:
                    tag = '%s %s/%s, %.2f A' % (os.path.basename(spec['path_budget']), spec.get('source'), spec.get('R_corner'), c['I'])
                    for pr in c['rows']:
                        if pr['name'].startswith('source ') or pr.get('off_board'): continue     # the cell, wires or cable: not on the board
                        refs = pr.get('ref') or []
                        refs = [refs] if isinstance(refs, str) else refs
                        for rf in (refs or [None]):
                            hf = e.get('R_hot_factor', 1.0)
                            k = hf.get(rf, hf.get('*', 1.0)) if isinstance(hf, dict) else hf
                            P = pr['P_W'] * k / max(len(refs), 1)
                            sub = dict(row, ref=rf, name=rf or pr['name'], what=pr['name'], kind='path', P_W=P,
                                       inputs='%.2f A^2 x %.1f mOhm%s%s' % (pr['I'], pr['R_mohm'], ' / %d parts' % len(refs) if len(refs) > 1 else '', ' x %.2f hot' % k if k != 1 else ''),
                                       I_basis=tag, placed=bool(rf))
                            if not rf and pr.get('run'):
                                sub.update(run=pr['run'].rsplit(':', 1)[-1], placed=True, kind='path copper')
                            elif not rf: sub['note'] = 'path element with no "ref" and no power run: its heat is spread evenly over the board'
                            rows.append(sub)
                            if rf: computed[rf] = computed.get(rf, 0.0) + P
                    continue
        rows.append(row)
    # converters last: their efficiency may already include an inductor computed above
    for e in entries:
        if e.get('kind') != 'converter': continue
        row = next(r for r in rows if r.get('_e') is e)
        po, w1 = at(e.get('P_out'), corner); eff, w2 = at(e.get('eff'), corner)
        if po is None or eff is None: row['why'] = w1 or w2; continue
        loss = po * (1 / eff - 1)
        sub = sum(computed.get(r_, 0.0) for r_ in e.get('eff_includes', []))
        missing = [r_ for r_ in e.get('eff_includes', []) if r_ not in computed]
        row['P_W'] = max(loss - sub, 0.0)
        row['inputs'] = '%.2f W out at %.1f %% = %.3f W%s' % (po, 100 * eff, loss, ' - %.3f W in %s (listed separately)' % (sub, ', '.join(e['eff_includes'])) if sub else '')
        if missing: row['note'] = 'eff_includes %s, which have no loss at this corner: nothing subtracted for them' % ', '.join(missing)
        if loss < sub: row['note'] = 'the inductor loss exceeds the converter loss from the efficiency: check both'
    return rows


def table(tcfg, corners, ctx, board_refs, cand):
    """the whole table: {corner: dict(rows, by_ref, total_W, unknown, negligible, below, groups)} plus warnings"""
    warn = []
    th = tcfg.get('list_threshold_W', DEFAULTS['list_threshold_W'])
    evaluated = {c: evaluate(tcfg, c, ctx) for c in corners}
    covered = {e.get('ref') for e in tcfg.get('sources', []) if e.get('ref')} | {r['ref'] for rs in evaluated.values() for r in rs if r.get('ref')}
    for e in tcfg.get('sources', []):
        if e.get('ref') and e['ref'] not in board_refs:
            warn.append('thermal source %s is not on the board: its loss is not placed anywhere' % e['ref'])
        if e.get('kind') == 'negligible' and not e.get('why'):
            warn.append('%s is marked negligible with no reason: say why (current, datasheet loss)' % e.get('ref'))
        if e.get('assumed'):
            warn.append('%s %s: inputs ASSUMED (%s)' % (entry_name(e), e.get('what', ''), e.get('basis', 'no basis given')))
    uncovered = sorted(set(cand) - covered, key=lambda r: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', r)])
    if uncovered:
        warn.append('%d candidate heat source(s) have no thermal entry and are UNKNOWN: %s' % (len(uncovered), ', '.join(uncovered)))
    out = {}
    for c in corners:
        rows = evaluated[c] + [dict(ref=r, name=r, what='', kind='unknown', group='unknown', P_W=None, basis='',
                                              assumed=False, why='not in thermal.sources (%s)' % cand[r], net=None) for r in uncovered]
        by_ref = {}
        for r in rows:
            if r['ref'] and r['P_W'] is not None: by_ref[r['ref']] = by_ref.get(r['ref'], 0.0) + r['P_W']
        groups = {}
        for r in rows:
            if r['P_W']: groups[r['group']] = groups.get(r['group'], 0.0) + r['P_W']
        unknown = [r for r in rows if r['P_W'] is None]
        for r in rows: r.pop('_e', None)
        out[c] = dict(title=((tcfg.get('corners') or {}).get(c) or {}).get('title', ''), rows=rows, by_ref=by_ref,
                      total_W=sum(r['P_W'] for r in rows if r['P_W']), groups=groups, unknown=unknown,
                      listed=sorted([r for r in rows if r['P_W'] is not None and r['P_W'] >= th], key=lambda r: -r['P_W']),
                      below=sorted([r for r in rows if r['P_W'] is not None and 0 < r['P_W'] < th], key=lambda r: -r['P_W']),
                      negligible=[r for r in rows if r['kind'] == 'negligible'])
        if unknown:
            warn.append('corner %s: %d UNKNOWN loss(es) (%s): the temperatures below leave them out' % (
                c, len(unknown), ', '.join(sorted({r['name'] for r in unknown}))))
    return out, warn


def starter(cand):
    """the thermal section a starter review_config.json gets: every candidate UNKNOWN, no invented numbers"""
    return dict(_comment='STARTER: every part that can dissipate real heat, found from the netlist, is UNKNOWN until you give its '
                         'loss per corner (kinds: i2r, converter, linear, fixed, copper, negligible with a reason). Set ambient_C to the '
                         'air around the board (inside the enclosure, if any) and define the corners (worst discharge, typical, charging '
                         'while running, ...). Set h_W_m2K from the enclosure - ask if the requirements do not say: "enclosed" (5 / 7 / '
                         '10, a closed box) or "bare" (9 / 12 / 16, a bare board in still room air); left null, the closed-box range is '
                         'assumed and the coverage says so. See kicad-board-review/scripts/heat.py.',
                ambient_C=None, h_W_m2K=None, corners={},
                sources=[dict(ref=r, kind='unknown', why=w) for r, w in sorted(cand.items())],
                # junction estimates need the datasheet's thermal table: one entry per IC / transistor, to fill in (or
                # delete for a part whose loss turns out negligible)
                parts={r: dict(psi_jb=None, theta_jc=None, Tj_max_C=None, basis='TODO: datasheet thermal information table (psi_JB or theta_JC, Tj max)')
                       for r in sorted(cand) if prefix(r) in ('U', 'IC', 'Q')},
                pads={})
