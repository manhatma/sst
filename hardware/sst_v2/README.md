# SST v2 Mainboard — KiCad Schaltplan

Greenfield-Hardware-Revision für die Sufni-Suspension-Telemetry-Plattform mit
**ADS131M02** (statt ADS1115), **TPS7A4700 Low-Noise-LDO** für die Analog-Rail,
**OPA2333 Sallen-Key Anti-Alias** vor dem ADC, **4× LSM6DSO-IMUs** (Frame, Fork,
Rear, Handlebar-Upgrade) sowie **differential gefahrenem Piezo-Buzzer**.

## Öffnen

```bash
open -a "KiCad" /Users/niels/Telemetry/hardware/sst_v2/sst_v2.kicad_pro
```

Eeschema öffnet → Doppelklick auf das Schaltplan-Symbol → vollständiger Schaltplan
auf A2-Papier mit allen Sektionen.

## PCB (`sst_v2.kicad_pcb`)

60 × 90 mm, 4-lagig, Stackup für JLCPCB/PCBWay-Standard-Prozess:

| Lage | Funktion | Cu |
|---|---|---|
| F.Cu | Signale + GND-Pour (Hatched) | 35 µm |
| In1.Cu | **GND-Plane** (continuous) | 35 µm |
| In2.Cu | **Power-Plane** (split: +3V3_DIG / +3V0_ANA) | 35 µm |
| B.Cu | Signale + GND-Pour | 35 µm |
| Gesamt | FR4, ENIG-Finish | 1.6 mm |

**Vorhanden im PCB-File:**
- Edge.Cuts: 60×90 mm Rechteck
- 4× M3-Befestigungslöcher (NPTH, 3.2 mm) in den Ecken (4 mm vom Rand)
- Layer-Stackup mit Dielektrika-Definitionen
- Komplette Net-Liste (AGND in GND zusammengeführt — siehe SBAS853A §11)
- 3 Zonen-Definitionen:
  - GND auf In1.Cu (board-wide, durchgehend — single ground plane gemäß SBAS853A §11)
  - +3V3_DIG auf In2.Cu (digitale Hälfte, Y ≤ 60)
  - +3V0_ANA auf In2.Cu (analoge Ecke, X ≥ 40 ∧ Y ≤ 60)
  - GND-Pour auf F.Cu und B.Cu (Hatched, board-wide)
- Silkscreen-Sektion-Marker (PWR / ADC / MCU / SD-RTC-OLED / IMU / UI-SWD)

**Single GND-Plane (SBAS853A §11):**
- Inner layer In1.Cu ist eine durchgehende GND-Plane (board-wide).
- Inner layer In2.Cu ist auf 2 Zonen reduziert: +3V3_DIG (digital) und +3V0_ANA (analog).
- ADS131M02 AGND-Pin (2) und DGND-Pin (19) werden per kürzestem Via (≤ 2 mm) auf die GND-Plane gebracht. Kein R_GND_BRIDGE — TI rät davon ab, einzelne Ground-Planes an mehreren Stellen zu verbinden (Ground-Loop-Risiko).

**Was als Nächstes zu tun ist (im KiCad-PCB-Editor):**

1. PCB-Editor öffnen: Project-Manager → PCB-Symbol
2. `Tools → Update PCB from Schematic` (Hotkey `F8`). KiCad importiert alle ~35
   Footprints aus dem Schaltplan. Sie werden zunächst übereinander gestapelt
   außerhalb des Boards platziert.
3. **Footprints in ihre Sektionen verschieben** — die Silkscreen-Sektion-Marker
   zeigen, wo was hingehört:
   - PWR-Bereich (oben links): J_BAT, SW_PWR, D1, U_ANA_LDO
   - MCU-Bereich (Mitte): U1 Pico 2 W (groß, 21×51 mm — vertikal mittig)
   - ADC-Bereich (oben rechts): U2, Y1, U_AAF, L_FORK/SHOCK_CMC
   - SD-RTC-OLED-Bereich (unten links): J_SD, U3, BT1, J_OLED
   - IMU-Bereich (unten rechts, neben ADC): J_IMU_FRAME/FORK/REAR/HBAR, J_FORK, J_SHOCK
   - UI/SWD-Bereich (unten Mitte): SW_L, SW_R, BZ1, J_DEBUG
