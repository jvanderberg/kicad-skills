#!/usr/bin/env python3
"""Build a .kicad_pcb from a schematic's netlist: footprints, symbol links, pad nets, fields, outline, placement.

Plain python 3 (no pcbnew needed; $KICAD_PYTHON works too):
  python3 new_board.py NETLIST.xml OUT.kicad_pcb [--layers 4] [--outline 50x40] [--origin 100,100]
        [--corner-r 1] [--placement place.json] [--labels labels.json] [--refs silk|fab|hidden] [--project-dir DIR]

KiCad has no command-line "update PCB from schematic". This does what that does for a NEW board, from
`kicad-cli sch export netlist --format kicadxml`, writing every item through kicad_sexpr (Board.add_footprint places
and flips footprints the way pcbnew does, checked item by item against pcbnew in kicad_sexpr's tests):
- loads each footprint from the project's fp-lib-table (${KIPRJMOD}) or KiCad's global table / library directory;
- sets reference, value, the symbol link (sheet path + symbol uuid, so schematic parity works) and every pad's net,
  escaping "/" as {slash} in auto-generated net names (kicad_sexpr.board_net_name);
- adds every other schematic field (LCSC, MPN, ...) as a hidden footprint property (an existing library property of
  the same name gets the value);
- carries the schematic's assembly attributes to the footprint: DNP -> dnp, not in BOM -> exclude_from_bom, not in
  position files -> exclude_from_pos_files (the symbol wins over the library footprint, as KiCad's update does); a
  symbol excluded from the board gets no footprint. BOM, position file and schematic parity then agree by construction;
- --placement JSON {"REF": [x, y, rot] or [x, y, rot, "B"]} in mm relative to --origin (the outline's top-left);
  unplaced parts are staged in a grid to the right of the outline;
- --outline WxH draws Edge.Cuts (rounded corners with --corner-r);
- --labels JSON {"REF": ["TEXT", dx, dy] or ["TEXT", dx, dy, rot]} puts a function label next to a footprint on
  F.SilkS and, mirrored, on B.SilkS (solder pads and connectors: say what each one is, see layout-rules.md);
- --refs: where references go (silk = KiCad default; fab = only on F.Fab for a dense assembled board; hidden);
- writes a minimal .kicad_pro next to OUT if there is none (KiCad fills in its defaults; board_setup.py edits it);
- keeps ids stable: every footprint (and item in it) keeps the uuid it had in --previous (default: OUT, if it
  exists), matched by reference; new parts get ids derived from their reference, so an unchanged design regenerates
  byte-identical. --previous none starts from scratch (still deterministic).
Then: board_setup.py (stackup, rules, net classes), placement, routing (router.py), check.sh.
Regenerating overwrites OUT: GUI edits made since are lost unless folded into the placement file first.
"""
import argparse, json, os, re, sys, xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import Board, Node, Project, Sym, board_net_name, load  # noqa: E402

# footprint attributes the schematic owns (netlist property -> footprint attr token), and KiCad's order in (attr ...)
SCH_ATTRS = (('exclude_from_pos_files', 'exclude_from_pos_files'), ('exclude_from_bom', 'exclude_from_bom'), ('dnp', 'dnp'))
ATTR_ORDER = ('smd', 'through_hole', 'board_only', 'exclude_from_pos_files', 'exclude_from_bom', 'allow_soldermask_bridges',
              'allow_missing_courtyard', 'dnp')


