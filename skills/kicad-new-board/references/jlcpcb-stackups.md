# JLCPCB facts for planning a board

Checked against jlcpcb.com in October 2026. JLC changes stackups, capabilities, prices and lead times regularly:
re-check the linked pages (and the live quote) before relying on a number, and tell the user that you did. Anything
marked **unverified** could not be confirmed on a JLC page.

## 4-layer stackups (1.6 mm)

Source: https://jlcpcb.com/impedance

- Outer copper 1 oz (0.035 mm finished) on all listed 4-layer stackups; inner copper listed as 0.5 oz
  (0.0152 mm). Options offered: outer 1 or 2 oz, inner 0.5, 1 or 2 oz. Inner copper defaults to 0.5 oz
  (https://jlcpcb.com/capabilities/pcb-capabilities) - use 0.5 oz in power and voltage-drop calculations unless 1 oz is
  ordered and paid for.
- Structure: L1 - prepreg - L2 - core - L3 - prepreg - L4. Signals on L1/L4 reference L2/L3 across the thin prepreg;
  the thick core separates the two planes.

| Stackup | Prepreg L1-L2 (and L3-L4) | Core L2-L3 | Notes |
|---|---|---|---|
| JLC04161H-7628 | 7628 x1, 0.2104 mm | 1.065 mm | Same build as "No requirement" (the default) |
| JLC04161H-3313 | 3313 x1, 0.0994 mm | 1.265 mm | Thinner prepreg: tighter coupling to the plane, narrower 50 ohm traces |
| JLC04161H-1080 | 1080 x1, 0.0764 mm | 1.265 mm | Thinnest single-ply prepreg |
| JLC04161H-2116 | 2116 x1, 0.1164 mm | 1.265 mm | |

The page lists about 15 more 4-layer variants (A-G suffixes) with multi-ply prepregs and thinner cores; look them up
if a specific dielectric height is needed.

Dielectric constants listed on the page: prepreg 7628 = 4.4, 3313 = 4.1, 1080 = 3.91, 2116 = 4.16; core 4.6; solder
mask 3.8. Use JLC's impedance calculator (https://jlcpcb.com/pcb-impedance-calculator) for trace widths; it takes
layer count, thickness and copper weights and recommends a stackup. Do not hand-compute widths and present them as
JLC's.

6-layer impedance stackups also exist (JLC06161H-3313, -7628, -1080, -2116 and lettered variants) on the same page.

## Fabrication capabilities

Source: https://jlcpcb.com/capabilities/pcb-capabilities

| Item | 1-2 layer | Multilayer (4+) |
|---|---|---|
| Min track/space, 1 oz | 0.10 / 0.10 mm | 0.09 / 0.09 mm |
| Min track/space, 2 oz | 0.16 / 0.16 mm | 0.15 / 0.15 mm |
| Min via drill / diameter | 0.15 / 0.25 mm | 0.15 / 0.25 mm |
| Smallest via at no extra cost | 0.3 mm drill / 0.4 mm via | 0.2 mm drill / 0.45 mm via |
| PTH annular ring, 1 oz | 0.25 mm recommended, 0.18 mm min | 0.20 mm recommended, 0.15 mm min |
| Outer copper options | 1 / 2 / 2.5 / 3.5 / 4.5 oz | 1 / 2 oz |

- 0.1 mm drill / 0.2 mm via is allowed only on boards of 1 mm or thinner with ENIG or OSP.
- Via pad should be 0.1 mm (preferably 0.15 mm) larger than the drill.
- Copper to board edge: at least 0.2 mm for routed edges, 0.4 mm for V-cut.
- Impedance tolerance: +/-10 % standard.
- Epoxy filled and capped vias (via-in-pad) are offered; default on 6+ layer boards.
- Board thicknesses listed: 0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0 mm (the FAQ on the same page quotes a wider range).
- The page is internally inconsistent on minimum PTH drill (0.15 mm in the table, 0.1 mm "more costly" elsewhere).

Design to comfortable values, not the minimums: 0.15 mm track/space and 0.3 mm drill / 0.6 mm via are easy to meet
on any layer count and leave room for the fab's tolerance.

**Small vias: the hole and the diameter together decide the price.** The quote page (https://cart.jlcpcb.com/quote,
"Min via hole size/diameter", checked 2026-10-30): "Additional charges will apply when the via hole<0.3mm and the via
diameter<=0.4mm. No additional charge when the via hole>=0.3mm, and via diameter>=0.4mm ... For multi-layer boards, if
the via diameter>=0.45mm, the 0.2mm hole is also without an extra charge." So:
- 4+ layers: **0.45 / 0.2 mm is the small free via** (a 4-layer RP2350 board used 139 of them at no extra charge);
  0.4 / 0.2 or 0.35 / 0.2 is charged.
- 1-2 layers: every hole under 0.3 mm is charged; 0.4 / 0.3 (or 0.45 / 0.3) is the small free via.
- Leave the quote's via option at the default unless the board really has a charged via. Selecting the
  "0.2mm/(0.3/0.35mm)" option on a 5-pc 4-layer 44 x 30 mm HASL board (2026-10-30) raised the quote from $13.10 to
  $49.78, and it switched on high-spec options (material upgrade, deburring, a $16.63 4-wire Kelvin test) that stayed
  on after switching back: check every option on the quote before ordering.
- Pad drills count like vias: KiCad's `*_ThermalVias` footprints use 0.2 mm drills in 0.5 mm pads (free on 4+ layers,
  charged on 2).

