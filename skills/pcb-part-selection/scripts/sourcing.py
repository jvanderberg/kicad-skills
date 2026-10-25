#!/usr/bin/env python3
"""The project's sourcing context in one place, and every LCSC stock lookup made through it.

  sourcing.py show [PROJECT_DIR]                      # the context every script uses, and the file it came from
  sourcing.py init PROJECT_DIR --assembler JLCPCB --region global [--boards 5] [--min-stock 0]
  sourcing.py search "<keyword | MPN>" [--project DIR] [-n 15] [-t basic|extended|both] [--min-stock N]
  sourcing.py stock C3289423 C316138 ... [--project DIR] [--per-board 3]

Availability is a fact about (part, the warehouse the assembler buys from, quantity, date), not about the part. LCSC
runs two warehouses with separate stock: `global` (what international JLCPCB assembly buys from, prices in USD) and
`cn` (SZLCSC, JLC China, prices in CNY). The same C-number can show 12,000 in one and 0 in the other (C3289423,
SiSS80DN, October 2026). jlcimport-cli's `search` takes its region from its own config when `--region` is missing,
and that config is whatever was last picked in the KiCad plugin's region menu, so a bare `jlcimport-cli search` can
answer for the wrong warehouse with no sign that it did.

So the project names its assembler and region once, in `sourcing.json` (found like every project input: projfiles.py,
the project folder and its parents up to the repository root, each folder and its docs/), and every lookup here,
in bom_check.py and in part_gate.py reads it, passes `--region` explicitly, and prints the region and date with every
stock figure. With no sourcing.json and no --region the scripts stop and say how to create one: there is no default.
When a part is short in the project's region the other region is looked up too and shown, labelled as not counting,
because "it shows stock" from the other warehouse is exactly the mistake to explain.

sourcing.json:
  {"assembler": "JLCPCB",          # required: who assembles (stock lookups here cover JLCPCB/LCSC only)
   "region": "global",             # required: global | cn - the warehouse that assembler buys from
   "boards": 5,                    # assembled boards per order (default 5)
   "attrition": 0.10,              # extra fraction ordered for loss (default 0.10)
   "min_stock": 0,                 # stock policy: listed units per LCSC part, on top of the order need (default 0)
   "exceptions": [{"lcsc": "C123", "reason": "...", "approved": "<who>, <date>"}]}   # named policy exceptions
"""
import argparse, csv, datetime, io, json, math, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import projfiles  # noqa: E402

NAME = 'sourcing.json'
REGIONS = {
    'global': 'LCSC global warehouse (international JLCPCB assembly; prices USD)',
    'cn': 'LCSC China warehouse (SZLCSC / JLC China assembly; prices CNY)',
}
CURRENCY = {'global': 'USD', 'cn': 'CNY'}
DEFAULTS = dict(boards=5, attrition=0.10, min_stock=0, exceptions=[])


class SourcingError(Exception):
    pass


def default_cli():
    return (os.environ.get('JLCIMPORT_CLI') or shutil.which('jlcimport-cli')
            or os.path.expanduser('~/.local/bin/jlcimport-cli'))


def today():
    return datetime.date.today().isoformat()


def other(region):
    return 'cn' if region == 'global' else 'global'


