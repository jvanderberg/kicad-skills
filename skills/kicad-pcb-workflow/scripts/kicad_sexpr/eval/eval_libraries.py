"""Round-trip evaluation of KiCad s-expression libraries on real KiCad 10 files, judged by kicad-cli
(the harness behind EVALUATION.md).

  python3 -m venv venv && venv/bin/pip install kiutils kicad-skip kicadfiles
  venv/bin/python eval_libraries.py cases.json OUT_DIR

cases.json: [["name", "/path/file.kicad_pcb", "/path/project_dir", "/path/project_dir/root.kicad_sch"], ...]
(project dir and root sheet null for library files). Results: OUT_DIR/results.json and stdout.

For every (file, library): parse + write unchanged, drop the result into a copy of the project, then compare against
the untouched copy: token stream, lost/added keywords, kicad-cli DRC / ERC / netlist, and the file KiCad writes when
it re-saves it (`kicad-cli ... upgrade --force`) -- identical re-saves mean KiCad loaded identical content.
"""
import collections
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(HERE, 'rt')
K = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))     # .../scripts, for kicad_sexpr

TOK = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"]+', re.S)


def toks(t):
    return TOK.findall(t)


def heads(t):
    tk = toks(t)
    return collections.Counter(tk[i + 1] for i in range(len(tk) - 1) if tk[i] == '(')


# ------------------------------------------------------------------ adapters

def a_mine(src, dst):
    from kicad_sexpr.sexp import loads, dumps
    open(dst, 'w').write(dumps(loads(open(src).read())))


def a_kiutils(src, dst):
    from kiutils.board import Board
    from kiutils.schematic import Schematic
    from kiutils.footprint import Footprint
    from kiutils.symbol import SymbolLib
    cls = {'kicad_pcb': Board, 'kicad_sch': Schematic, 'kicad_mod': Footprint,
           'kicad_sym': SymbolLib}[src.rsplit('.', 1)[1]]
    cls.from_file(src).to_file(dst)


def a_skip(src, dst):
    import skip
    ext = src.rsplit('.', 1)[1]
    if ext == 'kicad_sch':
        skip.Schematic(src).write(dst)
    elif ext == 'kicad_pcb':
        skip.PCB(src).write(dst)
    else:
        raise NotImplementedError('kicad-skip has no %s support' % ext)


def a_kicadfiles(src, dst):
    import kicadfiles as kf
    ext = src.rsplit('.', 1)[1]
    cls = {'kicad_pcb': kf.KicadPcb, 'kicad_sch': kf.KicadSch, 'kicad_mod': kf.Footprint,
           'kicad_sym': kf.KicadSymbolLib}[ext]
    if ext == 'kicad_mod':
        o = cls.from_str(open(src).read())
        open(dst, 'w').write(o.to_sexpr_str())
    else:
        cls.from_file(src).save_to_file(dst)


ADAPTERS = {'kicad_sexpr': a_mine, 'kiutils': a_kiutils, 'kicad-skip': a_skip, 'kicadfiles': a_kicadfiles}


# ------------------------------------------------------------------ kicad-cli probes

def run(args, cwd=None):
    p = subprocess.run([K] + args, capture_output=True, text=True, cwd=cwd, timeout=600)
    return p.returncode, p.stdout + p.stderr


def drc(pcb):
    j = pcb + '.drc.json'
    rc, out = run(['pcb', 'drc', '--severity-all', '--schematic-parity', '--format', 'json', '-o', j, pcb])
    if not os.path.exists(j):
        return 'LOAD FAILED: ' + out.strip().splitlines()[-1] if out.strip() else 'LOAD FAILED'
    d = json.load(open(j))
    c = collections.Counter(v['type'] for v in d['violations'])
    return dict(violations=dict(sorted(c.items())), unconnected=len(d.get('unconnected_items', [])),
                parity=len(d.get('schematic_parity', [])))


def erc(sch):
    j = sch + '.erc.json'
    rc, out = run(['sch', 'erc', '--severity-all', '--format', 'json', '-o', j, sch])
    if not os.path.exists(j):
        return 'LOAD FAILED: ' + out.strip()[-200:]
    d = json.load(open(j))
    c = collections.Counter(v['type'] for s in d['sheets'] for v in s['violations'])
    return dict(sorted(c.items()))


def netlist(sch):
    x = sch + '.net.xml'
    rc, out = run(['sch', 'export', 'netlist', '--format', 'kicadxml', '-o', x, sch])
    if not os.path.exists(x):
        return 'LOAD FAILED'
    t = open(x).read()
    t = re.sub(r'<(date|source|tool)>.*?</\1>', '', t)
    return t


