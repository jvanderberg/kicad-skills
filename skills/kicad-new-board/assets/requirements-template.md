# <Project name> - requirements and architecture

Revision: <n> - Date: <YYYY-MM-DD> - Status: draft | agreed

Scope: hobby/personal project. Not designed or reviewed for safety-critical, medical, automotive, on-board mains or
certified use.

## 1. Purpose

- What it does:
- Users:
- Quantity: <fabricated> boards, <assembled> assembled
- Budget: <per board> / <total>
- Timeline:
- Project type: learning | tool
- Existing prototype / firmware:

## 2. Usage and environment

| Item | Requirement |
|---|---|
| Location | indoor / outdoor |
| Ambient temperature | <min> to <max> C |
| Enclosure | none / <type, material, inside dimensions> |
| Mounting | |
| Vibration / moisture / dust | |
| External connections | <connector: what plugs in, how often, cable length> |
| User-touchable parts (ESD) | |
| Long cables (> 1 m) | |
| Mains proximity | none / <details> |
| Thermal budget | max board / enclosure temperature <C>, airflow yes / no |

## 3. Functional blocks

### Block diagram

```
<text block diagram>
```

### Blocks

| Block | Function | Key requirements |
|---|---|---|
| Processor | | |
| Connectivity | | |
| Sensors | | |
| Display | | |
| Actuators / loads | | |
| Storage | | |
| User interface | | |
| Debug / programming | | |
| Expansion | | |

### Interfaces

| From | To | Interface | Speed | Length / notes |
|---|---|---|---|---|

### Startup and control

- Must work before the main processor runs: <charger config, soft power switch, gauge, ... / nothing>
- How each is configured without it: <standalone parts / on-board controller>

### External connections (user-facing)

| Connection | Connector or pad | Label | Polarity / keying | Side |
|---|---|---|---|---|

### Bring-up test points

| Rail or signal | Test point (pad, side) | Ground pad nearby | Expected value |
|---|---|---|---|
| <every rail, every ground domain, reset/enable, clocks> | | | |

## 4. Power

- Source(s): <USB-C 5 V / PD x V / battery chemistry, cells, capacity / DC <nom> V, range <min>-<max> V / external
  certified adapter>
- Charging: <none / on-board, charge current>
- Protection: reverse polarity <how>, overcurrent <fuse/PTC>, surge <TVS>, hot-plug/inrush <how>
- Battery life target / sleep current:

### Rails

| Rail | Voltage | Tolerance | Source | Regulator type (tentative) | Noise-sensitive loads |
|---|---|---|---|---|---|

### Power budget

| Rail | Load | Avg mA | Peak mA | Datasheet tables summed (table, page; what each excludes) |
|---|---|---|---|---|
| | **Total (with <x> % margin)** | | | |

Input power at peak: <W>. Regulator design: see the pcb-power-supply notes when done.

Input power check (all loads at once, worst case): system peak <W> / eta + charging <A> x <V> / eta = <W> needed;
input can deliver <W> (<source and what it advertises>) -> pass / fail -> <action>.

## 5. Physical

| Item | Requirement |
|---|---|
| Board outline | <W x H mm, shape> (provisional until placement) |
| Area budget | connectors / pads <mm2>, mounting keepouts <mm2>, components <mm2> |
| Connector positions | <connector: edge, position> |
| Mounting holes | <count, size, positions> |
| Height limits | top <mm>, bottom <mm> |
| Assembly side | top only / both |
| Through-hole parts | |
| Assembly method per part | assembled / hand-soldered (out of the BOM and the position file) / not fitted (DNP) - set on each symbol at capture |

## 6. Manufacturing

| Item | Choice |
|---|---|
| Fab | JLCPCB |
| Assembly | JLC economic / standard / hand / mix |
| Assembler's stock region | global (international JLCPCB) / cn (JLC China) - recorded in `docs/sourcing.json` |
| Quantity | <fab> / <assembled> |
| Surface finish, colour | |
| Smallest package | 0402 |
| Part policy | in stock at LCSC in the assembler's region for quantity + attrition (+ policy minimum, if any, in `sourcing.json`); prefer Basic / Preferred Extended |

## 7. Stackup

| Item | Choice |
|---|---|
| Layers | 2 / 4 |
| Reason | |
| JLC stackup | <e.g. JLC04161H-7628> |
| Thickness | 1.6 mm |
| Copper | outer <oz>, inner <oz> |
| Layer use | L1 signal / L2 GND / L3 GND or power / L4 signal |
| Controlled impedance | none / <nets, target ohms> |
| Design rules | track/space <mm>, via <drill>/<diameter> mm, copper to edge <mm> |

Values checked on jlcpcb.com on <date>.

## 8. Component candidates

| Block | Candidate (front-runner first) | LCSC | Stock (region, date) | Class | Package | Why / concerns |
|---|---|---|---|---|---|---|

## 9. Decisions

| Decision | Choice | Reason | Agreed by user (date) |
|---|---|---|---|

An agreed decision is frozen: changing it later (a substitute part, a new threshold) goes back to the user with the
reason and options first (R26).

## 10. Assumptions

Defaults accepted without explicit confirmation, and anything decided without asking; each was stated to the user
(date). Challenge any that are wrong.

-

## 11. Open questions

| Question | Who answers | Blocks |
|---|---|---|

## 12. Next steps

1. Create the KiCad project; set stackup and design rules to section 7; draw the outline and mounting holes.
2. Power design from section 4 (pcb-power-supply).
3. Stock and datasheet checks for each candidate in section 8 (pcb-part-selection).
4. Schematic capture and layout (kicad-pcb-workflow).
5. Design review before ordering (kicad-board-review).
