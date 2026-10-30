---
name: pcb-part-selection
description: Choosing, verifying and sourcing electronic components for a KiCad board assembled at JLCPCB/LCSC (or similar) - finding parts, checking stock in the assembler's own warehouse region and assembly class, reading the datasheet for limits, variants and required external parts, deriving component values from datasheet equations, importing symbols/footprints/3D models, and sweeping the whole BOM before an order. Use it whenever a part is added, swapped or questioned ("what regulator should I use", "is X in stock", "find a replacement", "why is JLC rejecting my BOM"), when calculating divider/inductor/capacitor/trip values from a datasheet, whenever a part is substituted (re-derive every value that used it), and before any board order.
---

# PCB part selection and sourcing

A part on the board has to be right three ways: **electrically** (it survives and works in this circuit, per its
datasheet), **physically** (footprint, height, assembly side and package the assembler can place), and
**commercially** (in stock now, in the quantity needed, at an acceptable assembly class and price). Skipping any check
below can cost a board revision or an order: a part placed with zero stock, a part with no substitute and a handful of
units left, a 0201 that economic assembly cannot place, a protection design done from memory that the datasheet
contradicts.

## External data is a snapshot about one exact item

Stock counts, lifecycle status, prices, design-tool recommendations and even datasheet values are facts about **one
orderable part number at one moment**. Before building on any of them:
- **Is it the exact orderable item?** A suffix, grade or package variant (-Q1, A/B, R/T reel codes, package letters) is
  a different part with its own datasheet, equations and limits; a stock count for one variant says nothing about
  another.
- **Is it current?** Stock moves daily; parts are discontinued while distributors still hold thousands. Record the date
  with every number you write down, and re-check before ordering.
- **Distributor stock is not evidence a part is still made.** Read the lifecycle on the manufacturer's product page
  (ACTIVE / NRND / LAST TIME BUY / OBSOLETE). A product page that returns 404, or a datasheet link that returns an HTML
  page instead of a PDF, means treat the part as discontinued until the manufacturer says otherwise.
`scripts/part_gate.py <names or C-numbers...>` does the lifecycle (TI product pages; other vendors: check by hand) and
LCSC stock per exact variant in the project's region in one command; `--from-text` takes pasted text such as a design
tool's results table.

Statements in these skills about third-party sites and tools (JLC, LCSC, TI, WEBENCH, jlcimport) carry the date they
were checked. Treat them as hints about where to look: discover the current behaviour (read the page, run `--help`),
and update the skill text when it has changed.

## Availability is a fact about one warehouse (R24)

A stock figure answers "how many of this exact part can **this assembler** buy, **from where**, **today**, against the
quantity this order needs" - not "is the part available". LCSC runs two warehouses with separate stock: `global` (what
international JLCPCB assembly buys from, USD) and `cn` (SZLCSC / JLC China, CNY) (jlcimport-cli 1.6.7 `--help` and
prices, October 2026). The same C-number can be plentiful in one and absent from the other. Example (labelled): a
protection FET (Vishay SiSS80DN, C3289423) showed 12,000 in a search, was approved by the user and the block was laid
out around it; `bom_check.py` then found 0 in the global warehouse the project's assembler buys from. The search had gone to `cn`, because `jlcimport-cli search` takes its region
from its own config when `--region` is missing, and that config is whatever the KiCad plugin's region menu last used.
The layout was redone around a substitute, whose higher R_DS(on) then moved the protector's trip current (below).

So:
- **The project states its sourcing context once**: `sourcing.json` (assembler, region, assembled boards, attrition,
  stock policy, named exceptions), kept where `projfiles.py` finds project inputs (`docs/` works). Create it at the
  manufacturing step of the interview: `scripts/sourcing.py init <project> --assembler JLCPCB --region global`.
  `sourcing.py show` prints what every script will use.
- **Every lookup reads it and names the region explicitly.** `sourcing.py search`, `sourcing.py stock`, `part_gate.py`
  and `bom_check.py` pass `--region` from it, print the region and date on their first line, and stop when there is
  neither a `sourcing.json` nor a `--region`: there is no default. Do not run `jlcimport-cli search` directly; if you
  must, always pass `--region <the project's region>`. Never rely on a third-party tool's default for a fact that
  depends on context (R21).
- **Stock in the other region does not count.** The scripts show it beside a short part, labelled as such, because it
  is exactly what makes an unorderable part look fine. Pre-order, consignment or another part is the way out, and that
  is the user's choice.
- **Check availability at the point of selection, for every candidate, before the user is asked to choose and before
  any layout work.** Present each candidate as: part, LCSC number, stock **with region and date**, need (per board x
  boards + attrition), assembly class, price with currency. A candidate shown without its region is not checked.
