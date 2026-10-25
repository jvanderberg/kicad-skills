#!/usr/bin/env python3
"""Diff each IC's datasheet typical application (and layout figure) against the design: which schematic part
satisfies each required part, at what value and how far from its pin.

  refparts.py NETLIST.xml|SHEET.kicad_sch [BOARD.kicad_pcb] [--spec reference-parts.json] [--md out.md]

The datasheet's typical application and layout example are the primary list of the parts an IC needs and where they
sit: bootstrap, VCC/LDO bypass, a small high-frequency capacitor at the output pins, snubbers, RC filters, the
feedback divider - not only the bulk capacitors. A vendor tool's BOM (WEBENCH) is a secondary source: it can leave out
a part the datasheet draws (WEBENCH's TPS61088 BOM had no 1 uF at VOUT; the datasheet's C9 sits at the VOUT pins), and
"some capacitor of that kind is nearby" is not the part the datasheet asks for. Write the list from the datasheet,
once per IC, and let this script name the part that satisfies each entry - or say that none does.

reference-parts.json (found by projfiles.py's convention when --spec is not given):
  {"U5": {"part": "TPS61088-Q1", "source": "SLVSE52A fig. 13 (typical application), fig. 21 (layout example)",
          "parts": [
            {"role": "C9: small output cap at VOUT", "kind": "C", "between": ["VOUT", "GND"], "value": "1u", "tol": 0.5,
             "max_mm": 2.0, "where": "fig. 21: at pins 14-16, before the bulk caps"},
            {"role": "bootstrap", "kind": "C", "between": ["BOOT", "SW"], "value": "100n"},
            {"role": "FSW resistor", "kind": "R", "between": ["FSW", "SW"]}]}}
  between: two endpoints, each an IC pin function ("VOUT"), "pin:14", or "net:NAME" / a net name ("GND"); the part
  must have one pad on each. kind: refdes prefix (C, R, L, D, ...). value with "tol" (relative, default 0.25) and/or
  "min"/"max"; max_mm: centre-to-centre distance from the part's nearest pad to the IC pad of the first endpoint
  (needs the board). Exit 1 if any entry is MISSING, WRONG VALUE or FAR.
"""
import argparse, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netspec import netlist_xml  # noqa: E402
import projfiles  # noqa: E402

UNIT = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'm': 1e-3, '': 1.0, 'k': 1e3, 'K': 1e3, 'M': 1e6}


def value(s):
    s = (s or '').strip()
    m = re.match(r'^(\d+)([RkKMunpµ])(\d+)', s)            # 2R2, 4k7, 4u7
    if m:
        return float('%s.%s' % (m.group(1), m.group(3))) * UNIT.get(m.group(2) if m.group(2) != 'R' else '', 1.0)
    m = re.match(r'^([\d.]+)\s*([pnuµmkKM]?)', s)
    return float(m.group(1)) * UNIT[m.group(2)] if m else None


def pin_fn(pf, pin):
    return re.sub(r'~\{([^}]*)\}', r'\1', re.sub(r'_%s$' % re.escape(pin), '', pf or ''))


def load_netlist(root):
    comps = {c.get('ref'): c.findtext('value') or '' for c in root.find('components')}
    pins = {}                                             # ref -> [(pin, function, net)]
    for net in root.find('nets'):
        for n in net.findall('node'):
            pins.setdefault(n.get('ref'), []).append((n.get('pin'), pin_fn(n.get('pinfunction'), n.get('pin')), net.get('name')))
    return comps, pins


def endpoint(ep, ic, pins, nets):
    """-> (set of nets, set of IC pin numbers on it)"""
    if ep.startswith('pin:'):
        num = ep[4:]
        return {n for p, f, n in pins.get(ic, []) if p == num}, {num}
    if ep.startswith('net:'):
        n = ep[4:]
        return {n}, {p for p, f, nn in pins.get(ic, []) if nn == n}
    hit = [(p, n) for p, f, n in pins.get(ic, []) if f.upper() == ep.upper()]
    if hit:
        return {n for _, n in hit}, {p for p, _ in hit}
    if ep in nets:
        return {ep}, {p for p, f, n in pins.get(ic, []) if n == ep}
    return set(), set()


def board_pads(path):
    if not path:
        return {}
    from kicad_sexpr import Board
    b = Board.load(path)
    out = {}
    for f in b.footprints():
        seen = {}
        for p in f.pads():
            num = str(p[1])
            k = seen.get(num, 0); seen[num] = k + 1
            out.setdefault(f.ref, []).append((num, f.pad_position(num, k)))
    return out