def resave(path):
    """KiCad's own re-save of the file (in a private copy)."""
    d = path + '.resave'
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    ext = path.rsplit('.', 1)[1]
    if ext == 'kicad_mod':
        lib = os.path.join(d, 'x.pretty')
        os.makedirs(lib)
        shutil.copy(path, lib)
        rc, out = run(['fp', 'upgrade', '--force', lib, '-o', os.path.join(d, 'o.pretty')])
        f = os.path.join(d, 'o.pretty', os.path.basename(path))
    elif ext == 'kicad_sym':
        f = os.path.join(d, os.path.basename(path))
        shutil.copy(path, f)
        rc, out = run(['sym', 'upgrade', '--force', f])
    else:
        # schematic sub-sheets / boards: re-save inside the project copy dir so references resolve
        f = path + '.resaved.' + ext
        shutil.copy(path, f)
        rc, out = run(['pcb' if ext == 'kicad_pcb' else 'sch', 'upgrade', '--force', f])
    if not os.path.exists(f):
        return None
    t = open(f).read()
    # library files carry no uuids, so KiCad invents fresh ones on every load: mask them
    return re.sub(r'\(uuid "[^"]*"\)', '(uuid U)', t)


def svg(path):
    ext = path.rsplit('.', 1)[1]
    d = path + '.svg'
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    if ext == 'kicad_mod':
        lib = os.path.join(d, 'x.pretty')
        os.makedirs(lib)
        shutil.copy(path, lib)
        run(['fp', 'export', 'svg', '-o', os.path.join(d, 'out'), lib])
    else:
        run(['sym', 'export', 'svg', '-o', os.path.join(d, 'out'), path])
    res = {}
    o = os.path.join(d, 'out')
    for fn in sorted(os.listdir(o)) if os.path.isdir(o) else []:
        res[fn] = re.sub(r'<title>.*?</title>|<desc>.*?</desc>', '', open(os.path.join(o, fn)).read(), flags=re.S)
    return res


# ------------------------------------------------------------------ one case

def case(name, target, proj, root_sch):
    ext = target.rsplit('.', 1)[1]
    res = {}
    base = os.path.join(OUT, name)
    shutil.rmtree(base, ignore_errors=True)
    orig_text = open(target, encoding='utf-8').read()
    variants = ['orig'] + list(ADAPTERS)
    copies = {}
    for v in variants:
        d = os.path.join(base, v)
        if proj:
            subprocess.run(['rsync', '-a', '--exclude', '.git', '--exclude', '.history', '--exclude', '*-backups',
                            '--exclude', '*.step', '--exclude', '*.wrl', '--exclude', '*.zip',
                            '--exclude', 'production*',
                            '--exclude', '*.lck', proj + '/', d + '/'], check=True)
            dst = os.path.join(d, os.path.relpath(target, proj))
        else:
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, os.path.basename(target))
            shutil.copy(target, dst)
        r = dict()
        if v != 'orig':
            try:
                tmp = os.path.join(os.path.dirname(dst), '_tmp_' + os.path.basename(dst))
                ADAPTERS[v](target, tmp)
                shutil.move(tmp, dst)
            except Exception as e:
                r['write'] = 'FAILED: %s: %s' % (type(e).__name__, str(e)[:120])
                res[v] = r
                continue
            new = open(dst, encoding='utf-8').read()
            r['byte_identical'] = new == orig_text
            r['token_identical'] = toks(new) == toks(orig_text)
            ho, hn = heads(orig_text), heads(new)
            lost = {k: ho[k] - hn[k] for k in ho if ho[k] > hn[k]}
            added = {k: hn[k] - ho[k] for k in hn if hn[k] > ho[k]}
            r['keywords_lost'] = dict(sorted(lost.items(), key=lambda kv: -kv[1])[:8])
            r['keywords_added'] = dict(sorted(added.items(), key=lambda kv: -kv[1])[:8])
        copies[v] = (d, dst)
        res[v] = r

    def probe(v):
        d, dst = copies[v]
        r = res[v]
        if ext == 'kicad_pcb':
            r['drc'] = drc(dst)
        if ext == 'kicad_sch' or (ext == 'kicad_pcb' and False):
            rs = os.path.join(d, os.path.relpath(root_sch, proj))
            r['erc'] = erc(rs)
            r['_netlist'] = netlist(rs)
        if ext in ('kicad_mod', 'kicad_sym'):
            r['_svg'] = svg(dst)
        r['_resave'] = resave(dst)
    with cf.ThreadPoolExecutor(5) as ex:
        list(ex.map(probe, list(copies)))
    o = res['orig']
    for v in ADAPTERS:
        r = res[v]
        if 'write' in r:
            continue
        if '_netlist' in r:
            r['netlist_same'] = r.pop('_netlist') == o['_netlist']
        if '_svg' in r:
            r['svg_same'] = r.pop('_svg') == o['_svg']
        rs = r.pop('_resave')
        r['kicad_resave_same'] = (rs == o['_resave']) if rs is not None else 'RESAVE FAILED (KiCad could not load it)'
        for k in ('drc', 'erc'):
            if k in r:
                r[k + '_same'] = r[k] == o[k]
    for k in ('_netlist', '_svg', '_resave'):
        o.pop(k, None)
    return name, res


if __name__ == '__main__':
    CASES = json.load(open(sys.argv[1]))
    results = {}
    with cf.ThreadPoolExecutor(3) as ex:
        futs = [ex.submit(case, *c) for c in CASES]
        for f in cf.as_completed(futs):
            try:
                n, r = f.result()
            except Exception:
                traceback.print_exc()
                continue
            results[n] = r
            print('==', n, flush=True)
            for v, x in r.items():
                print('  %-12s %s' % (v, json.dumps(x)), flush=True)
    json.dump(results, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
