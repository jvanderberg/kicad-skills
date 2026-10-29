"""Duplicate footprint references: Board.validate() (which save() runs) and `sexp.py check` follow KiCad's own rule.
    python3 tests/test_duplicate_refs.py
KiCad's DRC never counts board-only footprints (logos, graphics) as duplicates; placeholder references (REF**, G***)
are left to DRC. Two G*** logos on one board used to make save() refuse the board and `sexp.py check` fail it."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from kicad_sexpr import Board, new_footprint, save

CASES = [   # (references and attributes on one board, duplicate reported)
    ([('G***', ()), ('G***', ())], None),
    ([('REF**', ()), ('REF**', ())], None),
    ([('LOGO1', ('board_only',)), ('LOGO1', ('board_only', 'exclude_from_bom'))], None),
    ([('LOGO1', ('board_only',)), ('LOGO1', ())], None),                    # one counted: not a duplicate
    ([('X1', ('exclude_from_pos_files', 'exclude_from_bom')), ('X1', ('exclude_from_bom',))], 'X1'),
    ([('R1', ()), ('R1', ())], 'R1'),
]


def _board(fps):
    b = Board.new(copper_layers=2)
    for i, (ref, attr) in enumerate(fps):
        b.add_footprint(new_footprint('P', attr=('smd',) + attr), 'L:P', ref, 'x', (10 + 5 * i, 10))
    return b


def test_validate_and_sexp_check_agree_with_kicad():
    d = tempfile.mkdtemp()
    for i, (fps, dup) in enumerate(CASES):
        b = _board(fps)
        v = [p for p in b.validate() if 'duplicate footprint references' in p]
        assert v == (["duplicate footprint references: ['%s']" % dup] if dup else []), (fps, v)
        p = os.path.join(d, 'b%d.kicad_pcb' % i)
        if dup:
            save(b.tree, p)
        else:
            b.save(p)                                   # refused before: "duplicate footprint references: ['G***']"
        r = subprocess.run([sys.executable, os.path.join(HERE, 'sexp.py'), 'check', p], capture_output=True, text=True)
        assert r.returncode == (1 if dup else 0), (fps, r.stdout)
        assert ("['%s']" % dup in r.stdout) if dup else 'duplicate' not in r.stdout, (fps, r.stdout)


if __name__ == '__main__':
    test_validate_and_sexp_check_agree_with_kicad(); print('PASS')
