#!/usr/bin/env python3
"""Routing as data: tracks, vias, zones and keepouts at coordinates you choose, written onto the board by kicad_sexpr.

  router.py check board.json plan.py                      # run the plan, print every check result, write nothing
  router.py apply BOARD.kicad_pcb board.json plan.py [-o OUT.kicad_pcb] [--append] [--previous OLD.kicad_pcb]

plan.py defines build(r), where r is a Router. board.json comes from kicad-board-review/scripts/boarddump.py (run on
the board as it is before routing). Runs in the analysis venv (needs shapely): kicad_env.sh sets $PY.

What it does for you (each one was a real DRC failure on a hand-written router):
- Pads are referenced by name: r.P('U4', '7') is the pad centre; routes follow placement changes.
- Nets come from the pads, never typed: a track that touches pads of two nets raises an error.
- Every new via is checked before it is accepted: copper clearance to other nets (pads, tracks, vias, existing and
  new), hole-to-hole distance to EVERY drilled hole whatever its net (vias and pad drills), and the board edge.
  Same-net copper is skipped for clearance but never for hole-to-hole: a stitching pass that drops a via onto a
  hand-placed via of the same net is a hole_to_hole DRC error at 0.000 mm.
- Every new track segment is checked against other-net copper on its layer and the board edge; problems are logged
  as VIOLATION (the coordinates are yours, so it does not move them) and make the CLI exit 1.
- Zone fills are not checked (KiCad refills them); DRC (check.sh) stays the authority.
- Ids are stable: --previous OLD.kicad_pcb (the routed board before regeneration, e.g. `git show HEAD:...`) gives
  each track, via, zone and keepout the uuid it had there (matched by net + geometry, zones by name); the rest get
  ids derived from the same keys, so re-running an unchanged plan writes the same bytes.

Library:
  r = Router('pack/board.json')                 # rules: max netclass clearance in board.json, then the .kicad_pro
                                                # next to the dumped board (min_hole_to_hole, min_copper_edge_clearance)
  r.track('F.Cu', 0.3, ('U2', '1'), (115.0, 121.0), ('C2', '1'))      # pads and (x, y) points, net from the pads
  r.track('B.Cu', 0.2, (1, 2), (3, 2), net='EN')                       # no pad on it: give the net
  r.via((x, y), 'GND')                          # checked; returns False and logs REJECTED if it does not fit
  r.via_near('C5', '2')                         # closest legal spot to a pad edge, plus a short link track
  r.via_field('GND', x0, y0, x1, y1, pitch=1.0) # grid of vias, skipping spots that fail a check
  r.zone(net, layer, pts, prio=10, name='VBUS_IN'); r.rect(net, layer, x0, y0, x1, y1)
  r.keepout(layer, pts, name='AGND_CHG')       # pour-free rule area (tracks, vias, pads still allowed)
  r.add_to(board)                               # write everything onto a kicad_sexpr Board (then board.save())
"""
import argparse, fnmatch, importlib.util, json, math, os, sys
from shapely.geometry import Point, LineString, Polygon
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import Board  # noqa: E402


def _r(v):
    return round(float(v), 4)


# ------------------------------------------------------------------ rules

def load_project(board_json):
    """The .kicad_pro next to the dumped board (board.json 'source'), or {}."""
    pro = os.path.splitext(board_json.get('source', ''))[0] + '.kicad_pro'
    try:
        return json.load(open(pro))
    except (ValueError, OSError):
        return {}


