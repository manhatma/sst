# Plan: ADS131M04 + 4× ICM-42686-P — Rev. 3

Stand 2026-09-04. Ersetzt Rev. 2 (ADS131M02 + 4× MPU6050). Branch
`claude/upgrade-adc-sensor-wGFyG`. Datenblätter unter `firmware/docs/`.

## 0. Was sich gegenüber Rev. 2 ändert und warum

| Rev. 2 | Rev. 3 | Grund (Quelle) |
|---|---|---|
| ADS131M02, 2 Kanäle | **ADS131M04, 3 von 4 Kanälen** (Fork, Shock, Speisung) | Phase E (Commit 8776e8c) misst die Poti-Speisung und normalisiert ratiometrisch (`linear_ads1115.c:250`). Der M02 hat keinen Kanal dafür übrig. |
| Serienwiderstand in der Pot-Speisung, 1,15 V Vollhub | **Gepufferte 1,0-V-Speisung** aus 3V3-Teiler mit RC und Opamp | Pot-Toleranz ±20 % hätte den 1,2-V-FSR überschritten; Ripple des RT6154 (PFM) geht sonst 1:1 ein. |
| 1 kΩ + 100 nF am Schleifer | **Schleifer-Puffer (Opamp), RC erst dahinter** | `hardware-drdy-checklist.md:215`: kein C auf der Schleiferleitung, ELPM75-Schleiferstrom ≤ 10 µA. ADS131M04 hat bei Gain 1 nur 330 kΩ Eingangsimpedanz (SBAS890D Tab. 6.5, Gl. 4), das ergäbe bis 0,75 % positionsabhängigen Fehler. |
| 4× MPU6050 an I2C, 400 kHz, freilaufender Takt | **4× ICM-42686-P an SPI, CLKIN 32 kHz aus dem ADC-Takt** | MPU6050: ±16 g, kein Taktanschluss, I2C über 1 m Kabel. Vorgaben aus dem Interview: ≥ 32 g, harter Sync < 1 ms, Kabel bis 1 m. |
| TCXO ±25 ppm | **CMOS-Oszillator 8,192 MHz** (XO, ±50 ppm reicht) | ADS131M04 hat keinen Quarztreiber (kein XTAL2-Pin, SBAS890D Abschnitt 5), braucht LVCMOS-Takt. Genauigkeit ist egal, alle Raten hängen am selben Takt. |
| MPU-INT je Bus auf einem GPIO | **entfällt** | Zwei Push-Pull-INT auf einer Leitung wären ein Kurzschluss. FIFO wird gepollt, Rate ist durch CLKIN bekannt. |
| 2,2-kΩ-I2C-Pull-ups bleiben | **entfallen** (beide I2C-Blöcke ungenutzt) | Kein I2C-Sensor mehr. |

Gescheiterte Alternative, dokumentiert damit sie nicht wieder aufkommt:
**ICM-45686** (AN-000478 Kap. 7): CLKIN 20–40 kHz, ODR skaliert mit
fCLKIN/32 kHz, ODR-Liste ohne 1000 Hz (800/1600). 1000 Hz bräuchten 20 kHz
oder 40 kHz CLKIN; 8,192 MHz / 20 kHz = 409,6 ist nicht ganzzahlig (Faktor 5
fehlt in 2^13·1000). Nur mit zweitem Takt-IC oder 8:5-Resampling lösbar.
Verworfen zugunsten des ICM-42686-P mit nativer 1-kHz-ODR.

## 1. Verifizierte Datenblattwerte

### ADS131M04 (TI SBAS890D, Mai 2021, `firmware/docs/ads131m04.pdf`)