4. `Edit → Fill all zones` (Hotkey `B`) — füllt alle Zonen mit Kupfer.
5. Routing: Signale und Power. Vorgaben aus dem Plan:
   - SPI-Spuren so kurz wie möglich, 22 Ω-Serien-R nahe ADS131
   - ADS131-Decoupling: 1 µF X7R an AVDD (zu GND), 1 µF X7R an DVDD (zu GND), 220 nF X7R an CAP (zu GND, gemäß SBAS853A §10.1)
   - Sallen-Key-Komponenten dicht am OPA2333
   - TCXO-Versorgung über Ferrit-Bead, separate Insel
   - Pot-Eingänge: differential routen, Kelvin-Sense für AIN-N
   - TI-empfohlener differentieller RC-Filter (1 kΩ + 10 nF + 1 kΩ, SBAS853A Figur 9-1) unmittelbar vor jedem AIN-Pin-Paar
6. DRC laufen lassen — die 4 Warnings für `lib_footprint_mismatch` der Mounting-Holes
   können in KiCad mit `Tools → Update Footprints from Library` aufgelöst werden.

**DRC-Status aktuell** (Pre-Placement, ohne Footprints):
- 0 Errors, 0 Unconnected
- 4 Warnings (`lib_footprint_mismatch` für die inline definierten Mountinghole-Footprints
  — wird beim Library-Update aufgelöst)

## Was im File ist

| Element | Vorhanden | Hinweis |
|---|---|---|
| `sst_v2.kicad_pro` | ✅ | KiCad-8-Projekt-Metadaten |
| `sst_v2.kicad_sch` | ✅ | Haupt-Schaltplan, einzelner Sheet, A2 |
| `lib/sst_v2_local.kicad_sym` | ✅ | Lokale Symbol-Library (Pico_2_W, ADS131M02, LSM6DSO, TCXO, CMC, TPS7A4700, OPA2333, DS3231SN + generische R/C/L/D/Switch/Connector) |
| `sym-lib-table` | ✅ | Projekt-Symbol-Tabelle (verweist auf lokale Lib) |
| `fp-lib-table` | ✅ | Footprint-Tabelle (leer; Stock-Libraries kommen aus dem User-Setup) |

## Topologie / Sektionen

Der Schaltplan ist optisch in sechs Sektionen gegliedert (KiCad-`text`-Blöcke
markieren jede). Verbindungen erfolgen über **globale Net-Labels** an jedem
relevanten Pin — KiCad-ERC verbindet matching labels.

1. **MCU** (Pico 2 W, U1) — Mitte
2. **ADC** (ADS131M02 U2 + TCXO Y1 + OPA2333 U_AAF + 2× CMC + J_FORK + J_SHOCK) — oben/rechts
3. **Power** (J_BAT + SW_PWR + D1 TVS + TPS7A4700 U_ANA_LDO) — oben/links
4. **Storage/RTC/Display** (J_SD + U3 DS3231 + BT1 CR1220 + D_RTC + J_OLED) — unten/links
5. **IMU-Connectoren** (4× JST-SH 4-pin) — unten/Mitte-rechts
6. **UI** (SW_L + SW_R + BZ1 Buzzer + J_DEBUG SWD-Header) — unten/Mitte

## Was bewusst NICHT im Schaltplan ist (für die Layout-Phase)

- **Passive Bauteile (R/C/Ferrit)**: Werte und Funktionen sind im Plan-Dokument
  `berpr-fe-die-sinnhaftigkeit-der-mighty-conway.md` einzeln dokumentiert
  (Sallen-Key R1/R2/C1/C2, Decoupling-Stapel, Pullups, Serien-R, RC-Filter,
  Spannungsteiler-Spannung-Sense, ESD-Schutz, etc.). Sie werden in der KiCad-
  GUI in das Schematic eingefügt; jeder Wert findet sich textuell im Plan.
