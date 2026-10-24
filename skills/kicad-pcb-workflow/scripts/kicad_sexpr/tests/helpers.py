"""Shared test helpers: locate KiCad, run kicad-cli, temp dirs. Tests that need KiCad skip when it is missing."""
import collections
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))      # .../scripts, so "import kicad_sexpr" works


try:                                    # under pytest, Skip is pytest's own skip exception
    import pytest
    Skip = pytest.skip.Exception
except ImportError:
    class Skip(Exception):              # type: ignore[no-redef]
        pass


def _first(paths: List[str]) -> Optional[str]:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


KICAD_CLI = _first([os.environ.get('KICAD_CLI', ''), '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli',
                    shutil.which('kicad-cli') or '', '/usr/bin/kicad-cli'])
KICAD_PYTHON = _first([os.environ.get('KICAD_PYTHON', ''),
                       '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3'])
SHARE = _first([os.environ.get('KICAD_SHARE', ''), '/Applications/KiCad/KiCad.app/Contents/SharedSupport',
                '/usr/share/kicad'])


def need_cli() -> str:
    if not KICAD_CLI:
        raise Skip('kicad-cli not found (set KICAD_CLI)')
    return KICAD_CLI


def need_share() -> str:
    if not SHARE or not os.path.isdir(os.path.join(SHARE, 'symbols')):
        raise Skip('KiCad libraries not found (set KICAD_SHARE)')
    return SHARE


def symbols_dir() -> str:
    return os.path.join(need_share(), 'symbols')


def footprints_dir() -> str:
    return os.path.join(need_share(), 'footprints')


def tmpdir(name: str) -> str:
    d = tempfile.mkdtemp(prefix='kicad_sexpr_%s_' % name)
    return d


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([need_cli()] + list(args), capture_output=True, text=True, timeout=600)


def netlist(sch: str) -> Dict[str, List[str]]:
    """{net name: ['REF.PIN', ...]} from kicad-cli's netlist export."""
    import xml.etree.ElementTree as ET
    out = sch + '.net.xml'
    r = cli('sch', 'export', 'netlist', '--format', 'kicadxml', '-o', out, sch)
    assert os.path.exists(out), r.stdout + r.stderr
    root = ET.parse(out).getroot()
    return {n.get('name'): ['%s.%s' % (x.get('ref'), x.get('pin')) for x in n.findall('node')]
            for n in root.find('nets')}


def netlist_components(sch: str) -> Dict[str, Dict[str, str]]:
    import xml.etree.ElementTree as ET
    out = sch + '.net.xml'
    cli('sch', 'export', 'netlist', '--format', 'kicadxml', '-o', out, sch)
    root = ET.parse(out).getroot()
    res = {}
    for c in root.find('components'):
        d = {f.get('name'): f.text or '' for f in (c.find('fields') or [])}
        d['_value'] = c.findtext('value') or ''
        d['_footprint'] = c.findtext('footprint') or ''
        res[c.get('ref')] = d
    return res


def erc(sch: str) -> Dict[str, int]:
    out = sch + '.erc.json'
    r = cli('sch', 'erc', '--severity-all', '--format', 'json', '-o', out, sch)
    assert os.path.exists(out), r.stdout + r.stderr
    d = json.load(open(out))
    return dict(collections.Counter(v['type'] for s in d['sheets'] for v in s['violations']))


def drc(pcb: str, refill: bool = True, parity: bool = False) -> dict:
    out = pcb + '.drc.json'
    args = ['pcb', 'drc', '--severity-all', '--format', 'json', '-o', out]
    if refill:
        args += ['--refill-zones']
    if parity:
        args += ['--schematic-parity']
    r = cli(*(args + [pcb]))
    assert os.path.exists(out), 'KiCad could not load %s: %s' % (pcb, r.stdout + r.stderr)
    d = json.load(open(out))
    return dict(violations=dict(collections.Counter(v['type'] for v in d['violations'])),
                unconnected=len(d.get('unconnected_items', [])), parity=len(d.get('schematic_parity', [])),
                raw=d)


def resave(path: str) -> str:
    """Have KiCad load and re-save a file (kicad-cli ... upgrade --force); returns the re-saved text."""
    ext = path.rsplit('.', 1)[1]
    if ext == 'kicad_pcb':
        r = cli('pcb', 'upgrade', '--force', path)
    elif ext == 'kicad_sch':
        r = cli('sch', 'upgrade', '--force', path)
    elif ext == 'kicad_sym':
        r = cli('sym', 'upgrade', '--force', path)
    else:
        raise ValueError(ext)
    assert r.returncode == 0, r.stdout + r.stderr
    return open(path, encoding='utf-8').read()


def corpus(pattern_env: str = 'KICAD_SEXPR_CORPUS') -> List[str]:
    """Extra real files to round-trip: KICAD_SEXPR_CORPUS = colon-separated globs."""
    out: List[str] = []
    for g in os.environ.get(pattern_env, '').split(':'):
        if g:
            out += sorted(glob.glob(g, recursive=True))
    return out
