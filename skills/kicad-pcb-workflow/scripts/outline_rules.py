"""What counts as a footprint's silkscreen outline, shared by strip_outline.py (library files, kicad_sexpr nodes) and
board_lint.py (boards, pcbnew shapes). Plain python 3, no dependencies; both import it from this folder.

- MARK: a silk circle, or a filled silk shape, smaller than this (mm) both ways, stroke included, is a mark (a pin-1
  dot), not part of the outline.
- REMOVED: the hidden footprint property strip_outline.py writes into every copy it makes. It travels with the
  footprint onto the board (new_board.py and KiCad's update keep library properties), so board_lint.py knows the
  outline was removed even when a cathode bar or diode symbol was kept.
"""

MARK = 1.0
REMOVED = ('Silk outline', 'removed by strip_outline.py')     # (property name, value)


def is_mark(kind, filled, width, height):
    """a pin-1 dot or similar: kind 'circle' (any other kind is not a circle) or a filled shape, whose extent (mm,
    stroke included) is under MARK both ways"""
    return (kind == 'circle' or bool(filled)) and width < MARK and height < MARK
