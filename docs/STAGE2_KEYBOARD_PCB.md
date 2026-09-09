## Sources

### Stock mainboard — ArteryTek AT32F415

- [MHooijberg/Zoom75-Wireless-Firmware](https://github.com/MHooijberg/Zoom75-Wireless-Firmware) —
  research into porting QMK to the Zoom75 Wireless. `SPECIFICATION.md` identifies the MCU,
  the W25Q64 external flash and the unmarked radio module; the checklist shows where it
  stalled. Two unanswered issues, including one reporting a working QMK proof of concept for
  the Meletrix Zoom TKL derived purely from firmware analysis. Dormant since late 2024
- [MHooijberg/qmk_firmware, branch `meletrix_zoom75_tri-mode`](https://github.com/MHooijberg/qmk_firmware/tree/meletrix_zoom75_tri-mode) —
  draft board: `AT32F415`, `at32-dfu`, a complete `mcuconf.h` for a 16 MHz crystal (matches
  our board), `FLASH_START = 0x08001000` (stock bootloader occupies the first 4 KB), and a
  candidate matrix pinout
- [QMK PR #23445](https://github.com/qmk/qmk_firmware/pull/23445) — ArteryTek AT32F415 MCU
  support merged into `develop` on 2024-11-21
- [github.com/Meletrix](https://github.com/Meletrix) — wired boards only (atmega32u4). Useful
  purely as a reference for the logical 6×15 matrix; no wireless sources have ever been published
- Wireless module OTA procedure (from the Drive archive): `BLEOTA_V1.1.apk`, `Fn+Shift+U`
  enters update mode, device advertises as `KEY_BOARD_MODULE_OTA`, auto-exits after 20 s

### PCB design references

- [ebastler/zmk-designguide](https://github.com/ebastler/zmk-designguide) — guide to designing
  nRF52840 ZMK boards, plus the marbastlib footprint library
- [ebastler/cornholius](https://github.com/ebastler/cornholius) — drop-in ZMK replacement PCB
  for an existing case: BQ24075 charging, gerbers, JLCPCB BOM. The closest analogue to this project
- [4pplet/cyber60](https://github.com/4pplet/cyber60) — 60% on nRF52840 (Holyiot YJ-18010),
  ZMK, production files published
- KipperSun **OBB87** — 80% ANSI on nRF52840, ZMK, 89 addressable LEDs
- karnadii **marvelous65** — 65% with encoder, OLED and RGB on ZMK; archived in 2022, but
  proves a classic-layout wireless board with a screen is buildable
- ai03 Unified Daughterboard — open-source USB daughterboard design

### Wireless and dongle

- [Official ZMK dongle guide](https://zmk.dev/docs/development/hardware-integration/dongle) —
  including the caveat that the keyboard becomes a peripheral and stops working without the dongle
- [ZMK issue #2885](https://github.com/zmkfirmware/zmk/issues/2885) — runtime switching between
  central and peripheral roles, still open
- [badjeff/zmk-feature-split-esb](https://github.com/badjeff/zmk-feature-split-esb) — Nordic ESB
  as a ZMK transport, latency from 1 ms. Working configs:
  [kmobs](https://github.com/kmobs/zmk-config),
  [pekorali](https://github.com/pekorali/zmk-cyn-sofle-with-dongle-and-single-trackpoint)
- [adafruit/Adafruit_nRF52_Bootloader](https://github.com/adafruit/Adafruit_nRF52_Bootloader) —
  UF2 bootloader; supported boards include PCA10059 and the Raytac MDBT50Q-RX Dongle
- [makerdiary/nrf52840-mdk-usb-dongle](https://github.com/makerdiary/nrf52840-mdk-usb-dongle) —
  procedure for switching between Open Bootloader and UF2 in both directions via `nrfutil`

### Displays

- [nice!view](https://github.com/zmkfirmware/zmk/blob/main/app/boards/shields/nice_view) —
  Sharp LS011B7DH03, 160×68, 36×14×2.9 mm, 3-wire SPI, ~10 µA
- **Vista272** and **Vista508** — pin-compatible nice!view replacements on the same
  MiP panel technology; Vista508 offers higher resolution at the same wiring
- [mctechnology17/zmk-nice-oled](https://github.com/mctechnology17/zmk-nice-oled) — modular
  widgets for OLED and nice!view, X/Y coordinates configurable via Kconfig, RAW HID support
- [carrefinho/prospector](https://github.com/carrefinho/prospector) and
  [prospector-zmk-module](https://github.com/carrefinho/prospector-zmk-module) — ZMK dongle
  with a full-colour LCD (XIAO nRF52840 + Waveshare 1.69" 240×280). Proof that colour displays
  work under ZMK, but only on USB power
- [splitkb Halcyon](https://docs.splitkb.com) — modular VIK platform: colour ST7789 TFT via
  Quantum Painter + LVGL, e-paper module, nRF52840 dongle sold separately. Note their explicit
  statement that the TFT module is **not supported** with wireless controllers — it drains a
  LiPo in roughly an hour. This is why the colour-screen-plus-battery combination requires the
  smart-module architecture