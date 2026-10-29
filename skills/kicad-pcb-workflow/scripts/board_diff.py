#!/usr/bin/env python3
"""What changed between two versions of a board (or schematic), grouped so a human can check it was all intended.

  board_diff.py OLD.kicad_pcb NEW.kicad_pcb [--expect x0,y0,x1,y1 ...] [--expect-refs R1,R2,...] [--expect-nets N1,N2]
  board_diff.py HEAD NEW.kicad_pcb ...          # OLD = the same file in a git revision (any folder, any cwd)
  board_diff.py HEAD SCRATCH/x.kicad_pcb --repo PROJECT   # a scratch copy (outside the repository, or inside
                                                # it untracked): OLD = the file of that name in HEAD of PROJECT's
                                                # repository (the current folder's without --repo); it prints which
                                                # file it used
  board_diff.py HEAD:hardware/x.kicad_pcb NEW   # an explicit path in a revision (repo-root relative, or ./ relative
                                                # to --repo or the current folder, as git takes it)
  board_diff.py HEAD NEW.kicad_sch ...          # schematics: symbols by reference, then everything else

Lists every difference, never only the geometric ones: per footprint (or symbol) every attribute that changed -
library id, position, rotation, side, every field (Value, LCSC, MPN, Datasheet, ...), attributes (DNP, exclude from
BOM/position files), pad nets, 3D model paths, and "other content" when anything else inside it differs; copper
(tracks, arcs, vias) only in OLD or only in NEW grouped by net, layer and area; zones whose outline, net or settings
changed; board graphics and text; and every other top-level item (setup, stackup, net classes, groups, dimensions...)
that differs. Anything outside the --expect boxes, refs and nets is marked UNEXPECTED. The last line says how many
items of each kind were compared, so "0 unexpected" can be read against what was looked at.

Run it before copying a scripted change back into the user's project, against the committed version. It catches the
silent failure where a rebuild started from an older snapshot and quietly reverted the user's own later edits, and a
field edit (value, LCSC) that no geometry diff can see.
"""
import argparse, collections, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_sexpr import loads, dumps, Node  # noqa: E402


def git(cwd, *args):
    return subprocess.run(['git', *args], capture_output=True, text=True, cwd=cwd)


def work_tree(d):
    """the top of the git work tree holding folder d, or None"""
    r = git(d, 'rev-parse', '--show-toplevel') if os.path.isdir(d) else None
    return r.stdout.strip() if r is not None and r.returncode == 0 else None


def find_in_rev(rev, name, top, here):
    """the one file called `name` in revision `rev` of the repository at `top` (the one in folder `here`, when several)"""
    r = git(top, 'ls-tree', '-r', '-z', '--name-only', '--full-tree', rev)    # -z: non-ASCII names unquoted
    if r.returncode:
        sys.exit('git ls-tree %s (in %s) failed: %s' % (rev, top, r.stderr.strip()))
    cands = [f for f in r.stdout.split('\0') if f and os.path.basename(f) == name]
    if len(cands) > 1:
        rel = os.path.relpath(os.path.realpath(here), os.path.realpath(top))
        cands = [f for f in cands if os.path.dirname(f) == ('' if rel == '.' else rel)] or cands
    if len(cands) != 1:
        sys.exit('%s in %s of %s: %s - give the path, %s:<path in the repository>' % (
            name, rev, top, 'several files of that name (%s)' % ', '.join(cands) if cands else 'no file of that name', rev))
    return cands[0]


