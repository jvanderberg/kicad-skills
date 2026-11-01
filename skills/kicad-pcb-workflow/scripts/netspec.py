#!/usr/bin/env python3
"""Compare the circuit you intended with the netlist KiCad actually extracts from the schematic.

  netspec.py check SPEC NETLIST.xml|SHEET.kicad_sch [--symmetric R,C,L,FB,F]
  netspec.py expand SPEC > flat.json                                     # a sheet-template spec, written out flat
  netspec.py from-netlist NETLIST.xml|SHEET.kicad_sch > spec.json        # freeze an existing, reviewed schematic

SPEC is JSON {"NET": ["REF.PIN", ...], ...} or a .py file that defines NETS = {...}. Net names are yours; KiCad's
names are printed beside them. A .kicad_sch is exported with kicad-cli first ($KICAD_CLI or found on PATH/macOS);
give the root sheet of a hierarchical design.

Hierarchical designs with repeated sheets: write each sheet's nets once, in the sheet's own references, and list its
instances (JSON shown; a .py file defines NETS, SHEETS and GLOBAL):
  {"global": ["GND", "+3V3"],
   "nets":   {"VIN": ["J1.1", "power/VIN"], "D1": ["J2.1", "ch1/DIN"], "D2": ["J2.2", "ch2/DIN"]},
   "sheets": {"channel": {"nets": {"DIN": ["R1.1"], "DOUT": ["R1.2", "J1.2"], "GND": ["J1.3"]},
                          "instances": {"ch1": 100, "ch2": 200}},
              "power":   {"nets": {"VIN": ["U1.3", "C1.1"], "GND": ["U1.1", "C1.2"]},
                          "instances": {"power": {"refs": {"U1": "U1", "C1": "C1"}}}}}}
- An instance is named by its sheet path without the outer slashes ("ch1", "bank2/port1" for a nested one) and maps
  the sheet's references to its own: an int offset (R1 + 100 = R101, as schgen's sheet(refs=100)), {"offset": n},
  or {"refs": {local: reference}} (schgen's Sch.instances() gives these; unlisted references stay as they are).
- Each net of a sheet becomes one net per instance, named /ch1/DOUT as KiCad names it, unless its name is in "global"
  (power symbols, global labels): those join the top-level net of that name across every sheet.
- "INSTANCE/NET" in a net's list joins that instance's net to it: a sheet pin and the wire on the parent. In a
  sheet's own nets it is relative to the sheet (a nested sheet's net, "port1/DIN" inside each bank).
- Every mapped reference must be on its own instance in the netlist (its sheet path): MISPLACED otherwise (an offset
  that does not match the drawing).

Reports, and exits 1 on any of them:
  SPLIT       one intended net became several KiCad nets (a wire end that misses a pin, a label typo)
  SHORT       one KiCad net holds pins of two intended nets (a pin dropped on a wire of another net)
  MISSING     a REF.PIN in the spec that is not in the netlist (symbol dropped, pin renumbered)
  UNEXPECTED  a multi-pin KiCad net with no pin from the spec (an unplanned connection)
  MISPLACED   a sheet instance's mapped reference that KiCad puts on another sheet
Pins not in the spec must be unconnected; list them in `nc_audit.py` instead.

Two-pin passives may be drawn either way round: a part is treated as symmetric when it has exactly two pins, both of
type passive in its library symbol, and its reference prefix is in --symmetric (default R,C,L,FB,F). Diodes, LEDs and
polarised capacitors with other prefixes are checked pin by pin.

Why: ERC does not prove the drawing matches the design. A generated schematic with a supply shorted to GND passed
ERC with one unrelated warning; this check found it at once. Pair it with schgen.find_merges() to locate the wire.
"""
import argparse, json, os, re, runpy, shutil, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_locks import cli_run  # noqa: E402


def kicad_cli():
    for c in (os.environ.get('KICAD_CLI'), shutil.which('kicad-cli'), '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'):
        if c and os.path.exists(c):
            return c
    sys.exit('kicad-cli not found; set KICAD_CLI')


