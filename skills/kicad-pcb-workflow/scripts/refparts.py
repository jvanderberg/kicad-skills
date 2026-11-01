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
  (needs the board). Exit 1 if any entry is MISSING, WRONG VALUE, FAR or AMBIGUOUS.

Hierarchical designs: an entry for one instance of an IC on a sheet used several times (U101 on /ch1/) is checked on
every instance of it (U201, U301, ...: the same symbol of the same sheet file), each against its own parts and board
placement: a part inside another instance of the same sheet never satisfies it (four port pairs on one bank rail:
U201's decoupling cap is C201, not C101; parts of the root or a parent sheet still count). A pin endpoint is the same
pin of each instance's IC. A global net (a power symbol or global label: +5V, GND - no sheet path) is the same net in
every instance. Any other net endpoint is carried over through the symbol pins of the first instance that are on it,
to the same pins in the other instance: "net:/BANK1" becomes U201's rail (/BANK2) whatever the parent named it,
through the IC's VCC pin or, when the IC has no pin on it, through another part's (C101.1 -> C201.1). One no symbol of
the instance touches is kept as written. An entry whose net lands on several nets in an instance (wired differently there) is AMBIGUOUS: give that
instance its own entry. An instance with an entry of its own keeps it.
"pin:2,5" names several pins of the IC on one net (AMBIGUOUS if they are not on one net); a part satisfies an entry
only with one pad on each endpoint.
"""
import argparse, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netspec import netlist_xml, siblings  # noqa: E402
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


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


def is_global(net):
    """a net KiCad names the same on every sheet: a power symbol or a global label (no sheet path), not one of its
    own names for an unlabelled net (Net-(R101-Pad2), unconnected-(...), named after one instance's part)"""
    return not net.startswith(('/', 'Net-(', 'unconnected-('))


def instance_net(net, sheet, sheet2, sib, pins):
    """(the net `net` of instance `sheet` is on instance `sheet2`, or None, problem). A global net (is_global: +5V,
    GND) is itself in every instance, whatever a pin strapped to it in one instance is strapped to in another. Any
    other net is carried over through every symbol pin of the first instance (and the sheets below it) that is on it,
    to the same pin of the same symbol in the other instance; one no symbol of the instance touches comes back
    unchanged."""
    if is_global(net):
        return net, None
    where = {(f, u, sh): r for r, (f, u, sh) in sib.items() if u}
    pin2net = {(r, p): n for r, ps in pins.items() for p, _, n in ps}
    to = {}
    for r, ps in sorted(pins.items(), key=lambda kv: natkey(kv[0])):
        f, u, sh = sib.get(r, ('', '', ''))
        if not u or not sh.startswith(sheet):
            continue
        r2 = where.get((f, u, sheet2 + sh[len(sheet):]))
        for p, _, n in ps:
            if n == net and r2 is not None and (r2, p) in pin2net:
                to.setdefault(pin2net[(r2, p)], []).append('%s.%s' % (r, p))
    if not to:
        return net, None
    if len(to) > 1:
        return None, 'its pins on %s are on %s in %s' % (net, ', '.join('%s (%s)' % (n, ' '.join(v[:3]))
                                                                        for n, v in sorted(to.items())), sheet2)
    return next(iter(to)), None


def expand_instances(spec, sib, pins):
    """the spec with each IC's entry repeated for the other instances of its sheet (same symbol uuid and sheet file)
    that have none of their own, right after it. A pin endpoint (function or "pin:") is the same pin of each
    instance's IC; a net endpoint is carried over through the instance's own symbol pins on it (instance_net), so
    "net:/BANK1" becomes each instance's own rail whatever the parent named it, and an entry whose net lands on
    several nets in an instance is marked (reported AMBIGUOUS)."""
    out = {}
    for ic, blk in spec.items():
        out.setdefault(ic, blk)
        if ic not in sib or not sib[ic][1]:
            continue
        f, uuid, sheet = sib[ic]
        own = pins.get(ic, [])
        for ref in sorted(sib, key=natkey):
            f2, u2, sheet2 = sib[ref]
            if ref == ic or (f2, u2) != (f, uuid) or ref in spec or ref in out:
                continue
            b = json.loads(json.dumps(blk))
            for e in b.get('parts', []):
                eps = []
                for ep in e['between']:
                    if ep.startswith('pin:') or (not ep.startswith('net:') and any(fn.upper() == ep.upper() for _, fn, _ in own)):
                        eps.append(ep)                          # a pin of the IC: the same pin in every instance
                        continue
                    n2, problem = instance_net(ep[4:] if ep.startswith('net:') else ep, sheet, sheet2, sib, pins)
                    if problem:
                        e['ambiguous'] = '%s: %s' % (ep, problem)
                    eps.append('net:%s' % n2 if n2 is not None else ep)
                e['between'] = eps
            b['instance_of'] = ic
            out[ref] = b
    return out


def endpoint(ep, ic, pins, nets):
    """-> (set of nets, set of IC pin numbers on it)"""
    if ep.startswith('pin:'):                             # one pin, or several on one net: "pin:2,5"
        nums = set(ep[4:].split(','))
        return {n for p, f, n in pins.get(ic, []) if p in nums}, nums
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


def foreign(ic, sib):
    """the sheet paths of the other instances of ic's sheet (ic on /port2/: /port1/, /port3/, ...; nested: the other
    /g*/l*/): a part under one of them is another instance's, never ic's"""
    if not sib or ic not in sib or not sib[ic][1]:
        return ()
    f, _, sheet = sib[ic]
    return tuple(sorted({sh for ff, u, sh in sib.values() if ff == f and u and sh != sheet}))


def check(spec, comps, pins, pads, sib=None):
    """sib (netspec.siblings): with it, an IC on a sheet used several times is satisfied only by parts of its own
    instance (or outside every instance of that sheet: the root's, a parent's), never by another instance's"""
    nets = {n for v in pins.values() for _, _, n in v}
    rows = []
    for ic, blk in spec.items():
        others = foreign(ic, sib)
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
            if e.get('ambiguous'):
                r['status'] = 'AMBIGUOUS: in this instance %s (the entry for %s does not carry over: give %s its own)' % (
                    e['ambiguous'], blk.get('instance_of', ic), ic); continue
            if not n1 or not n2:
                r['status'] = 'MISSING: endpoint %s not found on %s' % (e['between'][0] if not n1 else e['between'][1], ic); continue
            several = [(x, n) for x, n in zip(e['between'], (n1, n2)) if len(n) > 1]
            if several:
                r['status'] = 'AMBIGUOUS: endpoint %s of %s is on %d nets (%s): name one pin or net' % (
                    several[0][0], ic, len(several[0][1]), ', '.join(sorted(several[0][1]))); continue
            cands = []
            for ref, ps in pins.items():
                if e.get('kind') and not re.match(r'^%s\d' % re.escape(e['kind']), ref):
                    continue
                if len(ps) != 2 or (others and sib.get(ref, ('', '', ''))[2].startswith(others)):
                    continue
                a, b = ps[0][2], ps[1][2]                     # one pad on each endpoint, never both on one
                if a != b and ((a in n1 and b in n2) or (b in n1 and a in n2)):
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
    root = netlist_xml(a.netlist)
    comps, pins = load_netlist(root)
    sib = siblings(root)
    rows = check(expand_instances(spec, sib, pins), comps, pins, board_pads(a.board), sib)
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
