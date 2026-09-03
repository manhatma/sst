# Plan: DRDY-Zeitstempel + Resampling auf Quarzraster (860 Hz bleibt)

> **AP0 Test 2 bestanden am 2026-08-13.** Gemessen mit `drdy_probe` am Gerät:
> `F=8324 S=8677 | PW 8/8 us | T 1201/1152 us | XCHK OK`.
> DRDY pulst auf beiden Kanälen, 8 µs breit, **aktiv low**. GPIO-IRQ und
> PWM-Flankenzählung am selben Pin stören sich nicht (`XCHK OK`).
>
> | | Fork | Shock |
> |---|---|---|
> | ADC-Rate | **832,4 SPS** | **868,1 SPS** |
> | ADC-Periode | **1201 µs** | **1152 µs** |
> | Intervall-Gate (0,8 × T) | **961 µs** | **922 µs** |
>
> Der Shock-ADC läuft **schneller** als der Poll-Takt vor AP5 (860,585 Hz). Er verwirft
> heute ~7,4 Wandlungen pro Sekunde, statt zu duplizieren. Der Fork dupliziert
> ~28/s. Die Zahlen ersetzen alle Schätzwerte weiter unten.

*Stand 2026-08-13: Raster auf exakt 860,000 Hz festgelegt. AP6, AP7 und AP7b
entfallen dadurch; `sample_rate = 860` beschreibt die Zeitachse exakt.*

*Stand 2026-08-14: AP8 abgeschlossen -- Punkte 1-5 und 7 bestanden, Punkt 6
statisch verifiziert (Bridge prueft nur das Magic). Offen bleiben nur die
opportunistische Rausch-Wiederholung bei teilentladenem Akku (AP8.4, kein
Blocker) und die Nebenbefunde.*

*Stand 2026-08-13: AP0 bis AP3 auf Hardware verifiziert; 400-kHz-Empfehlung aus
AP1 verworfen, Bus bleibt bei 1 MHz; Jitter gemessen statt angenommen.*

*Historischer Stand 2026-08-13: Code-Referenzen gegen den damaligen Plan geprüft
([protokoll-hw-verifikation-drdy.md](protokoll-hw-verifikation-drdy.md), Abschnitt 4):
gosst-`CurrentProcessingVersion` ist inzwischen 9 (Bump → 10), Sufni.Bridge ist 30
(Bump → 31). Zeilennummern in AP3/AP7/AP7b nach dem Dead-Band-Umbau (gosst) und
dem Bridge-Refactoring neu erhoben. Hardware-Annahmen unverändert bestätigt.*

*Stand 2026-07-28: Aufnahmelänge ≤ ~10 min bestätigt → uint32-Wrap entschärft
(AP3, AP8, Risiken). AP7 um das Sufni.Bridge-Paket erweitert — die Bridge darf
mitgeändert werden, bleibt aber aus anderem Grund beim additiven Feld.*
*Stand 2026-07-27: Review eingearbeitet — t_0-Vorzeichen korrigiert (AP5),
Mixed-Preset-Abstraktion (AP5), Ring 16 statt 8, Glitch-Gate pro Kanal.*

## Ziel

Die ADC-Uhr wird beobachtet statt angenommen. ADS1115 läuft weiter frei in
`MODE_CONTINUOUS` / `RATE_860_SPS`; jede Wandlung bekommt beim DRDY-Impuls einen
Quarz-Zeitstempel. Ausgabe auf exaktem 860-Hz-Raster, Catmull-Rom-interpoliert.

**Erreicht:** keine Duplikate, ehrliche Zeitachse, Fork/Shock-Skew höchstens 37 µs
und vor allem konstant statt mit 28,2 Hz wandernd (heute ±1,2 ms),
konstantes Sample-Alter (~3,6 ms, s. AP5), Ausfälle werden gezählt statt verschluckt.

**Nicht erreicht (bewusst):** effektive Bandbreite bleibt ~416 Hz (setzt der ADC),
und vor dem ADC sitzt weiterhin kein Antialiasing-Filter. Beides bleibt offen.

## Ausgangslage

| | Wert |
|---|---|
| Poll-Takt vor AP5 | 860,585 Hz (`-1000000/860` = 1162 µs, Integer-Division) |
| Raster ab AP5 | exakt 860,000 Hz (Restakkumulator 1162/1163 µs) |
| Header deklariert | 860 Hz |
| Wandlung Fork real | 832,4 SPS (gemessen AP0) |
| Wandlung Shock real | 868,1 SPS (gemessen AP0) |
| Schwebung Fork | 28,2 Hz → 28 Duplikate/s |
| Schwebung Shock | 7,4 Hz → 7,4 verworfene Wandlungen/s |
| Geschwindigkeitsfehler in gosst | ~3,4 % |
| Fork/Shock-Zeitversatz | wandert um bis zu ±1,2 ms mit der Schwebung |
| Reale Aufnahmelänge | Größenordnung Minuten, max ~10 min |

## Arbeitspakete

Firmware-Kette AP0→AP5 ist seriell. AP6, AP7 und AP7b entfallen mit dem exakten
860-Hz-Raster; danach folgt direkt AP8.

---

### AP0 — Vorabverifikation am Baustein

