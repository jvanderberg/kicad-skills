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

| Rail | Load | Avg mA | Peak mA | Notes |
|---|---|---|---|---|
| | **Total (with <x> % margin)** | | | |

Input power at peak: <W>. Regulator design: see the pcb-power-supply notes when done.

## 5. Physical

| Item | Requirement |
|---|---|
| Board outline | <W x H mm, shape> |
| Connector positions | <connector: edge, position> |
| Mounting holes | <count, size, positions> |
| Height limits | top <mm>, bottom <mm> |
| Assembly side | top only / both |
| Through-hole parts | |

## 6. Manufacturing

| Item | Choice |
|---|---|
| Fab | JLCPCB |
| Assembly | JLC economic / standard / hand / mix |
| Quantity | <fab> / <assembled> |
| Surface finish, colour | |
| Smallest package | 0402 |
| Part policy | in stock at LCSC (<region>) for quantity + attrition; prefer Basic / Preferred Extended |

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

| Block | Candidate (front-runner first) | LCSC | Stock | Class | Package | Why / concerns |
|---|---|---|---|---|---|---|

## 9. Decisions

| Decision | Choice | Reason |
|---|---|---|

## 10. Assumptions

Defaults accepted without explicit confirmation; challenge any that are wrong.

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
