# Sources

Manufacturer datasheets and application notes behind the battery references. TI documents are at
ti.com/lit/ds/symlink/<part>.pdf (datasheets) or ti.com/lit/an/<number>/<number>.pdf (app notes). Page references are
to the PDF page; "s" is a section number.

| Code | Document | Used for |
|---|---|---|
| BQ2407x | TI SLUS810N, BQ2407x Standalone 1-Cell 1.5-A Linear Battery Chargers with Power Path | Variants and VBAT(REG)/system output (p6), USB100/500 and ILIM (p9, p12), VIN-DPM 4.35-4.63 V (p12), VBAT(REG) 4.16-4.23 V, precharge 2.9-3.1 V, termination 10 %, timers 30 min / 5 h, KISET, TJ(REG) 125 C (p13), NTC trip 0/50 C with 10 k (p14), DPPM (s9.3.4), layout (s12.1) |
| BQ25185 | TI SLUSF65B, BQ25185 1-Cell 1A Standalone Linear Battery Charger With Power Path | VSET options incl. LiFePO4 3.6/3.65 V, ILIM 100/500/1100 mA (p1), IQ_BAT 4 uA, factory mode 3.2 uA, VINDPM tracking (p6), KISET 300 A-ohm, termination 10 % (p7), safety timer 6 h, VBATSC trickle 7 mA, NTC thresholds (p8), NTC 10 k beta 3435 (s6.3.9), status pins (s6.3.10) |
| BQ25606 | TI SLUSCK6C (rev. Sept 2021), BQ25606 Standalone 1-Cell 3.0-A Buck Battery Charger | NVDC power path, standalone (p1), ICHG / ILIM resistor setting (p6), VBUS operating range 3.9-13.5 V (p9), VINDPM 4.3 V tracking VBAT + 200 mV and D+/D- detection: DCP 2.4 A, unknown adapter set by ILIM (s9.3.2.3, p19), ILIM used for unknown adapters (p23) |
| BQ25895 | TI SLUSC88C, I2C Controlled Single Cell 5-A Fast Charger | Switching charger example, ship mode and 12 uA leakage (p1, p5, p11), D+/D- detection (s8.2.3.3), thermistor window (s8.2.7.5) |
| BQ24400 | TI SLUS498A, NiMH/NiCd fast-charge management IC | PVD termination 3.8 mV, max temperature and time backups (p1, p5) |
| BQ25570 | TI SLUSBH2G, nano power boost charger and buck converter | Harvester; MPPT at 80 % / 50 % of Voc, 16 s sampling (p4, p7, p13) |
| MCP73831 | Microchip DS20001984H, MCP73831/2 Li-Ion/Li-Polymer Charge Management Controllers | Regulation options 4.20-4.50 V (p1), +/-0.75 % (s4.6), termination options (p4), IREG = 1000 V / RPROG (s5.1.2), reverse discharge < 2 uA (s4.1-4.2), dissipation example 1.54 W (s6.1.1.3), 4.7 uF VBAT capacitor (s6.1.1.4), layout heatsink (s6.2), "1C preferred" (s6.1.1.1) |
| TI BQ297xx | TI SLUSBU9I, BQ297xx Voltage and Current Protection IC for Single-Cell Li-Ion | Threshold table (p3), normal-mode current 4/5.5 uA (p5), delays (p6), FET drive (s5.1.4-5.1.5), FET R_DS(on) and OCD design example (p19-20) |
| TI SLYT365 | Li-ion battery-charger solutions for JEITA compliance (Analog Applications Journal 1Q 2010) | Why cold/hot charging is dangerous; JEITA single-cell bands T1 0 C, T2 10 C, T3 45 C, T4 50 C, T5 60 C, 4.15/4.10 V (Figure 3) |
| TI SLYT118 | Powering electronics from the USB port | USB 2.0 100 mA unit load, 500 mA after enumeration |
| TI SLVA842 | USB PD Power Negotiations | PD required above 15 W (s1) |
| TI SWRA349 | Coin cells and peak current draw | CR2032 effective capacity vs pulse current; parallel capacitor; vendor spread |
| TI SLUA372 | Support of Multiple Li-Ion Chemistries With Impedance Track Gas Gauges | Gauge chemistry selection (s1-2) |
| BQ27441-G1 | TI SLUSBH1C, System-Side Impedance Track Fuel Gauge | 10 mOhm Kelvin sense resistor (p1, p4), mode currents (p6) |
| MAX17048 | Maxim/ADI 19-6171 Rev 7, 3 uA 1-Cell/2-Cell Fuel Gauge with ModelGauge | No sense resistor or learning, 3 uA hibernate / 23 uA active (p1-2) |
| TPS63802 / TPS63020 | TI SLVSEU9D / SLVS916I buck-boost converters | 1.3-5.5 V in, 11 uA Iq / 25 uA Iq (p1) |
| TPS7A02 | TI SBVS277C, 25-nA Iq 200-mA LDO | Iq, 270 mV max dropout at 200 mA for 3.3 V (p1) |
| TPS62840 | TI SLVSEC6D, 60-nA Iq step-down converter | 100 % mode 120 nA (p1, p7) |
| TLV757P | TI SBVS322C, 1-A low-Iq LDO | Ground current up to 33 uA (p5) |
| USB Type-C R2.0 | USB Type-C Cable and Connector Specification Release 2.0, Aug 2019 (usb.org) | Sink model (p156), VBUS only after attach (p139), CC1/CC2 independently terminated (p170), Rd 5.1 k +/-20 % / +/-10 % (Table 4-25, p236), vRd ranges (Table 4-36, p241), precedence of power sources (Table 4-17, p217) |
| Panasonic NCR18650B | Panasonic (Sanyo) NCR18650B spec sheet, version 13.11 R1 | 3.6 V nominal, 3200/3350 mAh, CC-CV 0.5C max 4.20 V, 1625 mA std 4 h, 65 mA cut-off, 2.5 V discharge cutoff, charge 0-45 C (0.25C below 10 C), discharge -20 to 60 C |
| Dubilier LP-503759 | Dubilier Li-polymer cell specification LP-503759-1S-3 (2012) | Pouch-cell ratings (s3), low-temperature capacity (s4.3), handling, PCM requirement, soldering limits, pack design (s6) |
| A123 ANR26650M1-B | A123 Systems datasheet MD100113-02 | LiFePO4 3.3 V nominal, CC/CV to 3.6 V |
| Energizer CR2032 | Energizer CR2032 datasheet, Form 2032NA0618 | 235 mAh to 2.0 V at 15 k, max reverse charge 1 uA, ~1 %/year self-discharge, child-safety compartment |
| Energizer E91 / L91 | Energizer alkaline AA and Ultimate Lithium AA datasheets | Primary cell voltages, capacity to 0.8 V, Li/FeS2 2.5 A continuous, -40 to 60 C |
| Energizer NiMH handbook | Energizer Nickel Metal Hydride Handbook and Application Manual | 0.9 V cutoff (p9), charge behaviour (p10), 0.1C 12-14 h and C/40 trickle (p11) |
| Energizer lithium coin handbook | Energizer Lithium Coin Handbook and Application Manual | Pulse effects and internal resistance of coin cells |
| Panasonic PLI-PSDS-01-EN | Panasonic Energy lithium-ion product safety data sheet | Do not solder directly onto batteries; storage at 30-50 % charge (s7); fire measures (s5); fire risk above 100 C (p1) |
| IATA Lithium Battery Guidance 2026 | IATA Guidance Document, Transport of Lithium Metal, Lithium Ion and Sodium Ion Batteries, revised for the 2026 regulations | UN 3480 30 % SoC and passenger-aircraft restriction (p4), Wh definition (p6), 20 Wh / 100 Wh thresholds (p7, p10), test summary (p8) |
| IEC 62133-2:2017 | IEC 62133-2:2017 (+A1:2021) scope, via IEC webstore / national standards bodies | Scope only; the test clauses were not read |
| JST PH series page | jst-mfg.com PH series product page | 2 A (AWG 24), 100 V, AWG 32-24, -40 to 105 C |
| Battery University BU-802b | batteryuniversity.com, "What does elevated self-discharge do?" | Secondary source only: self-discharge rates (Li-ion 1-2 %/month + 3 % protection circuit; NiMH 10-15 %/month) |

## Not verified from a primary source (marked where used)

- JST-PH battery lead polarity differing between vendors: community forums (Particle, RobotShop) and a SparkFun board
  errata note, not a JST document - JST does not define wire colour assignment.
- Genuine 18650 capacity ceiling around 3500 mAh (only NCR18650B's 3350 mAh verified).
- LiFePO4 discharge cutoff (~2.0-2.5 V), supercap voltage per cell, and the fraction of Li-ion capacity below about
  3.5 V: typical values; read the specific datasheet curve.
- DW01A + 8205A as the common hobby PCM: practice; thresholds not checked.
- Switched-divider circuit, ADC source impedance advice, and P-FET reverse-polarity behaviour on a charging battery
  input: standard practice.
- The "+/-0.5-1 %" spread of charge regulation is a summary of the BQ2407x and MCP73831 figures, not a general rule.
