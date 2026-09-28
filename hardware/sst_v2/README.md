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
- Unter dem Pico (zwischen den Buchsenleisten, USB-Ende): Lader U_CHG1 mit C_CHG1/C_CHG2, R_PROG, R_STAT1/R_STAT2. `sst_v2.kicad_dru` erlaubt die Courtyard-Überdeckung nur für diese sechs Teile mit U1.
- Montagelöcher: Alle Courtyards liegen ≥ 3,5 mm von der Bohrungsmitte (Platz für Schraubenkopf oder Scheibe Ø 7 mm).
- Unten: IMU-Stecker, Taktteiler und Taktpuffer.
- Digitalleitungen (IMU, SD, UI) laufen außerhalb des Analogblocks. Die ADC-SPI-Leitungen laufen im Poti-Block nur auf B.Cu, getrennt durch die GND-Lage In1.

| Lage | Inhalt |
|---|---|
| F.Cu | Bauteile, Signale, GND-Pour |
| In1.Cu | GND, durchgehend |
| In2.Cu | +3V3_DIG; Insel +3V0_ANA unter der analogen Seite von LDO/ADC/Opamp (x 94,3–108,5 mm, y 112,2–132,5 mm, dazu Streifen y 107,8–112,2 mm ab x 84,9 mm). Die digitale Seite von LDO und ADC (x < 94,3 mm) liegt über +3V3_DIG. |
| B.Cu | Signale, GND-Pour |

Fertigungsregeln (PCBWay): Leiterbahn/Abstand ≥ 0,2 mm, Via 0,6/0,3 mm,
Kupfer–Kante ≥ 0,3 mm, Lötstopp-Steg ≥ 0,1 mm (grüner Lötstopp).

## Schaltung

| Block | Bauteile | Kurzbeschreibung |
|---|---|---|
| ADC | U2 ADS131M04 | CH0 Fork, CH1 Shock, CH2 Poti-Speisung (ratiometrisch), CH3 an GND. AVDD 3,0 V, DVDD 3,3 V über FB1 (Logikpegel = Pico-Pegel). CAP 220 nF. |
| Analog-LDO | U_ANA_LDO1 TPS7A4700 (RGW) | 3,3 V → 3,0 V, ANY-OUT: nur 1P6V (Pin 8) an GND, übrige ANY-Pins offen. SENSE an OUT. NR 10 nF (C25), IN 10 µF (C22), OUT 22 µF (C6). |
| Poti-Speisung | U_AAF1 TLV4333 (A), R32/R33 20k/10k 0,1 %, C35 | 1,0 V Referenz, gepuffert, 47 Ω (R34) auf POT_EXC, Messung über R35/C36 an AIN2P. |
| Schleifer | U_AAF1 (B, C), R36/R37, R8/R14, C9/C12 | Opamp-Puffer, danach 1 kΩ + 10 nF an AINxP. AINxN = Poti-Masse (Remote Sense), R9/R15 0 Ω als Sternpunkt. |
| Poti-Stecker | J_POT1 JST-SH 6 → HR30 6p | 1 POT_EXC, 2 Fork-Schleifer, 3 Fork-Masse, 4 Shock-Schleifer, 5 Shock-Masse, 6 Schirm/GND. ESD D2–D4, CMC L_FORK/L_SHOCK (DLW5BTM251SQ2L). |
| Takt | Y1 ECS-2520MVLC 8,192 MHz, U_DIV1 74HC4040, U_CLKBUF1 74LVC125 | XO → 33 Ω → ADC CLKIN; XO → 4040 Q7 = 32,000 kHz → 2 Puffer → 33 Ω → IMU-CLKIN A/B. |
| IMU | J_IMU_A1/B1 JST-SH 12 → HR30 12p | 1 IMU_3V3 (FB2), 3 SCLK, 5 MOSI, 7 MISO, 8 CLKIN, 10/11 CS, 2/4/6/9/12 GND. 33 Ω in allen DAQ-Ausgängen. |
| Strom | J_BAT1, Q_RP1, J_PWR1, D1, D_VSYS1 | LiPo (JST-PH) → Q_RP1 DMG2305UX (Verpolschutz) → externer Schalter J_PWR1 → +VBAT_SW (TVS D1, C26–C28, Teiler R19/R20 → GP28) → D_VSYS1 PMEG3020EH → VSYS. D_VSYS1 verhindert, dass USB-VBUS direkt in den Akku speist. |
| Lader | U_CHG1 MCP73831T-2ACI/OT, C_CHG1/C_CHG2 4,7 µF, R_PROG 3,3k, R_STAT1/R_STAT2 10k/20k | VDD an +VBUS (Pico Pin 40), Ausgang an +VBAT (vor dem Schalter): Laden auch bei offenem Schalter. 4,20 V, 300 mA (I = 1000 V / R_PROG; 500 mA mit 2,0k). STAT über Teiler an GP6 (CHG_STAT): Laden = 0 V, fertig = 3,3 V, ohne VBUS hochohmig → 0 V. USB kommt über ein Kabel von einer Gehäusebuchse in die Micro-USB-Buchse des Pico. |
| RTC | U3 DS3231SN, BT1 CR1220 | VBAT direkt an der Zelle, RST offen. I2C gemeinsam mit OLED (PIO, R25/R26 4,7k). |
| microSD | J_SD1 DM3AT | SPI0. Pull-ups: SD_CS 10k (R31), DAT1 47k (R48), DAT2 47k (R49). |
| UI | SW_L1/SW_R1 (JST-SH 2), BZ1 PS1240P02BT, J_OLED1, J_DEBUG1 | Taster mit 10k-Pull-up. Buzzer über 47 Ω an GP22. J_DEBUG1: 1 RX (GP1), 2 TX (GP0), 3 GND. SWD direkt am Pico. |
| MCU | U1 Pico 2 W | Steckt in 2× 1×20-Buchsenleisten (8,5 mm). 3V3_EN offen (interner Pull-up). |