def netlist_xml(path):
    if path.endswith('.kicad_sch'):
        out = os.path.join(tempfile.mkdtemp(), 'net.xml')
        cli_run([kicad_cli(), 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', out, path], path, check=True,
                capture_output=True)
        path = out
    return ET.parse(path).getroot()


def read_netlist(root):
    """-> (netpins {kicad_net: [REF.PIN]}, pin2net, parts {ref: dict(prefix, pins, passive)})"""
    netpins, pin2net = {}, {}
    for net in root.find('nets'):
        pins = ['%s.%s' % (n.get('ref'), n.get('pin')) for n in net.findall('node') if not n.get('ref', '').startswith('#')]
        netpins[net.get('name')] = pins
        for p in pins:
            pin2net[p] = net.get('name')
    libpins = {}
    for lp in root.find('libparts') if root.find('libparts') is not None else []:
        pins = lp.find('pins')
        libpins[(lp.get('lib'), lp.get('part'))] = [p.get('type') for p in pins] if pins is not None else []
    parts = {}
    for c in root.find('components'):
        ref = c.get('ref')
        if ref.startswith('#'):
            continue
        ls = c.find('libsource')
        types = libpins.get((ls.get('lib'), ls.get('part')), []) if ls is not None else []
        sp = c.find('sheetpath')
        parts[ref] = dict(prefix=re.match(r'[A-Za-z_#]*', ref).group(0), types=types,
                          sheet=sp.get('names') if sp is not None else '/')
    return netpins, pin2net, parts


def siblings(root):
    """{ref: (sheet file, symbol uuid, sheet path)}: parts with the same first two are one symbol drawn on a sheet
    that is used more than once (one per instance); shared by nc_audit.py and refparts.py"""
    out = {}
    for c in root.find('components'):
        sp = c.find('sheetpath')
        f = next((q.get('value') for q in c.findall('property') if q.get('name') == 'Sheetfile'), '')
        out[c.get('ref')] = (f, (c.findtext('tstamps') or '').strip(), sp.get('names') if sp is not None else '/')
    return out


def load_spec(path):
    if path.endswith('.py'):
        g = runpy.run_path(path)
        if 'SHEETS' in g:
            return dict(nets=dict(g.get('NETS', {})), sheets=dict(g['SHEETS']), **{'global': list(g.get('GLOBAL', []))})
        return dict(g['NETS'])
    return json.load(open(path))


def is_template(spec):
    """a sheet-template spec ({"nets", "sheets", "global"}) rather than a flat {net: pins}"""
    return isinstance(spec.get('sheets'), dict) and all(isinstance(v, dict) and 'instances' in v
                                                       for v in spec['sheets'].values())


class SpecError(ValueError):
    pass


def instance_ref(m, ref, where):
    """the reference `ref` of a sheet gets in an instance with mapping m (int offset, {"offset"}, {"refs"})"""
    if isinstance(m, dict):
        if 'refs' in m:
            return m['refs'].get(ref, ref)
        m = m.get('offset', 0)
    if isinstance(m, bool) or not isinstance(m, int):
        raise SpecError('%s: an instance maps references by an int offset, {"offset": n} or {"refs": {...}}' % where)
    if m == 0:
        return ref
    g = re.match(r'^(.*?)(\d+)$', ref)
    if not g:
        raise SpecError('%s: reference %s has no number to offset' % (where, ref))
    return '%s%d' % (g.group(1), int(g.group(2)) + m)


def expand(spec):
    """(flat {net: [REF.PIN]}, {REF: sheet path it must be on}, {REF.PIN: where in the spec it came from}) of a
    sheet-template spec; a flat spec is returned as it is."""
    if not is_template(spec):
        return {k: list(v) for k, v in spec.items()}, {}, {}
    glob = set(spec.get('global', []))
    parent, pins, origin, sheet_of = {}, {}, {}, {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb                                    # the group's name is chosen at the end
    # instance path -> (sheet name, its nets, mapping)
    insts = {}
    for name, sh in spec['sheets'].items():
        for ip, m in sh['instances'].items():
            ip = ip.strip('/')
            if ip in insts:
                raise SpecError('instance %s is listed under sheets %s and %s' % (ip, insts[ip][0], name))
            insts[ip] = (name, sh.get('nets', {}), m)

    def net_id(scope, name):
        return name if name in glob or not scope else '/%s/%s' % (scope, name)

    def add(scope, net, entries, m, where):
        nid = net_id(scope, net)
        find(nid)
        pins.setdefault(nid, [])
        for e in entries:
            if '/' in e:                                       # INSTANCE/NET: that instance's net joins this one
                ip, sub = e.rsplit('/', 1)
                full = '%s/%s' % (scope, ip) if scope else ip
                if full not in insts:
                    raise SpecError('%s: %s names no instance %s (instances: %s)' % (where, e, full, sorted(insts)))
                if sub not in insts[full][1]:
                    raise SpecError('%s: %s - sheet %s has no net %s' % (where, e, insts[full][0], sub))
                union(nid, net_id(full, sub))
                continue
            ref, _, pin = e.partition('.')
            if not pin:
                raise SpecError('%s: %r is neither REF.PIN nor INSTANCE/NET' % (where, e))
            r = instance_ref(m, ref, where) if scope else ref
            p = '%s.%s' % (r, pin)
            pins[nid].append(p)
            if scope:
                origin[p] = '%s:%s' % (scope, e)
                if sheet_of.setdefault(r, '/%s/' % scope) != '/%s/' % scope:
                    raise SpecError('%s maps two instances to reference %s (%s and /%s/)' % (where, r, sheet_of[r], scope))
    for net, entries in spec.get('nets', {}).items():
        add('', net, entries, 0, 'nets.%s' % net)
    for ip, (name, nets, m) in sorted(insts.items()):
        for net, entries in nets.items():
            add(ip, net, entries, m, 'sheets.%s.nets.%s (instance %s)' % (name, net, ip))
    groups = {}
    for nid in pins:
        groups.setdefault(find(nid), []).append(nid)
    flat = {}
    for members in groups.values():
        top = sorted(n for n in members if not n.startswith('/'))
        if len(top) > 1:
            raise SpecError('the spec joins top-level nets %s into one net (through %s)' % (
                ', '.join(top), ', '.join(sorted(n for n in members if n.startswith('/')))))
        name = top[0] if top else sorted(members)[0]
        flat[name] = [p for n in sorted(members) for p in pins[n]]
    return flat, sheet_of, origin


def check(spec, root, symmetric=('R', 'C', 'L', 'FB', 'F')):
    netpins, pin2net, parts = read_netlist(root)
    spec, sheet_of, origin = expand(spec)
    owner = {p: n for n, ps in spec.items() for p in ps}
    errors = []
    for ref, want in sorted(sheet_of.items()):
        got = parts.get(ref, {}).get('sheet')
        if got is not None and got != want:
            errors.append('MISPLACED %s is on %s, but the spec maps a part of %s to it (the instance\'s reference '
                          'map does not match the drawing)' % (ref, got, want))
    # two-pin passives drawn the other way round: swap their pins in the spec when that is what KiCad has
    for ref, info in parts.items():
        if info['prefix'] not in symmetric or len(info['types']) != 2 or any(t != 'passive' for t in info['types']):
            continue
        a, b = ref + '.1', ref + '.2'
        na, nb = owner.get(a), owner.get(b)
        if not (na and nb) or na == nb:
            continue
        others_b = [q for q in spec[nb] if q != b]
        if others_b and pin2net.get(a) and pin2net.get(a) == pin2net.get(others_b[0]):
            spec[na] = [b if q == a else q for q in spec[na]]
            spec[nb] = [a if q == b else q for q in spec[nb]]
            owner[a], owner[b] = nb, na
    all_pins = set(pin2net)
    for n, ps in spec.items():
        for p in ps:
            if p not in all_pins:
                ref = p.split('.')[0]
                errors.append('MISSING  %-12s %s%s: %s' % (n, p, ' (%s)' % origin[p] if p in origin else '',
                                                          'no such part in the netlist' if ref not in parts
                                                          else 'part has no pin %s' % p.split('.', 1)[1]))
    def groups(d):
        """{name: [pins]} with the largest group shortened, so the odd pins out stand out"""
        big = max(d, key=lambda k: len(d[k]))
        return ', '.join('%s: %s' % (k, ('%d pins' % len(v)) if k == big and len(d) > 1 and len(v) > 4 else ' '.join(v))
                         for k, v in sorted(d.items(), key=lambda kv: len(kv[1])))
    for ours, pins in spec.items():
        present = [p for p in pins if p in all_pins]
        kn = sorted({pin2net[p] for p in present})
        if len(kn) > 1:
            errors.append('SPLIT    %s is %d KiCad nets -> %s' % (ours, len(kn), groups({'"%s"' % k: [p for p in present if pin2net[p] == k] for k in kn})))
    for k, pins in sorted(netpins.items()):
        by = {}
        for p in pins:
            if p in owner:
                by.setdefault(owner[p], []).append(p)
        if len(by) > 1:
            errors.append('SHORT    KiCad net "%s" joins %s' % (k, groups(by)))
    for k, pins in netpins.items():
        if len(pins) > 1 and not any(p in owner for p in pins):
            errors.append('UNEXPECTED KiCad net "%s": %s' % (k, pins))
    return errors


def from_netlist(root):
    netpins, _, _ = read_netlist(root)
    return {k: sorted(v) for k, v in sorted(netpins.items()) if len(v) > 1}


def main():
    ap = argparse.ArgumentParser(description='intended netlist vs KiCad netlist')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check'); c.add_argument('spec'); c.add_argument('netlist')
    c.add_argument('--symmetric', default='R,C,L,FB,F', help='reference prefixes of two-pin parts that may be reversed')
    f = sub.add_parser('from-netlist'); f.add_argument('netlist')
    e = sub.add_parser('expand'); e.add_argument('spec')
    a = ap.parse_args()
    if a.cmd == 'expand':
        try:
            flat = expand(load_spec(a.spec))[0]
        except SpecError as err:
            sys.exit('netspec: %s' % err)
        json.dump(flat, sys.stdout, indent=1); print()
        return
    root = netlist_xml(a.netlist)
    if a.cmd == 'from-netlist':
        json.dump(from_netlist(root), sys.stdout, indent=1); print()
        return
    try:
        errs = check(load_spec(a.spec), root, tuple(s for s in a.symmetric.split(',') if s))
    except SpecError as err:
        sys.exit('netspec: %s' % err)
    print('\n'.join(errs) if errs else 'netlist matches the spec')
    sys.exit(1 if errs else 0)


if __name__ == '__main__':
    main()
