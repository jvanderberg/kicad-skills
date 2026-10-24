# Digest a KiCad XML netlist into PACK/netlist.md (readable) and PACK/netlist.json (used by the other scripts).
#   kicad-cli sch export netlist --format kicadxml -o PACK/net.xml project.kicad_sch
#   python netdigest.py PACK [title]
# netlist.md sections: bill by sheet, every multi-pin part's pin -> net, two-pin parts as net -- net, power nets, signal
# nets, single-node nets. A reviewer reads this instead of the schematic files; it is far easier to check pin by pin.
import xml.etree.ElementTree as ET, json, re, sys, collections, os
R = os.path.abspath(sys.argv[1]) + os.sep
title = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(R.rstrip(os.sep))
x = ET.parse(R + 'net.xml').getroot()
comps = {}
for c in x.find('components'):
    f = {e.get('name'): (e.text or '') for e in c.find('fields')} if c.find('fields') is not None else {}
    sp = c.find('sheetpath')
    comps[c.get('ref')] = dict(ref=c.get('ref'), value=c.findtext('value'), fp=(c.findtext('footprint') or '').split(':')[-1],
                               lcsc=f.get('LCSC', '') or f.get('LCSC Part', ''), mpn=f.get('Manufacturer Part', '') or f.get('MPN', ''),
                               desc=(c.findtext('description') or '')[:70], sheet=sp.get('names') if sp is not None else '/',
                               dnp=any(p.get('name') == 'dnp' for p in c.findall('property')), pins={})
nets = {}
for n in x.find('nets'):
    name = n.get('name'); nodes = []
    for nd in n.findall('node'):
        ref, pin = nd.get('ref'), nd.get('pin'); pf = nd.get('pinfunction') or ''; pt = nd.get('pintype') or ''
        nodes.append((ref, pin, pf, pt))
        if ref in comps: comps[ref]['pins'][pin] = (name, pf, pt)
    nets[name] = nodes
def natkey(s): return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]
def kind(n):
    nodes = nets[n]
    if n.startswith('unconnected-') or len(nodes) == 1: return 'nc'
    if re.search(r'GND', n): return 'ground'
    if any(pt in ('power_in', 'power_out') for _, _, _, pt in nodes) or re.search(r'(\+\d|3V3|5V|VIN|VBUS|VSYS|VCC|VDD|VBAT)', n): return 'power'
    return 'signal'
out = ['# %s netlist digest' % title, '',
       'Generated from `kicad-cli sch export netlist --format kicadxml`. %d components, %d nets.' % (len(comps), len(nets)), '',
       'Sections: 1. Bill by sheet  2. Multi-pin parts (pin -> net)  3. Two-pin parts (net -- net)  4. Power and ground nets  5. Signal nets  6. Single-node nets', '']
bysheet = collections.defaultdict(list)
for r in sorted(comps, key=natkey): bysheet[comps[r]['sheet']].append(comps[r])
out.append('## 1. Bill by sheet')
for sh, cs in bysheet.items():
    out += ['', '### Sheet `%s` (%d parts)' % (sh, len(cs)), '', '| Refs | Value | Footprint | LCSC | MPN |', '|---|---|---|---|---|']
    g = collections.OrderedDict()
    for c in cs: g.setdefault((c['value'], c['fp'], c['lcsc'], c['mpn']), []).append(c['ref'] + (' (DNP)' if c['dnp'] else ''))
    for (v, fp, l, m), refs in g.items():
        rs = ', '.join(refs) if len(refs) <= 8 else '%s ... %s (%d)' % (', '.join(refs[:4]), refs[-1], len(refs))
        out.append('| %s | %s | %s | %s | %s |' % (rs, v, fp, l, m))
out += ['', '## 2. Multi-pin parts (pin -> net)', '']
for r in sorted(comps, key=natkey):
    c = comps[r]
    if len(c['pins']) <= 2: continue
    out.append('### %s  %s  (%s, %s, %s)' % (r, c['value'], c['fp'], c['lcsc'], c['sheet']))
    out.append('```')
    for p, (n, pf, pt) in sorted(c['pins'].items(), key=lambda kv: natkey(kv[0])):
        out.append('%5s %-18s %-14s %s' % (p, pf[:18], pt[:14], n))
    out.append('```')
