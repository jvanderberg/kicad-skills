"""The generic tree: parsing, quoting, number formatting and KiCad's output layout. No KiCad needed except where
noted (round-trips of installed libraries and of files KiCad itself saved)."""
import glob
import os
import re
import shutil

from helpers import Skip, cli, corpus, footprints_dir, symbols_dir, tmpdir
from kicad_sexpr.sexp import Node, SexpError, Sym, dumps, fmt_num, loads, quote, unquote

TOK = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"]+', re.S)

# Verbatim from a board KiCad 10.0.1 saved: nested lists, quoted / bare atoms, (xy ...) packing and wrapping.
ZONE = '''(zone
	(net "GND")
	(layer "F.Cu")
	(uuid "03eadf43-1bae-4fd4-a0ad-f68aa79a259a")
	(name "PGND12")
	(hatch edge 0.5)
	(priority 10)
	(connect_pads yes
		(clearance 0.2)
	)
	(min_thickness 0.2)
	(fill yes
		(thermal_gap 0.3)
		(thermal_bridge_width 0.4)
		(island_removal_mode 0)
	)
	(polygon
		(pts
			(xy 114.4 110) (xy 119.1 110) (xy 119.1 111.4) (xy 120.3 111.4) (xy 120.3 115.1) (xy 118.65 115.1)
			(xy 118.65 111.55) (xy 114.4 111.55)
		)
	)
)
'''


def test_zone_layout_is_byte_identical():
    assert dumps(loads(ZONE)) == ZONE


def test_build_matches_kicad_layout():
    z = Node('zone', Node('net', 'GND'), Node('layer', 'F.Cu'), Node('uuid', '03eadf43-1bae-4fd4-a0ad-f68aa79a259a'),
             Node('name', 'PGND12'), Node('hatch', Sym('edge'), 0.5), Node('priority', 10),
             Node('connect_pads', Sym('yes'), Node('clearance', 0.2)), Node('min_thickness', 0.2),
             Node('fill', True, Node('thermal_gap', 0.3), Node('thermal_bridge_width', 0.4),
                  Node('island_removal_mode', 0)),
             Node('polygon', Node('pts', *[Node('xy', x, y) for x, y in
                                           [(114.4, 110), (119.1, 110), (119.1, 111.4), (120.3, 111.4), (120.3, 115.1),
                                            (118.65, 115.1), (118.65, 111.55), (114.4, 111.55)]])))
    assert dumps(z) == ZONE


def test_quoting_and_escapes():
    s = 'a "quoted" \\ back\nslash'
    assert quote(s) == '"a \\"quoted\\" \\\\ back\\nslash"'
    assert unquote(quote(s)) == s
    n = Node('text', s)
    back = loads(dumps(n))
    assert back[1] == s
    assert '\n' not in dumps(n).strip().split('\n')[0][6:], 'raw newline written inside a string'
    # a plain str is always quoted, a Sym never
    assert dumps(Node('x', 'yes', Sym('yes'))) == '(x "yes" yes)\n'


def test_empty_string_and_unicode():
    n = loads('(property "Value" "" (at 0 0 0) "Ω µ 国")')
    assert n[2] == '' and n[4] == 'Ω µ 国'
    assert dumps(n).count('"Ω µ 国"') == 1


def test_numbers():
    assert fmt_num(1.0) == '1' and fmt_num(0.25) == '0.25' and fmt_num(-0.0) == '0'
    assert fmt_num(1e-7) == '0' and fmt_num(123.4567891) == '123.456789' and fmt_num(1e6) == '1000000'
    assert dumps(Node('at', 1.27, -3.81, 90)) == '(at 1.27 -3.81 90)\n'
    try:
        fmt_num(float('nan'))
        raise AssertionError('nan accepted')
    except ValueError:
        pass


def test_numbers_read_keep_their_text():
    n = loads('(width 0.1500)')
    assert isinstance(n[1], Sym) and dumps(n) == '(width 0.1500)\n'


