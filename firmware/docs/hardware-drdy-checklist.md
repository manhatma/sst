# Hardware-Checkliste: DRDY-Verdrahtung + I²C-Pull-ups + AIN1-Abgriff

Umsetzung von AP1 aus [plan-drdy-resampling.md](plan-drdy-resampling.md), plus das,
was AP0 Test 2 physisch voraussetzt, plus der ratiometrische AIN1-Abgriff (eigenes
Thema, aber dasselbe offene Gehäuse). Parallel zur Software-Kette abarbeitbar.

**Abhängigkeit:** Phase A blockiert AP0 Test 2 (der Showstopper-Test zählt Flanken an
GP21/GP27 — ohne Drähte kein Test). Phase B und E sind unabhängig und jederzeit
möglich. Phase 0 muss vor allem anderen laufen.

## Material

| Menge | Teil |
|---|---|
| 4 | Widerstand 2,2 kΩ, 1/4 W (Wert unkritisch, 1,8–2,7 kΩ tut es auch) |
| 2 | Draht DRDY, so kurz wie möglich, AWG 26–30 |
| 2 | Draht GND für Verdrillung (optional, s. A4) |
| 2 | Draht AIN1-Abgriff (Phase E) |

Werkzeug: Lötkolben, Multimeter (Durchgang + Widerstand + DC-Spannung).
Kein Oszilloskop nötig — das macht der Pico in AP0 Test 2.

---

## Phase 0 — vor jedem Eingriff

- [ ] **0.1 Referenzaufnahme.** Ruheaufnahme bei stehendem Fahrwerk mit der
      **jetzigen** Firmware, Datei sichern und eindeutig benennen
      (`ref-vor-drdy.SST`). Ohne sie fehlt in AP8.3 der Vergleich für den
      ~28-Hz-Buckel im Differenzenquotienten — nachträglich nicht mehr herstellbar.
- [ ] **0.2 Fotos vom offenen Gehäuse**, bevor irgendwas abgelötet/verlegt wird.
- [ ] **0.3 VDD-Check am ADS1115-Modul (Gate).** Gerät an, Multimeter zwischen
      Modul-`VDD` und `GND`.
      - **3,3 V → weiter.**
      - **5 V → STOP, nicht mit GP21/GP27 verbinden.** Der ALRT-Pull-up läge dann auf
        5 V und der RP2040 ist nicht 5-V-tolerant. (Sehr unwahrscheinlich: die
        Modul-Pull-ups auf SDA/SCL lägen dann ebenfalls auf 5 V und hätten den Pico
        längst beschädigt. Der Check kostet 10 s, also trotzdem machen.)
      - Beide Module einzeln prüfen.

---

## Phase A — DRDY-Verdrahtung (blockiert AP0 Test 2)

- [ ] **A1 ALRT-Pin identifizieren.** AZ-Delivery-Board, 10-poliger Header, von
      rechts: `VDD, GND, SCL, SDA, ADDR, ALRT, A0, A1, A2, A3`.
      → **ALRT = 6. von rechts, sitzt zwischen `ADDR` und `A0`.**
      Nichts nachrüsten: Pull-up (10 kΩ) ist bestückt und gemessen (AP0).
- [ ] **A2 Fork-Modul `ALRT` → Pico `GP21`** (Header-Pin **27**).
- [ ] **A3 Shock-Modul `ALRT` → Pico `GP27`** (Header-Pin **32**).
      Zuordnung nicht vertauschen — die Intervall-Gate-Schwellen in AP3 sind
      kanalindividuell (Fork ~832 SPS, Shock ~850–859 SPS).
- [ ] **A4 Verlegung — die eigentliche Maßnahme.** Beide Drähte **weg von der
      SD-Verdrahtung GP16–19** (6,75 MHz, burstartig 8 KB alle ~2,4 s → garantiert
      gleichzeitig mit DRDY-Kanten). Die ALRT-Leitung ist mit 10 kΩ hochimpedant, eine
      eingekoppelte falsche fallende Flanke erzeugt ein Phantom-Sample.
      - Nicht parallel zu den SD-Drähten führen; wenn kreuzen, dann im 90°-Winkel.
      - Am Header ist der Abstand unvermeidbar klein (GP19 = Pin 25, GP21 = Pin 27).
        Das ist unkritisch — es geht um die Strecke, nicht um den letzten Zentimeter.
      - Optional, billig, wirksam: jeden DRDY-Draht mit einem GND-Draht verdrillen,
        GND an Pin **28** (nicht Pin 33 = AGND, die soll ruhig bleiben — dort hängt
        die VSYS-Messung mit dran).