| Punkt | Wert | Fundstelle |
|---|---|---|
| Gehäuse | TSSOP-20 (PW) oder WQFN-20 (RUK) | Abschn. 5 |
| TSSOP-Pins | 1 AVDD, 2 AGND, 3 AIN0P, 4 AIN0N, 5 AIN1N, 6 AIN1P, 7 AIN2P, 8 AIN2N, 9 AIN3N, 10 AIN3P, 11 SYNC/RESET, 12 CS, 13 DRDY, 14 SCLK, 15 DOUT, 16 DIN, 17 CLKIN, 18 CAP, 19 DGND, 20 DVDD | Fig. 5-2 |
| Takt | LVCMOS an CLKIN, **kein Quarzoszillator**; HR-Modus 0,3 bis 8,4 MHz, nominal 8,192 MHz; tw(CLH/CLL) ≥ 49 ns | Tab. 6.3, 6.6, Abschn. 8.3.x |
| Datenrate | fDATA = fCLKIN / 2 / OSR; OSR 4096 → **1000 SPS** | Tab. 8-3 |
| CLOCK-Register 0x03 | Reset 0x0F0E; Bit 11:8 CH3..CH0_EN, Bit 5 TBM, Bit 4:2 OSR (101b = 4096), Bit 1:0 PWR (10b = HR). Kein XTAL_DIS. | Tab. 8-17 |
| Frame | **immer 6 Wörter** (Status, CH0..CH3, CRC) = 18 Byte bei 24-bit-Wörtern, auch bei deaktivierten Kanälen; Ausgangs-CRC nicht abschaltbar | Abschn. 8.5.1.7, Z. 3063 |
| Eingang, Gain 1 | Absolutbereich AGND − 1,3 V bis AVDD; VIN ±1,2 V; **Differenz-Eingangsimpedanz 330 kΩ** (× 4,096 MHz / fMOD) | Tab. 6.3, 6.5, Gl. 4 |
| Referenz | intern 1,2 V, ±0,1 %, Drift 7,5 typ / 20 max ppm/°C | Tab. 6.5 |
| Rauschen | OSR 4096, Gain 1, HR: **3,38 µV rms**, 108 dB DR (19,4 ENOB) | Tab. 7-1, 7-2 |
| Reset | SYNC/RESET low ≥ **2048 tCLKIN** (250 µs) = Reset; 1 bis 2047 tCLKIN = nur SYNC; danach tREGACQ 5 µs | Tab. 6.6 |
| DRDY | DRDY_FMT = 0 (Pegel): geht bei ungelesenen Daten vor der nächsten Wandlung kurz high, es gibt also immer eine fallende Flanke. DRDY_FMT = 1 (Puls): ungelesene Daten lassen einen Puls ausfallen → **FMT = 0 verwenden** | Abschn. 8.5.1.5 |
| Lesezeitpunkt | Nicht lesen, während eine Wandlung fertig wird (DRDY-Puls wird sonst unterdrückt) → Frame direkt nach DRDY, dauert 18 B / 8 MHz ≈ 18 µs von 1000 µs | Z. 3572 |
| SPI | SCLK-Periode ≥ 40 ns bei DVDD 2,7–3,6 V (25 MHz); Mode 1 | Tab. 6.6 |
| CAP | 220 nF nach DGND (DVDD > 2,7 V) | Abschn. 10.1 |
| Abblockung | AVDD und DVDD je 1 µF direkt am Pin | Abschn. 10.3 |
| ID-Register | Reset 24xxh, CHANCNT = 4 | Abschn. 8.6.1 |

### ICM-45686 (nur zur Dokumentation der Ablehnung, AN-000478 Rev. 1.0)

CLKIN 20–40 kHz auf Pin 9 (geteilt mit INT2/FSYNC, `PADS_INT2_CFG_OVRD_VAL = 2`),
RTC_CONFIG 0x26 Bit 5 RTC_MODE, Bit 6 RTC_ALIGN (Phasen-Reset mehrerer Geräte),
FIFO 2 kB / 8 kB, Pakete 16 B oder 20 B (Hi-Res). ODR-Liste 6400 … 1,5625 Hz
in Zweierschritten, ohne 1000 Hz (TDK-Treiber `inv_imu_defs.h`, Zephyr
`dt-bindings/sensor/icm45686.h`).

### ICM-42686-P (TDK DS-000348, `firmware/docs/ds-000348-icm-42686-p-datasheet.pdf`)

