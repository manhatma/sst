# Protokoll: Verifikation der Hardware-Annahmen (DRDY-Plan)

Datum: 2026-08-13. Geprüft vor Umsetzung von
[hardware-drdy-checklist.md](hardware-drdy-checklist.md) /
[plan-drdy-resampling.md](plan-drdy-resampling.md) AP0/AP1.
Methode: jede Annahme galt als falsch, bis Code, Datenblatt oder Rechnung
sie bestätigt hat.

## Ergebnis

**Die Hardware-Checkliste ist freigegeben.** Kein Fehler in den
Hardware-Annahmen gefunden. Drei Software-Referenzen des Plans sind
veraltet (Abschnitt 4). Sie blockieren die Hardware nicht.
AP0 Test 2 bleibt zwingendes Gate vor der Firmware-Kette.

## 1. Pins und Firmware (gegen Code geprüft)

| # | Annahme | Quelle | Befund |
|---|---|---|---|
| 1 | Fork = i2c0, SDA GP8, SCL GP9 | `hardware_config.h:68` | ✓ — B2 korrekt |
| 2 | Shock = i2c1, SDA GP14, SCL GP15 | `hardware_config.h:78` | ✓ — B3 korrekt |
| 3 | SD-SPI: spi0, 6,75 MHz, GP16–19 | `hardware_config.h:47` | ✓ — Störer aus A4 real |
| 4 | SDIO-Build hätte D2 auf GP21 | `hardware_config.h:56` (D0=19, D2=D0+2) | ✓ — aktiver Preset ist SPI (`CMakePresets.json:39`), GP21 frei |
| 5 | Buzzer GP22 | `buzzer.h:6` | ✓ |
| 6 | Buzzer nach Startton statisch | `buzzer.c:11` (silence-Alarm setzt Level 0) | ✓ mit Hinweis, s. Abschnitt 5 |
| 7 | I²C-Takt 1 MHz | `linear_ads1115.c:94` | ✓ |
| 8 | Pico-interne Pull-ups aktiv | `linear_ads1115.c:97` | ✓ |
| 9 | Beide Module Adresse 0x48, getrennte Busse | `linear_ads1115.c:36`, `:40` | ✓ — ADDR-Pull-down plausibel |
| 10 | Wiper auf A0, A1 frei | `linear_ads1115.c:106` (`MUX_SINGLE_0`) | ✓ — Phase E kollisionsfrei |
| 11 | PGA 4,096, Continuous, 860 SPS | `linear_ads1115.c:107` | ✓ |
| 12 | Lib-Setter für Comparator fehlen | `external/pico-ads1115/include/ads1115.h:112` | ✓ — auskommentiert |
| 13 | Alte FW lässt COMP_QUE = disable → ALERT hochohmig | Lib-Default 0x8583, FW schreibt COMP-Bits nie (`registers.h:96`, `linear_ads1115.c:106`) | ✓ — D1-Messung (3,3 V Ruhepegel) gültig |
| 14 | `MUX_SINGLE_1` in Lib vorhanden | `registers.h:31` | ✓ |
| 15 | Globaler GPIO-Callback von pushbutton belegt | `pushbutton.c:59` | ✓ — Raw-Handler-Ansatz nötig |
| 16 | Poll-Takt −1000000/860 = 1162 µs = 860,585 Hz | `main.c:137`, `main.c:435` | ✓ |
| 17 | Header: 2 Byte Padding vor 64-bit-Zeit, 16 Byte | `sst.h:29`, `gosst/formats/sst/sst.go:14`, Bridge `RawTelemetryData.cs` (HeaderSize 16, Bytes 6–8 Padding, nur Magic-Gate) | ✓ |
| 18 | SD-Burst 8 KB alle ~2,4 s | `sst.h:47` (2048 × 4 B), 2048/860,585 Hz = 2,38 s | ✓ |
| 19 | WLAN bestromt, nicht assoziiert, Power-Save | `main.c:823`, Kommentar `main.c:608` | ✓ |
| 20 | Belegte GPIOs 2–5, 8, 9, 14–19, 22, 23–25, 29; frei 6, 7, 10–13, 20, 21, 26–28 | alle `gpio_init`/`gpio_set_function`-Stellen + `PICO_BOARD pico_w` (`CMakeLists.txt:17`) | ✓ — Debug-Builds nutzen zusätzlich GP0/1 (UART), berührt GP21/27 nicht |

## 2. RP2040 / Pico-Header (gegen Doku und Rechnung geprüft)

| # | Annahme | Prüfung | Befund |
|---|---|---|---|
| 21 | GP21 = Slice 2B, GP27 = 5B, GP26 = 5A, GP22 = 3A, GP13 = 6B | Slice = (GP>>1)&7, B = ungerade | ✓ alle fünf |
| 22 | Nur B-Kanal zählt Flanken (`PWM_DIV_B_FALLING`) | RP2040-Datenblatt / SDK-Enum | ✓ |
| 23 | GPIO-IRQ greift Pad ab, unabhängig vom Funcsel | RP2040-Datenblatt | ✓ — AP0 verifiziert zusätzlich empirisch |
| 24 | Header-Pins: GP21=27, GP27=32, GP8=11, GP9=12, GP14=19, GP15=20, GND=28, AGND=33, GP19=25, GP20=26, GP22=29, GP26=31, GP28=34, 3V3=36 | offizielles Pinout | ✓ alle 14 Angaben |
| 25 | RP2040 nicht 5-V-tolerant; Schmitt-Eingänge default an; interner Pull-up ~56 kΩ | Datenblatt | ✓ |
| 26 | `timerawl` wrappt nach 71,6 min | 2³² µs | ✓ |

