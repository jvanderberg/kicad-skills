#!/usr/bin/env python3
"""Build a .kicad_pcb from a schematic's netlist: footprints, symbol links, pad nets, fields, outline, placement.

Run with KiCad's bundled python (it has pcbnew; kicad_env.sh sets $KICAD_PYTHON):
  $KICAD_PYTHON new_board.py NETLIST.xml OUT.kicad_pcb [--layers 4] [--outline 50x40] [--origin 100,100]
        [--corner-r 1] [--placement place.json] [--labels labels.json] [--refs silk|fab|hidden] [--project-dir DIR]

KiCad has no command-line "update PCB from schematic". This does what that does for a NEW board, from
`kicad-cli sch export netlist --format kicadxml`:
- loads each footprint from the project's fp-lib-table (${KIPRJMOD}) or KiCad's global table / library directory,
  with the cast, Duplicate() and SetFPID() that pcbnew-api.md's failure table requires;
- sets reference, value, the symbol link (sheet path + symbol uuid, so schematic parity works) and every pad's net,
  escaping "/" as {slash} in auto-generated net names;
- writes the board, then adds every other schematic field (LCSC, MPN, ...) as a hidden footprint property, as text
  (SetField would put visible text on F.SilkS);
- --placement JSON {"REF": [x, y, rot] or [x, y, rot, "B"]} in mm relative to --origin (the outline's top-left);
  unplaced parts are staged in a grid to the right of the outline;
- --outline WxH draws Edge.Cuts (rounded corners with --corner-r);
- --labels JSON {"REF": ["TEXT", dx, dy] or ["TEXT", dx, dy, rot]} puts a function label next to a footprint on
  F.SilkS and, mirrored, on B.SilkS (solder pads and connectors: say what each one is, see layout-rules.md);
- --refs: where references go (silk = KiCad default; fab = only on F.Fab for a dense assembled board; hidden).
Then: board_setup.py (stackup, rules, net classes), placement, routing (router.py), check.sh.
Regenerating overwrites OUT: GUI edits made since are lost unless folded into the placement file first.
"""
import argparse, json, math, os, re, sys, xml.etree.ElementTree as ET
import uuid

import pcbnew

MM = pcbnew.FromMM


# ------------------------------------------------------------------ libraries

def kicad_fp_dir():
    for c in (os.environ.get('KICAD10_FOOTPRINT_DIR'), os.environ.get('KICAD9_FOOTPRINT_DIR'),
              '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints', '/usr/share/kicad/footprints',
              'C:/Program Files/KiCad/10.0/share/kicad/footprints'):
        if c and os.path.isdir(c):
            return c
    return ''


def global_fp_table():
    home = os.path.expanduser('~')
    for c in (os.path.join(home, 'Library/Preferences/kicad/10.0/fp-lib-table'), os.path.join(home, '.config/kicad/10.0/fp-lib-table'),
              os.path.join(os.environ.get('APPDATA', ''), 'kicad/10.0/fp-lib-table'),
              os.path.join(home, 'Library/Preferences/kicad/9.0/fp-lib-table'), os.path.join(home, '.config/kicad/9.0/fp-lib-table')):
        if os.path.exists(c):
            return c
    return None


def read_fp_table(path, prjdir):
    libs = {}
    if not path or not os.path.exists(path):
        return libs
    env = dict(os.environ, KIPRJMOD=prjdir)
    env.setdefault('KICAD10_FOOTPRINT_DIR', kicad_fp_dir()); env.setdefault('KICAD9_FOOTPRINT_DIR', kicad_fp_dir())
    for name, uri in re.findall(r'\(lib\s+\(name\s+"?([^")]+)"?\)\s*\(type\s+"?[^")]+"?\)\s*\(uri\s+"?([^")]+)"?\)', open(path).read()):
        libs[name] = re.sub(r'\$\{(\w+)\}', lambda m: env.get(m.group(1), m.group(0)), uri)
    return libs


# ------------------------------------------------------------------ text pass (s-expression writers)

