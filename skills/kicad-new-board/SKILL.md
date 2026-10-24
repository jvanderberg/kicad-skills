---
name: kicad-new-board
description: Start a new hobbyist PCB project in KiCad the right way - interview the user from the general to the specific (purpose, environment, functional blocks and interfaces, power budget, physical limits, JLCPCB manufacturing, stackup, candidate parts) and write a requirements/architecture document that schematic capture, power design, part selection and review build on. Use it whenever someone wants to design a new board, "make a PCB for" something, turn an idea or breadboard into a board, asks "where do I start", "how many layers do I need", "2 or 4 layer", "what MCU/module should I use for my board", or starts an empty KiCad project - before any schematic is drawn.
---

# Starting a new board

Most of what makes a hobby board succeed or fail is decided before the schematic: what it must do, how it is powered,
what plugs into it, how big it is, how it will be made. Those decisions are cheap to change now and expensive after
layout. This skill gets them out of the user's head and onto paper in a few short exchanges, then hands the result to
the skills that do the detailed work.

**Scope.** This is for hobby and personal projects. It is not a substitute for professional engineering on
safety-critical, medical, automotive, mains-powered (on-board mains circuitry) or certified products; if the project is
one of those, say so and recommend professional design and review.

References (read when you reach that step):
- `references/interview-guide.md` - the questions for each level, the defaults to offer, and what each answer changes
- `references/jlcpcb-stackups.md` - verified JLCPCB stackup, capability, assembly and lead-time facts, with sources
- `assets/requirements-template.md` - the document you fill in

## How to run the interview

- **Funnel from general to specific.** Purpose first, part numbers last. A part chosen before the power source and
  enclosure are known usually has to be chosen again.
- **A few questions at a time, in plain conversational text.** Three to five per message, grouped by level. Menus and
  long questionnaires feel like paperwork and get worse answers.
- **Offer a default with each question** ("indoor, 0-40 C, in a plastic box - unless you tell me otherwise"), so the
  user can accept most of them with one word. Hobbyists often have not thought about a point yet; a sensible default
  is more useful than an open question.
- **Skip what is already known or obvious.** Read the user's message, any existing notes, breadboard code or project
  files first. Do not ask about USB for a board that is described as "USB-C powered", or about outdoor rating for a desk
  gadget.
