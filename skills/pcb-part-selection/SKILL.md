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

## Finding candidates

- Search LCSC/JLC with JLCImport's CLI (`https://github.com/jvanderberg/kicad_jlcimport`):
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

- Download the PDF (`curl -sSL -A Mozilla/5.0 -o ds.pdf <url>`; LCSC's `/datasheet/Cxxx.pdf` returns an HTML page that
  links the real PDF; TI is `https://www.ti.com/lit/ds/symlink/<part>.pdf`). Read with `pdftotext -layout`; render
  figures (pinouts, layout examples, land patterns) with `pdftoppm -r 170 -f P -l P -png` and look at them.
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

`jlcimport-cli import <C-number> -p <project_dir> --lib-name JLCImport --kicad-version 10` adds the symbol, footprint
and 3D model to project libraries. Treat imported parts as drafts:
- symbols often have off-grid pins and every pin typed "unspecified" (ERC noise) - fix pin types and grid;
- footprints may lack a courtyard, have silk through pads, or differ from the datasheet land pattern - compare pad
  sizes and positions against the datasheet figure (render with `kicad-cli fp export svg`);
- 3D models can be offset from the pads - check in a 3D render, especially next to tall parts;
- set the `LCSC` field on the symbol so the BOM and the stock sweep find it.

## Before every order (and after any part change)

`python3 ${CLAUDE_SKILL_DIR}/scripts/bom_check.py <project>.kicad_sch --boards N [--cli path/to/jlcimport-cli]`

It exports the BOM from the schematic and flags parts with no LCSC number, numbers not found, stock below
N boards x count + 10 %, packages below 0402, and Extended parts. Re-run it right before ordering - stock moves daily.
Then check by hand that each LCSC number really is the part
the symbol means (value, voltage, package, pinout): a valid number can still be the wrong part. Parts with no
substitute (polarity-marked inductors, specific crystals, modules) need a plan before the order: a second source,
pre-order, or consignment. If the project has a stock policy (e.g. at least 1,000 listed per MPN) apply it, and list
any user-approved exceptions explicitly.