def resolve(project_dir=None, region=None, explicit=None):
    """The sourcing context: dict(assembler, region, boards, attrition, min_stock, exceptions, source, notes).
    An explicit --region wins over the file's (and the override is noted); with neither, SourcingError."""
    project_dir = project_dir or os.getcwd()
    path, msg = projfiles.describe(project_dir, NAME, explicit)
    cfg = dict(DEFAULTS)
    notes = [msg]
    if path:
        try:
            data = json.load(open(path))
        except (OSError, ValueError) as e:
            raise SourcingError('cannot read %s: %s' % (path, e))
        unknown = sorted(set(data) - {'assembler', 'region', 'boards', 'attrition', 'min_stock', 'exceptions', 'notes'})
        if unknown:
            raise SourcingError('%s: unknown keys %s (known: assembler, region, boards, attrition, min_stock, '
                                'exceptions, notes)' % (path, ', '.join(unknown)))
        cfg.update(data)
        if not cfg.get('assembler') or not data.get('region'):
            raise SourcingError('%s must name "assembler" and "region" (one of %s)' % (path, ', '.join(REGIONS)))
    if region:
        if path and cfg.get('region') != region:
            notes.append('--region %s overrides %s\'s "%s"' % (region, NAME, cfg.get('region')))
        cfg['region'] = region
        cfg['source'] = '--region' + (' (other fields from %s)' % path if path else '')
    elif path:
        cfg['source'] = path
    else:
        raise SourcingError(
            'no sourcing context: which assembler, and which LCSC warehouse does it buy from? Stock differs by region '
            '(global = international JLCPCB, cn = SZLCSC / JLC China), and there is no safe default.\n'
            '  Create it once:  sourcing.py init <project_dir> --assembler JLCPCB --region global\n'
            '  or pass --region for a one-off lookup.\n  %s' % msg)
    if cfg['region'] not in REGIONS:
        raise SourcingError('region "%s" is not one of %s' % (cfg['region'], ', '.join(REGIONS)))
    cfg.setdefault('assembler', '(not named: --region only)')
    cfg['notes'] = notes
    return cfg


def need_for(ctx, per_board=1, lcsc=None):
    """units the order needs (per board x boards x (1 + attrition), rounded up), and the policy floor for this part
    unless a named exception covers it: (order_need, policy_need, exception or None)"""
    order = int(math.ceil(per_board * ctx['boards'] * (1 + ctx['attrition']) - 1e-9))
    exc = next((e for e in ctx.get('exceptions') or [] if e.get('lcsc') == lcsc), None) if lcsc else None
    policy = 0 if exc else int(ctx.get('min_stock') or 0)
    return order, policy, exc


def header(ctx):
    return 'Sourcing: %s, region %s = %s; boards %d, attrition %d %%%s; stock as of %s; context from %s' % (
        ctx['assembler'], ctx['region'], REGIONS[ctx['region']], ctx['boards'], round(100 * ctx['attrition']),
        ', policy >= %d listed per part' % ctx['min_stock'] if ctx.get('min_stock') else '', today(), ctx['source'])


def search(keyword, region, cli=None, n=10, kind='both', min_stock=0):
    """rows from `jlcimport-cli search ... --region REGION --csv`, each tagged with its region and currency.
    Raises SourcingError when the CLI cannot be run or does not know --region."""
    if region not in REGIONS:
        raise SourcingError('region "%s" is not one of %s' % (region, ', '.join(REGIONS)))
    cmd = [cli or default_cli(), 'search', keyword, '--region', region, '--min-stock', str(min_stock), '--csv',
           '-n', str(n), '-t', kind]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SourcingError('cannot run %s: %s (install: pipx install git+https://github.com/jvanderberg/kicad_jlcimport)'
                            % (cmd[0], e))
    if r.returncode:
        err = (r.stderr or r.stdout).strip().splitlines()
        if any('--region' in l for l in err):
            raise SourcingError('%s does not accept --region (needs jlcimport v1.6.0+): %s' % (cmd[0], err[-1]))
        raise SourcingError('%s search %r failed (exit %d): %s' % (cmd[0], keyword, r.returncode, err[-1] if err else ''))
    rows = []
    for row in csv.DictReader(io.StringIO(r.stdout)):
        try:
            stock = int(float(row.get('Stock') or 0))
        except ValueError:
            stock = 0
        rows.append(dict(lcsc=row.get('LCSC', ''), type=row.get('Type', ''), price=row.get('Price', ''), stock=stock,
                         part=row.get('Part', ''), package=row.get('Package', ''), brand=row.get('Brand', ''),
                         description=row.get('Description', ''), region=region, currency=CURRENCY[region]))
    return rows


def lookup(lcsc, region, cli=None):
    """the row for exactly this C-number in this region, or None (not listed there)"""
    for row in search(lcsc, region, cli, n=5):
        if row['lcsc'] == lcsc:
            return row
    return None


def stock_text(row, region):
    if row is None:
        return 'not listed in %s' % region
    return '%s in stock (%s, %s)' % ('{:,}'.format(row['stock']), region, today())


