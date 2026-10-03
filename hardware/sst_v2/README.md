# SST v2 Mainboard — Rev. 3 (KiCad)

DAQ-Mainboard für Sufni Suspension Telemetry: 24-bit-ADC für Fork- und Shock-Poti,
Takt für vier IMUs, microSD, RTC, Pico 2 W. Entwurfsgrundlage und Begründungen:
`firmware/docs/plan-ads131m04-icm42686.md`.

```bash
open -a "KiCad" /Users/niels/Telemetry/sst/hardware/sst_v2/sst_v2.kicad_pro
```

Nur diesen Ordner bearbeiten. Vor Skript-Änderungen KiCad schließen
(`~*.lck`), sonst überschreibt die GUI beim Speichern.

## Platine

60 × 90 mm, 4 Lagen, 1,6 mm FR4, ENIG. 4× M3-NPTH (H1–H4).

Platzierung:

- Oben: Pico 2 W auf Buchsenleisten. Der Pico mit USB-Buchse liegt ganz innerhalb der Platine (x 91,7–144,1 mm, Rand bei 144,55 mm).
- Links: Poti-Eingang (J_POT1 am Rand, ESD D2–D4, CMCs), darunter Analogblock (LDO, ADC, Opamp, RC-Netz). Der Analogblock liegt weit weg von Funkmodul und SMPS des Pico.
- Mitte: RTC-Batterie BT1 unter dem Pico, Öffnung zum Pico. Der Bereich zwischen BT1 und den Pico-Buchsenleisten ist frei von Bauteilen, damit die Zelle heraus- und hineingleitet.
- Rechts: OLED- und Taster-Stecker am Rand neben ihren Pico-Pins, Buzzer BZ1, Stromversorgung (D1, D_VSYS1, C26), microSD. Der Körper von J_SD1 endet 0,25 mm vor der Platinenkante.
- Oberkante (x 113–123,6 mm, y 48,3–55,2 mm, zwischen Q_RP1 und J_DEBUG1, außerhalb des Pico): Lader U_CHG1 mit C_CHG1/C_CHG2, R_PROG, R_STAT1/R_STAT2. Thermalfläche: Zone „Lader Thermal“ (GND, F.Cu, Priorität 2, volle Anbindung) über den Laderbereich und den Streifen über J_DEBUG1, gefüllt 0,77 cm² zusammenhängend (0,49 cm² im Laderbereich). Sechs GND-Vias 0,6/0,3 mm links neben dem VSS-Pad (Pin 2) zur GND-Lage In1. +VBUS und +VBAT kommen auf B.Cu, F.Cu bleibt dort fast ganz GND.
- Unter dem Pico: R50 (ADC_RST) neben GP7. Soft-Power-Steuerung (U_PWR1, C_PWR1, Q_PWR2, Q_PWR3, R_PWR2–R_PWR4, D_PWR1) und Fuel Gauge (U_FG1, C_FG1) zwischen den Buchsenleisten bei x 120–135 mm, y 61–74 mm (Bauhöhe ≤ 1,1 mm, Buchsenleisten 8,5 mm). `sst_v2.kicad_dru` erlaubt die Courtyard-Überdeckung mit U1 nur für diese Teile.
- Unter der unteren Pico-Buchsenleiste (außerhalb des Pico): Lastschalter Q_PWR1 (119,6 / 82,1) mit Gate-Pull-up R_PWR1 (122,9 / 82,1), direkt vor C26.
- Pico-Antenne (Ende gegenüber USB, x < 101 mm): Rule Area „Pico antenna: keepout“ auf allen Kupferlagen, ohne Leiterbahnen, Vias und Pours. Sie deckt den Raum zwischen den Buchsenleisten (y 61,3–76,1 mm) und das Pico-Ende über die volle Breite plus 1 mm Rand ab (x 90,7–92,1 mm, y 57,1–80,2 mm). Die Streifen der Buchsenleisten bleiben frei, damit die Leitungen an Pin 17–24 nach außen laufen. In1 (GND) und In2 (+3V3_DIG) haben dort eine Aussparung.
- Fiducials FID1–FID3 (1 mm, Maske 3 mm) auf F.Cu: (135,95 / 54,8), (89,5 / 106,8), (136,95 / 101,3). Alle ≥ 5 mm von der Kante, außerhalb von Pico und Steckern.
- Montagelöcher: Alle Courtyards liegen ≥ 3,5 mm von der Bohrungsmitte (Platz für Schraubenkopf oder Scheibe Ø 7 mm).
- Unten: IMU-Stecker, Taktteiler und Taktpuffer.
- Digitalleitungen (IMU, SD, UI) laufen außerhalb des Analogblocks. Die ADC-SPI-Leitungen laufen im Poti-Block nur auf B.Cu, getrennt durch die GND-Lage In1.

| Lage | Inhalt |
|---|---|
| F.Cu | Bauteile, Signale, GND-Pour |
| In1.Cu | GND, durchgehend |
| In2.Cu | +3V3_DIG; Insel +3V0_ANA unter der analogen Seite von LDO/ADC/Opamp (x 94,3–108,5 mm, y 112,2–132,5 mm, dazu Streifen y 107,8–112,2 mm ab x 84,9 mm). Die digitale Seite von LDO und ADC (x < 94,3 mm) liegt über +3V3_DIG. |
| B.Cu | Signale, GND-Pour |