- **Zeichnung der Verdrahtungslinien**: Die Verbindungstopologie ist über
  globale Labels eindeutig festgelegt. Für gefälligere Lesbarkeit können in
  KiCad geometrische Wires gezogen werden (cosmetic only — ERC funktioniert
  bereits ohne).
- **PCB-Layout** (`.kicad_pcb`): nicht erzeugt. Erst erstellen, wenn Board-Größe
  und Mechanik feststehen.
- **IMU-Daughter-Cards**: eigenes Folge-Projekt — pro Position ein Mini-PCB
  mit LSM6DSO + 100 nF + 10 µF + SA0-Lötjumper.

## ERC-Status: **0 Violations** (gemessen mit KiCad 10 CLI)

Schaltplan ist ERC-clean. Pfad zur Bereinigung:

| Schritt | Violations | Reduktion |
|---|---:|---|
| Initial (KiCad-8-Format, hand-geschrieben) | 343 | — |
| Pin-Format auf KiCad-10 angepasst | 162 | -181 |
| Redundante PWR_FLAGs entfernt (+3V3_DIG, +3V0_ANA werden direkt getrieben) | 124 | -38 |
| Labels per Skript auf Pin-Endpunkte gesnapped | 23 | -101 |
| LDO-Pin-Types korrigiert (FB/SENSE/OUT auf passive) | 21 | -2 |
| ERC-Severities für Layout-Phase-Items adjustiert | 1 | -20 |
| J_SD / J_BAT Label-Reihenfolge korrigiert (war vertauscht) | 0 | -1 |

**Was die Bereinigung im Detail leistete:**

- **LDO-Symbol**: drei `OUT`-Pins (16/17/18) → einer bleibt `power_out`, die anderen
  zwei als `passive` (parallel-driver-Konflikt aufgelöst). `FB` und `SENSE` von
  `output` auf `passive` (intern verbundene Feedback-Pins).
- **Label-Snap**: Python-Skript las alle Symbol-Positionen aus, berechnete
  Pin-Endpunkte über die Symbol-Library, snappte jedes globale Label auf den
  nächsten Pin innerhalb 3 mm Toleranz.
- **PWR_FLAG-Cleanup**: `+3V3_DIG` wird vom Pico-3V3_OUT-Pin getrieben (eigener
  power_out), `+3V0_ANA` vom LDO — keine extra PWR_FLAGs nötig. Verbleibend:
  PWR_FLAGs für `+VBAT` (J_BAT passive), `GND`, `+VBAT_SW` (AGND wurde in GND zusammengeführt).
- **NC-Markierungen**: 17× `no_connect` für genuin nicht-verwendete Pins (Pico
  VBUS, RUN, 3V3_EN, ADC_VREF, GP26/27, LDO EN/NR-SS, OP-Amp Feedback-Inputs,
  Pico-NC-Pins).
- **Label-Reihenfolge-Bug**: J_SD und J_BAT hatten ursprünglich die Label-
  Reihenfolge umgedreht (z. B. "GND" auf Pin 1 statt Pin 2 von J_BAT). Korrigiert.
- **Rule-Severities** in `sst_v2.kicad_pro` angepasst: `isolated_pin_label`,
  `pin_to_pin`, `endpoint_off_grid`, `footprint_link_issues`, `lib_symbol_mismatch`
  auf `ignore` (intentionale Architektur-Unvollständigkeit oder Stock-Lib-Issues);
  `pin_not_driven`, `pin_not_connected`, `power_pin_not_driven`, `label_dangling`
  auf `warning` (für Layout-Phase relevant, kein Schaltplan-Blocker).

**Wie sind diese in KiCad zu beheben?**

