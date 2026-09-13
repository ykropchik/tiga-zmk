# Stage 1 — Custom firmware for the Meletrix Zoom75 TIGA display module

> Project knowledge base. Version 1.9, updated 12.09.2026 — verified the GCC-built image's
> `jump_table_t` header against the factory dump byte-for-byte: magic, size accounting and the
> `--gc-sections` question are all resolved (§Phase 2 addendum), and the build is confirmed
> toolchain-only, not flash-ready (`firmware_version=0`, undersized `image_size`, missing CRC
> signing step — see open question 21).
> Version 1.8 closed Phase 2: the Keil eval linker's ~32 KB cap (hit while building
> `ble_simple_peripheral` unchanged, `L6050U`) is bypassed by building through the SDK's own
> GCC/Makefile path instead: `arm-none-eabi-gcc` + GnuWin32 Make + Git Bash's `sh`/`rm`, full-size
> image (154 728 bytes), no license needed. Keil is no longer required to build this SDK.
> Version 1.7 stood up the Phase 2 build environment and hit that Keil license wall in the first
> place. Version 1.6 decoded all 608 resource containers to PNG, which settled how spans and
> animation runs actually work. Version 1.5 closed phase 3 by decompilation plus a live RAM read.
> Previous updates: 1.4 phase 0.5, 1.3 phase 0, 1.2 SDK and gitee material.
> Keep in the repository at `tiga-zmk/docs/`. Update as new facts are established.
> Rule: **fact** — something verified; **hypothesis** — something derived by reasoning. Do not mix them.

---

## 1. Purpose of this stage

The display module is a physically separate device inside the keyboard. It does not depend on the
main board and will survive its replacement in stage 2. Therefore it can be developed entirely
independently, on the bench, without disassembling the keyboard after the first module extraction.

### Target outcome of this stage

1. Custom firmware on the module; full control over screen rendering and layout.
2. Receiving data from the main board over UART in a custom, documented format
   (which will later allow the stage 2 ZMK board to send layer, profile, channel, battery level).
3. Ability to upload a background image / GIF (optional, does not block the stage).

### What is NOT part of stage 1

- Keyboard PCB development (that is stage 2).
- Reverse-engineering the proprietary Meletrix protocol — not needed with custom firmware.
- Reverse-engineering the PocketWuque BLE protocol — the app will not work with custom firmware.

### An important consequence to accept consciously

Custom firmware is **incompatible with PocketWuque**. The app communicates with the factory
firmware via its own GATT service. After flashing, uploading images from the phone will stop
working until you implement your own channel. If background GIFs matter more than freedom —
stage 1 is unnecessary; just leave the stock firmware and feed the module over UART in its
native format.

---

## 2. Module hardware — established facts

### 2.1 Board

| Parameter | Value | Source |
|---|---|---|
| Board ID | `RA0167CS V1.0`, date `2024.06.28` | silkscreen |
| MCU | **FREQCHIP FR8008HP**, lot `UN2574 2415 TAP` | chip marking |
| MCU crystal | 24.000 MHz | marking |
| Panel | 13-pin FPC, Hirose connector | visual |
| FPC marking | `FPC-145BJ070V4` (partially read — **verify**) | photo |
| Keyboard interface | 4 pogo pins, labelled `GND / RX / TX / VCC` | silkscreen |
| Test points | only duplicated holes next to the pogo pins | visual |
| SWD pads | **absent** | visual |
| BLE MAC | `04:75:79:FB:DD:E7` | nRF Connect |
| BLE name | `ZOOM75 TIGA` | nRF Connect |
| Pogo contacts are the bootloader UART | confirmed — module answers with `freqchip` / chip id & MAC over these pins | phase 0 experiment |
| Panel resolution | **320 × 172, RGB565, landscape** | resource catalogue, §4.5 |
| Panel interface | SPI via SSIM0 (`0x50030000` / `0x50030060`) | 4-byte-aligned literals in firmware |

> ⚠️ **Wiring:** the pogo labels are printed from the **main board's** point of view, not the
> module's. Connect straight, not crossed: adapter TX → module `TX` pin, adapter RX → module
> `RX` pin, GND → GND. The crossed ("TX to RX") wiring does not work at all. Port parameters:
> 115200 8N1, no flow control. Full detail in `docs/UART_PROTOCOL.md`.

### 2.2 MCU FR8008HP — vendor specification

| Parameter | Value |
|---|---|
| Core | ARM Cortex-M3, 96 MHz |
| Flash | **16 MB** (built-in) |
| PSRAM | 2 MB |
| SRAM | 56 KB |
| ROM | 150 KB (BLE Profile, GATT, LM, LC) |
| GPIO | 28 |
| Package | QFN40 5×5 |
| BLE | 5.3, supports Mesh and proprietary 2.4 GHz protocol |
| Peripherals | DMA, QSPI×2, SPI, UART, I2C, I2S, ADC×8, PWM×8 |
| Display interfaces | SPI, 3/2-wire D-SPI, QSPI, parallel I8080; up to 640×480 |
| OS / graphics | LVGL, FreeRTOS, RT-Thread |
| Price | ~$1.3–1.7, available on LCSC (`C7293546`) and JLCPCB |

The FR800x series is positioned by the vendor **specifically for display devices**: rotary knobs
with screens, home appliances with displays, wearables. The module is a typical application of
this chip, not an exotic use case.

### 2.3 Firmware map and addresses (from FreqChip documentation)

| What | Address |
|---|---|
| RAM start (FR800x) | `0x11000000`, size `0x4000` |
| External Flash base (J-Flash) | `0x10000000`, max `0x1000000` |
| MAC address in flash | `0x60000` |
| Serial number in flash | `0x61000` |
| BLE stack keys (default) | `0x30000` |

> ⚠️ MAC and SN are erased by a full flash erase. **MAC is recorded above — do not lose it.**
> The flashing utility can write MAC and SN back.

### 2.4 Flashing and debug pins

| Function | FR800x pin |
|---|---|
| Bootloader UART_RX | **PA0** |
| Bootloader UART_TX | **PA1** |
| J-Link CLK | PC6 |
| J-Link DIO | PC7 |

Confirmed by FR8000 Specification V1.2.0 (p. 277, IOMux table for port A):
with mux value `0x4`, **PA0 = UART0_Rx, PA1 = UART0_Tx**. Mux registers:
`PA0_MUX` / `PA1_MUX`, p. 47.

**Confirmed, phase 0:** the pogo RX/TX contacts are routed from PA0/PA1. A CP2102 adapter wired
directly to the pogo pins (115200 8N1, straight — not crossed, see §2.1) receives the boot-ROM
`freqchip` banner and chip id/MAC on power-up, which only happens if these are the bootloader
UART pins. See `docs/UART_PROTOCOL.md` for the capture.

---

## 3. UART flashing — how it works

FreqChip's official position: J-Link does not always work with BLE-stack chips (cannot connect
if the chip is asleep or SW pins are remapped), **so serial flashing and debugging are
recommended**. The absence of SWD pads on the module is an expected situation, not a problem.

### Mechanism

On power-up the internal ROM boot program attempts to communicate with the PC utility over UART.
After the handshake, flash writing becomes available.