- **Re-check at every hand-off** (schematic capture, before layout, before ordering): stock moves daily.

## Finding candidates

- **Switching regulators: run the requirement through the vendor's design tool before settling on a part or sizing by
  hand** (TI WEBENCH: the pcb-power-supply skill's checklist and `webench.md`), then gate its picks. Chargers are not
  covered by WEBENCH; use their datasheets.
- **Gate every candidate** with `scripts/part_gate.py` before spending design time on it.
- Search LCSC/JLC through the project's sourcing context: `scripts/sourcing.py search "<keyword | MPN>" [-n 15]
  [-t basic|extended|both] [--min-stock 1000]` (JLCImport's CLI underneath, `https://github.com/jvanderberg/kicad_jlcimport`,
  with `--region` from `sourcing.json`); `sourcing.py stock C123 C456 --per-board 3` checks exact C-numbers against the
  order need. Basic parts search badly by value; search a family part number (e.g. UNI-ROYAL `0402WGF1003TCE` for 0402 1 %
  resistors). Many descriptions are Chinese (升降压 = buck-boost, 降压 = buck).
- Prefer the plentiful variant when choices are equivalent (an automotive-grade version with many times the stock for
  a small premium is often the better buy). Ask the user when the trade-off is real.
- Stock counts only **in the region the assembler buys from** (R24 above); the other region is information, not
  supply.
- Check the assembly class: `curl -sL -A 'Mozilla/5.0' https://jlcpcb.com/partdetail/<C-number> | grep -o 'Economic and Standard\|Standard Only'`.
  "Standard only" parts force the whole order to standard assembly; the same part under another C-number may be
  economic. Each unique Extended part costs a loading fee (about $3) on economic assembly; regulators are almost never
  Basic.
- Packages: no 0201/01005 for economic assembly (0402 is the practical floor). Respect the board's assembly plan
  (e.g. all parts on the top side).

## Reading the datasheet (download it; do not work from memory)