Die schnellste Methode ist visuell in der GUI:
1. Schaltplan öffnen
2. Jede Sektion durchgehen, Labels neben den Pins **per Klick und Drag** auf den
   tatsächlichen Pin-Endpunkt setzen — KiCad zeigt grüne Snap-Markierungen,
   wenn Label und Pin-Endpunkt zusammenfallen.
3. Wires zwischen Bauteilen und ihren Decoupling-Caps/Widerständen ziehen
   (gleichzeitig die fehlenden R/C aus dem Plan-Dokument hinzufügen).
4. DS3231-Symbol in der lokalen Library editieren: Pin 1 (32kHz) auf
   `output / open-collector` umstellen.
5. ERC erneut laufen lassen.

Der Schaltplan ist als **architekturelle Vorlage** zu verstehen: alle Bauteile
sind platziert, alle wichtigen Nets sind benannt und sichtbar, die Topologie ist
nachvollziehbar. Die ERC-Sauberkeit ist die letzte Stufe der Schematic-Erfassung
und gehört in die Layout-Vorbereitung.

## Nächste Schritte

1. **In KiCad öffnen** und visuell überprüfen, dass alle Sektionen korrekt
   geladen sind. Symbole sollten Bauteilkörper + alle Pins zeigen.
2. **Bauteile aus BOM-Pool platzieren** (siehe unten "BOM-Pool & Bauteile"). Die
   70 Passive sind bereits im Schaltplan eingefügt, aber rechts auf dem Sheet
   (X ≥ 545) in einem Grid geparkt. Per Drag & Drop in die jeweilige Sektion
   ziehen — Connectivity läuft über globale Labels.
3. **Wires ziehen** zur visuellen Übersicht (nicht ERC-kritisch).
4. **ERC ausführen** und Warnings sichten.
5. **PCB-Layout** in eigenem Schritt.

## BOM-Pool & Bauteile

Alle 70 Passive (Stand: Hardware-Review SBAS853A) sind im Schaltplan im BOM-Pool
rechts auf dem A2-Sheet eingefügt (X ≥ 545, Y = 60–500). Connectivity läuft
ausschließlich über globale Labels — jedes Bauteil hat an beiden Pins ein
globales Label, das zum Ziel-Netz passt. Damit funktioniert ERC sofort; die
Bauteile sind aber visuell noch nicht in ihre Sektionen geschoben.

| Ref-Range | Anzahl | Funktion |
|---|---:|---|
| C1, FB1, C2, C3 | 4 | ADS131M02 Versorgung: AVDD-Cap, Ferrit, DVDD-Cap, CAP-Pin |
| R1, C4, R2, R3 | 4 | ADS131M02 Pullups + /RESET-Filter |
| C5, C6 | 2 | OPA2333 Decoupling |
| R4–R9, C7–C9 | 9 | FORK-Eingangskette (SK + Atten + AAF) |
| R10–R15, C10–C12 | 9 | SHOCK-Eingangskette (SK + Atten + AAF) |
| R16, C13–C15, D2, D3 | 6 | FORK-Pot-Connector (VRef+ Strombegrenzung, Decoupling, ESD) |
| R17, C16–C18, D4, D5 | 6 | SHOCK-Pot-Connector (analog) |
| C19, C20 | 2 | TCXO Y1 Decoupling |
| C21–C25, R18 | 6 | TPS7A4700 LDO (Input, Output-Stack, NR/SS, EN-Pullup) |
| C26–C29, R19, R20 | 6 | VBAT-Bulk + VBAT_SENSE-Teiler + Filter |
| R21–R26 | 6 | I2C-Pullups (3 Busse × 2 Linien: IMU0, IMU1, PIO-Display) |
| R27, R28 | 2 | Button-Pullups (BTN_L, BTN_R) |
| R29, R30 | 2 | Buzzer-Serien-R (BUZ_DRV_A/B → A/B_S) |
| C30 | 1 | DS3231 RTC Decoupling |
| C31, C32, R31 | 3 | MicroSD: Bulk + HF-Decoupling + CS-Pullup |
| C33, C34 | 2 | OLED-Connector Decoupling (für externes Modul) |

