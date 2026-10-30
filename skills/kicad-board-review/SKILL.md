---
name: kicad-board-review
description: Engineering design review of a KiCad PCB - power distribution and copper capacity, ground planes and return paths, heat, signal integrity and EMC (crosstalk, reference planes, radiation), protection (fusing, reverse polarity, surge, ESD), datasheet compliance, sourcing and manufacturability - backed by a measured analysis pack (netlist digest, DC voltage-drop solver, plane and EMC geometry) and an adversarial reviewer. Use it whenever the user asks to review, audit, sanity-check or "find problems in" a board, asks whether a design will work, asks about voltage drop, current capacity, vias, ground planes, crosstalk, emissions, ESD, fusing or heat, before ordering boards, and after any significant rework to prove it did not regress.
---

# KiCad board review

A review is worth what it finds before the boards are made. Two things make it find real problems: **evidence** (measure
the copper instead of eyeballing it, read the datasheet instead of remembering it) and **adversarial intent** (assume
the design - including your own recent work - is wrong somewhere, and go looking). A board that passes DRC can still
have blockers and major issues, and the most recent rework is where regressions hide. DRC checks rules; it does not
check engineering.

Read `references/review-checklist.md` for what to look at in each area and why it matters. It is the core of this
skill. `references/interpreting-results.md` explains what the numbers from the analysis mean (and how to explain them
to the user); `references/reviewer-brief.md` is the brief for the adversarial reviewer agent; `references/analysis-limits.md`
lists what the scripts cannot see.

## 1. Understand the board before judging it

- Read the project docs (README, design notes, CLAUDE.md), the intended use (input voltage range, load currents,
  environment, enclosure temperature, cable lengths, who plugs what in), and decisions the user already made.
- Build the analysis pack (section 2) and read `netlist.md` end to end: every IC's pin-to-net map, every two-pin part.
  Many findings come straight from it (a missing series resistor, a pin tied wrong, a protection part on the wrong side
  of a resistor, an address strap, an undriven chip select).
- Know the stackup the fab will actually build. A file saying 35 um inner copper often ships as 0.5 oz (17.5 um); if it
  is not confirmed, analyse both and say so.

## 2. Build the analysis pack

```
${CLAUDE_SKILL_DIR}/scripts/preflight.py --for review                    # every tool the pack needs, before minutes of work
${CLAUDE_SKILL_DIR}/scripts/make_pack.sh <project_dir> <pack_dir>        # uses the project's review_config.json, or writes
                                                                         # a STARTER derived from this board's netlist
# edit <pack_dir>/review_config.json: bus classes (regex -> usb/spi/clock/i2c/analog/...), power runs, diff pairs;
# check the derived switch nodes and hot loops; delete "starter"; keep it in the project (docs/) for the next review
${CLAUDE_SKILL_DIR}/scripts/make_pack.sh <project_dir> <pack_dir> --inner-um 17.5,35    # run in the background: minutes
```

It copies the project (never touches the original), refills zones with KiCad (and says so if DRC failed and the fills
are stale), and writes:
`netlist.md` (readable netlist), `board_overview.md` (stackup, copper per layer, vias, widths, parts),
`power.md` (DC drop, copper loss, current density hotspots, busiest via per power path; ground plane pieces, slots and
what cuts them; tracks on inner layers), `emc.md` (fast nets off their reference plane, crosstalk, layer changes and
return vias, edge proximity, switching nodes, hot loops, microstrip Z0, diff pair skew), `thermal.md` (heat-source table
per corner, board and part temperatures at a low / nominal / high film coefficient next to the board-average check,
junction estimates, thermal vias per exposed pad, the pour under each hot part, ground stitching and a stitching
what-if), `drc.md`, plus JSON for all of it. `emc.md` also holds the same-net isolation of every declared island
(`islands.py`), the nearest decoupling capacitor of every IC supply pin by copper path with an inductance estimate
(`decoupling.py`), and each declared differential pair's impedance estimate with the measured gap to the nearest
same-layer copper. `netlist.md` ends with pin audits, among them the control lines between ICs that have no pull
resistor (a reset-state decision per line).

