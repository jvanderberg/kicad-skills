# Charging

Source codes in brackets are in `sources.md`. Follow the charger datasheet's design procedure; use this to choose the
part and to check its settings against the cell.

## The lithium charge profile (CC/CV)

1. **Precharge (trickle)** while the cell is deeply discharged: a small current (typically about 10 % of the fast
   rate) until the cell rises past a threshold near 3.0 V (BQ2407x: VLOWV 2.9-3.1 V [BQ2407x p13]). Below a further
   short-circuit threshold the charger only sources a few mA (BQ2407x: below 1.8 V [BQ2407x p13]; BQ25185: 7 mA below
   VBATSC [BQ25185 p8]). A cell that does not leave precharge before the precharge timer expires is faulty - the
   timer stops charging it.
2. **Constant current** at the programmed rate until the cell reaches the regulation voltage.
3. **Constant voltage** at VBAT(REG) (4.20 V +/- about 0.5-1 %: BQ2407x 4.16-4.23 V [BQ2407x p13]; MCP73831 +/-0.75 %
   [MCP73831 s4.6]) while the current tapers.
4. **Termination** when the current falls below the termination threshold (commonly 10 % of the fast rate: BQ2407x
   default 10 % [BQ2407x p13]; BQ25185 10 % [BQ25185 p7]; MCP73831 factory options, e.g. 5 % [MCP73831 p4]). Cell
   makers test with lower cut-offs (0.02C [Dubilier LP-503759 s3.5]; 65 mA on a 3250 mAh cell [Panasonic
   NCR18650B]); a higher termination current charges slightly less but stresses the cell less.
5. **Recharge** when the cell drops by a set amount; **safety timers** cap precharge and fast charge (BQ2407x default
   30 min precharge and 5 h fast charge, resistor-programmable [BQ2407x p13]; BQ25185 6 h [BQ25185 p8]).

**Charge current** comes from the cell datasheet: often 0.5C standard, sometimes 1C maximum, and lower when cold
(NCR18650B: 0.5C max, 0.25C below 10 C [Panasonic NCR18650B]). Set it with the charger's ISET/PROG resistor using
the datasheet equation (BQ2407x: ICHG = KISET / RISET with KISET 797-975 A-ohm [BQ2407x p13]; BQ25185: KISET
300 A-ohm typical [BQ25185 p7]; MCP73831: IREG(mA) = 1000 V / RPROG(kOhm) [MCP73831 s5.1.2]). Use the minimum and
maximum K factor to check that the worst case stays within the cell's limit.

**Do not put a large load directly on the cell during charging with a charger that has no power path:** the charger
sees the load current as charge current and may never terminate, or terminate early, and the timer expires. Use a
power-path charger (below) or switch the load off while charging.

## Temperature: NTC and JEITA

Lithium plating while charging below 0 C permanently damages the cell and can lead to internal shorts; high
temperature at high voltage accelerates electrolyte reactions and, in the limit, thermal runaway [TI SLYT365].
Therefore:
- **Always use the charger's TS/NTC input with a thermistor in contact with the cell** (not on the far side of the
  board). A typical standalone charger suspends charging outside 0-50 C with a 10 k NTC (BQ2407x: 0 C and 50 C
  trip points with a 10 k Vishay Type 2 curve NTC [BQ2407x p14]; BQ25185: 10 k, beta 3435 K [BQ25185 s6.3.9]). Check
  that the window sits inside the cell's charge range (often 0-45 C) - add compensating resistors or choose a
  charger whose thresholds match.
- **JEITA** (single-cell handheld guideline): no charge below T1 (0 C); reduced current between T1 and T2 (10 C);
  full current and voltage from T2 to T3 (45 C); reduced charge voltage from T3 to T5 (60 C, e.g. 4.15 V then
  4.10 V maximum); no charge above T5 [TI SLYT365, Figure 3]. Chargers with JEITA support implement these bands;
  simple chargers have only hot and cold cutoffs, which is acceptable if the window is set to the cell's narrower
  limits.
- Do not disable the TS function to "make it work" on the bench. If the NTC is not fitted yet, use the datasheet's
  fixed resistor (BQ25185: 10 k to GND [BQ25185 s6.3.9]) and accept that the board then has no temperature
  protection.
- Chargers also regulate their own die temperature (TJ(REG) 125 C on BQ2407x [BQ2407x p13]) by cutting the current;
  that protects the IC, not the cell.

## Linear vs switching

| | Linear | Switching (buck) |
|---|---|---|
| Heat | (Vin - Vbat) x Icharge: all the headroom is lost | P_out x (1/eta - 1) |
| Practical current from 5 V | up to about 0.5-1 A with good copper | 1-5 A |
| Parts | IC + a few resistors and capacitors | + inductor; layout like any buck |
| EMI | quiet | switching noise |