- **Save every IC's datasheet into the project at selection time** (`docs/datasheets/`, the MPN in the file name)
  with `scripts/datasheet.py fetch <url> docs/datasheets/<mpn>.pdf` (R5: gather the references early). Later phases -
  the adversarial review above all - can only check a pin, a limit or a layout rule against a datasheet they can
  open; a link in a field is not the document. `bom_check.py` reports every BOM IC with no local file.
  `fetch` keeps the file only if it really is a PDF. Manufacturer "symlink" URLs and distributor links can return an
  HTML page: a distributor viewer page is followed to the PDF it embeds (LCSC's `/datasheet/Cxxx.pdf` was such a
  page, October 2026); a refusal (HTTP 403, bot protection) exits 2 with the next step - open the URL in a browser
  (the user's, or browser automation) and save the PDF, or take it from the manufacturer's product page; a 404 page
  for a discontinued part is itself a lifecycle warning (TI's `https://www.ti.com/lit/ds/symlink/<part>.pdf` returned
  one, October 2026). Find sections and figures with `datasheet.py find ds.pdf "Layout Example"
  "Figure 12"` (names the page, no per-page grepping) and render them with `datasheet.py page ds.pdf N out.png`; look
  at them. When you save figure pages into the project, name which page holds which figure.
- **Record the lifecycle status** from the manufacturer's product page next to the datasheet (`part_gate.py` reads TI's).
- Extract, with page/section references, before designing:
  - absolute maximum per pin, **including pin current limits**, and the recommended operating range;
  - required external parts and their values (series resistors, pull-ups, bootstrap caps, compensation);
  - the exact variant: suffixes change voltage (3.3 V and 1.8 V versions of the same memory or regulator), mode
    (forced PWM vs auto light-load), grade and package;
  - power-up behaviour (some converters need I2C before their output turns on - unacceptable for the MCU's own rail),
    and **every pin's default state** (pull-up, pull-down, high impedance, driven) at power-up, in reset and before
    configuration: an interface line between two chips needs a defined level in each state (kicad-pcb-workflow
    `references/new-design.md` s4, R12);
  - **supply current from every table that states it** (R16: a sum says what it summed): search the datasheet for
    "supply current", "Icc", "Idd", "operating current", "except" and per supply-pin group. A device with several
    domains (core, I/O, PHY, analog, an internal regulator) often tabulates each separately, and a table "excluding"
    one domain leaves it to another table. Sum every domain at each operating corner and record the table and page of
    each term in the power budget, with the tables that exclude something named;
  - addresses, strap tables and register semantics (signed vs unsigned, LSB);
  - the layout example and land pattern.
- Derate: capacitor voltage with margin over the maximum (1.5-2x is common practice) and capacitance read from the DC-bias curve - a higher voltage rating in the same case can lose more; resistor power at 50 % or less; PTC
  hold current at the enclosure temperature; FET SOA at real case temperature; inductor I_sat above the converter's
  current limit, not just the load.

## Deriving values

Compute from the datasheet's equations and write the numbers down (in the schematic notes or design doc), then pick
standard values - JLC Basic if possible - and recompute the result with the chosen values. Examples of what this looks
like: an EN/UVLO divider from the threshold and hysteresis current (and the pin's abs max at the highest input); an FB
divider from Vref; a frequency-set resistor; a spread-spectrum capacitor from its modulation equation; an inductor
from ripple and I_sat; a PTC from hold current derating and I_max versus the upstream fuse.

**Every derived value records what it depends on (R25).** A value computed from one part's parameters is right only
for that part, and nothing in ERC, DRC or a stock check notices when the part changes. Coupled values are easy to
miss because they live in another block: a protector's over-current trip is its threshold divided by the FETs'
R_DS(on) (pcb-battery-power `protection-and-safety.md`); a current-limit or sense resistor is sized from a FET or a
shunt; a snubber or compensation network from a switch's or a capacitor's capacitance; a UVLO divider from an IC's
threshold; an inductor's I_sat from the converter's current limit; a temperature estimate from a package's psi / theta
and its copper. Record each one in the project's `design-values.json` (format: `scripts/derived_check.py --help`): the
value, the equation, where it is written out, and per input the ref, the orderable part (LCSC number or MPN), the
parameter and the number used, with its datasheet page; mark `"approved"` when the user agreed to it.
- **Before swapping a part**: `derived_check.py deps SHEET Q2 Q3` lists every recorded value that used it. Re-read
  each parameter from the new part's datasheet (at the same conditions: Vgs, temperature, corner), re-derive, and
  update the record. If nothing is listed but something was computed from the part, record it first.
- **After any part change**: `derived_check.py check SHEET` (bom_check.py runs it) reports every value whose source
  part changed as STALE, with the number to re-read. A swap is not done while any value is stale.
- If a re-derived value no longer meets its requirement (the trip falls below the peak load), the fix (another
  variant, another threshold, another part) changes something the user approved: R26 below.

## Substituting a part the user approved (R26)

A part, threshold or behaviour the user agreed to is a frozen decision (kicad-pcb-workflow `SKILL.md`, "Approved
decisions are frozen"). When it has to change - no stock in the assembler's region, a footprint that cannot be
routed, a lifecycle problem, a re-derived value that now fails - stop before editing anything and bring the user:
1. what changed and the evidence (the stock line with region and date, the failing number);
2. every consequence, from `derived_check.py deps` and the re-derivation: which values move, from what to what, and
   whether each still meets its requirement;
3. two or three options with their costs (a substitute and what else must change with it; pre-order or consignment;
   relaxing the requirement), and a recommendation.
Then wait for the choice. A forced substitution is still a new decision: the cascade it starts (a second part to keep
the trip current, a new threshold) is part of the same question, not a follow-up done silently. Example (labelled):
after the unorderable FET above, the substitute's ~2.5x higher R_DS(on) moved the over-current trip below the 15 W
peak, and the protector variant was being re-chosen without asking; the user, who had approved the protection values,
had to ask why they were changing.

## Importing into KiCad

**A part JLCPCB will assemble gets JLC's own footprint.** `jlcimport-cli import <C-number> -p <project_dir> --lib-name
JLCImport --kicad-version 10` adds its EasyEDA symbol, footprint and 3D model to project libraries. JLCPCB places
every part with that footprint, at the position and rotation in the CPL file, so a board drawn with it gets the
rotation and polarity JLC expects. A KiCad library footprint has to be bridged to JLC's, and that bridge is where
placements go wrong: polarity named differently (A/C pins, `_AK` footprints, "+"/"-" marks on LEDs), pads numbered in
mirror image (resistor arrays such as C25724 and C48442), KiCad's pad-1 convention against JLC's. On test boards with
the same ~900 JLC parts (JLCImport's production-export work, jvanderberg/kicad_jlcimport PR #121, October 2026), JLC's
footprints solved 958 of 962 placements at high confidence, with 4 warnings and no polarity guesses; KiCad library
footprints solved 274 of 852, with 266 warnings and 112 polarity guesses.

A KiCad library footprint is fine where it is an exact geometric match for JLC's: chip passives (0402/0603/0805 R and
C), and any footprint JLCImport's matcher suggests. On a board JLCPCB does not assemble, KiCad's library is the better
default (one convention, courtyards and fab outlines). Check every footprint you assign:
`kicad-pcb-workflow/scripts/fpcheck.py FOOTPRINT --package "<LCSC package>" --symbol LIB:NAME` (courtyard, pad count,
body size, symbol pins vs pads), plus the datasheet land-pattern figure for pad sizes and pitch.

JLCImport's matcher (jvanderberg/kicad_jlcimport PR #122, October 2026) suggests a KiCad footprint only when JLC's
pads fit it within 0.05 mm (same pad numbers, no mirrored numbering, polarity checked) and otherwise keeps JLC's;
v1.6.7 and earlier match by name only, and offered a wrong pad count for 406 of 963 parts, so check what they suggest
with `fpcheck.py`. The suggestion is offered in the plugin's and TUI's import dialogs; `jlcimport-cli import` always
writes JLC's footprint (to use a KiCad one, assign it in the schematic). Treat imported parts as drafts:
- symbols often have off-grid pins and every pin typed "unspecified" (ERC noise) - fix pin types and grid, or redraw
  with kicad-pcb-workflow's `symgen.py`;
- most EasyEDA footprints have no courtyard: add one by rule of thumb with `add_courtyard.py <project_dir>` (every
  project library; kicad-pcb-workflow `references/new-design.md` s5 has the clearances) rather than redrawing the
  footprint. Silk may run through pads. Compare the pads with the datasheet land pattern (render with `kicad-cli fp
  export svg`); fix a real error in place, keeping the origin, rotation and pad numbers JLC places by, rather than
  swapping in another footprint;
- a redrawn symbol, or a KiCad footprint, must use the footprint's pad numbers (`fpcheck.py --symbol`): a KiCad
  footprint may merge pins into one pad (e.g. FET source pins 5-8 as pad "5");
- 3D models can be offset from the pads or missing (`board_lint.py` lists missing files) - check in a 3D render;
- set the `LCSC` field on the symbol so the BOM and the stock sweep find it;
- **keep the imported data when you replace the drawing.** The imported symbol carries the Datasheet link (JLCImport
  writes `https://www.lcsc.com/datasheet/C<n>.pdf`), LCSC number, manufacturer and description. A redraw takes them
  over (`symgen.ic(..., inherit=<the imported symbol>)`), a placed symbol takes its library's values (`schgen`), the
  board takes the schematic's (`new_board.py`), and `partfields.py check` fails the build when any BOM part ends up
  without a datasheet link or with a field that differs between schematic and board (kicad-pcb-workflow
  `SKILL.md`, "Data that exists upstream is carried forward"). Prefer the manufacturer's canonical URL for the exact
  part where one exists (TI: `https://www.ti.com/lit/ds/symlink/<device>.pdf` returns the PDF itself); the LCSC URL is
  the fallback, and it opens a viewer page whose title names the MPN.

**Installing jlcimport-cli** (checked October 2026): `pipx install git+https://github.com/jvanderberg/kicad_jlcimport`
(pipx brings its own recent pip; a system Python 3.9 with pip 21 could not do an editable `pip install -e` of the
repository). The `--region` option the
commands here use appeared in v1.6.0: check with `jlcimport-cli search --help`, and do not use an older prebuilt
binary that lacks it. Without `--region`, `search` uses the region saved in its config (`jlcimport.json` in KiCad's
preferences folder, written by the plugin's region menu; v1.6.7): the skills' scripts always pass it, and
`preflight.py --project` says when that saved default differs from the project's region.

## Before every order (and after any part change)

`python3 ${CLAUDE_SKILL_DIR}/scripts/bom_check.py <project>.kicad_sch [--boards N] [--cli path/to/jlcimport-cli]`

It reads the sourcing context (`sourcing.json`; its first output line names assembler, region, quantity and date),
exports the BOM from the schematic and flags parts with no LCSC number, numbers not listed in the region, stock below
boards x count x (1 + attrition) or below the project's stock policy (unless a named exception covers the part),
packages below 0402, Extended parts, missing datasheet links, ICs with no datasheet saved in the project and stale
derived values (`design-values.json`). Re-run it right before ordering - stock moves daily.
Then check by hand that each LCSC number really is the part
the symbol means (value, voltage, package, pinout): a valid number can still be the wrong part. Parts with no
substitute (polarity-marked inductors, specific crystals, modules) need a plan before the order: a second source,
pre-order, or consignment. If the project has a stock policy (e.g. at least 1,000 listed per part), put it in
`sourcing.json` as `min_stock`, with each user-approved exception named (`exceptions`: LCSC number, reason, who
approved it and when); bom_check applies both and notes exceptions for parts no longer in the BOM.
