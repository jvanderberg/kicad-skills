#!/usr/bin/env python3
"""Part metadata that has to survive every pipeline stage, and the check that it did.

  partfields.py check SHEET.kicad_sch [BOARD.kicad_pcb] [--require Datasheet,LCSC|MPN] [--accept exemptions.json]
                      [--online]

Every in-BOM part needs a real Datasheet link (not "" and not KiCad's "~" placeholder) and a sourcing field (LCSC or
an MPN), in the schematic AND on the board, with the same value in both. Every other field the schematic carries
(Value, Footprint, Description, LCSC, MPN, Manufacturer, custom fields) and the DNP / exclude-from-BOM state must match
the board's footprint. Exit status 1 on any problem, so check.sh and a project build fail instead of shipping a BOM
with the information thrown away. Board-only library fields (e.g. KiLib_Generator) are listed, not compared.

--accept: {"TP1": {"Datasheet": "bare test pad, no datasheet exists"}} exempts one field of one part, with a reason;
exempted items are printed. Without it, field-exemptions.json is found by projfiles.py's convention.
--online: fetch each distinct Datasheet URL once and check it is a PDF, or a page whose title names the part's MPN,
LCSC number or value (an LCSC viewer page names the MPN) - the link must be for the exact orderable part (R3).

Library use (generators): resolve_datasheet(explicit, library_value, fields) gives the value to write and where it
came from, in this order: the caller's explicit value, the library symbol's (an imported JLCImport/EasyEDA symbol
carries one), then the LCSC datasheet URL built from the part's LCSC number. A manufacturer URL is preferable where one
is canonical (e.g. https://www.ti.com/lit/ds/symlink/<device>.pdf): pass it explicitly.
"""
import argparse, json, os, re, sys, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BLANK = ('', '~')
SOURCING = ('LCSC', 'LCSC Part', 'MPN', 'Manufacturer Part', 'Manufacturer Part Number')


def blank(v):
    return v is None or str(v).strip() in BLANK


def lcsc_number(fields):
    v = next((fields.get(k) for k in ('LCSC', 'LCSC Part', 'JLCPCB Part') if not blank(fields.get(k))), '')
    m = re.match(r'^\s*(C\d+)\s*$', v or '')
    return m.group(1) if m else None


def lcsc_datasheet(lcsc):
    return 'https://www.lcsc.com/datasheet/%s.pdf' % lcsc


def resolve_datasheet(explicit=None, library_value=None, fields=None):
    """(value, source) - value is None when nothing upstream had one (the caller must then fail, not write a blank)"""
    if not blank(explicit):
        return explicit, 'given'
    if not blank(library_value):
        return library_value, 'library symbol'
    c = lcsc_number(fields or {})
    if c:
        return lcsc_datasheet(c), 'LCSC %s' % c
    return None, 'none'


def _yes(n, head, default=True):
    x = n.find(head)
    return default if x is None else str(x[1]) == 'yes'


def schematic_parts(path):
    """{ref: dict(fields={name: value}, in_bom, on_board, dnp)} for real parts (power symbols and #refs skipped)"""
    from kicad_sexpr import load
    out = {}
    def walk(file, seen):
        t = load(file)
        for s in t.nodes('symbol'):
            props = {str(p[1]): str(p[2]) for p in s.nodes('property')}
            ref = props.get('Reference', '')
            if not ref or ref.startswith('#'):
                continue
            e = out.setdefault(ref, dict(fields={}, in_bom=_yes(s, 'in_bom'), on_board=_yes(s, 'on_board'), dnp=_yes(s, 'dnp', False)))
            for k, v in props.items():               # units of one part: the union of their fields
                if not blank(v) or k not in e['fields']:
                    e['fields'][k] = v
        for sh in t.nodes('sheet'):                  # hierarchical sheets
            props = {str(p[1]): str(p[2]) for p in sh.nodes('property')}
            f = props.get('Sheetfile') or props.get('Sheet file')
            if f:
                f = os.path.join(os.path.dirname(file), f)
                if f not in seen and os.path.exists(f):
                    seen.add(f); walk(f, seen)
    walk(path, {path})
    return out


def board_parts(path):
    from kicad_sexpr import load
    out = {}
    for f in load(path).nodes('footprint'):
        props = {str(p[1]): str(p[2]) for p in f.nodes('property')}
        ref = props.get('Reference', '')
        attr = f.find('attr')
        flags = [str(x) for x in attr[1:]] if attr is not None else []
        props['Footprint'] = str(f[1])
        out[ref] = dict(fields=props, dnp='dnp' in flags, exclude_from_bom='exclude_from_bom' in flags)
    return out


