# SST v2 — PCB Finishing-Plan

Stand 2026-07-21. Erstellt aus Schaltplan-Netzliste + PCB-Zustand (KiCad 10.0.2, autoritativ via `kicad-cli`/`pcbnew`).

## Board-Status

- **4-Lagen**, 60 × 90 mm. Stackup: `F.Cu / In1.Cu=GND / In2.Cu=PWR / B.Cu`.
- **29 von 95 Bauteilen platziert** und teilverdrahtet (319 Segmente, 63 Vias): alle großen ICs/Stecker/Schalter/CMCs.
- **70 Passive fehlen noch auf der Platine:** `C1–C34`, `R1–R31`, `D2–D5`, `FB1`.
- **4 Zonen** definiert, aber **ungefüllt**.
- **Board-Netzliste ist veraltet ggü. Schaltplan** (19 `net_conflict`, v. a. am ADS131 U2) → `Update PCB from Schematic` ist Pflicht-Schritt 1.
- Firmware M0+M1 passt zum **Schaltplan**; nur die Platine hinkt hinterher.

## IC-Ankerpunkte (bereits platziert, mm)

| Ref | Bauteil | X | Y | Rolle |
|---|---|---|---|---|
| U1 | Pico 2 W (RP2350) | 119,3 | 68,7 | MCU, oben-mitte |
| U2 | ADS131M02 | 90,9 | 124,3 | 24-bit-ADC, unten-links |
| U_ANA_LDO1 | TPS7A4700 | 91,3 | 114,0 | rauscharme Analog-LDO |
| U_AAF1 | OPA2333 (dual) | 102,0 | 123,9 | Anti-Alias-Filter |
| U3 | DS3231 RTC | 115,7 | 116,6 | |
| Y1 | TCXO 8,192 MHz | 131,4 | 84,5 | → ADC_CLKIN |
| J_FORK1 / J_SHOCK1 | Poti-Stecker | 131,1 / 139,8 | ~93 | Sensor-Eingänge, rechts |
| L_FORK/SHOCK_CMC1 | Common-Mode-Chokes | ~131/140 | ~102 | |
| BZ1 | Buzzer | 114,9 | 87,5 | |

---

## 1. Finishing-Reihenfolge

1. **`Update PCB from Schematic`** (PCB-Editor: `Tools → Update PCB from Schematic`, F8).
   - Importiert die **70 fehlenden Footprints** (erscheinen geclustert — von Hand platzieren).
   - **Behebt die 19 U2-Netzkonflikte**: re-mappt die ADS131-Pads auf den aktuellen Schaltplan (AIN0=Fork, AIN1=Shock, Attenuator/Differential-Netze). ⚠️ **Bestehende Tracks an den alten U2-Netzen werden dabei ungültig** — der AIN-Bereich um U2 muss neu geroutet werden.
   - Weist die neuen **Netclasses** zu (siehe §2, liegen bereits im `.kicad_pro`).
2. **Passive platzieren** (§3): erst Decoupling, dann Analog-Frontend, dann ESD/Pull-ups.
3. **Routen** (§4): Analog-Frontend → Power → Digital.
4. **Zonen füllen** (`Edit → Fill All Zones`, `B`) — die 4 Zonen sind aktuell leer.
5. **DRC** iterieren (§5) bis sauber.

> Backup des Ausgangsstands liegt unter `scratchpad/sst_v2_backup/` (voller Ordner-Klon).

---

## 2. Netclasses (bereits gesetzt im `.kicad_pro`)

| Klasse | Clearance | Track | Via (Ø/Bohr) | Nets |
|---|---|---|---|---|
| **Analog_HiZ** | 0,25 | 0,25 | 0,6/0,3 | Sallen-Key/Attenuator/AIN, `ADC_CAP`, `ADC_VREF*`, Sensor-Stecker-Netze (22 Netze) |
| **Analog_PWR** | 0,25 | 0,40 | 0,7/0,35 | `+3V0_*`, `LDO_NRSS` |
| **Clock** | 0,25 | 0,20 | 0,6/0,3 | `ADC_CLKIN` |
| **SPI** | 0,20 | 0,20 | 0,6/0,3 | `ADC_SCK/SDI/SDO/CS`, `SD_*` |
| **Power** | 0,20 | 0,50 | 0,8/0,4 | `+VBAT*`, `+VBUS`, `+3V3_DIG`, `+3V3_EN`, `VSYS`, `MCU_RUN`, `VBAT_SENSE` |
| Default | 0,20 | 0,20 | 0,6/0,3 | Rest (GND, I2C, Buzzer, Digital) |

Track-Werte sind Defaults fürs **neue** Routing; bestehende Tracks bleiben geometrisch unverändert (nur DRC prüft schärfer). Jede Klasse hat eine eigene Farbe zur Sichtbarkeit beim Routen.

---

## 3. Platzierung der 70 Passiven

### 3a. Decoupling / Bypass (an den IC-Pin, GND-Via direkt am Pad)