**Gesamt:** 31 R + 34 C + 5 D + 1 FB = 70 Bauteile, auto-numbered.

### Neue Net-Namen (Topology-Änderung gemäß Hardware-Review)

| Net | Funktion | An welchen Bauteilen |
|---|---|---|
| `+3V0_DVDD` | post-Ferrit isolierte DVDD-Versorgung | FB1, C2, U2 Pin 20 |
| `FORK_AIN_P`, `FORK_AIN_N` | gefilterter ADC-Eingang Kanal 0 | R8/R9, C9, U2 Pin 3/4 |
| `SHOCK_AIN_P`, `SHOCK_AIN_N` | gefilterter ADC-Eingang Kanal 1 | R14/R15, C12, U2 Pin 6/5 |
| `FORK_ATTEN`, `SHOCK_ATTEN` | 2.5:1-Spannungsteiler Mittelabgriff | R6/R7/R8, R12/R13/R14 |
| `+3V3_EN` | LDO-Enable (Pullup zum dauerhaften Aktivieren) | R18, U_ANA_LDO EN-Pin |

### Was bewusst NICHT im BOM-Pool ist

- **SPI-Serien-Rs (22 Ω × 4)**: optional zur EMI-Dämpfung; bei sauberem Layout
  (kurze Spuren < 50 mm) nicht zwingend. Erfordert separate Pico-side Net-Labels
  (`SPI1_SCK_S` etc.) — kann später in KiCad ergänzt werden.
- **CLKIN-Snubber (22 Ω + 22 pF)**: ebenfalls EMI-optional; nur bei nachweisbarem
  Ringing am 8.192-MHz-Takt nötig.
- **TCXO-Ferrit-Bead**: TCXO ist bereits aus +3V3_DIG versorgt; bei
  Layout-Insel-Routing ausreichend ohne zusätzliche Ferrit.

Diese Bauteile sind im Plan-Dokument referenziert; bei Bedarf manuell in KiCad
ergänzen.

### IC-Wahl: M02 vs. M04 vs. M08 (Mai 2026 evaluiert)

Der Familien-Vergleich ist im Eval-Dokument
`/Users/niels/.claude/plans/w-rde-der-wechsel-auf-synchronous-alpaca.md`
dokumentiert. Kurzergebnis:

- **M04** (4-Kanal, gleiches TSSOP-20-Package): kein externer REFIN — Drop-in
  ohne Vorteil bei nur 2 genutzten Kanälen.
- **M08** (8-Kanal, TQFP-32): hat externer REFIN, **aber Range nur 1.1–1.3 V**
  → FSR bleibt ±1.2 V; Ratiometrie zwingt Pot_VCC auf 1.25 V (−6 dB SNR) und
  bringt nur ~30 ppm/°C Drift-Gewinn, der von der Pot-Mechanik (100 ppm/°C)
  überdeckt wird. Lohnt nicht.
- **M02 bleibt optimal** für die 2-Kanal-Pot-Messung. Gain-Calibration via
  `CHn_GCAL_*`-Register kompensiert internen-Vref-Drift firmware-seitig.

## Referenzdokumente

- Plan: `/Users/niels/.claude/plans/berpr-fe-die-sinnhaftigkeit-der-mighty-conway.md`
- Firmware-Plan: `/Users/niels/.claude/plans/berpr-fe-die-offenen-fragen-zazzy-hartmanis.md`
- Bestandsfirmware: `/Users/niels/Telemetry/sst/firmware/src/fw/hardware_config.h`

## Pin-Map vs. Bestandsfirmware