**Confirmed experimentally, phase 0:** connecting a CP2102 adapter directly to the pogo pins
(115200 8N1, straight wiring, see §2.1) and powering the module reproduces this exactly — the
`freqchip` banner and chip id/MAC print about 2.3 s after power-up, byte-for-byte reproducible
across power cycles. Full capture and timing in `docs/UART_PROTOCOL.md`.

### Parameters

| Parameter | Value |
|---|---|
| Bootloader handshake baud rate | **115200** |
| Actual flashing baud rate | **921600** |
| Sign of a live chip | on reset the string **`freqchip`** is printed to the port |
| Family in the utility | **FR800X** (covers FR8008 and FR8003) |

### Utility

`FreqChip_Download_New.zip` — at the root of `https://gitee.com/YgqMars/freqchip`.
Current version is **V1.3.9.1** (2025-03-18), newer than the V1.3.8 described in the guide.

Archive contents: `FreqChip_Download.exe` (GUI), **`FreqChip_Download_Consle.exe`** (console
build — suitable for scripting and automation), `FrDownloadSdk.dll` v1.4.5, `setting.ini`.

`setting.ini` confirms the MAC address location in flash (`MAC_FLASH=0x60000`) and exposes the
configuration keys: `Chip_Type`, `Flash_Select`, `uart_port`, `Baud_Rate`, `Auto_Burn`,
`Auto_Reset`, `MAC_BASE`.

> ⚠️ **The SDK V2.1 does NOT include a flashing utility.** The `tools/` folder contains only
> `FR8000.FLM` (flash algorithm for Keil/J-Flash) and `JLinkDevices.xml`. Download the
> utility separately via the link above.

Procedure: select FR800X → load bin → check "auto-flash" and "auto-restart" →
"open firmware" → reset the module → handshake happens automatically.
The "Options" menu has entries for writing MAC, SN, specifying a file, erasing the OTA region,
and flash protection.

> ⚠️ The utility writes but **does not read**. It cannot dump the factory firmware.

### 3.1 Serial OTA — a second, gentler write path

Besides flashing through the boot ROM (a full flash rewrite), the FR8000 has a **stock OTA over
UART**, documented separately in `FR800x/FR8000-串口-ota_V1/升级协议文档.pdf`.

The key statement in that document: the upgrade procedure is **identical across UART, USB and
other channels** — the same opcode set we found over BLE, only the transport differs.

Shipped alongside it: `fr8000-master-0.4.10.7z` (an SDK variant with serial OTA support) and
`串口OTA工具（上位机）.7z` (the PC-side utility).

**Practical implication:** if the factory firmware was built with serial OTA (and we already know
it was built with BLE OTA), the module can also be written over the wire using the same protocol,
without touching the boot ROM and without risking the bootloader.

### 3.2 AT commands and transparent mode

`FR800x/FR8000串口透传指令与使用说明.pdf` documents the SDK's stock AT interface.

Default port parameters: **115200, 8N1, no parity**.
Format: `AT+<CMD>[op][params]<CR><LF>`; response `<CR><LF>+<RSP>[params]<CR><LF>`, where RSP is
`OK` or `ERR`.

Useful commands:

| Command | Action |
|---|---|
| `AT+CIVER?` | software version — **the safest probe** |
| `AT+NAME?` / `AT+NAME=` | device name (1–17 bytes) |
| `AT+MAC?` / `AT+MAC=` | MAC address |
| `AT+MODE?` / `AT+MODE=` | mode: `I` idle, `M` link, `B` advertising, **`U` upgrade**, `X` error |
| `AT+UART?` / `AT+UART=` | port parameters |
| `AT+LINK?` | connection state |
| `AT+SLEEP=S/E` | enter / stop sleep |
| `AT+Z` | reboot |
| `+++` | enter transparent mode |
| `AT+FLASH` | persist settings to flash |
| `AT+CLR_BOND` / `AT+CLR_INFO` | clear bonds and stored settings |

**Rejected, phase 0:** tested directly against the pogo lines — `AT+CIVER?` and other AT commands
get no response. The module's application firmware is not built on this AT/transparent-mode
example; it speaks its own binary framed protocol instead (`A5`-prefixed frames with a checksum),
captured and partially decoded in `docs/UART_PROTOCOL.md`.

Worth noting separately: `AT+MODE=U` puts the module **into upgrade mode**. If it answers AT at
all, that is another entry point into flashing, in addition to the boot ROM.

---

## 4. Factory firmware — what is known

### 4.1 Architecture (reconstructed, confirmed by observation)

The module has **two independent communication channels**:

- **UART to main board** — live data: Win/Mac mode, active channel, battery level,
  page-scroll commands (Fn+PageUp/PageDown, Fn+Enter, Fn+Delete).
- **BLE to phone** — image and GIF upload via PocketWuque, plus firmware OTA.

Verified: when the module is removed, the BLE device `ZOOM75 TIGA` disappears from the air →
the radio is in the module, not in the keyboard.

### 4.2 Factory firmware GATT — cross-checked against SDK source

Device is **NOT BONDED** — connects without pairing or encryption.

**Service `02f00000-0000-0000-0000-00000000fe00`** is the **standard OTA profile from the SDK**,
`components/ble/profiles/ble_ota/`. Byte-for-byte match, nothing left to guess:

| UUID on air | Constant in `ota_service.h` | Properties | Purpose |
|---|---|---|---|
| `...fe00` | `OTA_SVC_UUID` | — | service |
| `...ff00` | `OTA_CHAR_UUID_TX` | READ | TX |
| `...ff01` | `OTA_CHAR_UUID_RX` | WRITE, WRITE NO RESP | receive commands |
| `...ff02` | `OTA_CHAR_UUID_NOTI` | NOTIFY, READ | responses, `ntf_enable` descriptor |
| `...ff03` | `OTA_CHAR_UUID_VERSION_INFO` | READ | firmware version |

**Conclusion: the module runs firmware built from this very SDK with the stock OTA profile.**
This means the full documented set of flash operations — including reading — is available over BLE.

**Service `1f40eaf8-aab4-14a3-f1ba-f61f35cddbaa`** is the PocketWuque application protocol,
written by Meletrix/Wuque on top of the SDK:

| Characteristic | Properties | Hypothesized purpose |
|---|---|---|
| `1f400001` | WRITE, WRITE NO RESP | command channel |
| `1f400002` | NOTIFY | command responses |
| `1f400003` | WRITE, WRITE NO RESP | data channel (images) |
| `1f400004` | NOTIFY | transfer progress |

### 4.3 OTA protocol — exact opcodes from `ota.h`

Request (to `ff01`): `Opcode(1) | Length(2, LE) | Payload`
Response (on `ff02`): `Result(1) | Opcode(1) | Length(2, LE) | Payload`

| Opcode | Constant | Action |
|---|---|---|
| `0x00` | `OTA_CMD_NVDS_TYPE` | NVDS type (none / flash / eeprom) |
| `0x01` | `OTA_CMD_GET_STR_BASE` | storage base address |
| `0x02` | `OTA_CMD_READ_FW_VER` | firmware version (uint32) |
| `0x03` | `OTA_CMD_PAGE_ERASE` | erase page, payload = `base_address` (uint32) |
| `0x04` | `OTA_CMD_CHIP_ERASE` | ⚠️ full erase |
| `0x05` | `OTA_CMD_WRITE_DATA` | write to flash: `base_address`(4) + `length`(2) + data |
| `0x06` | **`OTA_CMD_READ_DATA`** | **read flash: `base_address`(4) + `length`(2)** |
| `0x07` | `OTA_CMD_WRITE_MEM` | write to memory |
| `0x08` | **`OTA_CMD_READ_MEM`** | **read memory** |
| `0x09` | `OTA_CMD_REBOOT` | reboot |

