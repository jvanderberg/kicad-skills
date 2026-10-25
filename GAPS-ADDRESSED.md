# Gaps from the minipc-power session: what changed

Source: `minipc-power/docs/skill-gaps.md` (33 numbered gaps, tool notes, tool list), written against commit 3ba7b5f.
Branch: `minipc-power-gaps`. The skill text is organised around the log's general rules (R1-R14), not around the
incidents; minipc-power appears only as labelled examples. Scripts are general-purpose and were tested on scratch
copies of minipc-power's files (the minipc-power repo was not modified).

Paths below are relative to `skills/`. "wf" = `kicad-pcb-workflow`, "nb" = `kicad-new-board`, "psu" =
`pcb-power-supply`, "bat" = `pcb-battery-power`, "ps" = `pcb-part-selection`, "rev" = `kicad-board-review`.

## Rules and where each one now lives

| Rule | Canonical statement | Also applied in |
|---|---|---|
| R1 Whole operating envelope | nb `SKILL.md` "How to run the interview" | nb interview-guide (thermal, startup, input power check, area budget); bat `charging.md` "Charging while running" |
| R2 Surface every assumption | nb `SKILL.md` "Never decide silently" | nb requirements template s10; wf layout-stages (frozen decisions back to the user) |
| R3 External data is a snapshot of one exact item | ps `SKILL.md` "External data is a snapshot..." | psu checklist + webench.md step 6; psu step 3 variants; rev checklist s8; `part_gate.py` |
| R4 Third-party statements go stale | ps `SKILL.md` (same section, last paragraph) | psu webench.md header (dated, discover current behaviour); ps jlcimport install note (dated) |
| R5 Gather references early, re-consult at point of use, brief per phase | wf `references/layout-stages.md` intro | psu step 6 (reference pack); wf SKILL.md s1; wf assets/layout-brief-template.md |
| R6 Verify against the reference, not only generic checks | wf `SKILL.md` s3 item 6 | wf layout-stages (compliance file), wf checks.md, rev checklist s4, rev analysis-limits |
| R7 Every check has blind spots | wf `references/checks.md` | wf SKILL.md s3; `board_lint.py`; rev checklist s9 |
| R8 Never suppress a category | wf `references/checks.md` "Exemptions" | `drc_summary.py --accept` (both copies); `check.sh --accept`; wf SKILL.md s3 item 7; rev checklist s11 |
| R9 "Can't be met" needs evidence | wf `references/layout-stages.md` compliance section | wf assets/layout-compliance-template.md; wf SKILL.md mistakes list; rev checklist s4 |
| R10 Later phases check earlier frozen decisions | wf `references/layout-stages.md` stage 1 | bat `charging.md` "PD sink + charger" (contract as a downstream limit); wf SKILL.md s1 and mistakes |
| R11 Allocate shared resources first | wf `references/layout-stages.md` stage 0 | wf routing.md (plan before the first track; reserved via sites) |
| R12 Defaults are decisions; interfaces get affordances | wf `references/layout-rules.md` "External connections are a user interface" + `nc_audit.py` | nb interview (startup, external connections), nb template; rev checklist s6/s9; `new_board.py --labels` |
| R13 One place owns each format and fiddly rule | wf `SKILL.md` (paragraph after the reference list) | wf new-design.md (table of owning scripts); `kicad_sexpr` owns the syntax and the writers sit on it: `schgen`, `symgen`, `new_board.py` (no pcbnew), `board_setup.py`, `router.py`, `add_courtyard.py` build every item with its builders and format no KiCad text (branch `writers-on-kicad-sexpr`; `.kicad_dru` rules text is the one exception, and no skills script writes it); `fpcheck.py` reads through it; `sexp.py` lost its text-editing helpers |
| R15 Generated files are deterministic and canonical | wf `SKILL.md` "Generated files are deterministic" | `kicad_sexpr` stable uuids (previous file's id by key, else uuid5 of the key) used by every writer; `Project.assign` writes KiCad 10's list form; kicad_sexpr README "Stable ids" |
| R14 Standard, verified building blocks first | ps `SKILL.md` "Importing into KiCad" | wf new-design.md s5; `fpcheck.py`, `add_courtyard.py` |
| R16 The interview comes first; a short request is not consent to defaults | nb `SKILL.md` "The interview comes first" | nb `SKILL.md` "Respect the user's time" (defaults only on an explicit request); wf new-design.md "Requirements first" (no schematic without an agreed `docs/requirements.md`); root `CLAUDE.md` (SKILL.md files are instructions when the plugin is not installed) |

Refinements to the rules: none merged. R13 gained one concrete corollary found while porting (compute the new text
before opening a file for writing: `open(p, 'w').write(f(t))` truncates the file before `f` runs; wf SKILL.md s2).

## Gap -> rule -> change -> verification

| Gap | Rule | What changed (files) | How it was verified |
|---|---|---|---|
| 1 multi-amp 1S | R1 | bat `SKILL.md` scope note + s4; `charging.md` "Choosing the charger"; `protection-and-safety.md` trip sizing with boost input current | Text. BQ25606 facts checked against SLUSCK6C (p1, p6, p9); power-bank SoC families named only, marked "not reviewed" |
| 2 15 W ceiling vs charge-while-running | R1 | nb `SKILL.md` step 4, interview-guide "Input power check", template s4; bat `charging.md` "Charging while running"; bat verification.md | Text (arithmetic only) |
| 3 thermal budget question | R1 | nb `SKILL.md` step 2, interview-guide s2 row, template s2 | Text |
| 4 jlcimport install | R4 | ps `SKILL.md` "Installing jlcimport-cli"; README requirements | `pipx install git+https://github.com/jvanderberg/kicad_jlcimport` into a scratch PIPX_HOME: installed 1.6.7, `--region` present. `--region` first appears in tag v1.6.0 (git history) |
| 5 PD sink + charger interaction | R10 | bat `charging.md` "PD sink + charger"; sources.md BQ25606 row; verification.md | VINDPM 4.3 V / VBAT+200 mV (p19) and ILIM used only for an unknown adapter (p19, p23) read in SLUSCK6C. Sink fallback behaviour: guidance only (no CH224Q datasheet statement exists, per the log) |
| 6 parallel cells | R1 | bat `chemistries.md` "Parallel cells (1SnP)" | Text, marked as practice |
| 7 protector trip vs gate drive | R1 | bat `protection-and-safety.md` new bullet with the boost-current example | Text; 8205A trip range marked "commonly reported, unverified". See "Disagreements" |
| 8 standalone vs I2C chargers | R1 | bat `charging.md` table + startup-independence paragraph; bat `SKILL.md` s4 cross-link | Text; BQ25606 standalone/NVDC checked (SLUSCK6C p1) |
| 9 WEBENCH too late | R5 | psu `SKILL.md` checklist at the top; nb step 8; ps "Finding candidates"; psu webench.md header (no chargers) | Text |
| 10 WEBENCH picks not stock-filtered | R3 | psu webench.md step 6; `pcb-part-selection/scripts/part_gate.py --from-text` | Run on minipc-power's WEBENCH notes text: TPS61022 0, TPS61230A 0, TPS61236P 13 at LCSC global (matches the log), TPS61088 SUSPECT (404) with 7,130 in stock. Not tested on live WEBENCH page text (no session) |
| 11 WEBENCH refuses a part | R4, R9 | psu webench.md "When WEBENCH refuses a part" | Text |
| 12 false "no CAD export"; PCB LAYOUT tab | R4 | psu webench.md "CAD export and the reference layout" (dated list, re-check instruction) | EAGLE path verified: minipc-power's WBDesign36 export (zip of zips, backslash paths) -> `kicad-cli pcb import --format eagle` -> 14 footprints, no Edge.Cuts; rendered with the fixed `render.py --window`. Export list itself taken from the log (Oct 2026) |
| 13 layout reference pack, order of authority | R5 | psu `SKILL.md` new step 6; psu layout.md intro; wf SKILL.md s1 | Text; `datasheet.py find` located the BQ25606 layout pages (p34-35) |
| 14 lifecycle check | R3 | ps `SKILL.md` snapshot section + datasheet step; psu webench.md ("IC Cost: N/A"); nb step 8; rev checklist s8; `part_gate.py` | TI product pages: TPS61088 -> 404 -> SUSPECT; TPS61088-Q1, BQ25606 -> ACTIVE (meta status tag); orderable numbers resolve (TPS61089RNRR -> TPS61089, TPS61088QRHLRQ1 -> TPS61088-Q1) |
| 15 render.py needs Edge.Cuts | R7 | wf `scripts/render.py` (temporary outline at --window; uncropped without) | Rendered minipc-power's imported WEBENCH board (no outline) with and without --window; looked at the PNG |
| 16 from-scratch schematic/board, readability | R13 | wf `references/new-design.md`; `schgen.py`, `symgen.py`, `netspec.py`, `new_board.py`, `board_setup.py`; wf SKILL.md | Regenerated minipc-power's schematic with the ported schgen/symgen: netspec matches, ERC clean (same as original). Full pipeline netlist -> `new_board.py` -> `board_setup.py` -> `router.py` (board's own route plan) -> DRC: 0 unconnected, 0 parity, only the 2 known J1 silk_edge warnings, identical to the real board. Empty `Sch().write()` loads in kicad-cli |
| 17 imported footprints lack courtyards | R7, R14 | wf `scripts/add_courtyard.py`, `board_lint.py` (lists them), layout-rules.md | Fresh `jlcimport-cli import` of 4 parts: none had F.CrtYd; added, re-run skips, `kicad-cli fp export svg` renders them, image inspected. board_lint flags a footprint whose courtyard was removed |
| 18 KiCad library footprints first; matcher unreliable | R14 | ps `SKILL.md` "Importing into KiCad"; wf new-design.md s5; `fpcheck.py` | fpcheck on KiCad NexFET VSON-8 vs Device:Q_PMOS reports the merged-pad problem; vs the redrawn symbol passes; RHL QFN vs "VQFN-20-EP(3.6x4.6)" passes; a wrong package string is flagged. `jlcimport-cli import --help` has no footprint-choice option (v1.6.7) |
| 19 board setup / stackup | R13 | wf `scripts/board_setup.py`; nb next steps; wf file-format.md, pcbnew-api.md | Stackup + rules + classes on a pcbnew-created board: KiCad reads thickness 1.606 mm, min clearance 0.15, hole-to-hole 0.25, edge 0.3, GND/VBUS in class Power, patterns (`+*`) assign +12V/+3V3; 2-layer variant DRC loads; layer-count mismatch refused without writing |
| 20 router helper, hole-to-hole | R13 | wf `scripts/router.py`; routing.md s2-3; file-format.md | See "Router" below |
| 21 datasheet layout loop in routing | R5, R6 | wf routing.md (block loop, "Generic habits that break datasheet rules"); layout-stages.md; compliance template | Text |
| 22 staged sessions with briefs | R5 | wf `references/layout-stages.md`; `assets/layout-brief-template.md` | Text |
| 23 MCU / controller question | R1, R2 | nb `SKILL.md` step 3, interview-guide s3, template "Startup and control" | Text |
| 24 pad-only boards: labels, polarity | R12 | wf layout-rules.md "External connections are a user interface"; nb interview + template; `new_board.py --labels` (both silk layers, mirrored); rev checklist s9 | `new_board.py --labels` reproduced minipc-power's pad labels (pipeline test); board_lint found no label on a part body on the real board and caught one moved onto U4 |
| 25 board size ignores pads | R1 | nb `SKILL.md` step 5, interview-guide s5; wf layout-rules.md | Text |
| 26 fine-pitch fan-out before freezing | R10 | wf layout-stages.md stage 1; wf SKILL.md s1 + mistakes | Text |
| 27 channel plan | R11 | wf layout-stages.md stage 0; routing.md | Text |
| 28 "infeasible" needs evidence | R9 | wf layout-stages.md; compliance template deviation fields; wf SKILL.md mistakes; rev checklist s4 | Text |
| 29 variant re-derivation | R3 | psu `SKILL.md` step 3 + checklist; psu webench.md; ps snapshot section | Text; `part_gate.py` keeps -Q1 variants apart (verified) |
| 30 viewing vs editing; full paths | R2 | wf `SKILL.md` s0 (open a copy) and s4 (absolute paths); nb next steps | Text |
| 31 full-board renders unreadable with pours | R7 | wf rendering.md (use view.py for routing / figure comparison); render.py docstring | Text |
| 32 datasheet handling | R4 | `pcb-part-selection/scripts/datasheet.py`; ps `SKILL.md` | TI symlink for TPS61088 refused ("HTTP 404, page title Error 404"); BQ25606 PDF saved; `find` named pages for "Layout Example", "9.3.2.3"; `page` rendered p35. pdftotext warnings suppressed |
| 33 no-connect pins hide decisions | R12 | wf `scripts/nc_audit.py`, check.sh; new-design.md; rev checklist s6 | On minipc-power's netlist: 23 rows (unused pins, symbol-NC pins, inputs tied to rails such as OTG/CE to GND), notes file fills the decision column, `--require-notes` exits 1 while any is missing |
| 0 s-expression object model | R13, R15 | `kicad_sexpr` (merged from `sexpr-model`); the writers moved onto it on `writers-on-kicad-sexpr` | minipc-power (f8f963b) rebuilt with the ported writers vs with main's: ERC, netlist, DRC report identical (0 unconnected, parity 0, the 2 accepted J1 silk items; 105 footprints, 298 segments, 98 vias, 28 zones incl. 3 keepouts); generated schematic and symbol library equal item by item. Two from-scratch builds byte-identical (.kicad_sch, .kicad_pcb before and after refill, .kicad_pro); a build over the committed files keeps all 887 schematic and 2273 of 2277 board uuids (the 4 others: 2 vias + 2 links that skills' `router.py` places differently from minipc's own router), a rebuild of that is byte-identical, and adding one part adds only its 84 schematic / 160 board lines |