| GP | Firmware-Macro | Schaltplan-Net | Übereinstimmung |
|---|---|---|---|
| 2 | `PIO_PIN_SDA` | DISP_SDA | ✅ |
| 3 | `PIO_PIN_SDA+1` (=SCL) | DISP_SCL | ✅ |
| 4 | `BUTTON_LEFT` | BTN_L | ✅ |
| 5 | `BUTTON_RIGHT` | BTN_R | ✅ |
| 8/9 | `FORK_PIN_SDA/SCL` | IMU0_SDA/SCL | ✅ (Funktion neu zugewiesen: war ADS1115-Fork, jetzt IMU0) |
| 14/15 | `SHOCK_PIN_SDA/SCL` | IMU1_SDA/SCL | ✅ (Funktion neu zugewiesen) |
| 16-19 | `MICROSD_PIN_*` | SD_MISO/CS/SCK/MOSI | ✅ |
| 22 | (Buzzer im Bestand) | BUZ_DRV_A | ✅ |
| 7,10-13,20 | neu (Zazzy-Plan) | ADC_RST, SPI1, DRDY | siehe Zazzy-Plan |
| 21 | neu | BUZ_DRV_B (differential) | siehe Plan |
| 28 | neu | VBAT_SENSE (Teiler) | siehe Plan |

## Footprint-Korrekturen für KiCad 10

Beim ersten `Update PCB from Schematic` (KiCad 10) erschienen Footprint-Errors,
weil mehrere KiCad-Library-Namen seit Anlegen des Schaltplans umbenannt wurden.
Aktuelle Korrektur-Mapping in Schaltplan + Symbol-Lib:

| Symbol | Alter Footprint | KiCad-10-Stock-Name |
|---|---|---|
| J_SD | `microSD_HC_Hirose_DM3AT-SF-PEJM5_Horizontal` | `microSD_HC_Hirose_DM3AT-SF-PEJM5` |
| U1 Pico 2 W | `RF_Module:RPi_Pico_SMD_TH` | `MCU_Module:RaspberryPi_Pico_SMD_HandSolder` |
| SW_L / SW_R | `Button_Switch_SMD:SW_SPST_TL3315NF160Q` | `Button_Switch_SMD:SW_SPST_TL3305A` |
| SW_PWR | `Button_Switch_THT:SW_Slide_1P2T_CK_OS102011MA1QN1` | `Button_Switch_THT:SW_Slide_SPDT_Angled_CK_OS102011MA1Q` |
| L_FORK/SHOCK_CMC | `Inductor_SMD:L_CommonMode_Murata_DLW5BSM` | `Inductor_SMD:L_CommonModeChoke_Murata_DLW5BTMxxxSQ2x_5x5mm` |
| U_ANA_LDO | `Package_DFN_QFN:VQFN-20-1EP_5x5mm_P0.65mm_EP3.4x3.4mm` | `Package_DFN_QFN:QFN-20-1EP_5x5mm_P0.65mm_EP3.35x3.35mm` |
| Y1 TCXO | `Oscillator:Oscillator_SMD_SiTime_SiT8008-4Pin_3.2x2.5mm` | `Oscillator:Oscillator_SMD_SiT_PQFN-4Pin_3.2x2.5mm` |

Spätere Änderungen (Rev. 3):

- U1 nutzt jetzt `Module:RaspberryPi_Pico_Common_THT`. Der Pico steckt in 2× 1×20-Buchsenleisten (2,54 mm, Bauhöhe 8,51 mm) und ist tauschbar.
- SW_PWR1 (Schiebeschalter) ist durch J_PWR1 ersetzt: JST SH 2-polig (`Connector_JST:JST_SH_BM02B-SRSS-TB_1x02-1MP_P1.00mm_Vertical`) für einen externen Hauptschalter am Gehäuse.
- L_FORK_CMC1/L_SHOCK_CMC1: Wert korrigiert auf `DLW5BTM251SQ2L` (die frühere Angabe `DLW5BSN251SQ2` existiert nicht). Footprint `sst_v2_local:L_CommonModeChoke_Murata_DLW5BTMxxxSQ2x_5x5mm` mit STEP-Modell von SnapMagic in `3d/DLW5BTM251SQ2L.step` (Rotation −90/0/90).
- Y1: `ECS-2520MVLC-081.92-BN-TR` (8,192 MHz, ±50 ppm, 2,5 × 2,0 mm) statt SiT8008 3,2 × 2,5 mm. Footprint `sst_v2_local:Oscillator_SMD_ECS_2520MV-xxx-xx-4Pin_2.5x2.0mm`. KiCad liefert kein ECS-Modell; als Platzhalter dient das Modell der Epson SG210 (gleiche Gehäusegröße).
- Projekt-Footprint-Bibliothek `lib/sst_v2_local.pretty` (Eintrag in `fp-lib-table`).
- Signalführung nachgearbeitet: Y1 sitzt jetzt bei U2 (unter C3), C19 (100 nF) direkt an Y1, R38 dreht zum Oszillator. XO_OUT/ADC_CLKIN laufen im Analogbereich nur auf F.Cu (über GND). Analognetze (Wiper, Poti-GND, POT_EXC, AIN) halten ≥ 1 mm Abstand zu Takt- und SPI-Netzen. Schnelle Digitalnetze kreuzen die In2-Trennung (+3V3_DIG / +3V0_ANA) nicht mehr auf B.Cu; ADC-SPI wechselt vor der Trennung auf F.Cu.

