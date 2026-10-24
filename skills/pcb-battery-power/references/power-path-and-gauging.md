# Regulation, sleep current, battery life and gauging

Source codes in brackets are in `sources.md`. Regulator sizing is in the **pcb-power-supply** skill; this covers what
is different when the source is a cell.

## Regulating 3.3 V from a 1S lithium cell

The cell spends its life between 4.2 V and its cutoff (3.0 V or lower), so a 3.3 V rail is sometimes below and
sometimes above the input.

| Option | Uses the cell down to | Notes |
|---|---|---|
| Buck-boost (e.g. TPS63802: 1.3-5.5 V in, 11 uA Iq [TPS63802 p1]; TPS63020: 25 uA Iq [TPS63020 p1]) | the cutoff | Full capacity; more parts and Iq; check light-load efficiency |
| Low-dropout LDO (e.g. TPS7A02: 25 nA Iq, 270 mV max dropout at 200 mA for 3.3 V [TPS7A02 p1]) | about 3.3 V + dropout at your current | Simple and quiet; loses the tail of the discharge |
| Buck with 100 % duty mode (e.g. TPS62840: 60 nA Iq, 120 nA in 100 % mode [TPS62840 p1, p7]) | about 3.3 V + I x R_on | Efficient from 4.2 V; tracks the cell in dropout |
| Run the load from the cell directly | the load's minimum | LiFePO4 (3.0-3.6 V) with 3.6 V-tolerant loads |
| Lower the rail (3.0 V or 2.8 V) | lower | If every part on the rail allows it |

How much of the capacity an LDO loses depends on the cell's discharge curve at your load and temperature: read the
cell datasheet's curve at the voltage where regulation stops. For many Li-ion cells at moderate loads the region
below about 3.5 V holds a modest fraction of the capacity, but more when cold or at high current (estimate - check
the curve). Account for the regulator's input under load: the cell's internal resistance and the protector's FETs
drop voltage at peaks, so a 300 mA radio burst can push an LDO into dropout earlier than the open-circuit voltage
suggests.

The regulator's input must survive the charger's system output (up to the USB input on some power-path chargers -
BQ24075 passes up to 5.5 V [BQ2407x p6]).

## Sleep-current audit

List every part that draws current with the device asleep and add it up - it often dominates life for a device that
sleeps most of the time. Typical entries:
- regulator quiescent current at no load (not shutdown current, unless it is actually shut down): from 25 nA to tens
  of uA in the parts above; an LDO's ground current can be far above its headline Iq at load (TLV757P: up to 33 uA
  ground current [TLV757P p5]);
- charger battery-side drain with no input (BQ25185: 4 uA typical, 5 uA maximum [BQ25185 p6]; MCP73831 reverse
  discharge below 2 uA [MCP73831 s4.1-4.2]);
- protector (BQ2970x: 4 uA typical [TI BQ297xx p5]) and fuel gauge (MAX17048: 3 uA hibernate, 23 uA active
  [MAX17048 p1-2]; BQ27441-G1: 9 uA hibernate, 21 uA sleep, 93 uA normal [BQ27441-G1 p6]);
- dividers on the battery (V / R_total, continuous), pull-ups held low, LED indicators, sensors that are not put in
  their own sleep mode, leakage through I/O protection diodes into unpowered parts (back-powering);
- the MCU in its real sleep mode with its RTC, brown-out detector and retained RAM as configured.

Measure it on the bench (`verification.md`) - an unmeasured sleep current is a guess.

## Battery-life estimate

