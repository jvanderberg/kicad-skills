---
name: kicad-pcb-workflow
description: How to safely create or change a KiCad (9/10) project from Claude Code - generating a new schematic and board from scratch, adding or swapping parts, editing schematics, placing footprints, routing tracks and vias (in staged, datasheet-checked blocks), editing zones and silk, setting up stackups and design rules, converting KiCad versions, and fixing DRC/ERC/parity errors - by scripted edits to the .kicad_sch/.kicad_pcb files with a verify-and-look loop. Use this whenever the user asks to create, draw, lay out, modify, route, place, fix, upgrade or clean up anything in a KiCad project, even a "small" tweak, and whenever you are about to write or edit a .kicad_sch, .kicad_pcb, .kicad_pro, .kicad_sym or .kicad_mod file.
---

# KiCad PCB workflow

You are editing a board that someone will pay to manufacture. The files are plain-text s-expressions, which makes
scripted edits possible, but KiCad gives almost no feedback when an edit is subtly wrong: a bad string silently drops
half a schematic sheet, a moved pad silently renames a track's net, a new track silently cuts a ground plane. So the
work is a loop: **checkpoint -> edit in a scratch copy with a script -> verify with KiCad's own tools -> look at a
render -> copy back -> report.** Skipping any step below lets a silent failure through.

Scripts are in `${CLAUDE_SKILL_DIR}/scripts/`. Detailed references (read the one you need, when you need it):
- `references/new-design.md` - a new project from nothing: intended netlist, readable generated schematic, board from
  the netlist, stackup and rules (kicad-cli can do none of this)
- `references/layout-stages.md` - layout as staged sessions with written briefs, resource allocation, feasibility
  back-checks, the datasheet compliance file
- `references/checks.md` - what each check proves and what it does not (cover the blind spots)
- `references/file-format.md` - s-expression anatomy, insertion anchors, nets, vias, zones, schematic symbols, the gotchas
- `references/pcbnew-api.md` - what pcbnew's python can and cannot be trusted with (KiCad 10.0.x)
- `references/layout-rules.md` - layer discipline, planes and return paths, power copper, vias, sense lines, silk,
  external connections
- `references/routing.md` - routing from a script with `router.py` (no autorouter): lanes, coordinates as data, checks
- `references/rendering.md` - getting images you can actually inspect
- `references/version-upgrade.md` - KiCad 9 -> 10 conversion

**One place owns each file format and each fiddly rule.** Generate KiCad text only through the scripts' writers
(`schgen`/`symgen` for schematics and symbols, `new_board.py` and `board_setup.py` for boards and projects, `router.py`
for copper, `sexp.kstr()` for any string); they own the syntax, escaping, uuids, `{slash}` net names and hole spacing.
A project generator describes the design; if it needs a feature the writers lack, add it there, not as a format string
in the project.

## 0. Before touching anything

1. **Is KiCad open?** Run `${CLAUDE_SKILL_DIR}/scripts/kicad_open.sh <project_dir>`. KiCad keeps its own copy in memory;
   if it is open, the user's next save overwrites your edit, or yours overwrites their unsaved work. If it is open, ask
   the user to save and close it, wait for them to say so, then re-read the files: they may have changed things.
   **Looking is not editing:** when the user only wants to see the board ("open it for me"), copy the project to a
   scratch folder and open the copy (`open -a KiCad <copy>/proj.kicad_pro` on macOS), or tell them plainly that the
   board will be regenerated and any edits they make will be lost - do not refuse to keep working because it is open.
2. **Checkpoint.** Before any non-trivial change, make sure the current state is committed (ask the user if it is not
   yours to commit), so the change is one clean diff they can review or revert.
3. **Read the project's own rules.** CLAUDE.md, README, design docs (often `docs/`), the layer usage you can see on the
   board (which layers carry signals, which are planes), and decisions the user already made. A board usually has a
   discipline - e.g. "no signals on inner layers", "all parts on top" - that is not written down anywhere except in the
   copper. Respect it; if your change seems to need breaking it, ask first.