**Vor jeder Firmware-Arbeit.** Modul ist ein AZ-Delivery ADS1115
(„16BIT I2C ADC+PGA", blaues CJMCU-Layout).

**Am Foto bereits geklärt:**

- **ALRT ist auf den Header geführt** — Pinreihe von rechts:
  `VDD, GND, SCL, SDA, ADDR, ALRT, A0, A1, A2, A3`. Kein Antasten am Chip nötig.
- 4× „103" (10 kΩ) bestückt. Kanonische Belegung dieses Boards: SDA-Pull-up,
  SCL-Pull-up, ALERT-Pull-up, ADDR-Pull-down. Der ADDR-Pull-down passt zu
  `i2c_addr = 0x48` in `linear_ads1115.c:36` → stützt die Zuordnung.
- Der Pull-up-Wert ist für ALRT unkritisch: getriggert wird auf die **fallende**
  Kante, die treibt der Open-Drain-Ausgang hart. Nur die RC-langsame Freigabeflanke
  hängt am Widerstand, und die zählt nicht.

**Gemessen:**

1. ~~ALRT gegen VDD~~ → **10 kΩ, Pull-up bestückt ✓**. Belegt damit auch die
   Zuordnung der vier „103": SDA-PU, SCL-PU, ALRT-PU, ADDR-PD. Kein Nachlöten.
3. ~~Modulposition~~ → **beide Module sitzen im DAQ-Gehäuse ✓**. I²C und ALRT sind
   kurz und board-to-board, nur das analoge Sensorsignal geht durchs Kabel.
   Buskapazität ~30 pF.

**Erledigt:**

2. ~~Der Showstopper-Test.~~ → **bestanden ✓**: 8324 Counts Fork, 8677 Counts Shock, DRDY-Puls auf beiden Kanälen 8 µs breit und aktiv low, Kreuzcheck PWM- gegen ISR-Zähler ohne Differenz (`XCHK OK`).

   Die gemessene **kanalindividuelle** ADC-Rate liefert das Intervall-Gate in AP3:
   961 µs für Fork, 922 µs für Shock.

**Abbruchkriterium:** keine Pulse → Plan hinfällig, zurück auf Variante B
(Single-Shot-Retrigger, ~780 Hz).

*Umgebungsabhängig — läuft am Gerät, nicht delegierbar.*

---

### AP1 — Hardware

**DRDY:**

- ALRT Fork → **GP21**, ALRT Shock → **GP27**
- Pull-ups sind auf dem Modul bestückt (AP0), nichts nachzurüsten
- `firmware/src/fw/hardware_config.h`: `FORK_PIN_DRDY` / `SHOCK_PIN_DRDY` neben die
  bestehenden `*_PIN_SDA/SCL`-Blöcke
- **DRDY-Drähte im Gehäuse von der SD-Verdrahtung (GP16–19, 6,75 MHz) wegführen** —
  billigste Maßnahme gegen die Einkopplung aus AP3

**Warum genau diese Pins.** Die RP2040-PWM-Slices können Flanken in Hardware zählen
(`PWM_DIV_B_FALLING`) — aber nur auf dem **B-Kanal**, also nur auf **ungeraden**
GPIOs, und beide müssen auf **verschiedenen Slices** liegen. GP21 = Slice 2B,
GP27 = Slice 5B. Kein Konflikt mit der Buzzer-PWM (GP22 = Slice 3).

Das ist die Voraussetzung für AP0 Test 2 ohne Oszilloskop und liefert darüber hinaus
im finalen Build einen kostenlosen Gegencheck zu `drdy_count` aus dem ISR: divergieren
Hardware-Zähler und ISR-Zähler, verliert die ISR Kanten.

(GP26 wäre Slice 5 **Kanal A** — kann nicht zählen und läge auf demselben Slice wie
GP27. Vorbehalt zu GP21: in einem SDIO-Build wäre das D2; der aktive Preset ist
SPI-MicroSD, also frei. Alternative GP13 = Slice 6B, kollidiert dafür mit dem
SPI-Display-Build.)

Freie GPIOs im aktiven Preset `spi_card-i2c_disp-linear_fork-linear_shock`:
6, 7, 10–13, 20, 21, 26–28. Belegt: 2–5, 8, 9, 14–19, 22, 23–25, 29.

**I²C-Pull-ups — Nebenbefund aus AP0, unabhängig von DRDY:**

`linear_ads1115.c:94` fährt den Bus mit 1 MHz (Fast-mode Plus, t_r max 120 ns). Die
Modul-Pull-ups sind 10 kΩ, parallel zum Pico-internen ~56 kΩ also ~8,5 kΩ:

Module sitzen im Gehäuse (AP0 Test 3), Buskapazität ~30 pF. Pull-ups sind
10 kΩ (Modul) ∥ ~56 kΩ (Pico intern) = 8,5 kΩ:

| Rp | 30 pF | 50 pF | 1 MHz (120 ns) | 400 kHz (300 ns) |
|---|---|---|---|---|
| 8,5 kΩ (Bestand) | 216 ns | 360 ns | ✗ | grenzwertig |
| **+ 2,2 kΩ parallel → 1,8 kΩ** | 46 ns | 76 ns | ✓ | ✓ |

Die 2,2-kΩ-Widerstände sind eingelötet. Parallel zu den 10 kΩ der Module ergeben
sie gemessene 1,8 kΩ je Leitung. Damit liegt die Anstiegszeit bei 1 MHz innerhalb
der Fast-mode-Plus-Spec.

→ **2,2 kΩ von SDA und SCL nach 3V3, je Bus, auf der Pico-Seite, sind eingelötet.**
Nichts wurde ausgelötet. Senkstrom 1,8 mA, klar innerhalb der 3 mA des ADS1115.

→ **Der Plan empfahl hier 400 kHz. Die Messung in AP3 widerlegt das.** Der Bus
bleibt bei 1 MHz. 400 kHz verlängert den Read und damit die ISR-Kollision. Die
maximale Zeitstempelabweichung steigt von 37 µs auf 81 µs. Der Anteil über 35 µs
steigt von 0,19 % auf 7,7 %. Mit 1,8-kΩ-Pull-ups bleiben `i2c_err_count` und
`glitch_count` bei 1 MHz null.

Die Pico-internen Pull-ups sind in `linear_ads1115.c:101`–`102` per `gpio_disable_pulls` abgeschaltet.

Aufwand: 2 Drähte, 4 bedrahtete Widerstände.

**Erledigt:** DRDY-Leitungen und 2,2-kΩ-Pull-ups sind eingebaut. Effektiver
Pull-up-Widerstand: gemessene 1,8 kΩ je Leitung. Der Bus bleibt bei 1 MHz.

---

### AP2 — ADS1115-Treiber: DRDY scharfschalten, Read verschlanken

Datei: `firmware/src/sensor/linear_ads1115.c`

- In `linear_sensor_ads1115_init` nach `ads1115_write_config`:
  - `Hi_thresh = 0x8000` (Pointer 0x03), `Lo_thresh = 0x0000` (Pointer 0x02)
  - `COMP_QUE` von `QUE_DISABLE` (0b11, Lib-Default) auf `QUE_1` (0b00)
  - `COMP_POL` low, nicht latchend — beides Default, nur nicht überschreiben
- `pico-ads1115` kann weder Thresholds noch Comparator (Setter sind in
  `include/ads1115.h:112` auskommentiert) → zwei kleine Helper analog
  `ads1115_read_adc_debug`, das Config-Wort direkt maskieren
- **Pointer-Write eliminieren:** `ads1115_read_adc_debug` schreibt den Pointer bei
  jedem Read neu. Der Pointer bleibt aber auf 0x00 stehen, wenn ihn niemand ändert
  → einmalig in `init` setzen, danach reiner 2-Byte-Read. Spart 20 µs pro ISR.
  Invariante dokumentieren: kein anderer Pfad darf den Pointer bewegen —
  `check_availability` (1-Byte-Read ohne Pointer-Write, `linear_ads1115.c:119`)
  und `calibrate_expanded` (läuft vor RECORD) sind sicher.

---

### AP3 — Ringpuffer + Zeitstempel-ISR

Neue Datei: `firmware/src/sensor/drdy_ring.c` / `.h`

```c
struct sample { uint32_t t_us; uint16_t v; };
```
Ring pro Kanal, **16 Einträge** (128 B/Kanal), Power-of-two-Maske, Single-Producer
(ISR) / Single-Consumer (Timer-CB), `head` volatile. 8 würden rechnerisch reichen
(9,6 ms Fenster gegen ~6 ms Bedarf inkl. Konsument-Verspätung), 16 kosten 64 B mehr
und nehmen das Thema komplett vom Tisch.

**Zeitarithmetik (Wrap-Regel, gilt für AP3–AP5).** `timerawl` wrappt nach 71,6 min
— und zwar ab **Boot**, nicht ab Aufnahmestart, der Wrap kann also durchaus in eine
Aufnahme fallen. Entschärft ist er trotzdem: reale Aufnahmen sind Minuten lang
(max ~10 min = 6·10⁸ µs), verglichen werden ohnehin nur Zeitpunkte innerhalb des
Rings (~ms). Jede auftretende Differenz liegt damit um Größenordnungen unter
2³¹ µs (35,8 min) → **modulare uint32-Arithmetik ist hier per Konstruktion exakt**,
kein Sonderfall, kein Langzeittest nötig.

Kostet eine Klammer, also mitnehmen: Vergleiche ausschließlich über
`(int32_t)(a - b)`; `t_k` wird in AP5 mit 1162/1163-µs-Schritten und bewusst als
wrappende uint32-Rechnung fortgeschrieben.
**Nirgends `absolute_time_t` oder 64-bit-Zeit einmischen** — genau das (und nacktes
`a < b`) wäre der einzige Weg, den Wrap doch noch sichtbar zu machen.

ISR-Reihenfolge ist die tragende Annahme des ganzen Entwurfs:

```c
uint32_t t = timer_hw->timerawl;   // ZUERST — nur das ist zeitkritisch
uint16_t v = i2c_read_2bytes();    // ~30 µs, darf spät sein
ring[head & MASK] = (struct sample){t, v};
__dmb();
head++;
```

Der Read darf verzögert werden, weil das Conversion-Register den Wert bis zur
nächsten fertigen Wandlung hält → ~1,2 ms Budget für 30 µs Arbeit.

Zähler: `drdy_count`, `late_count` (neuer DRDY bevor der vorige Read fertig war),
`i2c_err_count`, `glitch_count` (s.u.).

**Intervall-Gate gegen Störeinkopplung.** Der ALERT-Pull-up ist 10 kΩ (AP0), die
Leitung also hochimpedant. Eine eingekoppelte falsche fallende Kante erzeugt ein
Phantom-Sample, das eine echte Stützstelle *verdrängt* und die Interpolation
verfälscht.

Der einzige relevante Störer ist **SD-SPI** (6,75 MHz, GP16–19): burstartig 8 KB alle
~2,4 s, also garantiert gleichzeitig mit DRDY-Kanten. WLAN ist während RECORD zwar
bestromt, aber nicht assoziiert und im Power-Save (`main.c:823`, `main.c:608`) — kein
RF. Die Buzzer-PWM stoppt nach dem Starton (`buzzer.c:54`), GP22 liegt statisch.
Beide vernachlässigbar.

Abwehr: DRDY verwerfen, wenn er weniger als 0,8× der in AP0 gemessenen ADC-Periode
**des jeweiligen Kanals** nach dem vorherigen kommt: Fork 832,4 SPS, Periode
1201 µs, Gate 961 µs; Shock 868,1 SPS, Periode 1152 µs, Gate 922 µs. Eine globale
Schwelle wäre für den schnelleren Kanal zu locker. Ein kürzeres Intervall ist
physikalisch unmöglich. Ein Vergleich, `glitch_count` hoch, fertig. Kein
Software-Entprellen, das würde den Zeitstempel verschmieren. Die
Schmitt-Trigger-Eingänge des RP2040 sind ohnehin aktiv.

Der Zähler ist primär **Diagnose**: bleibt `glitch_count` über eine lange Aufnahme
auf 0, ist die Verdrahtung sauber. Die billigste Maßnahme ist ohnehin Layout, nicht
Software — siehe AP1.

**IRQ-Registrierung:** `pushbutton.c:59` belegt via
`gpio_set_irq_enabled_with_callback` den *einen globalen* GPIO-Callback.
→ `gpio_add_raw_irq_handler_with_order_priority` für die beiden DRDY-Pins, hält
`pushbutton.c` unangetastet.

**Beide ISRs auf Core0.** Core1 macht blockierende SD-Writes, die die 1,2-ms-Grenze
reißen können.

> **AP3 auf Hardware verifiziert am 2026-08-13.** `drdy_count` traf exakt die
> AP0-Erwartung: 8324 Fork und 8677 Shock in 10 s. `late_count`, `i2c_err_count`
> und `glitch_count` blieben in allen Läufen null. Ein Ringdump zeigte echte
> Wandlungswerte und bestätigte damit die Pointer-Invariante.
>
> | Größe | 400 kHz | 1 MHz |
> |---|---:|---:|
> | max. Abweichung | 81 µs | 37 µs |
> | Anteil Samples > 5 µs daneben | 10,6 % | 5,3 % |
> | Anteil Samples > 35 µs daneben | 7,7 % | 0,19 % |
> | Anteil Samples > 75 µs daneben | 0,41 % | 0 |
> | `i2c_err_count` / `glitch_count` / `late_count` | 0 | 0 |
>
> Beide blockierenden DRDY-ISRs laufen auf Core0. Kollidieren zwei DRDY-Impulse,
> wartet der zweite Read auf den ersten. 1 MHz verkürzt dieses Warten. Kontrollen
> mit jeweils nur einem aktiven Kanal ergaben 9 µs und 1 µs maximale Abweichung.
> Sie bestätigen die Kollision als alleinige Ursache. Der Restjitter von 37 µs
> ist inhärent und wird in AP4 als Stützstellenabstand-Ungleichheit sichtbar.

---

### AP4 — Catmull-Rom-Resampler

Gleiche Datei. `resample(channel, t_k) → uint16`

- Intervall `[t_i, t_{i+1}] ∋ t_k` im Ring suchen (Vergleiche wrap-sicher, s. AP3);
  CR braucht zusätzlich `i-1` und `i+2` → 4 Stützstellen, Auswerte-Latenz
  3 ADC-Perioden des langsameren Kanals = 3 × 1201 µs = 3603 µs ≈ 3,6 ms
  (Offset aus AP5)
- `u = (t_k − t_i) / (t_{i+1} − t_i)` in Q16
- `v = ½·( 2P₁ + (−P₀+P₂)u + (2P₀−5P₁+4P₂−P₃)u² + (−P₀+3P₁−3P₂+P₃)u³ )`
- int32/int64-Arithmetik, kein Float nötig (RP2040 hat keine FPU).
  ~20 Ops pro Kanal pro Tick → 34 k Ops/s von 125 MHz, nicht messbar
- Gemessener Jitter höchstens 37 µs gegen 1152 µs Intervall, also 3,2 %; 95 % der
  Intervalle liegen innerhalb 5 µs. Das echte `u` enthält den Jitter bereits;
  ignoriert wird nur die Ungleichheit der Abstände zwischen vier Stützstellen.

**Randfälle:**

| Fall | Verhalten |
|---|---|
| < 4 Stützstellen im Ring | letzten Wert halten, Zähler hoch |
| `t_k` vor dem Ring | sollte nach korrektem `t_0` nicht vorkommen, Zähler hoch |
| `t_k` hinter dem Ring (ADC steht) | letzten Wert halten, Zähler hoch |
| Loch im Ring (Glitch-Gate / I²C-Fehler) | Intervall wird ~2 Perioden breit, uniform-CR verzerrt lokal — hinnehmen, `glitch_count`/`i2c_err_count` zeigen es; bei erwartetem 0 kein Thema |
| Kanal nicht verfügbar | `0xFFFF` wie heute |

**Wichtig:** Baseline-Subtraktion und Clamp auf 0 stehen heute in
`linear_sensor_ads1115_measure` (`linear_ads1115.c:162`). Beides muss **nach** der
Interpolation laufen — clampt man die Stützstellen, verzerrt man die Kurve.
Im Ring stehen Rohwerte.

> **AP4 auf dem Host geprüft am 2026-08-13.** Die Datei `drdy_ring.c` wurde mit
> Pico-SDK-Stubs auf dem Rechner übersetzt und gegen eine Float-Referenz geprüft.
>
> Die Q16-Festkommarechnung liefert bei u=0 exakt P1 und bei u=1 exakt P2. Eine
> Gerade als Stützstellenfolge wird exakt reproduziert. Eine Konstante bleibt exakt
> konstant.
>
> Der Host-Test maß nur den über alle `u` gemittelten Versatz. Das war der Fehler.
> Entscheidend ist die Abhängigkeit von `u`: Der abschneidende Versatz läuft von 0
> bei u=0 auf -0,88 LSB bei u=0,9 und springt bei u=1 zurück auf 0. `u` durchläuft
> diesen Bereich mit der Schwebungsfrequenz. Der Versatz wird damit zu einem
> Sägezahn von 0,9 LSB, im Ruhesignal von rund 1 LSB.
>
> Eine Aufnahme mit der abschneidenden Variante zeigte die Linie im Signal mit
> +18,4 dB (Fork, 27,32 Hz) und +16,6 dB (Shock, 7,97 Hz). Die alte Firmware hatte
> im Signal keine solche Linie. Die Simulation der ganzen Kette reproduziert den
> Befund und sagt für die gerundete Variante den Rauschboden voraus. Deshalb wird
> gerundet. Der `u`-abhängige Versatz sinkt auf praktisch null, die maximale
> Abweichung von der Float-Referenz von 2,00 auf 0,97 LSB.
>
> Bei Extremstützstellen mit einem Wechsel zwischen -32768 und 32767 läuft das
> Ergebnis auf -40960 bis 40958. Catmull-Rom überschwingt an Stufen um bis zu
> 25 Prozent. Der Clamp auf den int16-Bereich ist damit notwendig, nicht
> vorsorglich.
>
> Bei 16 Ringeinträgen sind die Intervalle 1 bis 13 nutzbar. Das sind 13 Intervalle
> oder rund 15,6 ms Vorgeschichte. Der Auswerte-Offset von 3,6 ms aus AP5 liegt
> komfortabel darin.
>
> `t_k` vor dem Fenster, `t_k` hinter dem Fenster und weniger als vier Stützstellen
> lösen jeweils den richtigen Zähler aus und halten den letzten Wert. Ein
> uint32-Überlauf der Zeitstempel mitten im Ring ändert nichts am Ergebnis. Die
> Wrap-Regel aus AP3 trägt.
>
> Das Torn-Prädikat wurde einzeln gegen zwölf Fälle geprüft. Dabei überholt die ISR
> den Consumer während des Kopierens. Die Fälle enthalten einen Überlauf von
> `head` selbst. Das Prädikat trifft in allen Fällen zu. Im Einzelthread lässt sich
> der Fall nicht fahren. Deshalb erfolgte die getrennte Prüfung.
>
> Ein Loch im Ring verzerrt lokal, stürzt aber nicht ab. Das ist so vorgesehen.
>
> Das Testprogramm liegt außerhalb des Repos. Es gibt im Firmware-Teil noch keine
> Testinfrastruktur.

---

### AP5 — Grid-Timer und Startsequenz

Datei: `firmware/src/fw/main.c`

- **Mixed-Presets:** `data_acquisition_cb` (`main.c:157`) ist preset-übergreifend —
  `linear_fork-as5600_shock` und `as5600_fork-linear_shock` existieren in
  `CMakePresets.json`. Deshalb kein `resample()`-Call und kein `#ifdef` direkt im
  Callback, sondern optionale Ops in `sensor.h`: `sample_at`, `ready` und `stop`.
  Statische Inline-Helfer verwenden bei `NULL` weiterhin `measure()`, `true` bzw.
  keine Aktion. So bleiben AS5600 und EvoMini unangetastet. ADS1115 implementiert
  Ring-Resampling + Baseline/Clamp (Reihenfolge aus AP4), Ring-Füllstand und
  IRQ-Abschaltung.
- Das Raster läuft **exakt mit 860,000 Hz**. Weil
  `1000000 = 860 · 1162 + 680`, ist jeder Schritt zunächst 1162 µs lang; ein
  Restakkumulator addiert 680 und macht den Schritt bei Überlauf über 860 zu
  1163 µs. Das Muster wiederholt sich nach 43 Ticks über exakt 50000 µs und
  sammelt unabhängig von der Aufnahmedauer keinen Fehler an. `t_k` bleibt eine
  wrappende uint32-Rechnung gemäß AP3.
- Ein selbst neu gestellter Alarm ersetzt den Wiederhol-Timer. Der Callback gibt
  den nächsten Schritt **negativ** zurück. Damit plant das SDK relativ zum
  vorgesehenen Auslösezeitpunkt; ein positiver Wert wäre relativ zur Jetztzeit
  und würde Verspätung und Interrupt-Jitter in der Zeitachse aufsummieren.
  `get_absolute_time()` kommt im Callback nicht vor.
- `on_rec_start` (`main.c:407`): DRDY-IRQs aktivieren → warten, bis alle
  **verfügbaren** Kanäle ≥ 4 Samples im Ring haben (Timeout ~100 ms; „beide" wäre
  bei nur einem bestückten Sensor ein Dauer-Timeout — `start_sensors` lässt einen
  genügen, `main.c:201`) → **`t_0` = jetzt **−** 3 ADC-Perioden des langsameren
  Kanals = jetzt − 3 × 1201 µs = jetzt − 3603 µs** → Timer starten.

  **Das Vorzeichen ist tragend.** Auswertung von `t_k` setzt voraus, dass `i+2`
  schon gewandelt ist: `t_k ≤ W − 2·T_adc` (W = Wanduhrzeit im Callback). Läge
  `t_0` in der Zukunft (+2), stünde jedes `t_k` dauerhaft ~1,2 ms vor dem neuesten
  Sample — jeder Tick fiele still in den Hold-Fallback, sähe aus wie heute (inkl.
  Duplikaten), nur mit explodierendem Zähler. −3 statt −2: eine Periode
  Jitter-Reserve. Sample-Alter damit konstant ~3,6 ms, abgeleitet aus der
  Fork-Periode als langsamerem Kanal.
- `absolute_time_t` wird beim Start nur verwendet, um den ersten Alarm zu
  terminieren. Direkt daneben wird `grid_t_k_us = timerawl - 3603` gelesen; die
  Rasterrechnung selbst mischt keine 64-bit-Zeit ein.
- `on_rec_stop` (`main.c:441`): Alarm abbrechen, DRDY-IRQs ausschalten und alle
  Ringzähler beider ADS1115-Kanäle debug-ausgeben. Nichtnull-Fehlerzähler werden
  mit Kanal, Kürzel und Wert kurz auf dem Display sichtbar gemacht.
- Der Dateiversionswert steigt von 3 auf 4. Headerformat und -größe bleiben
  unverändert; der Bump kennzeichnet lediglich Dateien aus dem DRDY-Verfahren.

---

### AP6 — Entfallen (ehemals Dateiformat v4)

**Entfallen.** Dieses Arbeitspaket existierte nur, um die 0,585-Hz-Abweichung des
1162-µs-Takts nach unten durchzureichen. Das exakte Raster stimmt mit
`sample_rate = 860` überein; gosst, Bridge und Dashboard brauchen kein neues
Periodenfeld. Der Versionsbump 3 → 4 bleibt als Kennzeichen ohne Formatänderung.

Der folgende Text dokumentiert den früheren, nicht mehr umzusetzenden Ansatz.

Die Rasterperiode 1162 µs = 860,585 Hz ist kein ganzzahliges Hz. Der Header hat aber
2 Byte implizites Padding (Alignment vor `time_t`) — sichtbar in
`gosst/formats/sst/sst.go:14`. Da rein die Periode.

**Firmware** `src/fw/sst.h`:
```c
struct header {
    char     magic[3];
    uint8_t  version;          // 3 -> 4
    uint16_t sample_rate;      // bleibt 860, für alte Leser
    uint16_t sample_period_us; // NEU, war Padding: 1162
    time_t   timestamp;
};
```
Plus Initialisierung in `main.c:267`. Keine Größenänderung, voll rückwärtskompatibel.

**gosst** `formats/sst/sst.go`: `Padding` → `SamplePeriodUs`; bei `Version >= 4`
Rate = `1e6 / SamplePeriodUs`, sonst wie bisher aus `SampleRate`.

Nebeneffekt: der Integer-Divisions-Fehler ist damit strukturell unmöglich.

**Zweiter Konsument des Headers: Sufni.Bridge.** Die Bridge parst die rohe .SST-Datei
selbst, nicht nur den Blob — `Sufni.Bridge/Models/Telemetry/RawTelemetryData.cs:27`.
Im Code geprüft, AP6 ist für sie unkritisch:

- **Kein Version-Gate** — validiert wird nur das Magic (Zeile 40), `Version` wird bloß
  durchgereicht. Der Bump 3→4 bricht nichts.
- Bytes 6–8 werden explizit als Padding übersprungen (Zeile 37), `HeaderSize = 16`
  (Zeile 22) bleibt. Das neue Feld ist für die Bridge unsichtbar.

Ohne Bridge-Anpassung liest sie weiter `sample_rate` = 860 statt der 1162 µs, bleibt
also bei **0,068 %** Fehler (heute 3,4 %) — tolerierbar. Da die Bridge geändert werden
darf, ist das Feld dort trotzdem vorgesehen: → **AP7b**.

---

### AP7 — Entfallen (ehemals gosst auf Fließkomma-Rate)

**Entfallen.** Die Fließkomma-Rate war nur wegen der 0,585-Hz-Abweichung des
früheren 1162-µs-Rasters nötig. Mit exakt 860,000 Hz ist `sample_rate = 860`
bereits vollständig; gosst und Dashboard bleiben unverändert.

Der folgende Text dokumentiert den früheren, nicht mehr umzusetzenden Ansatz.

**Empfohlener Weg bleibt additiv statt Typwechsel.** `Meta.SampleRate uint16` im Blob
**stehen lassen** und ein neues Feld `SampleRateHz float64` danebenlegen. Alte Blobs
dekodieren, das neue Feld ist bei ihnen 0 → Fallback auf `float64(SampleRate)`.

**Die Begründung hat sich verschoben, das Ergebnis nicht.** Sufni.Bridge darf
mitgeändert werden, „fremder Consumer" zieht als Argument also nicht mehr. Der
eigentliche Grund ist ein anderer: die Bridge ist nicht nur Leser, sondern
**auch Produzent** des Blobs (`TelemetryData.cs:735` / `:833`
`MessagePackSerializer.Serialize(this)`) und hat eine **eigene** Pipeline mit
eigenem `CurrentProcessingVersion = 30` (`TelemetryData.cs:180`). Ein Typwechsel
`SampleRate` uint16→float64 im Blob erzwingt damit ein **Lockstep-Deploy** beider
Seiten: eine alte Bridge stolperte über einen Float unter dem Key `SampleRate`
(C#-Property ist `int`, `TelemetryData.cs:187`), eine neue gosst-Version über die
uint16-Blobs, die jede noch nicht aktualisierte Bridge weiter schreibt. Additiv
kennt dieses Problem nicht — beide Seiten dürfen unabhängig ausgerollt werden.

Kosten der Alternative, falls doch jemand „sauber" will: `int SampleRate` → `double`
schlägt auf ~110 Fundstellen in 26 Dateien der Bridge durch, u. a.
`ComputeVelocity(double[], int)` (`TelemetryData.cs:494`), `FilterStrokes`
(`Strokes.cs:241`), die Cache-Spalten `int? SampleRate` (`SessionCache.cs:288/307`)
sowie zwei heute ganzzahlige Divisionen (`SQLiteDatabaseService.cs:1097`,
`ImportSessionsViewModel.cs:340`). Nicht empfohlen.

Umzustellen in gosst (Signaturen `uint16` → `float64`):

| Funktion | Ort |
|---|---|
| `calculateDerivative` | `psst.go:226` |
| `forkVelocityZeroThreshold` | `psst.go:127` |
| `shockVelocityZeroThreshold` | `psst.go:131` |
| `rearWheelVelocityZeroThreshold` | `psst.go:135` |
| `rejectSingleSampleSpikes` | `psst.go:269` |
| `reprocessSuspension` | `psst.go:630` |
| `filterStrokes` (`rate`, nicht `sampleRate`) | `stroke.go:397` |
| `coveredByAirtime` | `airtimes.go:8` |

(Die Funktionen `rearWheelVelocityZeroThreshold` und
`rejectSingleSampleSpikes` kamen mit dem Dead-Band-Umbau dazu. Beide tragen
ebenfalls den Parameter `sampleRate uint16`.)

(Zeilen Stand 2026-08-13. Die Threshold-Funktionen tragen seit dem Dead-Band-Umbau
einen zusätzlichen Parameter `travelPerLsb float64`; die Umstellung betrifft
weiterhin nur `sampleRate uint16` → `float64`.)

~32 Fundstellen in 4 Dateien, durchweg Divisionen/Multiplikationen; die
`float64(...)`-Casts fallen weg.

Weiter:
- `gosst-http.go:40` `Session.SampleRate` → `float64`, JSON-Feld `sample_rate` bleibt
- `CurrentProcessingVersion` 9 → 10 (`psst.go:106`), damit alte Blobs neu gerechnet werden
- **Fallback ist dauerhaft, nicht übergangsweise:** solange die Bridge Blobs ohne
  `SampleRateHz` schreiben darf, muss gosst den 0-Fall auf ewig behandeln
- **Dashboard (optional, analog AP7b):** Die Blob-Dekodierung ist unkritisch.
  `_dfd` in `dashboard/app/telemetry/psst.py:142` setzt unbekannte Keys per
  `setattr`. Das neue Feld `SampleRateHz` landet sauber am Objekt. Nichts bricht.
  Das Dashboard liest aber weiter `t.SampleRate`. Das bleibt bei der additiven
  Lösung 860. Der Ratenfehler bleibt damit wie bei der Bridge ohne AP7b bei
  0,068 %. Der Fix ist klein: `SampleRateHz float` in die `Telemetry`-Dataclass
  (`dashboard/app/telemetry/psst.py:131`) aufnehmen, eine Property
  `rate = SampleRateHz or SampleRate` ergänzen und die Aufrufstellen umhängen:
  `dashboard/app/api/session/routes.py:99`, `:199` und `:416`,
  `dashboard/app/telemetry/balance_metrics.py:124`,
  `dashboard/app/telemetry/travel.py:498` und `:506`,
  `dashboard/app/telemetry/misc_plots.py:223` sowie
  `dashboard/app/telemetry/fft.py:67`.

---

### AP7b — Entfallen (ehemals Sufni.Bridge, symmetrisch additiv)

**Entfallen.** Wie AP6 und AP7 diente dieses Paket ausschließlich dazu, die
0,585-Hz-Abweichung weiterzureichen. Beim exakten 860-Hz-Raster benötigt die
Bridge weder ein Zusatzfeld noch einen Processing-Version-Bump.

Der folgende Text dokumentiert den früheren, nicht mehr umzusetzenden Ansatz.

Sufni.Bridge ist nicht Teil dieses Repositories. Dessen oberste Ebene enthält nur
`caddy`, `dashboard`, `firmware`, `gosst`, `pics` und `test_utils`. AP7b braucht ein
separates Checkout.

Zweck: die Bridge rechnet ihre eigene Verarbeitung ebenfalls mit der exakten Rate und
gibt sie in selbst geschriebenen Blobs weiter. Ohne AP7b bleibt sie funktionsfähig,
nur mit 0,068 % Ratenfehler und ohne `SampleRateHz` in ihren Blobs.

1. `Models/Telemetry/RawTelemetryData.cs`: Bytes 6–8 (heute Padding-Kommentar,
   Zeile 37) als `ushort SamplePeriodUs` lesen; `double SampleRateHz` =
   `Version >= 4 ? 1e6 / SamplePeriodUs : SampleRate`. Magic-Check und
   `HeaderSize = 16` bleiben unangetastet.
2. Durchreichen an den `TelemetryData`-Konstruktor in den drei Einlesepfaden:
   `MassStorageTelemetryFile.cs:53`, `NetworkTelemetryFile.cs:32`,
   `StorageProviderTelemetryFile.cs:67`.
3. `TelemetryData`: `double SampleRateHz` **neben** `int SampleRate` (Zeile 187)
   — Map-Mode (`keyAsPropertyName: true`, Zeile 173) heißt: alte Blobs liefern 0 →
   Fallback auf `SampleRate`, exakt die gosst-Semantik. In `ComputeVelocity`
   (`:494`), `FilterStrokes` (`Strokes.cs:241`) und den Plots die neue Property
   verwenden. `Parameters.WhLambdaForCutoff` nimmt bereits `double`
   (`Parameters.cs:267`) — dort nichts zu tun.
4. `CurrentProcessingVersion` 30 → 31 (`TelemetryData.cs:180`), sonst behalten
   gecachte Blobs ihre mit 860 gerechneten Geschwindigkeiten.

Die Whittaker-Referenzrate `WhReferenceSampleRate = 860.0` (`Parameters.cs:250`)
bleibt, wie sie ist: 860 → 860,585 verschöbe λ um 0,14 %, unterhalb jeder Relevanz.

---

### AP8 — Abnahme

1. **DRDY lebt:** 832,4 SPS (Fork) / 868,1 SPS (Shock). Mit AP0 Test 2 bereits
   erbracht.
2. **Keine verlorenen Reads:** 2-min-Aufnahme unter Last (SD-Writes laufen),
   `late_count == 0`, `i2c_err_count == 0`, `glitch_count == 0`. Die
   Fehlerfenster liegen an den Puffertauschen (alle 2048 Records = 2,38 s),
   nicht in der Dauer: 2 min decken ~50 Puffertausche und ~10^5 Wandlungen je
   Kanal ab, das Zwoelffache der AP3-Verifikation. Die fruehere 10-min-Vorgabe
   stammte aus der entfallenen Langzeit-Logik.

   > **Bestanden am 2026-08-14 (00280, 128 s, ~54 Puffertausche):** keine
   > Zaehleranzeige nach dem Stopp, alle Fehlerzaehler null.

3. **Der eigentliche Test:** Die Referenzaufnahme `ref-vor-drdy.SST` (126 s,
   108682 Records, Ruhe, alte Firmware) zeigt im Duplikat-Indikator
   (`v[n] == v[n-1]`) einen Kamm bei 27,94 Hz und Vielfachen auf dem Fork sowie
   einen Kamm mit 7,38 Hz Grundabstand auf dem Shock. Beide Schwebungskämme müssen
   nach dem Umbau verschwinden. Im Differenzenquotienten dominieren auf beiden
   Kanälen zwei Linien bei 88,7 Hz und 177,3 Hz, 8 bis 13 dB über dem Rauschen.
   Sie fehlen im Duplikat-Indikator und sind damit echtes Analogsignal, kein
   Abtastartefakt. Sie bleiben nach dem DRDY-Umbau und sind kein Fehlschlag. Ihre
   Herkunft ist ein eigenes, offenes Thema. Verdacht: Speisung.

   > **Bestanden am 2026-08-14 (00280, 128 s Ruhe):** Duplikatrate Fork 8,0 %,
   > Shock 11,4 % (v3: 41 %/35 %), kein Kamm bei ~27,6 oder ~8 Hz. Staerkster
   > Rest-Peak bei 1,68 Hz = 4. Harmonische des 2048-Record-Pufferzyklus
   > (Rausch-Nebenbefund, kein Abtastartefakt). Kontrolllinien 88,6/177,3 Hz
   > mit 29-33 dB erhalten. Auch unter Bewegung (00281, 23 s Wippen) kein
   > Schwebungskamm.

4. **Schwebung im Signalspektrum:** Die Schwebungsfrequenz im Signal prüfen, nicht
   nur im Duplikat-Indikator. Die alte Firmware zeigte die Schwebung ausschließlich
   im Duplikat-Indikator; ihr Signal war frei davon. Der Indikator allein hätte
   diesen Fehler nicht gefunden.

   > **Ergebnis (00279, 46,5 s, gerundeter Kern):** Die Schwebungslinie ist in
   > beiden Kanälen nicht mehr nachweisbar. Maß ist die Phasenkohärenz über acht
   > Segmente, verglichen mit 290 Kontrollfrequenzen von 3 bis 60 Hz. Vorher
   > (00278, abschneidender Kern): Fork 0,980 und Shock 0,984, jeweils 0 von 290
   > Kontrollen stärker. Nachher (00279): Fork 0,542 mit 43 von 290 stärker,
   > Shock 0,677 mit 14 von 290 stärker. Beide liegen damit mitten in der
   > Verteilung der Kontrollen. Die Kontrolllinie bei 88,7 Hz bleibt in beiden
   > Kanälen erhalten (+14,7 dB, 0 von 194 Kontrollen stärker); echtes
   > Analogsignal geht also nicht verloren. Header: SST, Version 4, 860 Hz.
   >
   > Offen: 00279 entstand mit frisch geladenem Akku und zeigt rund zehnfach
   > höheres Breitbandrauschen als 00278. Der Test bleibt gültig, ist aber
   > unschärfer als nötig. Eine Wiederholung in Ruhe mit halb geladenem Akku
   > ist kurzfristig nicht machbar: eine 10-min-Messung entlädt den Akku nicht
   > auf halb. Die Wiederholung erfolgt opportunistisch, sobald der Akku durch
   > normale Nutzung teilentladen ist. Sie ist kein Abnahme-Blocker; die
   > Schwebungslinie ist in 00279 trotz des Rauschens statistisch sauber
   > widerlegt.
5. **Skew:** 15-20 s im Stand auf den Pedalen wippen, so gleichmaessig wie von
   Hand moeglich (~2 Hz). Auswertung mit `~/Telemetry/harness-drdy-skew/skew.py`:
   Tracking-SNR >= 10 dB (keine WARNUNG) und kein dominanter Peak bei ~28 Hz
   oder ~8 Hz im Skew-Spektrum. Minutenlange rhythmische Anregung ist von Hand
   nicht machbar und nicht noetig: das SNR bestimmt die Amplitude, nicht die
   Dauer; das Skript verwirft nur ~26 ms Raender. Der Wander-Mechanismus
   (Sample-Hold-Schwebung) ist durch die Punkte 3 und 4 bereits widerlegt;
   dieser Test bestaetigt nur den Restpfad eines konstanten Kanalversatzes
   (AP3-Grenze 37 us). An Ruheaufnahmen ist der Test nicht fuehrbar: die
   88,6-Hz-Linie ist fuer Phasen-Tracking zu schwach (Tracking-SNR -13 bis
   -8 dB), und ihre Schwebungs-Seitenbaender sind mit 8-12 dB kein
   Diskriminator.

   > **Bestanden am 2026-08-14.** Anregungslinie 3,2 Hz (00281) wie erwartet
   > untauglich (Mechanik im Trackingband, WARNUNG). Nachweis an der
   > 88,63-Hz-Linie von 00280 mit `--lp 0.5`, Tracking-SNR +11,9 dB:
   > mittlerer Skew -23 us (Kontrolle bei 177,26 Hz: -26 us, konsistent),
   > trendbereinigte Std 64 us ueber 128 s, kein Drift. Staerkster Peak im
   > Skew-Spektrum 3-60 Hz: 1,6 us. Das 0,5-Hz-Filter daempft 28-Hz-Anteile;
   > Obergrenze aus diesem Lauf ~350 us bei 28 Hz. Zusammen mit fehlendem
   > Duplikat-Kamm und widerlegter Schwebungslinie ist das v3-Wandern von
   > +-1,2 ms dreifach unabhaengig ausgeschlossen.

6. **Sufni.Bridge:** eine v4-Rohdatei wird trotz unverändertem Headerformat
   eingelesen; `sample_rate = 860` gilt unverändert für alle Konsumenten.
7. **Regression:** alte v3-Dateien müssen unverändert durchlaufen.

*Entfallen:* der frühere Langzeittest > 75 min. Aufnahmen sind Minuten lang, der
uint32-Wrap ist mit der Regel aus AP3 rechnerisch abgedeckt statt empirisch.

---

## Risiken

| Risiko | Wirkung | Abfederung |
|---|---|---|
| DRDY pulst nicht wie im Datenblatt | Plan hinfällig | AP0 Test 2, vor allem anderen |
| `t_0`-Offset falsch herum | Interpolation läuft nie, Fallback maskiert es | Vorzeichen-Begründung in AP5; Randfall-Zähler in AP8.2 mit abnehmen |
| 64-bit-Zeit in die uint32-Kette gemischt | Wrap wird doch sichtbar (Timer läuft ab Boot) | Wrap-Regel AP3; Differenzen ≤ 10 min ≪ 2³¹ µs → modular exakt, solange nichts gemischt wird |
| `resample()` hart im Callback | bricht Mixed-Presets (AS5600/ADS131) | `sample_at`-Op mit `measure()`-Default (AP5) |
| Fester 1162-µs-Timer | Raster läuft 0,585 Hz zu schnell; `t_k` verlässt langfristig den Ring | exakter 1162/1163-µs-Restakkumulator (AP5) |
| Alarm relativ zur tatsächlichen Callback-Zeit | Interrupt-Jitter summiert sich als Rasterdrift | negativer Alarm-Rückgabewert plant relativ zum Sollzeitpunkt (AP5) |
| I²C-Anstiegszeit außerhalb Spec (Bestand) | sporadische Lesefehler | AP1: 2,2 kΩ parallel eingelötet, gemessen 1,8 kΩ; 1 MHz bleibt; AP3: über 10 s je Kanal `i2c_err_count = 0` |
| SD-SPI koppelt auf die 10-kΩ-ALRT-Leitung | Phantom-Sample verdrängt echte Stützstelle | Drähte trennen (AP1); Intervall-Gate + `glitch_count` (AP3) |
| Late-Reads durch Core0-Blockaden | falscher Wert zu altem Zeitstempel | `late_count`; DRDY-IRQ-Priorität nur während der Aufnahme anheben, da IO_IRQ_BANK0 ein Vektor für die gesamte GPIO-Bank ist und die Anhebung damit auch den Funk-IRQ betrifft |
| CR-Randfälle am Aufnahmestart | erste Samples unbrauchbar | Ringe vorfüllen, `t_0` erst danach |

## Zu verifizierende Annahmen

- ~~ALRT am Modul herausgeführt~~ → am Foto bestätigt (AZ-Delivery, Pin 6)
- ~~ALERT-Pull-up bestückt~~ → gemessen, 10 kΩ ✓
- Sufni.Bridge braucht kein Zusatzfeld mehr; AP7b ist mit dem exakten Raster
  entfallen. Der v4-Versionswert ändert das Headerformat nicht.
- ~~uint32-Wrap tritt in realen Aufnahmen auf~~ → Aufnahmen max ~10 min, Wrap nur
  noch als Hygiene-Regel relevant (AP3)
- ~~DRDY-Pulsbreite und Polarität~~ → 8 µs und aktiv low auf beiden Kanälen,
  AP0 Test 2 ✓
- ~~`COMP_QUE = QUE_1` reicht, um den Pin zu aktivieren~~ → AP0 Test 2 ✓
- ~~GPIO-IRQ und PWM-Flankenzählung auf demselben Pin schließen sich nicht aus~~ (die
  Interruptlogik greift den Pegel am Pad ab, vor dem Function-Mux) → AP0 Test 2
  mit Zählerdifferenz 0 verifiziert ✓
- AP7 bringt kein Blob-Feld mehr ein; ein entsprechender Codec-Test entfällt.

## Reihenfolge

```
AP0 ─ AP1 ─ AP2 ─ AP3 ─ AP4 ─ AP5 ─ AP8

AP6 / AP7 / AP7b: entfallen durch das exakte 860-Hz-Raster
```

## Offene Nebenbefunde

Beide Punkte sind beim Umbau aufgefallen, gehören aber nicht dazu. Sie sind
dokumentiert, damit sie nicht verloren gehen.

**Breitbandrauschen, an den Schreibpuffer gekoppelt — behoben.** Untersucht am
2026-08-14 (phasenstarre Faltung auf den 2048-Record-Zyklus, Residuum gegen
9-Punkt-Median). Betroffen sind 00279, 00280 und 00281 (alle mit frisch
geladenem Akku), frei sind 00276, 00277, 00278 und `ref-vor-drdy` (alle mit
fast leerem Akku). Befund:

- Rauschstärke: Fork bis 8,9 LSB MAD-σ statt 1,5 (00278), Shock 4,4 statt <1.
  Breitbandig, +26 dB gegenüber 00278 in allen Bändern 5–430 Hz, leicht
  fallend zu hohen Frequenzen, keine Burst-Periode im Record-Raster
  (Autokorrelation nach Lag 1 ≈ 0).
- Fensterlage, in allen betroffenen Aufnahmen identisch: Records ~4 bis ~247
  nach dem Puffertausch sind ruhig (≈284 ms), ab Record 247/248 (scharfe
  Kante) bis in die Records 0–3 des nächsten Puffers ist das Signal gestört.
  Die frühere Angabe "erste ~170 Records ruhig" war zu kurz gemessen.
- Streng einseitig: Obergrenze bleibt der Ruhewert (p99,9 der Abweichung
  +1 LSB). Median im gestörten Fenster liegt 16 LSB (Fork) bzw. 8 LSB
  (Shock) unter dem Ruhewert, Extremwerte −45/−23 LSB. Fork/Shock-Korrelation
  0,82 — Gleichtakt, nicht mechanisch.
- Der Effekt ist alt: 13 von 205 Archiv-Aufnahmen in
  `/Volumes/data/DAQ_backup_260712` (Firmware v3, 2026-03 bis 2026-07)
  zeigen dieselbe Signatur mit gleicher Fensterlage (ruhig bis Record
  ~253). Der DRDY-Umbau ist als Ursache ausgeschlossen.

Deutung: Der SD-Schreibvorgang (`f_write` + `f_sync` direkt nach dem Tausch)
ist nicht der Auslöser, sondern der Dämpfer. Seine Last hält den Wandler
≈285 ms im Dauerbetrieb; solange ist das Signal ruhig. Fällt die Last ab,
geht der RT6154 in den Puls-Skip-Betrieb (PFM), und die 3V3-Versorgung sackt
zwischen den Pulsen ein — einseitig nach unten, wie gemessen. Bei fast leerem
Akku (V_in ≈ V_out) bleibt der Wandler auch bei geringer Last aus dem
Skip-Betrieb heraus. Die Firmware setzt WL_GPIO1 (SMPS-PSM-Pin des Pico W)
nie; der Wandler läuft also immer im PFM-Default.

Fix: `on_rec_start` setzt `cyw43_arch_gpio_put(SMPS_FORCE_PWM_WL_GPIO, true)`
vor `state = RECORD`, `on_rec_stop` nimmt es zurück (`main.c`). WL_GPIO1 high
zwingt den RT6154 in den PWM-Betrieb, solange die Aufnahme läuft.

Verifikation (00282, voller Akku, 121 s Ruhe, 51 Puffertausche, Version 4,
860 Hz): Das Rauschen ist vollständig weg. MAD-σ Fork und Shock = 0,0 LSB über
den ganzen Zyklus, kein ruhig/laut-Fenster mehr, kein einseitiger Sag
(Median-Delta 0 LSB je Phase, Extremwert −1 LSB), Fork/Shock-Korrelation 0,06
(vorher 0,82). Echtes Analogsignal bleibt erhalten: Kontrolllinien 88,7 Hz und
177,3 Hz weiter nachweisbar (Fork +25,4/+21,3 dB, Shock +21,1/+18,8 dB). Damit
ist der Wandler als Ursache bestätigt und der Fix wirksam. Die opportunistische
Wiederholung bei teilentladenem Akku (AP8.4) entfällt.

**Reset-Schleife im MSC-Zustand — behoben.** Das Gerät kam bei USB-Versorgung
nicht in den MSC-Zustand: `read_voltage()` lieferte unter 4,4 V, dreimal in Folge,
danach `soft_reset()`. Die ursprüngliche Folgerung („VSYS liegt wirklich unter
4,4 V") war falsch. Tatsächliche Ursache: der cyw43 klemmt im Power-Save die
geteilte ADC3/GPIO29-Leitung auf ~0 V, die Messung las eine eingebrochene
Versorgung, wo keine war. Fix in `edf898c`: `read_voltage()` weckt den Chip vor
der Messung per `cyw43_arch_gpio_get` (Muster aus pico-examples `read_vsys`),
Schwelle auf 4,30 V präzisiert, und ein absichtlicher Reboot in den MSC-Zustand
wird über `watchdog_hw->scratch[3]`-Magic mit 10 s USB-Timeout erzwungen. Der
Umbau war wie vermutet nicht die Ursache; der Fehler bestand auch auf `main`.

**MSC-Session bricht ~20 s nach dem Mount ab — behoben.** Seit Juli 2026
bekannt (Vermerk in `955ac70`): kurz nach dem Mount fiel das Gerät vom USB-Bus,
das Display blieb bei „MSC MODE" stehen, nur ein Neustart half. Diagnose am
2026-09-03 in vier Stufen am Gerät: (1) Watchdog 4 s im MSC-Zustand mit
Phasen-Code in `scratch[4]` — Ergebnis „HANG P2", also innerhalb von
`tud_task()`, nicht in SD-Init/Read/Write. (2) Ohne cyw43 und ohne
VSYS-Messung im MSC-Zustand: Abbruch bleibt, die Absteck-Erkennung ist
unschuldig. (3) PC-Sampler (Hardware-Alarm alle 1 ms, gestapelten PC in
`scratch[6]`, `addr2line` gegen das gesicherte ELF): Der Code drehte in
`uart_tx_wait_blocking` aus `stdio_uart_out_flush` — ein `panic()`, dessen
Meldung in der UART hängen blieb (TinyUSBs `board_init()` registriert den
stdio-UART-Treiber auch im Release-Build). (4) `panic()` per
`PICO_PANIC_FUNCTION=sst_panic` abgefangen, Meldung und erstes Argument in
Scratch-Registern gesichert, nach dem Reset auf dem OLED gezeigt:
`ep 03 was already available`, Endpunkt 0x03 = MSC-Bulk-OUT.

Ursache ist ein Fehler in TinyUSB 0.17.0 (Pico SDK 2.1.0), kein eigener Code:
macOS schickt kurz nach dem Mount `CLEAR_FEATURE(ENDPOINT_HALT)` auf den
MSC-OUT-Endpunkt, während der Empfang des nächsten CBW schon scharf ist.
`usbd_edpt_clear_stall()` löscht das `busy`-Flag des Endpunkts, der
MSC-Klassentreiber sieht ihn als frei und schaltet den CBW-Empfang erneut
scharf. Der rp2040-Port löscht beim Clear-Halt aber nur das STALL-Bit; der
alte Puffer bleibt AVAIL, und der zweite Start läuft in
`panic("ep %02X was already available")` (`rp2040_usb.c`). Upstream ist das
seit TinyUSB 0.21 (RP2-Treiber-Refactor) behoben: `dcd_edpt_clear_stall`
bricht den laufenden Transfer ab und startet ihn neu.

Fix in `9b24da0`, ohne Eingriff ins SDK: Linker-Wrap
`--wrap=dcd_edpt_clear_stall`; `__wrap_dcd_edpt_clear_stall()` in `main.c`
setzt `usb_dpram->ep_buf_ctrl[n].out/in = 0`, bevor das Original läuft.
Zusätzlich beantwortet `tud_msc_scsi_cb` SYNCHRONIZE CACHE (0x35) als Erfolg.
Als Sicherheitsnetz bleiben drin: Watchdog 4 s im MSC-Zustand mit Phasen-Code,
`scratch[5]`-HANG-Magic, 10 s „HANG P<n>" bzw. „PANIC <ep>" plus Meldungstext
nach einem Watchdog-Reset, danach automatisch wieder MSC; `sst_panic()` als
`panic()`-Ersatz (Reboot per Watchdog statt UART-Ausgabe). Der PC-Sampler
wurde nach der Diagnose wieder entfernt.

Verifikation: 10 min gemountet, 100 MB gelesen, 200 KB und 2 MB geschrieben
und byteweise zurückgelesen, kein Abbruch; vorher Abbruch nach 15–35 s in
jedem Lauf. Endversion (mit reaktivierter Absteck-Erkennung): 5 min stabil,
Abziehen führt korrekt in die Idle-Anzeige.

Ausgeschlossen: RP2040-Errata-E15-Workaround (`UFRAME_FIX=0` getestet, Abbruch
bleibt) und die VSYS-Messung. Nebenbefund: `read_voltage()`-Werte unter 2,5 V
gelten jetzt als Störung der geteilten ADC3-Leitung und werden verworfen,
Entprellung 8 × 250 ms. Auf dem Mac bleiben tote Mounts als Zombie in der
Mount-Tabelle („Resource busy"); ein neu angestecktes Gerät bekommt dann
`disk9`/`disk10`, Mount auf einen frischen Mountpoint.
