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
| R13 One place owns each format and fiddly rule | wf `SKILL.md` (paragraph after the reference list) | wf new-design.md (table of owning scripts); every new script keeps s-expression output in small `*_sexpr()` functions |
| R14 Standard, verified building blocks first | ps `SKILL.md` "Importing into KiCad" | wf new-design.md s5; `fpcheck.py`, `add_courtyard.py` |

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
| 0 s-expression object model | R13 | Not on this branch: handled on the separate `sexpr-model` branch. New scripts keep output in small per-object `*_sexpr()` functions so they can move onto it | - |

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

- **Gap 0** (object model): separate `sexpr-model` branch, by instruction.
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
