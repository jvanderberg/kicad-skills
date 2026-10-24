# Group a kicad-cli DRC or ERC JSON report by type, with counts and the first few items, so a run can be read at a glance
# and compared with a baseline.
#   python drc_summary.py report.json [--baseline old.json] [--accept accepted.json]
# With --baseline, only items not in the baseline are listed (matched on type + description + item positions rounded to
# 0.1 mm), which is how you tell what YOUR change introduced. "Was it already there?" is never an excuse to leave it:
# the point is to know exactly what to fix.
# With --accept, specific known items are moved to an "Accepted" section with their reason. The file is a JSON list:
#   [{"type": "silk_edge_clearance", "items": ["Segment of J1 "], "reason": "USB-C receptacle overhangs the edge by design"}]
# An entry matches a violation of that type when every string in "items" occurs in one of its item descriptions.
# Every entry must name items: exempting a whole type hid three real silk overlaps on a real board while hiding one
# known warning. Entries that match nothing are reported as stale; exempted items are counted, never silently dropped.
import json, sys, collections


def items(path):
    d = json.load(open(path)); out = []
    for k in ('violations', 'unconnected_items', 'schematic_parity'):
        for v in d.get(k, []): out.append((k, v))
    for s in d.get('sheets', []):                    # ERC
        for v in s.get('violations', []): out.append(('erc ' + s.get('path', ''), v))
    return out


def key(v):
    pos = tuple(sorted((round(i.get('pos', {}).get('x', 0), 1), round(i.get('pos', {}).get('y', 0), 1)) for i in v.get('items', [])))
    return (v.get('type'), v.get('description', ''), pos)


def load_accept(path):
    rules = json.load(open(path))
    for r in rules:
        if not r.get('type') or not r.get('items') or not r.get('reason'):
            sys.exit('--accept: every entry needs "type", a non-empty "items" list and a "reason" '
                     '(exempt named items, never a whole type): %s' % r)
    return rules


def accepted_by(v, rules):
    descs = [i.get('description', '') for i in v.get('items', [])]
    for n, r in enumerate(rules):
        if r['type'] == v.get('type') and all(any(s in d for d in descs) for s in r['items']):
            return n
    return None


cur = items(sys.argv[1])
if '--baseline' in sys.argv:
    base = collections.Counter(key(v) for _, v in items(sys.argv[sys.argv.index('--baseline') + 1]))
    new = []
    for k, v in cur:
        kk = key(v)
        if base[kk] > 0: base[kk] -= 1
        else: new.append((k, v))
    print('# %d items, %d not in the baseline\n' % (len(cur), len(new))); cur = new
acc = collections.defaultdict(list)
if '--accept' in sys.argv:
    rules = load_accept(sys.argv[sys.argv.index('--accept') + 1])
    keep = []
    for k, v in cur:
        n = accepted_by(v, rules)
        if n is None: keep.append((k, v))
        else: acc[n].append(v)
    cur = keep
by = collections.defaultdict(list)
for k, v in cur: by[(v.get('severity', ''), v.get('type', ''))].append(v)
print('| Severity | Type | Count |\n|---|---|---|')
for (sev, ty), vs in sorted(by.items(), key=lambda kv: (kv[0][0] != 'error', -len(kv[1]))): print('| %s | %s | %d |' % (sev, ty, len(vs)))
for (sev, ty), vs in sorted(by.items(), key=lambda kv: (kv[0][0] != 'error', -len(kv[1]))):
    print('\n## %s (%s, %d)' % (ty, sev, len(vs)))
    for v in vs[:8]:
        its = '; '.join('%s @ (%.2f, %.2f)' % (i.get('description', '')[:60], i.get('pos', {}).get('x', 0), i.get('pos', {}).get('y', 0)) for i in v.get('items', [])[:3])
        print('- %s: %s' % (v.get('description', '')[:90], its))
    if len(vs) > 8: print('- ... %d more' % (len(vs) - 8))
if '--accept' in sys.argv:
    print('\n## Accepted (exempted by name, %d items)' % sum(len(x) for x in acc.values()))
    for n, r in enumerate(rules):
        print('- %s %s: %d item(s) - %s%s' % (r['type'], r['items'], len(acc.get(n, [])), r['reason'],
                                             '   <-- STALE: matches nothing; remove it or fix it' if not acc.get(n) else ''))