Fertigungsregeln (PCBWay): Leiterbahn/Abstand ≥ 0,2 mm, Via 0,6/0,3 mm (+3V3_DIG: 0,7/0,4 mm,
Power: 0,8/0,4 mm), Via-Restring ≥ 0,15 mm, Kupfer–Kante ≥ 0,3 mm, Lötstopp-Steg ≥ 0,1 mm
(grüner Lötstopp). Silkscreen: Strichbreite ≥ 0,15 mm, Texthöhe ≥ 0,8 mm (PCBWay-Minimum). `sst_v2.kicad_pro`
prüft Restring und Textstrich mit 0,15 mm, Texthöhe mit 0,8 mm.

## Schaltung

| Block | Bauteile | Kurzbeschreibung |
|---|---|---|
| ADC | U2 ADS131M04 | CH0 Fork, CH1 Shock, CH2 Poti-Speisung (ratiometrisch), CH3 an GND. AVDD 3,0 V, DVDD = Netz +3V3_DVDD aus +3V3_DIG über FB1 (Logikpegel = Pico-Pegel, PWR_FLAG hinter FB1). CAP 220 nF. SYNC/RESET (ADC_RST) über R50 100 Ω an GP7 (ADC_RST_MCU), Pull-up R1, C4. |
| Analog-LDO | U_ANA_LDO1 TPS7A4700 (RGW) | 3,3 V → 3,0 V, ANY-OUT: nur 1P6V (Pin 8) an GND, übrige ANY-Pins offen. SENSE an OUT. NR 10 nF (C25), IN 10 µF (C22), OUT 22 µF (C6). |
| Poti-Speisung | U_AAF1 TLV4333 (A), R32/R33 20k/10k 0,1 %, C35 | 1,0 V Referenz, gepuffert, 47 Ω (R34) auf POT_EXC, Messung über R35/C36 an AIN2P. |
| Schleifer | U_AAF1 (B, C), R36/R37, R8/R14, C9/C12 | Opamp-Puffer, danach 1 kΩ + 10 nF an AINxP. AINxN = Poti-Masse (Remote Sense), R9/R15 0 Ω als Sternpunkt. |
| Poti-Stecker | J_POT1 JST-SH 6 → HR30 6p | 1 POT_EXC, 2 Fork-Schleifer, 3 Fork-Masse, 4 Shock-Schleifer, 5 Shock-Masse, 6 Schirm/GND. ESD D2–D4, CMC L_FORK/L_SHOCK (DLW5BTM251SQ2L). |
| Takt | Y1 ECS-2520MVLC 8,192 MHz, U_DIV1 74HC4040, U_CLKBUF1 74LVC125 | XO → 33 Ω → ADC CLKIN; XO → 4040 Q7 = 32,000 kHz → 2 Puffer → 33 Ω → IMU-CLKIN A/B. |
| IMU | J_IMU_A1/B1 JST-SH 12 → HR30 12p | 1 IMU_3V3 (FB2), 3 SCLK, 5 MOSI, 7 MISO, 8 CLKIN, 10/11 CS, 2/4/6/9/12 GND. 33 Ω in allen DAQ-Ausgängen. |
| Strom | J_BAT1, Q_RP1, Q_PWR1, D1, D_VSYS1 | LiPo (JST-PH) → Q_RP1 DMG2305UX (Verpolschutz) → +VBAT → Q_PWR1 DMG2305UX (Soft-Power-Schalter) → +VBAT_SW (TVS D1, C26–C28) → D_VSYS1 PMEG3020EH → VSYS. D_VSYS1 verhindert, dass USB-VBUS direkt in den Akku speist. Kein externer Schalter mehr (J_PWR1 entfällt). |
| Soft-Power | U_PWR1 MAX16150AUT+T, Q_PWR1 DMG2305UX, Q_PWR2/Q_PWR3 2N7002, R_PWR1–R_PWR4 100k, C_PWR1 100 nF, D_PWR1 RB751S40 | U_PWR1 VCC an +VBAT. Taster SW_L1 → PWR_BTN → PB_IN (interner Pull-up 1,2–2,0 MΩ an VCC). Drücken > 50 ms: OUT (PSW_EN) high → Q_PWR2 zieht PSW_GATE auf GND → Q_PWR1 leitet. R_PWR1 hält Q_PWR1 sonst aus, R_PWR2 hält Q_PWR2 aus, solange OUT undefiniert ist. Aus per Firmware: GP28 (PWR_OFF) high → Q_PWR3 zieht ~CLR low → OUT low. R_PWR4 hält Q_PWR3 ohne Firmware aus. ~CLR-Pull-up R_PWR3 an OUT (Datenblatt-Empfehlung): kein VBAT-Pegel an einem GPIO. Halten > 8 s (Version A): OUT low, Hardware-Aus. ~INT offen. BTN_L (GP4, R27 10k an +3V3_DIG) liegt über D_PWR1 (Anode BTN_L, Kathode PWR_BTN) am Taster: SW_L1 bleibt UI-Taste. |
| Fuel Gauge | U_FG1 MAX17048G+T10, C_FG1 100 nF | VDD (Messeingang) und CELL an +VBAT, dauerhaft versorgt. I2C 0x36 am PIO-I2C (DISP_SDA/DISP_SCL, R25/R26). CTG, QSTRT, EP an GND, ~ALRT offen (kein GPIO frei). |
| Lader | U_CHG1 MCP73831T-2ACI/OT, C_CHG1/C_CHG2 4,7 µF, R_PROG 3,3k, R_STAT1/R_STAT2 10k/10k | Platz an der Oberkante außerhalb des Pico, mit Thermalfläche (GND-Zone 0,77 cm² an VSS, 6 Vias zu In1). VDD an +VBUS (Pico Pin 40), Ausgang an +VBAT (vor dem Schalter): Laden auch bei ausgeschaltetem Gerät (Q_PWR1 offen). 4,20 V, 300 mA (I = 1000 V / R_PROG; 500 mA mit 2,0k). STAT über Teiler 10k/10k an GP6 (CHG_STAT): Laden = 0 V, fertig = 0,5 × VBUS (2,5 V bei 5,0 V, max. 2,6 V bei 5,25 V), ohne VBUS hochohmig → 0 V. USB kommt über ein Kabel von einer Gehäusebuchse in die Micro-USB-Buchse des Pico. |
| RTC | U3 DS3231SN, BT1 CR1220 | VBAT direkt an der Zelle, RST offen. I2C gemeinsam mit OLED und U_FG1 (PIO, R25/R26 4,7k). |
| microSD | J_SD1 DM3AT | SPI0. Pull-ups: SD_CS 10k (R31), DAT1 47k (R48), DAT2 47k (R49). |
| UI | SW_L1/SW_R1 (JST-SH 2), BZ1 PS1240P02BT, J_OLED1, J_DEBUG1 | Taster mit 10k-Pull-up. SW_L1 ist zusätzlich die Power-Taste (siehe Soft-Power). Buzzer über 47 Ω an GP22. J_DEBUG1: 1 RX (GP1), 2 TX (GP0), 3 GND. SWD direkt am Pico. |
| MCU | U1 Pico 2 W | Steckt in 2× 1×20-Buchsenleisten (8,5 mm). 3V3_EN offen (interner Pull-up). |

