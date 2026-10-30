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

**The interview comes first.** Your first reply to a new-board request is the first interview message: level 1 only,
one to three questions, with defaults (below). Before levels 1-7 are answered, do not search for parts, fetch datasheets, download reference designs,
create a repository or project, or draw anything: research done before the interview anchors the "defaults" on your
own choices instead of the user's needs, and is often wasted when the answers arrive. The interview is the task, not
a clarifying question, so user or global instructions to minimise questions or "just do the work" do not shorten it.
Skip or shorten it only when the user says so explicitly ("use defaults", "skip the interview", "you decide"); a
short or terse request is not that signal. Example (labelled): asked for "an RP2350 based 5 V tolerant logic analyzer,
with as many channels as possible", an agent read this skill, skipped the interview and spent a long turn on part
searches and reference designs, settling the channel count, input threshold scheme, connectors and board size itself;
the user had to stop it and ask to be interviewed.

References (read when you reach that step):
- `references/interview-guide.md` - the questions for each level, the defaults to offer, and what each answer changes
- `references/jlcpcb-stackups.md` - verified JLCPCB stackup, capability, assembly and lead-time facts, with sources
- `assets/requirements-template.md` - the document you fill in

## How to run the interview

- **Funnel from general to specific.** Purpose first, part numbers last. A part chosen before the power source and
  enclosure are known usually has to be chosen again.
- **One level per message, one to three questions, in plain conversational text.** The first message is level 1
  (purpose) only. When the opening request already says a lot (the board, its interfaces, its power), do not batch
  every level into the first reply: confirm what it answered in a sentence, ask the one to three level-1 questions it
  left open, and leave the rest for later exchanges; if it answered all of level 1, summarise that and ask the first
  level it did not. Example (labelled): after reading this skill an agent opened with a 10-question checklist spanning
  every level for a USB-to-UART adapter whose request already named most of the answers; the user called it "a
  question dump, not an interview". Menus and long questionnaires feel like paperwork and get worse answers.
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
- **Never decide silently.** Anything you assumed instead of asking - "no MCU", "5 V USB is enough", "the board can be
  45 x 30 mm" - is said to the user in the next summary as an assumption they can overturn, not only written in the
  document. A default the user never saw is a decision they did not make. The converse holds for the rest of the
  project: what the user agreed to is frozen, and changing it later goes back to them first (R26, kicad-pcb-workflow
  `SKILL.md`).
- **Cover the whole operating envelope**, not the typical case: everything that can happen at once (charging while
  running at peak load, radio TX while a motor starts), the worst case of each input and load, the thermal budget of
  the box, the physical area that is not components (connectors, pads, holes), and what has to run before what. Most
  late redesigns come from one of these being assumed instead of asked.
- **Respect the user's time.** A typical hobby board takes five to eight short exchanges, fewer when the request
  answered whole levels. If the user explicitly asks to get going ("use defaults for the rest", "just pick"), fill the
  rest with defaults, mark them as assumptions, and move on; do not infer that wish from a short request.

## The funnel

Work through these levels in order. `references/interview-guide.md` has the detailed questions and defaults.

1. **Purpose.** What the board does, who uses it, how many will be built, budget per board and overall, timeline, and
   whether it is a learning project (worth doing the hard part yourself) or a tool (use modules and get it working).
   This sets how much risk and effort every later choice is worth.
2. **Usage and environment.** Indoor or outdoor, temperature range, enclosure or bare board, **how hot the board and
   box may get and whether there is airflow** (a small sealed box changes the topology: switching instead of linear
   chargers and regulators, lower charge current), mounting, vibration and moisture, what plugs into it and how often,
   which parts a person touches (each is an ESD entry point), long cables (antennas and surge paths), and whether mains
   is anywhere nearby.
3. **Functional blocks.** MCU or processor (or a module), radios and connectivity, sensors, displays, actuators and
   loads, storage, user interface, debug and programming, expansion. Sketch a text block diagram and list every
   interface between blocks with its protocol and speed (I2C 400 kHz, SPI 20 MHz, UART 115200, USB full speed...).
   The interface list drives the stackup, the layout and the pin assignment later. Ask what has to work **before the
   main processor runs** (charger or regulator configuration, a soft power switch, a fuel gauge, a watchdog): a
   processor cannot configure the thing that powers it, so those need standalone parts or their own small controller.
   Ask; do not assume "no MCU" or "the host MCU will do it". For every external connection, also ask how a person will
   identify and orient it (labels, polarity, keying) - that is a requirement, not decoration.