def check(sch, pcb=None, require=('Datasheet', 'LCSC|MPN'), accept=None, online=False):
    accept = accept or {}
    S = schematic_parts(sch)
    B = board_parts(pcb) if pcb else {}
    problems, exempt, info = [], [], []

    def flag(ref, field, msg):
        why = accept.get(ref, {}).get(field)
        (exempt if why else problems).append('%s %s: %s%s' % (ref, field, msg, ' (accepted: %s)' % why if why else ''))
    bom = {r: e for r, e in S.items() if e['in_bom'] and e['on_board']}
    for ref in sorted(bom, key=natkey):
        f = bom[ref]['fields']
        for req in require:
            alts = req.split('|')
            alts = [a for a in alts] if req != 'LCSC|MPN' else list(SOURCING)
            if all(blank(f.get(a)) for a in alts):
                flag(ref, req, 'blank in the schematic%s' % (' (fill it from the imported symbol, or %s)' % lcsc_datasheet(lcsc_number(f))
                                                             if req == 'Datasheet' and lcsc_number(f) else ''))
    if pcb:
        for ref in sorted(S, key=natkey):
            e = S[ref]
            if not e['on_board']:
                continue
            if ref not in B:
                flag(ref, 'footprint', 'in the schematic but not on the board'); continue
            bf = B[ref]['fields']
            for k, v in e['fields'].items():
                if k == 'Reference' or (blank(v) and blank(bf.get(k))):
                    continue
                if k not in bf:
                    flag(ref, k, 'schematic "%s", missing on the board' % v[:60])
                elif bf[k] != v:
                    flag(ref, k, 'schematic "%s" != board "%s"' % (v[:60], bf[k][:60]))
            if e['dnp'] != B[ref]['dnp']:
                flag(ref, 'DNP', 'schematic %s, board %s' % (e['dnp'], B[ref]['dnp']))
            if e['in_bom'] == B[ref]['exclude_from_bom']:
                flag(ref, 'in_bom', 'schematic in_bom %s, board exclude_from_bom %s' % (e['in_bom'], B[ref]['exclude_from_bom']))
            extra = sorted(k for k in bf if k not in e['fields'] and not blank(bf[k]))
            if extra:
                info.append('%s: board-only fields %s' % (ref, ', '.join(extra)))
            if ref in bom:
                for req in require:
                    alts = list(SOURCING) if req == 'LCSC|MPN' else req.split('|')
                    if all(blank(bf.get(a)) for a in alts):
                        flag(ref, req, 'blank on the board')
        for ref in sorted(set(B) - set(S), key=natkey):
            if ref and not ref.startswith(('H', 'MH', 'LOGO', 'G', 'REF')):
                info.append('%s: on the board, not in the schematic' % ref)
    if online:
        problems += check_links(bom); info += notes
    n_ds = sum(not blank(e['fields'].get('Datasheet')) for e in bom.values())
    return dict(parts=len(bom), with_datasheet=n_ds, problems=problems, exempt=exempt, info=info)


notes = []


def check_links(bom):
    out, seen = [], {}
    for ref in sorted(bom, key=natkey):
        f = bom[ref]['fields']; url = f.get('Datasheet')
        if blank(url) or not url.startswith('http'):
            continue
        if url not in seen:
            try:
                r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30)
                data = r.read(400000)
            except (urllib.error.URLError, OSError) as e:
                seen[url] = ('error', str(e)[:80]); data = None
            if data is not None:
                if data.startswith(b'%PDF'):
                    seen[url] = ('pdf', '')
                else:
                    t = re.search(rb'<title>(.*?)</title>', data, re.I | re.S)
                    seen[url] = ('html', t.group(1).decode('utf-8', 'replace').strip()[:160] if t else '')
        kind, txt = seen[url]
        if kind == 'error':
            out.append('%s Datasheet: %s does not load (%s)' % (ref, url, txt))
        elif kind == 'html':
            names = [f.get(k, '') for k in SOURCING + ('Value',)]
            an = lambda x: re.sub(r'[^0-9a-z]', '', x.lower())
            dev = [re.match(r'[a-z]+\d+', an(n)) for n in names if n]
            named = any(n and len(n) > 2 and an(n) in an(txt) for n in names) or any(m and len(m.group(0)) >= 6 and m.group(0) in an(txt) for m in dev)
            lc = lcsc_number(f)
            if lc and lc in url and txt:
                notes.append('%s: %s opens "%s" (the LCSC page of %s)' % (ref, url, txt[:70], lc))   # tied to the part's own LCSC number
            elif not named:
                out.append('%s Datasheet: %s is a page titled "%s", which names none of %s' % (ref, url, txt, [n for n in names if n]))
    return out


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check')
    c.add_argument('sch'); c.add_argument('pcb', nargs='?')
    c.add_argument('--require', default='Datasheet,LCSC|MPN', help='comma list; a|b = either field')
    c.add_argument('--accept'); c.add_argument('--online', action='store_true')
    a = ap.parse_args()
    import projfiles
    acc_path, msg = projfiles.describe(a.sch, 'field-exemptions.json', a.accept)
    print('exemptions: ' + msg)
    acc = json.load(open(acc_path)) if acc_path else {}
    r = check(a.sch, a.pcb, [x for x in a.require.split(',') if x], acc, a.online)
    print('%d BOM parts, %d with a datasheet link in the schematic%s' % (r['parts'], r['with_datasheet'], '' if a.pcb else ' (no board given: parity not checked)'))
    for x in r['problems']:
        print('PROBLEM ' + x)
    for x in r['exempt']:
        print('ACCEPTED ' + x)
    for x in r['info'][:40]:
        print('note    ' + x)
    print('%d problem(s), %d accepted' % (len(r['problems']), len(r['exempt'])))
    sys.exit(1 if r['problems'] else 0)


if __name__ == '__main__':
    main()
