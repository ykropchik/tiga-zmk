# Decision log

Format: date, decision, rationale, status. Do not delete entries — mark them as cancelled instead.

| Date | Decision | Rationale | Status |
|---|---|---|---|
| 09.09.2026 | Project is split into two independent stages, display first | The display module is a separate device, developed on the bench, survives replacement of the main board | accepted |
| 09.09.2026 | No backlighting in stage 2 | Eliminates the LED type question, simplifies routing (possibly to 2-layer), radically improves battery life, reduces build cost | accepted |
| 09.09.2026 | Stage 2 MCU — Raytac MDBT50Q | 48 GPIO vs ~20 on Pro Micro boards; with a ~28-pin budget the headroom is needed; module is certified, RF section ready; ZMK `nice_nano_v2` as reference | preliminary |
| 09.09.2026 | Module placed where the stock radio module sits | The manufacturer already found the spot where signal exits the aluminium enclosure; we replicate the copper keep-out zone under the PCB antenna | accepted |
| 09.09.2026 | 2.4 GHz deferred | Does not affect board routing; resolved later in software — ZMK dongle over BLE (upstream) or ESB module (fork) | accepted |
| 09.09.2026 | Dongle — nRF52840 | ESB is only implemented in Nordic radios; ZMK BLE dongle is also proven on nRF | accepted |
| 09.09.2026 | Dump factory module firmware — task #1 | `OTA_CMD_READ_DATA` found in FR8000 SDK; module GATT matches SDK profile byte-for-byte, so reading is available over BLE without a soldering iron | accepted |
| 09.09.2026 | Prefer serial OTA over boot-ROM flashing for the module | Same opcode set, does not touch the bootloader, leaves a recovery path; boot-ROM flashing stays as the fallback | preliminary |
| 09.09.2026 | Stage 2 screen: route pads for both nice!view and the native module | Five-pin footprint (SPI) plus four-pin UART connector; costs almost nothing, keeps both paths open | accepted |
| 09.09.2026 | UART protocol reverse-engineering deferred past phase 0 | Phase 0 captured the module's frame format opportunistically (see `UART_PROTOCOL.md`), but full decoding needs the module talking to the main board (phase 1). Only needed for stage 2, so it can feed the module from the ZMK board — it does not block stage 1 custom-firmware development | accepted |
| 10.09.2026 | Panel treated as 320 × 172 RGB565 landscape | The 608-container resource catalogue caps at exactly 320 wide and 172 tall, with 88 containers at precisely that size; matches a 1.47" 172×320 ST7789 module used in landscape | accepted |
| 10.09.2026 | Never use Chip Erase, never touch Flash Protect | The MAC is not at `0x60000` and its real location is unknown, so a chip erase may be unrecoverable; the utility's Flash Protect entry *sets* protection rather than reporting it | accepted |
| 10.09.2026 | Reuse the HPLX container format in custom firmware | Format is fully decoded and trivial to read and write; keeping it means the existing ~8.7 MB of assets stays usable instead of being discarded | preliminary |
| 10.09.2026 | Panel confirmed as a 1.47" 172×320 ST7789 in landscape | Commands 0x2A/0x2B/0x2C with big-endian coordinates; visible area 320×172; live RAM read shows a 34-row Y offset, i.e. a 172-row strip centred on a 240-row die | accepted |
| 10.09.2026 | Custom firmware sets the window as columns 0..319, rows 34..205 | The Y offset of 34 is real, not zero as static analysis suggested; starting at row 0 shifts the image and corrupts the bottom edge | accepted |
| 10.09.2026 | Copy the vendor's frame-transfer architecture | Two PSRAM framebuffers plus chained DMA into the SSIM0 data register is the only workable approach — 110 KB per frame cannot be pushed byte-by-byte from a 96 MHz core | accepted |
| 10.09.2026 | Drop FPC pinout mapping from the plan | The module stays intact, so the panel wiring is internal to its board. Only relevant if the panel is ever detached or replaced | accepted |
| 10.09.2026 | Logic analyser no longer needed | Decompilation plus one live RAM read answered controller, geometry, offsets and MCU-side pinout | accepted |
| 12.09.2026 | Treat sprite replacement as a first-class way to customise the UI | The interface is assembled from sprites rather than drawn by code, so glyphs, icons and units can be swapped without touching firmware — the cheapest route to a custom look | accepted |
| 12.09.2026 | Animation vs sprite decided per run, by the first container's coverage | Per-container coverage is unreliable (a digit does not fill its box); the first entry of a size run is full-frame for animations and partial for sprite sets | accepted |
| 12.09.2026 | Keil license question deliberately deferred | Unlicensed Keil V5.28 caps linked images at ~32 KB, confirmed by building `ble_simple_peripheral` unchanged (106 660 bytes, `L6050U` linker error). Blocks any real firmware build until resolved — candidates are buying a license or switching to the SDK's own GCC/Makefile build path | open |

