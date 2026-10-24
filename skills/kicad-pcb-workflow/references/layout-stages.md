# Layout in stages, each from a written brief

A board designed in one long session loses its own early work: the datasheet layout figures and reference boards
collected at the start are out of working attention by the time the last block is routed, and generic habits take
over (a ground via beside every pad, one pour everywhere) that quietly break the specific rules. DRC stays clean
throughout, because DRC checks manufacturing rules, not design intent. The fix is structural, and it applies to any
multi-phase job, not only layout:

1. **Gather the authoritative references early** (for each switching converter, charger, RF or high-speed part: the
   layout reference pack, `pcb-power-supply` step 6).
2. **Every stage starts from a brief that restates its own inputs and constraints**, copied from those references,
   so it does not depend on what a long conversation still remembers. Run each stage as a fresh agent session (or at
   least re-read its brief and references before starting); the brief is also the hand-off record, so a stage can be
   re-run alone.
3. **Every stage is verified against its reference, not only against generic checks.**
4. **A later stage checks the earlier stages' frozen decisions for feasibility before treating them as final**, and
   sends any it cannot honour back to the user as a decision - never a silent shortcut.

## Stages

| Stage | Output | Done when |
|---|---|---|
| 0. Channel and layer plan | `docs/layout-plan.md` | every shared resource below is allocated |
| 1. Placement | placement data file, board regenerated | courtyards clean, fine-pitch escapes proven, each block's placement matches its reference figure |
| 2..n. Routing, one block at a time (input/protection, charger, each converter, signals) | route plan section per block | block nets connected, DRC clean, compliance rows ticked |
| n+1. Planes, pours, stitching | pour and via-field section | plane continuity checked (`planes.py`), keepouts intact |
| n+2. Review | kicad-board-review | findings fixed or accepted by the user |

## Stage 0: allocate shared resources before anyone consumes them

Board area, layers and routing channels are shared by every block. When each block takes what it needs as it goes,
the first block's convenient track lands exactly where a later block's mandatory via has to go. Before routing any
block, write a one-page plan:
- which nets own which plane layers and which pours on the outer layers (and where those pours must stay unbroken);
- **reserved sites**: thermal and ground vias under each IC's exposed pad, each converter's single-point ground tie,
  keepout islands for analog grounds, the area under each switch node;
- **lanes for board-wide signals** (enables, status, sense lines, buses): which layer, which corridor, in which order;
- where each block's interface copper lands on its neighbours (which pour or via a block must connect to).
Route only inside your allocation; a block that needs more goes back to the plan, which is updated first.

## Stage 1: placement - prove the frozen decisions can be met

The schematic froze decisions (which pins are used, which features exist). Placement is the first stage that can
discover one is not achievable. Before calling placement done:
- **Escape check for every fine-pitch part** (0.5 mm pitch or less, or any part with inner pins): for each used pin,
  sketch the escape path to where its net must go, against its neighbours. A pin that cannot escape is a schematic
  decision (drop the feature, change the part, change the pinout use) for the user - not something to drop quietly at
  routing time.
- Each block's placement matches its reference figure (hot-loop parts at the pins, quiet-side parts, orientation).
- `check.sh` courtyard results clean (`board_lint.py` lists footprints with no courtyard: those are invisible to it).
- Report every frozen decision the placement could not honour as an open question with options.

## The brief (one per stage; template: `assets/layout-brief-template.md`)

- **Scope**: the block's parts and nets (from the netspec file), the board area allocated to it.
- **References**: the datasheet layout section and figure (primary), the EVM or vendor reference layout (secondary),
  with file paths and page numbers; the rules from them, copied as a numbered list.
- **Board-wide rules**: stackup, net classes, keepouts, the layer plan entries that apply.
- **Interfaces**: which neighbouring copper this block connects to, and what it must not cross.
- **Done criteria**: DRC clean for the block, its nets connected, a net-coloured render (`view.py`) compared side by
  side with the reference figure at the same scale, and every rule in the compliance file ticked or deviated with
  evidence.

## The compliance file (`docs/layout-compliance.md`; template: `assets/layout-compliance-template.md`)

One table per block, one row per rule from its references, each with the evidence: where the part or copper is and
why that satisfies the rule. Rules are checked against the render, not from memory.

**"Cannot be met" is itself a claim that needs evidence.** A deviation row must record what was tried (package sizes,
values, positions, layers), what blocked each attempt (which part, which clearance), and the cheaper alternatives
that were tried first: a smaller package, a different value that still meets the need, another position or layer.
Example (labelled): on one board a converter's "bypass cap at the VIN pin" rule was written off as "no room" after
only a 22 uF 0805 was tried; a 1 uF 0402 fitted. Only after the alternatives are exhausted does the deviation go to the
user as a decision, with its consequence.

## Per-block routing loop

1. Re-open the block's brief and its reference figure (render it next to the board window).
2. Route the block (`router.py`, `references/routing.md`).
3. Render the block net-coloured at the scale of the figure (`kicad-board-review/scripts/view.py`), compare, tick
   each compliance row with evidence.
4. `check.sh`; fix what is new. Move on only when the block's done criteria are met.
