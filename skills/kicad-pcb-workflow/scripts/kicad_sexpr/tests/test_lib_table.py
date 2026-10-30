"""Library tables: KiCad 10's layout, project-relative entries, idempotent adds, refused conflicts, and resolution the
way KiCad's LIBRARY_MANAGER does it (later rows win, disabled rows hide, Table rows expand in place)."""
import os
import subprocess
import sys

from helpers import tmpdir
from kicad_sexpr import LibTable, dumps, load, loads, resolve_libraries

# the first rows of KiCad 10's stock template fp-lib-table, in the layout KiCad saves
KICAD_SAVED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'kicad10_template.fp-lib-table')
SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _raises(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except ValueError as e:
        return str(e)
    raise AssertionError('no ValueError from %s%r' % (fn.__name__, args))


def _project(*libs):
    """A scratch project folder with a .kicad_pro and the named library files / folders."""
    d = tmpdir('libtable')
    open(os.path.join(d, 'p.kicad_pro'), 'w').write('{}\n')
    for lib in libs:
        p = os.path.join(d, lib)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.makedirs(p) if lib.endswith('.pretty') else open(p, 'w').close()
    return d


def test_kicad_saved_table_rewrites_byte_identical():
    """KiCad 10 saves tables in its LIBRARY_TABLE mode: tabs, each (lib ...) row on one line."""
    text = open(KICAD_SAVED, encoding='utf-8').read()
    assert dumps(load(KICAD_SAVED)) == text
    t = LibTable.load(KICAD_SAVED)
    assert t.kind == 'fp' and t.names()[0] == 'Audio_Module'


def test_project_table_layout_and_idempotent_add():
    d = _project('proj.kicad_sym', 'libs/sub.kicad_sym')
    t = LibTable.for_project(d, 'sym')
    assert t.path == os.path.join(d, 'sym-lib-table') and t.rows() == []
    assert t.add('Proj', os.path.join(d, 'proj.kicad_sym'), descr='project symbols')
    assert t.add('Sub', 'libs/sub.kicad_sym')                      # relative to the project folder
    t.save()
    assert open(t.path).read() == (
        '(sym_lib_table\n\t(version 7)\n'
        '\t(lib (name "Proj") (type "KiCad") (uri "${KIPRJMOD}/proj.kicad_sym") (options "") (descr "project symbols"))\n'
        '\t(lib (name "Sub") (type "KiCad") (uri "${KIPRJMOD}/libs/sub.kicad_sym") (options "") (descr ""))\n'
        ')\n')
    again = LibTable.load(t.path)                                  # next to a .kicad_pro: a project table
    assert again.project_dir == os.path.abspath(d)
    for spelling in ('proj.kicad_sym', '${KIPRJMOD}/proj.kicad_sym', '$(KIPRJMOD)/proj.kicad_sym',
                     '${KIPRJMOD}/./proj.kicad_sym', os.path.join(d, 'proj.kicad_sym')):
        assert again.add('Proj', spelling) is False, spelling      # same nickname, same file: nothing to do
    assert LibTable.new('fp').add('X', '${KICAD10_FOOTPRINT_DIR}/X.pretty', must_exist=False)


def test_conflicts_and_bad_input_are_refused():
    d = _project('JLCImport.pretty', 'Other.pretty', 'x.kicad_sym')
    t = LibTable.for_project(d, 'fp')
    t.add('JLCImport', 'JLCImport.pretty', descr='imported')
    t.tree.nodes('lib')[-1].append(loads('(hidden)'))
    assert 'already names' in _raises(t.add, 'JLCImport', 'Other.pretty')
    for spelling in ('JLCImport.pretty', '$(KIPRJMOD)/JLCImport.pretty/', os.path.join(d, 'JLCImport.pretty')):
        assert 'already registered as "JLCImport"' in _raises(t.add, 'Second', spelling), spelling
    assert 'outside the project' in _raises(t.add, 'Far', os.path.join(os.path.dirname(d), 'far.pretty'))
    assert 'outside the project' in _raises(t.add, 'Far', '${KIPRJMOD}/../far.pretty')
    assert 'KICADn_' in _raises(t.add, 'Home', '${HOME}/far.pretty')
    assert 'does not exist' in _raises(t.add, 'Gone', 'gone.pretty')
    assert 'not a fp library' in _raises(t.add, 'Sym', 'x.kicad_sym')
    assert 'bad library nickname' in _raises(t.add, 'a:b', 'Other.pretty')
    assert 'bad library nickname' in _raises(t.add, 'a\\b', 'Other.pretty')
    assert 'literally' in _raises(t.add, 'Q', 'Other.pretty', descr='the "main" lib')
    assert 'literally' in _raises(t.add, 'Q', 'Other.pretty', descr='two\nlines')
    assert t.add('JLCImport', 'Other.pretty', replace=True)        # re-pointed in place: settings kept
    r = t.row('JLCImport')
    assert (r.uri, r.descr, r.hidden) == ('${KIPRJMOD}/Other.pretty', 'imported', True), r
    assert t.remove('JLCImport') and not t.rows()


def test_resolution_matches_kicad():
    """KiCad's LIBRARY_MANAGER::Rows: rows[nickname] = row in reading order, so a later row wins, a disabled row
    still hides an earlier one, and a Table row's libraries replace earlier rows of the same nickname."""
    d = _project()
    inner = LibTable.new('fp', os.path.join(d, 'inner-fp-lib-table'))
    inner.add('Stock', '${STOCK}/Stock.pretty', must_exist=False)
    inner.add('Proj', '/elsewhere/Proj.pretty', must_exist=False)
    inner.save()
    t = LibTable.for_project(d, 'fp')
    for name in ('Proj', 'Twice', 'Off'):
        t.add(name, name + '.pretty', must_exist=False)
    t.tree.nodes('lib')[-1].append(loads('(disabled)'))
    t.add('Nested', os.path.join(d, 'inner-fp-lib-table'), type='Table', must_exist=False)
    t.tree.append(loads('(lib (name "Twice") (type "KiCad") (uri "${KIPRJMOD}/Later.pretty") (options "") (descr ""))'))
    t.save()
    assert '(disabled)' in open(t.path).read().splitlines()[4]      # on the row's own line, as KiCad writes it
    p = d.replace('\\', '/')
    res = LibTable.load(t.path).resolve({'STOCK': '/kicad/fp'})
    assert res == {'Proj': '/elsewhere/Proj.pretty', 'Twice': p + '/Later.pretty', 'Off': None,
                   'Stock': '/kicad/fp/Stock.pretty'}, res
    assert t.row('Twice').uri == '${KIPRJMOD}/Later.pretty'          # row() is the row KiCad uses
    assert 'Off' not in resolve_libraries(d, 'fp', {'STOCK': '/kicad/fp'}, include_global=False)


def test_empty_file_is_an_empty_table():
    d = _project('A.pretty')
    open(os.path.join(d, 'fp-lib-table'), 'w').close()               # KiCad accepts a 0- or 1-byte table
    t = LibTable.for_project(d, 'fp')
    assert t.rows() == [] and t.add('A', 'A.pretty')


def test_cli_add_list_remove():
    d = _project('My.pretty', 'my.kicad_sym')

    def run(*args):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'libtable.py')] + list(args), capture_output=True,
                           text=True)
        return r.returncode, r.stdout + r.stderr
    assert run('add', d, 'fp', 'My', 'My.pretty')[0] == 0
    assert 'unchanged' in run('add', d, 'fp', 'My', os.path.join(d, 'My.pretty'))[1]
    rc, out = run('add', d, 'sym', 'Bad', 'my.kicad_sym', '--descr', 'a "quoted" word')
    assert rc == 1 and 'not changed' in out, out
    rc, out = run('add', d, 'fp', 'My', 'Other.pretty')
    assert rc == 1 and 'does not exist' in out, out
    open(os.path.join(d, 'fp-lib-table'), 'a').write('')
    rc, out = run('list', d, 'fp')
    assert rc == 0 and '${KIPRJMOD}' not in out and 'My.pretty' in out, out
    os.rmdir(os.path.join(d, 'My.pretty'))
    rc, out = run('list', d, 'fp')
    assert rc == 1 and 'MISSING' in out, out
    assert run('remove', d, 'fp', 'My')[0] == 0 and LibTable.for_project(d, 'fp').rows() == []
    bare = tmpdir('libtable')                                        # no .kicad_pro: KiCad would never read it
    rc, out = run('add', bare, 'fp', 'X', 'X.pretty')
    assert rc == 1 and 'no .kicad_pro' in out, out