def check(spec, comps, pins, pads):
    nets = {n for v in pins.values() for _, _, n in v}
    rows = []
    for ic, blk in spec.items():
        used = {}                                        # one schematic part satisfies one datasheet part
        if ic not in pins:
            pass
        if ic not in pins:
            rows.append(dict(ic=ic, role='(whole block)', need='', status='MISSING: %s is not in the netlist' % ic)); continue
        for e in blk['parts']:
            (n1, p1), (n2, _) = [endpoint(x, ic, pins, nets) for x in e['between']]
            need = '%s %s-%s%s%s' % (e.get('kind', ''), e['between'][0], e['between'][1], ' %s' % e['value'] if e.get('value') else '',
                                     ' <=%g mm' % e['max_mm'] if e.get('max_mm') else '')
            r = dict(ic=ic, role=e['role'], need=need, where=e.get('where', ''))
            rows.append(r)
            if not n1 or not n2:
                r['status'] = 'MISSING: endpoint %s not found on %s' % (e['between'][0] if not n1 else e['between'][1], ic); continue
            cands = []
            for ref, ps in pins.items():
                if e.get('kind') and not re.match(r'^%s\d' % re.escape(e['kind']), ref):
                    continue
                pn = {n for _, _, n in ps}
                if len(ps) == 2 and len(pn) == 2 and pn & n1 and pn & n2:
                    cands.append(ref)
            taken = [c for c in cands if c in used and not e.get('shared')]
            cands = [c for c in cands if c not in taken]
            if not cands:
                r['status'] = 'MISSING: no %s between %s and %s%s' % (e.get('kind', 'part'), '/'.join(sorted(n1)), '/'.join(sorted(n2)),
                              ' (other than %s)' % ', '.join('%s, which is "%s"' % (c, used[c]) for c in taken) if taken else ''); continue
            want = value(e.get('value')) if e.get('value') else None
            lo = value(e['min']) if e.get('min') else (want * (1 - e.get('tol', 0.25)) if want else None)
            hi = value(e['max']) if e.get('max') else (want * (1 + e.get('tol', 0.25)) if want else None)
            ev = []
            for c in cands:
                v = value(comps.get(c))
                d = None
                if pads and c in pads and ic in pads:
                    icp = [xy for num, xy in pads[ic] if num in p1] or [xy for _, xy in pads[ic]]
                    d = min(math.dist(a, b) for _, a in pads[c] for b in icp)
                ok_v = (lo is None or (v is not None and v >= lo)) and (hi is None or (v is not None and v <= hi))
                ok_d = e.get('max_mm') is None or d is None or d <= e['max_mm']
                ev.append((ok_v, ok_d, d if d is not None else 1e9, c, comps.get(c), d))
            ev.sort(key=lambda t: (not t[0], not t[1], t[2]))
            ok_v, ok_d, _, c, val, d = ev[0]
            dtxt = '' if d is None else ', %.2f mm' % d
            others = ', '.join('%s %s%s' % (x[3], x[4], '' if x[5] is None else ' %.1f mm' % x[5]) for x in ev[1:4])
            r['by'] = c
            if ok_v and ok_d:
                used[c] = e['role']
                r['status'] = 'ok: %s (%s%s)' % (c, val, dtxt) + (' [distance not checked: no board]' if e.get('max_mm') and d is None else '')
            elif not ok_v:
                r['status'] = 'WRONG VALUE: best is %s (%s%s), need %s' % (c, val, dtxt, e.get('value') or '%s-%s' % (e.get('min'), e.get('max')))
            else:
                r['status'] = 'FAR: %s (%s) is %.2f mm from the pin, need <= %g' % (c, val, d, e['max_mm'])
            if others:
                r['status'] += '; others: ' + others
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('netlist'); ap.add_argument('board', nargs='?'); ap.add_argument('--spec'); ap.add_argument('--md')
    a = ap.parse_args()
    sp, msg = projfiles.describe(a.netlist, 'reference-parts.json', a.spec)
    print('spec: ' + msg, file=sys.stderr)
    if not sp:
        sys.exit('no reference-parts.json: write one from each IC\'s datasheet typical application and layout figure')
    spec = json.load(open(sp))
    comps, pins = load_netlist(netlist_xml(a.netlist))
    rows = check(spec, comps, pins, board_pads(a.board))
    out = ['| IC | Required (datasheet) | Where | Status |', '|---|---|---|---|']
    out += ['| %s | %s: %s | %s | %s |' % (r['ic'], r['role'], r['need'], r.get('where', ''), r['status']) for r in rows]
    bad = [r for r in rows if not r['status'].startswith('ok')]
    out.append('\n%d required parts, %d not satisfied%s' % (len(rows), len(bad), ' (no board: distances not checked)' if not a.board else ''))
    print('\n'.join(out))
    if a.md:
        open(a.md, 'w').write('\n'.join(out) + '\n')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
