# Stage 1 — Custom firmware for the Meletrix Zoom75 TIGA display module

> Project knowledge base. Version 1.3, updated 09.09.2026 after phase 0 results (live UART
> access to the module confirmed, boot-ROM handshake captured, application-layer frame protocol
> partially decoded). Previous update (1.2) reviewed fr8000_sdk_V2.1 and the
> gitee.com/YgqMars/freqchip repository.
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

### Phase 0.5. Check whether a factory firmware backup is even possible — do this FIRST

**This is a verification, not a guaranteed backup.** The FreqChip flashing utility only ever
*writes* (§3 — "the utility writes but does not read"), so the only known path to a dump is the
SDK's documented `OTA_CMD_READ_DATA` (`0x06`) over the BLE OTA service (§4.2, §4.3). Whether the
**factory build actually implements this opcode** is unknown — nobody has exercised the read path
on this module. Treat phase 0.5 as answering that question before assuming a safety net exists.

**Step 1 — safe probes only (no flash access, no risk):**

- [ ] Python + `bleak`, connect to `04:75:79:FB:DD:E7` (no pairing required, §4.2)
- [ ] Enable notify on `...ff02`
- [ ] Send `02 00 00` (`OTA_CMD_READ_FW_VER`) → expect a firmware version in the response
- [ ] Send `01 00 00` (`OTA_CMD_GET_STR_BASE`) → expect a bank base address
- [ ] If either command returns `0x02` (unknown command) or nothing at all: the factory build
      likely does not expose this handler — stop here and treat backup as **not available**
      (see "Outcome B" below)

**Step 2 — only if step 1 succeeds — trial read of a small fragment:**

- [ ] Negotiate a higher MTU if available (`gap_set_mtu`, up to 512)
- [ ] Send opcode `0x06` (`OTA_CMD_READ_DATA`) for a small range (e.g. 64–256 bytes) at the base
      address from step 1
- [ ] Confirm the returned bytes look like code/data, not garbage or an error result byte
- [ ] Account for: if the response is larger than `OTAS_NOTIFY_DATA_SIZE`, it is retrieved via a
      GATT Read on the characteristic, not delivered as a notification

**Outcome A — read works:** proceed to read the full image in a loop, save the dump, compute a
hash, place it in `docs/factory_dump/`; also read `0x60000` (MAC) and `0x61000` (SN) and verify
the MAC against the known value. **Success criterion: a binary image of the factory firmware is
on disk.** After this, later experiments (custom firmware, reflashing) are reversible.

**Outcome B — read does not work (opcode unsupported or errors out on this build):**
**there will be no factory firmware backup.** The decision to reflash the module with custom
firmware then has to be made without a rollback path — accept that stock functionality
(PocketWuque, factory OTA) is lost for good the moment the module is reflashed, or hold off on
stage 1 until/unless a factory `.bin` surfaces some other way (Meletrix support request, a leak,
etc.). This is a real possible outcome, not a formality — do not assume Outcome A without running
step 1.

> ⚠️ Do not send `0x04` (`CHIP_ERASE`) under any circumstances before this check is resolved,
> per project hardware safety rules.

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

- [x] **SDK obtained: `fr8000_sdk_V2.1`** (see section 7.1 — contents)
- [ ] Download: Technical Specification V0.3.19, Reference Manual V1.2.1,
      Hardware Application Guide V1.4, SDK User Guide V1.0, schematics and footprints V1.1
- [ ] **Keil V5 version 528** (newer versions do not compile the SDK — confirmed by the vendor)
      `https://armkeil.blob.core.windows.net/eval/MDK528.EXE`
- [ ] CMSIS pack `ARM.CMSIS.5.9.0.pack`
- [ ] Python 3.8+ added to PATH (needed for build scripts)
- [ ] `FreqChip_Download_New` from `gitee.com/YgqMars/freqchip`
- [ ] Build the `ble_simple_peripheral` example unchanged and flash it — verify the toolchain

### Phase 3. Panel identification

- [ ] Close-up photo of the FPC cable marking, find datasheet
- [ ] Identify the controller (expected: ST7789 / GC9A01 / ILI9341 or similar)
- [ ] Determine resolution, interface (SPI / D-SPI / QSPI / I8080), 13-pin pinout
- [ ] Probe which FR8008HP pins connect to the Hirose connector

Resolution reference from neighbours: Zoom75 (2023) — same class screen; YUNZII AL80
panel is 96×160 RGB565 big-endian row-major, 30 720 bytes per frame. The TIGA is claimed to
have twice the memory and "4× faster interface" — resolution is likely higher.

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
| No rollback to stock | **Unconfirmed** | Reflashing becomes a one-way trip; stock functionality (PocketWuque, factory OTA) is lost permanently | Pending phase 0.5 read check — `OTA_CMD_READ_DATA` is documented in the SDK but not yet confirmed to work on this build |
| Dump capture fails (factory build doesn't implement `READ_DATA`) | Medium | Above risk stays open | Request stock firmware from Meletrix before any writes; hold off on reflashing without a dump |
| MAC/SN lost on full erase | Medium | Module loses identity | MAC recorded: `04:75:79:FB:DD:E7`; do not use full erase without reason |
| ~~Pogo contacts are not PA0/PA1~~ | Resolved | — | Confirmed PA0/PA1 in phase 0 — boot-ROM handshake works directly on the pogo pins |
| Panel bonded COG / FPC non-detachable | Low | Cannot reuse panel separately | Hirose connector is visible — risk is low |
| Cheap USB-UART cannot sustain 921600 | Medium | Flashing fails | Use CP2102 / CH343 |
| Flash is write-protected | Low | Flashing impossible | Utility has a "Flash protection" menu entry |
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
2. What controller and resolution does the panel have? → phase 3
3. ~~Is there an SDK for FR8008HP?~~ → **closed:** `fr8000_sdk_V2.1` covers the FR8000 family
4. ~~Does the FR800x boot handshake mechanism match the one documented for FR801xH?~~ →
   **closed, phase 0:** confirmed experimentally — `freqchip` banner, chip id & MAC, same as
   documented
5. Is flash protection enabled? → will be revealed on the first `READ_DATA` in phase 0.5
6. ~~Will Meletrix provide the stock firmware?~~ → **not critical**, dump is captured independently
7. What is `OTAS_NOTIFY_DATA_SIZE` in the factory build? → determined empirically in phase 0.5
8. ~~Does the module answer AT commands on the pogo contacts?~~ → **closed, phase 0:** no —
   `AT+CIVER?` and other AT commands get no response; module uses its own binary framed protocol
   (see `docs/UART_PROTOCOL.md`)
9. Was the factory firmware built with serial OTA support? → follows from phase 0
10. Does the factory build actually implement `OTA_CMD_READ_DATA` (`0x06`)? → phase 0.5, unresolved
11. What is `msg_id 0x31` (the module's outgoing announce frame), and what other `msg_id` values
    exist? → phase 1, needs the module talking to the main board

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