**Worst case for a linear charger** is the start of fast charge: maximum input and minimum battery voltage
[MCP73831 s6.1.1.3]. Example (hypothetical): 5.25 V input, 3.0 V battery, 1 A: (5.25 - 3.0) x 1 = 2.25 W - too much
for a small QFN without thermal regulation cutting the current. Microchip's example is 1.54 W for 550 mA at 5.5 V
into 2.7 V, which forces thermal regulation in SOT-23-5 [MCP73831 s6.1.1.3]. Thermal regulation makes this safe
but slow; above about 500 mA from 5 V, plan real copper (`layout-and-mechanical.md`) or use a switching charger
(e.g. BQ25895, 5 A, I2C [BQ25895 p1]).

## Input: current limit, DPM and USB

- **Input current limit** keeps the charger plus system inside what the source can give. USB 2.0 allows 100 mA
  before enumeration and 500 mA after [TI SLYT118]; chargers offer 100/500 mA modes and a resistor-set limit
  (BQ2407x: 100 mA, 500 mA or ILIM resistor up to 1.5 A [BQ2407x p9, p12]; BQ25185: 100, 500 or 1100 mA [BQ25185 p1]).
- **VIN-DPM** reduces charge current when the input voltage sags, so a weak port or long cable is not pulled into
  collapse (BQ2407x: 4.35-4.63 V [BQ2407x p12]; BQ25185 tracks VBAT + 330 mV [BQ25185 p6]). For solar inputs the same
  loop sets the operating point (below).
- **Status pins** (CHG/STAT, PGOOD) are open-drain; pull them up to the MCU rail or drive an LED from the input, not
  from the battery, or the LED becomes a permanent drain.

## Power path (load sharing)

A power-path charger feeds the system from the input and charges the cell with what is left, and lets the cell
supplement the system when the input cannot supply a peak (BQ2407x DPPM and battery supplement mode [BQ2407x p1,
s9.3.4]). Benefits: the system runs with a dead or missing cell, termination works because the charger measures only the
cell current, and the cell is not cycled while plugged in [BQ2407x p1]. Watch the system-output behaviour per
variant: BQ24072 tracks VBAT + 225 mV, BQ24073/74 regulate 4.4 V, BQ24075/79 pass the input up to 5.5 V [BQ2407x p6],
so downstream regulators must accept the highest value. Without a power-path charger, an ideal-diode or P-FET switch
from VBUS to the system rail with the charger on the cell is the discrete equivalent (practice).

## USB-C as a 5 V sink

- **Pull down CC1 and CC2 each through its own 5.1 k resistor to GND.** Both pins shall be independently terminated
  [USB Type-C R2.0 p170]; a single shared resistor is a common mistake that some sources reject. A Type-C source does
  not turn VBUS on until it detects Rd [USB Type-C R2.0 p139], so a board without Rd gets no power from C-to-C cables.
- Rd is 5.1 k: +/-20 % is allowed if the sink does not detect current capability, +/-10 % if it does [USB Type-C
  R2.0 Table 4-25, p236]. Use 1 % resistors.
- **Current advertisement:** measure the CC voltage across Rd (on whichever CC pin is connected) with an ADC or
  comparator: 0.25-0.61 V is default USB power, 0.70-1.16 V is 1.5 A, 1.31-2.04 V is 3.0 A at 5 V [USB Type-C R2.0
  Table 4-36, p241]. The sink shall keep its load within the detected limit [USB Type-C R2.0 p156]. If you do not
  measure, assume default USB power and set the input limit to 500 mA.
- **USB PD is not needed for 5 V.** Above 15 W (5 V 3 A) or for 9-20 V, use a PD sink controller [TI SLVA842 s1].
- Older BC1.2 chargers advertise via D+/D-; chargers like the BQ25895 detect them [BQ25895 s8.2.3.3]. A simple
  resistor-only sink ignores BC1.2.
- Protect VBUS: TVS at the connector, the charger's input OVP (BQ2407x 6.6 V or 10.5 V [BQ2407x p6]; BQ25185 25 V
  tolerant [BQ25185 p1]), and the hot-plug guidance in the **pcb-power-supply** skill's `input-protection.md`.

## Solar

A solar panel is a current source whose power peaks at a voltage below its open-circuit voltage; a charger that
lets the panel collapse to the battery voltage wastes most of it. Use a charger with VIN-DPM / VINDPM set to the
panel's maximum-power voltage, or an MPPT harvester. The BQ25570 samples the open-circuit voltage every 16 s and
regulates at 80 % (or 50 %, or a resistor-set fraction) of it; solar cells typically have their maximum power point
near 80 % of Voc [BQ25570 p4, p7, p13]. Size the panel for the worst season's insolation, and keep the
NTC: a cell in a sealed box in the sun can exceed 45 C.

## NiMH charging

- Safe and simple: 0.1C for 12-14 h with a timer, then trickle below 0.025C [Energizer NiMH handbook p11].
- Faster (2-3 h) charging needs a smart charger [Energizer NiMH handbook p11]: termination on peak voltage detection
  (PVD / -dV, a few mV after a hold-off period so the initial voltage spike does not stop the charge), with maximum
  temperature and maximum time as backups (BQ24400: PVD threshold 3.8 mV at its BAT input, plus temperature and
  timer [BQ24400 p1, p5]). Voltage and temperature rise sharply at full charge as the cell turns energy into heat
  and pressure [Energizer NiMH handbook p10].
- Do not charge NiMH with a lithium CC/CV charger.
