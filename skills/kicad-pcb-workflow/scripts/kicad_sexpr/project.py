"""Project files (.kicad_pro, JSON): net classes, net class assignments and board design rules.

KiCad writes .kicad_pro as JSON with sorted keys, two-space indent and a final newline; ``save()`` does the same, so
a project KiCad saved is rewritten byte for byte when nothing changed (checked on KiCad 10 projects).
"""
from __future__ import annotations

import copy
import json
import os
from typing import Dict, List, Optional, Union

__all__ = ['Project', 'NETCLASS_DEFAULTS']

Json = Union[None, bool, int, float, str, List['Json'], Dict[str, 'Json']]

# Keys of a net class entry as KiCad 10.0.1 writes them (values from a KiCad-saved project's "Default" class).
NETCLASS_DEFAULTS: Dict[str, Json] = {
    'bus_width': 12, 'clearance': 0.2, 'diff_pair_gap': 0.25, 'diff_pair_via_gap': 0.25, 'diff_pair_width': 0.2,
    'line_style': 0, 'microvia_diameter': 0.3, 'microvia_drill': 0.1, 'pcb_color': 'rgba(0, 0, 0, 0.000)',
    'priority': 2147483647, 'schematic_color': 'rgba(0, 0, 0, 0.000)', 'track_width': 0.2, 'tuning_profile': '',
    'via_diameter': 0.6, 'via_drill': 0.3, 'wire_width': 6,
}


class Project:
    def __init__(self, data: Dict[str, Json], path: Optional[str] = None) -> None:
        self.data = data
        self.path = path

    @classmethod
    def load(cls, path: str) -> 'Project':
        with open(path, encoding='utf-8') as f:
            return cls(json.load(f), path)

    @classmethod
    def new(cls, filename: str) -> 'Project':
        """A minimal project (KiCad fills in every other setting with its defaults when it opens it)."""
        d: Dict[str, Json] = {
            'meta': {'filename': os.path.basename(filename), 'version': 3},
            'net_settings': {'classes': [dict(NETCLASS_DEFAULTS, name='Default')], 'meta': {'version': 5},
                             'net_colors': None, 'netclass_assignments': None, 'netclass_patterns': []},
            'board': {'design_settings': {'rules': {}}},
        }
        return cls(d, filename)

    def save(self, path: Optional[str] = None) -> None:
        target = path or self.path
        if not target:
            raise ValueError('no path given')
        with open(target, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(self.data, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
        self.path = target

    # ---------------------------------------------------------------- net classes
    def _ns(self) -> Dict[str, Json]:
        ns = self.data.setdefault('net_settings', {})
        assert isinstance(ns, dict)
        ns.setdefault('classes', [])
        ns.setdefault('meta', {'version': 5})
        return ns

    def netclasses(self) -> List[Dict[str, Json]]:
        classes = self._ns()['classes']
        assert isinstance(classes, list)
        return classes  # type: ignore[return-value]

    def netclass(self, name: str, **values: Json) -> Dict[str, Json]:
        """Create or update a net class. New classes start from the Default class's values (or KiCad's defaults);
        a class other than Default gets priority 0 unless given."""
        classes = self.netclasses()
        for c in classes:
            if c.get('name') == name:
                c.update(values)
                return c
        base = next((c for c in classes if c.get('name') == 'Default'), NETCLASS_DEFAULTS)
        c = copy.deepcopy(dict(base))
        c['name'] = name
        if name != 'Default':
            c['priority'] = 0
        c.update(values)
        classes.append(c)
        return c

    def assign(self, net: str, netclass: str, replace: bool = False) -> None:
        """Put one net in a class (``netclass_assignments``; net names as in the schematic netlist).

        KiCad 10 stores each net's classes as a list (``"VBUS": ["Power"]``) and rewrites the older single-string
        form to a list whenever it saves the project, so this writes a list. A net may carry several classes:
        assigning another class appends it (no duplicates); ``replace=True`` makes this the net's only class. The
        string form in a loaded file is read as one entry."""
        ns = self._ns()
        a = ns.get('netclass_assignments')
        if not isinstance(a, dict):
            a = {}
            ns['netclass_assignments'] = a
        cur = [] if replace else self.assignments().get(net, [])
        if netclass not in cur:
            cur.append(netclass)
        a[net] = list(cur)

    def assignments(self) -> Dict[str, List[str]]:
        """{net: [class, ...]} from ``netclass_assignments``, whether the file stores lists (KiCad 10) or strings."""
        a = self._ns().get('netclass_assignments')
        out: Dict[str, List[str]] = {}
        if isinstance(a, dict):
            for net, v in a.items():
                if isinstance(v, str):
                    out[net] = [v]
                elif isinstance(v, list):
                    out[net] = [str(c) for c in v]
        return out

    def clear_assignments(self, patterns: bool = True) -> None:
        """Drop every per-net assignment (and, by default, every pattern) before re-assigning from scratch."""
        ns = self._ns()
        ns['netclass_assignments'] = {}
        if patterns:
            ns['netclass_patterns'] = []

    def add_pattern(self, pattern: str, netclass: str) -> None:
        """Assign every net matching a wildcard pattern (``netclass_patterns``)."""
        ns = self._ns()
        p = ns.get('netclass_patterns')
        if not isinstance(p, list):
            p = []
            ns['netclass_patterns'] = p
        entry: Dict[str, Json] = {'netclass': netclass, 'pattern': pattern}
        if entry not in p:
            p.append(entry)

    # ---------------------------------------------------------------- board design settings
    def design_settings(self) -> Dict[str, Json]:
        b = self.data.setdefault('board', {})
        assert isinstance(b, dict)
        ds = b.setdefault('design_settings', {})
        assert isinstance(ds, dict)
        return ds

    def set_rules(self, **rules: Json) -> None:
        """board.design_settings.rules (min_clearance, min_track_width, min_via_diameter, min_hole_to_hole, ...)."""
        r = self.design_settings().setdefault('rules', {})
        assert isinstance(r, dict)
        r.update(rules)

    def set_track_widths(self, widths: List[float]) -> None:
        """Pre-defined track widths; KiCad keeps a leading 0.0 entry (= use the net class)."""
        tw: List[Json] = [0.0]
        tw += [w for w in widths if w]
        self.design_settings()['track_widths'] = tw

    def set_via_sizes(self, sizes: List[List[float]]) -> None:
        """Pre-defined vias as [diameter, drill]; KiCad keeps a leading zero entry."""
        vd: List[Json] = [{'diameter': 0.0, 'drill': 0.0}]
        vd += [{'diameter': d, 'drill': h} for d, h in sizes]
        self.design_settings()['via_dimensions'] = vd