- **Summarise back before going a level deeper** ("So: a desk clock, 3 units, USB-C powered, bare board on standoffs.
  Next, the blocks."). It catches misunderstandings while they are cheap and lets the user correct you in one line.
- **Record as you go.** Keep a running draft of the document (in your notes or written to disk early) so nothing said
  in exchange two is lost by exchange six. Every default the user did not explicitly confirm goes on the assumptions
  list.
- **Respect the user's time.** A typical hobby board should take four to six short exchanges. If the user wants to get
  going, fill the rest with defaults, mark them as assumptions, and move on.

## The funnel

Work through these levels in order. `references/interview-guide.md` has the detailed questions and defaults.

1. **Purpose.** What the board does, who uses it, how many will be built, budget per board and overall, timeline, and
   whether it is a learning project (worth doing the hard part yourself) or a tool (use modules and get it working).
   This sets how much risk and effort every later choice is worth.
2. **Usage and environment.** Indoor or outdoor, temperature range, enclosure or bare board, mounting, vibration and
   moisture, what plugs into it and how often, which parts a person touches (each is an ESD entry point), long cables
   (antennas and surge paths), and whether mains is anywhere nearby.
3. **Functional blocks.** MCU or processor (or a module), radios and connectivity, sensors, displays, actuators and
   loads, storage, user interface, debug and programming, expansion. Sketch a text block diagram and list every
   interface between blocks with its protocol and speed (I2C 400 kHz, SPI 20 MHz, UART 115200, USB full speed...).
   The interface list drives the stackup, the layout and the pin assignment later.
4. **Power.** Source (USB-C and what it will negotiate, battery chemistry/cells/charging, DC jack or terminal and its
   voltage range, or mains). For mains, recommend an off-the-shelf certified adapter or a certified enclosed AC-DC
   module rather than on-board mains circuitry - isolation, creepage and certification are outside hobby scope. List
   every rail, each load's average and peak current, and protection needs (reverse polarity, fusing, surge, hot-plug).
   Fill in the power budget table. Detailed regulator design belongs to the **pcb-power-supply** skill; batteries,
   charging and sleep-current budgets to the **pcb-battery-power** skill.
5. **Physical.** Board size and shape limits, connector positions and which edge they face, mounting holes, height
   limits (enclosure lid, tallest part), and assembly side. Default to all parts on the top side: JLC economic assembly
   places one side only, and it keeps the order cheap.
6. **Manufacturing.** JLCPCB fab and assembly unless the user says otherwise: economic vs standard assembly, Basic vs
   Extended parts and the per-part loading fee, 0402 as the smallest practical passive, the quantity, and the fact that
   every part must be in stock. Facts and sources are in `references/jlcpcb-stackups.md`.
7. **Stackup.** Decide the layer count with the rule below and record the reason.
8. **Component selection.** For each block, two or three candidate parts or modules, checked with the
   **pcb-part-selection** skill (stock in the assembler's region, assembly class, package, datasheet available). Prefer
   modules for RF and anything hard (certified radio modules avoid antenna design and give a certified radio), common
   parts with good datasheets and reference designs, and parts with second sources. Avoid single-source and NRND/EOL
   parts. Record the candidates and the reason for the front-runner; final choices can wait for schematic capture.
9. **Write the document** (below) and propose next steps.

## Choosing the layer count

- **Default: 4 layers at JLCPCB** - signal / GND / GND (or power pour) / signal. At hobby quantities the price
  difference over 2 layers is small (a few dollars to tens of dollars per order; check the live quote), and a solid
  ground plane under every signal prevents most signal-integrity, EMC and ground-bounce problems before they exist. It
  also makes routing much easier, because power and ground no longer compete with signals for space. Use JLC's default
  4-layer stackup (JLC04161H-7628, 1.6 mm) unless an interface needs controlled impedance, in which case pick one of
  their impedance stackups and use their impedance calculator.
- **2 layers when there is a reason:** a very simple board (a few parts, slow signals, no switching regulator or radio),
  a cost that matters at volume, or a board simple enough to route almost entirely on one side. Explain the trade-off:
  the bottom layer must be a nearly continuous ground pour, signals stay on top, every track that has to cross on the
  bottom is kept short, and return paths need deliberate attention (stitching vias, no long slots under fast signals).
- **6 or more layers:** if the design seems to need DDR memory, BGA escape beyond a couple of rows, several high-speed
  interfaces, or a controlled-impedance stack beyond simple 50/90/100 ohm traces, say plainly that this skill set is
  aimed at hobby boards. Suggest a module or system-on-module that already contains the hard part, a vendor reference
  design copied closely, or professional design help.

Record the layer count, the JLC stackup name, board thickness and copper weights in the document, so the KiCad
board setup and the review can use the same numbers.

## The document

Copy `assets/requirements-template.md` to `docs/requirements.md` in the project (or a path the user picks) and fill
every section. Keep it short and factual: tables and bullets, numbers with units, the reason for each decision in one
line. Two sections matter as much as the rest:
- **Assumptions** - every default the user accepted by not objecting, so they can be challenged later.
- **Open questions** - what is still unknown, who answers it, and what it blocks.

Show the user the finished document (or its key tables) and ask for corrections before moving on.

## Next steps to propose

1. **Create the KiCad project.** `kicad-cli` cannot create a project. Either the user creates it in KiCad (File > New
   Project, or New Project from Template - KiCad ships templates such as Raspberry Pi HAT and Arduino shields), or copy
   an existing minimal project (`.kicad_pro`, `.kicad_sch`, `.kicad_pcb`) and rename all three files consistently. Then,
   in Board Setup: set the layer count and the physical stackup to the chosen JLC stackup (dielectric thicknesses and
   copper weights from `references/jlcpcb-stackups.md`), and set design rules no tighter than JLC's capabilities for
   that layer count, with margin (e.g. 0.15 mm track/space and 0.3/0.6 mm vias as comfortable defaults). Draw the board
   outline and mounting holes from the physical section first, so placement starts inside real limits.
2. **Power design** with the **pcb-power-supply** skill, starting from the power budget table.
3. **Part checks** with the **pcb-part-selection** skill for every candidate before it goes in the schematic.
4. **Schematic capture and layout** with the **kicad-pcb-workflow** skill (scripted edits, verify, render, look).
5. **Review** with the **kicad-board-review** skill before ordering; the requirements document is its input for the
   intended use, environment, currents and interfaces.

Commit the document with the new project so later work can point back to it, and update it when a decision changes -
a requirements file that disagrees with the board misleads every later review.
