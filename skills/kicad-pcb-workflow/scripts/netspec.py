#!/usr/bin/env python3
"""Compare the circuit you intended with the netlist KiCad actually extracts from the schematic.

  netspec.py check SPEC NETLIST.xml|SHEET.kicad_sch [--symmetric R,C,L,FB,F]
  netspec.py from-netlist NETLIST.xml|SHEET.kicad_sch > spec.json        # freeze an existing, reviewed schematic

SPEC is JSON {"NET": ["REF.PIN", ...], ...} or a .py file that defines NETS = {...}. Net names are yours; KiCad's
names are printed beside them. A .kicad_sch is exported with kicad-cli first ($KICAD_CLI or found on PATH/macOS).

Reports, and exits 1 on any of them:
  SPLIT       one intended net became several KiCad nets (a wire end that misses a pin, a label typo)
  SHORT       one KiCad net holds pins of two intended nets (a pin dropped on a wire of another net)
  MISSING     a REF.PIN in the spec that is not in the netlist (symbol dropped, pin renumbered)
  UNEXPECTED  a multi-pin KiCad net with no pin from the spec (an unplanned connection)
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
        parts[ref] = dict(prefix=re.match(r'[A-Za-z_#]*', ref).group(0), types=types)
    return netpins, pin2net, parts


def load_spec(path):
    if path.endswith('.py'):
        return dict(runpy.run_path(path)['NETS'])
    return json.load(open(path))


def check(spec, root, symmetric=('R', 'C', 'L', 'FB', 'F')):
    netpins, pin2net, parts = read_netlist(root)
    spec = {k: list(v) for k, v in spec.items()}
    owner = {p: n for n, ps in spec.items() for p in ps}
    errors = []
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
                errors.append('MISSING  %-12s %s: %s' % (n, p, 'no such part in the netlist' if ref not in parts
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
    a = ap.parse_args()
    root = netlist_xml(a.netlist)
    if a.cmd == 'from-netlist':
        json.dump(from_netlist(root), sys.stdout, indent=1); print()
        return
    errs = check(load_spec(a.spec), root, tuple(s for s in a.symmetric.split(',') if s))
    print('\n'.join(errs) if errs else 'netlist matches the spec')
    sys.exit(1 if errs else 0)


if __name__ == '__main__':
    main()