Result codes: `0x00` success, `0x01` error, `0x02` unknown command.

#### Clarifications from `升级协议文档.pdf` (FR8000; applies to both BLE and UART)

**A/B ping-pong banking.** Bank A starts at address `0`, bank B starts at `image_size`.
`image_size` is set by the device firmware with headroom: if the code occupies 90 KB, one might
declare 100 KB, putting bank B in the 100–200 KB range. Command `0x01` returns the address of the
bank **the new firmware should be written to** — either `0` or `image_size`.

**Erase (`0x03`) works in 4 KB units.** Loop from the returned base address, `+0x1000` each time,
until enough space for the whole bin has been erased.

**Write (`0x05`)**: `base_addr(4) | packet_len(2) | data`. The header length field equals
`packet_len + 6`. Packet size is chosen by the host. The address advances by `packet_len` each
iteration. Response: `base_addr(4) | len(2)`, header length field `0x0006`.

**Reboot (`0x09`)**: payload = `bin_length(4) | CRC(4)`, header length field `0x0008`.
⚠️ **The CRC is computed over the file WITHOUT its first 256 header bytes.** The device verifies
the CRC first and only then reboots. This — not MD5 — is the correct variant for the FR8000.

Observed length-field values: `0x0004` for commands with a 4-byte payload, `0x0008` for reboot.
Byte order is little-endian.

Implementation detail (`ota.c`): if a read response does not fit into `OTAS_NOTIFY_DATA_SIZE`,
the module does not send it as a notification; instead it saves the request and waits for the
client to retrieve the data via a **GATT Read** on the characteristic. This must be handled in
your client.

Also in `ota.c`: long commands are reassembled — if the application splits a packet across MTU
chunks, the module accumulates them in a buffer until the expected length is reached. So you can
write in MTU-sized pieces.

Firmware is stored in **two banks**; the boot selects by version number — hence the prohibition
on downgrade and re-flashing the same version.

### 4.4 Vendor firmware naming scheme

`<Model>screen_OTA_<moduleID>_<modelCode>_V<version>_<timestamp>.bin`

| Board | Module ID | Code | Example |
|---|---|---|---|
| Zoom75 (2023) | `BA0009CS` | `0XC003` | `Zoom75screen_OTA_BA0009CS_0XC003_V000148_202307072353.bin` |
| Zoom98 | `BA0054CS` | `0XC013` | `Zoom98screen_OTA_BA0054CS_0XC013_V00014C_202308181735.bin` |
| **TIGA** | `RA0167CS` (from silkscreen) | ? | no file in public access |

> No factory firmware for the TIGA exists publicly — the Meletrix archive contains only the
> 2023 Zoom75 and Zoom98. `OTA_CMD_READ_DATA` over BLE is the SDK-documented way to read it back,
> but **it is not yet confirmed that the factory build actually implements this opcode** — the
> flashing utility only ever writes, never reads, so nobody has exercised this path on this
> module. See phase 0.5 for the planned check and both possible outcomes.

---

### 4.5 Resource format — `HPLX` containers

Images and animations live in flash **above the firmware banks**, in a chain of containers that
starts at `0x80000` and ends at `0x929940` — **608 containers, ~8.7 MB**.

Container layout:

```
+0x00  "HPLX"                    magic
+0x08  width         uint32 LE
+0x0C  height        uint32 LE
+0x20  table_offset  = 0x28              relative to container start
+0x24  data_offset   = 0x28 + height*8   relative to container start
```

The row table holds `height` entries of `(row_offset, row_size)`, uint32 LE, relative to
`data_offset`. **Each row is a list of spans**, not a raw scanline:

```
<x_start : uint32 LE> <byte_len : int32 LE> <pixel data>
```

**`byte_len` is signed, and its sign selects the pixel encoding** (`FUN_1000a03c`, `0x1000A1BE`):

| Sign | Bytes per pixel | Meaning |
|---|---|---|
| positive | 2 | plain RGB565, copied straight over the destination |
| negative | 3 | RGB565 + an 8-bit alpha in the third byte, blended with the destination |

For negative values the actual byte count is `byte_len & 0x7FFFFFFF`. The firmware feeds the
alpha to `FUN_100185b0` after shifting it right by 3, i.e. it blends at 5-bit precision.

**Alpha is the common case, not the exception: 509 of the 608 containers use it.** The Meletrix
boot animation happens to use only literal spans, which is why an alpha-blind decoder looks
correct at first and silently corrupts everything else.

A full row is a single span with `x_start = 0` and `byte_len = width*2`.

Practical notes, all learned the hard way:

- Container sizes are **variable**. Compute the end from the row table (`data_offset +
  max(row_offset + row_size)`), never from `width × height`.
- Containers are padded with `0xFF` up to a 4-byte boundary, and the last row's `size` field
  sometimes under-reports its final span. Verify the `HPLX` magic at the computed next address
  and resync forward if it is missing.
- Pixels are RGB565 little-endian, row-major. No palette, no entropy coding.

### Animation runs versus standalone sprites

Containers group into **152 runs** of consecutive same-size entries, and a run is one of two
things. Telling them apart matters: treat a sprite set as an animation and every glyph gets
drawn on top of the previous one.

The discriminator is the **first container of the run**:

- coverage > 90% → the run is an **animation**. The first frame is full, the rest are deltas;
  composite each onto the previous.
- coverage below that → the run is a **set of standalone sprites**. Clear the canvas before
  each one.

Coverage means the fraction of the container's area actually touched by its spans.

By this rule: **5 animation runs totalling 120 frames, and 147 sprite runs totalling 488
standalone images.** The animations are the Meletrix boot logo (31 frames), a cat (26), a
120 × 146 widget (41), and two single full-screen frames.

Note that per-container coverage alone is not enough — a digit does not fill its own box, so it
scores low despite being standalone. The decision has to be made once per run.

Catalogue of the 608 containers. Notable groups:

| Size | Count | What it is |
|---|---|---|
| 320 × 172 | 88 | **full-screen frames** — four separate runs, one of 85 frames |
| 120 × 146 | 41 | large widget animation |
| 320 × 80 | 31 | Meletrix boot logo with a travelling highlight |
| 44 × 38 | 28 | icons |
| 154 × 120 | 26 | cat animation |
| 170 × 160 | 26 | widget animation |
| 106 × 50 | 20 | panel strips |
| 46 × 46 | 18 | icons |
| 320 × 98, 260 × 60, 238 × 50, 232 × 74 | few each | banners and strips |
| 10 × 15, 12 × 20, 16 × 26, 8 × 16, 32 × 16 … | groups of 10–16 | **glyph sets — digits 0–9 in several point sizes** |

### What the library actually contains

Decoding everything to PNG made the structure obvious. The UI is **assembled from sprites, not
drawn by code**:

- **Digit sets in several styles and point sizes** — dense white, thin light, grey, cyan, and a
  slashed-zero variant. Plus separate sprites for `:`, `-`, `.`, `/`, `~` and `%`.