Declare in the config what only the design intent knows: `"islands"` (each single-point or quiet ground and each
pour that must meet its net only at named points: net, layer, its pads, allowed joins - format in `islands.py`; with
none, same-net isolation is NOT CHECKED), `"diff_pairs"` with `target_ohm`, `"decoupling"` limits, and
`thermal.h_W_m2K` from the enclosure - `"enclosed"` (5 / 7 / 10 W/m^2K per face, the default) or `"bare"` (9 / 12 / 16,
a bare board in still room air). Ask if the requirements do not say: on a bare USB-UART board the closed-box default
read a 76 C board average and a part over 85 C, against 56-68 C and nothing over a limit with the bare-board range.
Every pattern and named object in the config must match something: one that matches nothing is a warning in the
coverage, and a net that reaches a connector and falls through to "slow" is listed by name. The scripts run under the analysis venv and
`boarddump.py` under KiCad's python; each re-runs itself under the right one (`interp.py`).

Give the config a `"thermal"` section (format in `scripts/heat.py`; example in `assets/review_config.example.json`): the
ambient around the board, the corners that bound the heat (worst discharge at the lowest source voltage, typical,
charging while running), and a loss per candidate heat source - currents from `pcb-power-supply/scripts/path_budget.py
--json`, R_DS(on) hot, efficiencies from the vendor tool, the datasheet's psi_JB / theta_JC per IC. Without it the pack
still lists every candidate as UNKNOWN and reports heat as NOT CHECKED. The path's copper comes from the pack's power
runs, so solve it after the first build (`path_budget.py SPEC --json <pack_dir>/path_out.json`; relative paths resolve in
the pack, then next to the project's config) and re-run only `scripts/thermal.py <pack_dir>` (seconds).

Write power runs for every path that carries real current: each input connector -> fuse -> protection -> rail -> loads,
the ground return of all of them at once, regulator outputs to their loads, long thin rails. Use realistic currents
(the connector or fuse rating for power paths, datasheet peaks for radios). One-off questions get the ad hoc mode:
`scripts/power.py <pack> --net +12V --source F1:2 --sink J2:1=2.5 ...` prints the drop per sink and the busiest vias.
`scripts/region.py` and `scripts/view.py` show exactly what copper is where.

**Roles come from the design's structure; names only override (R17).** `topology.py` derives from the netlist what
name patterns guess at: ground nets (by IC ground pins), switch nodes (a net where an inductor meets an IC switch pin,
or an active part with no capacitor to ground - whatever KiCad named it, `Net-(C4-Pad2)` or `U6-L1`), switching ICs,
the inductor's DC side, and hot-loop candidates (each switching IC's power pins that have a capacitor to ground,
except the DC side). The analysis uses them whenever the config does not say otherwise, and says when a config rule
reclasses a derived switch node. Classify the rest (buses, feedback, sense, CC lines) in the config: nets that fall
through to "slow" are not checked for reference continuity, so a long I2C bus under a noisy pour goes unreported;
`emc.md` lists them longest first.

**Read the coverage first (R16).** `power.md`, `emc.md` and `thermal.md` start with "Coverage and warnings": configured items that
matched nothing, defaults used, derived roles, hot loops not checked, ground nets with no copper. "0 found" under a
warning is not a pass.

## 3. Review, area by area