## 3. Elektrik (nachgerechnet)

| # | Annahme | Rechnung | Befund |
|---|---|---|---|
| 27 | 10 k ∥ 56 k = 8,5 kΩ; t_r 216 ns @30 pF, 360 ns @50 pF | t_r = 0,847·RC | ✓ — Fm+ (120 ns) verletzt, Fm (300 ns) grenzwertig, wie im Plan |
| 28 | 2,2 k ∥ 10 k = 1,80 kΩ; 46/76 ns | dito | ✓ — beide Spec-Fenster eingehalten |
| 29 | Senkstrom 1,83 mA < 3 mA (ADS1115 VOL-Spec) | 3,3 V / 1,803 kΩ | ✓ — mit internem Pull-up 1,89 mA, weiter ok |
| 30 | Messwerte B1 ≈ 10 kΩ, B5 ≈ 1,8 kΩ (Gerät aus) | s. o. | ✓ |
| 31 | 26400 Counts = exakt 3,3/4,096·32768 | 32768/4096·3300 = 8·3300 | ✓ — identisch `MAX_ADC_3P3V` (`linear_ads1115.c:15`); 2^14,6883 ≈ 26400 konsistent |
| 32 | `baseline_norm` passt in uint16 | Wiper ≤ Speisung ⇒ ≤ 26400 | ✓ |
| 33 | DRDY-Puls ~8 µs aktiv-low; Hi=0x8000/Lo=0x0000 + COMP_QUE≠11 aktiviert ihn; ALERT bei QUE_DISABLE hochohmig; Abs-Max Analog = VDD+0,3 V | ADS1115-Datenblatt | ✓ — physischer Nachweis bleibt AP0 Test 2 |
| 34 | Fork ~832 / Shock ~850–859 SPS plausibel | Datenraten-Toleranz ±10 %; konsistent mit 28-Hz-Schwebung (860,585 − 832,6 ≈ 28) | ✓ als Hypothese — Messung in AP0 |
| 35 | 10-s-Zählfenster ohne Überlauf | 16-bit-PWM-Zähler, max ~8590 Counts | ✓ — Grenze: Fenster > ~75 s liefe über |

## 4. Abweichungen — Plan veraltet (nur Software, Hardware unberührt)

1. **gosst:** `CurrentProcessingVersion` ist **9** (`psst.go:106`), nicht 7.
   AP7-Bump muss 9 → 10 heißen.
2. **Bridge:** `CurrentProcessingVersion` ist **30** (`TelemetryData.cs:180`),
   nicht 28. AP7b-Bump muss 30 → 31 heißen. `SampleRate` jetzt Zeile 187.
3. **gosst-Signaturen bereits geändert** (Dead-Band-Umbau):
   `forkVelocityZeroThreshold` jetzt `psst.go:127`,
   `shockVelocityZeroThreshold` `:131`, `calculateDerivative` `:226`,
   alle mit Zusatzparameter `travelPerLsb`. AP7-Fundstellenliste vor
   Umsetzung neu erheben.
4. Kleinere Zeilendrifts ohne Wirkung: `main.c:821`→`:823`;
   Bridge `RawTelemetryData.cs` neu geschrieben, Semantik unverändert.

## 5. Hinweis (neu, unkritisch)

`on_rec_start` (`main.c:423`) startet den Buzzer-Chirp vor dem Timer; der
letzte Ton endet per Alarm bis ~150 ms **nach** Timerstart. GP22 toggelt
also mit 4,5 kHz in die ersten DRDY-IRQs hinein. Bewertung: Pin 28 (GND)
liegt zwischen GP22 und GP21, Frequenz niedrig, Intervall-Gate deckt den
Rest — keine Maßnahme nötig. Falls `glitch_count` in AP8 nur am
Aufnahmestart zählt, ist das die erste Verdachtsquelle.

## 6. Nur am Gerät prüfbar (bleibt offen, im Plan so vorgesehen)

- DRDY pulst überhaupt / Polarität / Breite → AP0 Test 2 (Showstopper-Gate).
- Reale SPS je Kanal (Schwellen für das Intervall-Gate) → AP0 Test 2.
- VDD = 3,3 V an beiden Modulen → Phase 0.3.
- Pinreihenfolge am Modul beim Löten gegen Silkscreen prüfen (bisher nur
  per Foto belegt).
- Buskapazität ~30 pF ist Schätzwert; Rechnung hält bis 50 pF
  (400 kHz + 1,8 kΩ), Marge ausreichend.

## Freigabe

Phasen 0, A, B, C, D, E der Checkliste: **umsetzbar wie beschrieben.**
Reihenfolge einhalten: Phase 0 (Referenzaufnahme!) vor jedem Eingriff,
AP0 Test 2 vor der Firmware-Kette.
