# KiCad PCB skills for Claude Code

Skills and command-line tools for developing, reviewing and sourcing KiCad (9/10) printed circuit boards with Claude
Code, aimed at hobby and small-batch boards made at JLCPCB/LCSC. They cover the path from an idea to an order: planning
the board, making scripted edits that are verified with KiCad's own tools, reviewing the design with measured evidence,
designing power supplies, and choosing and sourcing parts.

| Skill | Use it for |
|---|---|
| [`kicad-new-board`](skills/kicad-new-board/SKILL.md) | Starting a new hobby board: a short interview from purpose to parts (environment, blocks and interfaces, power budget, physical limits, JLCPCB manufacturing, 2 vs 4 layer stackup) that produces a requirements/architecture document the other skills build on |
| [`kicad-pcb-workflow`](skills/kicad-pcb-workflow/SKILL.md) | Making changes safely: scripted edits to `.kicad_sch` / `.kicad_pcb` in a scratch copy, verification with KiCad's own DRC/ERC/parity, rendering and looking, diffing against the last commit, copying back |
| [`kicad-board-review`](skills/kicad-board-review/SKILL.md) | Engineering review: power and protection, copper capacity and heat, ground and return paths, regulators, SI/EMC, ESD, datasheet compliance, sourcing, mechanical - backed by a measured analysis pack and an adversarial reviewer |
| [`pcb-power-supply`](skills/pcb-power-supply/SKILL.md) | Designing a rail: LDO vs buck/boost/buck-boost, choosing the IC (optionally with TI WEBENCH in the browser), sizing the inductor, capacitors and dividers, input protection, layout and verification |
| [`pcb-battery-power`](skills/pcb-battery-power/SKILL.md) | Battery-powered boards: choosing the chemistry and cell, charger ICs and USB-C charging, NTC/JEITA, cell protection, power path, regulation from a cell, fuel gauges, sleep-current and battery-life estimates, layout, safety, shipping and bench tests |
| [`pcb-part-selection`](skills/pcb-part-selection/SKILL.md) | Choosing parts, reading datasheets, deriving values, importing from LCSC, and sweeping the BOM for stock before an order |

## Install

As a Claude Code plugin:

```
/plugin marketplace add jvanderberg/kicad-skills
/plugin install kicad-skills@kicad-skills
```

Or copy any folder under `skills/` into `~/.claude/skills/` (each skill is self-contained).

## Tools

All tools also work without Claude.

| Tool | What it does |
|---|---|
| `kicad-pcb-workflow/scripts/check.sh` | DRC (zone refill x2, schematic parity) + ERC on a copy of the project, summarised and diffed against a baseline |
| `kicad-pcb-workflow/scripts/board_diff.py` | Everything that changed between two board versions (or vs a git revision), with anything outside the expected areas flagged |
| `kicad-pcb-workflow/scripts/kicad_sexpr/` | The file-format layer: lossless read/write of every KiCad s-expression file in KiCad's own formatting, plus builders for schematics (symbols, wires, labels, sheets), boards (footprints, tracks, vias, zones, keepouts, stackup) and project net classes. Generators and edits use it instead of formatting text |
| `kicad-pcb-workflow/scripts/sexp.py` | Check s-expression files (balance, raw newlines in strings, duplicate uuids); list/get footprints and symbols; editing helpers |
| `kicad-pcb-workflow/scripts/render.py` | Render a window of chosen layers by KiCad coordinates to PNG (or a 3D render) |
| `kicad-pcb-workflow/scripts/kicad_open.sh` | Is KiCad holding the project open? |
| `kicad-board-review/scripts/make_pack.sh` | Build the analysis pack: netlist digest, board overview, DC power runs, planes, EMC, DRC |
| `kicad-board-review/scripts/power.py` | Resistive-grid DC solver: drop per load, copper loss, current density hotspots, current per via |
| `kicad-board-review/scripts/planes.py`, `emc.py` | Ground plane pieces/slots/stitching; reference continuity, crosstalk, layer changes, hot loops, Z0 |
| `kicad-board-review/scripts/region.py`, `view.py` | List or render the copper inside a box |
| `pcb-part-selection/scripts/bom_check.py` | Stock, package size and assembly-class sweep of the whole BOM via JLCImport |

## Requirements

- KiCad 9 or 10 (`kicad-cli`, and KiCad's bundled python with `pcbnew` for `boarddump.py`). Paths are auto-detected on
  macOS, Linux and Windows; override with `KICAD_CLI` and `KICAD_PYTHON`.
- Python 3 with numpy, scipy, shapely >= 2 and matplotlib for the analysis scripts. `kicad_env.sh` creates a venv in
  `~/.cache/kicad-skills/venv` on first use (override with `PY`).
- `rsvg-convert` (librsvg) for `render.py`.
- [JLCImport](https://github.com/jvanderberg/kicad_jlcimport) (`jlcimport-cli`) for part search, import and stock checks.

## Limits

The analysis is DC and geometric: no field solving, no thermal model, components are not in the copper model. The
skills say so in their reports, and they keep design checks separate from hardware qualification.

## License

MIT - see [LICENSE](LICENSE).