- [ ] **A5 Kein Kondensator, kein Serienwiderstand** an DRDY. Filter verschmieren den
      Zeitstempel; Entstörung passiert über das Software-Intervall-Gate (AP3).
      Ausnahme s. „Reserve" unten.

**Danach ist AP0 Test 2 fahrbar.** Erwartung dort: ~8320 Counts (Fork) /
~8500–8590 (Shock) in 10 s, Puls ~8 µs, aktiv low.

---

## Phase B — I²C-Pull-ups (unabhängig, jederzeit)

Grund: der Bus läuft heute mit 1 MHz an 8,5 kΩ (10 kΩ Modul ∥ ~56 kΩ Pico intern)
→ t_r ≈ 216 ns gegen 120 ns Spec. Läuft, aber ohne Marge. Erklärt jedes
`i2c_err_count > 0` in AP8.

- [ ] **B1 Vorher-Messung** (Gerät **aus**), je Bus zwischen SDA und 3V3:
      Erwartung **~10 kΩ**. Bestätigt, dass Modul-Pull-up und 3V3-Rail derselbe Netz
      sind wie gedacht. Gleiches für SCL.
- [ ] **B2 Fork-Bus (i2c0):** 2,2 kΩ von **GP8/SDA** (Pin 11) nach 3V3,
      2,2 kΩ von **GP9/SCL** (Pin 12) nach 3V3.
- [ ] **B3 Shock-Bus (i2c1):** 2,2 kΩ von **GP14/SDA** (Pin 19) nach 3V3,
      2,2 kΩ von **GP15/SCL** (Pin 20) nach 3V3.
- [ ] **B4 Einbauort.** Der Plan sagt Pico-Seite; bei ~10 cm board-to-board und ~30 pF
      ist das elektrisch gleichwertig — also dort löten, wo es mechanisch am besten
      passt. Praktischster 3V3-Abgriff ist die **`VDD`-Pin des jeweiligen Moduls**
      (kommt ohnehin vom Pico-3V3, Pin 36 liegt auf der falschen Seite des Headers).
      Widerstände dann direkt am Modul-Header zwischen `VDD` und `SDA`/`SCL`.
- [ ] **B5 Nachher-Messung** (Gerät aus), gleiche Punkte: Erwartung **~1,8 kΩ**
      (2,2 k ∥ 10 k = 1803 Ω).
      - ~10 kΩ → Widerstand hängt nicht am richtigen Netz.
      - ~2,2 kΩ → Modul-Pull-up fehlt entgegen AP0, nachprüfen.
      - < 100 Ω → Kurzschluss, nicht einschalten.
- [ ] **B6 Nichts auslöten.** Die 10 kΩ auf den Modulen bleiben.

Senkstrom pro Leitung danach 1,83 mA — innerhalb der 3 mA des ADS1115.

**Software-Gegenstück** (macht die SW-Kette, nicht du): Baudrate 1 MHz → 400 kHz in
`linear_ads1115.c:94`. Kostet nichts, weil in Continuous Mode pro DRDY nur ein
2-Byte-Read bleibt (75 µs statt 30 µs, Budget sind 1,2 ms).

---

## Phase C — vor dem ersten Einschalten

- [ ] **C1 Durchgang** ALRT-Fork ↔ GP21, ALRT-Shock ↔ GP27.
- [ ] **C2 Kein Schluss** GP21 ↔ GND, GP21 ↔ 3V3, dito GP27; und keiner der beiden
      gegen die Nachbarpins (GP20 Pin 26, GP22 Pin 29, GP26 Pin 31, GP28 Pin 34).
- [ ] **C3 Kein Schluss** SDA ↔ SCL auf beiden Bussen (Lötbrücke am Modul-Header ist
      der wahrscheinlichste Fehler bei B4).
- [x] **C3b Kein Schluss** `A1` ↔ `A0` und `A1` ↔ `ADDR` (Phase E, Nachbarpins auf
      demselben Header). Ein Schluss A1↔A0 legt die Schleiferleitung auf die Speisung
      und sieht in den Daten wie Dauer-Vollausschlag aus.
- [ ] **C4 Zugentlastung/Fixierung** der neuen Drähte, das Gerät wird bewegt.

## Phase D — nach dem Einschalten, noch mit alter Firmware

