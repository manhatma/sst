# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Sufni Suspension Telemetry (fork of `sghctoma/sst`): MTB suspension data logger. Three parts live here:

- `firmware/` — Raspberry Pi Pico W data acquisition unit (C, Pico SDK 2.1.0). Almost all current work happens here.
- `gosst/` — Go backend: `gosst-tcp` (receives SST files from the DAQ over TCP), `gosst-http` (processing API), `gosst-file`. Signal processing lives in the separate module `gosst/formats` (`psst/`, `sst/`), tied together by `go.work`.
- `dashboard/` — Flask + Bokeh web UI (Python 3.11, SQLite, Alembic migrations, webpack frontend in `dashboard/frontend`).

`docker-compose.yml` wires dashboard, gosst-http, gosst-tcp (port 557) and Caddy together.

The main consumer of recordings today is the separate .NET/Avalonia app **Sufni.Bridge** (`../Sufni.Bridge`, iOS). It parses `.SST` files itself (`Models/Telemetry/RawTelemetryData.cs`). A change to the file format or to the sample-time semantics must be mirrored there, and in `gosst/formats`.

## Commands

Firmware (Pico SDK 2.1.0 at `/Users/niels/pico/pico-sdk`, Arm GNU toolchain at `/Applications/ArmGNUToolchain/15.2.rel1`; `~/.pico-sdk` from the VS Code extension is not installed, the `sdkVersion` block at the top of `CMakeLists.txt` has no effect):

```bash
cd firmware
cmake --preset spi_card-i2c_disp-linear_fork-linear_shock          # configure (release)
cmake --build --preset spi_card-i2c_disp-linear_fork-linear_shock  # build
# output: build/release/spi_card-i2c_disp-linear_fork-linear_shock/sufni-suspension-telemetry.uf2
```

- `-debug` presets build into `build/debug/...` and enable UART printf plus SNTP debug.
- Only the linear/linear preset (two ADS1115 via I2C) is the hardware in use. `CMakeLists.txt` compiles `linear_ads1115.c` unconditionally and has `rotational.c` (AS5600) commented out, so the AS5600 presets are not maintained.
- The stale `firmware/build/sufni-suspension-telemetry.uf2` is not the preset output; always use the preset build dir.
- Flashing: with the Pico in BOOTSEL, copy the `.uf2` to `/Volumes/RPI-RP2`, or use `picotool load -x <file>.uf2`. Before flashing, back up the device image with `picotool save` into `/Users/niels/Telemetry/firmware-backup/` (sibling of the repo root, not of `firmware/`; see its README).
- `drdy_probe` is a separate throw-away diagnostic firmware (USB serial + display) for verifying ADS1115 DRDY timing on hardware.

Backend and dashboard:

```bash
cd gosst && make                                   # builds dist/cmd/gosst-{tcp,http,file}
cd gosst/formats && go test ./...                  # processing tests
cd gosst/formats && go test ./psst -run TestRejectSingleSampleSpikes  # single test
cd dashboard && pytest tests/test_stats.py         # dashboard tests (conftest.py sets up app + fixtures)
```

## Firmware architecture

`src/fw/main.c` is a state machine (`enum state` in `src/fw/sst.h`, handlers in `state_handlers[]`): IDLE, SLEEP, WAKING, REC_START, RECORD, REC_STOP, SYNC_DATA, SERVE_TCP, MSC, calibration states, BOARDID_SELECT. Two push buttons drive the transitions (`src/ui/pushbutton.c`); the SSD1306 display shows the state.

Recording pipeline (the part that needs care):

- **Core 0** runs a repeating hardware alarm (`data_acquisition_cb`) on an exact **860.000 Hz** grid (1162/1163 µs steps with remainder carry). Negative alarm delays keep late ticks from accumulating drift.
- Each ADS1115 raises DRDY on a GPIO. `src/sensor/drdy_ring.c` timestamps every conversion into a 16-entry ring per channel (IRQ on core 0). `sensor_sample_at(sensor, t_k_us)` resamples the ring onto the grid time with a Catmull-Rom kernel. The ADCs free-run at ~832 SPS (fork) and ~868 SPS (shock), so the grid is decoupled from ADC clocks. The grid start is set 3603 µs in the past so the kernel has later support points.
- Samples go into one of two 2048-record buffers. When one is full, core 0 hands it to **core 1** via the multicore FIFO (`DUMP`), and core 1 writes it to the microSD card (FatFS). `OPEN`/`FINISH` open and close the file. The FIFO push/pop pairs are the ordering barriers; `open_datafile()` drains the FIFO first.
- The DS3231 RTC and the display share the PIO I2C state machine (`src/pio_i2c`). Anything touching the DS3231 must run on core 0. That is why the session timestamp is read on core 0 into `pending_timestamp` before `OPEN`.
- During RECORD the firmware forces the CYW43 SMPS into PWM mode (PFM ripple shows up as ADC noise).

File format (`.SST`, little-endian): 16-byte header `"SST"`, version `4`, `uint16` sample rate (860), 2 bytes padding, `int64` UTC timestamp; then 4-byte records `{uint16 fork, uint16 shock}` of raw ADC codes. Files are `00001.SST`… numbered via the `INDEX` file. After upload they move to `uploaded/` or `trash/`.

Time: `src/ntp/ntp.c` keeps the DS3231 as the source of truth (`rtc_timestamp()` falls back to the Pico RTC when the DS3231 value is implausible). WiFi modes (SYNC_DATA, SERVE_TCP) sync via SNTP. The Sufni.Bridge app also sets the time over TCP (`STATUS_TIME_SYNC` in `src/net/tcpserver.c`, protocol v2).

USB MSC mode (`src/msc/`) exposes the SD card to a host. It carries workarounds for TinyUSB 0.17 (`--wrap=dcd_edpt_clear_stall` in `CMakeLists.txt`, bus-suspend handling, watchdog phase codes in `watchdog_hw->scratch[]`). `panic()` is routed to `sst_panic`, which records the message and reboots via the watchdog. Read the comments in `main.c` around `MSC_*` before touching USB code.

Runtime configuration is read from a `CONFIG` file on the SD card (`SSID`, `PSK`, `NTP_SERVER`, `SST_SERVER`, `SST_SERVER_PORT`, `COUNTRY`, `TIMEZONE`; see `src/util/config.c`).

## Design documents

`firmware/docs/` holds the German planning and verification docs that explain *why* the firmware looks the way it does:

- `plan-drdy-resampling.md` — DRDY timestamping and resampling onto the 860 Hz grid (work packages AP0–AP8, measured ADC rates, open side findings).
- `protokoll-hw-verifikation-drdy.md`, `hardware-drdy-checklist.md` — hardware verification records.
- `plan-ads131m04-icm42686.md` — planned hardware revision (ADS131M04 ADC + ICM-42686-P IMUs, Hirose HR30 connectors).

Update the relevant doc when a firmware change affects its content.

## Conventions

- Commit messages are German with a scope prefix: `fw: …`, `docs: …`, `gitignore: …`. Firmware comments and docs are mostly German; code identifiers are English.
- `origin` is the user's fork `manhatma/sst`; upstream `sghctoma/sst` is not configured as a remote.