### Pico-Pinbelegung

| GP | Netz | GP | Netz |
|---:|---|---:|---|
| 0/1 | UART TX/RX | 14 | IMU_MISO |
| 2/3 | DISP_SDA/SCL (PIO I2C, RTC + OLED + Fuel Gauge) | 15 | IMU_CS0 |
| 4/5 | BTN_L (über D_PWR1 auch Power-Taste)/BTN_R | 16–19 | SD MISO/CS/SCK/MOSI (SPI0) |
| 6 | CHG_STAT (Lader, Teiler 10k/10k) | 20 | ADC_DRDY |
| 7 | ADC_RST_MCU → R50 100 Ω → ADC_RST (SYNC/RESET) | 21 | IMU_CS1 |
| 8/9 | IMU_SCLK/MOSI (PIO-SPI) | 22 | Buzzer |
| 10–12 | ADC SCK/SDI/SDO (SPI1) | 26/27 | IMU_CS2/CS3 |
| 13 | ADC_CS | 28 | PWR_OFF (high = Abschalten, Q_PWR3 → MAX16150 ~CLR) |

## Fertigungsdaten (`fab/`)

- `gerber/` + `sst_v2_gerber.zip`: Gerber (Protel-Endungen), Excellon PTH/NPTH, Bohrpläne, Job-Datei.
- `sst_v2_BOM_PCBWay.csv`, `sst_v2_CPL_PCBWay.csv`: 111 Positionen. Der Pico wird nicht bestückt, nur die Buchsenleisten.
  H1–H4, FID1–FID3 und TP1–TP15 stehen nicht in BOM und CPL.

Bestellhinweis PCBWay:

| Parameter | Wert |
|---|---|
| Größe | 60 × 90 mm (die Job-Datei meldet 60,1 × 90,1 mm wegen der Breite der Konturlinie) |
| Lagen | 4, Lagenzuordnung: L1 `sst_v2-F_Cu.gtl`, L2 `sst_v2-GND.g1`, L3 `sst_v2-PWR.g2`, L4 `sst_v2-B_Cu.gbl` |
| Dicke | 1,6 mm FR4 |
| Oberfläche | ENIG |
| Lötstopp / Bestückungsdruck | grün / weiß |
| Fiducials | FID1–FID3 auf F.Cu |

Export (Ordner `hardware/sst_v2`):

```bash
kicad-cli pcb export gerbers -l "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts" --subtract-soldermask -o fab/gerber/ sst_v2.kicad_pcb
kicad-cli pcb export drill --format excellon --excellon-separate-th --excellon-units mm --generate-map --map-format gerberx2 -o fab/gerber/ sst_v2.kicad_pcb
```

## Testpads (Unterseite)

15 SMD-Pads D 1,0 mm (`TestPoint:TestPoint_Pad_D1.0mm`) auf B.Cu, nur B.Mask, keine Paste.
Nicht bestückt: nicht in BOM und CPL (`in_bom no`, `exclude_from_bom`, `exclude_from_pos_files`).
Beschriftung = Wert auf B.Silkscreen (0,8 mm, Strich 0,15 mm, von unten lesbar), Referenz verborgen.
Im Schaltplan als Gruppe „Testpads (Unterseite, nicht bestückt)“ rechts unten.

