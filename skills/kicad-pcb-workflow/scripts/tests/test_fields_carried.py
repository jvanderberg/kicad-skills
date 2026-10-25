"""Part data survives every generator stage, or the stage fails:  python3 tests/test_fields_carried.py
symbol redraw (symgen inherit) -> placed symbol (schgen: library value, LCSC fallback) -> schematic written ->
partfields check; a part with no datasheet anywhere upstream makes schgen.write() raise instead of writing a blank.
With kicad-cli available: netlist -> new_board.py -> the board carries the same Datasheet and LCSC (parity)."""
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import symgen, partfields
from schgen import Sch
from kicad_sexpr import SymbolLibrary, dumps

IMPORTED = symgen.ic('BOOST1_IMPORTED', 5.08, left=[('VIN', ['1'], symgen.PI)], right=[('VOUT', ['2'], symgen.PO)],
                     bottom=[('GND', ['3'], symgen.PI)], footprint='Package_TO_SOT_SMD:SOT-23',
                     datasheet='https://www.ti.com/lit/ds/symlink/tps61023.pdf')
for k, v in (('LCSC', 'C2869700'), ('Manufacturer', 'Texas Instruments')):
    IMPORTED.append(symgen.lib_property(k, v, hide=True))


def lib():
    redrawn = symgen.ic('BOOST1', 5.08, left=[('VIN', ['1'], symgen.PI)], right=[('VOUT', ['2'], symgen.PO)],
                        bottom=[('GND', ['3'], symgen.PI)], inherit=IMPORTED)                  # no datasheet= given
    res = symgen.ic('R', 2.54, left=[('~', ['1'], symgen.PA)], right=[('~', ['2'], symgen.PA)], ref='R',
                    datasheet='https://generic.example/resistor-symbol.pdf')   # a generic symbol's link, not a part's
    blank = symgen.ic('BLANK', 2.54, left=[('~', ['1'], symgen.PA)], right=[('~', ['2'], symgen.PA)], ref='R')
    return symgen.library({'BOOST1': redrawn, 'R': res, 'BLANK': blank})


def test_redraw_inherits_imported_fields():
    p = {str(q[1]): str(q[2]) for q in lib().get('BOOST1').nodes('property')}
    assert p['Datasheet'] == 'https://www.ti.com/lit/ds/symlink/tps61023.pdf', p
    assert p['Footprint'] == 'Package_TO_SOT_SMD:SOT-23' and p['LCSC'] == 'C2869700' and p['Manufacturer'] == 'Texas Instruments', p


def sheet(d, with_blank):
    s = Sch('t', paper='A4')
    s.lib('P', lib=lib())
    s.add('P:BOOST1', 'U1', 'TPS61023', 50.8, 50.8)                                     # everything from the library
    s.add('P:R', 'R1', '10k', 30.48, 50.8, footprint='Resistor_SMD:R_0402_1005Metric', lcsc='C25744')
    if with_blank:
        s.add('P:BLANK', 'R2', '1k', 30.48, 60.96, footprint='Resistor_SMD:R_0402_1005Metric')   # no LCSC, no datasheet
    return s


def test_placed_symbols_carry_library_and_lcsc_datasheets():
    d = tempfile.mkdtemp()
    s = sheet(d, False)
    s.write(os.path.join(d, 't.kicad_sch'))
    parts = partfields.schematic_parts(os.path.join(d, 't.kicad_sch'))
    assert parts['U1']['fields']['Datasheet'] == 'https://www.ti.com/lit/ds/symlink/tps61023.pdf', parts['U1']
    assert parts['U1']['fields']['LCSC'] == 'C2869700' and parts['U1']['fields']['Footprint'] == 'Package_TO_SOT_SMD:SOT-23'
    assert parts['R1']['fields']['Datasheet'] == 'https://www.lcsc.com/datasheet/C25744.pdf', parts['R1']   # the part's own wins
    assert s.field_sources == {'U1': 'library symbol', 'R1': 'LCSC C25744'}, s.field_sources
    r = partfields.check(os.path.join(d, 't.kicad_sch'))
    assert not r['problems'] and r['with_datasheet'] == 2, r


def test_blank_datasheet_fails_write_unless_accepted():
    d = tempfile.mkdtemp()
    s = sheet(d, True)
    try:
        s.write(os.path.join(d, 't.kicad_sch')); raise AssertionError('write() accepted a BOM part with no datasheet')
    except ValueError as e:
        assert 'R2' in str(e) and 'R1' not in str(e).split(':')[1], e
    assert not os.path.exists(os.path.join(d, 't.kicad_sch'))
    s.accept_missing('R2', 'Datasheet', 'synthetic test part')
    s.write(os.path.join(d, 't.kicad_sch'))
    r = partfields.check(os.path.join(d, 't.kicad_sch'))
    assert any(x.startswith('R2 Datasheet') for x in r['problems']), r      # the checker still reports it...
    r = partfields.check(os.path.join(d, 't.kicad_sch'), accept={'R2': {'Datasheet': 'synthetic', 'LCSC|MPN': 'synthetic'}})
    assert not r['problems'] and r['exempt'], r                               # ...until it is exempted by name