out += ['', '## 3. Two-pin parts (pin1 net -- pin2 net)', '', '```']
for r in sorted(comps, key=natkey):
    c = comps[r]
    if len(c['pins']) > 2: continue
    ns = ' -- '.join('%s:%s' % (p, n) for p, (n, _, _) in sorted(c['pins'].items(), key=lambda kv: natkey(kv[0])))
    out.append('%-6s %-16s %-28s %s' % (r, (c['value'] or '')[:16], c['fp'][:28], ns))
out.append('```')
for head, k in (('4. Power and ground nets', ('power', 'ground')), ('5. Signal nets', ('signal',)), ('6. Single-node / unconnected nets', ('nc',))):
    out += ['', '## ' + head, '', '```']
    for n in sorted(nets, key=natkey):
        if kind(n) not in k: continue
        nodes = nets[n]
        if len(nodes) > 30:
            cnt = collections.Counter(re.match(r'[A-Z#]*', r).group(0) or r for r, _, _, _ in nodes)
            out.append('%s  [%d nodes]  %s' % (n, len(nodes), ', '.join('%s x%d' % kv for kv in sorted(cnt.items()))))
            ics = ['%s.%s(%s)' % (r, p, pf) for r, p, pf, _ in nodes if not re.match(r'^(C|R|D|F|J|TP|L|FB)\d', r)]
            if ics: out.append('    IC pins: ' + ', '.join(ics))
        else:
            out.append('%s  [%d]  %s' % (n, len(nodes), ', '.join('%s.%s%s' % (r, p, '(%s)' % pf if pf and pf != p else '')
                                                                for r, p, pf, _ in sorted(nodes, key=lambda t: natkey(t[0])))))
    out.append('```')
# ---- mechanical pin audits. Each flag needs confirming against the datasheet; they are prompts, not proof.
out += ['', '## 7. Pin audits (confirm each against the datasheet)', '']
PWR_FN = re.compile(r'^(~\{)?(A|D|IO|P)?(GND|VSS|VCC|VDD|VIN|VBAT|VSYS|PGND|AGND|DVDD|AVDD|IOVDD|VREG_VIN|VREG_AVDD)\d*\}?$', re.I)
def is_rail(n): return kind(n) in ('power', 'ground')
def fn(pf, p): return re.sub(r'_%s$' % re.escape(p), '', pf or '')   # imported symbols append _<pin number>
a1 = []
for r, c in sorted(comps.items(), key=lambda kv: natkey(kv[0])):
    for p, (n, pf, pt) in c['pins'].items():
        if (pt in ('power_in', 'power_out') or PWR_FN.match(fn(pf, p))) and (n.startswith('unconnected-') or len(nets[n]) == 1):
            a1.append('%s.%s (%s, %s) is on %s' % (r, p, pf, pt, n))
out += ['### Power/ground pins on an unconnected or single-node net', ''] + (['- ' + x for x in a1] or ['- none']) + ['']
ACT_LOW = re.compile(r'(~\{|#$|_N$|_B$|^N[A-Z]|^/)')
ENISH = re.compile(r'^(EN|OE|CE|CS|RST|RESET|SHDN|PD|STBY|SLEEP|WP|HOLD)\d*$', re.I)
a2 = []
for r, c in sorted(comps.items(), key=lambda kv: natkey(kv[0])):
    for p, (n, pf, pt) in c['pins'].items():
        pf = fn(pf, p)
        if not pf or not is_rail(n): continue
        if ACT_LOW.search(pf): a2.append('%s.%s %s (active low) tied to %s' % (r, p, pf, n))
        elif ENISH.match(pf): a2.append('%s.%s %s (no bar in the symbol - check the datasheet polarity) tied to %s' % (r, p, pf, n))