| TP | Netz | Beschriftung | Lage B-Seite (x/y mm) | Anbindung | Zweck |
|---|---|---|---|---|---|
| TP1 | GND | GND | 93,00 / 121,00 | GND-Pour B.Cu | Masse Analogteil (U2/LDO) |
| TP2 | GND | GND | 110,00 / 57,00 | GND-Pour B.Cu | Masse Stromversorgung (Lader, Q_RP1) |
| TP3 | GND | GND | 89,80 / 126,11 | GND-Pour B.Cu | Masse für Taktmessung, 2,55 mm neben TP6 |
| TP4 | +3V0_ANA | 3V0A | 96,46 / 114,05 | auf vorhandener Via | Analog-LDO-Ausgang |
| TP5 | +3V3_DVDD | DVDD | 86,80 / 128,68 | neue Via im Pad, F.Cu 0,6 mm | ADC-DVDD hinter FB1 |
| TP6 | ADC_CLKIN | CLK | 92,30 / 126,61 | neue Via im Pad, direkt auf der Leiterbahn (kein Stich) | 8,192-MHz-Takt am ADC (zwischen R38 und U2 Pin 17) |
| TP7 | +VBAT_SW | VBSW | 123,38 / 106,85 | Via + 1,0 mm B.Cu | Akku nach Q_PWR1 (Soft-Power) |
| TP8 | +VBAT | VBAT | 115,70 / 52,55 | auf vorhandener Via | Akku vor Q_PWR1 / Laderausgang |
| TP9 | EXC_REF | REF | 104,93 / 110,25 | neue Via im Pad, auf der Leiterbahn | Referenzspannung (R32/R33/C35, U_AAF1 Pin 3) |
| TP10 | POT_EXC | EXC | 90,95 / 87,84 | auf vorhandener Via | Poti-Speisung am Stecker |
| TP11 | FORK_AIN_P | FORK | 100,83 / 126,54 | Via + 1,0 mm B.Cu | ADC-Eingang Gabel |
| TP12 | SHOCK_AIN_P | SHCK | 100,92 / 123,39 | neue Via (F.Cu 0,6 mm) + 1,0 mm B.Cu | ADC-Eingang Dämpfer |
| TP13 | IMU_CLK32K | 32K | 117,75 / 121,65 | neue Via im Pad, auf der Leiterbahn | 32,768-kHz-Takt der IMUs |
| TP14 | IMU_3V3 | IMU | 126,50 / 134,81 | auf vorhandener Via | IMU-Versorgung |
| TP15 | GND | GND | 114,30 / 127,25 | GND-Pour B.Cu | Masse Takt-/IMU-Bereich (U_DIV1) |

Abstand Pad zu Pad ≥ 2,54 mm. Keine Pads in der Pico-Antennenfläche. Vias 228 → 233.

## Prüfstand (2026-10-03)

- ERC: 0 Fehler. 2 Warnungen, bewusst: MP-Pins von SW_L1/SW_R1.
- DRC mit Schaltplan-Parität (`--refill-zones --all-track-errors --severity-all`): 0 Fehler, 0 offene Verbindungen,
  0 Paritätsfehler. 6 Warnungen `lib_footprint_mismatch`, bewusst:
  H1–H4 ohne Courtyard, J_SD1 mit um 0,4 mm gekürzten vorderen Schirm-Pads (Kupfer–Kante 0,3 mm),
  U1 ohne Silkscreen-Linien am Platinenrand.
- Alle Referenzen stehen auf dem Silkscreen mit 0,8 mm Höhe und 0,15 mm Strich, von Hand positioniert (2026-10-03). Nur H1, H2 und FID1–FID3 haben die Referenz auf F.Fab. Referenzen unter dem Pico (R2, R27–R29, R41, R42, R44–R46, R50, D_VSYS1) sind nach dem Aufstecken verdeckt.
- U_AAF1: Referenz im Gehäuseumriss (links davon sitzt jetzt C1).
- U1: Die Silkscreen-Markierung im USB-Bereich unter dem Pico ist entfernt (lag über den früheren Lader-Pads).
- Zonen sind gefüllt gespeichert. Leiterbahnlänge 2658 → 2644 mm, Vias 225 → 228 (Lader an der Oberkante).
- Soft-Power + Fuel Gauge (2026-10-03): ERC und DRC wie oben (keine neue Warnung). Leiterbahnlänge 2649 → 2697 mm, Vias 233 → 250. Neue Verbindungen mit einem Rasterrouter (Raster 0,05 mm, Abstand netzklassengerecht), danach DRC. Neue Referenzen unter dem Pico (U_PWR1, C_PWR1, D_PWR1, Q_PWR2, Q_PWR3, R_PWR2–R_PWR4, U_FG1, C_FG1) sind nach dem Aufstecken verdeckt.
- Doppelte UUIDs: TP1–TP15 teilten sich 5 UUIDs (Pad und Grafik, 70 Duplikate aus dem Kopier-Skript). Alle Duplikate haben jetzt eigene UUIDs.

## Review Rev. 3 (2026-10-03): Soft-Power MAX16150 + Fuel-Gauge MAX17048

