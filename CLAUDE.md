# Project context for the AI agent

Read this file first. It is a map, not the knowledge itself — open the referenced documents
when the task needs them. Do not read everything up front.

## Who I am and what I'm doing

Owner of a Meletrix Zoom75 TIGA. Not a professional electronics engineer. Replacing the
closed-source electronics with open ones: **stage 1** — custom display module firmware,
**stage 2** — custom keyboard PCB running ZMK.

## Where things are

| Need | File |
|---|---|
| Stage 1 plan, phase status, hardware facts, HPLX format, flash map | `docs/STAGE1_DISPLAY_MODULE.md` |
| Stage 2 plan and references | `docs/STAGE2_KEYBOARD_PCB.md` |
| UART wire protocol between module and main board | `docs/UART_PROTOCOL.md` |
| What was decided and why | `docs/DECISIONS.md` |
| Factory firmware dumps, both banks — rollback material | `docs/factory_dump/` |
| BLE tooling: OTA probe, flash dump, RAM read, flash map, resource grab, PNG decode | `tools/` |
| Hand-reconstructed C from the factory firmware | `research/` |
| Datasheets, board photos, measurements | `hardware/` |

Resource images (~8.7 MB of vendor sprites) are deliberately **not** in the repository. They
live outside it and are gitignored.

## Facts worth having in front of you

These come up in almost every task. Everything else, look up.

- **Module MCU:** FreqChip FR8008HP — Cortex-M3 96 MHz, 16 MB flash, 2 MB PSRAM, 56 KB SRAM.
  Board `RA0167CS V1.0`. BLE name `ZOOM75 TIGA`, MAC `04:75:79:FB:DD:E7`, **no pairing**.
- **Panel:** 1.47" 172x320 ST7789 in landscape. Visible area 320 x 172 RGB565.
  **The window is columns 0..319, rows 34..205** — the 34-row Y offset is real and was
  measured on live hardware, not derivable statically. Starting at row 0 shifts the image.
- **Framebuffer:** 110 080 bytes, two of them, in PSRAM. Pushed by chained DMA into the
  SSIM0 data register at `0x50030060`.
- **Display pins:** RST `PA2`, DC `PA4`, CS `PA5`, SPI on `PB0`/`PB2`-`PB5` (alt function 2),
  `PA3` an input (likely TE).
- **UART to the main board:** `PA0`/`PA1`, 115200 8N1. Wiring is **straight through, not
  crossed** — the pogo silkscreen is from the main board's point of view.
- **Wire frame format:** `A5 | msg_id | len(2, big-endian) | payload | checksum`, where
  checksum is `~(sum of everything after A5)`. A checksum of `0xFF` is accepted unverified.
- **HPLX spans:** `byte_len` is **signed**. Positive means 2 bytes per pixel, plain RGB565.
  Negative means 3 bytes per pixel, RGB565 plus alpha. Alpha is the common case (509 of 608).

## Hardware safety rules

- **Never send `OTA_CMD_CHIP_ERASE` (0x04).** The MAC is not at `0x60000` — that address
  reads back as `0xFF` — and its real location is unknown, so a chip erase may be
  unrecoverable. Reference value: `04:75:79:FB:DD:E7`.
- **Never toggle "Flash Protect"** in the FreqChip utility. It *sets* protection; it does not
  report it.
- Do not write blindly to the OTA service `fe00` — it carries erase and reboot commands.
- Do not touch the stock keyboard PCB. It is the continuity reference and the fallback path.
- Custom module firmware must carry a version **above 1**, or the boot loader will not select
  it. Factory version is 1 in both banks.
- The `0x02` UART transfer command refuses target addresses below `0x80000`, so the wire path
  cannot damage the firmware banks. The boot ROM can.
- BLE OTA `WRITE_DATA` only accepts the storage base (`0x32000`) or a contiguous continuation of
  the previous write — anything else is dropped silently, with no response. It is a
  firmware-flashing channel, not a general-purpose flash writer.

## How to work with me

**Break tasks down to verifiable steps.** Not "design a schematic", but "select a module with
at least 30 GPIO, give three options with price, JLCPCB availability, and a link to the
datasheet page with the pin table".

**Never invent numbers.** Pin numbers, register addresses, packet sizes — only from a
datasheet or from the code, with a reference to the file and line, or the PDF page. "I don't
know" is a valid answer. A pinout mistake costs a board order and three weeks of waiting.

**Separate facts from hypotheses**, and say which is which. The knowledge base maintains that
distinction; keep it up. Three conclusions in this project turned out wrong precisely because
they were reasoned rather than measured: the window offset (assumed zero, actually 34), the
sign convention in HPLX spans (backwards), and a peripheral scan that produced false positives
because it was not 4-byte aligned. Verify against hardware where you can.

**Record decisions** in `docs/DECISIONS.md`. The project runs for months with gaps, and these
files are the only memory that survives between sessions.

**Prefer editing existing tools** in `tools/` over writing new ones. They already encode the
module's quirks: reads below ~32 bytes are rejected, `READ_DATA` acknowledges by notification
but delivers the payload via a GATT read on `ff00`, and container sizes must come from the row
table rather than from width x height.

## Scope

Useful for: firmware, ZMK configs (devicetree, Kconfig, keymap), power budgets, component
selection, Python tooling, KiCad generation and checking via `kicad-cli`, DRC/ERC, BOM.

Useless or dangerous for: PCB routing, especially RF; mechanics and measurements; anything
that requires looking at a physical object.

## Environment

- Module firmware: Keil V5 **strictly version 528** (newer fails to build the SDK),
  FR8000 SDK V2.1, Python 3.8+.
- Module flashing: `FreqChip_Download` V1.3.9.1 over UART — 115200 for the boot-ROM
  handshake, 921600 for the transfer. Not shipped with the SDK; fetch it from gitee.
- Keyboard firmware: ZMK, built via GitHub Actions; no local toolchain needed.
- PCB: KiCad.
- Python tooling needs `bleak`, `pillow`, `pyserial`.