- [ ] **D1 ALRT-Ruhepegel.** Multimeter DC an GP21 bzw. GP27 gegen GND:
      **~3,3 V, stabil.** Die alte Firmware lässt `COMP_QUE = QUE_DISABLE`, der
      ALERT-Ausgang ist hochohmig → der Pull-up hält high. Belegt Draht + Pull-up.
      Ein Wert um 0 V oder schwankend = Verdrahtungsfehler.
- [ ] **D2 Normale Aufnahme fahren**, prüfen dass beide Kanäle weiter sauber messen.
      Die Pull-ups können den Bus nicht verschlechtern (nur t_r verkürzen); wenn hier
      etwas kaputt ist, ist es die Verdrahtung, nicht das Konzept.
- [ ] **D3 Gehäuse zu**, aber erst nachdem AP0 Test 2 durch ist — sonst öffnest du
      zweimal.

---

## Phase E — ratiometrischer AIN1-Abgriff (unabhängig)

Eigenes Thema, nicht Teil des DRDY-Plans: die Poti-Speisung wird gemessen statt
angenommen (heute implizit 3,300 V in `resolution: 14.6883`). Zielt auf
**Reproduzierbarkeit** — Speisungsdrift mit Akku und Temperatur wirkt zwischen *und
innerhalb* von Sessions, 1 % = 2,0 mm am 200-mm-Fork. AIN1–AIN3 sind an beiden
Modulen frei.

- [x] **E1 Vorbedingung prüfen (Gate).** DMM Durchgang, Gerät aus: Poti-Klemme „+" am
      Stecker ↔ ADS1115-`VDD` müssen **dasselbe Netz** sein.
      **Poti an 5 V / VSYS ⇒ nicht anschließen** — abs. max. Analogeingang ist
      VDD + 0,3 V. Beide Kanäle einzeln prüfen.
- [x] **E2 A1-Pin identifizieren.** Selbe Pinreihe wie A1 in Phase A, von rechts:
      `VDD, GND, SCL, SDA, ADDR, ALRT, A0, A1, A2, A3`
      → **A1 = 8. von rechts = 3. von links, sitzt zwischen `A0` und `A2`.**
- [x] **E3 Fliegender Draht pro Modul: Poti-„+"-Pin → Modul-`A1`.**
      **Am Stecker abgreifen, nicht irgendwo am 3V3-Netz.** Falls Schutzwiderstand,
      Diode oder Abschalt-FET in Reihe liegt, muss der Abgriff **dahinter** sitzen —
      sonst misst A1 eine andere Spannung als das Poti sieht und der ganze Zweck ist
      weg.
- [x] **E4 Kein Teiler, kein RC, kein Serien-R** — weder auf A1 noch auf A0.
      (Begründung bei A0: ein C auf der Schleiferleitung reißt die Wiper-Stromgrenze
      des ELPM75 und macht den Quellwiderstand positionsabhängig.)
- [x] **E5 Zwischenprüfung ohne Firmware.** DMM DC zwischen Modul-`A1` und Modul-`GND`,
      Gerät an: muss gleich der VDD-Messung aus 0.3 sein (~3,3 V). Abweichung ⇒
      falscher Abgriffspunkt.
- [x] **E6 Abnahme mit Firmware-Support.** A1 muss **26400 counts** lesen
      (3,3/4,096 × 32768 = exakt 26400,0), Fenster **25600–27200**.
      - **32767 → falsche Schiene, sofort trennen.**
      - ~0 → nicht kontaktiert.
      - Wert **nicht als Voltmeter lesen** — er trägt den ADC-Gain-Fehler. Genau ist
        nur das Verhältnis `c_wiper / c_exc`, und genau darin kürzen sich Speisung
        und Gain weg.

> **Phase E abgenommen am 2026-08-18 (Commit `8776e8c`).** Beide Module: Draht
> A1 → Modul-`VDD` gelötet. Firmware-Support umgesetzt in
> `linear_ads1115.c` (c_exc-Messung via MUX SINGLE_1, ratiometrische
> Normalisierung `raw · 26400 / c_exc`, Pointer-Restore auf 0x00) und
> `main.c` (c_exc-Anzeige `CEXC F/S` nach CAL EXP). E6 auf Hardware:
> beide Kanäle im Fenster 25600–27200. Beide Kollisionen mit dem DRDY-Plan
> gelöst: c_exc-Messung in `start()` vor dem DRDY-Arm, Pointer nach jedem
> MUX-Wechsel explizit zurückgesetzt.