| Änderung | Grund |
|---|---|
| J_PWR1 (externer Schalter) entfernt. Q_PWR1 DMG2305UX als High-Side-Schalter zwischen +VBAT und +VBAT_SW, gesteuert von U_PWR1 MAX16150AUT+T über Q_PWR2 2N7002. | Ein- und Ausschalten mit der linken Panel-Taste. Die Firmware kann das Gerät selbst abschalten. |
| SW_L1 Pin 2 → PWR_BTN (PB_IN). BTN_L über D_PWR1 RB751S40 an PWR_BTN. | Die Taste bleibt UI-Taste. Gedrückt: BTN_L = VF ≈ 0,3 V (low). Losgelassen: Diode sperrt, kein Strom in den GPIO. Pico ohne Spannung: Diode sperrt, nur Leckstrom. |
| GP28: VBAT_SENSE → PWR_OFF. R19/R20/C29 entfernt. GP28 → Q_PWR3 2N7002 → ~CLR. R_PWR3 100k von ~CLR an OUT. | Kein GPIO frei. Die Akkuspannung misst jetzt U_FG1. ~CLR nur an OUT hochgezogen: Im Aus-Zustand liegt kein VBAT-Pegel an einem Pin des Pico. |
| U_FG1 MAX17048G+T10 mit C_FG1 an +VBAT und PIO-I2C (0x36). | Ladezustand (SOC), Zellspannung (VCELL) und Lade-/Entladerate (CRATE) über I2C. |
| Netzklassen-Muster VBAT_SENSE aus `sst_v2.kicad_pro` entfernt. Courtyard-Regel für die Teile unter dem Pico in `sst_v2.kicad_dru`. | Netz existiert nicht mehr. Teile sitzen absichtlich unter dem Pico. |
| Langer Leiterzug von der Oberkante (früher +VBAT_SW ab J_PWR1) ist jetzt +VBAT. Q_PWR1 sitzt am unteren Ende vor C26. | Leistungspfad bleibt 0,5 mm breit und kurz. +VBAT liegt damit auch für U_PWR1 und U_FG1 bereit (Zuleitung 0,3/0,25 mm, µA-Lasten). |

Datenblattwerte:

- **MAX16150A** (Datenblatt Rev 4, 1/21): VCC 1,3–5,5 V. ISB ≤ 20 nA (VCC 5 V, OUT low, −40…+70 °C), 10/40 nA typ/max bis +85 °C. ICC 15/30 µA nur während PB_IN-Erkennung oder INT-Puls. PB_IN-Pull-up 1,2/1,4/2,0 MΩ an VCC, Eingang ±60 V. VIH 0,7 × VCC, VIL 0,3 × VCC. tDB 50 ms, tSO 8 s (±20 %). ~CLR wird bei OUT low ignoriert und nach OUT high für 1,6–2,4 × tINT (51–77 ms). OUT = VCC − 0,1 V bei 20 mA. Das Datenblatt empfiehlt Pull-up von ~CLR/~INT an OUT.
- **Q_PWR1 DMG2305UX:** RDS(on) ≤ 52 mΩ (typ 40) bei VGS −4,5 V, ≤ 100 mΩ (typ 52) bei −2,5 V. Bei leerem Akku (VGS −3,0 V) also ≤ 100 mΩ: 0,5 A → ≤ 50 mV, ≤ 25 mW. VGS(th) −0,5…−0,9 V, IDSS ≤ 1 µA.
- **Q_PWR2/Q_PWR3 2N7002 (Diodes):** VGS(th) 1,0–2,5 V, IDSS ≤ 1 µA (60 V), IGSS ≤ 10 nA. Last nur 42 µA (4,2 V / 100k): bei VGS 3,0 V (Akku leer) bzw. 3,3 V (GP28) sicher durchgeschaltet.
- **D_PWR1 RB751S40 (Nexperia):** VF ≤ 370 mV bei 1 mA. Kurve: ≈ 0,27 V bei 0,33 mA (25 °C), ≈ 0,36 V bei −40 °C. RP2350 VIL ≤ 0,8 V: BTN_L ist sicher low. IR ≤ 0,5 µA bei 30 V. Kurve: ≈ 15 nA bei 4 V / 25 °C, ≈ 1,5 µA bei 85 °C. Spannungsabfall an PB_IN im Aus-Zustand: 15 nA × 1,4 MΩ = 21 mV (25 °C), ≈ 0,4 V bei 60 °C (2,0 MΩ). PB_IN bleibt über 0,7 × VCC.
- **MAX17048** (Datenblatt Rev 7): VDD 2,5–4,5 V. Aktiv 23/40 µA, Hibernate 3/5 µA (VRESET.Dis = 1) bzw. 4 µA typ (Komparator an), Sleep 0,5/2 µA (≤ 50 °C). Sleep nur mit MODE.EnSleep = 1 und SDA und SCL < VIL (0,5 V) für tSLEEP 1,75–2,5 s; eine steigende Flanke an SDA oder SCL weckt den Baustein. SDA/SCL haben 0,2/0,4 µA Pull-down (Erkennung „Bus offen“). Datenpins −0,3…+5,5 V unabhängig von VDD, SDA Open Drain, SCL Eingang: kein Rückspeisen in den 3V3-Bus. VIH 1,4 V. Im Sleep erkennt der Baustein keine Selbstentladung. Laden weckt ihn: USB versorgt den Pico, der Bus geht high.

### Ruhestrom im Aus-Zustand (USB ab, Pico ohne Spannung, 25 °C)