| Punkt | Wert | Fundstelle |
|---|---|---|
| Gehäuse, Pins | LGA-14. 1 AP_SDO/AD0, 4 INT1, 5 VDDIO, 6 GND, 7 RESV→GND, 8 VDD, **9 INT2/FSYNC/CLKIN**, 11 RESV→GND, 12 AP_CS, 13 AP_SCLK, 14 AP_SDI; 2, 3, 10 RESV (NC oder GND) | Abschn. 4.1 |
| Bereiche | Accel ±32 g (1024 LSB/g, 16 bit) bis ±2 g; Gyro ±4000 dps bis ±31,25 dps | Tab. 1, 2 |
| Rauschen | Accel 70 µg/√Hz, Gyro 5,3 mdps/√Hz | Abschn. 1 |
| ODR | 32 k … 12,5 Hz in Zweierschritten plus 500 Hz, **1 kHz nativ**; mit CLKIN skaliert ODR um fCLKIN/32 kHz, bei 32,000 kHz exakt | Abschn. 12.5 |
| CLKIN | **31 bis 50 kHz** (Tab. 4 und Abschn. 3.7, Note 1: „expected results based on design"), tHIGH ≥ 1 µs; Genauigkeit ODR mit CLKIN ±50 ppm statt ±1 % (PLL) bzw. ±8 % (RC) | Tab. 4, Abschn. 3.7, 12.1 |
| CLKIN aktivieren | Bank 0 INTF_CONFIG1 (0x4D) Bit 2 RTC_MODE = 1; Bank 1 INTF_CONFIG5 (0x7B) Bit 2:1 PIN9_FUNCTION = 10b | Abschn. 12.5, 14/15 |
| Timestamp im RTC-Modus | TMST_RES = 0 (1 µs): Werte um 32,768/fRTC skalieren; bei 1 kHz und 32 kHz liest man 976/977 → 1000 µs | Abschn. 12.5 |
| FIFO | physisch 2048 B, Lesecache 2 Pakete, Treiberpuffer 2080 B; Pakete 16 B (Accel+Gyro+Temp+TMST) oder 20 B Hi-Res | Abschn. 6.1, 6.2 |
| Hi-Res (FIFO_HIRES_EN) | 19 bit Gyro, 18 bit Accel; **erzwingt ±32 g und ±4000 dps**, 4096 LSB/g und 65,5 LSB/dps | Abschn. 6.1 |
| INT-Pins | INT1/INT2 je Push-Pull oder Open-Drain | Abschn. 4.1 |
| SPI | 3- oder 4-Draht, SCLK ≤ 24 MHz, Mode 0/3 | Abschn. 9, Note 4 |
| Versorgung | VDD 1,71–3,6 V, VDDIO 1,71–3,6 V | Abschn. 1 |
| WHO_AM_I | 0x44 | Zephyr `icm4268x_reg.h` |

Zum Vergleich liegen ICM-42688-P (DS-000347) und ICM-45686 (DS-000577)
ebenfalls unter `firmware/docs/`.

### 74HC4040 (Nexperia Rev. 8, 2024)

fmax min 6 MHz bei 2,0 V, 30 MHz bei 4,5 V; bei 3,3 V interpoliert ≥ 15 MHz.
8,192 MHz am CP-Eingang ist sicher. Q8 (÷256) = **32,000 kHz**.

## 2. Systemarchitektur

### 2.1 Taktbaum (ein Oszillator, alles phasenstarr)

```
XO 8,192 MHz (CMOS, 3,3 V)
 ├─ 33 Ω ─► ADS131M04 CLKIN      fMOD 4,096 MHz, OSR 4096 → 1000 SPS
 └─ 74HC4040 CP, Q8 = 32,000 kHz
      └─ 74LVC125 (4 Puffer, je 33 Ω) ─► 4× ICM-42686-P Pin 9 (CLKIN)
                                          RTC_MODE = 1, ODR 1000 Hz exakt
```

Beide Raten sind Ganzzahlteiler desselben Takts: ADC 8,192 M / 8192, IMU
32 k / 32. Frequenzdrift zwischen Poti- und IMU-Strom ist damit null.
Phasenversatz zwischen den IMUs ist konstant und kleiner als eine Periode; er
wird beim Aufnahmestart über TMST_STROBE je IMU gemessen und im Header
abgelegt (M5). Aktivierung je IMU: RTC_MODE (Bank 0, 0x4D Bit 2) und
PIN9_FUNCTION = CLKIN (Bank 1, 0x7B Bit 2:1). FIFO-Zeitstempel sind im
RTC-Modus um 32,768/32 zu skalieren (DS-000348 Abschn. 12.5).

### 2.2 Analog-Frontend (Potis)

```
3V3 ─ 23 kΩ ─┬─ 10 kΩ ─ GND        1,0 V Nennwert, RC mit 10 µF (fc ≈ 2 Hz)
             ├─ 10 µF ─ GND         filtert RT6154-PFM-Ripple
             └─►│+  OPA2333 A │──┬─► Pot-Speisung Fork (Kabel)
                └──────────────┘  ├─► Pot-Speisung Shock (Kabel)
                                  └─ 1 kΩ ─┬─ AIN2P (c_exc)   AIN2N ─ AGND
                                           └─ 10 nF ─ AGND

Schleifer Fork (Kabel) ─►│+  OPA2333 B │─ 1 kΩ ─┬─ AIN0P   AIN0N ─ Pot-GND-Ader Fork
                          └─────────────┘        └─ 10 nF ─ AGND
Schleifer Shock          ─► gleich mit OPA2333 C ─ AIN1P / AIN1N ─ Pot-GND-Ader Shock
```

- **Speisung 1,0 V**: 17 % Headroom zu 1,2 V FSR, unabhängig vom
  Poti-Widerstand (Fork VLP 200 mm und Shock ELPM75 haben verschiedene Werte).
- **Schleifer-Puffer**: Schleiferstrom = Opamp-Biasstrom (pA) plus
  Kabelkapazität (≈ 3 nA bei 2 m/s), weit unter den 10 µA des ELPM75. Die
  330 kΩ des ADC belasten nur noch den Opamp-Ausgang.
- **RC 1 kΩ + 10 nF hinter dem Puffer** (fc 16 kHz): Kickback-Reservoir für
  den Switched-Cap-Eingang, kein Anti-Alias im Nutzband. Der Serien-R ergibt
  mit 330 kΩ 0,3 % Gain-Fehler, identisch auf allen drei Kanälen → kürzt sich
  in `raw · 26400 / c_exc`.
- **Opamp-Wahl**: RRIO, Ib ≤ 100 pA, VOL bei µA-Last < 1 mV. Kandidaten
  OPA2333/TLV2333 (Zero-Drift, 10 µV Offset) oder MCP6004 (Budget, 4,5 mV
  Offset, wird per Baseline kalibriert). Vierfach-Opamp deckt alle drei
  Kanäle ab.
- **Remote Sense**: AINxN auf die Pot-GND-Ader am Stecker, nicht auf AGND.
  Kompensiert den Masseversatz im Kabel. Eingangsbereich AGND − 1,3 V lässt
  das zu.
- **Skalierung**: `value16 = raw_wiper · 26400 / raw_exc`, Vollhub = 26400
  counts wie beim ADS1115 (Phase E). Rauschen: 3,38 µV rms auf 37,9 µV/count
  → 0,09 counts rms (ADS1115: ≈ 1 count).
- **Schutz**: 1 kΩ Serien-R vor jedem Opamp-Eingang plus ESD-Diode (z. B.
  PESD3V3) an den Kabel-Eingängen.

### 2.3 IMU-Bus (SPI-Stern, 4 Knoten, je 1 m Kabel)

- Pico → PIO-SPI (PIO1, 1 SM, Mode 0, **2 MHz**, DMA über DREQ_PIO1_TX/RX).
  Hardware-SPI1 bleibt beim ADS131M04 (bestehender Treiber).
- Gemeinsam: SCLK, MOSI, MISO, CLKIN, 3V3, GND. Je Knoten: CS.
- Kabel 7 Adern + Schirm, verdrillt SCLK/GND und MISO/GND. Serien-R 33 Ω an
  allen Treiberausgängen auf dem DAQ, 33 Ω an MISO auf jeder Sensor-PCB.
- Sensor-PCB: ICM-42686-P (LGA-14), 100 nF + 1 µF an VDD, 100 nF an VDDIO,
  33 Ω an MISO, 10 kΩ Pull-up an CS (Bus bleibt definiert, wenn der Knoten
  fehlt). Footprint für KX134-1211 (±64 g) vorsehen, nicht bestücken.
- Datenrate: 4 × 1000 × 20 B = 80 kB/s (Hi-Res) bzw. 64 kB/s (16 bit).
  Bei 2 MHz SCLK ≈ 32 % Busauslastung. Burst alle 50 ms je IMU: 50 Pakete =
  1000 B, FIFO 2 kB → 50 ms Reserve gegen Scheduler-Verspätung.
- Bei Fehlern am Aufbau (Reflexionen, Übersprechen): erst SCLK auf 1 MHz
  und Slew-Rate-Limit (RP2040 `gpio_set_slew_rate`), dann Kabel.

### 2.4 Pin-Map Pico W (SPI_MICROSD = ON, I2C-Display)

| GPIO | Funktion | Anmerkung |
|---|---|---|
| 0, 1 | UART debug | unverändert |
| 2, 3 | PIO0 I2C (RTC, OLED) | unverändert |
| 4, 5 | Buttons | unverändert |
| 6 | frei | (Display-RST nur im SPI-Display-Build) |
| 7 | ADS131 SYNC/RESET | Output, 10 kΩ Pull-up |
| 8 | IMU SCLK (PIO1) | |
| 9 | IMU MOSI (PIO1) | |
| 10 | ADS131 SCLK (SPI1) | |
| 11 | ADS131 DIN (SPI1 TX) | |
| 12 | ADS131 DOUT (SPI1 RX) | |
| 13 | ADS131 CS | GPIO, 10 kΩ Pull-up |
| 14 | IMU MISO (PIO1) | |
| 15 | IMU CS0 | |
| 16–19 | SPI0 MicroSD | unverändert |
| 20 | ADS131 DRDY | Input, Raw-IRQ, fallende Flanke |
| 21 | IMU CS1 | (im ADS1115-Build: Fork-DRDY) |
| 22 | Buzzer | unverändert |
| 26 | IMU CS2 | |
| 27 | IMU CS3 | (im ADS1115-Build: Shock-DRDY) |
| 28 | Reserve | z. B. gemeinsame IMU-INT-Leitung, open-drain, später |
| 29 | VSYS/3 | unverändert |

`SPI_DISPLAY` kollidiert mit GPIO 10–13 → `#error` bleibt.

### 2.5 DMA und IRQ

| Ressource | Nutzer |
|---|---|
| DMA-Kanäle | ADS131: TX + RX (SPI1), IRQ auf DMA_IRQ_0. IMU: TX + RX (PIO1), ohne IRQ, Completion gepollt. SD-Lib: DMA_IRQ_1 (`.DMA_IRQ_num`). cyw43: eigene. |
| GPIO-IRQ | DRDY über `gpio_add_raw_irq_handler`, koexistiert mit Pushbutton-Callback |
| PIO | PIO0 SM0: I2C. PIO1: cyw43 (1 SM) + IMU-SPI (1 SM). |
| Core 0 | DRDY-ISR → DMA-ISR (Poti-Sample in Puffer), IMU-Burst-Scheduler im RECORD-Handler |
| Core 1 | SD-Writes (unverändert), zusätzlich IMU-Blöcke (M5) |

Poti-Pfad läuft komplett in ISRs und wird von nichts blockiert. IMU-Pfad
läuft ohne IRQ per DMA, Polling im 50-ms-Raster.

## 3. Meilensteine

Jeder Meilenstein baut und bootet für sich.

### M0 — Config-Plumbing

- `hardware_config.h`: `ADS131_SENSORS`-Block (SPI1, CS 13, DRDY 20, RESET 7,
  `#error` bei SPI_DISPLAY), `IMU_ICM42686`-Block (PIO1, SCLK 8, MOSI 9,
  MISO 14, CS 15/21/26/27).
- `CMakePresets.json`: Preset `spi_card-i2c_disp-ads131m04-icm42686`
  (+ `-debug`), `ADS131_SENSORS=ON`, `IMU_ICM42686=ON`.
- `CMakeLists.txt`: Flags, `hardware_spi hardware_dma hardware_pio`,
  Quellenauswahl. Vorlage: Diff des Branches `ads131m02-upgrade`.

### M1 — ADS131M04-Treiber, ratiometrisch

Basis: `linear_ads131m02.c` aus `ads131m02-upgrade` (Frame-Helfer,
Registerzugriff, DRDY→DMA-Kette, Standby/Wake). Änderungen:

- Frame 18 Byte (6 Wörter), CH0 = Fork, CH1 = Shock, CH2 = Speisung, CH3 aus.
  CLOCK = 0x0716 (CH2..0 an, OSR 4096, HR). MODE = 0x0110 (RESET-Flag
  gelöscht, 24 bit, DRDY_FMT 0). GAIN = 0. ID-Prüfung CHANCNT == 4.
- ISR: `raw_exc` mitlesen, `value16 = raw · 26400 / raw_exc` (Clamp
  `raw_exc` ≥ 2^20, sonst Kanal als fehlend markieren). Baseline-Abzug wie
  gehabt, 0xFFFE-Kappung, 0xFFFF reserviert.
- `check_availability()` ohne blockierende SPI-Zugriffe während des
  Samplings: Lebendigkeit aus dem Sample-Zähler (letztes DMA-Ende < 10 ms).
  Der alte Branch pausiert dafür den DRDY-IRQ; das kostet je Aufruf ein
  Sample und entfällt.
- `last_c_exc()`-Getter für die CEXC-Anzeige in `on_cal_exp` (heute
  `linear_sensor_ads1115_last_c_exc`, `main.c:131`), gleiche Signatur.
- Reset ≥ 300 µs low, danach 10 µs, dann Konfiguration.
- main.c gegen den heutigen Stand: Alarm-Callback `data_acquisition_cb`
  (`main.c:251`) unter `#ifndef ADS131_SENSORS`, `ads131_begin/end` in
  `on_rec_start`/`on_rec_stop`, `SAMPLE_RATE` → `ads131_sample_rate()`,
  Standby/Wake in `on_sleep`/`on_waking`. CAL-Magic `'C','A','L',2` wie im
  alten Branch, gilt für alle Builds.
- CMake: `sst.h`-as5600-Guard und Link-Bedingung um `ADS131_SENSORS`
  erweitern.

Verifikation: DRDY-Periode 1,000 ms; Frame 18 B; 10-min-Aufnahme
`(size − 16) / 4 = 600000 ± 1`; CEXC-Anzeige ≈ 26400 ± 3 % (Fenster wie
Phase E E6); Vergleich mit ADS1115-Board: Zählweite gleich; Sleep/Wake ohne
Sofort-Aufwachen.

### M2 — Analog-Bringup (Hardware, kein Code)

Opamp-Board mit Speisung und Pufferung, Remote Sense, ESD. Messpunkte:
Speisung 1,00 V ± 2 %, Ripple < 1 mV bei PFM-Betrieb (Aufnahme aus,
`SMPS_FORCE_PWM` low), Schleifer-Puffer-Offset < 1 mV bei Pot am Anschlag,
Rauschen im Stillstand < 0,5 counts rms.

### M3 — ICM-42686-P: Treiber, PIO-SPI, CLKIN, 1 kHz, RAM-Ring

- `firmware/src/sensor/icm42686.c/.h` (neu, ~500 LOC), PIO-SPI-Programm
  (`pio_spi` aus pico-examples, CPHA 0) mit DMA-Helfern.
- Init je IMU: WHO_AM_I == 0x44, Soft-Reset, Bank 1 INTF_CONFIG5
  PIN9_FUNCTION = 10b (CLKIN), Bank 0 INTF_CONFIG1 RTC_MODE = 1, ODR 1 kHz
  für Accel und Gyro, AAF laut Datenblatt, FIFO Stream + TMST +
  FIFO_HIRES_EN. Hi-Res legt ±32 g und ±4000 dps fest (4096 LSB/g,
  65,5 LSB/dps), die FS-Register sind dann ohne Wirkung. Nicht antwortende
  IMUs: `available = false`.
- Scheduler auf Core 0 im RECORD-Handler (`state_handlers[RECORD]`, heute
  `dummy`, `main.c:936`): alle 50 ms je IMU FIFO_COUNT lesen (kurz,
  blockierend), Burst per DMA, nächste IMU nach Completion. Overflow-Bit
  prüfen, Zähler.
- **Clip-Zähler** je IMU und Achse (|a| ≥ 0,98 · FSR) für die Entscheidung
  über den KX134-Footprint.
- Sync: beim Start FIFO-Reset aller IMUs, dann TMST_STROBE je IMU und
  ADS131-Sample-Index festhalten → Phasenversatz pro IMU.
- Daten: RAM-Ring 128 Samples je IMU, Debug-Dump über UART/TCP. Noch nicht
  in .SST.
- Sleep: PWR_MGMT0 alle Sensoren aus in `on_sleep`, Re-Init in `on_waking`.

Verifikation: SPI-Analyzer: 4 CS-Zyklen pro 50 ms, Bursts ≈ 1000 B; Rate
= 1000/s ± 0,01 % je IMU über 10 min (nur noch Zähl-, keine Taktabweichung);
keine FIFO-Overflows; Poti-Sample-Count währenddessen weiterhin
`600000 ± 1`; DRDY-Jitter unverändert.

### M4 — entfällt (Buzzer vorhanden)

### M5 — Erweitertes Dateiformat

Header Version 4; IMU-Blöcke als eigener Stream in der Datei (nicht in
`struct record`, damit gosst/Dashboard für Version 3 unverändert bleiben):
pro IMU-Burst ein Block mit IMU-Index, ADC-Sample-Index des ersten Samples,
Anzahl, dann Hi-Res-Pakete. Core-1-Protokoll um `IMU_DUMP` erweitern.
SD-Last ≈ 84 kB/s. gosst: Reader für Version 4, Phasenversatz aus Header
anwenden, IMU-Daten als Zeitreihen auf dem 1-kHz-Raster der Potis.

## 4. Stückliste Frontend (neu gegenüber Rev. 2)

| Bauteil | Zweck |
|---|---|
| ADS131M04 PW (TSSOP-20) | ADC, 3 Kanäle genutzt |
| XO 8,192 MHz, CMOS 3,3 V (z. B. SiT2024, ECS-2520MV) | Master-Takt |
| 74HC4040 | ÷256 → 32 kHz |
| 74LVC125 | 4× CLKIN-Puffer für die Kabel |
| OPA2333 ×2 oder OPA4333 (alternativ MCP6004) | Speisung + 2 Schleifer-Puffer |
| 4× ICM-42686-P auf Sensor-PCB | IMU, Footprint KX134-1211 vorsehen |
| Steckverbinder 8-polig je Sensor (z. B. M8 8-pin oder JST-GH 8) | 7 Adern + Schirm |

## 5. Risiken und offene Punkte

1. **CLKIN-Spezifikation des ICM-42686-P trägt Note 1** („expected results
   based on design, not guaranteed in production"). 32,000 kHz liegt mittig
   im Bereich 31–50 kHz; beim M3-Bringup ODR-Lock am Analyzer nachweisen.
2. **SPI über 1 m Kabel bei 2 MHz.** Am Aufbau mit Analyzer prüfen; Fallback
   1 MHz. Datenrate reicht dann noch (64 % Auslastung mit Hi-Res).
3. **Opamp-Ausgang nahe 0 V.** Bei Pot am unteren Anschlag muss der Puffer
   unter 1 mV kommen; mit µA-Last erfüllt, im M2-Bringup messen.
4. **`multicore_fifo_push_blocking` im ISR** (unverändert aus Rev. 2): 2 s
   Reserve bei 2048er-Puffer, mit IMU-Blöcken (M5) neu bewerten.
5. **Clipping > 32 g.** Poti-Ableitung zeigte bis 80 g, vermutlich
   rauschbedingt überschätzt. Clip-Zähler aus M3 entscheidet über KX134.
6. **CALIBRATION-Migration** erzwingt einmalige Neukalibrierung auf allen
   Boards, auch ADS1115. In Release-Notes aufnehmen.
7. **DMA-Budget**: 4 eigene Kanäle + SD + cyw43; `dma_claim_unused_channel(true)`
   macht Engpass beim Boot sichtbar.
