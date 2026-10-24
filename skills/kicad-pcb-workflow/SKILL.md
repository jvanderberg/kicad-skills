---
name: kicad-pcb-workflow
description: How to safely change a KiCad (9/10) project from Claude Code - adding or swapping parts, editing schematics, placing footprints, routing tracks and vias, editing zones and silk, converting KiCad versions, and fixing DRC/ERC/parity errors - by scripted edits to the .kicad_sch/.kicad_pcb files with a verify-and-look loop. Use this whenever the user asks to modify, route, place, fix, upgrade or clean up anything in a KiCad project, even a "small" tweak, and whenever you are about to edit a .kicad_sch, .kicad_pcb, .kicad_sym or .kicad_mod file.
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
- `references/file-format.md` - s-expression anatomy, insertion anchors, nets, vias, zones, schematic symbols, the gotchas
- `references/pcbnew-api.md` - what pcbnew's python can and cannot be trusted with (KiCad 10.0.x)
- `references/layout-rules.md` - layer discipline, planes and return paths, power copper, vias, sense lines, silk
- `references/routing.md` - routing by hand from a script (no autorouter): planning lanes, coordinates as data, checks
- `references/rendering.md` - getting images you can actually inspect
- `references/version-upgrade.md` - KiCad 9 -> 10 conversion

## 0. Before touching anything

1. **Is KiCad open?** Run `${CLAUDE_SKILL_DIR}/scripts/kicad_open.sh <project_dir>`. KiCad keeps its own copy in memory;
   if it is open, the user's next save overwrites your edit, or yours overwrites their unsaved work. If it is open, ask
   the user to save and close it, wait for them to say so, then re-read the files: they may have changed things.
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
- Pass plain Python strings to the layer; it escapes quotes, backslashes and **newlines** when it writes (do not
  pre-escape). A raw newline inside a schematic string makes KiCad silently drop every item after it; the layer
  cannot write one.
- Keep schematic and board in sync in the same change: a part added to the schematic needs its footprint, pad nets and
  fields on the board; series parts rename auto-generated nets (`Net-(U1-GPIO35)`), which the board must follow.

## 3. Verify (every iteration)

1. `python3 ${CLAUDE_SKILL_DIR}/scripts/sexp.py check <files>` - balance, raw newlines in strings, duplicate uuids.
2. `${CLAUDE_SKILL_DIR}/scripts/check.sh <scratch_proj> <scratch>/run1 --baseline <scratch>/base` - refills zones (run
   it twice after zone edits; the first refill can leave stale clearance errors), DRC with schematic parity, ERC,
   netlist export, all diffed against the baseline. Required: **0 unconnected items**, no new errors, parity clean.
3. Netlist assertions for what you added: export the netlist and assert the new refs exist and connect to the nets you
   intended. ERC passing does not prove a symbol was not silently dropped.
4. **Geometry checks DRC cannot do**: does a new track on a plane layer cut that plane (and what return paths cross the
   cut)? Did a via field leave isolated copper or slivers? Did a pour lose connection to a pad? Did a power path neck
   down? Use the board-review skill's scripts (`planes.py`, `power.py --net ...`, `view.py`) for these.
5. **Look at it.** `scripts/render.py board.kicad_pcb out.png --layers ... --window x0,y0,x1,y1`, then open the PNG with
   the Read tool and inspect it: overlaps, slivers, labels on pads, tracks where they should not be, parts in the way of
   tall components (use `--3d` for those). A clean DRC is not "looks right". See `references/rendering.md`.

## 4. Copy back, then report

- Diff against the last commit: `python3 ${CLAUDE_SKILL_DIR}/scripts/board_diff.py HEAD <scratch board> --expect
  x0,y0,x1,y1 ... --expect-refs ... --expect-nets ...`. Everything outside what you meant to change is listed as
  UNEXPECTED; each one must be explained or reverted before copying back.
- Check KiCad is still closed and the originals' shasums still match (the user may have edited meanwhile). Copy the
  changed files back, re-run `check.sh` on the real project, delete any `~*.lck` files kicad-cli left behind.
- Update the design docs the project keeps (as-built values, why decisions were made) in the same change.
- If the project keeps a review list (e.g. `REVIEW.md`), queue findings there and apply them when the user says to work
  the list, not piecemeal as they are found.
- Report: checks first (DRC/ERC/parity vs baseline, unconnected = 0), then what changed (schematic and board, with
  coordinates), deviations from what was asked and why, anything not verified (say so plainly), and what the user must
  do (reopen/revert in KiCad, refill zones before saving, regenerate fabrication outputs). Ask before committing unless
  told to commit. Design checks passing is not "ready to fabricate": say what has not been qualified.

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