| Teil | typ | max | Bemerkung |
|---|---:|---:|---|
| U_PWR1 MAX16150 (ISB) | < 20 nA | 20 nA | Grenzwert bei 5 V, ≤ 70 °C |
| D_PWR1 Leckstrom über PB_IN-Pull-up | 15 nA | 0,5 µA | max = IR-Grenzwert bei 30 V |
| U_FG1 MAX17048, Sleep (EnSleep = 1) | 0,5 µA | 2 µA | ohne EnSleep: Hibernate 3 µA typ / 5 µA max |
| U_CHG1 MCP73831, Rückstrom (VDD offen) | 0,25 µA | 2 µA | |
| Q_PWR1 IDSS in die +VBAT_SW-Last | < 0,01 µA | 1 µA | max bei −20 V |
| Q_PWR2 IDSS über R_PWR1 | < 0,01 µA | 1 µA | max bei 60 V |
| R_PWR1–R_PWR4, C_PWR1, C_FG1 | 0 | – | ohne Spannung bzw. MLCC |
| **Summe** | **≈ 0,8 µA** | **≈ 6,5 µA** | Hibernate statt Sleep: ≈ 3,3 / 9,5 µA |

1200 mAh / 0,8 µA ≈ 170 Jahre, bei 6,5 µA ≈ 21 Jahre. Die Selbstentladung des LiPo (einige %/Monat) dominiert.

### Firmware-Folgen

1. **Abschalten:** SD-Datei schließen (Puffer schreiben, `f_close`, `f_sync`), dann GP28 high. Ohne USB fällt die Versorgung sofort. Mit USB läuft der Pico weiter: GP28 nach ≥ 100 ms wieder low setzen. Sonst schaltet ein Tastendruck nach der ~CLR-Sperrzeit (≈ 64 ms) sofort wieder ab.
2. **GP28 beim Start:** so früh wie möglich als Ausgang low. R_PWR4 hält Q_PWR3 bis dahin aus.
3. **BTN_L:** bleibt UI-Taste (GP4, aktiv low, Pegel ≈ 0,3 V). Der Einschalt-Druck ist beim Booten oft noch aktiv: BTN_L erst nach dem ersten Loslassen auswerten. Halten > 8 s = Hardware-Aus ohne Dateiabschluss. Darum: bei Halten ≥ 3 s die Datei schließen und selbst über GP28 abschalten.
4. **Akku:** Spannung und Ladezustand aus U_FG1 (VCELL 0x02: 78,125 µV/LSB, SOC 0x04: 1/256 %, CRATE 0x16: 0,208 %/h) statt VSYS-Teiler an GP28. Nach jedem Start STATUS.RI prüfen; wenn gesetzt, Konfiguration schreiben (MODE.EnSleep = 1, ggf. RCOMP) und RI löschen.
5. **Neuer Zustand CHARGING:** Start mit USB (VBUS über CYW43 WL_GPIO2) und ohne USB-Host → Anzeige „CHARGING“, SOC-Balken, Restzeit aus CRATE; „FULL“ bei CHG_STAT high (GP6). Host meldet sich an → MSC wie bisher. SW_L1-Druck → normaler Betrieb (der Druck schaltet zugleich Q_PWR1 ein).

## Review Rev. 3 (2026-09-30)

| Änderung | Grund |
|---|---|
| 23 Vias +3V3_DIG 0,6/0,4 → 0,7/0,4 mm; `min_via_annular_width` 0,15 | PCBWay: Restring ≥ 0,15 mm (vorher 0,10 mm). Keine neuen Abstandsfehler. |
| 347 Silkscreen-Linien 0,12 → 0,15 mm; Referenzen 0,8 → 1,0 mm Höhe, Strich 0,15 mm; `min_text_thickness` 0,15 | PCBWay: Strich ≥ 0,15 mm, Höhe ≥ 0,8 mm, Verhältnis 1:5. |
| R_STAT2 20k → 10k | CHG_STAT-Teiler: „fertig“ = 0,5 × VBUS = 2,6 V bei 5,25 V (mit 20k: 3,5 V über IOVDD 3,3 V). |
| Rule Area „Pico antenna: keepout“: alle Kupferlagen, keine Leiterbahnen, Vias, Pours; volle Pico-Breite + 1 mm am Ende | Vorher nur Pour-Verbot auf F.Cu/B.Cu. ADC_CS, ADC_SCK, ADC_SDI, ADC_SDO liefen durch die Antennenfläche. Neu geroutet (Rasterrouter): ADC_CS/ADC_SCK rechts der Fläche (x > 101 mm), ADC_SDI/ADC_SDO über die Oberkante und links der Fläche (x ≈ 90,1/90,55 mm). Analogblock unverändert. |
| C1 an U_AAF1 Pin 4 (0,55 mm Pad-zu-Pad, vorher 3,8 mm), eigene GND-Via | Abblockung V+ direkt am Pin. POT_EXC dafür auf F.Cu 0,8 mm nach links verlegt. |
| C_CHG1 (VBUS) und C_CHG2 (VBAT) getauscht: C_CHG1 1,6 mm Pad-zu-Pad an U_CHG1 Pin 4 (vorher 4,2 mm) | Eingangskondensator direkt am VDD-Pin. +VBUS läuft von Pin 40 über C_CHG1 zu Pin 4, +VBAT zu C_CHG2 links vorbei. |
| R50 100 Ω 0603 zwischen GP7 (ADC_RST_MCU) und ADC_RST (R1/C4/U2 Pin 11), unter dem Pico an Pin 10 | Serienwiderstand gegen Überschwinger und Querstrom auf der langen Reset-Leitung. |
| Netz +3V0_DVDD → +3V3_DVDD, PWR_FLAG hinter FB1 | Name entsprach nicht der Spannung; ERC-Warnung „power pin not driven“ an U2 Pin 20 entfällt. |
| Fiducials FID1–FID3 (Schaltplan + Layout) | Passermarken für die Bestückung. Freie Plätze mit ≥ 1,6 mm Abstand zu Kupfer und Silkscreen. |
| Titelblock Rev. „3“ (Schaltplan, Layout) | Job-Datei meldete Revision „A“. |
| Lader umgesetzt: U_CHG1, C_CHG1/C_CHG2, R_PROG, R_STAT1/R_STAT2 von unter dem Pico (141/69) an die Oberkante (x 113–123,6, y 48,3–55,2). GND-Zone „Lader Thermal“ 0,77 cm², 6 GND-Vias am VSS-Pad. C_CHG1 0,75 mm Pad-zu-Pad an VDD, C_CHG2 0,72 mm an VBAT, R_PROG 0,68 mm an PROG. +VBUS 49 mm (Pin 40 → F.Cu x 143,1 → B.Cu y 57,5 → Lader), +VBAT ab J_PWR1 10 mm (vorher 34 mm), CHG_STAT gerade zu GP6. Courtyard-Ausnahmen der sechs Teile aus `sst_v2.kicad_dru` entfernt. R42-Referenz links neben R42. | Unter dem Pico staute sich die Wärme (θJA 230 K/W, 0,4–0,6 W beim Laden) ohne Kupferfläche und ohne Luft. Jetzt liegt der Lader frei, mit Kupfer an VSS und Vias zur GND-Lage. |

