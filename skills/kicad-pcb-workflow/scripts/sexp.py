#!/usr/bin/env python3
"""Small, dependency-free helpers for looking at KiCad s-expression files (.kicad_sch, .kicad_pcb, .kicad_sym,
.kicad_mod) as text, plus a checker. Nothing here writes KiCad files: edits and generators go through kicad_sexpr
(SKILL.md section 2).

CLI:
  sexp.py check FILE...            balance, raw newlines/tabs inside strings, duplicate uuids, duplicate references
  sexp.py list FILE                footprints (pcb) or placed symbols (sch): ref, lib id, position
  sexp.py get FILE REF             print the footprint / symbol block for a reference
  sexp.py nets FILE                pcb: net names in use (shows KiCad's {slash} style escaping)

Library (import sexp):
  block(text, i)                   the balanced (...) starting at index i
  blocks(text, head, depth=None)   [(start, block_text)] for every "(head" block
  find_ref(text, ref)              (start, block) of the footprint/symbol whose Reference is ref

`check` works on the raw text on purpose: it reports what a parser would reject or silently misread (unbalanced
parentheses, raw newlines inside strings, duplicated uuids).
"""
import re, sys, collections

def block(t, i):
    """balanced s-expression starting at t[i] == '(' ; strings may contain parens and escaped quotes"""
    assert t[i] == '(', 'block() must start at "("'
    d = 0; j = i; n = len(t); ins = False
    while j < n:
        c = t[j]
        if ins:
            if c == '\\': j += 2; continue
            if c == '"': ins = False
        elif c == '"': ins = True
        elif c == '(': d += 1
        elif c == ')':
            d -= 1
            if d == 0: return t[i:j + 1]
        j += 1
    raise ValueError('unbalanced block at %d' % i)

def blocks(t, head):
    out = []
    for m in re.finditer(r'\(%s[\s)]' % re.escape(head), t):
        out.append((m.start(), block(t, m.start())))
    return out

def find_ref(t, ref):
    """footprint (pcb) or placed symbol (sch) whose Reference property is ref"""
    for head in ('footprint', 'symbol'):
        for s, b in blocks(t, head):
            if re.search(r'\(property "Reference" "%s"' % re.escape(ref), b) and '(lib_symbols' not in b[:40]:
                return s, b
    return None, None

def check(path):
    t = open(path, encoding='utf-8').read(); probs = []
    d = 0; ins = False; line = 1; sline = 0; i = 0; n = len(t)
    while i < n:
        c = t[i]
        if c == '\n':
            if ins: probs.append('line %d: raw newline inside a string that started on line %d (KiCad can silently drop everything after it; write \\n)' % (line, sline))
            line += 1
        if ins:
            if c == '\\': i += 2; continue
            if c == '"': ins = False
        elif c == '"': ins = True; sline = line
        elif c == '(': d += 1
        elif c == ')':
            d -= 1
            if d < 0: probs.append('line %d: unmatched ")"' % line); d = 0
        i += 1
    if ins: probs.append('unterminated string from line %d' % sline)
    if d: probs.append('%d unclosed "(" at end of file' % d)
    uu = collections.Counter(re.findall(r'\((?:uuid|tstamp) "?([0-9a-fA-F-]{36})"?\)', t))
    dup = [u for u, k in uu.items() if k > 1]
    if dup: probs.append('%d duplicated uuids (copy-pasted blocks need fresh uuids), e.g. %s' % (len(dup), dup[:3]))
    if path.endswith('.kicad_pcb'):
        # as Board.validate() (KiCad's DRC rule): in file order, a reference already seen (any case) is a duplicate
        # unless this footprint is board-only; placeholder references (REF**, G***) are left to DRC
        seen, d2 = set(), []
        for _, b in blocks(t, 'footprint'):
            r = re.search(r'\(property "Reference" "([^"]+)"', b)
            if not r or '*' in r.group(1):
                continue
            if r.group(1).upper() in seen and not re.search(r'\(attr\b[^)]*\bboard_only\b', b) and r.group(1) not in d2:
                d2.append(r.group(1))
            seen.add(r.group(1).upper())
        if d2: probs.append('duplicate footprint references: %s' % d2[:10])
    return probs

def main():
    if len(sys.argv) < 3: print(__doc__); sys.exit(2)
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == 'check':
        bad = 0
        for p in sys.argv[2:]:
            pr = check(p); bad += bool(pr)
            print('%s: %s' % (p, 'ok' if not pr else ''))
            for x in pr: print('  ' + x)
        sys.exit(1 if bad else 0)
    t = open(path, encoding='utf-8').read()
    if cmd == 'list':
        head = 'footprint' if path.endswith('.kicad_pcb') else 'symbol'
        for s, b in blocks(t, head):
            r = re.search(r'\(property "Reference" "([^"]+)"', b)
            if not r: continue
            lib = re.match(r'\(%s "([^"]+)"' % head, b) or re.search(r'\(lib_id "([^"]+)"\)', b)
            at = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', b)
            side = ' B' if '(layer "B.Cu")' in b[:300] else ''
            print('%-8s %-50s %s%s' % (r.group(1), lib.group(1) if lib else '?', at.groups() if at else '', side))
    elif cmd == 'get':
        s, b = find_ref(t, sys.argv[3]); print(b if b else 'not found')
    elif cmd == 'nets':
        for n in sorted(set(re.findall(r'\(net (?:\d+ )?"([^"]*)"\)', t))): print(n)
    else:
        print(__doc__); sys.exit(2)

if __name__ == '__main__':
    main()
