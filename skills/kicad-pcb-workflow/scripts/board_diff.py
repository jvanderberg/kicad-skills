#!/usr/bin/env python3
"""What changed between two versions of a board, grouped so a human can check it was all intended.

  board_diff.py OLD.kicad_pcb NEW.kicad_pcb [--expect x0,y0,x1,y1 ...] [--expect-refs R1,R2,...] [--expect-nets N1,N2]
  board_diff.py HEAD NEW.kicad_pcb ...        # OLD may be a git revision of the board in the current repo

Lists footprints added / removed / moved / swapped, copper (tracks, arcs, vias) only in OLD or only in NEW grouped by
net, layer and area, zones whose outline changed, and board text/graphics that moved. Anything outside the --expect
boxes, refs and nets is printed under "UNEXPECTED".

Run it before copying a scripted change back into the user's project, against the committed version. It catches the
silent failure where a rebuild started from an older snapshot and quietly reverted the user's own later edits.
"""
import argparse, collections, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import blocks

ap = argparse.ArgumentParser(); ap.add_argument('old'); ap.add_argument('new')
ap.add_argument('--expect', action='append', default=[]); ap.add_argument('--expect-refs', default=''); ap.add_argument('--expect-nets', default='')
a = ap.parse_args()
def load(p):
    if os.path.exists(p): return open(p).read()
    path = os.path.basename(a.new) if p in ('HEAD',) or ':' not in p else p.split(':', 1)[1]
    rev = p.split(':', 1)[0]
    return subprocess.run(['git', 'show', '%s:%s' % (rev, path)], capture_output=True, text=True, check=True,
                          cwd=os.path.dirname(os.path.abspath(a.new))).stdout
O, N = load(a.old), load(a.new)
boxes = [tuple(map(float, b.split(','))) for b in a.expect]
xrefs = set(filter(None, a.expect_refs.split(','))); xnets = set(filter(None, a.expect_nets.split(',')))
def inbox(p): return any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for x0, y0, x1, y1 in boxes)
def top(t, head): return [(s, b) for s, b in blocks(t, head) if t[s - 2:s] == '\n\t']
def pts(b): return [(round(float(x), 3), round(float(y), 3)) for x, y in re.findall(r'\((?:start|mid|end|at|xy) ([-\d.]+) ([-\d.]+)', b)]
def net(b):
    m = re.search(r'\(net (?:\d+ )?"([^"]*)"\)', b) or re.search(r'\(net_name "([^"]*)"\)', b); return m.group(1) if m else ''

def fps(t):
    o = {}
    for s, b in top(t, 'footprint'):
        r = re.search(r'\(property "Reference" "([^"]+)"', b)
        if r: o[r.group(1)] = (re.match(r'\(footprint "([^"]+)"', b).group(1), tuple(float(v) for v in re.search(r'\(at ([-\d. ]+)\)', b).group(1).split()))
    return o
fo, fn = fps(O), fps(N)
unexpected = []
print('## Footprints')
for r in sorted(set(fo) | set(fn), key=lambda s: [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', s)]):
    o, n = fo.get(r), fn.get(r)
    if o == n: continue
    what = 'added %s at %s' % n if not o else 'removed (was %s at %s)' % o if not n else \
           ('swapped %s -> %s' % (o[0], n[0]) if o[0] != n[0] else '') + (' moved %s -> %s' % (o[1], n[1]) if o[1] != n[1] else '')
    ok = r in xrefs or all(inbox(p[1][:2]) for p in (o, n) if p)
    print('- %s %s%s' % (r, what.strip(), '' if ok else '   <-- UNEXPECTED')); ok or unexpected.append(r)

def copper(t):
    o = {}
    for head in ('segment', 'arc', 'via'):
        for s, b in top(t, head):
            lay = re.search(r'\(layers? ([^)]*)\)', b)
            o[(head, net(b), lay.group(1) if lay else '', tuple(pts(b)))] = 1
    return o
co, cn = copper(O), copper(N)
print('\n## Copper (tracks, arcs, vias), grouped by net / layer')
for tag, A, Bx in (('only in OLD', co, cn), ('only in NEW', cn, co)):
    g = collections.defaultdict(list)
    for k in A:
        if k not in Bx: g[(k[1], k[2], k[0])].append(k[3])
    print('### %s' % tag)
    for (n_, lay, head), v in sorted(g.items()):
        P = [p for q in v for p in q]
        ok = n_ in xnets or all(inbox(p) for p in P)
        print('- %-22s %-18s %-7s %3d  x %.1f-%.1f  y %.1f-%.1f%s' % (n_, lay, head, len(v), min(p[0] for p in P), max(p[0] for p in P),
              min(p[1] for p in P), max(p[1] for p in P), '' if ok else '   <-- UNEXPECTED'))
        ok or unexpected.append('%s %s' % (n_, lay))

def outline(b): return tuple(pts(re.sub(r'\(filled_polygon.*', '', b, flags=re.S)))
zo = collections.Counter((net(b), outline(b)) for s, b in top(O, 'zone')); zn = collections.Counter((net(b), outline(b)) for s, b in top(N, 'zone'))
print('\n## Zones whose outline changed')
for tag, A, Bx in (('only in OLD', zo, zn), ('only in NEW', zn, zo)):
    for (n_, P), c in (A - Bx).items():
        ok = n_ in xnets or all(inbox(p) for p in P)
        print('- %s %-16s x %.1f-%.1f y %.1f-%.1f%s' % (tag, n_ or 'keepout', min(p[0] for p in P), max(p[0] for p in P), min(p[1] for p in P), max(p[1] for p in P),
              '' if ok else '   <-- UNEXPECTED'))
        ok or unexpected.append('zone ' + n_)
print('\n## Board text and graphics that changed')
for head in ('gr_text', 'gr_line', 'gr_rect', 'gr_poly', 'gr_arc', 'gr_circle'):
    key = lambda b: re.sub(r'\s+', ' ', re.sub(r'\(uuid "[^"]+"\)', '', b))
    go = {key(b): b for s, b in top(O, head)}; gn = {key(b): b for s, b in top(N, head)}
    for tag, A, Bx in (('only in OLD', go, gn), ('only in NEW', gn, go)):
        for k, b in A.items():
            if k in Bx: continue
            P = pts(b); tx = re.match(r'\(gr_text "([^"]*)"', b)
            ok = all(inbox(p) for p in P)
            print('- %s %s %s at %s%s' % (tag, head, '"%s"' % tx.group(1) if tx else '', P[0] if P else '?', '' if ok else '   <-- UNEXPECTED'))
            ok or unexpected.append(head)
print('\n%d unexpected change groups%s' % (len(unexpected), ': check each one was intended' if unexpected else ''))
sys.exit(1 if unexpected else 0)