## Review Rev. 3 (2026-09-27) — behobene Fehler

| Fehler | Behebung |
|---|---|
| TPS7A4700-Symbol mit falscher Pinbelegung (GND-Pin an 3,3 V, OUT/IN vertauscht, ANY-OUT an 3,3 V) | Symbol nach SBVS204G, Footprint Texas RGW0020A, LDO-Bereich neu geroutet, Eingangs-C ergänzt |
| USB-VBUS speiste über die Pico-Schottky in den Akku | D_VSYS1 zwischen +VBAT_SW und VSYS |
| RTC-Backup-Diode verpolt | Diode entfernt, CR1220 direkt an VBAT |
| Buzzer-Footprint 7,6 mm statt 5 mm Raster | Footprint Buzzer_TDK_PS1240P02BT |
| R18 zog 3V3_EN auf die eigene Ausgangsspannung | R18 entfernt |
| DS3231 RST fest an 3,3 V | RST offen |
| ADS131M04 DVDD 3,0 V bei 3,3-V-Logik | DVDD aus +3V3_DIG über FB1 |
| CMC gegenphasig beschaltet (Gleichtaktdämpfung unwirksam) | Beschaltung nach Murata-Ersatzschaltbild: Eingänge ②/③, Ausgänge ①/④ |
| SWD-Pins am Header ohne Verbindung | J_DEBUG1 als 1×3 UART |
| DRC: 40 Lötstopp-Stege, 17 Thermals, 4 Randabstände | Regeln an PCBWay angepasst, volle Anbindung, J_SD1-Pads gekürzt |

Zusätzlich umgesetzt: Verpolschutz Q_RP1, Polymer-Tantal C26, 1 µF direkt an AVDD
(C23), 100 nF direkt an 74HC4040 (C44), DAT1-Pull-up R48, Montagelöcher im Schaltplan,
Silkscreen bereinigt.

## Umplatzierung (2026-09-27)

| Änderung | Grund |
|---|---|
| Pico 2,0 mm nach links | USB-Buchse ragte 1,6 mm über den Platinenrand. |
| Poti-Eingang nach links, OLED/Taster nach rechts | Poti-Leitungen liefen quer über die Platine durch den Digitalbereich; UI-Leitungen ebenso in Gegenrichtung. |
| Analogblock 2 mm nach rechts, In2-Insel verkleinert | Mehr Platz für die ADC-SPI-Leitungen an der digitalen Seite von U2; +3V3-Pads des LDO erreichen die +3V3-Ebene. |
| R34/R35 um 180° gedreht, R2 zum Pico, C26 zu D1/D_VSYS1 | Kürzere Wege für POT_EXC, ADC_CS und +VBAT_SW. |
| R49 (47k) an SD_DAT2 | DAT2 war offen. |
| Y1-3D-Modell SG210 (gleiches 2520-Gehäuse), U1 als Pico W | ECS-Modell fehlt in KiCad 10. |

Neu geroutet: Freerouting für die Digitalnetze (mit Sperrfläche über dem Analogblock), dann die Analognetze;
die lokalen Analogverbindungen um LDO/ADC/Opamp aus dem vorherigen Layout übernommen; Reste mit einem Rasterrouter.
Ergebnis: Leiterbahnlänge 2922 → 2597 mm, Vias 328 → 221; Poti-Analogpfade 350 → 272 mm, 34 → 14 Vias.

## Nacharbeit (2026-09-28)