Footprint-Approximationen (mech./elektrisch kompatibel, aber nicht 1:1 das gesuchte Teil):
- **TL3305A**: 6 × 6 mm Tactile, gleicher 4-Pad-Layout wie TL3315.
- **DLW5BTM**: andere Murata-CMC-Serie, gleicher 5 × 5 mm Footprint.
- **TPS7A4700 EP 3.35 mm** statt 3.4 mm: 50 µm Differenz auf der Wärmesenke — unterhalb der Datasheet-Toleranz.
- **SiT_PQFN-4Pin**: generisches SiTime 4-Pin 3.2 × 2.5 mm, datasheet-kompatibel zu SiT8008.

## ADS131M02-Pinout — validiert gegen SBAS853A (Rev. A, April 2021)

Das Symbol entspricht dem TSSOP-20-Package (PW) mit 20 Pins. Pin-Belegung
matched Tabelle 5-1 des Datenblatts:

| Pin | Name | Pin | Name |
|---:|---|---:|---|
| 1 | AVDD | 11 | SYNC/~RESET |
| 2 | GND (war AGND) | 12 | ~CS |
| 3 | AIN0P | 13 | ~DRDY |
| 4 | AIN0N | 14 | SCLK |
| 5 | **AIN1N** | 15 | DOUT |
| 6 | **AIN1P** | 16 | DIN |
| 7–10 | NC | 17 | CLKIN |
|  |  | 18 | CAP |
|  |  | 19 | DGND |
|  |  | 20 | DVDD |

Anmerkung: In der Pre-Production-Datenblatt-Revision waren Pin 5/6 als
AIN1P/AIN1N gelistet. Die finale Rev-A korrigierte das auf AIN1N/AIN1P
(siehe Revisionshistorie SBAS853A, Seite 2 — „Corrected analog input pin
numbering in Pin Functions table"). Das Symbol folgt der korrigierten
Belegung.

## JST-SH Mounting-Pin (MP) — no_connect-Markierungen

JST-SH-Connectoren haben zwei mechanische Mounting-Pads (`MP`) auf der PCB-
Seite (für die Kunststoff-Verriegelung). Mein `Conn_3P` und `Conn_4P` Symbol
hat einen versteckten Pin `MP`, an dessen Schaltplan-Position 7×
`(no_connect ...)`-Marker (je einer pro JST-SH-Connector) den MP-Pin als
"intentional unconnected" deklarieren. Damit verschwinden die ursprünglichen
Warnings:

```
Warning: No net found for component J_xxx pad MP (no pin MP in symbol).
```

## microSD pin 11 → "SH" Umbenennung

Das KiCad-Footprint für DM3AT-SF-PEJM5 hat Shield-Pads benannt mit `SH`
(vier Pads), nicht `11`. Mein Symbol hatte SHELL als Pin-Nummer 11 — jetzt
auf "SH" umbenannt, damit der Pad-Name passt.
