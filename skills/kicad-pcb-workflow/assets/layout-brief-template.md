# Layout brief: <stage / block name>

Written <date> for stage <n> of `docs/layout-plan.md`. Read this, then the files it names, before touching the board.

## Scope

- Parts: <refs>
- Nets: <net names, from the netspec file>
- Board area allocated: <x0, y0 - x1, y1 mm>, layers <list>

## References (primary first)

1. Datasheet <doc number>, section <n> "Layout Guidelines" (p<n>), Figure <n> "Layout Example" (p<n>):
   `docs/layout-refs/<part>/datasheet-p<n>.png`
2. EVM / vendor reference layout: <file, figure> (secondary: drawn around its own BOM and stackup)

Rules from the references (numbered; each becomes a row in `docs/layout-compliance.md`):

1.
2.

## Board-wide rules that apply

- Stackup / layer use: <from layout-plan.md>
- Net classes and widths: <class: track, clearance>
- Keepouts and reserved sites in this area: <single-point ground tie, thermal vias, analog island>

## Interfaces

- Connects to: <neighbour copper / pour / via, where>
- Must not cross or cut: <planes, lanes reserved for other blocks>

## Frozen decisions to re-check

- <schematic choices this stage could find infeasible (pin use, features), and what to do if so: ask the user>

## Done criteria

- [ ] Block nets connected, DRC clean for the block (check.sh, nothing new outside named accepted items)
- [ ] Net-coloured render (`view.py`) next to the reference figure at the same scale; differences explained
- [ ] Every rule above ticked in `docs/layout-compliance.md`, or a deviation with evidence of what was tried
- [ ] Anything that changed an earlier decision reported to the user