| Änderung | Grund |
|---|---|
| J_SD1 0,35 mm nach links, 1,25 mm nach oben | Körper ragte 0,1 mm über die Kante; Abstand zu H4. |
| BT1 und BZ1 getauscht, BT1 bei (112,7 / 98,3) | Vor der Öffnung von BT1 lagen C26, R19–R21 u. a.: Die Zelle ließ sich nicht einschieben. Jetzt ist der Weg zum Pico frei. R29 sitzt am Pico-Pin. |
| C3 neben U2 Pin 18 (1,9 mm statt 5,4 mm) | CAP-Kondensator direkt am Pin. |
| C40 neben U_CLKBUF1 VCC (2,7 mm statt 6,8 mm), R39 auf den alten Platz von C40 | Abblockung direkt am IC. U_CLKBUF1 und C33 0,25 mm nach oben. |
| FB1, Y1, C19 von H3 weg; R49, R48 neu gesetzt | Schraubenkopf-Freiraum ≥ 3,5 mm. |
| Lader MCP73831 unter dem Pico, GP6 = CHG_STAT | Laden über USB (Plan „USB-Buchse für Laden + MSC“). Pico-Pin VBUS im Symbol als Power-Ausgang. |

Neu geroutet: alle Digitalnetze mit Freerouting (Sperrfläche über dem Analogblock), Reste mit Rasterrouter.
Keine Digitalleitung im Analogbereich. Leiterbahnlänge 2577 → 2633 mm (Lader +VBAT, 34 mm), Vias 223 → 221.

## Offene Punkte

- **microSD:** Eine gesteckte Karte ragt 5,2 mm über die Platinenkante (Push-Push, Karte zum Greifen). Gehäuse braucht an dieser Stelle einen Schlitz.
- **USB im Gehäuse:** Wasserdichte USB-C-Panelbuchse mit 5,1 kΩ an CC1/CC2 (sonst liefert ein C-auf-C-Netzteil keine Spannung), kurzes Kabel mit 90°-Micro-B-Stecker in den Pico. Platz neben der Platinenkante einplanen (~10–12 mm).
- **Lader im Gehäuse:** IC-Temperatur beim Laden (300 mA) im geschlossenen Gehäuse messen. Der Lader sitzt jetzt an der Oberkante mit Thermalfläche 0,77 cm². Wenn U_CHG1 trotzdem zu heiß wird (thermische Regelung senkt den Strom), R_PROG 5k (200 mA).
- **Akku-Polarität** am JST-PH prüfen: Pin 1 = Plus. Q_RP1 schützt bei Verpolung.
- **Gehäuse:** J_POT1 liegt jetzt am linken Rand, J_OLED1/SW_L1/SW_R1 am rechten Rand. Kabelwege im Gehäuse anpassen.
- **Autorouting prüfen:** Die Digitalnetze stammen aus Freerouting, einzelne Reste (IMU_CS0/CS1, SD_MISO/MOSI, +VBAT_SW) und die ADC-SPI-Leitungen am Pico-Ende (2026-09-30) aus einem Rasterrouter mit Glättung. Elektrisch geprüft (DRC), Sichtprüfung im KiCad empfohlen.
- **Testpads Sichtprüfung:** Lage und Beschriftung (B-Seite) im KiCad prüfen. TP4–TP6, TP8–TP10, TP13, TP14 haben eine Via im Pad (offen, nicht bestückt, für Prüfspitzen unkritisch).
- **Soft-Power, Zustand nach Akku-Einstecken:** Laut MAX16150-Datenblatt (Rev 4) ist OUT nach dem ersten Anlegen von VCC nicht festgelegt („use PB_IN or CLR to set OUT“). Das Gerät kann beim Einstecken des Akkus einschalten. Die Firmware schaltet dann normal ab. Am Muster prüfen.
- **Fuel Gauge, Messpunkt:** U_FG1 misst an der +VBAT-Abzweigung ≈ 25 mm hinter Q_RP1, nicht mit eigener Leitung am Akku. Fehler ≈ (Q_RP1 ≈ 52 mΩ + Leiterzug ≈ 25 mΩ) × Laststrom: ≈ 10 mV bei 130 mA, ≈ 40 mV bei 0,5 A Spitze. ModelGauge glättet das. Der SOC unter Last ist etwas zu niedrig.
- **Teile unter dem Pico:** Sichtprüfung und Nacharbeit von U_PWR1, U_FG1 und den Kleinteilen nur ohne gesteckten Pico. Der Pico ist gesteckt, also lösbar.
- **Temperatur im Aus-Zustand:** Der Leckstrom von D_PWR1 steigt stark mit der Temperatur (≈ 1,5 µA bei 85 °C). Ab ≈ 80 °C (IR ≈ 1 µA, Pull-up bis 2,0 MΩ) kann PB_IN unter 0,3 × VCC fallen: Das Gerät schaltet von selbst ein. Die LiPo-Lagergrenze (60 °C) liegt darunter.
- **Gehäuse:** Externer Schalter entfällt. Die linke Panel-Taste (SW_L1) ist die Power-Taste.
- **Firmware:** Soft-Power und Fuel Gauge umsetzen (siehe „Firmware-Folgen“).
- **Firmware:** `PICO_BOARD pico_w` → `pico2_w` (`firmware/CMakeLists.txt`).
