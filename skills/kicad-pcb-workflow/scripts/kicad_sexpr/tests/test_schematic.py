"""Schematic builders, checked by KiCad itself (kicad-cli netlist export, ERC and re-save)."""
import os

from helpers import erc, netlist, netlist_components, resave, symbols_dir, tmpdir
from kicad_sexpr import (Node, Schematic, SymbolLibrary, dumps, lib_pin, lib_property, lib_rectangle, lib_symbol,
                         load, loads)


def _libs():
    d = symbols_dir()
    return {n: SymbolLibrary.load(os.path.join(d, n + '.kicad_sym'), n)
            for n in ('Device', 'power', 'Regulator_Linear')}


def test_pin_positions_all_orientations():
    """pin() after every rotation x mirror: a label at each computed pin point must land on that pin (netlist).
    AMS1117-3.3 is a derived symbol (extends AMS1117-ADJ...), so this also checks flattening."""
    libs = _libs()
    s = Schematic.new('t')
    s.embed_symbol('Regulator_Linear:AMS1117-3.3', libs['Regulator_Linear'])
    i = 0
    for ang in (0, 90, 180, 270):
        for mir in (None, 'x', 'y'):
            u = s.add_symbol('Regulator_Linear:AMS1117-3.3', 'U%d' % (i + 1), 'AMS1117',
                             (25.4 + 38.1 * (i % 4), 25.4 + 38.1 * (i // 4)), ang, mir)
            for num, pt in u.pins().items():
                s.label('O%d_%s' % (i, num), pt)
            i += 1
    d = tmpdir('pins')
    p = os.path.join(d, 't.kicad_sch')
    s.save(p)
    nets = netlist(p)
    checked = 0
    for name, pins in nets.items():
        for rp in pins:
            ref, pin = rp.split('.')
            assert name.endswith('O%d_%s' % (int(ref[1:]) - 1, pin)), (name, rp)
            checked += 1
    assert checked == 36


def test_wired_block_netlist_and_erc():
    """A small wired block with power symbols, a junction, labels, a no-connect and text: ERC clean, netlist right."""
    libs = _libs()
    s = Schematic.new('demo', paper='A4', title='demo "block"', date='2026-10-24', rev='1')
    for lib_id, lib in (('Device:R', libs['Device']), ('Device:C', libs['Device']), ('power:GND', libs['power']),
                        ('power:+3V3', libs['power']), ('power:PWR_FLAG', libs['power'])):
        s.embed_symbol(lib_id, lib)
    r1 = s.add_symbol('Device:R', 'R1', '10k', (50.8, 50.8), footprint='Resistor_SMD:R_0402_1005Metric',
                      fields={'LCSC': 'C25744'})
    c1 = s.add_symbol('Device:C', 'C1', '100n', (63.5, 58.42), footprint='Capacitor_SMD:C_0402_1005Metric')
    r1.set_field('LCSC', at=(53.34, 55.88), hide=False)           # an extra visible field
    top, bot = r1.pin(1), r1.pin(2)
    vcc = s.power('power:+3V3', (top[0], top[1] - 2.54))
    s.wire(vcc.pin(1), top)
    s.wire(bot, (bot[0], 58.42 - 3.81), (c1.pin(1)[0], 58.42 - 3.81), c1.pin(1))
    s.junction((bot[0], 58.42 - 3.81))
    s.wire((bot[0], 58.42 - 3.81), (bot[0], 66.04))
    s.label('MID', (bot[0], 66.04), 270)
    g = s.power('power:GND', (c1.pin(2)[0], c1.pin(2)[1] + 2.54))
    s.wire(c1.pin(2), g.pin(1))
    s.global_label('MID_OUT', (76.2, 58.42 - 3.81), 0, 'output')
    s.wire((c1.pin(1)[0], 58.42 - 3.81), (76.2, 58.42 - 3.81))
    flags = [s.add_symbol('power:PWR_FLAG', '#FLG0%d' % k, 'PWR_FLAG', (30.48 + 10.16 * k, 30.48), in_bom=False,
                          on_board=False) for k in (1, 2)]
    s.wire(flags[0].pin(1), (flags[0].pin(1)[0], 35.56))
    s.power('power:+3V3', (flags[0].pin(1)[0], 35.56), angle=180)
    s.wire(flags[1].pin(1), (flags[1].pin(1)[0], 35.56))
    s.power('power:GND', (flags[1].pin(1)[0], 35.56))
    s.text('multi-line note:\n"quoted" \\ back-slash', (30.48, 80.0))
    d = tmpdir('block')
    p = os.path.join(d, 'demo.kicad_sch')
    s.save(p)
    # the only ERC finding is the deliberate one: local label MID and global label MID_OUT name the same net
    assert erc(p) == {'multiple_net_names': 1}, erc(p)
    nets = {k: sorted(v) for k, v in netlist(p).items()}
    assert sorted(nets['+3V3']) == ['R1.1']
    assert sorted(nets['GND']) == ['C1.2']
    mid = [v for k, v in nets.items() if 'C1.1' in v]
    assert mid == [['C1.1', 'R1.2']], nets
    comps = netlist_components(p)
    assert comps['R1']['LCSC'] == 'C25744' and comps['R1']['_footprint'] == 'Resistor_SMD:R_0402_1005Metric'
    # KiCad re-saves it without dropping anything, and the text survives with its quote, backslash and newline
    t = resave(p)
    texts = [n for n in loads(t).nodes('text')]
    assert texts and texts[0][1] == 'multi-line note:\n"quoted" \\ back-slash'
    assert len(loads(t).nodes('symbol')) == len(s.tree.nodes('symbol'))


def test_hierarchical_sheet():
    """Root sheet with a sheet block + sheet pin, sub-sheet with a hierarchical label: the net joins across."""
    libs = _libs()
    d = tmpdir('hier')
    root = Schematic.new('hier')
    sub_path = os.path.join(d, 'sub.kicad_sch')
    blk = root.sheet('Sub', 'sub.kicad_sch', (101.6, 50.8), (25.4, 12.7), pins=[('SIG', 'input', (101.6, 55.88), 180)])
    root.embed_symbol('Device:R', libs['Device'])
    r1 = root.add_symbol('Device:R', 'R1', '1k', (76.2, 55.88), 90, footprint='Resistor_SMD:R_0402_1005Metric')
    root.wire(r1.pin(1), (101.6, 55.88))
    root.no_connect(r1.pin(2))
    sub = Schematic.new('hier', root=False, instance_path='/%s/%s' % (root.uuid, blk.get('uuid')))
    sub.embed_symbol('Device:R', libs['Device'])
    r2 = sub.add_symbol('Device:R', 'R2', '2k', (76.2, 55.88), 90, footprint='Resistor_SMD:R_0402_1005Metric')
    sub.wire(r2.pin(2), (88.9, 55.88))
    sub.hierarchical_label('SIG', (88.9, 55.88), 0, 'input')
    sub.no_connect(r2.pin(1))
    root.save(os.path.join(d, 'hier.kicad_sch'))
    sub.save(sub_path)
    nets = netlist(os.path.join(d, 'hier.kicad_sch'))
    joined = [sorted(v) for v in nets.values() if 'R1.1' in v]
    assert joined == [['R1.1', 'R2.2']], nets
    comps = netlist_components(os.path.join(d, 'hier.kicad_sch'))
    assert set(comps) == {'R1', 'R2'}


def test_library_symbol_builder_and_load_modify_save():
    """Build a library symbol, place it, then re-load the sheet and modify it (read-modify-write)."""
    sym = lib_symbol('TEST', [lib_property('Reference', 'U', 0, 6.35), lib_property('Value', 'TEST', 0, -6.35),
                              lib_property('Footprint', '', hide=True), lib_property('Datasheet', '', hide=True),
                              lib_property('Description', 'test part', hide=True)],
                     {(0, 1): [lib_rectangle(-5.08, 5.08, 5.08, -5.08)],
                      (1, 1): [lib_pin('input', -7.62, 2.54, 0, 'IN', '1'),
                               lib_pin('output', 7.62, 2.54, 180, 'OUT', '2'),
                               lib_pin('passive', 0, -7.62, 90, 'COM', '3'),
                               lib_pin('passive', 0, -7.62, 90, 'COM', '4', hide=True)]})
    lib = SymbolLibrary.new('t')
    lib.add(sym)
    d = tmpdir('libsym')
    lp = os.path.join(d, 't.kicad_sym')
    lib.save(lp)
    assert resave(lp)                                            # KiCad accepts the library
    s = Schematic.new('m')
    u = s.add_symbol('t:TEST', 'U1', 'TEST', (50.8, 50.8), lib=SymbolLibrary.load(lp, 't'))
    for k in ('1', '2', '3'):
        s.label('N' + k, u.pin(k))
    p = os.path.join(d, 'm.kicad_sch')
    s.save(p)
    s2 = Schematic.load(p)
    u2 = s2.symbol('U1')
    u2.set_field('Value', 'TEST2')
    u2.set_field('Reference', 'U7')
    assert u2.pin('OUT') == u.pin('2')
    s2.save()
    comps = netlist_components(p)
    assert set(comps) == {'U7'} and comps['U7']['_value'] == 'TEST2' and comps['U7']['Description'] == 'test part'
    nets = netlist(p)
    assert sorted(v for k, v in nets.items() if k.endswith('N3'))[0] == ['U7.3', 'U7.4']


def test_validate_rejects_duplicates():
    libs = _libs()
    s = Schematic.new('v')
    s.embed_symbol('Device:R', libs['Device'])
    s.add_symbol('Device:R', 'R1', '1k', (25.4, 25.4))
    s.add_symbol('Device:R', 'R1', '1k', (50.8, 25.4))
    assert any('duplicate references' in p for p in s.validate())
    s2 = Schematic.new('v')
    s2.add(Node('junction', Node('at', 1, 1), Node('uuid', 'a')))
    s2.add(Node('junction', Node('at', 2, 2), Node('uuid', 'a')))
    assert any('duplicated uuids' in p for p in s2.validate())


def test_loaded_real_schematic_round_trips_through_api():
    """Load -> touch nothing -> save is byte-identical for a sheet KiCad saved (here: re-saved by kicad-cli)."""
    libs = _libs()
    s = Schematic.new('rt')
    s.embed_symbol('Device:R', libs['Device'])
    s.add_symbol('Device:R', 'R1', '1k', (25.4, 25.4))
    d = tmpdir('rt')
    p = os.path.join(d, 'rt.kicad_sch')
    s.save(p)
    t = resave(p)
    s2 = Schematic.load(p)
    s2.save()
    assert open(p).read() == t
    assert dumps(load(p)) == t


def test_bus_and_polyline_survive_kicad_resave():
    s = Schematic.new('m')
    s.bus((25.4, 25.4), (50.8, 25.4))
    s.polyline([(25.4, 30.48), (50.8, 30.48), (50.8, 40.64)], width=0.2, type_='dash')
    d = tmpdir('bus')
    p = os.path.join(d, 'm.kicad_sch')
    s.save(p)
    t = loads(resave(p))
    assert len(t.nodes('bus')) == 1 and len(t.nodes('polyline')) == 1
    assert str(t.find('polyline').need('stroke').get('type')) == 'dash'
