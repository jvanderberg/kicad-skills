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
- `scripts/kicad_sexpr/README.md` - the file-format layer: read, modify and generate .kicad_sch / .kicad_pcb /
  .kicad_sym / .kicad_mod / .kicad_pro. **Every generator and edit goes through it** (section 2)
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

**One place owns each file format and each fiddly rule.** `scripts/kicad_sexpr` owns KiCad's file syntax (quoting,
escaping, uuids, headers, `{slash}` net names, KiCad's own formatting). The higher-level writers sit on top of it and
own the design rules: `schgen`/`symgen` for schematics and symbols, `new_board.py` and `board_setup.py` for boards and
projects, `router.py` for copper and hole spacing, `add_courtyard.py` for footprints. They build every item through
the layer's builders and format no KiCad text themselves (the `.kicad_dru` rules language, which is not KiCad
s-expression data, is the one thing still written as text). A project generator describes the design; if it needs a
feature the writers lack, add it to the writer or the layer, never as a format string in the project.

**Generated files are deterministic.** The layer gives every item a stable uuid: the one it already had in the file
being regenerated (footprints and symbols by reference, items inside a footprint by what they are, tracks and vias by
net and geometry, zones by name), else one derived from that same key. The writers reuse the existing file by default
(`router.py --previous` for routing, since its input board has none), so an unchanged design regenerates
byte-identical, a change touches only its own lines, and GUI edits keep their ids. Never generate random ids.

**Data that exists upstream is carried forward (R22).** Every stage of the pipeline either keeps each field it receives
or stops with an error that names the part and the field: imported symbol -> redrawn symbol (`symgen.ic(...,
inherit=)`), library symbol -> placed symbol (`schgen` copies the library's Datasheet, Footprint, Description and
custom fields unless the call overrides them, falls back to the LCSC datasheet URL, and `write()` raises for a BOM part
with no datasheet link anywhere upstream unless `accept_missing(ref, field, reason)` names it), schematic -> netlist ->
board (`new_board.py` copies every field, Datasheet and Description included). `partfields.py check SHEET BOARD`
proves it at the end: every BOM part has a Datasheet link (not "" or "~") and an LCSC/MPN, and every schematic field
(Value, Footprint, Datasheet, Description, LCSC, MPN, custom fields, DNP / in-BOM) equals the board's; `check.sh` runs
it and exits 1 on a problem. Example (labelled): minipc-power's 87 BOM parts all reached the board with an empty
Datasheet, although JLCImport had written the LCSC link into every imported symbol and every part had an LCSC number:
the redraw, the placed-symbol writer and the board writer each wrote "" without complaint.

**Approved decisions are frozen; changing one is the user's call (R26).** Anything the user agreed to - a part, a
threshold or trip current, a behaviour, a value they were shown, a feature, the board size - is frozen. When later work
finds it cannot stand (the part is not stocked in the assembler's region, a pin cannot escape, a substitute moves a
derived value past its requirement, a rule cannot be met), stop before editing, and bring the user what changed with
its evidence, every consequence (pcb-part-selection `derived_check.py deps` lists the values that depended on a
part), two or three options with their costs, and a recommendation; then wait. A change forced by circumstances is
still a new decision, and so is everything it drags along (a second part changed to keep a trip current where it
was). This generalises "later stages check earlier frozen decisions" (R10, `references/layout-stages.md`) to every
phase, part selection included; pcb-part-selection `SKILL.md` "Substituting a part the user approved" has the
procedure. Record the user's choice where the decision lives (requirements, design notes, `design-values.json`
`"approved"`).