class NetClasses:
    """net -> clearance, from the project's net classes: explicit assignments, then patterns (wildcards), then Default.
    The clearance between two items is the larger of their two classes', as in KiCad. Custom .kicad_dru rules are not
    modelled: pass clearance= to track()/via() where such a rule allows less, and name the rule in a comment."""
    def __init__(self, pro, fallback):
        ns = pro.get('net_settings', {})
        self.cls = {c['name']: c.get('clearance', fallback) for c in ns.get('classes', [])}
        self.default = self.cls.get('Default', fallback)
        self.assign = ns.get('netclass_assignments') or {}
        self.patterns = [(p.get('pattern', ''), p.get('netclass', 'Default')) for p in ns.get('netclass_patterns') or []]
        self.cache = {}

    def __call__(self, net):
        if net not in self.cache:
            c = self.assign.get(net)
            if c is None:
                c = next((k for pat, k in self.patterns if fnmatch.fnmatchcase(net, pat)), 'Default')
            if isinstance(c, list):
                c = c[0] if c else 'Default'
            self.cache[net] = self.cls.get(c, self.default)
        return self.cache[net]


def _polys(pl):
    out = []
    for ring, holes in pl:
        if len(ring) < 3:
            continue
        p = Polygon(ring, [h for h in holes if len(h) >= 3])
        out.append(p if p.is_valid else p.buffer(0))
    return out