def set_sch_attrs(fp, flags):
    """set the footprint's DNP / exclude_from_bom / exclude_from_pos_files to the schematic's (the symbol wins, as in
    KiCad's update from schematic); library-only attributes (smd, through_hole, board_only, ...) are kept"""
    node = fp.node
    attr = node.find('attr')
    if attr is None:
        attr = Node('attr')
        anchor = next((node.find(h) for h in ('sheetfile', 'sheetname', 'path') if node.find(h) is not None), None)
        props = node.nodes('property')
        pos = node.index(anchor) + 1 if anchor is not None else (node.index(props[-1]) + 1 if props else len(node))
        node.insert(pos, attr)
    toks = [str(x) for x in attr[1:]]
    managed = {tok for _, tok in SCH_ATTRS}
    keep = [t for t in toks if t not in managed] + [tok for prop, tok in SCH_ATTRS if prop in flags]
    keep = sorted(dict.fromkeys(keep), key=lambda t: ATTR_ORDER.index(t) if t in ATTR_ORDER else len(ATTR_ORDER))
    del attr[1:]
    attr.extend(Sym(t) for t in keep)
    if not keep:
        node.remove_node(attr)


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
    """{nickname: library directory} from an fp-lib-table, with ${VAR} expanded (KIPRJMOD = prjdir)."""
    libs = {}
    if not path or not os.path.exists(path):
        return libs
    env = dict(os.environ, KIPRJMOD=prjdir)
    env.setdefault('KICAD10_FOOTPRINT_DIR', kicad_fp_dir()); env.setdefault('KICAD9_FOOTPRINT_DIR', kicad_fp_dir())
    for lib in load(path).nodes('lib'):
        name, uri = lib.get('name'), lib.get('uri')
        if name is not None and uri is not None:
            libs[str(name)] = re.sub(r'\$\{(\w+)\}', lambda m: env.get(m.group(1), m.group(0)), str(uri))
    return libs


# ------------------------------------------------------------------ board

def show_fab_reference(fp):
    """Make the footprint's F.Fab "${REFERENCE}" text visible (what pcbnew's SetVisible(True) does)."""
    for txt in fp.node.nodes('fp_text'):
        if str(txt[2]) == '${REFERENCE}' and str(txt.get('layer')) == 'F.Fab':
            txt.remove_all('hide')
            eff = txt.find('effects')
            if eff is not None:
                eff.remove_all('hide')