def check_part(lcsc, ctx, per_board=1, cli=None):
    """(row, flags, note) for one C-number in the project's region; when it is short, the other region is looked up
    and described as not counting"""
    row = lookup(lcsc, ctx['region'], cli)
    order, policy, exc = need_for(ctx, per_board, lcsc)
    flags, note = [], ''
    have = row['stock'] if row else 0
    if row is None:
        flags.append('NOT LISTED in %s' % ctx['region'])
    elif have < order:
        flags.append('STOCK %d < need %d (%s)' % (have, order, ctx['region']))
    elif have < policy:
        flags.append('POLICY %d < %d listed (%s)' % (have, policy, ctx['region']))
    if flags:
        alt = lookup(lcsc, other(ctx['region']), cli)
        if alt and alt['stock']:
            note = '%s has %s - does not count: %s buys from %s' % (
                other(ctx['region']), '{:,}'.format(alt['stock']), ctx['assembler'], ctx['region'])
    if exc and row and have >= order:
        note = (note + '; ' if note else '') + 'policy exception: %s (%s)' % (exc.get('reason', '?'), exc.get('approved', '?'))
    return row, flags, note


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('show'); s.add_argument('project', nargs='?')
    s = sub.add_parser('init'); s.add_argument('project'); s.add_argument('--assembler', required=True)
    s.add_argument('--region', required=True, choices=sorted(REGIONS)); s.add_argument('--boards', type=int, default=5)
    s.add_argument('--attrition', type=float, default=0.10); s.add_argument('--min-stock', type=int, default=0)
    for name in ('search', 'stock'):
        s = sub.add_parser(name)
        s.add_argument('items', nargs='+'); s.add_argument('--project'); s.add_argument('--region', choices=sorted(REGIONS))
        s.add_argument('--sourcing', help='explicit sourcing.json'); s.add_argument('--cli', default=default_cli())
        if name == 'search':
            s.add_argument('-n', type=int, default=15); s.add_argument('-t', default='both', choices=('basic', 'extended', 'both'))
            s.add_argument('--min-stock', type=int, default=0)
        else:
            s.add_argument('--per-board', type=int, default=1)
    a = ap.parse_args()
    try:
        if a.cmd == 'init':
            d = os.path.join(os.path.abspath(a.project), 'docs') if os.path.isdir(os.path.join(a.project, 'docs')) else os.path.abspath(a.project)
            p = os.path.join(d, NAME)
            if os.path.exists(p):
                sys.exit('%s exists; edit it (a changed region is a sourcing decision: re-run bom_check.py)' % p)
            json.dump(dict(assembler=a.assembler, region=a.region, boards=a.boards, attrition=a.attrition,
                           min_stock=a.min_stock, exceptions=[]), open(p, 'w'), indent=1)
            print('wrote %s' % p)
            return
        if a.cmd == 'show':
            ctx = resolve(a.project)
            print(header(ctx))
            for n in ctx['notes']:
                print('  ' + n)
            return
        ctx = resolve(a.project, a.region, a.sourcing)
        print(header(ctx))
        for n in ctx['notes'][1:]:
            print('  note: ' + n)
        if a.cmd == 'search':
            for kw in a.items:
                rows = search(kw, ctx['region'], a.cli, a.n, a.t, a.min_stock)
                print('\n"%s" in %s: %d result(s)' % (kw, ctx['region'], len(rows)))
                print('  %-11s %-9s %10s %10s  %-24s %-18s %s' % ('LCSC', 'type', 'stock', 'price ' + CURRENCY[ctx['region']], 'part', 'package', 'brand'))
                for r in rows:
                    print('  %-11s %-9s %10s %10s  %-24s %-18s %s' % (r['lcsc'], r['type'], '{:,}'.format(r['stock']), r['price'],
                                                                   r['part'][:24], r['package'][:18], r['brand'][:20]))
            return
        bad = 0
        for c in a.items:
            row, flags, note = check_part(c, ctx, a.per_board, a.cli)
            bad += bool(flags)
            print('%-11s %-24s %s%s%s' % (c, (row or {}).get('part', '')[:24], stock_text(row, ctx['region']),
                                         '   <-- ' + ', '.join(flags) if flags else '', '   [' + note + ']' if note else ''))
        sys.exit(1 if bad else 0)
    except SourcingError as e:
        sys.exit('sourcing: %s' % e)


if __name__ == '__main__':
    main()