4. **Power.** Source (USB-C and what it will negotiate, battery chemistry/cells/charging, DC jack or terminal and its
   voltage range, or mains). For mains, recommend an off-the-shelf certified adapter or a certified enclosed AC-DC
   module rather than on-board mains circuitry - isolation, creepage and certification are outside hobby scope. List
   every rail, each load's average and peak current, and protection needs (reverse polarity, fusing, surge, hot-plug).
   Fill in the power budget table. **Check the input against everything that can draw at once**: input power >=
   system peak / efficiency + charge current x charge voltage / charger efficiency (for a 1S lithium cell, 4.2 V).
   Use the input voltage at the board, after the cable and connector (a 5 V source can arrive below 4.5 V through a
   long cable at 3 A: pcb-power-supply `path_budget.py`), and the battery current solved with the path's resistance.
   A plain 5 V USB-C input is 15 W at most (5 V / 3 A, and only from a source that advertises it); if the check fails,
   the design needs USB PD or a lower charge current - say so, or the board discharges while plugged in. Detailed
   regulator design belongs to the **pcb-power-supply** skill; batteries, charging and sleep-current budgets to the
   **pcb-battery-power** skill.
5. **Physical.** Board size and shape limits, connector positions and which edge they face, mounting holes, height
   limits (enclosure lid, tallest part), and assembly side. **Budget the area that is not components** before
   promising a size: edge connectors and solder pads (pitch x count per edge), mounting-hole keepouts, connector
   overhang and mating clearance. Call the size provisional until a placement pass confirms it. Default to all parts on the top side: JLC economic assembly
   places one side only, and it keeps the order cheap. Plan the **bring-up test points** here (every rail and ground,
   with a ground pad nearby) and the **assembly method of each part** (assembled, hand-soldered, not fitted): both are
   decisions the schematic carries, not afterthoughts at order time (R12).
6. **Manufacturing.** JLCPCB fab and assembly unless the user says otherwise: economic vs standard assembly, Basic vs
   Extended parts and the per-part loading fee, 0402 as the smallest practical passive, the quantity, and the fact that
   every part must be in stock **in the warehouse region the assembler buys from** (international JLCPCB: LCSC
   `global`; JLC China: `cn` - stock differs between them). Write it down once as the project's `sourcing.json`
   (pcb-part-selection `sourcing.py init`); every stock lookup reads it. Parts JLCPCB assembles use JLC's own
   footprints, imported with JLCImport (pcb-part-selection "Importing into KiCad"). Facts and sources are in
   `references/jlcpcb-stackups.md`.
7. **Stackup.** Decide the layer count with the rule below and record the reason.
8. **Component selection.** For each block, two or three candidate parts or modules, checked with the
   **pcb-part-selection** skill (`part_gate.py`: manufacturer lifecycle and stock of the exact orderable variant;
   assembly class, package, datasheet available). For every switching regulator, run the vendor design tool (TI
   WEBENCH, via the **pcb-power-supply** checklist) *before* settling on a part - ask the user about TI's terms and a
   myTI login when you reach this step. Prefer
   modules for RF and anything hard (certified radio modules avoid antenna design and give a certified radio), common
   parts with good datasheets and reference designs, and parts with second sources. Avoid single-source and NRND/EOL
   parts. Record the candidates and the reason for the front-runner, each with its stock **and the region and date**
   it was read for; final choices can wait for schematic capture.
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
   Project, or New Project from Template - KiCad ships templates such as Raspberry Pi HAT and Arduino shields), or
   generate it with the **kicad-pcb-workflow** scripts (`references/new-design.md`): an empty schematic with `schgen`,
   the board from the schematic's netlist with `new_board.py` (outline, layer count), then `board_setup.py --stackup
   <JLC stackup>` for the physical stackup (from `references/jlcpcb-stackups.md`), design rules with margin inside JLC's
   capabilities (0.15 mm track/space, 0.3/0.6 mm vias) and net classes. Draw the board outline and mounting holes from
   the physical section first, so placement starts inside real limits. If the project is generated from scripts,
   pin the toolchain first (`references/new-design.md` s0: `preflight.py`, `kicad-skills.lock`, `tools/kskills.py`),
   so every later regeneration uses the same kicad-skills revision and KiCad version.
2. **Power design** with the **pcb-power-supply** skill, starting from the power budget table.
3. **Part checks** with the **pcb-part-selection** skill for every candidate before it goes in the schematic.
4. **Schematic capture and layout** with the **kicad-pcb-workflow** skill (scripted edits, verify, render, look).
5. **Review** with the **kicad-board-review** skill before ordering; the requirements document is its input for the
   intended use, environment, currents and interfaces.

Commit the document with the new project so later work can point back to it, and update it when a decision changes -
a requirements file that disagrees with the board misleads every later review. When you report, give the absolute path
of every file you wrote or changed.