def natkey(s):
    return [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', s)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('netlist'); ap.add_argument('out')
    ap.add_argument('--layers', type=int, default=4); ap.add_argument('--outline'); ap.add_argument('--origin', default='100,100')
    ap.add_argument('--corner-r', type=float, default=0.0)
    ap.add_argument('--placement'); ap.add_argument('--labels'); ap.add_argument('--refs', default='silk', choices=['silk', 'fab', 'hidden'])
    ap.add_argument('--project-dir', help='where fp-lib-table and ${KIPRJMOD} point (default: the output directory)')
    ap.add_argument('--previous', help='board whose item ids to keep (default: OUT if it exists; "none" = none)')
    a = ap.parse_args()
    prj = os.path.abspath(a.project_dir or os.path.dirname(os.path.abspath(a.out)))
    libs = read_fp_table(global_fp_table(), prj)
    libs.update(read_fp_table(os.path.join(prj, 'fp-lib-table'), prj))
    ox, oy = map(float, a.origin.split(','))
    place = json.load(open(a.placement)) if a.placement else {}
    labels = json.load(open(a.labels)) if a.labels else {}

    root = ET.parse(a.netlist).getroot()
    comps, missing, offboard = [], [], []
    for c in root.find('components'):
        ref, fp = c.get('ref'), c.findtext('footprint') or ''
        if not fp:
            missing.append(ref)
            continue
        sp = c.find('sheetpath')
        path = (sp.get('tstamps') if sp is not None else '/') + (c.findtext('tstamps') or '').strip()
        f = {e.get('name'): (e.text or '') for e in (c.find('fields') or [])}
        # every schematic field is carried to the footprint, Datasheet and Description included (KiCad also writes
        # them as <datasheet>/<description> elements; use those when the field list lacks them)
        for k, tag in (('Datasheet', 'datasheet'), ('Description', 'description')):
            if not (f.get(k) or '').strip() and (c.findtext(tag) or '').strip():
                f[k] = c.findtext(tag).strip()
        f = {k: v for k, v in f.items() if k not in ('Reference', 'Value', 'Footprint')}
        # the schematic's assembly attributes (do not populate, not in the BOM, not in the position file): carried to
        # the footprint, so the BOM, the CPL and schematic parity agree by construction
        flags = {p.get('name') for p in c.findall('property')}
        if 'exclude_from_board' in flags:
            offboard.append(ref)
            continue
        comps.append(dict(ref=ref, value=c.findtext('value') or '', fp=fp, path=path, fields=f, flags=flags))
    pins = {(n.get('ref'), n.get('pin')): board_net_name(net.get('name'))
            for net in root.find('nets') for n in net.findall('node')}

    previous = a.previous if a.previous is not None else (a.out if os.path.exists(a.out) else 'none')
    b = Board.new(copper_layers=a.layers)
    if previous != 'none':
        ids = b.reuse_ids(previous)
        if ids.ambiguous:
            print('note: %d ids in %s have ambiguous keys (matched in file order): %s' % (
                len(ids.ambiguous), previous, ', '.join(ids.ambiguous[:5])))
    nets, nfields = set(), 0
    nattr = {prop: 0 for prop, _ in SCH_ATTRS}
    w, h = map(float, a.outline.lower().split('x')) if a.outline else (0.0, 0.0)
    staged = 0
    for c in sorted(comps, key=lambda c: natkey(c['ref'])):
        lib, name = c['fp'].split(':', 1)
        if lib not in libs:
            sys.exit('%s: footprint library "%s" is in neither the project nor the global fp-lib-table' % (c['ref'], lib))
        src = os.path.join(libs[lib], name + '.kicad_mod')
        if not os.path.exists(src):
            sys.exit('%s: footprint %s not found (%s)' % (c['ref'], c['fp'], src))
        pl = place.get(c['ref'])
        if pl:
            at, rot, side = (ox + pl[0], oy + pl[1]), (pl[2] if len(pl) > 2 else 0), ('B' if len(pl) > 3 and pl[3] == 'B' else 'F')
        else:
            col, row = divmod(staged, 12)
            at, rot, side = (ox + w + 15 + col * 10, oy + row * 8), 0, 'F'
            staged += 1
        fp = b.add_footprint(src, c['fp'], c['ref'], c['value'], at, rot, side, path=c['path'], fields=c['fields'])
        set_sch_attrs(fp, c['flags'])
        for prop, _ in SCH_ATTRS:
            if prop in c['flags']:
                nattr[prop] += 1
        nfields += len(c['fields'])
        pad_nums = {str(p[1]) for p in fp.pads()}
        for num in sorted(pad_nums):
            n = pins.get((c['ref'], num))
            if n:
                fp.set_pad_net(num, n)
                nets.add(n)
        if a.refs != 'silk':
            fp.set_field('Reference', c['ref'], hide=True)
            if a.refs == 'fab':
                show_fab_reference(fp)
    for ref, spec in labels.items():
        try:
            fp = b.footprint(ref)
        except KeyError:
            sys.exit('--labels: no footprint %s' % ref)
        text, dx, dy = spec[0], spec[1], spec[2]
        rot = spec[3] if len(spec) > 3 else 0
        fp.set_field('Reference', ref, hide=True)
        x, y = fp.at[0] + dx, fp.at[1] + dy
        b.gr_text(text, (x, y), 'F.SilkS', size=1.0, thickness=0.15, angle=rot)
        b.gr_text(text, (x, y), 'B.SilkS', size=1.0, thickness=0.15, angle=rot)    # mirrored: B.* layer
    if a.outline:
        b.outline_rect(ox, oy, w, h, corner_radius=a.corner_r, width=0.1)
    b.save(a.out)
    pro = os.path.splitext(a.out)[0] + '.kicad_pro'
    if not os.path.exists(pro):
        Project.new(pro).save()
    print('wrote %s: %d footprints (%d placed, %d staged), %d nets, %d fields, %d ids kept; attributes from the schematic: '
          '%d dnp, %d exclude_from_bom, %d exclude_from_pos_files%s%s' % (
              a.out, len(comps), len(comps) - staged, staged, len(nets), nfields, b.uuids.reused, nattr['dnp'],
              nattr['exclude_from_bom'], nattr['exclude_from_pos_files'],
              '; not on the board (schematic says exclude from board): ' + ' '.join(offboard) if offboard else '',
              '; no footprint assigned: ' + ' '.join(missing) if missing else ''))


if __name__ == '__main__':
    main()