def git_show(spec, new, repo=None):
    """'HEAD' -> NEW's own path in HEAD when it is tracked there (NEW inside the repository, and in --repo if given);
    otherwise - a scratch copy outside the repository, or inside it but untracked - the file of NEW's name in HEAD of
    --repo, else of the repository holding the current folder, else of the one holding NEW.
    'REV:path' -> as git resolves it from --repo, else from the current folder."""
    home = os.path.dirname(os.path.abspath(new))
    own = work_tree(home)
    if ':' in spec:
        cwd = repo or os.getcwd()
    else:
        if own and (repo is None or own == work_tree(repo)):
            r = git(home, 'show', '%s:./%s' % (spec, os.path.basename(new)))   # ./ = relative to NEW's folder
            if r.returncode == 0:
                return r.stdout
        top = work_tree(repo) if repo else (work_tree(os.getcwd()) or own)
        if not top:
            sys.exit('%s is outside any git repository and so is %s: give the repository, --repo DIR, or REV:path '
                     'from inside it' % (new, repo or 'the current folder %s' % os.getcwd()))
        spec = '%s:%s' % (spec, find_in_rev(spec, os.path.basename(new), top, repo or os.getcwd()))
        cwd = top
        print('OLD = %s in %s (NEW is not that file: matched by file name)' % (spec, top))
    r = git(cwd, 'show', spec)
    if r.returncode:
        sys.exit('git show %s (in %s) failed: %s' % (spec, cwd, r.stderr.strip()))
    return r.stdout


def load(p, new, repo=None):
    return open(p).read() if os.path.exists(p) else git_show(p, new, repo)


def nat(s): return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


def strip_ids(n):
    """a copy without uuids / tstamps (ids are bookkeeping, not design)"""
    c = n.deepcopy()
    for x in list(c.walk()):
        for k in ('uuid', 'tstamp', 'tstamps'):
            x.remove_all(k)
    c.remove_all('uuid'); c.remove_all('tstamp')
    return c


def norm(n): return re.sub(r'\s+', ' ', dumps(strip_ids(n)))


def props(n): return collections.OrderedDict((str(p[1]), str(p[2])) for p in n.nodes('property'))


def pts(n):
    out = []
    for x in n.walk():
        if x.head in ('start', 'mid', 'end', 'at', 'xy', 'center') and len(x) >= 3:
            try:
                out.append((round(x.number(1), 3), round(x.number(2), 3)))
            except (TypeError, ValueError):
                pass
    return out


def netname(n):
    x = n.find('net')
    if x is None:
        return ''
    return str(x[-1]) if len(x) > 1 else ''


def fp_attrs(f):
    a = collections.OrderedDict()
    a['lib_id'] = str(f[1])
    at = f.find('at')
    a['at'] = tuple(round(at.number(i, 0.0), 3) for i in (1, 2)) if at is not None else None
    a['rotation'] = round(at.number(3, 0.0), 3) if at is not None and len(at) > 3 else 0.0
    a['side'] = str(f.get('layer', ''))
    for k, v in props(f).items():
        a['field ' + k] = v
    at_ = f.find('attr')
    a['attributes'] = ' '.join(str(x) for x in at_[1:]) if at_ is not None else ''
    for k in ('locked', 'dnp'):
        if f.find(k) is not None:
            a[k] = str(f.get(k))
    for p in f.nodes('pad'):
        a['pad %s net' % p[1]] = netname(p)
    a['3D models'] = ' '.join(str(m[1]) for m in f.nodes('model'))
    return a


def sym_attrs(s):
    a = collections.OrderedDict()
    a['lib_id'] = str(s.get('lib_id', ''))
    at = s.find('at')
    a['at'] = tuple(round(at.number(i, 0.0), 3) for i in (1, 2)) if at is not None else None
    a['rotation'] = round(at.number(3, 0.0), 3) if at is not None and len(at) > 3 else 0.0
    a['mirror'] = str(s.get('mirror', ''))
    for k in ('in_bom', 'on_board', 'dnp', 'exclude_from_sim', 'in_pos_files'):
        if s.find(k) is not None:
            a[k] = str(s.get(k))
    for k, v in props(s).items():
        a['field ' + k] = v
    return a


