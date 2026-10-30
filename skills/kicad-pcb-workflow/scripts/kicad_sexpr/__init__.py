"""kicad_sexpr: the one place that owns the KiCad 10 file formats.

Read, modify and write .kicad_sch / .kicad_pcb / .kicad_sym / .kicad_mod (and .kicad_pro, library tables) without
formatting text by hand. A generic lossless tree (``sexp``) keeps every token of a file; typed builders (``schematic``,
``board``, ``symbol_lib``, ``project``, ``lib_table``) create the common items with KiCad 10's syntax, fresh unique
uuids and escaped strings.
See README.md next to this file. Pure Python 3.9+, no dependencies.
"""
from .sexp import Node, Sym, SexpError, dumps, load, loads, num, save
from .common import (FOOTPRINT_VERSION, KICAD_VERSION, PCB_VERSION, SCH_VERSION, SYMBOL_LIB_VERSION, IdMap, Uuids,
                     board_net_name, duplicate_uuids, rotate)
from .symbol_lib import Pin, SymbolLibrary, lib_pin, lib_polyline, lib_property, lib_rectangle, lib_symbol, pins_of
from .schematic import SchSymbol, Schematic, sch_ids, sch_item_key, symbol_point
from .board import (Board, Footprint, StackupLayer, board_ids, board_item_key, copper_layer_names, flip_footprint_data,
                    fp_item_key, fp_line, fp_rect, new_footprint, stackup)
from .project import Project
from .lib_table import (LIB_TABLE_VERSION, TABLE_FILES, LibRow, LibTable, expand_uri, find_project_dir, global_table,
                        kicad_env, resolve_libraries)

__all__ = ['Node', 'Sym', 'SexpError', 'dumps', 'load', 'loads', 'num', 'save',
           'FOOTPRINT_VERSION', 'KICAD_VERSION', 'PCB_VERSION', 'SCH_VERSION', 'SYMBOL_LIB_VERSION', 'IdMap', 'Uuids',
           'board_net_name', 'duplicate_uuids', 'rotate',
           'Pin', 'SymbolLibrary', 'lib_pin', 'lib_polyline', 'lib_property', 'lib_rectangle', 'lib_symbol', 'pins_of',
           'SchSymbol', 'Schematic', 'sch_ids', 'sch_item_key', 'symbol_point',
           'Board', 'Footprint', 'StackupLayer', 'board_ids', 'board_item_key', 'copper_layer_names',
           'flip_footprint_data', 'fp_item_key', 'fp_line', 'fp_rect',
           'new_footprint',
           'stackup', 'Project',
           'LIB_TABLE_VERSION', 'TABLE_FILES', 'LibRow', 'LibTable', 'expand_uri', 'find_project_dir', 'global_table',
           'kicad_env', 'resolve_libraries']
