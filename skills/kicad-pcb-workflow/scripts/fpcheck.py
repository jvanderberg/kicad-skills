#!/usr/bin/env python3
"""Check a footprint before assigning it: pads, courtyard, size against the package, numbering against the symbol.

  fpcheck.py FOOTPRINT.kicad_mod [--package "VQFN-20-EP(3.6x4.6)"] [--symbol LIB.kicad_sym:NAME] [--pads]

FOOTPRINT may also be LIB.pretty:NAME, or Lib:Name for a KiCad library footprint (found in $KICAD10_FOOTPRINT_DIR or
the usual install path). Prints one line of facts and a list of PROBLEMs; exit 1 if there are any:
- no F.CrtYd courtyard (DRC cannot see overlaps with this part: add one with add_courtyard.py);
- pad count / body size differ from the package string (LCSC's "Package" column, e.g. from jlcimport-cli search):
  "-20" in the name is the lead count, "-EP" an exposed pad, "(3.6x4.6)" the body in mm (either orientation, 0.2 mm
  tolerance against the F.Fab outline; without an F.Fab outline the pad span is printed as a note only);
- symbol pin numbers with no pad, or numbered pads with no symbol pin (an unconnected pad, or a footprint that merges
  pins into one pad - e.g. several FET source pins as one pad "5" - so the symbol must be renumbered to match).
Footprint matchers (including jlcimport's) propose wrong pin counts and sizes often enough that every suggestion
needs this check, and the datasheet's land-pattern figure is still the authority for pad sizes and pitch.
"""
import argparse, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import SymbolLibrary, load, pins_of  # noqa: E402


def fp_dir():
    for c in (os.environ.get('KICAD10_FOOTPRINT_DIR'), os.environ.get('KICAD9_FOOTPRINT_DIR'),
              '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints', '/usr/share/kicad/footprints',
              'C:/Program Files/KiCad/10.0/share/kicad/footprints'):
        if c and os.path.isdir(c):
            return c
    return None


def resolve(spec):
    if os.path.exists(spec):
        return spec
    if '.pretty:' in spec:
        lib, name = spec.split('.pretty:', 1)
        return os.path.join(lib + '.pretty', name + '.kicad_mod')
    if ':' in spec and fp_dir():
        lib, name = spec.split(':', 1)
        return os.path.join(fp_dir(), lib + '.pretty', name + '.kicad_mod')
    sys.exit('footprint not found: ' + spec)


def pads(fp):
    """[(number, type, x, y, w, h, rot)] for every pad of a footprint node (read through kicad_sexpr)"""
    out = []
    for p in fp.nodes('pad'):
        at, size = p.find('at'), p.find('size')
        if at is None or size is None:
            continue
        out.append((str(p[1]), str(p[2]), at.number(1), at.number(2), size.number(1), size.number(2), at.number(3, 0.0)))
    return out


def layer_bbox(fp, layer):
    """Bounding box of the points of every fp_line / fp_rect / fp_arc / fp_circle / fp_poly on `layer`, or None."""
    xs, ys = [], []
    for g in fp.nodes():
        if g.head not in ('fp_line', 'fp_rect', 'fp_arc', 'fp_circle', 'fp_poly') or str(g.get('layer')) != layer:
            continue
        for n in g.walk():
            if n.head in ('start', 'end', 'mid', 'center', 'xy'):
                xs.append(n.number(1)); ys.append(n.number(2))
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def symbol_pins(spec):
    """Pin numbers of LIB.kicad_sym:NAME (derived symbols flattened), all units."""
    path, name = spec.rsplit(':', 1)
    lib = SymbolLibrary.load(path)
    if name not in lib.names():
        sys.exit('symbol %s not in %s' % (name, path))
    return {p.number for p in pins_of(lib.get(name), None, None)}