- **Units as ready-made images**: `°C`, `°F`, `CPU`, `RPM`, `MBPS`, `mbps`.
- **Icons**: battery in several states, a CPU die, a sun, a toggle switch, the `Aa` layout
  indicator, frames and divider strips.
- **Chinese page headings** 风格 ("Style") and 数据 ("Data") — menu pages. The duplicate glyph
  sets in different colours are the themes that page switches between.
- **Animations**: the Meletrix logo, a cat, a white dog, a lion cub, orange rays.

**Consequence, and it is a useful one:** because the interface is sprite-based, its appearance
can be changed by replacing images alone — no custom firmware needed. Swap the glyphs and the
digits on screen change; swap the icons and the indicators change. Encoding a PNG back into
`HPLX` is the exact inverse of the decoder and is a few dozen lines of Python.

Tooling: `tools/hplx_grab.py` walks the chain and downloads every container, resumably;
`tools/hplx_decode.py` converts a directory of containers to PNG, handling both span encodings
and both run types, and emits RGBA so alpha survives.

### 4.6 Flash map (16 MB, probed at 64 KB steps)

| Range | Contents |
|---|---|
| `0x000000` – `0x032000` | firmware bank A (code ends at `0x25988`, ~154 KB) |
| `0x032000` – `0x064000` | firmware bank B, identical image |
| `0x064000` – `0x080000` | erased gap |
| `0x080000` – `0x929940` | **`HPLX` resource chain, 608 containers, ~8.7 MB** |
| `0x929940` – `0xFFFFFF` | erased, ~6 MB free |

Only **one** firmware header (magic `33333333` at `+0x08`) exists in the whole flash — there is
no second application. All rendering happens inside the ~154 KB image that was dumped.

Tooling: `tools/ota_scan.py` produces this map.

---

## 5. What needs to be done — stage plan

### Phase 0. Access confirmation (blocking) — ✅ done, 09.09.2026

- [x] Buy a **3.3 V** USB-UART adapter — used a CP2102
- [x] Connect: GND↔GND, adapter TX → module `TX` pin, adapter RX → module `RX` pin
      (**straight, not crossed** — see wiring warning in §2.1; the crossed variant does not work)
- [x] Terminal at **115200 8N1**, no flow control, apply power to the module
- [x] **Success criterion met: `freqchip` appears in the port**, ~2.3 s after power-up, followed
      by chip id and MAC (reversed byte order, matches the known `04:75:79:FB:DD:E7`)
- [x] Tried `AT+CIVER?` and other AT commands — **no response**. Module does not speak the AT
      example; it runs its own binary framed protocol, captured passively and partially decoded
      in `docs/UART_PROTOCOL.md`
- [x] Pogo contacts confirmed as PA0/PA1 (bootloader UART) — no soldering to QFN-40 needed

**Result: the module can be flashed over UART through the pogo pins alone.** No soldering to the
QFN-40 package is required for stage 1 firmware development. This is the key unblock for the
whole stage.

### Phase 0.5. Factory firmware backup — ✅ DONE, 10.09.2026 (Outcome A)

**Result: `OTA_CMD_READ_DATA` is implemented in the factory build. Both banks are dumped.
The "no rollback" risk is eliminated.**

Probe responses:

| Command | Response payload | Meaning |
|---|---|---|
| `02 00 00` `READ_FW_VER` | `01 00 00 00` | firmware version = **1** |
| `00 00 00` `NVDS_TYPE` | `11` | `0x11` — not a value in the SDK enum, see open questions |
| `01 00 00 00` `GET_STR_BASE` | `00 20 03 00` | storage base = **`0x00032000`** |

Two implementation details that cost time and are easy to hit again:

**The `READ_DATA` notification is only an acknowledgement.** It echoes back `base_addr` and
`length` with result `0x00`. The payload itself must be fetched with a plain **GATT Read on
`...ff00`** afterwards. Waiting for the data to arrive as a notification will time out forever.

**The module rejects reads below roughly 32 bytes.** An 8-byte request fails outright. Always
request at least 32 bytes and trim the result.

Dumps taken:

| Bank | Address | Size | sha256 (short) |
|---|---|---|---|
| A | `0x00000` | 204 800 | `328439b6b26bd3f2` |
| B | `0x32000` | 204 800 | `2bdd6ed5dfa04173` |

Both banks hold **the same firmware**. The only difference is the gap between the header and the
code (`0x64`–`0x2000`): `0xFF` in bank A, zeros in bank B. Bank A was written on the production
line via the UART utility, which skips blank pages; bank B was written via OTA, which stores the
file verbatim. Version is 1 in both, so the unit was never updated by a user and no older image
exists for comparison.

Two independent reads of the same firmware from different flash regions agreeing byte for byte
is the strongest available validation that the read path is correct.

> ⚠️ `0x60000` — the MAC location per the flashing utility's `setting.ini` — reads back as all
> `0xFF`. **The MAC is not stored there in this build.** It presumably lives in eFuse or NVDS.
> Since its real location is unknown, a chip erase may be unrecoverable. Do not use `0x04`
> (`CHIP_ERASE`), and do not touch the utility's "Flash Protect" menu entry — it is a toggle
> that *sets* protection, not an indicator that reports it.

Tooling used: `tools/ota_probe.py` (safe probes), `tools/ota_dump.py` (flash range dump),
`tools/ota_readmem.py` (live RAM reads via `READ_MEM` 0x08, and flash with `--flash`).

### Phase 1. Capture the factory UART protocol (do BEFORE reflashing)

While the stock firmware is alive, this is the only chance to see how the main board talks
to the module.

- [ ] Insert module in keyboard, solder onto main board TX line (listen only)
- [ ] Record traffic on: power-on, channel switch (Fn+Z/X/C/V), Fn+Space,
      Fn+Q / Fn+W, Fn+PageUp/PageDown, Fn+Enter, Fn+Delete, charger connect
- [ ] Match events to packets, document in `docs/UART_PROTOCOL.md`

Why bother if the firmware will be custom: first, it is a ready working format that can simply
be reused in stage 2; second, it is insurance — if the custom firmware fails, the fallback is
"stock + custom UART master".

### Phase 2. Development environment

- [x] **SDK obtained: `fr8000_sdk_V2.1`** (see section 7.1 — contents), local copy in
      `firmware/display-module/vendor/sdk_V2.1/`