### Tool notes in the log

| Note | Change | Verification |
|---|---|---|
| render.py refuses boards without Edge.Cuts | gap 15 | above |
| jlcimport cannot choose a KiCad library footprint | ps SKILL.md (assign in the schematic; check suggestions with fpcheck) | `--help` |
| KiCad library footprints reference uninstalled 3D models | `board_lint.py` MODEL MISSING; rendering.md; rev checklist | On a regenerated minipc-power board: J1 (HRO TYPE-C-31-M-12) and F1 (NANO2) missing as the log says, **plus U5 (Texas_VQFN-RHL-20), which the log does not mention and which the real board still has** |
| `FOOTPRINT.Models()` returns copies | wf pcbnew-api.md failure table | Not re-tested; from the log |
| router via_ok any-net spacing; keepout() | `router.py` (hole-to-hole vs every drill incl. pad drills; `keepout()` with configurable forbids) | Router tests below |
| DRC passes silk under bodies | `board_lint.py` SILK ON PART | Injected test caught; real board clean |
| DRC summary dropped every silk_* type | `drc_summary.py --accept` (both skills), `check.sh --accept`, checks.md | Named J1 exemption accepted 2 items; stale entry flagged; type-only entry refused |
| jlcimport "No component found" for one part | No change (part-specific; a part without EasyEDA data simply needs another part) | - |

### Tools list in the log

| Tool | Status |
|---|---|
| 1 netspec | `wf/scripts/netspec.py`, generalised (JSON or .py spec, symmetry from library pin types + prefixes, MISSING, SHORT reported once per KiCad net, `from-netlist`) |
| 2 find_merges | `wf/scripts/schgen.py find_merges()`. Two prototype bugs fixed: PWR_FLAG symbols were treated as one net name (false merges of every flagged net), and reversed two-pin passives were tagged with the wrong net. On minipc-power's clean sheet the prototype logic reported 7 false merges; the port reports none and pinpoints an injected fault |
| 3 schgen.Sch | `wf/scripts/schgen.py` (plus `collisions()`, duplicate-property assertion, symbol-dir finder) |
| 4 symbols ic()/fet() | `wf/scripts/symgen.py` |
| 5 symlib / fpinfo | folded into `wf/scripts/fpcheck.py` |
| 6 collision check | `Sch.collisions()`: pins on wire interiors, overlapping collinear wires, wires through bodies, overlapping bodies (text-on-text overlap not done) |
| 7 block layout helpers | Guidance only ("ladder layout" in new-design.md); no helper code |
| 8 footprint vs package / matcher wrapper | `fpcheck.py` (pad count, body size vs the LCSC package string, numbering vs symbol). Not a wrapper around jlcimport's matcher |
| 9 lifecycle + stock gate | `ps/scripts/part_gate.py` (TI lifecycle only; other vendors "check by hand") |
| 10 WEBENCH table -> stock | `part_gate.py --from-text` |

### Router (gap 20, issue #1)

- minipc-power's own route plan, run through `router.py apply` on the board with its routing stripped, reproduces the
  real board (298 segments, 98 vias, 28 zones incl. 3 keepouts). DRC on the result equals the real board's (2 known J1
  silk warnings, 0 unconnected, 0 parity).