def kstr(s):
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def hidden_property_sexpr(key, value):
    return ('\t\t(property %s %s\n\t\t\t(at 0 0 0)\n\t\t\t(layer "F.Fab")\n\t\t\t(hide yes)\n\t\t\t(uuid "%s")\n'
            '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n\t\t\t\t\t(thickness 0.15)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n') % (
        kstr(key), kstr(value), uuid.uuid4())


def add_fields(t, fields):
    """fields {ref: {name: value}}: set existing footprint properties' values, add the rest as hidden properties."""
    n = 0
    starts = [m.start() for m in re.finditer(r'\n\t\(footprint "', t)] + [len(t)]
    out, pos = [], 0
    for s, e in zip(starts, starts[1:]):
        seg = t[s:e]
        m = re.search(r'\(property "Reference" "((?:\\.|[^"\\])*)"', seg)
        ref = m.group(1) if m else None
        if ref in fields:
            add = ''
            for k, v in fields[ref].items():
                pat = re.compile(r'\(property %s "(?:\\.|[^"\\])*"' % re.escape(kstr(k)))
                if pat.search(seg):
                    seg = pat.sub(lambda _m: '(property %s %s' % (kstr(k), kstr(v)), seg, count=1)
                else:
                    add += hidden_property_sexpr(k, v)
                n += 1
            i = seg.index('\t\t(property "Reference"')
            seg = seg[:i] + add + seg[i:]
        out.append(t[pos:s]); out.append(seg); pos = e
    out.append(t[pos:])
    return ''.join(out), n


# ------------------------------------------------------------------ board

def board_text_item(b, text, layer, x, y, rot=0, mirror=False, size=1.0):
    t = pcbnew.PCB_TEXT(b)
    t.SetText(text); t.SetLayer(layer); t.SetMirrored(mirror)
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size))); t.SetTextThickness(MM(0.15))
    t.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    if rot:
        t.SetTextAngle(pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T))
    b.Add(t)


def outline(b, x0, y0, w, h, r):
    def seg(a, c):
        s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(MM(a[0]), MM(a[1]))); s.SetEnd(pcbnew.VECTOR2I(MM(c[0]), MM(c[1])))
        s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(MM(0.1)); b.Add(s)
    if r <= 0:
        pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
        for i in range(4):
            seg(pts[i], pts[(i + 1) % 4])
        return
    seg((x0 + r, y0), (x0 + w - r, y0)); seg((x0 + w, y0 + r), (x0 + w, y0 + h - r))
    seg((x0 + w - r, y0 + h), (x0 + r, y0 + h)); seg((x0, y0 + h - r), (x0, y0 + r))
    for cx, cy, sa in ((x0 + w - r, y0 + r, 270), (x0 + w - r, y0 + h - r, 0), (x0 + r, y0 + h - r, 90), (x0 + r, y0 + r, 180)):
        s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetCenter(pcbnew.VECTOR2I(MM(cx), MM(cy)))
        s.SetStart(pcbnew.VECTOR2I(MM(cx + r * math.cos(math.radians(sa))), MM(cy + r * math.sin(math.radians(sa)))))
        s.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(90, pcbnew.DEGREES_T))
        s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(MM(0.1)); b.Add(s)


