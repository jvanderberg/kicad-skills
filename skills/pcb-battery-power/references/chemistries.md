# Chemistries, cells and packs

Source codes in brackets are in `sources.md`. The cell's own datasheet overrides every generic number here: charge
voltage, charge current, charge temperature and discharge cutoff vary between cell models.

## Comparison (single cell)

| Chemistry | Nominal | Max charge | Typical cutoff | Energy | Safety | Charging |
|---|---|---|---|---|---|---|
| Li-ion / Li-polymer (LiCoO2/NMC/NCA) | 3.6-3.7 V | 4.20 V (4.35-4.4 V for HV cells) | 2.5-3.0 V | Highest | Needs protection; fire risk if abused | CC/CV, single IC |
| LiFePO4 | 3.2-3.3 V | 3.6-3.65 V | ~2.0-2.5 V | Lower | Much more tolerant | CC/CV at 3.6 V |
| NiMH | 1.2 V | (current-controlled) | 0.9-1.0 V | Medium | Benign; vents if overcharged hard | Peak/-dV, temperature, timer |
| Alkaline (Zn/MnO2) | 1.5 V | **Never charge** | 0.8-1.0 V | Medium; poor at high current | Leaks when flat | None |
| Lithium primary AA (Li/FeS2) | 1.5 V | **Never charge** | 0.8-1.0 V | High, good when cold | Good | None |
| Lithium coin (Li/MnO2, CR) | 3.0 V | **Never charge** | 2.0 V | Small; high IR | Ingestion hazard | None |
| Supercapacitor (EDLC) | - | Rated V (2.5-3 V per cell) | Any | Very low | Over-voltage destroys it | Current-limited, balance in series |

Values verified from: NCR18650B 4.20 V / 2.5 V cutoff / 3.6 V nominal [Panasonic NCR18650B]; pouch LP-503759 4.20
V +/- 0.05 V, 2.75 V cutoff, absolute maximum 4.25 V [Dubilier LP-503759]; HV charge settings of 4.35/4.4 V exist on
chargers (MCP73831 4.20/4.35/4.40/4.50 V options [MCP73831 p1]; BQ24078 4.35 V [BQ2407x p6]); LiFePO4 3.3 V
nominal, 3.6 V CC/CV charge [A123 ANR26650M1-B]; NiMH 1.2 V nominal, 0.9 V cutoff typical [Energizer NiMH handbook
p9]; alkaline 1.5 V, capacity to 0.8 V [Energizer E91]; Li/FeS2 AA 1.5 V, -40 to 60 C [Energizer L91]; CR2032 3.0 V,
235 mAh to 2.0 V [Energizer CR2032]. LiFePO4 cutoff and supercap ratings are typical ranges (not verified here) - read
the part's datasheet.

## Li-ion and Li-polymer (the usual choice)

- Charge only with CC/CV at the cell's charge voltage; never above its absolute maximum (often 4.25 V for 4.20 V
  cells [Dubilier LP-503759 s6]). A charger set for 4.35 V on a 4.20 V cell overcharges it.
- Charging temperature is narrower than discharge: 0 to 45 C charge, -20 to 60 C discharge are common
  [Panasonic NCR18650B; Dubilier LP-503759]. Below 10 C some cells require a reduced rate (NCR18650B: 0.25C)
  [Panasonic NCR18650B].
- Standard charge rate is often 0.5C (NCR18650B: 1625 mA standard for a 3250 mAh cell, CC-CV 0.5C max, 4 h)
  [Panasonic NCR18650B]; some pouch cells allow 1C quick charge [Dubilier LP-503759 s3.5]. Charger datasheets
  quoting "1C preferred" [MCP73831 s6.1.1.1] do not override the cell's limit.
- Capacity is specified at a low rate and room temperature; at 0 C and -10 C one pouch cell guarantees only 80 % and
  70 % [Dubilier LP-503759 s4.3.4-4.3.5].
- Self-discharge is low (roughly 1-2 %/month, more when full and hot) plus the protection circuit's drain
  [Battery University BU-802b - secondary source].

## LiFePO4

Safer chemistry and long cycle life, but lower voltage and energy. Charge to 3.6-3.65 V (A123 standard charge:
CC/CV to 3.6 V [A123 ANR26650M1-B]); some single-cell chargers have a LiFePO4 setting (BQ25185: 3.6 V or 3.65 V
[BQ25185 p1]). The discharge curve is flat, so a voltage reading says little about state of charge until the cell is
nearly empty; use coulomb counting if the remaining capacity matters. Many 3.3 V loads can run directly from the
cell (3.0-3.6 V) if their supply range allows it.