4. **Baseline the checks** on the unchanged project: `${CLAUDE_SKILL_DIR}/scripts/check.sh <project> <scratch>/base`.
   Existing warnings the user has accepted are part of the baseline; you will diff against it so you can see exactly
   what your change introduced. Everything new is yours to fix - "it was probably already there" is not a reason.

## 1. Plan the change against real data

- **New project, schematic or board from scratch:** follow `references/new-design.md`.
- **Layout of anything with a datasheet layout section** (switching converters, chargers, RF, high-speed): gather the
  reference pack first (`pcb-power-supply` step 6), then lay out in stages from written briefs
  (`references/layout-stages.md`): allocate layers, areas, lanes and reserved via sites before any block consumes them;
  prove at placement that the schematic's decisions can be routed (fine-pitch escapes) and take any that cannot back
  to the user as a decision.

- Get coordinates from the file, not from guessing at a render: `scripts/sexp.py list|get`, or the board-review
  skill's `region.py` (pads, tracks, zones and vias inside a box, per layer) once a `board.json` dump exists.
- For a new part: choose and verify it with the **pcb-part-selection** skill first (stock, package, datasheet). Use the
  datasheet's land pattern and layout example, not just the imported footprint.
- For routing: decide the layer and path, and list what it will cross, pass over, or cut (see layout-rules.md). Look in
  `git log -p` / older revisions for routes that existed before (e.g. escape routing of a part you just removed) - reusing
  them is usually far better than inventing new ones.
- For anything electrical (dividers, limits, protection), compute from the datasheet and write the numbers down.

## 2. Edit in a scratch copy, with a script that rebuilds from a frozen base

- Copy the project (`rsync -a --exclude .git --exclude 'production*' proj/ $SCRATCH/proj/`, or `git archive HEAD`),
  keep an untouched `base/` copy, and record `shasum` of the originals.
