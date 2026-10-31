"""Stacked pins drawn by symgen do not make global nets:  python3 tests/test_symgen_stacked.py
A hidden power_in pin is an implicit global net of the pin's name in KiCad, so the extra numbers of a stacked pin are
written the way KiCad's own libraries write them: one visible pin with the stated type, the others passive (no_connect
for NC) and hidden on the same point. With kicad-cli: two regulators whose stacked IN pins sit on different nets stay
on different nets (no global "IN", no multiple_net_names), the stacked numbers join their visible pin's net, and a
stacked NC pin left open raises no ERC."""
import collections, json, os, shutil, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import symgen
from schgen import Sch, kicad_symbol_dir
from kicad_sexpr import LibTable

REG = symgen.ic('REG', 5.08, left=[('IN', ['3', '4'], symgen.PI), ('EN', ['6'], symgen.IN)],
                right=[('OUT', ['1', '7'], symgen.PO), ('NC', ['8', '9'], symgen.NC)],
                bottom=[('GND', ['2', '5'], symgen.PI)],
                footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', datasheet='https://example.com/reg.pdf')


def _pins(sym):
    return [(str(p[1]), p.get('number'), p.find('hide') is not None, tuple(p.need('at')[1:3]))
            for sub in sym.nodes('symbol') for p in sub.nodes('pin')]


def test_stacked_copies_are_hidden_passive_on_the_same_point():
    pins = {num: (typ, hidden, at) for typ, num, hidden, at in _pins(REG)}
    assert pins['3'][:2] == ('power_in', False) and pins['4'][:2] == ('passive', True) and pins['3'][2] == pins['4'][2]
    assert pins['1'][:2] == ('power_out', False) and pins['7'][:2] == ('passive', True) and pins['1'][2] == pins['7'][2]
    assert pins['2'][:2] == ('power_in', False) and pins['5'][:2] == ('passive', True)
    assert pins['8'][:2] == ('no_connect', False) and pins['9'][:2] == ('no_connect', True)   # NC stays NC
    assert not [p for p in _pins(REG) if p[2] and p[0] not in ('passive', 'no_connect')], 'a hidden typed pin'


def test_fet_extra_pads_are_hidden_passive():
    from schgen import SymLib
    q = symgen.fet(SymLib('Device', kicad_symbol_dir() + '/Device.kicad_sym').get('Q_NMOS'), 'Q', D=['5', '6', '7', '8'],
                   G=['4'], S=['1', '2', '3'])
    assert not [p for p in _pins(q) if p[2] and p[0] != 'passive'], 'a hidden pin that is not passive'


def test_two_parts_with_stacked_supply_pins_stay_on_their_own_nets():
    cli = os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
    if not os.path.exists(cli):
        print('  (skipped: no kicad-cli)'); return
    d = tempfile.mkdtemp()
    lib = symgen.library({'REG': REG})
    lib.save(os.path.join(d, 'P.kicad_sym'))
    t = LibTable.for_project(d, 'sym'); t.add('P', 'P.kicad_sym'); t.save()
    s = Sch('t', paper='A4')
    s.lib('P', lib=lib)
    s.lib('power', kicad_symbol_dir() + '/power.kicad_sym')
    for i, (ref, net) in enumerate((('U1', 'VA'), ('U2', 'VB'))):
        u = s.add('P:REG', ref, 'REG', 76.2 + 50.8 * i, 63.5)
        x, y = u.p('IN')
        s.wire((x, y), (x - 7.62, y))
        s.label(net, x - 7.62, y)
        s.power('GND', *u.p('GND'))
        for pin in ('EN', 'OUT'):
            s.nc(u.p(pin))
    sch = os.path.join(d, 't.kicad_sch')
    s.write(sch)
    out = os.path.join(d, 'net.xml')
    subprocess.run([cli, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', out, sch], check=True, capture_output=True)
    nets = {n.get('name'): sorted('%s.%s' % (x.get('ref'), x.get('pin')) for x in n.findall('node'))
            for n in ET.parse(out).getroot().find('nets')}
    assert nets['/VA'] == ['U1.3', 'U1.4'] and nets['/VB'] == ['U2.3', 'U2.4'], nets
    assert 'IN' not in nets and nets['GND'] == ['U1.2', 'U1.5', 'U2.2', 'U2.5'], nets
    erc = os.path.join(d, 'erc.json')
    subprocess.run([cli, 'sch', 'erc', '--severity-all', '--format', 'json', '-o', erc, sch], capture_output=True)
    kinds = collections.Counter(v['type'] for sh in json.load(open(erc))['sheets'] for v in sh['violations'])
    assert 'multiple_net_names' not in kinds and 'no_connect_connected' not in kinds, kinds
    assert kinds.get('pin_not_connected', 0) == 0, kinds          # the unflagged NC stack (8, 9) is not an open pin


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                import traceback; traceback.print_exc()
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