## Assembly (PCBA)

Sources: https://jlcpcb.com/capabilities/pcb-assembly-capabilities, https://jlcpcb.com/help/article/pcb-assembly-price
(updated 22 Oct 2026), https://jlcpcb.com/help/article/pcb-assembly-faqs

| | Economic | Standard |
|---|---|---|
| Smallest package | 0402 | 01005 |
| Sides | Single-sided placement | Single and double sided |
| Layer counts | 2, 4, 6 | 1-32 |
| Board thickness | 0.8-1.6 mm | No limit |
| Board size (single) | 10x10 to 470x500 mm | 70x70 to 460x500 mm |
| Min BGA pitch | 0.5 mm | 0.3 mm |
| Min fine-pitch lead spacing | 0.40 mm | 0.35 mm |
| Setup fee | $8.18 | $25.56 one side / $51.12 two sides |
| Stencil | $1.53 | $8.21 one side / $16.42 two sides |
| Feeder loading | $3.07 per unique Extended part | $1.53 per unique part (Basic or Extended) |

- Basic parts are kept loaded on the machines; Extended parts are loaded by hand, hence the fee. "Preferred Extended"
  parts are exempt from the loading fee on economic assembly (assembly FAQ).
- One part that economic assembly cannot place (e.g. an 0201, or a part only available for standard) moves the whole
  order to standard. Check each part's class with the pcb-part-selection skill.
- All parts on the top side keeps the board eligible for economic assembly.

## Lead time

Source: https://jlcpcb.com/help/article/pcb-fabrication-services-and-production-time (updated 9 Sep 2026). Board
up to 100x100 mm, FR-4 1.6 mm, 1 oz, HASL, green mask:

| Layers | 5 pcs | Up to ~50 pcs | Over ~50 pcs |
|---|---|---|---|
| 1-2 | 24 hours | 1-2 days | 5-6 days |
| 4 | 2-5 days | 2-5 days | 8 days |
| 6 | 6-7 days | 6-7 days | 7-8 days |

Fabrication only; assembly and shipping add to it.

## Cost, 2 vs 4 layers

**Unverified for today.** The live price is only on the quote page (https://cart.jlcpcb.com/quote). What could be
found:
- **Unverified:** JLC has run a "$2 for 5 pcs" offer reported as covering 1-2 layer boards up to 100x100 mm and 4-8
  layer boards up to 50x50 mm (green mask, 1 oz). The JLC page that described it (jlcpcb.com/blog/4-free) returned 404
  when checked; whether the offer still exists, and its terms, must be checked on the quote page.
- March 2024: small-batch 4-layer board charge cut from $75.1/m2 to $70.6/m2 (100 pcs of 100x100 mm = $70.60 board
  charge) - https://jlcpcb.com/news/discount-on-quality-4-layer-pcbs. A 2026 notice on the same site mentions FR-4
  price changes, so treat these as historical.

Practical guidance: for a handful of prototypes the 4-layer premium is typically small next to assembly, parts and
shipping, and a respin caused by a ground problem costs more than the difference. Quote both on jlcpcb.com with the
real size and quantity when cost is the deciding factor.