**ADS131 U2 (unten-links):**
| Ref | Wert | Netz | Platzierung |
|---|---|---|---|
| **C3** | 220nF | `ADC_CAP` (U2.18) | **kürzest möglich am CAP-Pin** — interne Referenz-Stützung, kritisch |
| C1 / C5 | 1µF / 100nF | `+3V0_ANA` (AVDD U2.1) | direkt am AVDD-Pin |
| C6 / C22 | 10µF | `+3V0_ANA` | Bulk am LDO-Ausgang |
| C23 / C24 | 100nF / 10nF | `+3V0_ANA` | verteilt an AVDD |
| C2 | 1µF | `+3V0_DVDD` (DVDD U2.20) | am DVDD-Pin, hinter FB1 |
| **FB1** | BLM18PG471 | `+3V0_ANA`→`+3V0_DVDD` | Ferrit **neben U2**, speist ADC-Digitalversorgung sauber |
| C4 + R1 | 100nF + 10k | `ADC_RST` (U2.11) | R1 Pull-up→`+3V3_DIG`, C4→GND; am RST-Pin |

**Analog-LDO U_ANA_LDO1 (TPS7A4700):**
- **C25** 10nF → `LDO_NRSS` (Noise-Reduction/Soft-Start-Pin) — **direkt am Pin**, bestimmt die Rauscharmut.

**Pico U1 + Digital (`+3V3_DIG`):** C19 100nF, C20 10nF, C21 4,7µF, C30/C32/C34 100nF, C31/C33 10µF — je 100nF an jedem VCC-Pin von Pico, RTC (U3), SD (J_SD1), OLED (J_OLED1).

**Power-Eingang (`+VBAT_SW`, bei J_PWR1/D1):** C26 100µF Tant (Bulk) + C27 10µF + C28 100nF.

**Sensor-Excitation-Rails** (aus `+3V0_ANA` über 47R gefiltert):
- Fork: **R16** 47R → `+3V0_ANA_FORK`; C13 10µF + C14 100nF + C15 10nF an J_FORK1.
- Shock: **R17** 47R → `+3V0_ANA_SHOCK`; C16 10µF + C17 100nF + C18 10nF an J_SHOCK1.

**Battery-Sense:** R19/R20 100k (Teiler `+VBAT_SW`→`VBAT_SENSE`→GND) + C29 100nF, an U1.34 (GP28).

### 3b. Analog-Frontend — das Herzstück

Pro Kanal: **Poti-Wiper → CMC → Sallen-Key-Tiefpass (2. Ordnung, OPA2333) → Attenuator → differentielles RC → ADS131-AIN.** Alle RC-Teile kompakt **zwischen U_AAF1 (102,124) und U2 (91,124)** platzieren, links/rechts symmetrisch.

**Fork-Kanal (OPA2333-Sektion B, Pins 5/6/7):**
| Ref | Wert | Funktion |
|---|---|---|
| R4 / R5 | 22k / 22k | Sallen-Key-Serienwiderstände (`WIPER_F`→`SK_NODE`→`AAF_FB`) |
| C7 / C8 | 47nF / 22nF | Sallen-Key-Kondensatoren (`SK_NODE`→GND / →`AAF_OUT`) |
| R6 / R7 | 1,5k / 1,0k (0,1%) | Attenuator `AAF_OUT`→`ATTEN`→GND (≈0,4×) |
| R8 / R9 | 1k / 1k | Serien-R in `AIN_P` / `AIN_N` (aus `ATTEN` / `VREF_M`) |
| **C9** | 10nF | **differentielles Anti-Alias direkt an U2.3/U2.4** |

**Shock-Kanal (OPA2333-Sektion A, Pins 1/2/3):** R10/R11 22k, C10 47nF, C11 22nF; R12 1,5k + R13 1,0k; R14/R15 1k; **C12** 10nF direkt an U2.5/U2.6.

**Layout-Regeln Analog-Frontend:**
- `SK_NODE` und die 22k-Hi-Z-Knoten **so kurz wie möglich**.
- **C9/C12 unmittelbar an den AIN-Pins** des ADS131 (das ist der letzte Anti-Alias-Pol).
- Die beiden AIN-Leitungen als **symmetrisches Differential-Paar** führen, `VREF_M` parallel dazu.
- Mit GND umgeben (Guard); kein SPI/Clock unter dem Frontend über In1 kreuzen.

### 3c. ESD an den Steckern
D2/D3 (PESD5V0S2BT, SOT-23 bidirektional: Pin 1 Leitung, Pin 3 GND) an J_FORK1 (Wiper/VREF), D4/D5 an J_SHOCK1 — **am Stecker-Eintritt, vor den CMCs**.

### 3d. Pull-ups / Serien-R
- I2C 4,7k: R21/R22 (IMU0 SDA/SCL), R23/R24 (IMU1), R25/R26 (Display) — nahe Pico oder Bus-Mitte.
- 10k Pull-ups: R2/R3 (ADC CS/DRDY), R27/R28 (Buttons), R31 (SD_CS), R18 (`3V3_EN`).
- **R29/R30** 47R Serien-Dämpfung am Buzzer (BUZ_DRV_A/B → BZ1).