def test_parse_errors():
    for bad in ('(a (b)', '(a))', '(a) (b)', '', '("x" 1)'):
        try:
            loads(bad)
            raise AssertionError(bad)
        except SexpError:
            pass


def test_node_helpers():
    n = loads('(footprint "X" (layer "F.Cu") (at 1 2) (pad "1" smd rect (at 0 0)) (pad "2" smd rect (at 1 0)))')
    assert n.get('layer') == 'F.Cu'
    assert len(n.find_all('pad')) == 2 and len(list(n.walk('at'))) == 3
    n.set('at', 5, 6, 90)
    assert dumps(n.find('at')) == '(at 5 6 90)\n'
    assert n.remove_all('pad') == 2 and n.find('pad') is None
    c = n.deepcopy()
    c.find('layer')[1] = 'B.Cu'
    assert n.get('layer') == 'F.Cu'


def test_long_atom_runs_wrap_like_kicad():
    # (layers ...) with many names wraps after column 72 (KiCad's rule); the wrapped form must round-trip
    n = Node('zone', Node('layers', *['In%d.Cu' % i for i in range(1, 31)]))
    text = dumps(n)
    assert max(len(line.expandtabs(1)) for line in text.splitlines()) < 90
    assert dumps(loads(text)) == text


def _roundtrip(path):
    t = open(path, encoding='utf-8').read()
    o = dumps(loads(t))
    return o == t, TOK.findall(o) == TOK.findall(t)


def test_installed_symbol_libraries_round_trip():
    """A third of KiCad's symbol libraries: byte-identical where KiCad wrote the file, token-identical always."""
    files = sorted(glob.glob(os.path.join(symbols_dir(), '*.kicad_sym')))[::3]
    assert files
    byte = 0
    for f in files:
        same, tok = _roundtrip(f)
        assert tok, f
        byte += same
    assert byte > len(files) // 2


def test_installed_footprints_round_trip():
    files = sorted(glob.glob(os.path.join(footprints_dir(), '*.pretty', '*.kicad_mod')))[::25]
    assert files
    for f in files:
        assert _roundtrip(f)[1], f


def test_kicad_saved_files_are_byte_identical():
    """Have KiCad itself save a footprint library and a symbol library, then check the round trip is exact."""
    d = tmpdir('saved')
    lib = os.path.join(d, 'x.pretty')
    os.makedirs(lib)
    for name in ('Package_DFN_QFN.pretty/QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm', 'Package_TO_SOT_SMD.pretty/SOT-23-6',
                 'Connector_USB.pretty/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal'):
        shutil.copy(os.path.join(footprints_dir(), name + '.kicad_mod'), lib)
    r = cli('fp', 'upgrade', '--force', lib, '-o', os.path.join(d, 'out.pretty'))
    out = sorted(glob.glob(os.path.join(d, 'out.pretty', '*.kicad_mod')))
    assert len(out) == 3, r.stdout + r.stderr
    for f in out:
        assert _roundtrip(f)[0], f
    sym = os.path.join(d, 'power.kicad_sym')
    shutil.copy(os.path.join(symbols_dir(), 'power.kicad_sym'), sym)
    cli('sym', 'upgrade', '--force', sym)
    assert _roundtrip(sym)[0]


def test_extra_corpus():
    """Optional: KICAD_SEXPR_CORPUS='/path/**/*.kicad_pcb:/path/**/*.kicad_sch' round-trips real projects."""
    files = [f for f in corpus() if f.endswith(('.kicad_pcb', '.kicad_sch', '.kicad_sym', '.kicad_mod', '.kicad_wks',
                                                 'fp-lib-table', 'sym-lib-table'))]
    if not files:
        raise Skip('KICAD_SEXPR_CORPUS not set')
    for f in files:
        assert _roundtrip(f)[1], f
