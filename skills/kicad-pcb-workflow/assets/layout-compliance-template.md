# Layout compliance: each block checked against its reference

Each block is checked against `docs/layout-refs/<part>/` (datasheet layout section and figure first, vendor/EVM layout
second) in a net-coloured render before the next block is started. DRC is not enough: it checks manufacturing rules,
not the datasheet's.

## <Part / block> (<datasheet doc number> s<n>, fig. <n>)

| # | Rule (from the reference) | Status | Evidence (where, what, render) |
|---|---|---|---|
| 1 | | ok / fixed / deviation | |

Deviation rows (a rule not met) must also say:
- **Tried:** package sizes, values, positions, layers attempted, and the cheaper alternatives (smaller package, other
  value, other position) tried first;
- **Blocked by:** the part, clearance or rule that stopped each attempt;
- **Consequence and decision:** what the deviation costs, and who accepted it (the user, with date).