def test_save_library_registers_in_the_project_folder():
    """The table goes next to the .kicad_pro, wherever the library file sits; no project, nothing written."""
    sys.path.insert(0, SCRIPTS)
    import symgen
    d = _project()
    sym = {'X': symgen.ic('X', 2.54, left=[('A', ['1'], symgen.IN)], right=[('B', ['2'], symgen.OUT)])}
    table = symgen.save_library(sym, os.path.join(d, 'lib', 'x.kicad_sym'), 'X')
    assert table == os.path.join(d, 'sym-lib-table') and not os.path.exists(os.path.join(d, 'lib', 'sym-lib-table'))
    assert LibTable.load(table).row('X').uri == '${KIPRJMOD}/lib/x.kicad_sym'
    before = open(table).read()
    symgen.save_library(sym, os.path.join(d, 'lib', 'x.kicad_sym'), 'X')
    assert open(table).read() == before
    bare = tmpdir('libtable')
    assert 'no .kicad_pro' in _raises(symgen.save_library, sym, os.path.join(bare, 'y.kicad_sym'), 'Y')
    assert not os.listdir(bare)


def test_variables_backslashes_and_settings():
    d = _project('A.pretty', 'b.kicad_sym')
    t = LibTable.for_project(d, 'fp')
    for uri in ('${KICAD_MYLIBS}/X.pretty', '${KICAD10_3RD_PARTY}/footprints/X.pretty', '${HOME}/X.pretty'):
        assert 'KICADn_' in _raises(t.add, 'V', uri, must_exist=False), uri   # differs per machine
    assert t.add('Stock', '${KICAD10_FOOTPRINT_DIR}/Battery.pretty', must_exist=False)
    assert t.add('A', d + '\\A.pretty') and t.row('A').uri == '${KIPRJMOD}/A.pretty'   # backslashes become /
    assert 'contains' in _raises(t.add, 'B', 'A2.pretty', descr='C:\\libs', must_exist=False)
    assert t.add('A', 'A.pretty', descr='first') and t.row('A').descr == 'first'    # same file, new description
    assert t.add('A', 'A.pretty', descr='first') is False
    t.save()
    open(os.path.join(d, 'sym-lib-table'), 'w').write(open(t.path).read())        # an fp table under the sym name
    assert 'holds a fp_lib_table table' in _raises(LibTable.for_project, d, 'sym')
    open(t.path, 'w').write('(fp_lib_table (version 7) (lib (name "W") (type "KiCad") (uri "C:\\libs\\W.pretty") '
                            '(options "") (descr "")))\n')
    w = LibTable.for_project(d, 'fp')
    w.add('A', 'A.pretty')
    assert 'holds a backslash' in _raises(w.save)


def test_cli_paths_and_table_rows():
    d = _project('A.pretty', 'sub/In.pretty')
    inner = LibTable.new('fp', os.path.join(d, 'sub', 'fp-lib-table'))
    inner.add('In', os.path.join(d, 'sub', 'In.pretty'))
    inner.save()
    t = LibTable.for_project(d, 'fp')
    t.add('A', 'A.pretty')
    t.add('Sub', 'sub/fp-lib-table', type='Table')
    t.save()

    def run(*args):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'libtable.py')] + list(args), capture_output=True,
                           text=True, cwd=os.path.dirname(d))
        return r.returncode, r.stdout + r.stderr
    rc, out = run('add', d, 'fp', 'A2', '${KIPRJMOD}/A.pretty')
    assert rc == 1 and 'already registered as "A"' in out, out       # variable paths reach add() unchanged
    rc, out = run('add', d, 'fp', 'U', '${KICAD_MYLIBS}/U.pretty')
    assert rc == 1 and 'KICADn_' in out, out
    rc, out = run('list', d, 'fp')
    assert rc == 0 and 'In.pretty' in out and '  table' in out, out    # the Table row's libraries are listed
