#!/usr/bin/env python3
"""Find a project's own kicad-skills inputs by one convention, so every script and wrapper sees the same files.

  projfiles.py find PROJECT_DIR NAME        # print the path (exit 1 and say where it looked if there is none)
  projfiles.py list PROJECT_DIR             # every known input and where it resolved

Convention (the same for check.sh, make_pack.sh, nc_audit.py and anything else that reads project inputs):
  1. an explicit command-line option or environment variable wins (the caller handles that);
  2. otherwise walk up from PROJECT_DIR to the repository root (the first folder holding .git; outside a repository
     only PROJECT_DIR and its parent), and in each folder look at  <dir>/NAME  then  <dir>/docs/NAME.  First hit wins.
A project whose KiCad files live in hardware/ and whose notes live in docs/ at the repository root is found without
options. Every caller prints which file it used, or that none was found and where it looked: a wrapper that silently
runs without the project's notes reports a different answer from the project's own build.

Known inputs (KNOWN below): pin-decisions.json (nc_audit.py --notes), drc-accept.json (check.sh --accept),
review_config.json (make_pack.sh), reference-parts.json (refparts.py), kicad-skills.lock (skills_rev.py),
field-exemptions.json (partfields.py), sourcing.json (bom_check.py, part_gate.py, sourcing.py),
design-values.json (derived_check.py, bom_check.py).
Identical copies in kicad-pcb-workflow/scripts, kicad-board-review/scripts and pcb-part-selection/scripts (each skill
folder is self-contained).
"""
import os
import sys

KNOWN = {
    'pin-decisions.json': 'decision per unused / strapped pin (nc_audit.py --notes)',
    'drc-accept.json': 'named DRC exemptions with reasons (check.sh --accept)',
    'review_config.json': 'board review analysis config (make_pack.sh)',
    'reference-parts.json': "parts each IC's datasheet typical application requires (refparts.py)",
    'kicad-skills.lock': 'the kicad-skills revision this project builds with (skills_rev.py)',
    'field-exemptions.json': 'named exemptions from the part-field check, with reasons (partfields.py --accept)',
    'sourcing.json': "assembler, the warehouse region it buys from, order quantity, stock policy (every stock lookup)",
    'design-values.json': "each derived value and the part parameters it was computed from (derived_check.py)",
}


def search_dirs(project_dir):
    """the project folder and its parents up to the repository root; outside a repository, the folder and its parent"""
    d = os.path.abspath(project_dir if os.path.isdir(project_dir) else os.path.dirname(project_dir))
    chain, x = [d], d
    while not os.path.exists(os.path.join(x, '.git')):
        parent = os.path.dirname(x)
        if parent == x or x == os.path.expanduser('~'):
            chain = chain[:2]          # no repository above: do not wander into unrelated folders
            break
        x = parent; chain.append(x)
    return [p for c in chain for p in (c, os.path.join(c, 'docs'))]


def find(project_dir, name):
    """(path or None, list of places looked, other matches further up)"""
    dirs = search_dirs(project_dir)
    hits = [os.path.join(d, name) for d in dirs if os.path.exists(os.path.join(d, name))]
    return (hits[0] if hits else None), [os.path.join(d, name) for d in dirs], hits[1:]


def describe(project_dir, name, explicit=None):
    """one line for a caller to print: which file it is using and why"""
    if explicit:
        return explicit, 'using %s (given explicitly)' % explicit
    p, looked, others = find(project_dir, name)
    if p:
        return p, 'using %s (found by search)%s' % (p, '; also present, ignored: ' + ', '.join(others) if others else '')
    return None, 'no %s found (looked in: %s)' % (name, ', '.join(looked))


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('find', 'list'):
        sys.exit(__doc__)
    if sys.argv[1] == 'find':
        p, msg = describe(sys.argv[2], sys.argv[3])
        print(msg, file=sys.stderr)
        if not p:
            sys.exit(1)
        print(p)
    else:
        for n, what in KNOWN.items():
            p, msg = describe(sys.argv[2], n)
            print('%-22s %s\n%22s %s' % (n, what, '', msg))


if __name__ == '__main__':
    main()