out += ['### Enable / select / reset pins tied to a rail', ''] + (['- ' + x for x in a2] or ['- none']) + ['']
# data direction: two same-direction functions on one net are suspicious; numbered data lines must meet the same index
DIRS = [(re.compile(r'(^|_)(MOSI|SDO|TXD?|COPI)$', re.I), 'out'), (re.compile(r'(^|_)(MISO|SDI|RXD?|CIPO)$', re.I), 'in')]
QSD = re.compile(r'QSPI_SD(\d)|(^|_)SD(\d)$', re.I); QIO = re.compile(r'^(IO|DQ|SIO)(\d)|^(DI)$|^(DO)$', re.I)
a3 = []
for n, nodes in nets.items():
    if len(nodes) < 2: continue
    fns = [(r, p, fn(pf, p)) for r, p, pf, _ in nodes if pf and not re.match(r'^(R|C|TP|J|FB|L)\d', r)]
    for rx, d in DIRS:
        same = [x for x in fns if rx.search(x[2])]
        if len({x[0] for x in same}) > 1: a3.append('%s joins %s - two pins of the same direction (%s)' % (n, ', '.join('%s.%s %s' % x for x in same), d))
    sd = [(x, int(next(g for g in QSD.search(x[2]).groups() if g and g.isdigit()))) for x in fns if QSD.search(x[2])]
    io = []
    for x in fns:
        m = QIO.search(x[2])
        if m: io.append((x, int(m.group(2)) if m.group(2) else (0 if m.group(3) else 1)))
    for (x, k) in sd:
        for (y, j) in io:
            if k != j: a3.append('%s joins %s.%s %s to %s.%s %s - data line index %d meets %d: check both datasheets' % (n, *x, *y, k, j))
out += ['### Data direction (DI/DO, TX/RX, MOSI/MISO, numbered data lines)', ''] + (['- ' + x for x in a3] or ['- none flagged - still trace every serial/memory/UART line driver to receiver against both datasheets']) + ['']
# LED series resistor power at the rail voltage (rail voltage from the net name, or review_config.json "rail_voltages")
cfg = json.load(open(R + 'review_config.json')) if os.path.exists(R + 'review_config.json') else {}
RV = cfg.get('rail_voltages', {})
def volts(n):
    if n in RV: return float(RV[n])
    m = re.search(r'(\d+)V(\d+)?', n.replace('+', ''))
    return float('%s.%s' % (m.group(1), m.group(2) or 0)) if m else None
PKG_W = {'0201': 0.05, '0402': 0.0625, '0603': 0.1, '0805': 0.125, '1206': 0.25, '2512': 1.0}
leds = {r for r, c in comps.items() if re.match(r'^D', r) and re.search(r'LED|^(red|green|blue|white|yellow|amber|orange|rgb|ws28|sk68)', c['value'] + ' ' + c['fp'] + ' ' + c['desc'], re.I)}
a4 = []
for r, c in sorted(comps.items(), key=lambda kv: natkey(kv[0])):
    if not r.startswith('R') or len(c['pins']) != 2: continue
    ns = [v[0] for v in c['pins'].values()]
    if not any(any(x[0] in leds for x in nets[n]) for n in ns): continue
    m = re.match(r'([\d.]+)\s*([kKmM]?)', c['value'] or '')
    rail = [n for n in ns if volts(n)]
    if not m or not rail: continue
    ohm = float(m.group(1)) * {'k': 1e3, 'K': 1e3, 'M': 1e6, 'm': 1e6, '': 1}[m.group(2)]
    v = volts(rail[0]); pw = max(v - 2.0, 0) ** 2 / ohm if ohm else 0
    pkg = next((k for k in PKG_W if k in c['fp']), None)
    flag = ' <-- over 50 %% of the %s rating (%.0f mW)' % (pkg, PKG_W[pkg] * 1e3) if pkg and pw > 0.5 * PKG_W[pkg] else ''
    a4.append('%s %s on %s (%.3g V): ~%.1f mW (assuming 2 V LED drop)%s' % (r, c['value'], rail[0], v, pw * 1e3, flag))
out += ['### LED series resistor power', ''] + (['- ' + x for x in a4] or ['- none found (set "rail_voltages" in review_config.json for rails whose name has no voltage)'])
open(R + 'netlist.md', 'w').write('\n'.join(out) + '\n')
json.dump(dict(components=comps, nets={n: [list(t) for t in v] for n, v in nets.items()}), open(R + 'netlist.json', 'w'), indent=1)
print(len(comps), 'components', len(nets), 'nets ->', R + 'netlist.md')
