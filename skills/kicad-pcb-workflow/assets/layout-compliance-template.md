# Layout compliance: each block checked against its reference

Each block is checked against `docs/layout-refs/<part>/` (datasheet layout section and figure first, vendor/EVM layout
second) in a net-coloured render before the next block is started. DRC is not enough: it checks manufacturing rules,
not the datasheet's.

## <Part / block> (<datasheet doc number> s<n>, fig. <n>)

| # | Rule (from the reference) | Status | Satisfied by (refdes, value, distance) | Evidence (where, what, render) |
|---|---|---|---|---|
| 1 | | ok / fixed / deviation | | |

Each row names the specific part, pin or copper that satisfies it ("C38 1 uF, 0.5 mm from pin 14"), not "C_OUT at
the VOUT pins": a capacitor of the same kind nearby is not the one the datasheet draws. Paste `refparts.py`'s table
for the block (every part of the datasheet's typical application, with the part that satisfies it) above the rules.
Electrical rules get an electrical number where a tool gives one: a hot loop's ground return from `emc.py` (path
resistance, share through one via), not only its pad-to-pad distance.

Deviation rows (a rule not met) must also say:
- **Tried:** package sizes, values, positions, layers attempted, and the cheaper alternatives (smaller package, other
  value, other position) tried first;
- **Blocked by:** the part, clearance or rule that stopped each attempt;
- **Consequence and decision:** what the deviation costs, and who accepted it (the user, with date).
