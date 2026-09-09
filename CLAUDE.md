# Project context for the AI agent

Read this first. Then `docs/STAGE1_DISPLAY_MODULE.md`.

## Who I am and what I'm doing

Owner of a Meletrix Zoom75 TIGA. Not a professional electronics engineer. Replacing the
closed-source electronics with open ones: stage 1 — custom display module firmware,
stage 2 — custom keyboard PCB for ZMK.

## How to work with me

**Break tasks down to verifiable steps.** Not "design a schematic", but "select a module
with at least 30 GPIO, give three options with price, JLCPCB availability, and a link to
the datasheet page with the pin table".

**Never invent numbers.** Pin numbers, register addresses, packet sizes — only from
the datasheet or source code, with a reference to the file and line or PDF page. If you
don't know — say "I don't know", that's a valid answer. A pinout mistake costs a board
order and three weeks of waiting.

**Separate facts from hypotheses.** The knowledge base maintains this distinction — keep it up.

**Record decisions.** Everything decided and why goes in `docs/DECISIONS.md`. The project
runs for months with gaps; the only cross-session memory is in these files.

## Scope

Agent is useful for: firmware, ZMK configs (devicetree, Kconfig, keymap), power budget
calculations, component selection, Python scripts, KiCad generation and verification via
`kicad-cli`, DRC/ERC, BOM.

Agent is useless or dangerous for: PCB routing, especially RF sections; mechanical design
and measurements; any decision that requires looking at a physical object.

## Hardware safety rules

- Do **not touch** the stock keyboard PCB. It is the reference for continuity testing and
  the fallback path.
- Before obtaining a factory firmware dump, **do not send `OTA_CMD_CHIP_ERASE` (0x04)**
  and do not write anything to flash at all.
- The module MAC `04:75:79:FB:DD:E7` and SN are stored in flash at `0x60000` and `0x61000`.
  A full erase will destroy them.
- Do not blindly write to the OTA service `fe00`: it contains erase commands.

## Environment

- Module firmware: Keil V5 **strictly version 528**, FR8000 SDK V2.1, Python 3.8+.
- Keyboard firmware: ZMK, built via GitHub Actions — no local toolchain needed.
- PCB: KiCad.