### Pico-Pinbelegung

| GP | Netz | GP | Netz |
|---:|---|---:|---|
| 0/1 | UART TX/RX | 14 | IMU_MISO |
| 2/3 | DISP_SDA/SCL (PIO I2C, RTC + OLED) | 15 | IMU_CS0 |
| 4/5 | BTN_L/BTN_R | 16–19 | SD MISO/CS/SCK/MOSI (SPI0) |
| 6 | CHG_STAT (Lader) | 20 | ADC_DRDY |
| 7 | ADC_RST (SYNC/RESET) | 21 | IMU_CS1 |
| 8/9 | IMU_SCLK/MOSI (PIO-SPI) | 22 | Buzzer |
| 10–12 | ADC SCK/SDI/SDO (SPI1) | 26/27 | IMU_CS2/CS3 |
| 13 | ADC_CS | 28 | VBAT_SENSE (Teiler 1:2) |

## Fertigungsdaten (`fab/`)

- `gerber/` + `sst_v2_gerber.zip`: Gerber (Protel-Endungen), Excellon PTH/NPTH, Bohrpläne, Job-Datei.
- `sst_v2_BOM_PCBWay.csv`, `sst_v2_CPL_PCBWay.csv`: 102 Positionen. Der Pico wird nicht bestückt, nur die Buchsenleisten.

Export (Ordner `hardware/sst_v2`):

```bash
kicad-cli pcb export gerbers -l "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts" --subtract-soldermask -o fab/gerber/ sst_v2.kicad_pcb
kicad-cli pcb export drill --format excellon --excellon-separate-th --excellon-units mm --generate-map --map-format gerberx2 -o fab/gerber/ sst_v2.kicad_pcb
```

## Prüfstand (2026-09-28, nach Nacharbeit)

- ERC: 0 Fehler. 3 Warnungen, bewusst: MP-Pins von SW_L1/SW_R1, DVDD über FB1.
- DRC mit Schaltplan-Parität: 0 Fehler, 0 offene Verbindungen. 6 Warnungen `lib_footprint_mismatch`, bewusst:
  H1–H4 ohne Courtyard, J_SD1 mit um 0,4 mm gekürzten vorderen Schirm-Pads (Kupfer–Kante 0,3 mm),
  U1 ohne Silkscreen-Linien am Platinenrand.
- 26 Referenzen im dichten Analogbereich sind auf dem Silkscreen ausgeblendet. 13 Referenzen liegen auf F.Fab: D2, J_OLED1, SW_L1, C23, C40, U_CLKBUF1, Y1 (kein Platz) und die sechs Lader-Teile (unter dem Pico nicht sichtbar).
- U1: Die Silkscreen-Markierung im USB-Bereich unter dem Pico ist entfernt (lag über den Lader-Pads).

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
- **Lader im Gehäuse:** IC-Temperatur beim Laden (300 mA) im geschlossenen Gehäuse messen.
- **Akku-Polarität** am JST-PH prüfen: Pin 1 = Plus. Q_RP1 schützt bei Verpolung.
- **Gehäuse:** J_POT1 liegt jetzt am linken Rand, J_OLED1/SW_L1/SW_R1 am rechten Rand. Kabelwege im Gehäuse anpassen.
- **Autorouting prüfen:** Die Digitalnetze stammen aus Freerouting, einzelne Reste (IMU_CS0/CS1, SD_MISO/MOSI, +VBAT_SW) aus einem Rasterrouter mit Glättung. Elektrisch geprüft (DRC), Sichtprüfung im KiCad empfohlen.
- **Firmware:** GP6 als Eingang CHG_STAT auswerten und bei VBUS „CHG“/„FULL“ anzeigen (optional).
- **Firmware:** `PICO_BOARD pico_w` → `pico2_w` (`firmware/CMakeLists.txt`).