def natkey(s):
    return [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', s)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('netlist'); ap.add_argument('out')
    ap.add_argument('--layers', type=int, default=4); ap.add_argument('--outline'); ap.add_argument('--origin', default='100,100')
    ap.add_argument('--corner-r', type=float, default=0.0)
    ap.add_argument('--placement'); ap.add_argument('--labels'); ap.add_argument('--refs', default='silk', choices=['silk', 'fab', 'hidden'])
    ap.add_argument('--project-dir', help='where fp-lib-table and ${KIPRJMOD} point (default: the output directory)')
    a = ap.parse_args()
    prj = os.path.abspath(a.project_dir or os.path.dirname(os.path.abspath(a.out)))
    libs = read_fp_table(global_fp_table(), prj)
    libs.update(read_fp_table(os.path.join(prj, 'fp-lib-table'), prj))
    ox, oy = map(float, a.origin.split(','))
    place = json.load(open(a.placement)) if a.placement else {}
    labels = json.load(open(a.labels)) if a.labels else {}

    root = ET.parse(a.netlist).getroot()
    comps, fields, missing = [], {}, []
    for c in root.find('components'):
        ref, fp = c.get('ref'), c.findtext('footprint') or ''
        if not fp:
            missing.append(ref)
            continue
        sp = c.find('sheetpath')
        path = (sp.get('tstamps') if sp is not None else '/') + (c.findtext('tstamps') or '').strip()
        f = {e.get('name'): (e.text or '') for e in (c.find('fields') or [])}
        f = {k: v for k, v in f.items() if k not in ('Reference', 'Value', 'Footprint')}
        if f:
            fields[ref] = f
        comps.append(dict(ref=ref, value=c.findtext('value') or '', fp=fp, path=path))
    pins = {(n.get('ref'), n.get('pin')): net.get('name') for net in root.find('nets') for n in net.findall('node')}

    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(a.layers)
    nets = {}

    def net(name):
        if name.startswith(('Net-(', 'unconnected-(')):
            name = name.replace('/', '{slash}')       # how KiCad stores "/" in auto-generated net names
        if name not in nets:
            nets[name] = pcbnew.NETINFO_ITEM(b, name)
            b.Add(nets[name])
        return nets[name]

    w, h = map(float, a.outline.lower().split('x')) if a.outline else (0.0, 0.0)
    staged = 0
    for c in sorted(comps, key=lambda c: natkey(c['ref'])):
        lib, name = c['fp'].split(':', 1)
        if lib not in libs:
            sys.exit('%s: footprint library "%s" is in neither the project nor the global fp-lib-table' % (c['ref'], lib))
        f = pcbnew.Cast_to_FOOTPRINT(pcbnew.FootprintLoad(libs[lib], name).Duplicate(False))
        f.SetFPID(pcbnew.LIB_ID(lib, name))
        f.SetReference(c['ref']); f.SetValue(c['value'])
        f.SetPath(pcbnew.KIID_PATH(c['path']))
        b.Add(f)
        pl = place.get(c['ref'])
        if pl:
            if len(pl) > 3 and pl[3] == 'B':
                f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
            f.SetPosition(pcbnew.VECTOR2I(MM(ox + pl[0]), MM(oy + pl[1])))
            f.SetOrientationDegrees(pl[2] if len(pl) > 2 else 0)
        else:
            col, row = divmod(staged, 12)
            f.SetPosition(pcbnew.VECTOR2I(MM(ox + w + 15 + col * 10), MM(oy + row * 8)))
            staged += 1
        for p in f.Pads():
            n = pins.get((c['ref'], p.GetNumber()))
            if n:
                p.SetNet(net(n))
        if a.refs != 'silk':
            f.Reference().SetVisible(False)
            if a.refs == 'fab':
                for item in f.GraphicalItems():
                    if isinstance(item, pcbnew.PCB_TEXT) and item.GetText() == '${REFERENCE}' and item.GetLayer() == pcbnew.F_Fab:
                        item.SetVisible(True)
    for ref, spec in labels.items():
        f = b.FindFootprintByReference(ref)
        if f is None:
            sys.exit('--labels: no footprint %s' % ref)
        text, dx, dy = spec[0], spec[1], spec[2]
        rot = spec[3] if len(spec) > 3 else 0
        f.Reference().SetVisible(False)
        x, y = pcbnew.ToMM(f.GetPosition().x) + dx, pcbnew.ToMM(f.GetPosition().y) + dy
        board_text_item(b, text, pcbnew.F_SilkS, x, y, rot)
        board_text_item(b, text, pcbnew.B_SilkS, x, y, rot, mirror=True)
    if a.outline:
        outline(b, ox, oy, w, h, a.corner_r)
    pcbnew.SaveBoard(a.out, b)
    t, n = add_fields(open(a.out, encoding='utf-8').read(), fields)
    open(a.out, 'w', encoding='utf-8').write(t)
    print('wrote %s: %d footprints (%d placed, %d staged), %d nets, %d fields%s' % (
        a.out, len(comps), len(comps) - staged, staged, len(nets), n,
        '; no footprint assigned: ' + ' '.join(missing) if missing else ''))


if __name__ == '__main__':
    main()