def parse_package(s):
    """'VQFN-20-EP(3.6x4.6)' -> (20, True, (3.6, 4.6)); missing parts are None"""
    n = re.search(r'-(\d+)(?:[-(]|$)', s)
    body = re.search(r'\(([\d.]+)\s*[xX*]\s*([\d.]+)', s)
    return (int(n.group(1)) if n else None, bool(re.search(r'EP|PAD|HR', s, re.I)),
            (float(body.group(1)), float(body.group(2))) if body else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('footprint'); ap.add_argument('--package'); ap.add_argument('--symbol'); ap.add_argument('--pads', action='store_true')
    a = ap.parse_args()
    path = resolve(a.footprint)
    fp = load(path)
    P = pads(fp)
    numbered = sorted({p[0] for p in P if p[0]}, key=lambda s: (len(s), s))
    crt = layer_bbox(fp, 'F.CrtYd')
    fab = layer_bbox(fp, 'F.Fab')
    probs = []
    print('%s: %d pads (%d numbers: %s), courtyard %s, F.Fab body %s' % (
        os.path.basename(path), len(P), len(numbered), ' '.join(numbered[:40]),
        '%.2f x %.2f' % (crt[2] - crt[0], crt[3] - crt[1]) if crt else 'NONE',
        '%.2f x %.2f' % (fab[2] - fab[0], fab[3] - fab[1]) if fab else 'none'))
    if a.pads:
        for n in numbered + ([''] if any(not p[0] for p in P) else []):
            lst = [p for p in P if p[0] == n]
            q = max(lst, key=lambda p: p[4] * p[5])
            print('  pad %-5s x%-2d %-8s (%7.3f, %7.3f) %5.2f x %-5.2f' % (n or '""', len(lst), q[1], q[2], q[3], q[4], q[5]))
    if not crt:
        probs.append('no F.CrtYd courtyard: DRC will not report overlaps with this part (add_courtyard.py)')
    if a.package:
        leads, ep, body = parse_package(a.package)
        if leads is not None:
            # the exposed pad is usually numbered leads+1; KiCad library footprints may also give it a lead number
            count = len([n for n in numbered if not (ep and n.isdigit() and int(n) == leads + 1)])
            if count != leads and not (ep and count == leads - 1):
                probs.append('package says %d leads%s, footprint has %d numbered pads%s%s' % (
                    leads, ' + EP' if ep else '', len(numbered), ' (EP excluded: %d)' % count if ep else '',
                    ': the footprint merges pins into shared pads - number the symbol to match' if count < leads else ''))
        if body:
            if fab and min(fab[2] - fab[0], fab[3] - fab[1]) > 0.5:       # a body outline, not just a pin-1 mark
                w, h = fab[2] - fab[0], fab[3] - fab[1]
                if not any(abs(w - bw) <= 0.2 and abs(h - bh) <= 0.2 for bw, bh in (body, body[::-1])):
                    probs.append('package body %.2f x %.2f mm, footprint F.Fab outline %.2f x %.2f mm' % (body[0], body[1], w, h))
            elif P:
                xs = [x for p in P for x in (p[2] - p[4] / 2, p[2] + p[4] / 2)]
                ys = [y for p in P for y in (p[3] - p[5] / 2, p[3] + p[5] / 2)]
                print('note: no F.Fab body outline; pads span %.2f x %.2f mm vs package body %.2f x %.2f mm - compare with '
                      'the datasheet land pattern by eye' % (max(xs) - min(xs), max(ys) - min(ys), body[0], body[1]))
    if a.symbol:
        sp = symbol_pins(a.symbol)
        fpn = set(numbered)
        if sp - fpn:
            probs.append('symbol pins with no pad: %s' % ' '.join(sorted(sp - fpn, key=lambda s: (len(s), s))))
        if fpn - sp:
            probs.append('pads with no symbol pin (unconnected, or the footprint merges pins): %s' %
                         ' '.join(sorted(fpn - sp, key=lambda s: (len(s), s))))
    for p in probs:
        print('PROBLEM ' + p)
    sys.exit(1 if probs else 0)


if __name__ == '__main__':
    main()