def inner_rest(n, drop_props=True):
    """the item's text without what fp_attrs/sym_attrs already compared (to catch anything else that changed)"""
    c = strip_ids(n)
    for h in ('property', 'at', 'attr', 'locked', 'dnp', 'model', 'layer', 'lib_id', 'mirror', 'in_bom', 'on_board',
              'exclude_from_sim', 'in_pos_files', 'instances', 'pin'):
        c.remove_all(h)
    for p in c.nodes('pad'):
        p.remove_all('net')
    return re.sub(r'\s+', ' ', dumps(c))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('old'); ap.add_argument('new')
    ap.add_argument('--expect', action='append', default=[]); ap.add_argument('--expect-refs', default='')
    ap.add_argument('--expect-nets', default='')
    ap.add_argument('--repo', help='the git repository OLD is a revision of (default: the one holding NEW, else the '
                    "current folder's); a scratch copy outside it is matched by file name")
    a = ap.parse_args()
    if a.repo and not os.path.isdir(a.repo):
        ap.error('--repo %s is not a folder' % a.repo)
    O, N = loads(load(a.old, a.new, a.repo)), loads(load(a.new, a.new))
    sch = O.head == 'kicad_sch'
    boxes = [tuple(map(float, b.split(','))) for b in a.expect]
    xrefs = set(filter(None, a.expect_refs.split(','))); xnets = set(filter(None, a.expect_nets.split(',')))
    inbox = lambda p: any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for x0, y0, x1, y1 in boxes)
    unexpected, counted = [], collections.Counter()
    mark = lambda ok: '' if ok else '   <-- UNEXPECTED'

    # ---- parts (footprints or symbols) by reference, every attribute
    head, attrs = ('symbol', sym_attrs) if sch else ('footprint', fp_attrs)
    def parts(t):
        out = {}
        for n in t.nodes(head):
            r = props(n).get('Reference', '')
            if sch and r.startswith('#'):
                # power symbols and flags are renumbered whenever one is added: match them by what and where they are
                at = n.find('at')
                r = '%s %s @%.2f,%.2f' % (n.get('lib_id'), props(n).get('Value', ''), at.number(1), at.number(2))
            unit = str(n.get('unit', '1')) if sch else ''
            out[r + ('#%s' % unit if sch and unit != '1' else '')] = n
        return out
    po, pn = parts(O), parts(N)
    counted[head + 's'] = len(set(po) | set(pn))
    print('## %s (every attribute)' % ('Symbols' if sch else 'Footprints'))
    for r in sorted(set(po) | set(pn), key=nat):
        o, n = po.get(r), pn.get(r)
        ref = r.split('#')[0] if not r.startswith('power:') else r
        if o is None or n is None:
            x = n if o is None else o
            A = attrs(x)
            ok = ref in xrefs or (A['at'] is not None and inbox(A['at']))
            print('- %s %s %s at %s%s' % (r, 'added' if o is None else 'removed', A['lib_id'], A['at'], mark(ok)))
            ok or unexpected.append(r); continue
        ao, an = attrs(o), attrs(n)
        diffs = [(k, ao.get(k), an.get(k)) for k in list(ao) + [k for k in an if k not in ao] if ao.get(k) != an.get(k)]
        if r.startswith('power:'):
            diffs = [d for d in diffs if d[0] != 'field Reference']
        if not diffs and inner_rest(o) != inner_rest(n):
            diffs = [('other content (pads, graphics, text layout)', 'differs', '')]
        if not diffs:
            continue
        geo_only = all(k in ('at', 'rotation') for k, _, _ in diffs)
        ok = ref in xrefs or (geo_only and all(inbox(x['at']) for x in (ao, an) if x['at'] is not None))
        print('- %s: %s%s' % (r, '; '.join('%s %r -> %r' % (k, v1, v2) if v2 != '' else '%s %s' % (k, v1) for k, v1, v2 in diffs), mark(ok)))
        ok or unexpected.append(r)

    if not sch:
        # ---- copper
        def copper(t):
            o = collections.Counter()
            for h in ('segment', 'arc', 'via'):
                for n in t.nodes(h):
                    lay = n.find('layer') or n.find('layers')
                    o[(h, netname(n), ' '.join(str(x) for x in lay[1:]) if lay is not None else '', norm(n))] += 1
            return o
        co, cn = copper(O), copper(N)
        counted['copper items'] = sum((co | cn).values())
        print('\n## Copper (tracks, arcs, vias), grouped by net / layer')
        for tag, A, Bx in (('only in OLD', co, cn), ('only in NEW', cn, co)):
            g = collections.defaultdict(list)
            for k, c in (A - Bx).items():
                g[(k[1], k[2], k[0])].append(pts(loads(k[3])))
            print('### %s' % tag)
            for (n_, lay, h), v in sorted(g.items()):
                P = [p for q in v for p in q]
                ok = n_ in xnets or all(inbox(p) for p in P)
                print('- %-22s %-18s %-7s %3d  x %.1f-%.1f  y %.1f-%.1f%s' % (n_, lay, h, len(v), min(p[0] for p in P), max(p[0] for p in P),
                      min(p[1] for p in P), max(p[1] for p in P), mark(ok)))
                ok or unexpected.append('%s %s' % (n_, lay))
        # ---- zones (outline, net, layers, settings; fills are derived and ignored)
        def zones(t):
            o = collections.Counter()
            for z in t.nodes('zone'):
                c = strip_ids(z); c.remove_all('filled_polygon'); c.remove_all('fill_segments')
                o[(netname(z) or str(z.get('name', '')) or 'keepout', re.sub(r'\s+', ' ', dumps(c)))] += 1
            return o
        zo, zn = zones(O), zones(N)
        counted['zones'] = sum((zo | zn).values())
        print('\n## Zones whose outline, net, layers or settings changed (fills ignored)')
        for tag, A, Bx in (('only in OLD', zo, zn), ('only in NEW', zn, zo)):
            for (n_, txt), c in (A - Bx).items():
                P = pts(loads(txt))
                ok = n_ in xnets or all(inbox(p) for p in P)
                print('- %s %-16s x %.1f-%.1f y %.1f-%.1f%s' % (tag, n_, min(p[0] for p in P), max(p[0] for p in P),
                      min(p[1] for p in P), max(p[1] for p in P), mark(ok)))
                ok or unexpected.append('zone ' + n_)

    # ---- everything else at the top level: graphics, text, wires, labels, setup, nets, groups...
    done = {head} | (set() if sch else {'segment', 'arc', 'via', 'zone'}) | {'uuid', 'version', 'generator', 'generator_version'}
    if sch:
        done |= {'lib_symbols', 'sheet_instances', 'symbol_instances'}
    def rest(t):
        o = collections.Counter()
        for n in t.nodes():
            if n.head not in done:
                o[(n.head, norm(n))] += 1
        return o
    ro, rn = rest(O), rest(N)
    counted['other top-level items'] = sum((ro | rn).values())
    print('\n## Other items that changed (graphics, text%s, setup, nets, groups, ...)' % (', wires, labels, junctions' if sch else ''))
    g = collections.defaultdict(lambda: [0, 0, []])
    for tag, A, Bx in ((0, ro, rn), (1, rn, ro)):
        for (h, txt), c in (A - Bx).items():
            g[h][tag] += c; g[h][2] += pts(loads(txt))
    for h, (nold, nnew, P) in sorted(g.items()):
        geo = h.startswith(('gr_', 'wire', 'junction', 'label', 'global_label', 'hierarchical_label', 'no_connect', 'text', 'bus', 'polyline'))
        ok = geo and bool(P) and all(inbox(p) for p in P)
        print('- %-18s %d only in OLD, %d only in NEW%s%s' % (h, nold, nnew, ' at x %.1f-%.1f y %.1f-%.1f' % (
            min(p[0] for p in P), max(p[0] for p in P), min(p[1] for p in P), max(p[1] for p in P)) if P else '', mark(ok)))
        ok or unexpected.append(h)
    if sch and norm(O.find('lib_symbols') or Node('lib_symbols')) != norm(N.find('lib_symbols') or Node('lib_symbols')):
        print('- lib_symbols: embedded library symbols differ (a symbol was redrawn or re-imported)')

    print('\nCompared: %s' % ', '.join('%d %s' % (v, k) for k, v in counted.items()))
    print('%d unexpected change groups%s' % (len(unexpected), ': check each one was intended' if unexpected else ''))
    sys.exit(1 if unexpected else 0)


if __name__ == '__main__':
    main()