---

## 4. Routing-Strategie

### 4.1 Lagen
- **In1.Cu = durchgehende Massefläche (GND), nicht splitten.** Für Mixed-Signal dieser Größe ist eine ununterbrochene Masse besser als ein Split/Moat; Analog-Integrität über Platzierung + kurze lokale Rückstrompfade.
- **In2.Cu = Power**: `+3V3_DIG` als Hauptfläche, die bestehende lokale **`+3V0_ANA`-Insel** unter U2/AAF/LDO belassen, kleine `+3V0_DVDD`-Insel hinter FB1.
- F.Cu / B.Cu = Signal; GND-Füllung auf Restflächen.

### 4.2 Analog
- Frontend als kompakte Insel unten-links; Rückstrom bleibt lokal über die GND-Plane.
- AIN-Paare symmetrisch/geführt, C9/C12 am Pin.

### 4.3 TCXO / Clock ⚠️
- **Erledigt (Rev. 3):** Y1 (ECS-2520MVLC) sitzt jetzt bei U2, R38 am Oszillatorausgang, C19 direkt an Y1; XO_OUT im Analogbereich nur auf F.Cu.
- **Y1 (131,85) liegt ~56 mm vom ADS131-CLKIN (U2, 91,124) entfernt** — für 8,192 MHz eine lange Clock-Leitung.
- **Empfehlung:** Y1 näher an U2 rücken, falls das Layout es zulässt. Sonst `ADC_CLKIN` kürzest, GND-begleitet routen und **Serienwiderstand (22–33 Ω) am TCXO-Ausgang** gegen Überschwingen vorsehen. Clock nicht über Analog-Hi-Z-Knoten führen.

### 4.4 Power
- `+VBAT_SW`/Bulk breit (≥0,5 mm, Power-Klasse), sternförmig von der Quelle.
- FB1 trennt `+3V0_ANA`→`+3V0_DVDD`; R16/R17 (47R) trennen die Excitation-Rails.

### 4.5 Zonen füllen
Nach dem Routen `Fill All Zones`. Aktuell sind alle 4 Zonen leer.

---

## 5. DRC-Triage (Ausgangsstand: 107 Violations)

| Einordnung | Typen | Aktion |
|---|---|---|
| **Löst sich beim Fertigstellen** | 70 `missing_footprint`, 43 `unconnected_items`, 19 `net_conflict` | via Update-from-Schematic + Platzieren/Routen |
| **Echt — prüfen/beheben** | 2 `shorting_items` (D1), 4 `clearance`, 4 `copper_edge_clearance`, 3 `items_not_allowed` | siehe unten |
| **Kosmetisch/später** | silk (33), `solder_mask_bridge` (21), `lib_footprint_issues` (29), dangling (11) | vor Fertigung aufräumen |

**Konkret zu prüfen:**
- **D1 (SMAJ5.0CA TVS, Power-Eingang) @(141, 84,5):** DRC meldet Short `GND ↔ +VBAT_SW`. Bei einer TVS über der Rail ist das netz-technisch normal — prüfe, ob ein echtes Track/Pad-Problem vorliegt oder ein Artefakt des veralteten Netzstands (nach Update-from-Schematic erneut prüfen).
- **`items_not_allowed` (3):** Pico-Antennen-Keepout („RF Copper Keep Out" von U1) — H1-Bohrung und U1-Paste-Pads liegen darin; großteils erwartbar, aber H1-Position ggf. anpassen.
- `copper_edge_clearance` (4): Kupfer < 0,5 mm zum Boardrand — vor Fertigung beheben.
- **Hinweis:** Mein Netclass-Setup hat ~17 zusätzliche Clearance-Flags auf bestehenden Analog-Tracks erzeugt (schärfere Analog-Clearance) — beim Re-Routing des Analogteils mitbereinigen.

---

## 6. Firmware-Abgleich (nicht am Board, aber offen)

- **`set(PICO_BOARD pico_w)` → `pico2_w`** (`firmware/CMakeLists.txt:17`). Board trägt einen **Pico 2 W (RP2350)**; ein RP2040-UF2 bootet darauf **nicht**. Header-Pinout ist kompatibel.
- **Buzzer differenziell** (GP21+GP22 über R29/R30) — Firmware treibt nur GP22 (`buzzer.h:6`) einseitig. Für vollen Pegel GP21 gegenphasig treiben.
- **Attenuator im Signalpfad** (R6/R7, R12/R13 ≈ 0,4×): Die Firmware-Kalibrierung (`TRAVEL_SCALE`, „1,15 V Vollhub → ~26400 Codes") muss die Abschwächung **und** die feste 1,2-V-ADC-Referenz berücksichtigen. Beim Hardware-Bringup gegen echte Messung verifizieren.
