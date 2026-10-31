# Interview guide

Questions for each level of the funnel, the default to offer when the user has no strong view, and why the answer
matters. Ask only what is not already known; one level per message, one to three questions (the first message is
level 1 only); summarise before moving on.

Contents: 1 Purpose - 2 Usage and environment - 3 Functional blocks - 4 Power - 5 Physical - 6 Manufacturing -
7 Stackup - 8 Component selection - Example opening

---

## 1. Purpose

| Ask | Default | Why it matters |
|---|---|---|
| What does it do, in one or two sentences? | - | Everything else hangs off this |
| Who uses it - you, friends, the public? | You | Non-technical users need keyed connectors, labels, protection against misuse |
| How many will be built? | 5 (JLC's minimum order) | Sets whether Extended-part fees, module cost or 2 vs 4 layers matter at all |
| Budget per board, and overall? | Not tight at prototype quantity | Decides module vs discrete, layer count, assembly vs hand soldering |
| Timeline? | A few weeks | Fab plus assembly plus shipping is usually 1-3 weeks; long-lead parts change the plan |
| Learning project or a tool that just has to work? | Tool | A tool should use modules and reference designs; a learning project may do the hard part on purpose |
| Is there an existing prototype (breadboard, dev board, firmware)? | - | Its parts and pin map are strong defaults; ask for the code or wiring |

## 2. Usage and environment

| Ask | Default | Why it matters |
|---|---|---|
| Indoor or outdoor? | Indoor | Outdoor means moisture, UV, wider temperature, conformal coating, sealed connectors |
| Temperature range? | 0-40 C ambient | Derates fuses, regulators, batteries (most Li-ion must not charge below 0 C) |
| How hot may the board / box get? Airflow? | Warm to the touch at most; no airflow if in a box | A sealed small box makes linear chargers and LDOs with real dropout impractical and limits charge current |
| Enclosure or bare board? What material? | Bare on standoffs | Metal boxes block radios; plastic boxes trap heat; the box sets board size and connector positions |
| How is it mounted? | M3 holes in the corners | Hole positions are a mechanical constraint for layout |
| Vibration, moisture, dust? | None | Changes connectors (locking), part sizes, and whether to coat |
| What plugs into it, and how often? | - | Every external connector needs a rating, a keyed/retained style, and ESD/surge thinking |
| Which parts does a person touch (buttons, connectors, touch pads, exposed headers)? | - | Each is an ESD entry point and needs a clamp near the entry |
| Any long cables (over ~1 m)? | No | Long cables are antennas and surge paths: series resistance, clamps, filtering |
| Is mains anywhere near (switching relays on mains, mains in the same box)? | No | On-board mains is outside hobby scope; recommend certified modules and professional review |

## 3. Functional blocks

Walk through the list; for each block that exists, ask what it needs to do, not which part.

- **Processor:** what it must run (simple control, Wi-Fi stack, audio, display graphics), I/O count, preferred
  ecosystem (Arduino, MicroPython, Pico SDK, ESP-IDF, Zephyr). Default: the ecosystem the user already knows.
- **Connectivity:** Wi-Fi, Bluetooth/BLE, LoRa, Zigbee/Thread, Ethernet, USB device/host, CAN, RS-485. Default for
  radios: a certified module with an integrated antenna or a u.FL connector.
- **Sensors:** what is measured, range, accuracy, sample rate.
- **Displays:** type (LED, character LCD, OLED, TFT, e-paper), size, interface.
- **Actuators and loads:** motors, LEDs/strips, relays, solenoids, speakers - with voltage and current, because these
  usually dominate the power budget.
- **Storage:** flash, microSD, EEPROM/FRAM.
- **User interface:** buttons, encoders, LEDs, buzzer.
- **Debug and programming:** USB bootloader, SWD/JTAG header, UART console, test points. Default: a debug header and a
  UART console even if USB programming exists, because they are what work when the firmware does not.
- **Bring-up test points:** a pad for every rail and every ground domain (plus reset/enable and the main clock), each
  labelled, with a ground pad within probe reach, on one side. Default: yes, all of them - the first power-up is
  where a missing one costs most (requirements template "Bring-up test points").
- **Expansion:** headers, Qwiic/STEMMA QT, Grove, a spare I2C/SPI/UART.
- **What must run before the main processor?** Charger or PMIC configuration, a soft power switch, a fuel gauge, a
  watchdog. Default: nothing, so every such part must be standalone (resistor-configured) - state this as an
  assumption. A part that needs I2C setup before it delivers power cannot be set up by the processor it powers.
- **How does a person use each external connection?** Labels, polarity, keying, which side wires are soldered from.
  Default: every connector and solder pad labelled with its function on the silkscreen, polarity marked, pairs in the
  same order (+ then GND) everywhere.

Then write the block diagram and interface table:

```
USB-C --> [5V in / protection] --> [3.3 V regulator] --> MCU module (ESP32-S3)
                                                          |-- I2C 400 kHz --> temp/humidity sensor
                                                          |-- SPI 20 MHz  --> TFT display
                                                          |-- GPIO        --> 3 buttons, status LED
                                                          '-- USB FS      --> USB-C (programming)
```

| From | To | Interface | Speed | Length/notes |
|---|---|---|---|---|
| MCU | Display | SPI | 20 MHz | On-board, ~40 mm |

Speeds and lengths decide whether anything needs termination, controlled impedance or extra care in layout.

## 4. Power

| Ask | Default | Why it matters |
|---|---|---|
| Power source? | USB-C 5 V | Sets the input range, protection and connector |
| USB-C: plain 5 V, or USB PD at a higher voltage? How much current? | 5 V, up to 1.5 A, with 5.1k CC pull-downs - only if the power check below passes | Without CC resistors many chargers give 0 V; above 5 V or 15 W needs a PD sink controller |
| Battery: chemistry, cells, capacity, charged on board? | 1S Li-ion, on-board charger | Sets the regulator topology (3.0-4.2 V around 3.3 V needs buck-boost or a low-dropout plan) and charge safety |
| DC jack or terminal: nominal voltage and real range? | 12 V, 9-15 V | The minimum sets regulator headroom; the maximum plus surge sets every part's voltage rating |
| Mains? | - | Recommend a certified external adapter or an enclosed certified AC-DC module |
| Which rails, and what loads on each, average and peak? | - | Fill the power budget table |
| Protection: reverse polarity, fuse, surge, hot-plug? | Fuse/PTC and reverse protection on any non-USB input; TVS on any input from a cable | Hobby boards die most often from a reversed or hot-plugged supply |
| Battery life target? | - | Sleep current becomes a requirement on every part on the always-on rail |

Power budget table (for each rail; sum loads, then add 20-30 % margin):

| Rail | Source | Load | Avg mA | Peak mA | Notes |
|---|---|---|---|---|---|
| 3V3 | Buck from 5 V | ESP32-S3 module | 100 | 500 | Wi-Fi TX peaks |

Peaks matter: radios, motors and LED strips draw far above average, and the regulator, the input connector and the
source must handle the peak. Hand the table to the **pcb-power-supply** skill.

**Input power check (everything at once).** Add up what can happen simultaneously, at its worst:

```
P_in_needed = P_system_peak / eta_regulators + I_charge x V_charge / eta_charger      (V_charge = 4.2 V for 1S Li-ion)
```
Compare with what the input can deliver: plain USB-C 5 V is 2.5 W (default USB), 7.5 W (1.5 A) or 15 W (3 A)
depending on what the source advertises; more needs USB PD (and a source that offers it) or another input. If it
fails, the board discharges while plugged in: propose PD, a lower charge current, or charging only while off, and let
the user choose. Example (labelled): a handheld drawing about 10 W at peak while charging a 1S2P pack at 2 A needs
roughly 10 / 0.9 + 2 x 4.2 / 0.9, about 20 W - beyond any 5 V USB-C source.

## 5. Physical

| Ask | Default | Why it matters |
|---|---|---|
| Size or shape limit? | As small as is comfortable, rectangle - provisional until placement | Smaller boards are cheaper but harder to route; very small boards may need 4 layers |
| How many external connections, and as connectors or solder pads? | - | Edge pads and connectors take pitch x count per edge; budget it before promising a size |
| Which connectors on which edge? | All on one edge | Connector placement fixes much of the layout |
| Mounting holes: count, size, positions? | 4 x M3 (3.2 mm), 3-4 mm from the corners | Must match the enclosure or standoffs; each needs a copper and part keepout around it, which costs area |
| Height limit above/below the board? | None | Tall parts (electrolytics, connectors, inductors) may not fit a lid |
| All parts on top? | Yes | Required for JLC economic assembly; cheaper and simpler |
| Through-hole parts? | Few, hand-soldered or JLC through-hole assembly | Each is a cost and process decision |
| Jumpers or switches that select a rail or mode? | Solder jumper or a header + shunt | A header that picks one of several rails must be a checkerboard (every adjacent pin pair one rail + common) so no shunt position shorts two rails (kicad-pcb-workflow `layout-rules.md` "Selection jumpers"); record each position's meaning |

## 6. Manufacturing

| Ask | Default | Why it matters |
|---|---|---|
| Fab and assembler? | JLCPCB fab + JLC economic assembly | Sets capabilities, part library (LCSC) and fees |
| Assembled by JLC, by hand, or a mix? | JLC assembles SMD, user solders big through-hole | Hand soldering limits package choice (0603+ and no QFN/BGA is a hobby-friendly floor). Record the method per part (assembled / hand-soldered / not fitted): it becomes each symbol's in-BOM, in-position-file and DNP attributes, and the assembler's BOM and position file follow them |
| Quantity per order? | 5 boards, 2-5 assembled | JLC assembly can populate fewer boards than are fabricated |
| Which JLC: international (jlcpcb.com) or China (jlc.com)? | International: LCSC **global** warehouse | Stock is per warehouse region (global vs cn): a part can be plentiful in one and absent from the other. Written to `sourcing.json`; every stock lookup reads it |
| Finish and colour? | HASL (lead-free), green | ENIG for fine-pitch parts or edge contacts |

Defaults to state: smallest passive 0402 (0201 forces standard assembly), each unique Extended part adds a loading
fee, every part must be in stock at LCSC in the assembler's region at order time. When this level is answered, write
the sourcing context: `pcb-part-selection/scripts/sourcing.py init <project> --assembler JLCPCB --region global
--boards <assembled>` (plus `min_stock` if the user wants a stock policy).

## 7. Stackup

Apply the rule in SKILL.md. Ask only what decides it: any switching regulator or radio (pushes to 4 layers), any
interface over ~10 MHz or USB/Ethernet (4 layers), quantity large enough that per-board cost dominates (may justify 2),
any DDR/BGA/multiple gigabit links (6+: out of scope). State the decision and the reason in one line.

## 8. Component selection

For each block, list two or three candidates with the **pcb-part-selection** checks:

| Block | Candidate | LCSC | Stock (region, date) | Class | Package | Why / concerns |
|---|---|---|---|---|---|---|

Fill the stock column from `part_gate.py` / `sourcing.py stock` (the project's region from `sourcing.json`), e.g.
"2,341 (global, 2026-10-25)"; a figure without its region was not checked for this assembler.

What makes a good hobby candidate: a module for anything RF or hard; a part with a reference design and a large
community; in stock with thousands available; Basic or Preferred Extended where a choice exists; hand-solderable if the
user will rework it; not NRND/EOL; a pin-compatible second source for anything critical.

## Example opening

> Happy to help plan this. A few questions about the purpose first - say "default" to any of them and I'll use what's
> in brackets:
> 1. What will the board do, in a sentence or two?
> 2. How many will you build, and is it a learning project or a tool that just has to work? [5 boards, a tool]
> 3. Any budget or deadline I should design around? [none; cheapest that works]

Environment, power and the rest come in the following exchanges, one level at a time. When the request already
answers question 1 ("a USB-C to UART adapter with 1.8/3.3/5 V I/O"), say so in one line and ask only 2 and 3.
