#!/usr/bin/env python3
"""Redraw schematic symbols so the schematic reads well: pins grouped by function, real pin types. Library.

  from symgen import ic, fet, library, PI, PO, IN, OUT, BI, PA, NC, OC
  LDO = ic('MYLDO', 7.62,
           left=[('VIN', ['1'], PI), ('EN', ['3'], IN)],          # (name, [pin numbers], type); None = empty row
           right=[('VOUT', ['5'], PO), None, ('PG', ['4'], OC)],
           bottom=[('GND', ['2', '6'], PI)],                       # several numbers = stacked: the first as typed,
           desc='300 mA LDO')                                      # the others hidden and passive on the same point
  NFET = fet(SymLib('Device', kicad_symbol_dir() + '/Device.kicad_sym').get('Q_NMOS'), 'MYFET',
             D=['1', '2', '5'], G=['3'], S=['4'])                  # renumber D/G/S to the FOOTPRINT's pad numbers
  save_library({'MYLDO': LDO, 'MYFET': NFET}, 'hw/proj.kicad_sym', 'Proj')   # writes it and registers Proj in
                                                                             # hw/sym-lib-table as ${KIPRJMOD}/proj.kicad_sym

ic() and fet() return kicad_sexpr symbol nodes; library() puts them in a kicad_sexpr SymbolLibrary, which owns the
syntax (quoting, layout, version header). library_text() returns the same file as a string (for Sch.lib(text=...)).
save_library() saves the library and registers it in the project's sym-lib-table (kicad_sexpr LibTable): use it
instead of editing the table, so the entry is project-relative and a re-run changes nothing.

Layout convention (what makes a generated sheet readable): inputs and supplies in on the left, outputs on the right,
supply pins on top, ground on the bottom, related pins adjacent, an empty row between groups. Pin numbers must match
the footprint you will use (check with `fpcheck.py --symbol`): an imported symbol numbered for one package and a
KiCad library footprint numbered differently (e.g. a footprint that merges several source pins into one pad) is a
silent wrong connection. Read every pin's type from the datasheet pin table; "unspecified" hides ERC problems.

Stacked pins (several pad numbers on one pin, ic() and fet()) follow KiCad's own libraries: one visible pin with the
stated type, the other numbers hidden and passive on the same point (no_connect for an NC pin). Never hidden power_in:
KiCad connects a hidden power_in pin to a global net named after the pin, so two parts with stacked IN or VCC pins
would be shorted together (ERC says only multiple_net_names).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_locks  # noqa: E402
from kicad_sexpr import (LibTable, Node, Sym, SymbolLibrary, dumps, find_project_dir, lib_pin,  # noqa: E402
                         lib_property, lib_rectangle, lib_symbol, loads)

L = 2.54  # pin length and pitch

PI, PO, IN, OUT, BI, PA, NC, OC, TS = ('power_in', 'power_out', 'input', 'output', 'bidirectional', 'passive',
                                       'no_connect', 'open_collector', 'tri_state')


def _carry(props, inherit):
    """Fill blank Footprint / Datasheet / Description from the symbol being replaced and append its other
    properties (LCSC, MPN, Manufacturer...) hidden. A redraw changes the drawing, never the part's data."""
    if inherit is None:
        return props
    old = {str(q[1]): str(q[2]) for q in _node(inherit).nodes('property') if not str(q[1]).startswith('ki_')}
    have = {str(q[1]) for q in props}
    for q in props:
        k = str(q[1])
        if k in ('Footprint', 'Datasheet', 'Description') and str(q[2]).strip() in ('', '~') and old.get(k, '').strip() not in ('', '~'):
            q[2] = old[k]
    for k, v in old.items():
        if k not in have and k not in ('Reference', 'Value') and v.strip() not in ('', '~'):
            props.append(lib_property(k, v, hide=True))
    return props


