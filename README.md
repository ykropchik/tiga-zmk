# tiga-zmk

Open electronics replacement for the Meletrix Zoom75 TIGA: custom display module firmware
and a custom keyboard PCB for ZMK.

## Why

The stock firmware is closed-source. Lack of keyboard customization,
and the screen layout cannot be configured. The goal is a fully open stack where every layer
can be modified.

## Target requirements

1. Remappable hotkeys for device switching and layout switching, presets per connection profile.
2. Screen with configurable layout: mode, connected device, battery level, layer.
3. Optional — background image / GIF.

## Two stages

| Stage | What | Status |
|---|---|---|
| **1** | Custom display module firmware (FreqChip FR8008HP) | phases 0 and 0.5 done |
| **2** | Custom PCB for the TIGA case on nRF52840 + ZMK | not started |

The stages are independent: the display module is a separate device, developed on the bench,
and survives replacement of the main board.

## Structure

```
docs/           knowledge base, decisions, protocols
  factory_dump/ factory firmware dumps (avoid committing large binaries unnecessarily)
hardware/       KiCad project, datasheets, board photos, measurements
firmware/
  display-module/  project for FR8008HP (Keil V5 528 + FR8000 SDK)
  keyboard/        zmk-config: board definition + keymap
research/       notes from related projects: cyber60, cornholius, al80-lcd, zmk-designguide
tools/          custom scripts: BLE client, dumper, UART protocol capture
```

## Where to start

Read `docs/STAGE1_DISPLAY_MODULE.md`. The first action on the plan is phase 0.5 —
dumping the factory module firmware over BLE. Do this before any flash writes.

## Key facts at a glance

- Display module: board `RA0167CS V1.0`, MCU **FreqChip FR8008HP** (Cortex-M3, 96 MHz,
  16 MB flash, 2 MB PSRAM), 24 MHz crystal, 13-pin FPC panel (Hirose connector),
  keyboard interface — UART on 4 pogo pins (`GND / RX / TX / VCC`).
- Module BLE: `ZOOM75 TIGA`, MAC `04:75:79:FB:DD:E7`, **no pairing required**.
- Panel: **320 × 172, RGB565, landscape**, driven in software over SPI (SSIM0). Likely ST7789.
- Flash: firmware banks A/B at `0x0` and `0x32000`; `HPLX` resource chain at `0x80000`
  (608 containers, ~8.7 MB); ~6 MB free above `0x929940`.
- Factory firmware **dumped over BLE**, both banks, byte-identical. Rollback is possible.
- Main keyboard board: **ArteryTek AT32F415** (LQFP64), 16 MHz crystal, external
  SPI flash, radio on a separate module with a PCB antenna on the main board.

## Sources

Stage-specific references live in the stage documents:
[stage 1](docs/STAGE1_DISPLAY_MODULE.md#sources) · [stage 2](docs/STAGE2_KEYBOARD_PCB.md#sources).
Listed here are project-wide sources and vendor material used by both stages.

### Vendor material

- **Wuque/Meletrix firmware archive** ([Google Drive](https://drive.google.com/drive/folders/1LjafcqynTOwxaq9joyR6-ybmTiCE5nr2)) — the single most useful find of the
  research phase. Screen module images for Zoom75, Zoom98 and Freya; `keyboard_project_base_ota.apk`;
  manual OTA instructions for both the screen module and the wireless module; QMK Toolbox;
  Meletrix ID desktop software; 3D board files. Owned by `wuquestudio@gmail.com`, so
  semi-official rather than a fan upload.
  <!-- TODO: insert link -->
- [Meletrix product page and firmware downloads](https://meletrix.com/pages/firmwares) — stock `.bin` files
  and VIA JSON definitions; also the TIGA source files (plate DXF), needed for stage 2
- [ZOOM75 TIGA operation instructions (PDF)](https://cdn.shopify.com/s/files/1/0835/9706/6540/files/ZOOM75_TIGA_Operation_Instructions.pdf) —
  authoritative list of stock hotkeys, including the ones that cannot be remapped

### Prior art — opening up closed keyboards

- [snackdriven/al80-lcd](https://github.com/snackdriven/al80-lcd) — the reference project for
  this whole effort: full reverse of the YUNZII AL80 LCD plus a custom vial-qmk firmware that
  keeps the screen working. Source of the key architectural insight — the display is a
  separate smart module, which is why it survives a firmware swap. Detailed notes in stage 1.
- [mctechnology17/awesome-zmk](https://github.com/mctechnology17/awesome-zmk) — curated list of
  ZMK drivers, configs, hardware and tooling; useful across both stages