- [x] Downloaded: `FR800x_Datasheet_v0.3.19.pdf`, `FR800x+Specification+V1.2.1.pdf`,
      `FR800x+Hardware+Manual_+V1.4.pdf`, `FR8000+SDK+User+Guide+V1.1.pdf` (plan called for V1.0,
      vendor site now serves V1.1 — newer, not a mismatch), `FR800x_RD_V1.1_20230923/` (schematics
      and footprints, 9 reference designs). All in `hardware/datasheets/`.
      ⚠️ The RD folder ships one PDF per die variant (`FR2012B`, `FR2012B-M`, `FR8003A`,
      `FR8003A-R`, `FR8003D`, `FR8008A`, `FR8008AP`, `FR8008G`, `FR8008XP`) — none named literally
      `FR8008HP` (the module's marking, §2.1). Not yet resolved which file (if any) actually
      matches; PDF text is glyph-index encoded and unreadable without `poppler-utils` for
      rendering. Does not block firmware work, only hardware reference — see open question 19.
- [x] **Keil V5 version 528 installed**, confirmed via `UV4.exe` file version `5.28.0.0`
      (newer versions do not compile the SDK — confirmed by the vendor)
- [x] CMSIS pack `ARM.CMSIS.5.9.0.pack` downloaded (in `vendor/freqchip/`), **not yet registered**
      in Keil's Pack Installer (only `5.5.1` shows as cached). Did not block compilation in the
      toolchain check below — this SDK's CMSIS headers are bundled under
      `components/modules/platform/include/cmsis`, not sourced from the official ARM pack.
- [x] Python 3.8+ — already present on the machine (3.14.7), no action needed
- [x] `FreqChip_Download_New` V1.3.9.1 from `gitee.com/YgqMars/freqchip` — in `vendor/freqchip/`
- [x] Built `ble_simple_peripheral` unchanged via `UV4.exe -b` — **compiled clean, failed at link**:
      `L6050U: The code size of this image (106660 bytes) exceeds the maximum allowed for this
      version of the linker.` This is the standard Keil eval/lite cap (~32 KB) — Keil V5.28 here
      has no commercial license. Since a factory firmware bank is ~154 KB (§4.6), this blocked any
      non-trivial build, not just this example.
- [x] **Resolved, 12.09.2026 — toolchain switched to GCC, Keil license question closed.**
      Installed `arm-none-eabi-gcc` 15.3.1 (`D:\Program Files\Arm\GNU Toolchain
      mingw-w64-x86_64-arm-none-eabi\bin`) and GnuWin32 Make 3.81
      (`D:\Program Files (x86)\GnuWin32\bin`). Built the same `ble_simple_peripheral` unchanged via
      the SDK's own `examples/.../gcc/Makefile` — **succeeded end to end**, no size cap:
      `fr8000_project.bin` is 154 728 bytes (`text 144188, data 2448, bss 6244`), in the same range
      as a real factory firmware bank (§4.6). Only linker warnings, no errors — unimplemented
      newlib syscall stubs (`_close`/`_fstat`/`_isatty`/`_lseek`/`_read`, unused by this example)
      and "Forcing branch to absolute symbol" from the prebuilt `libfr800x_stack.a` (normal for a
      vendor-supplied `.a` linked into Thumb code).
      GnuWin32 Make has no `sh`/`rm` of its own — the Makefile's `$(shell mkdir ...)` and
      `make clean`'s `rm -rf` both need a real POSIX shell on PATH, supplied here by Git Bash's
      `C:\Program Files\Git\usr\bin`. Without it, `Objects/` never gets created and the first
      compile fails with "No such file or directory".
      **Keil is no longer required to build this SDK** — GCC is the toolchain going forward. CMSIS
      pack registration in Keil (open above) is moot for the same reason.

#### Phase 2 addendum — GCC image structure verified against the factory dump (12.09.2026)

Compared the first 64 bytes of `fr8000_project.bin` (our GCC build) against
`docs/factory_dump/dump_0x0_0x32000.bin`. The `33 33 33 33` magic at +0x08 is present in our
build and lines up byte-for-byte with the factory header's field layout.

**The header is not appended by any flashing tool — it is compiled in**, as
`struct jump_table_t` (`components/modules/platform/include/jump_table.h:191-245`), assembled by
the linker from **two different sources**, confirmed by `fr8000_project.map:3853-3868` and
`objdump -h`:

| Field(s) | Flash offset | Comes from |
|---|---|---|
| `reserved_data` | +0x00 | `libfr800x_stack.a(jump_table_host.o)` — vendor blob, **not our code** |
| `image_size`, `image_type` | +0x04 | `examples/.../code/proj_main.c:46-50` (`_jump_table_image`) |
| `entry`, `memory_init_app` | +0x0C | vendor blob |
| `stack_top_address`, `firmware_version` | +0x14 | `proj_main.c:40-44` (`_jump_table_version`) |
| everything after (`system_option`, sleep timings, etc., 0x48 bytes) | +0x1C | vendor blob |

This explains why fields like `system_option` (+0x2C) and the sleep-timing constants are
byte-identical between our unmodified example and the real factory dump — they come from the
same precompiled `libfr800x_stack.a`, shared by every project built on this SDK, not recomputed
per project.

Two fields differ from the factory image, both traced to `proj_main.c`'s unmodified example
defaults, **not bugs in the build**:

- `firmware_version` (+0x18): factory = `1`, ours = `0` — set literally as
  `.firmware_version = 0x00000000` at `proj_main.c:43`. Per the hardware safety rule (CLAUDE.md),
  a real custom image must set this above 1 or the boot loader won't select it.
- `image_size` (+0x04): factory = `0x30000` (matches the bank boundary at `0x32000`, §4.3), ours =
  `0x20000` — set as `.image_size = 0x20000` at `proj_main.c:49`, a template placeholder. Our
  actual compiled `.bin` (154 728 bytes) is **larger** than this self-declared value (131 072) —
  harmless for a toolchain smoke test, but this field must be raised to match reality (with
  headroom) before it means anything for real OTA bank math.

**Open gap, not yet resolved:** `jump_table.h:247-260` carries (Chinese-language) comments stating
that `jump_table_crc` and `image_crc` — a *separate* struct, `image_crc_t`, appended after
`jump_table_t` — are computed by an external script run after the Keil build finishes, not by the
compiler. No such script was found anywhere in `sdk_V2.1` or `vendor/freqchip`, and the example's
own Keil project only runs `fromelf` in its post-build steps (`ble_simple_peripheral.uvproj:81-86`)
— no CRC patching. **Neither our GCC build nor a vanilla Keil build of this example produces a
CRC-signed image.** Whether the boot loader requires this stamp to accept an image is unconfirmed
— see open question 21.

**Size accounting**, verified with `objdump -h` (not inferred): `.jump_table` ends at flash offset
`0x64`; the linker script aligns `.text` to the next `0x2000` boundary
(`components/toolchain/gcc/ldscript.ld:50`), so `0x1F9C` (8092) zero-filled bytes sit between them
— this, not `--gc-sections` dropping anything, accounts for the gap between `size`'s
`text+data` (146 636) and the actual `.bin` (154 728). All `jump_table_0`–`4` sections carry
`KEEP()` (`ldscript.ld:34-38`) specifically to survive `--gc-sections`; the link produced zero
"undefined reference" errors, meaning every one of the ~102 vendor-library symbols pulled in
resolved cleanly. Minor, unrelated inefficiency spotted in passing: `stack_section` (the 2 KB
`system_stack` array) has no dedicated `NOLOAD` rule in the linker script, so it physically
occupies 2 KB of the `.bin` as zero padding instead of living only in `.bss` — free to reclaim in
a real build, not fixed here.

**Warning survey**, full clean `make clean && make` log (1468 lines, zero errors, zero warnings
from our own 6 source files): all 1443 warning lines fall into exactly three buckets —
1437 "Forcing branch to absolute symbol in Thumb mode" across 102 distinct vendor-library symbols
(`jump_table.h:284-293` declares the BLE stack's entry points as function-pointer externs assigned
absolute addresses, not ordinary relocatable symbols — GCC 15.3's linker is simply more vocal
about this than whatever shipped with the SDK originally; the link still resolved every one of
them, no missing symbols), one "LOAD segment with RWX permissions" (routine for a bare-metal
linker script with no ELF segment-permission split), and 5 unimplemented-newlib-syscall notices
(`_close`/`_fstat`/`_isatty`/`_lseek`/`_read` — unused by this example; `_write` is retargeted
elsewhere, since it's absent from the list). None of the three categories looks like a real
toolchain-version regression.

### Phase 3. Panel identification — ✅ DONE (10.09.2026)

Answered entirely by decompilation in Ghidra plus one live RAM read. No logic analyser needed.

**Controller: ST7789 or fully compatible.** `FUN_10014ed8` emits three commands:

```c
local_28 = 0x2a0002;   /* 0x2A — Column Address Set */
local_28 = 0x2b0002;   /* 0x2B — Row Address Set    */
local_20 = 0x2c0002;   /* 0x2C — Memory Write       */
```

Coordinates are assembled high byte first via `CONCAT11`, i.e. **16-bit big-endian**, exactly as
the ST77xx family specifies.

**Visible area: 320 × 172, RGB565, landscape.** Confirmed three ways: the resource catalogue
(§4.5) caps at 320 × 172; the window is set with `thunk_FUN_10014ed8(0, 0x13f, 0, 0xab)`; and each
framebuffer is cleared with length `0x1AE00` = 320 × 172 × 2 = 110 080 bytes.

**⚠️ The panel is offset by 34 rows.** `FUN_10014ed8` adds two globals to the window origin:
`_DAT_11003936` to X and `_DAT_11003938` to Y. Neither is ever written anywhere in the firmware,
so they were assumed to be zero — **wrong**. Read live from the module with
`tools/ota_readmem.py 0x11003934 16 --u16`:

```
11003934  01 01 00 00 22 00 00 00 ...
  +0x02  0x0000   X offset  = 0
  +0x04  0x0022   Y offset  = 34
```

So the underlying die addresses 240 rows and the visible strip of 172 is centred:
(240 − 172) / 2 = 34. This is an ordinary **1.47" 172×320 ST7789 module used in landscape**,
not a custom 320 × 172 panel.

**In custom firmware the window must be set as `columns 0..319, rows 34..205`.** Starting rows at
zero shifts the image up by 34 lines and leaves garbage along the bottom edge.

Other fields in that struct: `+0x00` is the busy flag checked in `FUN_10019f44`; `+0x01` and
`+0x0C` are set to 1, purpose unknown.

**Pinout on the MCU side**, from `FUN_10014d84` via the GPIO configurator
`FUN_100151a0(port, {mask, mode, pull, function})`:

| Signal | Pin | Configuration |
|---|---|---|
| UART to main board | PA0, PA1 | UART0 |
| Panel RST | PA2 | output (`mode 0x1001`) |
| unidentified input | PA3 | input (`mode 0x1000`) — likely TE |
| Panel DC | PA4 | output |
| Panel CS | PA5 | output |
| SPI to panel | PB0, PB2, PB3, PB4, PB5 | alternate function 2 |

Mode encoding: `0x1000` sets the direction bit (input), `0x1001` clears it (output), `2` writes a
4-bit alternate-function code into the mux register at `bit*4`. Levels are driven by
`FUN_1001549c(port, mask, level)` writing to `0x50060000 + port*4`.

**Reset sequence:** RST high, delay `0x4B0`, RST low, delay `0x4B0`, RST high — issued after SPI
and DMA are already up.

**Frame transfer** (`FUN_10019f44`) — the part worth copying:

- Two full framebuffers of 110 080 bytes, `_DAT_110038A0` and `_DAT_110038A4`. They cannot fit in
  the 56 KB SRAM, so they live in **PSRAM**.
- A frame goes out as **seven chained DMA descriptors**: source advances 16 000 bytes per block,
  4000 elements of 4 bytes each, with the last block taking the exact remainder.
- Destination is `0x50030060`, the SSIM0 data register — the literal that surfaced in the very
  first peripheral scan.
- Descriptors are linked (`next = 0x11007500 + i*0x14`), so the whole frame is pushed
  scatter-gather with no CPU involvement.
- CS (PA5) is held low for the duration of the transfer.
- DMA registers are at `0x200200xx`, stride `0x58` per channel, **channel 0**. Enabled in
  `FUN_10014d34`, which also sets `NVIC_ISER0 = 2` (IRQ 1).
- `FUN_1001e19c` swaps the buffers after each frame; `FUN_1001e500` is merely the setter for the
  active framebuffer pointer.

**Blitting** (`FUN_1000a03c`, reconstructed in `research/hplx_blit_reconstructed.c`): spans have
two encodings selected by the sign bit of `byte_len` — clear means 2 bytes per pixel copied
straight, set means **3 bytes per pixel with a 5-bit alpha** blended via `FUN_100185b0`.

> ⚠️ Our HPLX decoder in `tools/` only handles the 2-byte literal case. Containers using alpha
> spans decode incorrectly and we would not notice — the boot animation happens to use literal
> spans only. See open question 15.

Not needed, and deliberately dropped: mapping the 13-pin FPC to individual signals. The module
stays intact, so the panel wiring is internal to its board. That only matters if the panel is
ever detached or replaced.

Still open:

- [ ] The one-time ST7789 init sequence (`0x11`, `0x36`, `0x3A`, `0x29`) has not been located.
      The standard sequence can be used instead and tuned against the live panel.

### Phase 4. Custom firmware

- [ ] Panel driver on top of the SDK
- [ ] LVGL (supported by vendor, examples in SDK and on forum)
- [ ] UART command reception, custom format
- [ ] Screens: layer, BLE profile / channel, battery, Caps Lock, Win/Mac mode
- [ ] Power management: idle screen-off, sleep
- [ ] Optional: custom image upload channel (BLE or UART), stored in flash

Reference: `lvgl_knob_open_demo-master.zip` in `gitee.com/a18562560220/freqchip_faq` —
an open-source "knob with LVGL display" demo project on this exact chip family.

---

## 6. Risks

| Risk | Probability | Consequence | Mitigation |
|---|---|---|---|
| ~~Keil V5.28 has no commercial license~~ | **Eliminated** | — | Switched the build to the SDK's own GCC/Makefile path (`arm-none-eabi-gcc` + GnuWin32 Make + Git Bash's `sh`/`rm`); `ble_simple_peripheral` now builds full-size (154 728 bytes), no cap. Keil is no longer needed to build this SDK |
| ~~No rollback to stock~~ | **Eliminated** | — | Both banks dumped over BLE in phase 0.5; images in `docs/factory_dump/` |
| ~~Dump capture fails~~ | **Eliminated** | — | `READ_DATA` is implemented in the factory build |
| MAC not recoverable after a chip erase | **High** | Module permanently loses its identity | MAC is **not** at `0x60000` (reads `0xFF`) — real location unknown. Never use `CHIP_ERASE`. Known value for reference: `04:75:79:FB:DD:E7` |
| ~~Pogo contacts are not PA0/PA1~~ | Resolved | — | Confirmed PA0/PA1 in phase 0 — boot-ROM handshake works directly on the pogo pins |
| Panel bonded COG / FPC non-detachable | Low | Cannot reuse panel separately | Hirose connector is visible — risk is low |
| Cheap USB-UART cannot sustain 921600 | Medium | Flashing fails | Use CP2102 / CH343 |
| ~~Flash is read-protected~~ | **Eliminated** | — | `READ_DATA` returns real code and data |
| Flash is write-protected | Low | Flashing impossible | Unknown until the first write. **Do not touch the utility's "Flash Protect" entry** — it is a toggle that *sets* protection, not an indicator |
| Loss of PocketWuque | 100% | No image upload from phone | Conscious decision; custom channel in phase 4 |

---

## 7. Resources

### 7.0 Contents of `gitee.com/YgqMars/freqchip` (obtained, reviewed)

Unofficial but unusually substantial. Root:

| File | What it is |
|---|---|
| `FreqChip_Download_New.zip` | flashing utility V1.3.9.1, GUI + console |
| `FREQCHIP_OTA_V1.2.0.zip` | OTA host application |
| `ARM.CMSIS.5.9.0.pack` | Keil pack |
| `富芮坤芯片入手资料获取和使用.pdf` | how to obtain vendor material and use the flasher |
| `FR8000 OTA sleep profile.docx` | OTA combined with sleep |
| `FR8000_串口DMA不定长接收处理.pdf` | receiving variable-length UART packets via DMA |

`FR800x/` directory:

| File | What it is |
|---|---|
| `FR8000-串口-ota_V1/升级协议文档.pdf` | **the complete OTA protocol** (analysed, see 4.3) |
| `FR8000-串口-ota_V1/fr8000-master-0.4.10.7z` | SDK variant with serial OTA |
| `FR8000-串口-ota_V1/串口OTA工具（上位机）.7z` | serial OTA PC utility |
| `FR8000串口透传指令与使用说明.pdf` | **AT commands and transparent mode** (see 3.2) |
| `FR8000_usb_ota参考（io口复用为usb）.7z` | OTA over USB, IO multiplexing |
| `FR800系列SDK讲解.pdf` | SDK walkthrough |
| `FR800x提升RF脚ESD能力_1208.pdf` | ESD protection for RF pins |
| `fr8000u_sdk1.1_4983bf6_Power.7z` | SDK for the -U series |
| `过认证/FR800x_HCI_PA0_PA1认证测试V1.0.4.zip` | certification tests — **PA0/PA1 right in the filename**, further confirmation that this is the stock UART pair |

### 7.1 Contents of `fr8000_sdk_V2.1` (obtained, reviewed)

```
fr8000_sdk_V2.1/
├── components/
│   ├── ble/          library, include, profiles
│   ├── driver/       basic drivers + USB stack
│   ├── driver_enhance/
│   ├── modules/      os, freertos, rt-thread_v4.0.3, gui, gui_lib, RTT, crc32, sha256, aes
│   └── toolchain/
├── docs/
│   ├── FR8000 SDK User Manual V1.1.pdf
│   ├── FR8000 Specification V1.2.0.pdf   (284 pages)
│   └── fr8000u usage notes.pdf
├── examples/none_evm/
│   ├── ble_AT, ble_simple_central, ble_simple_peripheral
│   ├── ble_hid_kbd_mice        ← HID keyboard and mouse
│   ├── ble_freertos_demo, ble_RT-thread_demo
│   └── peripheral_demo
└── tools/  FR8000.FLM, JLinkDevices.xml   (no flashing utility)
```

**BLE profiles:** `ble_ota`, `ble_hid`, `ble_batt`, `ble_dev_info`, `ble_simple_profile`,
`ble_cts`, `ble_ANCS`, `ble_AMS`, `ble_AirSync`, `ble_audio_profile`, `ble_mesh_models`.

**Display-relevant drivers:** `driver_spi_master.c`, `driver_if8080.c` (parallel display
interface), `driver_psram.c`, `driver_dma.c`, `driver_rgb.c` (in `driver_enhance`),
`driver_uart_ex.c`, `driver_flash.c`, `driver_pmu.c`, `driver_keyscan.c`.

**LVGL is bundled:** `components/modules/gui/` contains `lvgl`, `lvgl_8_0`, `lvgl_8_1`,
`lvgl_examples`, plus config files `lv_conf.h` / `lv_ex_conf.h` and a separate `gui_lib`.
The graphics stack is already built and configured by the vendor — no need to start from scratch.

### Official

- Series page: `https://www.freqchip.com/fr800x` (docs downloadable without registration, SDK requires it)
- Developer forum: `http://www.freqchip.net:4567/category/11/fr800x` — active,
  moderator `ZR` responds in English as well
- FR800x FAQ: `https://docs.qq.com/pdf/DUnZrWVJIdktMekZY`
- Documentation feedback: `doc@freqchip.com`
- Open SDKs for adjacent series: `github.com/qdfreqchip/FR801x-SDK`, `FR801xH-SDK`

### Community

- `gitee.com/a18562560220/freqchip_faq` — FAQ, driver examples, flashing docs,
  `lvgl_knob_open_demo`
- `gitee.com/YgqMars/freqchip` — flashing utility `FreqChip_Download_New`

### Reference projects

- `github.com/snackdriven/al80-lcd` — full reverse of the YUNZII AL80 keyboard LCD:
  raw HID protocol, image and GIF formats, custom vial-qmk firmware, browser control panel
- `github.com/IsSuEat/zmk75-lcd-tool` *(verify exact name)* — Python/hidapi for Zoom75 LCD
- Meletrix/Wuque firmware archive on Google Drive — module images for Zoom75, Zoom98, Freya,
  APK `keyboard_project_base_ota.apk`, manual OTA instructions

---

## 8. Open questions

1. ~~Are the pogo RX/TX contacts actually routed from PA0/PA1?~~ → **closed, phase 0:** yes —
   boot-ROM banner and MAC print directly on the pogo pins
2. ~~What resolution does the panel have?~~ → **closed: 320 × 172 RGB565 landscape**, from the
   608-container resource catalogue (§4.5). Controller still to be confirmed — ST7789 expected
   → phase 3
3. ~~Is there an SDK for FR8008HP?~~ → **closed:** `fr8000_sdk_V2.1` covers the FR8000 family
4. ~~Does the FR800x boot handshake mechanism match the one documented for FR801xH?~~ →
   **closed, phase 0:** confirmed experimentally — `freqchip` banner, chip id & MAC, same as
   documented
5. ~~Is flash read-protected?~~ → **closed, phase 0.5:** no
6. ~~Will Meletrix provide the stock firmware?~~ → **not critical**, dump is captured independently
7. ~~What is `OTAS_NOTIFY_DATA_SIZE`?~~ → **partly closed:** `READ_DATA` never returns the
   payload by notification at all — it always acknowledges and hands the data over via GATT
   Read on `...ff00`. Separately, reads below ~32 bytes are rejected outright
8. ~~Does the module answer AT commands on the pogo contacts?~~ → **closed, phase 0:** no —
   `AT+CIVER?` and other AT commands get no response; module uses its own binary framed protocol
   (see `docs/UART_PROTOCOL.md`)
9. Was the factory firmware built with serial OTA support? → follows from phase 0
10. ~~Does the factory build implement `OTA_CMD_READ_DATA`?~~ → **closed, phase 0.5:** yes
11. What is `msg_id 0x31` (the module's outgoing announce frame), and what other `msg_id` values
    exist? → phase 1, needs the module talking to the main board
12. `NVDS_TYPE` returns `0x11`, which is not a value in the SDK enum (`0` none / `1` flash /
    `2` eeprom). What does it encode, and is the MAC kept there?
13. Where is the MAC actually stored, given that `0x60000` is erased?
14. Why does a container's last row sometimes under-report its final span in the row table?
15. ~~How many containers use alpha spans?~~ → **closed, 12.09.2026: 509 of 608.** The decoder
    now handles both encodings; see §4.5
16. What is PA3 for? Configured as an input by the display driver — TE is the obvious guess.
17. Where is the one-time ST7789 init sequence issued from?
18. What are the `+0x01` and `+0x0C` fields of the display context at `0x11003934`? Both read
    back as 1 on a running module.
19. Which of the 9 `FR800x_RD_V1.1_20230923` reference-design PDFs (`FR2012B`, `FR2012B-M`,
    `FR8003A`, `FR8003A-R`, `FR8003D`, `FR8008A`, `FR8008AP`, `FR8008G`, `FR8008XP`) actually
    matches the module's marked chip, `FR8008HP`? None is named literally `FR8008HP`. Only
    matters for hardware reference (pin-for-pin schematic check), not for firmware.
20. ~~How to get past the Keil eval linker's ~32 KB image cap?~~ → **closed, 12.09.2026:** moved
    the build to the SDK's own GCC path (`arm-none-eabi-gcc` + GnuWin32 Make + Git Bash's
    `sh`/`rm`) — `ble_simple_peripheral` now builds full-size, no license needed. See §6.
21. Does the boot loader require a signed `jump_table_crc`/`image_crc` (`jump_table.h:247-260`) to
    accept an image, or does it only check `firmware_version` for bank selection? No CRC-patching
    script was found anywhere in `sdk_V2.1` or `vendor/freqchip`, and neither our GCC build nor a
    vanilla Keil build of the example produces one. Matters before any real image is written to
    the module — see the Phase 2 addendum above.

---

## Sources

### FreqChip — chip vendor

- [FR800x series page](https://www.freqchip.com/fr800x) — specification, reference manual,
  hardware application guide, schematics and footprints download freely; SDK requires
  registration
- [FreqChip developer forum, FR800x section](http://www.freqchip.net:4567/category/11/fr800x) —
  active; moderator `ZR` answers in English as well. Threads on LVGL, PSRAM, MTU, flash
  endurance are directly relevant
- [FR800x series FAQ](https://docs.qq.com/pdf/DUnZrWVJIdktMekZY)
- [FR801x-SDK](https://github.com/qdfreqchip/FR801x-SDK) and
  [FR801xH-SDK](https://github.com/qdfreqchip/FR801xH-SDK) — open SDKs for adjacent series.
  Their `docs/` describe the OTA packet format and the power-on UART handshake; the FR8000
  SDK documents the same mechanisms

### Flashing and toolchain

- [gitee.com/YgqMars/freqchip](https://gitee.com/YgqMars/freqchip) — the richest single source.
  `FreqChip_Download_New` V1.3.9.1 (GUI + console), the full OTA protocol document, the serial
  OTA SDK variant and its PC utility, the AT command reference, USB OTA reference, RF ESD
  guidance. **The flashing utility is not shipped with SDK V2.1**, so it must be fetched here.
  Full breakdown in section 7.0
- [gitee.com/a18562560220/freqchip_faq](https://gitee.com/a18562560220/freqchip_faq) —
  unofficial mirror maintained by a forum moderator: `06富芮坤芯片入手资料获取和烧录工具使用.pdf`,
  `Freqchip芯片烧录与环境搭建.pdf`, peripheral driver examples, and `lvgl_knob_open_demo` —
  an open LVGL "knob with a screen" demo on this chip family, structurally close to what the
  module likely runs
- [Keil MDK V5.28](https://armkeil.blob.core.windows.net/eval/MDK528.EXE) — vendor-verified
  version; newer releases fail to build the SDK
- [ARM.CMSIS.5.9.0.pack](https://keilpack.azureedge.net/pack/ARM.CMSIS.5.9.0.pack)

### Display protocol reverse-engineering — reference projects

- [snackdriven/al80-lcd](https://github.com/snackdriven/al80-lcd) — complete reverse of the
  YUNZII AL80 LCD: raw HID protocol, still image and GIF formats, clock sync, browser control
  panel, host app pushing Spotify and weather. Panel there is 96×160 RGB565 big-endian,
  row-major, 30,720 bytes per frame — a useful order-of-magnitude reference
- [IsSuEat/zoom75-lcd-tool](https://github.com/IsSuEat/zoom75-lcd-tool) — Python/hidapi tool
  pushing clock and CPU/GPU temperatures to the original Zoom75 LCD
- Zuoya GMK87 / GMK67-S community tools: `gmk87-node`, `gmk67s` CLI — open image and GIF
  uploaders running on top of stock closed firmware, with a documented opcode spec

### Screen module firmware archive

Screen-related parts of the Wuque/Meletrix Google Drive (link in the root README):

- `1. Screen Manual Upgrade Software/` — `keyboard_project_base_ota.apk`, OTA walkthrough video
- `Zoom 75 Screen Firmware/`, `Zoom 98 Screen Firmware/`, `Freya Screen Firmware/` —
  module images, naming scheme `<board>screen_OTA_<module id>_<model code>_V<version>_<timestamp>.bin`
- `Zoom75_屏模组_手动方式_安卓_OTA_升级方法/` — Chinese manual OTA procedure: search over BLE,
  connect to `BA0009CS`, pick file, write; no downgrade and no same-version reflash

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 09.09.2026 | Split project into 2 stages, display first | Module is independent from main board, developed on the bench |
| 09.09.2026 | No backlighting in stage 2 | Simplifies the board, eliminates LED type question, radically improves battery life |
| 09.09.2026 | Stage 2 MCU — Raytac MDBT50Q | 48 GPIO vs ~20 on Pro Micro boards; certified; ZMK `nice_nano_v2` as reference |
| 09.09.2026 | 2.4 GHz deferred | Does not affect board layout, resolved later in software (ZMK dongle over BLE or ESB module) |
| 09.09.2026 | BLE firmware dump — priority #1 | `OTA_CMD_READ_DATA` found in SDK; factory GATT matches SDK profile byte-for-byte, so reading is available without a soldering iron |
| 12.09.2026 | Build firmware with the SDK's GCC/Makefile path, not Keil | Unlicensed Keil V5.28 caps linked images at ~32 KB (`L6050U`, hit building `ble_simple_peripheral` unchanged, 106 660 bytes). Installed `arm-none-eabi-gcc` + GnuWin32 Make + Git Bash's `sh`/`rm`; the same example then built full-size (154 728 bytes) with no license. Keil is no longer needed to build this SDK |
| 12.09.2026 | GCC-built images are toolchain smoke-tests only, not yet flash-ready | `firmware_version=0` and `image_size=0x20000` in the built header are unmodified example placeholders (`proj_main.c`), and no CRC-signing step (referenced in `jump_table.h` comments) was found anywhere in the SDK checkout. All three must be addressed with real values/tooling before any image derived from this SDK is written to the module |