def ic(name, half_w, left=(), right=(), top=(), bottom=(), ref='U', desc='', top_pitch=L, footprint='', datasheet='',
       inherit=None):
    """Rectangle symbol. Each side is a list of (name, [numbers], type) or None for an empty slot; left/right are
    listed top to bottom, top/bottom left to right. half_w: half the body width in mm (multiple of 1.27).
    inherit: the symbol this one replaces (e.g. the JLCImport symbol, as a node or its text): its Datasheet,
    Footprint, Description and custom fields fill whatever is not given here, so a redraw drops no data."""
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
                # stacked copies as in KiCad's libraries: hidden and passive (a hidden power_in pin is an implicit
                # global net named after the pin, which would join every part with a pin of that name); NC copies
                # stay no_connect (a passive copy would be an unconnected pin and touch the NC pin)
                etype = typ if k == 0 or typ == NC else PA
                pins.append(lib_pin(etype, round(x, 4), round(y, 4), rot, pname, n, length=L, hide=k > 0))
    y0 = half_h - L - (2 * L if top else 0)
    side(left, lambda i: (-half_w - L, y0 - i * L), 0)
    side(right, lambda i: (half_w + L, y0 - i * L), 180)
    # top/bottom pins right-aligned so the left half stays free for the reference and value text
    x0 = half_w - L - (len(top) - 1) * top_pitch
    side(top, lambda i: (x0 + i * top_pitch, half_h + L), 270)
    x0b = half_w - L - (len(bottom) - 1) * L
    side(bottom, lambda i: (x0b + i * L, -half_h - L), 90)
    props = [lib_property('Reference', ref, 0, half_h + 1.27), lib_property('Value', name, 0, -half_h - 1.27),
             lib_property('Footprint', footprint, hide=True), lib_property('Datasheet', datasheet, hide=True),
             lib_property('Description', desc, hide=True)]
    return lib_symbol(name, _carry(props, inherit), {(0, 1): [lib_rectangle(-half_w, half_h, half_w, -half_h)], (1, 1): pins})


def _node(sym):
    """A symbol given as a kicad_sexpr node (copied) or as KiCad text (parsed)."""
    return sym.deepcopy() if isinstance(sym, Node) else loads(sym)


def fet(base, name, D, G, S, desc='', inherit=None):
    """Copy a Device:Q_NMOS / Q_PMOS symbol (node, or its text) and renumber its D/G/S pins to the footprint's pad
    numbers; extra pads become hidden passive pins stacked on the same point. inherit: as for ic()."""
    t = _node(base)
    old = str(t[1]).split(':', 1)[-1]
    t[1] = name
    for sub in t.nodes('symbol'):                         # unit sub-symbols: "Q_NMOS_0_1" -> "<name>_0_1"
        if str(sub[1]).startswith(old + '_'):
            sub[1] = name + str(sub[1])[len(old):]
    for letter, nums in (('D', D), ('G', G), ('S', S)):
        hit = None
        for sub in t.nodes('symbol'):
            for p in sub.nodes('pin'):
                if p.get('name') == letter and p.get('number') == letter:
                    hit = (sub, p)
                    break
            if hit:
                break
        if not hit:
            raise ValueError('%s: base symbol has no pin named/numbered %s' % (name, letter))
        sub, pin = hit
        pin.need('number')[1] = nums[0]
        pos = sub.index(pin)
        for k, n in enumerate(nums[1:], 1):
            extra = pin.deepcopy()
            extra[1] = Sym(PA)                            # hidden copies passive, as for ic()
            extra.need('number')[1] = n
            extra.remove_all('hide')
            extra.insert(extra.index(extra.need('length')) + 1, Node('hide', True))
            sub.insert(pos + k, extra)
    for p in t.nodes('property'):
        if p[1] == 'Value':
            p[2] = name
        elif p[1] == 'Description' and desc:
            p[2] = desc
    if inherit is not None:
        props = t.nodes('property')
        added = _carry(list(props), inherit)[len(props):]
        pos = t.index(props[-1]) + 1
        for k, q in enumerate(added):
            t.insert(pos + k, q)
    return t


def library(symbols, generator='symgen'):
    """symbols: {name: symbol node or text} -> a kicad_sexpr SymbolLibrary (save it with .save(path))."""
    lib = SymbolLibrary.new(generator=generator)
    for sym in symbols.values():
        lib.add(_node(sym))
    return lib


def library_text(symbols, generator='symgen'):
    """symbols: {name: symbol node or text} -> the text of a .kicad_sym file, written by kicad_sexpr"""
    return dumps(library(symbols, generator).tree)


def save_library(symbols, path, nickname, project_dir=None, descr='', generator='symgen'):
    """Write ``symbols`` to ``path`` and register ``nickname`` for it in the project's sym-lib-table. The project is
    ``project_dir``, else the nearest folder at or above the library that holds a .kicad_pro (KiCad reads the table
    next to the .kicad_pro, nowhere else). Returns the table's path. Raises, before writing anything, if there is no
    project, the nickname already names another library, the file already has another nickname, the file is outside
    the project, or the table would change while a KiCad editor holds the project."""
    prj = project_dir or find_project_dir(path)
    if not prj:
        raise ValueError('no .kicad_pro at or above %s: create the project first or pass project_dir' % path)
    table = LibTable.for_project(os.path.abspath(prj), 'sym')
    changed = table.add(nickname, os.path.abspath(path), descr=descr or None, must_exist=False)   # written next
    if changed and kicad_locks.status(prj)[0] in ('OPEN', 'BUSY', 'UNSURE'):
        raise ValueError('KiCad holds %s and reads its sym-lib-table when the project opens: close it, then run again'
                         % prj)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    library(symbols, generator).save(path)
    if changed or not os.path.exists(table.path):
        table.save()
    return table.path
