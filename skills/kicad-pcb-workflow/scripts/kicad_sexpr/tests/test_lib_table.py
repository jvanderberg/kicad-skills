"""Library tables: add_library creates, appends and updates entries in KiCad's own layout, and leaves a table that
already has the entry untouched."""
import os

from helpers import tmpdir
from kicad_sexpr import add_library, library_names

KICAD_SAVED = '''(fp_lib_table
\t(version 7)
\t(lib
\t\t(name "JLCImport")
\t\t(type "KiCad")
\t\t(uri "${KIPRJMOD}/JLCImport.pretty")
\t\t(options "")
\t\t(descr "")
\t)
)
'''


def test_add_and_update_entries():
    d = tmpdir('libtable')
    fp = os.path.join(d, 'fp-lib-table')
    open(fp, 'w').write(KICAD_SAVED)
    assert add_library(fp, 'proj', '${KIPRJMOD}/proj.pretty')
    text = open(fp).read()
    assert text == KICAD_SAVED[:-2] + ('\t(lib\n\t\t(name "proj")\n\t\t(type "KiCad")\n\t\t(uri "${KIPRJMOD}/proj.pretty")\n'
                                       '\t\t(options "")\n\t\t(descr "")\n\t)\n)\n'), text
    assert not add_library(fp, 'proj', '${KIPRJMOD}/proj.pretty') and open(fp).read() == text      # already there
    assert add_library(fp, 'JLCImport', '${KIPRJMOD}/lib/JLCImport.pretty')                         # moved: updated
    assert library_names(fp) == ['JLCImport', 'proj'] and '${KIPRJMOD}/lib/JLCImport.pretty' in open(fp).read()


def test_new_symbol_table():
    sym = os.path.join(tmpdir('libtable2'), 'sym-lib-table')
    assert add_library(sym, 'proj', '${KIPRJMOD}/proj.kicad_sym', descr='project symbols')
    assert open(sym).read().startswith('(sym_lib_table\n\t(version 7)\n\t(lib\n\t\t(name "proj")')
    try:
        add_library(os.path.join(os.path.dirname(sym), 'lib-table'), 'x', 'y'); raise AssertionError('accepted a bad name')
    except ValueError:
        pass