def test_board_carries_fields_and_parity_catches_drift():
    cli = os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
    if not os.path.exists(cli):
        print('  (skipped: no kicad-cli)'); return
    d = tempfile.mkdtemp()
    s = sheet(d, False)
    s.write(os.path.join(d, 't.kicad_sch'))
    lib().save(os.path.join(d, 'P.kicad_sym'))
    open(os.path.join(d, 'sym-lib-table'), 'w').write('(sym_lib_table (version 7) (lib (name "P")(type "KiCad")(uri "${KIPRJMOD}/P.kicad_sym")(options "")(descr "")))\n')
    subprocess.run([cli, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', os.path.join(d, 'net.xml'), os.path.join(d, 't.kicad_sch')],
                   check=True, capture_output=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'new_board.py'), os.path.join(d, 'net.xml'), os.path.join(d, 't.kicad_pcb')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    res = partfields.check(os.path.join(d, 't.kicad_sch'), os.path.join(d, 't.kicad_pcb'))
    assert not res['problems'], res
    b = partfields.board_parts(os.path.join(d, 't.kicad_pcb'))
    assert b['U1']['fields']['Datasheet'].endswith('tps61023.pdf') and b['R1']['fields']['LCSC'] == 'C25744', b
    t = open(os.path.join(d, 't.kicad_pcb')).read().replace('"C25744"', '"C99999"')     # LCSC drifted on the board
    open(os.path.join(d, 't.kicad_pcb'), 'w').write(t)
    res = partfields.check(os.path.join(d, 't.kicad_sch'), os.path.join(d, 't.kicad_pcb'))
    assert any('R1 LCSC' in x for x in res['problems']), res


def test_board_carries_assembly_attributes():
    """DNP, not-in-BOM and not-in-position-file reach the footprint (the symbol wins over the library's attributes), so
    the BOM, the assembler's position file and schematic parity agree without a project fix-up script; KiCad re-saves
    the attributes unchanged (same order)"""
    cli = os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
    if not os.path.exists(cli):
        print('  (skipped: no kicad-cli)'); return
    d = tempfile.mkdtemp()
    s = Sch('t', paper='A4')
    s.lib('P', lib=lib())
    s.add('P:BOOST1', 'U1', 'TPS61023', 50.8, 50.8)                                                    # assembled
    s.add('P:R', 'R1', '10k', 30.48, 50.8, footprint='Resistor_SMD:R_0402_1005Metric', lcsc='C25744', dnp=True)   # not fitted
    s.add('P:R', 'R2', '1k', 30.48, 60.96, footprint='Resistor_SMD:R_0402_1005Metric', lcsc='C25744', in_bom=False)  # hand-fit
    s.add('P:R', 'R3', '1k', 30.48, 71.12, footprint='Resistor_SMD:R_0402_1005Metric', lcsc='C25744', in_pos_files=False)
    s.write(os.path.join(d, 't.kicad_sch'))
    lib().save(os.path.join(d, 'P.kicad_sym'))
    open(os.path.join(d, 'sym-lib-table'), 'w').write('(sym_lib_table (version 7) (lib (name "P")(type "KiCad")(uri "${KIPRJMOD}/P.kicad_sym")(options "")(descr "")))\n')
    subprocess.run([cli, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', os.path.join(d, 'net.xml'), os.path.join(d, 't.kicad_sch')],
                   check=True, capture_output=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'new_board.py'), os.path.join(d, 'net.xml'), os.path.join(d, 't.kicad_pcb')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert '1 dnp, 1 exclude_from_bom, 2 exclude_from_pos_files' in r.stdout, r.stdout
    pcb = os.path.join(d, 't.kicad_pcb')
    b = partfields.board_parts(pcb)
    assert b['R1']['dnp'] and not b['R1']['exclude_from_bom'] and not b['U1']['dnp'], b['R1']
    assert b['R2']['exclude_from_bom'] and b['R2']['exclude_from_pos'] and b['R3']['exclude_from_pos'] and not b['R3']['exclude_from_bom']
    res = partfields.check(os.path.join(d, 't.kicad_sch'), pcb)
    assert not res['problems'], res
    before = [l.strip() for l in open(pcb) if l.strip().startswith('(attr')]
    subprocess.run([cli, 'pcb', 'drc', '--save-board', '-o', os.path.join(d, 'drc.json'), '--format', 'json', pcb], capture_output=True)
    after = [l.strip() for l in open(pcb) if l.strip().startswith('(attr')]
    assert before == after, (before, after)
    # drift on the board is caught: the position-file attribute dropped
    t = open(pcb).read().replace('(attr smd exclude_from_pos_files)', '(attr smd)', 1)
    open(pcb, 'w').write(t)
    res = partfields.check(os.path.join(d, 't.kicad_sch'), pcb)
    assert any('R3 in_pos_files' in x for x in res['problems']), res


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