- Write the change as a script (python) that **always starts from the base copy** and applies every edit. Iterating =
  editing the script and re-running it, never patching the previous output (that stacks fixes on top of old mistakes).
  Keep the scripts somewhere durable (the user's repo `tools/` or a project scratch dir that will not be cleaned) -
  they are the record of what was done.
- **Text edits for almost everything** (`scripts/sexp.py` has the helpers): pad nets, tracks, vias, zones, fields, silk.
  They are exact, diffable, and do not reformat the file. Use **pcbnew python only to create/load or move footprints**,
  one stage per process, and do all deletions/renets of old copper as text *before* that stage - pcbnew renames track
  nets to match pads on save. Details in `references/pcbnew-api.md`.
- **The base is the last commit, never an older snapshot**, and GUI edits come first: if the user has edited the board
  in KiCad since the generator scripts last ran, rebuild from their current file (or fold their edits into the
  generators) before re-running anything. A rebuild from an older snapshot silently reverts the user's work, and only a
  diff against HEAD shows it.
- Every patch asserts its anchor matched exactly once (`assert t.count(old) == 1`). A silent miss is worse than a crash.
- Compute the new text before opening the file for writing: `open(p, 'w').write(f(t))` truncates the file before
  `f` runs, so an error or refusal inside `f` leaves an empty file.
- Generated strings go through `kstr()` (escapes quotes, backslashes and **newlines**). A raw newline inside a
  schematic string makes KiCad silently drop every item after it.
- Keep schematic and board in sync in the same change: a part added to the schematic needs its footprint, pad nets and
  fields on the board; series parts rename auto-generated nets (`Net-(U1-GPIO35)`), which the board must follow.

## 3. Verify (every iteration)

1. `python3 ${CLAUDE_SKILL_DIR}/scripts/sexp.py check <files>` - balance, raw newlines in strings, duplicate uuids.
2. `${CLAUDE_SKILL_DIR}/scripts/check.sh <scratch_proj> <scratch>/run1 --baseline <scratch>/base` - refills zones (run
   it twice after zone edits; the first refill can leave stale clearance errors), DRC with schematic parity, ERC,
   netlist export, all diffed against the baseline. Required: **0 unconnected items**, no new errors, parity clean.
3. Netlist assertions for what you added: `scripts/netspec.py check <spec> <sheet>` against the intended netlist (SPLIT,
   SHORT, MISSING, UNEXPECTED). ERC passing does not prove a symbol was not silently dropped or two nets were not
   joined. `check.sh` also runs `board_lint.py` (no courtyard, missing 3D models, silk on part bodies) and writes the
   unused/strapped-pin table (`nc_audit.py`); every pin in it needs a recorded decision before layout.
4. **Geometry checks DRC cannot do**: does a new track on a plane layer cut that plane (and what return paths cross the
   cut)? Did a via field leave isolated copper or slivers? Did a pour lose connection to a pad? Did a power path neck
   down? Use the board-review skill's scripts (`planes.py`, `power.py --net ...`, `view.py`) for these.
5. **Look at it.** `scripts/render.py board.kicad_pcb out.png --layers ... --window x0,y0,x1,y1`, then open the PNG with
   the Read tool and inspect it: overlaps, slivers, labels on pads, tracks where they should not be, parts in the way of
   tall components (use `--3d` for those). A clean DRC is not "looks right". See `references/rendering.md`.
6. **Verify against the reference, not only against generic checks.** DRC and ERC prove manufacturing and electrical
   rules, not design intent. Compare each block with its datasheet layout figure and tick its rules in the compliance
   file (`references/layout-stages.md`); compare the netlist with the intended one; `references/checks.md` lists what
   each check cannot see.
7. **Exempt items by name, never by category.** Known accepted warnings go in `check.sh --accept` with a reason each;
   never filter a whole violation type out of any report.

## 4. Copy back, then report

- Diff against the last commit: `python3 ${CLAUDE_SKILL_DIR}/scripts/board_diff.py HEAD <scratch board> --expect
  x0,y0,x1,y1 ... --expect-refs ... --expect-nets ...`. Everything outside what you meant to change is listed as
  UNEXPECTED; each one must be explained or reverted before copying back.
- Check KiCad is still closed and the originals' shasums still match (the user may have edited meanwhile). Copy the
  changed files back, re-run `check.sh` on the real project, delete any `~*.lck` files kicad-cli left behind.
- Update the design docs the project keeps (as-built values, why decisions were made) in the same change.
- If the project keeps a review list (e.g. `REVIEW.md`), queue findings there and apply them when the user says to work
  the list, not piecemeal as they are found.
- Report: checks first (DRC/ERC/parity vs baseline, unconnected = 0, every accepted item with its reason), then what
  changed (schematic and board, with coordinates), deviations from what was asked and why, anything not verified (say
  so plainly), and what the user must do (reopen/revert in KiCad, refill zones before saving, regenerate fabrication
  outputs). Give the absolute path of every file and render you mention. Ask before committing unless told to commit.
  Design checks passing is not "ready to fabricate": say what has not been qualified.

## Mistakes that make the user correct you

- Calling routing done with unconnected parts. Never call it done without 0 unconnected items in DRC *and* a look at
  the result.
- Routing signals on inner copper the designer kept clear. Follow the board's existing layer discipline; signals on
  plane layers need explicit permission.
- Routing from scratch next to traces that already exist. Check history for existing routes first.
- Placing a part that is out of stock. Every new part gets a stock check before it is placed.
- Designing around a part from memory. Read the datasheet first.
- Sizing power copper to the minimum. When there is room, make it wide.
- Starting a big rework without a checkpoint. Commit (or ask the user to) first.
- Re-raising something the user already accepted. Record accepted warnings and choices in the baseline and leave them.
- Declaring a requirement or datasheet rule "infeasible" without evidence. Record what was tried and what blocked it,
  and try the cheaper alternatives (smaller package, other value, other position or layer) first.
- Dropping a feature at layout because it is hard to route. A decision frozen in the schematic goes back to the user.
- Routing from memory of the datasheet. Re-open the block's brief and reference figure before routing it.
- Hiding a category of warnings to get rid of one known item. Exempt the item, by name.