class Router:
    def __init__(self, board_json, clearance=None, hole_to_hole=None, edge_clearance=None, via_gap=0.1,
                 via_size=0.6, via_drill=0.3):
        self.B = json.load(open(board_json)) if isinstance(board_json, str) else board_json
        pro = load_project(self.B)
        rules = pro.get('board', {}).get('design_settings', {}).get('rules', {})
        nc = [c['clearance'] for c in self.B.get('netclass', {}).values() if c.get('clearance')]
        self.clearance = clearance if clearance is not None else max(nc or [0.2])     # zone default; summary
        self.netclr = (lambda net: clearance) if clearance is not None else NetClasses(pro, self.clearance)
        self.max_clr = max([self.clearance] + list(getattr(self.netclr, 'cls', {}).values()))
        self.hole_to_hole = hole_to_hole if hole_to_hole is not None else rules.get('min_hole_to_hole', 0.25)
        self.edge_clearance = edge_clearance if edge_clearance is not None else rules.get('min_copper_edge_clearance', 0.3)
        self.via_gap = via_gap          # copper gap between any two vias, same net included (taste, not a DRC rule)
        self.via_size, self.via_drill = via_size, via_drill
        self.layers = self.B['layers']
        edge = unary_union(_polys(self.B.get('edge', [])))
        self.inside = edge.buffer(-self.edge_clearance) if not edge.is_empty else None
        self.pads = {}
        self.items = []                 # obstacles: dict(net, layers, geom, bounds)
        self.holes = []                 # (x, y, drill, what)
        for f in self.B['footprints']:
            for p in f['pads']:
                g = unary_union(_polys(p['poly']) or [Point(p['x'], p['y']).buffer(0.1)])
                d = dict(p, ref=f['ref'], geom=g)
                self.pads.setdefault((f['ref'], str(p['num'])), []).append(d)
                if p['layers']:
                    self._add(p['net'], self.layers if p.get('th') else p['layers'], g)
                if p.get('drill'):
                    self.holes.append((p['x'], p['y'], p['drill'], 'pad %s.%s' % (f['ref'], p['num'])))
        for t in self.B.get('tracks', []):
            pts = [t['a'], t['m'], t['b']] if t.get('arc') else [t['a'], t['b']]
            g = LineString(pts).buffer(t['w'] / 2, 8) if t['a'] != t['b'] else Point(t['a']).buffer(t['w'] / 2, 8)
            self._add(t['net'], [t['layer']], g)
        self.old_vias = []
        for v in self.B.get('vias', []):
            self._add(v['net'], self.layers, Point(v['x'], v['y']).buffer(v['size'] / 2, 16))
            self.holes.append((v['x'], v['y'], v['drill'], 'via %s' % v['net']))
            self.old_vias.append(((v['x'], v['y']), v['size']))
        self.tracks, self.vias, self.zones, self.keepouts = [], [], [], []
        self.log = []
        self.violations = 0
        self.rejected = 0

    def _add(self, net, layers, geom):
        self.items.append(dict(net=net, layers=set(layers), geom=geom, bounds=geom.bounds))

    # -------------------------------------------------------------- lookups
    def pad(self, ref, num, i=0):
        try:
            return self.pads[(ref, str(num))][i]
        except KeyError:
            raise KeyError('no pad %s.%s on the board' % (ref, num)) from None

    def P(self, ref, num, i=0):
        p = self.pad(ref, num, i)
        return (_r(p['x']), _r(p['y']))

    def net(self, ref, num):
        return self.pad(ref, num)['net']

    def bounds(self, ref, num, i=0):
        return self.pad(ref, num, i)['geom'].bounds

    # -------------------------------------------------------------- checks
    def _hits(self, geom, net, layers, clearance=None):
        """other-net obstacles on any of `layers` closer to geom than the clearance between the two nets' classes
        (or the explicit clearance)"""
        mine = self.netclr(net)
        reach = clearance if clearance is not None else self.max_clr
        x0, y0, x1, y1 = geom.bounds
        x0, y0, x1, y1 = x0 - reach, y0 - reach, x1 + reach, y1 + reach
        out = []
        for it in self.items:
            if it['net'] == net or not (it['layers'] & layers):
                continue
            b = it['bounds']
            if b[0] > x1 or b[2] < x0 or b[1] > y1 or b[3] < y0:
                continue
            need = clearance if clearance is not None else max(mine, self.netclr(it['net']))
            d = geom.distance(it['geom'])
            if d < need - 0.005:      # pad polygons carry up to 0.005 mm approximation error
                out.append(dict(it, gap=d, need=need))
        return out

    def via_problem(self, pt, net, size=None, drill=None, clearance=None):
        """None if a via fits here, else the reason"""
        size, drill = size or self.via_size, drill or self.via_drill
        c = Point(pt)
        if self.inside is not None and not self.inside.contains(c.buffer(size / 2, 16)):
            return 'within %.2f mm of the board edge' % self.edge_clearance
        for x, y, d, what in self.holes:
            gap = math.dist((x, y), pt) - (d + drill) / 2
            if gap < self.hole_to_hole:
                return 'hole-to-hole %.3f mm to %s (min %.2f)' % (max(gap, 0), what, self.hole_to_hole)
        for at, s in self.old_vias + [(v['at'], v['size']) for v in self.vias]:
            if math.dist(at, pt) < (s + size) / 2 + self.via_gap:
                return 'copper overlaps / within %.2f mm of the via at %s' % (self.via_gap, tuple(at))
        hit = self._hits(c.buffer(size / 2, 16), net, set(self.layers), clearance)
        if hit:
            return 'clearance %.3f mm to %s copper (min %.2f)' % (hit[0]['gap'], hit[0]['net'], hit[0]['need'])
        return None

    def seg_problem(self, a, b, net, w, layer, clearance=None):
        g = LineString([a, b]).buffer(w / 2, 8) if a != b else Point(a).buffer(w / 2, 8)
        if self.inside is not None and not self.inside.contains(g):
            return 'within %.2f mm of the board edge' % self.edge_clearance
        hit = self._hits(g, net, {layer}, clearance)
        if hit:
            return 'clearance %.3f mm to %s copper on %s (min %.2f)' % (hit[0]['gap'], hit[0]['net'], layer, hit[0]['need'])
        return None

    # -------------------------------------------------------------- primitives
    def track(self, layer, width, *pts, net=None, check=True, clearance=None):
        """pts: (x, y) points or ('REF', 'PIN') pad references; consecutive points become segments."""
        res = []
        for q in pts:
            if isinstance(q[0], str):
                pn = self.net(*q)
                if net is None:
                    net = pn
                elif pn != net:
                    raise ValueError('track on net %s touches %s.%s, which is net %s' % (net, q[0], q[1], pn))
                res.append(self.P(*q))
            else:
                res.append((_r(q[0]), _r(q[1])))
        if not net:
            raise ValueError('track needs a net: start or end it on a pad, or pass net=')
        for a, b in zip(res, res[1:]):
            if a == b:
                continue
            if check:
                why = self.seg_problem(a, b, net, width, layer, clearance)
                if why:
                    self.violations += 1
                    self.log.append('VIOLATION track %s %s %s -> %s: %s' % (net, layer, a, b, why))
            t = dict(layer=layer, w=width, a=a, b=b, net=net)
            self.tracks.append(t)
            self._add(net, [layer], LineString([a, b]).buffer(width / 2, 8))
        return res[-1]

    def _put_via(self, pt, net, size, drill):
        pt = (_r(pt[0]), _r(pt[1]))
        self.vias.append(dict(at=pt, net=net, size=size, drill=drill))
        self.holes.append((pt[0], pt[1], drill, 'new via %s' % net))
        self._add(net, self.layers, Point(pt).buffer(size / 2, 16))
        return pt

    def via(self, pt, net, size=None, drill=None, check=True, quiet=False, clearance=None):
        size, drill = size or self.via_size, drill or self.via_drill
        if check:
            why = self.via_problem(pt, net, size, drill, clearance)
            if why:
                if not quiet:
                    self.rejected += 1
                    self.log.append('REJECTED via %s at %s: %s' % (net, tuple(pt), why))
                return False
        self._put_via(pt, net, size, drill)
        return True

    def via_near(self, ref, num, net=None, size=None, drill=None, max_r=2.0, prefer=None, link=True, link_w=0.5):
        """Via as close as possible to a pad edge (searching outward), checked; prefer=(dx, dy) biases the side."""
        size, drill = size or self.via_size, drill or self.via_drill
        net = net or self.net(ref, num)
        p = self.pad(ref, num)
        x0, y0, x1, y1 = p['geom'].bounds
        cx, cy, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
        lw = min(link_w, 2 * min(hw, hh))
        lay = 'F.Cu' if p.get('th') or not p['layers'] else p['layers'][0]
        r = size / 2 + 0.15
        while r <= max_r:
            cands = []
            for k in range(32):
                a = 2 * math.pi * k / 32
                q = (cx + (hw + r) * math.cos(a), cy + (hh + r) * math.sin(a))
                bias = 0 if prefer is None else -0.3 * (math.cos(a) * prefer[0] + math.sin(a) * prefer[1])
                cands.append((r + bias, q))
            for _, q in sorted(cands):
                if self.via_problem(q, net, size, drill) is None and \
                        (not link or self.seg_problem((cx, cy), q, net, lw, lay) is None):
                    q = self._put_via(q, net, size, drill)
                    if link:
                        self.tracks.append(dict(layer=lay, w=_r(lw), a=self.P(ref, num), b=q, net=net))
                        self._add(net, [lay], LineString([self.P(ref, num), q]).buffer(lw / 2, 8))
                    return q
            r += 0.1
        self.rejected += 1
        self.log.append('REJECTED via_near %s.%s (%s): no legal spot within %.1f mm' % (ref, num, net, max_r))
        return None

    def via_field(self, net, x0, y0, x1, y1, pitch=1.0, size=None, drill=None):
        n = skipped = 0
        y = y0
        while y <= y1 + 1e-6:
            x = x0
            while x <= x1 + 1e-6:
                if self.via((x, y), net, size, drill, quiet=True):
                    n += 1
                else:
                    skipped += 1
                x += pitch
            y += pitch
        self.log.append('via_field %s (%.2f,%.2f)-(%.2f,%.2f): %d placed, %d spots skipped' % (net, x0, y0, x1, y1, n, skipped))
        return n

    def zone(self, net, layer, pts, prio=0, solid=True, name='', clearance=None, min_thick=0.2,
             thermal_gap=0.3, thermal_bridge=0.4):
        self.zones.append(dict(net=net, layer=layer, pts=[(_r(x), _r(y)) for x, y in pts], prio=prio, solid=solid,
                               name=name, clearance=clearance if clearance is not None else self.clearance,
                               min_thick=min_thick, thermal_gap=thermal_gap, thermal_bridge=thermal_bridge))

    def rect(self, net, layer, x0, y0, x1, y1, **kw):
        self.zone(net, layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], **kw)

    def keepout(self, layer, pts, name='', forbid=('copperpour',)):
        """Rule area. Default: pours kept out, tracks/vias/pads allowed (an analog-ground island).
        layer may be one name or a list."""
        layers = [layer] if isinstance(layer, str) else list(layer)
        self.keepouts.append(dict(layers=layers, pts=[(_r(x), _r(y)) for x, y in pts], name=name, forbid=set(forbid)))

    # -------------------------------------------------------------- output
    def add_to(self, board):
        """Write the tracks, vias, zones and keepouts onto a kicad_sexpr Board (vias are free: they keep their net)."""
        for tr in self.tracks:
            board.segment(tr['a'], tr['b'], tr['w'], tr['layer'], tr['net'])
        for v in self.vias:
            board.via(v['at'], v['size'], v['drill'], v['net'], free=True)
        for z in self.zones:
            board.zone(z['net'], z['layer'], z['pts'], priority=z['prio'], name=z['name'], clearance=z['clearance'],
                       min_thickness=z['min_thick'], connect_pads='yes' if z['solid'] else None,
                       thermal_gap=z['thermal_gap'], thermal_bridge_width=z['thermal_bridge'])
        for k in self.keepouts:
            board.rule_area(k['layers'], k['pts'], name=k['name'], tracks='tracks' not in k['forbid'],
                            vias='vias' not in k['forbid'], pads='pads' not in k['forbid'],
                            copperpour='copperpour' not in k['forbid'], footprints='footprints' not in k['forbid'])
        return board

    def summary(self):
        return ('%d segments, %d vias, %d zones, %d keepouts; %d track violations, %d rejected vias '
                '(rules: net-class clearances up to %.2f, hole-to-hole %.2f, edge %.2f mm)') % (
            len(self.tracks), len(self.vias), len(self.zones), len(self.keepouts), self.violations, self.rejected,
            self.clearance, self.hole_to_hole, self.edge_clearance)


