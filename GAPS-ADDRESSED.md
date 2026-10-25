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