Go through every section of `references/review-checklist.md`: power path and protection, copper capacity and heat,
ground and return paths, decoupling and regulator layout, signal integrity and EMC, ESD and external interfaces,
component and datasheet compliance, sourcing and assembly, mechanical and silkscreen, firmware-visible consequences.
**Every area produces a recorded output (R23).** The checklist marks each area's output (the heat-source table and the
temperatures for heat, the solved operating point for a power path, the edge-stitch gaps and weak pieces for stitching).
An area without its output in the review is reported as NOT CHECKED, not as fine: a review that skipped heat because the
checklist only said "list the heat sources" reported nothing about a battery path dissipating more than the converters.
For each finding record: **what** (with refdes, net, coordinates), **evidence** (the number from the pack, the
datasheet section and page, the netlist line), **consequence** (what fails, when, how badly), **fix** (concrete, and
what it costs in board space and risk).

Rank: **Blocker** (board will not work or cannot be built/ordered), **Major** (works on the bench, fails in the field,
in production, in compliance testing, or at rated load), **Minor** (margin, cleanliness, cost). Do not inflate; do not
soften. Mark anything unverified as unverified.

**Numbers come from the model that fits the real geometry, measured now (R29).** Every number in a finding, a fix or a
design doc is measured from the files as they are at the time of writing, with a model that includes what surrounds
the item: a track's loop inductance from its microstrip per-length value over its own plane (about 0.2-0.4 nH/mm on an
outer layer over a close plane; the free-wire ~1 nH/mm overstates it several times), a pair's impedance with the pour
beside it, a temperature from the solve rather than a via-count rule of thumb. A limit is read from the datasheet of
the part, not from a general rule. A fix is quantified before and after before it is applied (a relocation that moves
the number little is not worth its rework). Where a calculator owned by someone else is the authority (the fab's
impedance calculator for its stackup), run it - browser automation can - and record its numbers. This applies to the
adversarial reviewer's numbers as much as to yours: check each against the model before acting on it.

**Findings are ranked, and reported as the shape found (R18).** A list where every item looks alike hides the one that
matters: the pack sorts reference spans into high (over nothing), medium (over another net's plane, with the nearest
decoupling capacitor) and low (ground pour on both sides, ground edge), and you report in that order. Report the
shape the tool measured, not an aggregate: another net's pour inside a ground hole is a pour, each remaining slot has
its own size, and a branching track corridor is its length and width, not the bounding box of the merged hole
(minipc-power's B.Cu BAT pour plus nearby tracks once read as a "44.4 x 31.9 mm slot").

## 4. Adversarial pass

Spawn a separate reviewer (fork or general-purpose agent) with `references/reviewer-brief.md`, pointing it at the pack,
the project and the datasheets. Its job is to break the design and to challenge the pack itself (the scripts have
artefacts). Merge its findings with yours, de-duplicate, and verify each one against the files before reporting -
reviewers also make mistakes (a short crossing reported as a high crosstalk figure is a typical one).

## 5. Fix, then prove the fix

Fixes go through the **kicad-pcb-workflow** skill. Batch the fixes from the review, verify each with a quick check
aimed at what it changed (DRC, `pour_check.py` for a zone edit, `islands.py` or `decoupling.py` on a rebuilt pack, a
render; kicad-pcb-workflow R30), then rebuild the full pack once on the new board and compare against the pack from
before the fix: the targeted numbers must improve and nothing else may get worse (drops, copper loss,
hotspots, plane slots, inner-layer tracks, reference spans, crosstalk). Report the before/after table. Fixes that were
not done get an explicit reason (no room, part unavailable, user decision) and a mitigation (firmware limit, docs).

## 6. Report

Lead with blockers and majors, each with evidence and a recommended fix; then minors; then what was checked and found
fine (so the user knows the coverage), with each area's output (the heat table and the temperature range belong here
even when nothing is over a limit); then the areas NOT CHECKED and why; then limits of the analysis. Write the result into the project's docs if it
keeps a design log. When the user asks follow-up questions ("is this the voltage drop?", "what are the ground plane's
limits?", "enough vias?"), answer from measured numbers, explain the physics plainly, and run the ad hoc solver rather
than estimating - see `references/interpreting-results.md` for how to answer them.