**Kein Format-Impact:** `baseline_norm = c_w0 · 26400 / c_exc` passt in dasselbe
`uint16_t` ⇒ CALIBRATION-Datei, `struct record`, `struct header` und der App-Faktor
`200 mm / 2^14,6883` bleiben unverändert. Kein Bump, kein Reprocessing.

### Zwei Kollisionen mit dem DRDY-Plan (für die Software-Kette)

Beides fällt erst auf, wenn beide Änderungen zusammen laufen:

1. **Reihenfolge in `on_rec_start`.** Die `c_exc`-Messung braucht einen MUX-Wechsel
   auf `MUX_SINGLE_1`; mit `COMP_QUE = QUE_1` und den AP2-Thresholds feuert ALERT
   **kanalunabhängig bei jeder Wandlung** — also auch bei den AIN1-Wandlungen. Die
   `c_exc`-Messung muss daher **vor** dem Scharfschalten der DRDY-IRQs und vor dem
   Ring-Vorfüllen (AP5) liegen, sonst landen Speisungswerte als Stützstellen im Ring.
   Symmetrisch in `on_rec_stop`: erst IRQs aus, dann optional messen.
2. **AP2-Pointer-Invariante.** AP2 eliminiert den Pointer-Write pro Read und setzt
   voraus, dass **kein anderer Pfad den Pointer bewegt**. Ein MUX-Wechsel ist ein
   Config-Write auf Pointer 0x01 — verletzt die Invariante. Nach jeder `c_exc`-Messung
   (in `on_rec_start`, `on_rec_stop` **und** in `calibrate_expanded`) muss der Pointer
   explizit auf 0x00 zurückgesetzt werden. Der Plan listet `calibrate_expanded` heute
   als „sicher"; mit Phase E stimmt das nicht mehr.

Ferner unverändert aus dem Rezept: **gleiche PGA** (`ADS1115_PGA_4_096`) für beide
Messungen, sonst kürzt sich der Gain-Fehler nicht mehr weg. Nach MUX-Wechsel erstes
Ergebnis verwerfen und ≥ 2,4 ms warten. `c_exc == 0` oder außerhalb 20000–30000 ⇒
Rückfall auf 26400. **Baseline-Normalisierung ist Pflicht**, nicht optional — ohne sie
tauscht man Skalen- gegen Offsetfehler, und Offset ist beim absoluten Federweg
schlimmer.

---

## Reserve — nur falls `glitch_count ≠ 0` in AP8

Erst dann, nicht vorbeugend: **100 pF von DRDY nach GND**, am Pico-Ende. Die fallende
Flanke wird vom Open-Drain hart getrieben (Entladung ~0,3 µs bei 1 mA), die Verzögerung
ist damit **konstant und auf beiden Kanälen gleich** → kein Skew, kein zusätzlicher
Jitter. Gegen kapazitive Einkopplung aus der SD-SPI wirkt es sofort. Vorher aber
Verlegung nachbessern (A4) — das ist die billigere Maßnahme.

## Was nicht zu tun ist

- Modul-Pull-ups (die vier „103") **nicht** auslöten.
- **Kein C auf der Schleiferleitung** der Potis — bei 2 m/s zieht schon 100 nF ~3,3 µA,
  dieselbe Größenordnung wie die 10-µA-Grenze des ELPM75, und der Quellwiderstand des
  Potis ist positionsabhängig.
- **GP26 nicht** als DRDY verwenden: Slice 5 **Kanal A**, kann keine Flanken zählen,
  und läge auf demselben Slice wie GP27.
- GP13 wäre die einzige Alternative (Slice 6B), kollidiert aber mit dem
  SPI-Display-Build.
- ADDR-Pins nicht anfassen, beide Module bleiben auf 0x48 (getrennte Busse).

## Reihenfolge am Basteltisch

Gehäuse geht genau einmal auf. Löten in einem Rutsch: Phase A (DRDY) + Phase B
(Pull-ups) + Phase E (AIN1). Prüfen in Phase C/D. Erst danach zu — und erst nachdem
AP0 Test 2 durch ist.

Isolierbar bleibt es trotzdem: die Pull-ups können einen laufenden 1-MHz-Bus nicht
verschlechtern (sie verkürzen nur t_r), und der AIN1-Draht ist ohne Firmware-Support
elektrisch wirkungslos. Wenn nach dem Zusammenbau etwas nicht geht, ist es die
Verdrahtung, nicht eine der drei Änderungen an sich.
