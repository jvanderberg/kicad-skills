# Using TI WEBENCH Power Designer from the browser

**What this page describes was observed in October 2026.** WEBENCH's pages, steps and export options change; when a
step below does not match what you see, trust the page, update this file, and tell the user. Discover what the current
page offers (read the page text, list the tabs and export formats) rather than relying on a remembered list.
WEBENCH covers TI's DC/DC converters and controllers; it did not offer battery chargers (TI's BQ25xxx parts), so those
stay with the datasheet's design procedure.

WEBENCH (https://webench.ti.com/power-designer/switching-regulator) turns a requirement into ranked candidate designs
for TI parts, each with a complete power-stage BOM. It is the fastest way to see which controllers fit, what inductor
and capacitors a part wants at your operating point, and roughly what efficiency, area and cost to expect. Use it
through browser automation (Claude in Chrome) when it is available, as a cross-check on your own calculations - not as
a substitute for reading the datasheet.

## What works without an account

1. Open the page. Enter **Vin Min, Vin Max, Vout, Iout Max** (the form fields have those names). "Advanced" sections
   add Vin nominal, Iout nominal and Vout max ripple; "Design Parameters" adds max ambient temperature, max component
   height, soft-start time, minimum package size and switching frequency. Set ambient to the enclosure temperature and
   the minimum package to what the assembler places economically (0402).
2. Choose a priority: Balanced, Low Cost, High Efficiency, Small Footprint.
3. **"View Designs" stays disabled until a box agreeing to TI's WEBENCH Notice, Terms of Use and Privacy Policy is
   ticked. Ask the user before ticking it** - accepting terms is the user's decision.
4. Generation takes about a minute or two ("Generating Designs..."); wait and re-check rather than clicking again.
5. The results page lists every candidate (dozens for a wide-input buck-boost) with efficiency, BOM area, BOM cost,
   BOM count, topology and switching frequency, plus filters (module / converter / controller, efficiency, cost,
   footprint, frequency, ripple, phase margin, package, features such as power good or spread spectrum).
   **Switch to TABLE VIEW and read the page text**: each row then contains the part number, maximum output current,
   efficiency, area, cost, and the full schematic BOM as text - inductor value and DCR, each capacitor's value and ESR
   and quantity, feedback / enable / frequency / compensation resistor values. **That BOM is a secondary source**: it
   can omit parts the datasheet's typical application draws (WEBENCH's TPS61088 design had no 1 uF capacitor at VOUT;
   the datasheet's typical application and layout figure both put one at the VOUT pins). Diff it against the datasheet's
   list (`reference-parts.json`, SKILL.md step 6), never the other way round.
6. **Gate the candidates before customising any of them.** A recommendation is a snapshot about TI's catalogue, not
   about what can be bought: on one run the top three picks had 0, 0 and 13 units at LCSC. Paste the table text into
   the pcb-part-selection skill's gate, which finds the part numbers, reads TI's lifecycle status and lists LCSC stock
   per orderable variant:
   `pbpaste | python3 <pcb-part-selection>/scripts/part_gate.py --from-text --need <boards x per-board x 1.1>`
   Drop anything that fails, then shortlist. **"IC Cost: N/A" on a design is a lifecycle warning** (active parts show a
   price): check the product page; one such part had a 404 product page and no datasheet, while LCSC still listed
   thousands in stock.

## Optional: with the user's myTI login

"Customize" on a design redirects to login.ti.com. Never enter credentials: tell the user what the detailed pages
would add and ask whether they want to log in themselves; if they do, continue in their browser session. Logged in,
there is no terms checkbox (accepted at login), the start form gains a **Use Shielded Inductors** option, and three
more steps open for each design. Read them with the page text (they are long tables); none needs a download.

**Customize** (`.../customize/<id>`)
- *Configuration options*, then **Redesign**: EN/UVLO turn-on voltage, switching frequency, mode (e.g. FPWM vs
  auto), output current limit (this sets the inductor's stress - lower it to the real need), transient spec
  (% Vout for a load step), max output ripple, dithering/spread spectrum, sync frequency.
- *Bill of materials* tab: real manufacturer part numbers for every component with value, voltage, ESR, package,
  price and area, and **"Total Derated Cap"** - capacitance after DC bias (e.g. three 22 uF 25 V 1210 capacitors at
  5 V can show as roughly 50 uF total). "Select alternate part" per line. Use the MPNs as the specification to match with stocked LCSC parts.
- *Operating values* at any Vin / Iout you enter (**Recalculate**): duty cycle, efficiency, mode (CCM/DCM), output
  ripple, **phase margin, gain margin, crossover frequency**, actual Vout from the chosen divider and the Vout
  tolerance. Check phase margin (45-60 degrees or more is comfortable) at the extremes of Vin and load, not only at the
  default point.
- *Charts*: duty cycle and efficiency vs load at several input voltages; more charts on request.

**Simulate** (`.../simulate/<id>`): transient simulations of the design - Startup, Load Transient, Input Transient,
Steady State - with waveforms of Vout, inductor current, switch nodes and input current. They can take up to about
15 minutes each; start one and check back rather than waiting in a loop. Use load-transient for over/undershoot and
startup for inrush and monotonic rise.

**Export** (`.../export/<id>`): the full design summary on one page - schematic, BOM (CSV download icon), duty
cycle / efficiency / **loop response (Bode)** charts, and the most complete operating table: input and output
capacitor RMS currents and dissipation, inductor ripple (A and %), **inductor loss, IC loss, IC junction temperature
and the theta-JA it assumed**, peak switch current, average input current and total dissipation. Icons for a PDF report,
sharing and TI's cart. Designs are saved under **My Designs**.

**CAD export and the reference layout** (as of October 2026; check the current list on the page): Export offered
schematic, board and simulation files for Altium Designer, Cadence OrCAD, TINA-TI, CadSoft EAGLE, Mentor Graphics and
P-CAD - no native KiCad format. Customize and Export also show a **PCB LAYOUT** tab with the reference layout per layer
(Top / Mid 1 / Mid 2 / Bottom). For every design you will build:
1. Read or screenshot the PCB LAYOUT views for each layer.
2. With the user's permission to download, export EAGLE (or Altium) and import the board into KiCad. The EAGLE export
   was a zip containing zips; the board zip uses backslash path separators (unzip warns, and extracts correctly):
   ```
   unzip WBDesign<N>_CadSoftEAGLE.zip -d raw && unzip raw/ExportFiles/Board/*.zip -d brd
   kicad-cli pcb import --format eagle -o docs/layout-refs/<part>/webench-d<N>.kicad_pcb brd/Eagle/*/*.brd
   ```
   (`kicad-cli pcb import --format` also lists altium and pcad.) The imported board has no Edge.Cuts outline;
   kicad-pcb-workflow's `render.py --window` renders it anyway.
3. File it in the layout reference pack (SKILL.md step 6) as a **secondary** reference: it is drawn around WEBENCH's
   own BOM (other inductor and capacitor sizes than your stocked parts) and a generic stackup. The datasheet's layout
   guidelines and example win any conflict.

Use the logged-in numbers to: size the inductor's I_sat against the reported peak switch current *and* the current
limit; check capacitor ripple-current ratings against the RMS values; compare IC junction temperature with your board's
real copper (its theta-JA is for TI's assumed board); and record the operating table in the design doc. The values are
estimates from TI's models - the bench measurements still decide.

## When WEBENCH refuses a part

"Design cannot be created! Your preferred device does not work with the inputs you selected" comes without a reason,
including for operating points the datasheet allows (seen for a boost whose datasheet allows the output voltage
requested). It is not evidence that the part cannot do the job. Find the boundary by varying one input at a time
(Iout, then Vin range, then Vout) and note where it starts working, or fall back to the datasheet's design procedure
and say that WEBENCH was not used for that part.

## How to use the results

- Shortlist two or three parts that passed the gate in step 6, then check each with the **pcb-part-selection** skill
  (assembly class, package, datasheet). WEBENCH does not know what is in stock at JLC/LCSC.
- **Design for the exact orderable variant.** A suffix or grade variant (-Q1 automotive, A/B suffixes, package
  options) is a different part: its equations, references and limits can differ. Example: a commercial boost and its
  -Q1 version shared a pinout but used different current-limit references (so the same ILIM resistor gave a very
  different limit) and different Rds(on). Re-run WEBENCH on the exact orderable part, or re-derive every resistor and
  rating from that variant's own datasheet.
- Compare WEBENCH's inductor and capacitor values with your own calculation (`power-stage.md`). Where they differ,
  understand why (it often runs at a lower frequency than you assumed, or picks a large inductor for low ripple).
- Its parts are generic picks from its own library (often large electrolytic bulk caps and specific inductor MPNs);
  substitute stocked parts with equal or better ratings: inductance, I_sat, DCR, capacitance *after DC bias*, voltage,
  ESR and ripple current.
- Watch for parts that do not fit the application even though they appear: some candidates need I2C configuration
  before their output turns on, some are controllers needing external FETs, some are flyback/SEPIC with coupled
  inductors.
- Keep the compensation values WEBENCH computes for externally compensated parts, then recheck them if the inductor
  or output capacitance changes.
- Record the WEBENCH inputs and the chosen design's numbers in the design doc.