**Tools do not assume their environment (R21).** Scripts resolve every path from their arguments, never from the
current folder (`board_diff.py HEAD hardware/x.kicad_pcb` works from anywhere), find a project's own inputs by one
convention (`projfiles.py`: the project folder and its parents up to the repository root, each folder and its
`docs/`; every caller prints the file it used), pick the board by its `.kicad_pro` name rather than the first file
listed, and check their dependencies before starting (`preflight.py`). A project that builds with kicad-skills pins
the exact revision and KiCad version in `kicad-skills.lock` and checks it on every build (`skills_rev.py`,
`assets/kskills.py`; `references/new-design.md` s0). **Interpreters:** scripts that import `pcbnew` (`board_lint.py`,
kicad-board-review's `boarddump.py`) run under KiCad's python (`$KICAD_PYTHON`); scripts that import shapely, numpy or
scipy (`router.py`, the review pack's analysis scripts) under the analysis venv (`$PY`); everything else under any
python 3. Each one started under the wrong interpreter re-runs itself under the right one (`interp.py`), and an ad hoc
script that needs both runs with `interp.py run SCRIPT` (KiCad's python with the venv's packages, when their versions
match); `interp.py which` shows what was found. Scripts clean up after themselves: every kicad-cli call removes the
lock files it left (`kicad_locks.py`).

**Every stage proves it ran (R28).** A build or verification pipeline stops at the first stage that failed and checks
that each stage wrote its own, new output before the next one reads it: no `|| true` around a generator, a check for
the stage's "wrote" line or its output file (deleted before the stage runs, so a stale one cannot pass), `set -euo
pipefail` in shell. A router or checker that logs REJECTED or VIOLATION lines and exits 1 has failed, even though it
wrote a board. Verification run on stale or partial output reports about a board that does not exist: DRC after a
crashed routing stage reports the whole board unconnected, and a routing stage after a refused build routes the
previous board. When a checker becomes stricter, re-run the whole plan and list every newly rejected item
in one pass instead of discovering them one rebuild at a time. Pattern: `references/new-design.md` s6.

## 0. Before touching anything

1. **Is KiCad open?** Run `${CLAUDE_SKILL_DIR}/scripts/kicad_open.sh <project_dir>`. KiCad keeps its own copy in memory;
   if it is open, the user's next save overwrites your edit, or yours overwrites their unsaved work. If it is open, ask
   the user to save and close it, wait for them to say so, then re-read the files: they may have changed things.
   It answers OPEN only when a KiCad editor holds the folder; a lock file with no such process is STALE (kicad-cli
   leaves them; `--clean` deletes them) and UNSURE means ask. **Never tell the user KiCad is open from a lock file
   alone** - a state of the user's environment is reported from the thing itself, not from a proxy for it (R19).
   **Looking is not editing:** when the user only wants to see the board ("open it for me"), copy the project to a
   scratch folder and open the copy (`open -a KiCad <copy>/proj.kicad_pro` on macOS), or tell them plainly that the
   board will be regenerated and any edits they make will be lost - do not refuse to keep working because it is open.
2. **Checkpoint.** Before any non-trivial change, make sure the current state is committed (ask the user if it is not
   yours to commit), so the change is one clean diff they can review or revert.
3. **Read the project's own rules.** CLAUDE.md, README, design docs (often `docs/`), the layer usage you can see on the
   board (which layers carry signals, which are planes), and decisions the user already made. A board usually has a
   discipline - e.g. "no signals on inner layers", "all parts on top" - that is not written down anywhere except in the
   copper. Respect it; if your change seems to need breaking it, ask first.
4. **Preflight**: `${CLAUDE_SKILL_DIR}/scripts/preflight.py --project <project_dir>` - every tool present, and the
   kicad-skills checkout in use is the revision the project is pinned to.
5. **Baseline the checks** on the unchanged project: `${CLAUDE_SKILL_DIR}/scripts/check.sh <project> <scratch>/base`.
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
- For a new part: choose and verify it with the **pcb-part-selection** skill first (stock in the project's region from
  `sourcing.json`, package, datasheet). A part JLCPCB assembles uses JLC's own footprint, imported with JLCImport
  (pcb-part-selection "Importing into KiCad"), with a courtyard from `add_courtyard.py`; check it against the
  datasheet's land pattern, and lay out from the datasheet's layout example. For a **replacement** part:
  `derived_check.py deps` first (what was computed from the old part), and if the old part was approved by the user,
  R26 above before any edit.
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
- **Every read, edit and generator goes through `scripts/kicad_sexpr`** (its README has examples): load the file
  into the tree, change nodes or call the builders (symbols, wires, labels, footprints, tracks, vias, zones, keepouts,
  stackup, net classes), save. **Never build KiCad file text with format strings, f-strings or templates**, and never
  copy syntax out of another file: the layer owns quoting/escaping, unique uuids, KiCad 10 headers and the layouts
  KiCad writes, and it writes KiCad's own formatting, so untouched parts of a file stay byte-identical and diffs stay
  reviewable. Hand-formatted text is what produced a stray `'''` inside a schematic, a duplicated property, a keepout
  copied from a library footprint and a stackup found by grepping other projects. If the layer lacks a builder, build
  the `Node` (the generic tree keeps any token) and add a builder plus a kicad-cli-checked test to the layer.
- pcbnew python is not needed to place footprints any more (`Board.add_footprint`, checked against pcbnew's own
  placement and flipping). If you still use pcbnew for something, one stage per process, and pcbnew renames track
  nets to match pads on save. Details in `references/pcbnew-api.md`.
- **The base is the last commit, never an older snapshot**, and GUI edits come first: if the user has edited the board
  in KiCad since the generator scripts last ran, rebuild from their current file (or fold their edits into the
  generators) before re-running anything. A rebuild from an older snapshot silently reverts the user's work, and only a
  diff against HEAD shows it.
- Every edit asserts it found exactly what it meant to change (one footprint with that reference, one zone with that
  name, ...). A silent miss is worse than a crash.
- Regenerating a file: reuse the ids of the version you are replacing (`Board.new(previous=...)`,
  `Schematic.new(previous=...)`, or the writers' defaults) and check the diff against HEAD is only what you meant to
  change. A rebuild that rewrites every uuid hides the real change in noise (KiCad sorts board items by uuid on save).
- Compute the new text before opening the file for writing: `open(p, 'w').write(f(t))` truncates the file before
  `f` runs, so an error or refusal inside `f` leaves an empty file (the layer's `save()` already does this).
- Pass plain Python strings to the layer; it escapes quotes, backslashes and **newlines** when it writes (do not
  pre-escape). A raw newline inside a schematic string makes KiCad silently drop every item after it; the layer
  cannot write one.
- Keep schematic and board in sync in the same change: a part added to the schematic needs its footprint, pad nets and
  fields on the board; series parts rename auto-generated nets (`Net-(U1-GPIO35)`), which the board must follow.

## 3. Verify (every iteration)

**Check each edit where it acts, right after it (R30).** A fix is verified by a quick check aimed at what it changed,
run before the next edit: a zone, pour or via-field edit gets kicad-board-review's `pour_check.py BOARD --window ...`
(every pour piece keeps 2 vias to its plane; no track over a void, stubs and layer-change vias included); a placement
change gets the courtyard and overlap check at once (`check.sh`, `board_lint.py`), before any routing builds on it; a
generator change reads the generated file back and asserts the intended attribute arrived (the footprint, the field,
the net) - an override applied in one helper and missed by the part created elsewhere is found by the read-back, not
by the review; every label a script placed is looked at in a silk render. Batch the fixes from a review, check each
one this way, then run the long verification (the full pack, the full DRC baseline diff) once for the before/after
comparison: a minutes-long run restarted after every fix is abandoned, and nothing gets compared.

1. `python3 ${CLAUDE_SKILL_DIR}/scripts/sexp.py check <files>` - balance, raw newlines in strings, duplicate uuids.
2. `${CLAUDE_SKILL_DIR}/scripts/check.sh <scratch_proj> <scratch>/run1 --baseline <scratch>/base` - refills zones (run
   it twice after zone edits; the first refill can leave stale clearance errors), DRC with schematic parity, ERC,
   netlist export, all diffed against the baseline. Required: **0 unconnected items**, no new errors, parity clean.
3. Netlist assertions for what you added: `scripts/netspec.py check <spec> <sheet>` against the intended netlist (SPLIT,
   SHORT, MISSING, UNEXPECTED). ERC passing does not prove a symbol was not silently dropped or two nets were not
   joined. `check.sh` also runs `board_lint.py` (no courtyard - fix it with `add_courtyard.py` on the library, not by
   hand, `references/new-design.md` s5; missing 3D models, silk on part bodies, vias on same-net pads, paste over
   drilled holes, other-net copper under mounting hardware) and writes the unused/strapped-pin table (`nc_audit.py`);
   every pin in it needs a recorded decision before layout.
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

- Diff against the last commit: `python3 ${CLAUDE_SKILL_DIR}/scripts/board_diff.py HEAD <scratch board> --repo
  <project folder> --expect x0,y0,x1,y1 ... --expect-refs ... --expect-nets ...` (it finds the board of that file name
  in HEAD of the project's repository and prints which file it used; give `HEAD:<repo path of the board>` when two
  boards share the name), and the same for the schematic. Every attribute is compared (fields
  such as Value and LCSC, pad nets, DNP, models, settings), not only geometry. Everything outside what you meant to
  change is listed as UNEXPECTED; each one must be explained or reverted before copying back.
- Check KiCad is still closed and the originals' shasums still match (the user may have edited meanwhile). Copy the
  changed files back, re-run `check.sh` on the real project; `kicad_open.sh <project> --clean` removes lock files
  kicad-cli left behind (only when no KiCad process holds the folder).
- Update the design docs the project keeps (as-built values, why decisions were made) in the same change.
- If the project keeps a review list (e.g. `REVIEW.md`), queue findings there and apply them when the user says to work
  the list, not piecemeal as they are found.
- Report: checks first (DRC/ERC/parity vs baseline, unconnected = 0, every accepted item with its reason), then what
  changed (schematic and board, with coordinates), deviations from what was asked and why, anything not verified (say
  so plainly), and what the user must do (reopen/revert in KiCad, refill zones before saving, regenerate fabrication
  outputs). Give the absolute path of every file and render you mention. Every number in the report or a design doc
  (a via count, a length, a drop) is measured from the files as they are now (R29, kicad-board-review `SKILL.md`).
  Ask before committing unless told to commit.
  Design checks passing is not "ready to fabricate": say what has not been qualified.

## Mistakes that make the user correct you

- Calling routing done with unconnected parts. Never call it done without 0 unconnected items in DRC *and* a look at
  the result.
- Routing signals on inner copper the designer kept clear. Follow the board's existing layer discipline; signals on
  plane layers need explicit permission.
- Routing from scratch next to traces that already exist. Check history for existing routes first.
- Placing a part that is out of stock. Every new part gets a stock check before it is placed - in the assembler's
  region (`sourcing.json`), with the region stated when the part is shown to the user.
- Substituting for an approved part and fixing up what it breaks without asking. Stop and bring the options (R26).
- Designing around a part from memory. Read the datasheet first.
- Sizing power copper to the minimum. When there is room, make it wide.
- Starting a big rework without a checkpoint. Commit (or ask the user to) first.
- Re-raising something the user already accepted. Record accepted warnings and choices in the baseline and leave them.
- Declaring a requirement or datasheet rule "infeasible" without evidence. Record what was tried and what blocked it,
  and try the cheaper alternatives (smaller package, other value, other position or layer) first.
- Dropping a feature at layout because it is hard to route. A decision frozen in the schematic goes back to the user.
- Routing from memory of the datasheet. Re-open the block's brief and reference figure before routing it.
- Hiding a category of warnings to get rid of one known item. Exempt the item, by name.
- Telling the user KiCad is open because a lock file exists. Ask `kicad_open.sh`; it looks for the editor holding the
  folder.
- Running a check on the output of a stage that failed (R28). Stop at the failure; REJECTED / VIOLATION is a failure.
- Copying a reference block's copper without the copper that surrounded it, or onto different land patterns (R27,
  `references/layout-stages.md`).
- Leaving a control line between two chips to their reset defaults. Decide its level in every power and reset state
  (R12, `references/new-design.md` s4).
- Writing a number into a doc or a report from memory. Measure it from the current files (R29).
- A route-plan helper with a net name typed in. Nets come from the pads (R17, `references/routing.md`).