```
average current   I_avg = sum(I_mode x t_mode) / t_period
usable capacity   C_use = C_rated x f_window x f_temp x f_age
life              t = C_use / (I_avg + I_selfdischarge)
```
- f_window: fraction of the capacity between full and the voltage where your system stops (regulator dropout, brown-out
  or the protector's UVP), at your load - from the cell's discharge curve.
- f_temp: capacity at the coldest operating temperature (one pouch cell guarantees 80 % at 0 C and 70 % at -10 C
  [Dubilier LP-503759 s4.3.4-4.3.5]).
- f_age: end-of-life capacity after the cycles you expect (often specified as 80 % after a few hundred cycles in the
  cell datasheet).
- Self-discharge as an equivalent current: Li-ion roughly 1-2 %/month plus about 3 %/month for a protection circuit
  [Battery University BU-802b - secondary]; NiMH 10-15 %/month; primary lithium and alkaline only a few % per year
  (CR2032: about 1 %/year [Energizer CR2032]).
- Coin cells: rated capacity is at a light load; apply the pulse and internal-resistance limits in `chemistries.md`.

**Worked example (hypothetical numbers).** A sensor node on a 1000 mAh Li-polymer cell sleeps at 15 uA and wakes
every 60 s for 200 ms at 20 mA:
```
I_avg   = 15 uA + 20 mA x 0.2 s / 60 s          = 15 + 67   = 82 uA
C_use   = 1000 mAh x 0.85 (window) x 0.9 (cold) x 0.8 (aged)  = 612 mAh
I_self  = 1000 mAh x 2 %/month / 730 h          ~ 27 uA     (as large as the sleep current)
life    = 612 mAh / (0.082 + 0.027) mA          ~ 5600 h    ~ 7.7 months
```
The radio bursts dominate; halving the wake rate gains more than halving the sleep current, and the self-discharge
term is not negligible.

## Measuring the battery voltage

- A divider straight across the cell draws V / R continuously: 2 x 1 MOhm draws 2.1 uA at 4.2 V. High-value dividers
  are fine if the ADC is fed from a capacitor (for example 100 nF from the divider midpoint to ground) that charges
  the ADC's sampling capacitor, and the reading is taken slowly; check the ADC's maximum source impedance and the
  pin leakage, which become errors at MOhm values (practice).
- A **switched divider** draws nothing between readings: a P-FET high-side switch (with its gate pulled to the
  battery) driven through a small N-FET from a GPIO, or a load switch. Do not switch the bottom of the divider alone:
  the ADC pin then sees the full battery voltage through the top resistor, above the MCU's supply (practice).
- Keep the ADC input within the MCU's supply at all battery voltages; scale for 4.2 V (4.35-4.4 V for HV cells) plus
  margin.
- Measure under a known load, or note the load: Li-ion voltage sags under current, so a reading during a radio burst
  understates the state of charge.

## Fuel gauges

| Method | How | Good for |
|---|---|---|
| Voltage only (MCU ADC + lookup) | open-circuit voltage curve | coarse indication on Li-ion; poor on LiFePO4 and NiMH (flat curves) |
| Model-based voltage gauge (MAX17048 ModelGauge) | voltage plus a cell model; no sense resistor, no learning cycles [MAX17048 p1] | small 1S boards: percentage with almost no extra parts |
| Coulomb counting / Impedance Track (BQ27441-G1) | integrates current through a 10 mOhm 1 % sense resistor, Kelvin-connected, plus voltage and impedance [BQ27441-G1 p1, p4] | accurate remaining capacity, aging, LiFePO4 |

Configure the gauge for the actual cell: chemistry ID or model, design capacity, termination voltage. A gauge set for
the wrong chemistry reports confidently wrong numbers [TI SLUA372 s1-2].

## Ship mode, disconnect and low-battery cutoff

- **Ship mode / load disconnect** isolates the cell from the system for storage and transport, leaving only the
  IC's own drain: BQ25895 BATFET ship mode (12 uA battery leakage, exit by holding QON low [BQ25895 p1, p5, p11]);
  BQ25185 factory mode 3.2 uA [BQ25185 p6]; BQ24075/79 SYSOFF disconnect [BQ2407x p6]. A plain slide switch in series
  with the cell works too, rated for the peak current.
- **Low-battery cutoff in firmware:** stop radios, motors and LEDs, save state and enter the deepest sleep (or shut
  the regulator off) at a voltage with margin above the protector's UVP, so the cell is not left at the protector's
  threshold, which then keeps discharging slowly through the protector's own drain.
- **And in hardware:** a regulator enable or UVLO (an EN divider from the cell, or a supervisor) that turns the system
  off below a set voltage regardless of firmware - a crashed MCU or a stuck-on peripheral must not drain the cell into
  the protector. The protector's UVP is the last line, not the plan.
