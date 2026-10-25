---
name: pcb-part-selection
description: Choosing, verifying and sourcing electronic components for a KiCad board assembled at JLCPCB/LCSC (or similar) - finding parts, checking stock and assembly class, reading the datasheet for limits, variants and required external parts, deriving component values from datasheet equations, importing symbols/footprints/3D models, and sweeping the whole BOM before an order. Use it whenever a part is added, swapped or questioned ("what regulator should I use", "is X in stock", "find a replacement", "why is JLC rejecting my BOM"), when calculating divider/inductor/capacitor values from a datasheet, and before any board order.
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
`scripts/part_gate.py <names...>` does the lifecycle (TI product pages; other vendors: check by hand) and LCSC stock per
exact variant in one command; `--from-text` takes pasted text such as a design tool's results table.

Statements in these skills about third-party sites and tools (JLC, LCSC, TI, WEBENCH, jlcimport) carry the date they
were checked. Treat them as hints about where to look: discover the current behaviour (read the page, run `--help`),
and update the skill text when it has changed.

## Finding candidates

- **Switching regulators: run the requirement through the vendor's design tool before settling on a part or sizing by
  hand** (TI WEBENCH: the pcb-power-supply skill's checklist and `webench.md`), then gate its picks. Chargers are not
  covered by WEBENCH; use their datasheets.
- **Gate every candidate** with `scripts/part_gate.py` before spending design time on it.
- Search LCSC/JLC with JLCImport's CLI (`https://github.com/jvanderberg/kicad_jlcimport`; install below):
  `jlcimport-cli search "<keyword | MPN | C-number>" --region global [-t basic|extended|both] [--min-stock 1000] [--csv] -n 15`
  Basic parts search badly by value; search a family part number (e.g. UNI-ROYAL `0402WGF1003TCE` for 0402 1 %
  resistors). Many descriptions are Chinese (升降压 = buck-boost, 降压 = buck).
- Prefer the plentiful variant when choices are equivalent (an automotive-grade version with many times the stock for
  a small premium is often the better buy). Ask the user when the trade-off is real.
- Check stock **in the region the assembler buys from** (global JLC warehouse vs `--region cn`); they can differ by
  orders of magnitude, and pre-order/consignment from the other side is sometimes the way out.
- Check the assembly class: `curl -sL -A 'Mozilla/5.0' https://jlcpcb.com/partdetail/<C-number> | grep -o 'Economic and Standard\|Standard Only'`.
  "Standard only" parts force the whole order to standard assembly; the same part under another C-number may be
  economic. Each unique Extended part costs a loading fee (about $3) on economic assembly; regulators are almost never
  Basic.
- Packages: no 0201/01005 for economic assembly (0402 is the practical floor). Respect the board's assembly plan
  (e.g. all parts on the top side).

## Reading the datasheet (download it; do not work from memory)

- Download the PDF with `scripts/datasheet.py fetch <url> ds.pdf`: it keeps the file only if it really is a PDF.
  Manufacturer "symlink" URLs and distributor links can return an HTML page (LCSC's `/datasheet/Cxxx.pdf` returns a
  page that links the real PDF; TI's `https://www.ti.com/lit/ds/symlink/<part>.pdf` returned a 404 HTML page for a
  discontinued part, October 2026). Find sections and figures with `datasheet.py find ds.pdf "Layout Example"
  "Figure 12"` (names the page, no per-page grepping) and render them with `datasheet.py page ds.pdf N out.png`; look
  at them. When you save figure pages into the project, name which page holds which figure.
- **Record the lifecycle status** from the manufacturer's product page next to the datasheet (`part_gate.py` reads TI's).
- Extract, with page/section references, before designing:
  - absolute maximum per pin, **including pin current limits**, and the recommended operating range;
  - required external parts and their values (series resistors, pull-ups, bootstrap caps, compensation);
  - the exact variant: suffixes change voltage (3.3 V and 1.8 V versions of the same memory or regulator), mode
    (forced PWM vs auto light-load), grade and package;
  - power-up behaviour (some converters need I2C before their output turns on - unacceptable for the MCU's own rail);
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

## Importing into KiCad

**Prefer standard, verified building blocks over imported ones.** Use KiCad's library footprint whenever the package is
a standard one (chip passives, SOT/SOD, SOIC/TSSOP/MSOP, standard QFN/SON/DFN variants, common connectors, fuses): it
follows one convention, has a courtyard and fab layer, and is maintained. Keep an imported footprint only for a
genuinely part-specific package, and check every imported or suggested one against its source:
`kicad-pcb-workflow/scripts/fpcheck.py FOOTPRINT --package "<LCSC package>" --symbol LIB:NAME` (courtyard, pad count,
body size, symbol pins vs pads), plus the datasheet land-pattern figure for pad sizes and pitch.

`jlcimport-cli import <C-number> -p <project_dir> --lib-name JLCImport --kicad-version 10` adds the symbol, footprint
and 3D model to project libraries. Its CLI had no option to use a KiCad library footprint instead (v1.6.7): assign the
library footprint in the schematic, and treat any automatic footprint match as a suggestion to check - on one board the
matcher proposed a wrong pin count or body size for most of the parts it was asked about. Treat imported parts as drafts:
- symbols often have off-grid pins and every pin typed "unspecified" (ERC noise) - fix pin types and grid, or redraw
  with kicad-pcb-workflow's `symgen.py`;
- footprints may lack a courtyard (`add_courtyard.py`), have silk through pads, or differ from the datasheet land
  pattern - compare pad sizes and positions against the datasheet figure (render with `kicad-cli fp export svg`);
- check pad numbering against the symbol: a KiCad footprint may merge pins into one pad (e.g. FET source pins 5-8 as
  pad "5"), so the symbol must use the footprint's numbers;
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
binary that lacks it.

## Before every order (and after any part change)

`python3 ${CLAUDE_SKILL_DIR}/scripts/bom_check.py <project>.kicad_sch --boards N [--cli path/to/jlcimport-cli]`

It exports the BOM from the schematic and flags parts with no LCSC number, numbers not found, stock below
N boards x count + 10 %, packages below 0402, and Extended parts. Re-run it right before ordering - stock moves daily.
Then check by hand that each LCSC number really is the part
the symbol means (value, voltage, package, pinout): a valid number can still be the wrong part. Parts with no
substitute (polarity-marked inductors, specific crystals, modules) need a plan before the order: a second source,
pre-order, or consignment. If the project has a stock policy (e.g. at least 1,000 listed per MPN) apply it, and list
any user-approved exceptions explicitly.