def insert_routes(board, router, append=False):
    """Add the router's items to a kicad_sexpr Board; refuses a board that already has top-level tracks, vias or
    zones unless append=True."""
    if not append and any(board.items(h) for h in ('segment', 'via', 'zone')):
        raise SystemExit('the board already has top-level tracks, vias or zones: regenerate it from its unrouted base '
                         '(the plan is the record), or pass --append to add to it')
    return router.add_to(board)


def _load_plan(path):
    spec = importlib.util.spec_from_file_location('route_plan', path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check'); c.add_argument('board_json'); c.add_argument('plan')
    a = sub.add_parser('apply'); a.add_argument('pcb'); a.add_argument('board_json'); a.add_argument('plan')
    a.add_argument('-o', '--out'); a.add_argument('--append', action='store_true')
    a.add_argument('--previous', help='routed board whose track / via / zone ids to keep')
    for p in (c, a):
        p.add_argument('--clearance', type=float); p.add_argument('--hole-to-hole', type=float)
        p.add_argument('--edge-clearance', type=float)
    args = ap.parse_args()
    r = Router(args.board_json, args.clearance, args.hole_to_hole, args.edge_clearance)
    _load_plan(args.plan).build(r)
    for line in r.log:
        print('  ' + line)
    print(r.summary())
    if args.cmd == 'apply':
        out = args.out or args.pcb
        board = Board.load(args.pcb)
        if args.previous:
            ids = board.reuse_ids(args.previous)
            if ids.ambiguous:
                print('note: %d keys occur more than once in %s (matched in file order), e.g. %s' % (
                    len(ids.ambiguous), args.previous, ids.ambiguous[:3]))
        insert_routes(board, r, args.append).save(out)
        if args.previous:
            print('%d ids kept from %s' % (board.uuids.reused, args.previous))
        print('wrote', out)
    sys.exit(1 if r.violations or r.rejected else 0)


if __name__ == '__main__':
    main()