## NiMH

- 1.2 V nominal, 0.9 V per cell end-of-discharge for moderate rates [Energizer NiMH handbook p9]. Driving a cell into
  reversal (possible in a series pack) damages it; stop before the weakest cell is empty.
- Charging is the hard part: see `charging.md`. A 0.1C charge for 12-14 h is safe and simple; trickle below 0.025C
  (C/40) [Energizer NiMH handbook p11]. Fast charging needs peak-voltage / -dV detection with temperature and timer
  backups.
- Self-discharge is high (10-15 %/month) except in low-self-discharge types [Battery University BU-802b - secondary].

## Primary cells (alkaline, lithium AA, coin cells)

- **Never charge a primary cell**, and never let a supply back-feed one. A CR2032 allows a reverse charge of only
  1 uA [Energizer CR2032]; a coin cell used as a backup next to a powered rail needs a blocking diode (choose a
  low-leakage one) or an OR-ing switch so no current flows into it.
- Alkaline capacity collapses at high current; Li/FeS2 AA cells handle 2.5 A continuous and cold [Energizer L91].
- **Coin cells:** rated capacity is at a light load (CR2032: 235 mAh at 15 kOhm, about 0.19 mA) [Energizer CR2032].
  Internal resistance is tens of ohms and rises as the cell discharges, so a radio pulse sags the voltage below the
  MCU's brown-out long before the rated capacity is used. TI measured some CR2032 brands delivering only about 50 % of
  rated capacity with 15-30 mA pulses; going from 15 to 30 mA peak cost only about 9 % on average, and a capacitor in
  parallel with the cell improved poor cells by more than 40 % [TI SWRA349]. Design for microamp averages, put a
  low-leakage bulk capacitor across the cell for pulses, and keep the average current low rather than chasing a
  "15 mA limit".
- Coin cells are a serious ingestion hazard for children; the holder or battery door needs a tool or two independent
  movements to open [Energizer CR2032].

## Supercapacitors

Useful for hold-up (RTC, last-gasp writes) and as the store in energy harvesting (the BQ25570 harvester can charge
a supercap or a cell [BQ25570 p1]). Energy is 0.5 x C x (V1^2 - V2^2) between the start voltage and the minimum the
load accepts - small. Limit the charging current, never exceed the rated voltage, and balance cells in series.
Leakage current can exceed a sleeping MCU's current; read it from the datasheet.

## Buying and choosing cells

- **Genuine cells from a reputable distributor.** Counterfeit and rewrapped cells (18650s sold as 6000-9900 mAh) are
  common; a genuine 18650 is in the 3000-3500 mAh range (NCR18650B: 3350 mAh typical [Panasonic NCR18650B]). Distrust
  any rating far above the best name-brand parts, and ask for the cell's datasheet.
- **Protected vs unprotected.** A "protected" 18650 has a small PCM under its wrapper (and is slightly longer - check
  the holder). A Li-polymer pouch cell sold for hobby use usually has a PCM on its tab; the cell maker requires one
  [Dubilier LP-503759 s6.9]. Treat a cell without a PCM as needing protection on the board (`protection-and-safety.md`).
- **Discharge rating.** Check the cell's maximum continuous current against your peak load (the pouch above: 2 A for
  1350 mAh [Dubilier LP-503759 s3.6]); the PCM's overcurrent trip may be lower than the cell's rating.
- **Connections.** Use a cell holder (with the protected-cell length in mind) or a pack with factory spot-welded tabs
  and wire leads. **Never solder directly to a cylindrical cell** [Panasonic PLI-PSDS-01-EN s7]; the heat damages the
  seal and separator. Soldering to pouch tabs is permitted by some makers only with limits (e.g. below 300 C, under
  3 s, cell body never heated) [Dubilier LP-503759 s6.17].
- **Connector polarity.** 2-pin JST-PH battery leads have no polarity standard between vendors: about half put red
  on one side, half on the other [community and vendor reports - see sources]. Before the first connection, measure
  the lead with a meter against the board's silkscreen, mark polarity clearly on the board, and give the battery input
  reverse-polarity protection if users will plug in their own packs.
- **Connector and wire rating.** JST-PH is rated 2 A with 24 AWG wire, 26-32 AWG accepted [JST PH series page]. Rate
  the connector and wire for the protector's overcurrent trip (what flows in a fault), not the average load.
- Do not mix old and new cells, or different types, in one pack [Dubilier LP-503759 s6.19].
