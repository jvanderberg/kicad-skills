#!/usr/bin/env python3
"""Redraw schematic symbols so the schematic reads well: pins grouped by function, real pin types. Library.

  from symgen import ic, fet, library_text, PI, PO, IN, OUT, BI, PA, NC, OC
  LDO = ic('MYLDO', 7.62,
           left=[('VIN', ['1'], PI), ('EN', ['3'], IN)],          # (name, [pin numbers], type); None = empty row
           right=[('VOUT', ['5'], PO), None, ('PG', ['4'], OC)],
           bottom=[('GND', ['2', '6'], PI)],                       # several numbers = stacked, extra copies hidden
           desc='300 mA LDO')
  NFET = fet(SymLib('Device', kicad_symbol_dir() + '/Device.kicad_sym').get('Q_NMOS'), 'MYFET',
             D=['1', '2', '5'], G=['3'], S=['4'])                  # renumber D/G/S to the FOOTPRINT's pad numbers
  open('proj.kicad_sym', 'w').write(library_text({'MYLDO': LDO, 'MYFET': NFET}))

Layout convention (what makes a generated sheet readable): inputs and supplies in on the left, outputs on the right,
supply pins on top, ground on the bottom, related pins adjacent, an empty row between groups. Pin numbers must match
the footprint you will use (check with `fpcheck.py --symbol`): an imported symbol numbered for one package and a
KiCad library footprint numbered differently (e.g. a footprint that merges several source pins into one pad) is a
silent wrong connection. Read every pin's type from the datasheet pin table; "unspecified" hides ERC problems.
"""
import re

from schgen import kstr

L = 2.54  # pin length and pitch

PI, PO, IN, OUT, BI, PA, NC, OC, TS = ('power_in', 'power_out', 'input', 'output', 'bidirectional', 'passive',
                                       'no_connect', 'open_collector', 'tri_state')


def pin_sexpr(typ, x, y, rot, name, num, hide=False):
    return ('\t\t\t(pin %s line\n\t\t\t\t(at %s %s %s)\n\t\t\t\t(length %s)%s\n\t\t\t\t(name %s\n\t\t\t\t\t(effects\n'
            '\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t\t(number %s\n'
            '\t\t\t\t\t(effects\n\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n'
            '\t\t\t\t)\n\t\t\t)\n') % (typ, round(x, 4), round(y, 4), rot, L, '\n\t\t\t\t(hide yes)' if hide else '',
                                      kstr(name), kstr(num))


def lib_property_sexpr(k, v, y, hide):
    return ('\t\t(property %s %s\n\t\t\t(at 0 %s 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
            '\t\t\t\t)%s\n\t\t\t)\n\t\t)\n') % (kstr(k), kstr(v), y, '\n\t\t\t\t(hide yes)' if hide else '')


def body_sexpr(name, half_w, half_h):
    return ('\t\t(symbol %s\n\t\t\t(rectangle\n\t\t\t\t(start %s %s)\n\t\t\t\t(end %s %s)\n\t\t\t\t(stroke\n'
            '\t\t\t\t\t(width 0.254)\n\t\t\t\t\t(type default)\n\t\t\t\t)\n\t\t\t\t(fill\n\t\t\t\t\t(type background)\n'
            '\t\t\t\t)\n\t\t\t)\n\t\t)\n') % (kstr(name + '_0_1'), -half_w, half_h, half_w, -half_h)


def ic(name, half_w, left=(), right=(), top=(), bottom=(), ref='U', desc='', top_pitch=L, footprint='', datasheet=''):
    """Rectangle symbol. Each side is a list of (name, [numbers], type) or None for an empty slot; left/right are
    listed top to bottom, top/bottom left to right. half_w: half the body width in mm (multiple of 1.27)."""
    rows = max(len(left), len(right), 1) + (2 if top else 0) + (2 if bottom else 0)
    half_h = round((rows + 1) * L / 2 / 1.27) * 1.27
    pins, seen = [], set()

    def side(entries, xy, rot):
        for i, e in enumerate(entries):
            if e is None:
                continue
            pname, nums, typ = e
            x, y = xy(i)
            for k, n in enumerate(nums):
                assert n not in seen, '%s: pin number %s used twice' % (name, n)
                seen.add(n)
                pins.append(pin_sexpr(typ, x, y, rot, pname, n, hide=k > 0))
    y0 = half_h - L - (2 * L if top else 0)
    side(left, lambda i: (-half_w - L, y0 - i * L), 0)
    side(right, lambda i: (half_w + L, y0 - i * L), 180)
    # top/bottom pins right-aligned so the left half stays free for the reference and value text
    x0 = half_w - L - (len(top) - 1) * top_pitch
    side(top, lambda i: (x0 + i * top_pitch, half_h + L), 270)
    x0b = half_w - L - (len(bottom) - 1) * L
    side(bottom, lambda i: (x0b + i * L, -half_h - L), 90)
    return ('(symbol %s\n\t\t(pin_names\n\t\t\t(offset 0.508)\n\t\t)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n'
            '\t\t(on_board yes)\n' % kstr(name) +
            lib_property_sexpr('Reference', ref, half_h + 1.27, False) + lib_property_sexpr('Value', name, -half_h - 1.27, False) +
            lib_property_sexpr('Footprint', footprint, 0, True) + lib_property_sexpr('Datasheet', datasheet, 0, True) +
            lib_property_sexpr('Description', desc, 0, True) +
            body_sexpr(name, half_w, half_h) + '\t\t(symbol %s\n' % kstr(name + '_1_1') + ''.join(pins) +
            '\t\t)\n\t\t(embedded_fonts no)\n\t)')


def fet(base_text, name, D, G, S, desc=''):
    """Copy a Device:Q_NMOS / Q_PMOS symbol block and renumber its D/G/S pins to the footprint's pad numbers;
    extra pads become hidden pins stacked on the same point."""
    t = base_text
    base = re.match(r'\(symbol "([^"]+)"', t).group(1)
    t = t.replace('(symbol "%s"' % base, '(symbol "%s"' % name, 1).replace('"%s_' % base, '"%s_' % name)
    for letter, nums in (('D', D), ('G', G), ('S', S)):
        m = re.search(r'(\t*)\(pin (\w+) (\w+)\s*\(at [^)]*\)\s*\(length [^)]*\)\s*\(name "%s".*?\(number "%s"(.*?)\n\1\)\n'
                      % (letter, letter), t, re.S)
        if not m:
            raise ValueError('%s: base symbol has no pin named/numbered %s' % (name, letter))
        blk = m.group(0)
        new = blk.replace('(number "%s"' % letter, '(number "%s"' % nums[0])
        for n in nums[1:]:
            extra = blk.replace('(number "%s"' % letter, '(number "%s"' % n)
            new += re.sub(r'(\(length [^)]*\))', r'\1\n\t\t\t\t(hide yes)', extra, count=1)
        t = t.replace(blk, new)
    t = re.sub(r'\(property "Value" "[^"]*"', '(property "Value" %s' % kstr(name), t, count=1)
    t = re.sub(r'\(property "Description" "[^"]*"', '(property "Description" %s' % kstr(desc), t, count=1)
    return t


def library_text(symbols, generator='symgen'):
    """symbols: {name: symbol block text} -> a .kicad_sym file"""
    return '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator %s)\n\t' % kstr(generator) + \
        '\n\t'.join(symbols.values()) + '\n)\n'