- Its pre-write checks report 4 track VIOLATIONs, all in U1's 0.4 mm-pitch escape area, which the project's
  `.kicad_dru` relaxes; the router does not model custom DRU rules (documented; `clearance=` per call).
- Regression plan: a second same-net via on an existing via, one 0.3 mm away, one 0.5 mm from a TH pad drill, and one
  off the board edge are all REJECTED with the reason; a track joining pads of two nets raises; an unknown pad raises.

## Left open, and why

- **Tool 7** (block layout helpers): written as guidance; a helper worth having needs design work with the
  object model.
- **Live WEBENCH table text**: `part_gate.py --from-text` uses a TI part-number regex; tested on text containing the
  names, not on a pasted table-view page (no WEBENCH session).
- **Lifecycle for non-TI vendors**: reported as "check by hand".
- **router.py** does not model `.kicad_dru` rules or zone fills (DRC remains the authority).
- **board_setup.py**: the 2-layer entry is derived (JLC publishes no 2-layer table); copper-finish names are passed
  through unvalidated (KiCad's accepted strings could not be read from the install); hole-to-hole and hole clearance
  are KiCad defaults, not JLC numbers.
- **new_board.py / schgen.py**: tested on single-sheet projects only (new_board builds paths from the netlist's sheet
  path, so hierarchy should work, but it is untested).
- `FOOTPRINT.Models()` copy behaviour and WEBENCH's export list come from the log and were not re-tested here.

## Disagreements with the log

- **Gap 7** is partly already covered at 3ba7b5f: `protection-and-safety.md` said the gate is driven from the cell and
  to "use R_DS(on) at about 2.5-3.5 V Vgs". The new text makes the consequence explicit (trip current lowest when the
  cell is nearly empty, which is when a boost draws most) and adds the sizing example.
- **Gap 17's** fix as worded (pad/body bounding box + 0.25 mm) is what `add_courtyard.py` does; the courtyard-based
  body estimate turned out unreliable for size checks on leadless parts (pads protrude), so `fpcheck.py` only reports
  body size from a real F.Fab outline and prints the pad span as a note otherwise.
- **"Silk text vs courtyard"** (tool notes): checking text against courtyards flagged 15 labels on minipc-power that
  only graze the clearance margin of the pad they label. `board_lint.py` checks text against the other part's body
  (F.Fab extent + pads) instead, which is the actual failure (label hidden under a fitted part).

---

# Round 2: running kicad-board-review on minipc-power (gaps 34-45, plus 46)

Source: `minipc-power/docs/skill-gaps.md`, "Found running kicad-board-review (2026-10-24, GitHub main 77055cd)",
gaps 34-45, plus gap 46 (every Datasheet field empty on schematic and board), reported afterwards. Branch
`review-gaps` from origin/main a75cdde. As in round 1, each gap was first named as a class of failure and the class
was fixed; minipc-power appears only as labelled examples. All scripts were run on scratch copies of minipc-power's
files (the pre-review state is minipc-power `HEAD`, the fixed state its working tree); minipc-power was not modified.

## Classes, and where they differ from the brief's reading

| Class | Gaps | Rule |
|---|---|---|
| A check reports a clean or empty result for inputs it never saw (coverage missing from the result) | 34, 39b, 40 (half), and the audit below | R16 |
| Roles inferred from names instead of the design's structure | 34 | R17 |
| Findings unranked, or reported as an aggregate shape instead of what was measured | 41, 42 | R18 |
| A proxy accepted as evidence for the specific thing a requirement names (symbol pin type, a similar part nearby, a secondary tool's BOM, a geometric metric for an electrical one) | 35, 37, 43 | R19 |
| Idealised operating points: no source or path impedance, steady state only | 36, 38 | R20 |
| Tools that assume their environment (cwd, where config lives, what is installed, which revision) | 39a, 40 (half), 44, 45 | R21 |
| Data that exists upstream dropped silently by a pipeline stage | 46 | R22 |

Where this differs from the brief:
- **39b (board_diff blind to fields) is a coverage failure, not an environment one.** The tool ran fine; it compared
  only geometry and reported "0 unexpected change groups". It is fixed under R16 (compare every attribute, say what
  was compared), and 39a (the path) under R21.
- **43 belongs with 35/37.** Pad-to-pad loop geometry stood in for the electrical quantity exactly as "NC pin type"
  stood in for the pin-table instruction and "a 47 uF cap 3 mm away" for the datasheet's 1 uF at the pins. The fix
  is the brief's (an electrical cross-check), filed under R19.
- **41/42 are a separate class from 34.** 34 is silence about what was not seen; 41/42 report real findings badly
  (an aggregate bounding box, one undifferentiated list). Their fix is ranking and faithful shapes (R18), not coverage.
- **40 is both:** a wrapper not finding the project's notes (R21), and not saying which notes it used (R16).
- **46 is R16's sibling**: R16 is a check silently losing coverage, R22 a stage silently losing data. Both now fail
  or warn by name. R22 also covers precedence: a generic library symbol's link (KiCad's Connector symbols point at the
  USB-C specification) is not the part's datasheet.
- **45**: the deterministic writers are on main (a75cdde); what remained is pinning. The pin also records KiCad's
  major.minor, since the canonical file form (R15) depends on it, and refuses a commit that is on no remote branch -
  the actual root cause (an unpublished local branch).
- **44's wx noise is an R8 instance**: check.sh dropped every line containing "traits" (a category filter); now
  exactly the known assert line is dropped, at the source.

## Rules and where each one now lives

| Rule | Canonical statement | Also applied in |
|---|---|---|
| R16 Coverage is part of the result | wf `references/checks.md` "Coverage is part of the result" | rev SKILL.md s2 (read coverage first); every pack report starts with "Coverage and warnings"; `board_diff.py` "Compared:" line; `partfields.py` counts; `projfiles.py` callers print the file used; rev interpreting-results.md, reviewer-brief item 10 |
| R17 Roles from structure, names only override | rev `SKILL.md` s2 | `topology.py` (ground, switch nodes, switching ICs, hot-loop candidates); `common.cls_how`; starter config; `nc_audit.py` straps by supply-pin structure; rev analysis-limits.md |
| R18 Findings ranked and reported as the shape found | rev `SKILL.md` s3 | `emc.py` span severity (void > another net's plane > coplanar ground/edge) with nearest decap; `planes.py` pours vs slots, slot vs corridor network; `report.py` tiers |
| R19 Evidence names the specific item | psu `SKILL.md` step 6 (two paragraphs) | `refparts.py` + `reference-parts.json`; `nc_audit.py` (NC-typed pins need notes, `--datasheet`); psu webench.md (BOM is secondary); wf compliance template ("Satisfied by" column, electrical numbers); `emc.py` hot-loop DC solve; rev checklist s4/s7 |
| R20 Operating points solved with source and path impedance, at every corner and over time | psu `SKILL.md` "Operating points are solved, not divided" | `path_budget.py`; `power.py` R_eff; rev checklist s1 item and new s1b (start-up, shutdown, transients); bat protection-and-safety.md, verification.md, SKILL.md s6; nb SKILL.md step 4; rev reviewer-brief; psu input-protection.md |
| R21 Tools do not assume their environment | wf `SKILL.md` (paragraph before s0) | `projfiles.py` (both skills); `board_diff.py` path resolution; `pick_board` in check.sh/make_pack.sh; `preflight.py`; `skills_rev.py` + `assets/kskills.py`; wf new-design.md s0; wf SKILL.md s0 step 4; nb next steps |
| R22 Data that exists upstream is carried forward, or the stage fails | wf `SKILL.md` (paragraph before s0) | `symgen` inherit; `schgen` carried fields, precedence, `write()` raises, `accept_missing`; `new_board.py`; `partfields.py` (in check.sh); `bom_check.py`; `netdigest.py`; ps SKILL.md import notes; rev checklist s8 |

## Gap -> rule -> change -> verification

| Gap | Rule | What changed (files) | How it was verified |
|---|---|---|---|
| 34 starter config classifies switch nodes as slow, silently | R16, R17 | rev `scripts/topology.py` (new), `make_pack.sh` (project config by projfiles, else a starter derived from the netlist), `common.py` (WARN, derived classes, missing ground), `emc.py` (no silent skips, derived hot loops), `report.py` (coverage first) | Pre-review minipc pack with the old example config: **old scripts** `emc ok: ... loops 0 fast 0`, switch-copper list has 1 of 5 switch nodes, empty hot-loop table, no warning. **New** with the same config: 5 switch nodes derived (`Net-(C4-Pad2)`, `Net-(U4-SW)`, `Net-(C24-Pad2)`, `Net-(U6-L1)`, `Net-(U6-L2)`), the two placeholder loops `NOT CHECKED`, derived loops for U2/U4/U5/U6, 10 of 12 checked. Fresh `make_pack.sh` on the pre-review project writes a starter with those entries and runs. Synthetic: buck with switch node `Net-(L1-Pad1)` and a "PH" pin, async buck whose switch pin is "OUT", LC input filter (not a switch node), discrete-FET switch node (reported underived), wrong ground_nets (warned): `tests/test_topology.py` 5/5 |
| 35 NC-typed pin accepted as decided | R19, R12 | wf `nc_audit.py` (NC pins need notes, `--datasheet` pin-table row, notes found by projfiles), wf new-design.md s4, psu SKILL step 6, rev checklist s7 | Pre-review minipc: U5.11/U5.12 now `**TODO**` with the TPS61088-Q1 row "No connection inside the device. Connect these two pins to ground plane on the PCB for good thermal dissipation"; also U2.2 and U3.4 (NC) now need notes; 4 without a decision vs 0 before. Synthetic: NC to ground vs DNC must float, both shown, `--require-notes` exit 1 then 0: `tests/test_project_inputs.py` |
| 36 design currents ignore the source's series resistance | R20 | psu `scripts/path_budget.py` (new), psu SKILL.md, rev checklist s1, bat protection-and-safety.md / verification.md / SKILL.md, nb SKILL.md, `power.py` R_eff | minipc path from the datasheets (CSD13202Q2 R_DS(on) 8.4/10.4 mOhm at Vgs 3 V, BQ25606 BATFET 19.5/30 mOhm, IBATFET_OCP 6.0 A, TPS61088-Q1 UVLO falling 2.5 V max) plus the pack's copper R_eff, cell 20/40 mOhm and wiring 10/20 mOhm **assumed**: at 3.0 V typ, naive 5.65 A vs solved 7.12 A at 2.38 V, BATFET trip flagged as latching, UVLO crossed; at max R no operating point (16.95 W > 16.5 W); full load needs >= 3.35 V (typ) / 3.64 V (max R). Synthetic: 5 V USB through 0.10/0.25 Ohm cable into a buck (UVLO, latching eFuse, trip delay honoured, hand-checked quadratic, copper from a power run): `tests/test_path_budget.py` 3/3 |
| 37 small caps from the typical application dropped; WEBENCH treated as primary | R19 | wf `scripts/refparts.py` (new), psu SKILL step 6 + checklist, psu webench.md, compliance template, rev checklist s4/s7 | minipc with a TPS61088-Q1 `reference-parts.json` (7 entries): pre-review `WRONG VALUE: best is C30 (47uF, 4.57 mm), need 1u`, exit 1; fixed board `ok: C38 (1uF, 1.71 mm)`, exit 0. Synthetic buck missing its bootstrap and HF input cap; a single bulk cap does not satisfy two entries: `tests/test_refparts.py` |
| 38 load-switch / inrush timing in no checklist | R20 | rev checklist new s1b; `path_budget.py` transients; psu SKILL verify; bat verification.md; psu input-protection.md | minipc: Q5 turn-on 0.1 ms into 100 uF (**assumed** load C) adds 5 A: IBATFET_OCP crossed (latching) at every corner; 1 ms adds 0.5 A: clears at a full cell, not below ~3.6 V at 15 W |
| 39a board_diff fails below the repo root | R21 | wf `board_diff.py` (HEAD -> `HEAD:./name` from the file's folder; REV:path passed as written) | From `minipc-power/hardware`: old `CalledProcessError ... git show HEAD:minipc-power.kicad_pcb`; new works, and from outside the repository gives a clear error. Test: board in `hardware/`, run from the temp folder: `tests/test_board_diff.py` |
| 39b board_diff blind to fields | R16 | wf `board_diff.py` rewritten on kicad_sexpr: every footprint attribute + "other content", zones' settings, every other top-level item, schematics by reference, "Compared:" line | minipc working tree vs HEAD: old: 3 groups, R7/R16/C32 invisible; new: `R7: field Value '330' -> '100'; field LCSC 'C25104' -> 'C25076'`, R16, C32, U5 pad 11/12 nets, C38, the GND tracks and via (8 groups). Schematic mode also shows R25's LCSC change. Synthetic field-only change flagged: `tests/test_board_diff.py` |
| 40 check.sh cannot see the project's pin decisions | R21, R16 | `projfiles.py` (both skills), wf `check.sh` (`--notes`, `--require-notes`, discovery of notes and DRC exemptions, nc_audit failures no longer swallowed), `nc_audit.py` discovery | `check.sh` on a scratch copy of the pre-review project (KiCad files in `hardware/`, notes in `docs/`): "using .../docs/pin-decisions.json (found by search)", 23 listed / 4 without a decision (the NC pins of gap 35) instead of 19 |
| 41 another net's pour reported as a board-sized slot | R18 | rev `planes.py` (pours split out, per-slot sizes, slot vs corridor network, clearance ring dropped), `report.py`, boarddump zone clearance | Pre-review B.Cu: old "44.4x31.9 mm slot ... pour of BAT"; new "other-net pours inside it: BAT 97 mm^2" and "track corridors 160 mm long, 0.75 mm mean width, 120 mm^2 ... /EN, /3V3_PG, U2-TS, J1-CC2", then a 16 mm Q5-G corridor etc. Synthetic: VBAT pour inside a ground hole is a pour, a 20 x 0.8 mm cut is one slot: `tests/test_pack_synthetic.py` |
| 42 every B.Cu track "not over ground" under an In2 power plane | R18 | rev `emc.py` (severity per span, coplanar ground share, nearest decoupling cap), `report.py` tiers | minipc pack0 config with slow_ext made fast: /EN medium (22.5 mm over VSYS, nearest VSYS-GND cap 14.5 mm, coplanar ground 32 %), U2-TS and /3V3_PG low (coplanar ground 88-95 %), CC1 low (ground edge). Synthetic: void span = high, power-plane span with ground pour both sides = low |
| 43 hot-loop metric is pad-to-pad only | R19 | rev `emc.py` (1 A DC solve per loop, ground return and supply side: mOhm, share through vias, busiest via with size), `fem.py` link flows, `report.py`, analysis-limits.md | Pre-review: "U6 VIN loop (cap C33): ground return 100 % through one via (0.6/0.3 mm) ... 3.3 mOhm", U6 VOUT (C34) 100 % through the 0.45/0.2 via. Fixed board: C33 51 %, 1.7 mOhm; C34 still 84 % (the review's open item). Also flags C2 and C6 of U2 (single via each) - not in the review; worth a look |
| 44 environment: jlcimport, wx assert, view.py labels, layout-refs index | R21, R8, R4 | `preflight.py` (both skills); `boarddump.py`/`board_lint.py` drop exactly the wx assert line, check.sh's category grep removed; `view.py` labels clipped to the window, title with the window; ps `datasheet.py page --label` -> INDEX.md, `datasheet.py index`; psu SKILL step 6 | `preflight.py --project`: all 11 tools found (KiCad 10.0.1, shapely 2.0.7, jlcimport with --region). boarddump and board_lint on the minipc board print no assert. `view.py` 6 x 6 mm window rendered and inspected: labels inside, no clipping. `datasheet.py index` on a copy of `docs/layout-refs/tps63802-3v3/`: 7 images, 7 without a row (exit 1); `page ... 28 --label "Figure 12-1 layout example"` (p28 found by `find "Layout Example"`) writes the row |
| 45 build only reproducible against an unpublished kicad-skills | R21, R15 | `skills_rev.py` show/pin/check/require (both skills), `assets/kskills.py`, wf new-design.md s0, nb next steps | On this branch: pin refuses (dirty, then "on no remote branch"); `--allow-unpublished` pins; check ok; a lock with another commit fails with the worktree command; the kskills template stops the import on mismatch and loads kicad_sexpr from `KICAD_SKILLS` when it matches. Throw-away clone: pin refuses unpublished, check fails dirty and after a new commit: `tests/test_skills_rev.py` |
| 46 every Datasheet field empty (87 BOM parts) | R22, R3 | wf `symgen.py` (`inherit=`), `schgen.py` (carry library fields, precedence, `write()` raises, `accept_missing`, `Sch.lib(lib=)`), `new_board.py` (datasheet/description elements), `partfields.py` (new; in check.sh), ps `bom_check.py`, rev `netdigest.py`, docs | Pre-review: `partfields.py check` "87 BOM parts, 0 with a datasheet link", 174 problems, exit 1; check.sh exits 1; netdigest "87 of 87". minipc's own `gen_schematic.py` run against the fixed `schgen.py`: 87/87 filled, ERC 0, minipc's netspec matches, diff = the Datasheet lines plus library Descriptions; `new_board.py` from that netlist: 87/87 on the board, 0 parity problems. `--online`: 86 LCSC pages load and name the part; it caught J1 taking KiCad's generic USB-C spec .zip from the library symbol, which led to the precedence fix (now J1 -> its LCSC page "TYPE-C-31-M-12"). Synthetic part with no LCSC: `write()` raises, `accept_missing` writes and the checker still reports it until exempted; board LCSC drift caught: `tests/test_fields_carried.py` 4/4 |

### Audit: the silent-default pattern across the scripts

| Script | Silent default found | Now |
|---|---|---|
| `common.py` | ground nets default to `GND` even when no such net exists; no config is the same as the example | ground derived from IC ground pins; warns when configured ground nets are absent or have no copper, when there is no config, and while the starter is in use |
| `common.cls` | unmatched nets fall to "slow" unseen | `cls_how` says how each net was classed; emc.md lists the slow ones, longest first |
| `emc.py` | configured hot loops whose IC or nets are missing skipped; caps beyond 15 mm skipped; `switch` absent from fast_classes unnoticed | `NOT CHECKED` / `FAIL` rows and warnings; derived loops for uncovered switching ICs; warning |
| `planes.py` | layers with no ground silently empty; slot list truncated at 25 silently | warnings |
| `power.py` / `report.py` | no power runs -> power.md with no DC section and no word about it; empty tables with no "none" | explicit "No DC runs in this pack", "none" lines |
| `make_pack.sh` | a failed DRC (no refill) swallowed; ERC failure swallowed; first `*.kicad_pcb` taken | warnings; board picked by `.kicad_pro` name, ambiguity stops |
| `check.sh` | nc_audit crash swallowed (`2>&1 || true`); notes never passed; any stderr line with "traits" dropped | failure reported and exit status kept; notes discovered; only the exact assert dropped (at the source) |
| `nc_audit.py` | symbol-NC pins exempt; straps only recognised by rail name | NC pins need notes; supply-pin structure also counts |
| `schgen.py` | `Datasheet` written as "" when the call gave none, ignoring the library | precedence chain; raises on a BOM part with none |
| `region.py` | only a zone's first outline polygon listed | every outline |

Not changed: `netdigest.kind()` still uses power-pin types plus names to split power from signal nets in netlist.md
(display only); `view.py` colours nets containing "GND" grey (cosmetic); `fem.py` grid artefacts are documented, not
detected beyond the existing absurd-drop warning.

### Test runs

- `kicad_sexpr/tests/run.py`: 43 passed, 2 skipped before; after R22 two writer tests failed (their test parts had no
  datasheet or LCSC, which schgen now refuses); the tests now give those parts sourcing data, 43 passed, 2 skipped.
- New: wf `scripts/tests/` (board_diff, fields_carried, project_inputs, refparts, skills_rev), rev `scripts/tests/`
  (topology, pack_synthetic), psu `scripts/tests/` (path_budget): all pass (`python3 <file>`; pack_synthetic uses the
  analysis venv).

## Left open, and why

- **Hot-loop solve is DC**: it finds a return forced through one via, not loop inductance. Box is the IC and cap
  pads + 5 mm; a return path longer than that is not modelled (it would itself be a finding).
- **Derived hot-loop candidates over-list** (e.g. U2's VBUS, BAT and REGN as well as PMID): each is labelled
  "derived, confirm against the datasheet". Choosing the one true loop needs the topology the netlist cannot give
  (which pin is the rectifier output) - the datasheet layout section decides.
- **refparts.py** matches two-terminal parts between two nets; a series RC snubber is two entries (R between SW and an
  internal node, C from that node to ground) and the internal node must be named with `net:`. Distances are
  centre-to-centre.
- **path_budget.py** models a series chain feeding one node; a tree (separate rails off different points) needs one
  file per branch. Cell and wiring resistance and the load capacitance in the minipc example are assumptions.
- **partfields.py --online** proves a link loads and names the part (MPN/value, or the LCSC page of the part's own
  number); it cannot prove a PDF is the right revision. Manufacturer URLs are not derived automatically (only TI's
  symlink pattern was verified); give them explicitly.
- **minipc-power's own generators** (its `tools/schgen.py`, `symbols.py`, board pipeline) were not changed; with the
  skill's `schgen.py` its generator runs unchanged apart from the datasheet fill.

## For minipc-power's own docs (not changed here)

- skill-gaps.md: gaps 34-46 addressed on kicad-skills `review-gaps` (this file); R16-R22 to add to its rules table.
- Use `partfields.py check` in `tools/build_board.sh` (or `check.sh`, which now runs it); switch `tools/schgen.py` to
  the skill's (or port `carried_fields`), give U-parts their manufacturer datasheet URLs explicitly (TI symlink for
  the TPS/BQ parts), and carry Datasheet in the board writer.
- Add `kicad-skills.lock` and the `assets/kskills.py` checks to `tools/kskills.py`; keep `pin-decisions.json`,
  a `reference-parts.json` per converter and the review's `review_config.json` in `docs/`.
- pin-decisions.json needs entries for U2.2, U3.4 (NC) and the new state of U5.11/12.
- review-2026-10-24.md: the pack's hot-loop solve also flags U2's C2 (VBUS) and C6 (BAT) ground returns through a
  single via, and U4's C12 (VCC) at 63 %; not in the review. `docs/layout-refs/*/` has no INDEX.md (`datasheet.py index`).
- power-design.md s8 and requirements s4: the 5.6 A figure, re-derived with `path_budget.py` and the board's actual
  cell and wiring resistance.

---

# Round 3: heat (a review area with no required output)

Source: the owner looked at minipc-power (commit 947e64b: 52 x 36 mm, 4 layers, closed plastic box, 50 C design
ambient) after its kicad-board-review, saw almost no stitching vias and asked whether heat had been analysed. It had
not. Branch `thermal` from origin/main 8dcd3da. As in rounds 1 and 2 the class was fixed, not the instance; minipc-power
appears only as labelled examples and as the before-case test, run on scratch copies of its git objects (the
minipc-power repository was not touched).

## What was missed, and the class behind it

- The review never built a heat-source table. The checklist's s2 "Heat sources" was one prose line with no output;
  `analysis-limits.md` said "No thermal model ... temperature rise needs judgment"; no script produced a number, so the
  area was passed over without anyone deciding to skip it.
- The design notes added up converter losses only (about 1.1 W at the 15 W budget). At 15 W from an empty 3.0 V cell
  the solved battery current is 6.6 A, and the series path - three CSD13202Q2 FETs (10.4 mOhm max at Vgs 3 V, x1.4 hot),
  the BQ25606 BATFET (19.5 mOhm), the fuse and the copper - dissipates about 3.3 W on the board, three times the
  converters. The loss was where no tool was looking.
- The pack had measured poor ground stitching (6 vias within 3 mm of a 174 mm perimeter, edge gaps of 57/42/41/19 mm,
  two F.Cu ground islands with one via each) and nothing reported it, for EMC or for heat.

| Class | Rule |
|---|---|
| A checklist area with no required output and no tool is skipped silently; judgment stands in for a number | **R23 (new)** Every checklist area produces a recorded output; an area without one is reported NOT CHECKED, never as fine |
| Losses summed where a tool already existed (converters) and not along the series path the operating point flows through | R20, extended from the operating point to its heat |
| An unknown loss left out of a total instead of shown as unknown | R16 |
| A measurement filed under one concern only (stitching as EMC, never as a heat path) | R23 (the heat area's output includes the pours and stitching under hot parts) |

## Rules and where each one now lives

| Rule | Canonical statement | Also applied in |
|---|---|---|
| R23 Every checklist area produces a recorded output | rev `SKILL.md` s3 ("Every area produces a recorded output") | rev checklist intro and the **Output:** items in s2, s3, s9; `thermal.py` reports "heat NOT CHECKED" as a high finding when no losses are configured; rev SKILL.md s6 (each area's output in the report, NOT CHECKED areas listed); reviewer-brief 4b |
| R16 (applied) | as round 2 | `heat.py`: every candidate heat source (by structure) is listed, UNKNOWN when it has no entry or no input at a corner; `thermal.md` coverage first |
| R20 (extended) | psu `SKILL.md` "Operating points are solved" + step 8 "Losses and temperature" | `path_budget.py` prints the path's own loss next to the converters' and writes `--json` for the heat table; rev checklist s2; bat protection-and-safety.md "The battery path is a heat source", verification.md |
| R2 / R18 (applied) | as before | h, ambient, the board limit and every assumed input are named in the coverage; `thermal.md` "Findings, ranked" (high / medium / info) |

## Gap -> change -> verification

| Part | What changed (files) | How it was verified |
|---|---|---|
| Heat-source table | rev `scripts/heat.py` (new): kinds i2r (R x hot factor, current given / from a power run / from `path_budget.py --json`), converter (P_out x (1/eff - 1), inductor share subtracted), linear, fixed, copper (a power run's loss scaled by (I/I_run)^2), path (one row per solved path element with a `ref`), negligible (needs a reason), unknown; per-corner values; candidates by structure (ICs, FETs, inductors, fuses, diodes, beads, resistors <= 1 ohm, power-run ends); groups and conduction vs conversion. Config in `review_config.json` "thermal" (no new file: found by the same projfiles convention; make_pack records where it came from in `.config_source` so relative `path_budget` files resolve). psu `path_budget.py`: `ref`, `off_board`, path loss (on board) vs converter loss per corner, `--json`. topology.py starter config gets a thermal section with every candidate UNKNOWN | Synthetic (below): every loss equals its hand value. psu `test_path_budget.py` new test: path loss = I^2 x R (board share without off-board elements), converter loss, refs in the JSON |
| Thermal model | rev `scripts/thermal_model.py` (new, pure numpy/scipy): one node per cell per copper layer, copper k t joined only within one net (a clearance gap does not conduct), half the adjacent FR4 in-plane, FR4 through-plane per cell, via barrels between the layers where each lands on its own net, h on both faces, optional part-body nodes. rev `scripts/thermal.py` (new): rasterises the board's copper per net (0.3 mm cells, 3x3 supersampled), places each part's heat on a body node joined to its pads (the board decides which pad takes it), copper loss along each run's own loss map (`fem.py` now returns where the loss sits; `power.py` saves `maps/<run>_loss.npz`), solves every corner at low / nominal / high h, reports the board average P / (A (h_top + h_bottom)) beside the solver's mean, the peak, each part's board temperature and Tj (psi_JB or theta_JC), limits, the bare board's time constant, maps. `make_pack.sh` runs it every time | `tests/test_thermal_model.py` (analytic): uniform plate q/2h exact (rtol 1e-7); point source on a 300 mm copper plate vs Q/(2 pi k t) K0(r/lambda): 0.5 % at r = 3 mm, 0.02-0.3 % at 5-80 mm; FR4 slab drop q d / k exact; one 0.3 mm via over 1.6 mm = 220 K/W, solver within 1 %; energy balance; a body node's heat leaves through the cooled pad only. On minipc and the synthetic board the solver's mean face rise equals P / 2Ah within 0.3 % at every corner and h |
| Thermal vias and stitching for heat | `thermal.py`: every pad >= 1 mm^2 and >= 2x its footprint's median (exposed pads, drain tabs): vias in and beside it, barrel resistance to the nearest landed plane, the drop at the part's worst loss, the datasheet pattern from `thermal.pads` or a rule of thumb, and "this net has no copper on any other layer" where vias could land on nothing; per hot part, each pour it sits on with its vias, its FR4 and the solved step to the layer below (flagged only where the step is >= 3 K); weakly stitched ground pieces with the parts on them, a heat finding when one carries a hot part; edge stitching as planes.py measured it; a what-if solve with ground vias on a grid wherever the outer ground pour leaves room. `boarddump.py` writes via type names (the enum's numbers differ: THROUGH is 4 in KiCad 10). `rect_dims` moved to `common.py` | Synthetic: a regulator tab on a +5V pour that exists on no other layer (flagged, FR4-only, 76 K step), a QFN pad with 4 vias against 9 (flagged), a FET on a ground island with one via (heat finding), the what-if adds vias. minipc below |
| Pack, checklist and SKILL text | rev checklist s2 (heat-source table and temperatures as **Output:** items, series path explicitly), s3 (stitching output; stitching for heat), s9 (thermal vias output); analysis-limits.md (the model's limits instead of "no thermal model"); interpreting-results.md ("Will it get hot? / more stitching?"); reviewer-brief 4b; rev SKILL.md s2/s3/s6; example config "thermal"; psu SKILL.md (path loss checkbox; step 8 heat table, battery path called out), psu layout.md s6 (vias move heat only to their own net; the board-average check before layout); bat protection-and-safety.md, verification.md; README tools | Text; every number in an example traced to the minipc run or to arithmetic |

### minipc-power (947e64b), before and after

Pack built with this branch's `make_pack.sh` from a scratch copy of 947e64b (inner copper as the file says, 15.2 um;
power runs at 17.5 and 35 um, the worse of each used).

**Before** (the review's own `review_config.json`: power runs, no "thermal"): `thermal.md` now says
`high: heat NOT CHECKED: no losses are configured (20 candidate heat sources UNKNOWN)`, lists D1, F1, J1, L1-L4, LED1,
Q1-Q6, U1-U6 as UNKNOWN, and reports the stitching the pack had measured and nobody used: 48 ground vias (2.6 per
cm^2), 6 within 3 mm of the edge on a 174 mm perimeter, gaps 57 / 42 / 41 / 19 mm, two F.Cu ground islands (7.9 and
3.1 mm^2) with one via each, carrying only capacitors (C18, C1).

**With the thermal inputs the review should have had** (`tests/data/minipc_thermal.json`: datasheet values, the
WEBENCH efficiencies, the path current solved by `path_budget.py`; assumed values marked):

| Corner | Total | Battery path | Converters (+ inductors) | Charger | Board average rise at h 5 / 7 / 10 | Peak rise (where) at h 7 |
|---|---|---|---|---|---|---|
| 15 W from an empty 3.0 V cell (6.6 A solved) | 4.38 W | 3.27 W (Q1-Q3 0.63 W each, BATFET 0.85, F1 0.22 assumed R, copper 0.30) | 0.76 W (+0.23) | - | 234 / 167 / 117 K | 240 K at Q2 |
| typical 6.5 W, 3.6 V cell (2.05 A) | 0.81 W | 0.32 W | 0.45 W | - | 44 / 31 / 22 K | 39 K at U4 |
| 9 V in, charging 1.44 A while running | 2.05 W | 0.16 W | 0.45 W | 1.21 W (U2 buck) + 0.16 (L1) | 110 / 78 / 55 K | 106 K at U2 |

- At 50 C ambient: the 15 W empty-cell corner is far past every limit (board average 218 C at h 7; Q1-Q3 Tj about
  290 C) - the total loss is too much for 19 cm^2 of board in still air, whatever the copper; the bare board's time
  constant is about 4 min, so a 15 W burst shorter than a minute or two does not reach it. Typical use is fine (board
  about 80-90 C, every Tj under its limit). Charging while running puts U2 at about 155 C board / 166 C Tj at h 7, past
  its 110 C thermal regulation: the charge current will fold back in the box. U4, U5, U6 exceed their 125 C recommended
  Tj in that corner too.
- Locally, Q1-Q3 sit 61-72 K above the board average at the 15 W corner: their pours (Net-(U3-VSS) 13.2 mm^2,
  Net-(Q2-D-Pad1) 10.2 mm^2) exist on no other layer, so no via can reach a plane of their net; heat crosses 0.21 mm of
  prepreg with a solved 15-19 K step. Net-(J3-Pad1) has one via (10 K step).
- Ground stitching: 64 virtual ground vias at 3 mm pitch change no hot part by more than 0.5 K. On this board the In1
  ground plane is 0.21 mm under the F.Cu ground pour everywhere, so stitching is not what limits the temperature;
  the loss, the area and the enclosure are. The edge gaps remain an EMC finding (checklist s3), now reported.
- Thermal vias: U2 (BQ25606) 9 in the exposed pad, rule 9, ok; U5 (TPS61088-Q1) 8, the datasheet's RHL0020A land
  pattern (p33) shows 8 x 0.2 mm, ok (the rule of thumb alone would have asked for 10); Q4/Q5 source pads on nets with
  no copper on other layers (flagged, low: 0.03 W).

The two minipc checks are `tests/test_thermal_minipc.py` (run with `MINIPC_PACK=<pack>`; skipped otherwise, since
the board lives in another repository).

### Synthetic board (unlike minipc-power)

`tests/test_thermal_synthetic.py`: 80 x 50 mm, 2 layers, 12 V: an LDO (12 -> 5 V at 0.3 A = 2.1 W, linear kind) whose
tab pour is a net on no other layer, a QFN buck (converter kind, L1's loss subtracted) with 4 of 9 pad vias, a 50 mOhm
shunt (i2r from a corner current), L1 from `path_budget.py --json` (an off-board cable element ignored), a FET on a
one-via ground island, an unconfigured diode and a copper run the pack does not have. Every loss matches its hand
value; D1 and the missing run are UNKNOWN in the table and the coverage; mean face rise = P / 2Ah (0.5 %); low h is
hotter than nominal, nominal than high; the regulator's Tj is over its limit; the tab, the via shortfall, the
FR4-only pour and the hot part on the weak island are reported; with no "thermal" section every candidate is UNKNOWN and
the vias are still measured.

### Test runs

- rev `scripts/tests` (`python3 -m pytest -q tests`): 10 passed, 2 skipped (the minipc tests, without `MINIPC_PACK`);
  with `MINIPC_PACK` set to the full pack, 12 passed. The analytic model tests run under the analysis venv (plain
  python3 has no scipy: pytest re-runs the file under it); run directly they report 6/6.
- psu `scripts/tests`: 4 passed. wf `python3 -m pytest -q kicad_sexpr/tests tests`: 53 passed, 2 skipped (unchanged).
- End to end: `make_pack.sh` on the scratch project with the thermal section in its `docs/review_config.json` and the
  path results beside it: 2 min 19 s in all, `thermal.py` about 18 s; via types read by name (no false blind-via
  warning), path files resolved next to the config, numbers identical to the step-by-step run.

## Left open, and why

- **No enclosure model.** Ambient is the air around the board; the box's own rise and the walls are folded into h. A
  box model (air node, wall conductance, outside ambient) is the next step if the owner wants absolute numbers.
- **Heat through wires, cells and screws** is not modelled; on a small board with 18 AWG battery wires it is a real path,
  so the board numbers are pessimistic. Steady state only (the time constant is reported instead).
- **Converter input currents per corner** (the inductors' I^2 R) are given by hand in the minipc fixture; the heat
  table does not derive them from the path's node voltage.
- **Junction estimates** use psi_JB / theta_JC from the datasheet on the model's pad temperature; parts without either
  get the board temperature only (said so in the table).
- **Diagonal tracks** across cells conduct less than they should (4-neighbour grid); pours and planes are unaffected.
- **Fuse cold resistance** in the minipc fixture is assumed (5 mOhm), marked ASSUMED in the table and the coverage.

## Disagreements with the brief

- **h defaults** are 5 / 7 / 10 W/m^2K (low / nominal / high), inside the brief's 5-10, with open air (10-15) noted.
- **Edge stitching is not a heat path**: it is reported in `thermal.md` as the pack measured it, labelled as an EMC
  finding; the heat question about stitching is answered by the pours table and the what-if (on minipc: no effect).
- **A 0.3 mm via is about 220 C/W at 20 um plating**, slightly above the checklist's old "100-200 C/W"; the checklist now
  gives both.

## For minipc-power's own docs (not changed here)

- Add the "thermal" section (the fixture is a starting point) and the two path specs to `docs/`, and fix the fuse's cold
  resistance from the Littelfuse datasheet.
- power-design.md s8 adds converter losses only; add the battery path (about 3.3 W at the 15 W empty-cell corner).
- The 15 W budget at an empty cell is not thermally sustainable in a closed box (and trips the BATFET, round 2): a
  firmware power limit at low cell voltage, a bigger board or airflow. Charging while running will fold back charge
  current in the box (U2 at its 110 C regulation): expected, but slow charging should be documented.
- Q1-Q3 pours have no copper of their nets on any other layer: enlarge them, or add B.Cu copper of those nets with vias.

---

# Round 4: availability, coupled values and approved decisions (protection FET re-selection)

Source: minipc-power, 2026-10-25. The battery-protection FETs (Q1-Q3) were re-selected to cut heat. A search with
`jlcimport-cli search` and no `--region` (its saved default on that machine: `cn`) showed the Vishay SiSS80DN (C3289423)
with 12,000 in stock; its datasheet and footprint were checked, the user approved it, and the protection block was
laid out around it. Only `bom_check.py` at the end (which passes `--region global`) found 0 in the warehouse
international JLCPCB buys from. The block was redone around a Diodes DMN1004UFV (C316138, 317 in global stock) with
about 2.5x the R_DS(on); the protector senses over-current as I x (R_Q2 + R_Q3), so the trip moved, the protector
variant picked for the SiSS80DN (75 mV) would now trip below the 15 W peak, and it was being re-chosen without asking
the user, who had settled the protection values. Three tool bugs surfaced on the way (below). Branch `availability`
from `thermal` (5143b79). minipc-power was read from git only (scratch copies of HEAD d2f7dcd); it was not modified.

## Classes, and where they differ from the brief's reading

| Class | Rule |
|---|---|
| A context-dependent fact (stock, price) looked up without its context; the context (assembler, region) lived nowhere, hard-coded in two scripts and left to a third-party default on the path actually used at selection | **R24 (new)**, applying R3, R13 and R21 |
| A value computed from one part's parameters keeps the old part's number after a swap; nothing links the value to the part | **R25 (new)** |
| A change forced by circumstances treated as licence to change approved decisions, and its cascade done as follow-up fixes | **R26 (new)**, generalising R10 and R2 |
| A config entry naming a design object that the design renamed (KiCad's auto net names follow pads) crashes the tool | R16 (coverage: report it by name) |
| An exemption made for one rule leaks into another (same-net skip in clearance also skipping "no via on a pad") | R8's cousin: an exemption belongs to the one rule it was made for |
| A summary line printing two counts swapped | (test now asserts the exact line) |

Where this differs from the brief:
- **The region default was the trigger, not the root.** `bom_check.py` and `part_gate.py` already passed `--region
  global`; the selection itself went through a hand-typed search, so the scripted gate was not on the path where the
  decision was made, and the region was not project data anyone could read. The fix makes the project's sourcing
  context a file with one owner (R13), makes every lookup - including the free-text search used while browsing -
  go through it (`sourcing.py search`), and refuses to run without it (R21: no third-party default stands in for a
  fact that depends on context). Making the skill text say "always pass --region" alone would have left the region
  in the agent's memory instead of the project.
- **The gate also could not take the candidate as found.** `part_gate.py` matched device names only; a C-number from
  a search could not be gated. It now takes C-numbers.
- **R25 is checked, not only written.** A dependency note in a design doc goes stale the same way the value did. The
  record is JSON (`design-values.json`), `derived_check.py` compares it against the schematic's parts, and
  `bom_check.py` - which is what runs after any part change - runs it.
- **R26 is a new rule rather than an edit of R10** because R10 lived in the layout stages only and is about
  feasibility; the failure here was in part selection, and the new point is that a forced change is still a new
  decision and its whole cascade is one question to the user.
- **The via bug is a class in the skills too, and the cheaper catch is downstream.** kicad-skills' `router.py` had the
  same gap (verified: `via_near` put a via in the centre of a neighbouring same-net pad). It is fixed there, and
  `board_lint.py` now reports VIA IN PAD on any board, so a project's own router - where this one actually happened -
  is covered too.

## Rules and where each one now lives

| Rule | Canonical statement | Also applied in |
|---|---|---|
| R24 Availability is a fact about (part, the assembler's warehouse region, quantity, date): the project states its sourcing context once, every lookup reads it and names the region, no third-party default, checked for every candidate at selection before approval or layout | ps `SKILL.md` "Availability is a fact about one warehouse" | `sourcing.py` (new), `part_gate.py`, `bom_check.py`; `projfiles.py` (sourcing.json, 3 copies); `preflight.py --project` (both copies); nb SKILL step 6/8, interview-guide s6/s8, requirements template s6/s8; psu SKILL checklist; wf SKILL s1 and mistakes, layout-stages point 5 and stage 1; rev checklist s8 **Output**, reviewer-brief 7; README |
| R25 Every derived value records the part parameters it came from; a swap re-derives each dependent, and the review re-checks them | ps `SKILL.md` "Deriving values" | `derived_check.py` (new), `bom_check.py`; psu SKILL checklist, step 3 (variants), step 4, step 8; bat protection-and-safety.md (trip belongs to the FETs); rev checklist s7 **Output** |
| R26 Approved decisions are frozen; changing one (forced or not, with its cascade) goes back to the user with evidence, consequences and options before any edit | wf `SKILL.md` "Approved decisions are frozen" | ps SKILL "Substituting a part the user approved" (procedure); wf layout-stages point 4, SKILL s1 and mistakes; nb SKILL "Never decide silently", requirements template s9 ("Agreed by user"); psu SKILL step 3; bat protection-and-safety.md; rev checklist s8; `derived_check.py` (approved values) |
| R16 (applied) | as round 2 | `power.py` NOT RUN runs in power_runs*.json, power.md coverage and table, thermal.md coverage; `derived_check.py` coverage line; `bom_check.py` says when there is no design-values.json |

## Gap -> change -> verification

| Gap | What changed (files) | How it was verified |
|---|---|---|
| Stock looked up in the wrong region | ps `scripts/sourcing.py` (new: `show`, `init`, `search`, `stock`; `resolve()` stops with neither sourcing.json nor --region; every row tagged with region and currency; a short part's other-region stock shown as not counting), `part_gate.py` (region and need from sourcing.json, C-numbers exact, other region beside a short part), `bom_check.py` (header line with assembler / region / quantity / date / source, stock policy and named exceptions, region and date in --json), `projfiles.py` x3, `preflight.py` x2 (sourcing.json required for the parts skill; reports jlcimport's saved default when it differs) | Real lookups, 2026-10-25: `jlcimport-cli search C3289423 --region global` -> stock empty (0), `--region cn` -> 12000; without `--region` -> 12000 (this machine's `jlcimport.json` says `"region": "cn"`). C316138: 317 in both. `part_gate.py C3289423 C316138 SISS80DN BQ25606 --per-board 3` in a scratch project with global: `C3289423 ... 0 in stock ... <-- STOCK 0 < 17 in global [cn has 12,000 - does not count: JLCPCB buys from global]`, C316138 317 ok, BQ25606 ACTIVE 8,190. Without sourcing.json every script stops with how to create it, before any lookup. `preflight.py --project`: "sourcing.json: JLCPCB, region global; jlcimport-cli's default region is cn (...jlcimport.json)" |
| bom_check summary swapped | `bom_check.py` rewritten into functions; summary from the rows | minipc HEAD copy: `57 unique LCSC parts, 0 with problems, 38 extended, 0 without a datasheet link, 0 parts without an LCSC number` (the old line printed "0 extended, 38 without a datasheet link"). With Q1-Q3 set to C3289423: `C3289423 3 0 ... STOCK 0 < need 17 (global), extended [cn has 12,000 - does not count: JLCPCB buys from global]`, exit 1 |
| Coupled values not re-derived after a swap | ps `scripts/derived_check.py` (new: `check`, `deps`; STALE names the parameter and number to re-read; approved values point to R26; coverage of ICs/FETs/inductors/fuses no value names), `bom_check.py` runs it | minipc HEAD copy (Q2/Q3 = DMN1004UFV C316138) with a design-values.json recording the protector trip as derived from C3289423 (approved): 2 STALE lines (Q2, Q3) each "Re-read 'R_DS(on) max at Vgs 2.5 V' from the new part's datasheet ... User-approved value: take the re-derived result to the user before changing anything (R26)"; `deps ... U3` lists the trip with its VDIP input |
| Approved decision changed silently | Text: R26 (above) | Text |
| power.py crash on a renamed net | rev `power.py` (`run_problems`: net has copper, parts and pads exist and are on the net, a renamed net names where the pads are now; solver errors caught per run; `not_run` in the JSON), `fem.py` (clear error for a net with no copper), `report.py`, `thermal.py` | Synthetic pack, run `net: Net-(J3-Pad1)` on a board where its pads are on VSYS: the thermal-branch `power.py` -> `ValueError: cannot convert float NaN to integer`; new -> `power run renamed NOT RUN: net Net-(J3-Pad1) is not on the board; the run's pads are now on: C1:1 -> VSYS, R1:1 -> VSYS (renamed after a part change? update "net" in review_config.json)`, exit 0, other runs solved: `tests/test_pack_synthetic.py` |
| Via in a neighbouring same-net pad | wf `router.py` (`pad_problem`: no via on or within 0.05 mm of a same-net pad unless `in_pad=` names it; via/via_field/via_near), `board_lint.py` (VIA IN PAD; exposed-pad vias as NOTE), routing.md, checks.md, check.sh, SKILL s3 | Synthetic FET with three same-net source pads: thermal-branch `router.py` `via_near('Q2','2')` -> (10.0, 10.0), the centre of Q2.1; new -> a spot touching no pad; `via((11.3,10),'SRC')` REJECTED naming Q2.3, accepted with `in_pad=('Q2','3')`; a via field on an exposed pad needs `in_pad`: `tests/test_router_checks.py`. board_lint on a generated board (via on R1's ground pad, one clear, one in a QFN exposed pad): 1 VIA IN PAD, 1 NOTE, exit 1: `tests/test_board_lint_vias.py` |

### minipc-power (HEAD d2f7dcd), found by the new checks

- `board_lint.py`: 4 VIA IN PAD - ground vias beside C17.2, C18.2, C19.2 and C31.2 whose annular ring overlaps the pad
  (C19: via centre 0.15 mm outside the pad edge, so the 0.3 mm drill's edge sits on the pad edge; no mask web between
  them). 1 NOTE: one via in U1's exposed pad (order it filled or tented). Not fixed here (another repository).
- `bom_check.py`: everything in stock in global for 5 boards; 38 of 57 parts Extended.

### Audit: config entries that name design objects

| Where | Entry | On a missing object |
|---|---|---|
| `review_config.json` power_runs | net, source/sink pads | was: crash (NaN) or an assert ending the batch; now: NOT RUN with reason |
| `review_config.json` hot_loops | IC, nets | NOT CHECKED (round 2) |
| `review_config.json` thermal | refs, power runs | UNKNOWN / "not in the pack" (round 3) |
| `pin-decisions.json`, `reference-parts.json` | refs and pins | reported by nc_audit / refparts (rounds 1-2) |
| `design-values.json` | refs and parts | STALE (new) |
| `sourcing.json` exceptions | LCSC numbers | bom_check notes exceptions no longer in the BOM (new) |

### Test runs

- ps `scripts/tests` (new; `python3 -m pytest -q tests`): 8 passed, 1 skipped; with `LCSC_LIVE=1` 9 passed (the live
  test asserts C3289423 is 0 in global and stocked in cn, and C316138 is stocked in global). The fake jlcimport-cli
  exits 3 on any search without `--region`.
- wf `python3 -m pytest -q kicad_sexpr/tests tests`: 55 passed, 2 skipped (was 53 / 2; new: `test_router_checks.py`,
  which reruns itself under the analysis venv for shapely, and `test_board_lint_vias.py`, which needs KiCad's python).
  The router + DRC pipeline test in `test_writers.py` still passes with the pad check in `via_near`.
- rev `python3 -m pytest -q tests`: 11 passed, 2 skipped (was 10 / 2; new: the NOT RUN test in
  `test_pack_synthetic.py`; the 2 skips are the minipc thermal tests without `MINIPC_PACK`).
- psu `python3 -m pytest -q tests`: 4 passed (unchanged).

## Left open, and why

- **Assemblers other than JLCPCB/LCSC**: `sourcing.json` names the assembler, but the lookups are LCSC only; another
  assembler's stock is "check by hand" (said in the docstring).
- **design-values.json is written by hand.** Nothing infers which values depend on which parts; the coverage line
  lists ICs, FETs, inductors and fuses no value names, as a prompt. Values computed in a project's own generator could
  write their records there.
- **Approvals are recorded, not enforced.** R26 is a rule for the agent; `derived_check.py` marks approved values and
  the requirements template has an "Agreed by user" column, but no tool can tell that a change was discussed.
- **Price currency** is per region (USD global, CNY cn, as jlcimport reports it); prices are not converted.
- **board_lint's exposed-pad test** (>= 1 mm^2 and >= 2x the footprint's median pad) is a heuristic; a big pad that
  is not a thermal pad gets a NOTE instead of a problem.

## For minipc-power's own docs (not changed here)

- Add `docs/sourcing.json` (JLCPCB, global, 5 boards) and a `docs/design-values.json` with at least the protector
  trip (inputs: Q2, Q3 R_DS(on) at the cell's minimum gate drive, hot; U3's threshold variant), the EN/UVLO dividers,
  the inductor I_sat margins and the heat estimates, marking the values the user approved.
- Move the 4 ground vias off C17/C18/C19/C31's ground pads (or keep a mask web), and order U1's exposed-pad via
  filled or tented.
- skill-gaps.md: R24-R26 to add to its rules table.
