# Stage 1 — Custom firmware for the Meletrix Zoom75 TIGA display module

> Project knowledge base. Version 1.1, updated 09.09.2026 after reviewing fr8000_sdk_V2.1.
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

**Hypothesis, needs verification:** the pogo RX/TX contacts are routed from PA0/PA1
(not from UART1 on PA2/PA3 with mux `0x5`, and not from the alternative pair PA4/PA5).

---

## 3. UART flashing — how it works

FreqChip's official position: J-Link does not always work with BLE-stack chips (cannot connect
if the chip is asleep or SW pins are remapped), **so serial flashing and debugging are
recommended**. The absence of SWD pads on the module is an expected situation, not a problem.

### Mechanism

On power-up the internal ROM boot program attempts to communicate with the PC utility over UART.
After the handshake, flash writing becomes available.

### Parameters

| Parameter | Value |
|---|---|
| Bootloader handshake baud rate | **115200** |
| Actual flashing baud rate | **921600** |
| Sign of a live chip | on reset the string **`freqchip`** is printed to the port |
| Family in the utility | **FR800X** (covers FR8008 and FR8003) |

### Utility

`FreqChip_Download_New.zip` (FREQCHIP调试工具 V1.3.8) —
in the archive `https://gitee.com/YgqMars/freqchip/repository/archive/master.zip`

> ⚠️ **The SDK V2.1 does NOT include a flashing utility.** The `tools/` folder contains only
> `FR8000.FLM` (flash algorithm for Keil/J-Flash) and `JLinkDevices.xml`. Download the
> utility separately via the link above.

Procedure: select FR800X → load bin → check "auto-flash" and "auto-restart" →
"open firmware" → reset the module → handshake happens automatically.
The "Options" menu has entries for writing MAC, SN, specifying a file, erasing the OTA region,
and flash protection.

> ⚠️ The utility writes but **does not read**. It cannot dump the factory firmware.

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
> 2023 Zoom75 and Zoom98. **But it can be read from the module** with `OTA_CMD_READ_DATA`
> over BLE — see phase 0.5. This eliminates the main project risk.

---

## 5. What needs to be done — stage plan

### Phase 0. Access confirmation (blocking)

- [ ] Buy a **3.3 V** USB-UART adapter, CP2102 or CH343 (cheap CH340 may not sustain 921600 —
      explicitly warned in FreqChip documentation)
- [ ] Connect: GND↔GND, adapter TX → module RX, adapter RX ← module TX (cross)
- [ ] Terminal at **115200**, apply power to the module
- [ ] **Success criterion: the string `freqchip` appears in the port**
- [ ] If not — try 9600 / 57600 / 921600, then check with a logic analyser
- [ ] If still no — pogo contacts are not PA0/PA1; soldering to QFN-40 pins is required

### Phase 0.5. Dump factory firmware over BLE — do this FIRST

The module responds to the stock OTA profile, requires no pairing, and the command set includes
reading. So the factory firmware can be captured **without a soldering iron, without opening
anything, with no hardware at all** — just BLE from a computer.

- [ ] Python + `bleak`, connect to `04:75:79:FB:DD:E7`
- [ ] Enable notify on `...ff02`
- [ ] Read `...ff03` (version) and send `02 00 00` → compare with response
- [ ] Send `01 00 00` (`GET_STR_BASE`) → get bank base address
- [ ] Negotiate a higher MTU (`gap_set_mtu` on the module side up to 512; request maximum
      on the host side)
- [ ] Loop read: opcode `0x06`, payload `base_address(4, LE) + length(2, LE)`
- [ ] Account for: if the response is larger than `OTAS_NOTIFY_DATA_SIZE`, data is retrieved
      via GATT Read, not delivered as a notification
- [ ] Save the dump, compute hash, place in `docs/factory_dump/`
- [ ] Also read `0x60000` (MAC) and `0x61000` (SN) — verify MAC against the known value

**Success criterion: a binary image of the factory firmware is on disk.** After this, any
experiment is reversible and you can work more boldly.

> ⚠️ Do not send `0x04` (`CHIP_ERASE`) under any circumstances before the dump is obtained.

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
| ~~No rollback to stock~~ | Eliminated | — | Firmware can be read back with `READ_DATA` over BLE (phase 0.5) |
| Dump capture fails | Low | Previous risk returns | Request stock firmware from Meletrix before any writes |
| MAC/SN lost on full erase | Medium | Module loses identity | MAC recorded: `04:75:79:FB:DD:E7`; do not use full erase without reason |
| Pogo contacts are not PA0/PA1 | Medium | Soldering to QFN-40 required | Check in phase 0 |
| Panel bonded COG / FPC non-detachable | Low | Cannot reuse panel separately | Hirose connector is visible — risk is low |
| Cheap USB-UART cannot sustain 921600 | Medium | Flashing fails | Use CP2102 / CH343 |
| Flash is write-protected | Low | Flashing impossible | Utility has a "Flash protection" menu entry |
| Loss of PocketWuque | 100% | No image upload from phone | Conscious decision; custom channel in phase 4 |

---

## 7. Resources

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

1. Are the pogo RX/TX contacts actually routed from PA0/PA1? → phase 0
2. What controller and resolution does the panel have? → phase 3
3. ~~Is there an SDK for FR8008HP?~~ → **closed:** `fr8000_sdk_V2.1` covers the FR8000 family
4. Does the FR800x boot handshake mechanism match the one documented for FR801xH? → phase 0
5. Is flash protection enabled? → will be revealed on the first `READ_DATA` in phase 0.5
6. ~~Will Meletrix provide the stock firmware?~~ → **not critical**, dump is captured independently
7. What is `OTAS_NOTIFY_DATA_SIZE` in the factory build? → determined empirically in phase 0.5

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

- [gitee.com/YgqMars/freqchip](https://gitee.com/YgqMars/freqchip) — `FreqChip_Download_New`,
  the serial flashing utility. **Not shipped with SDK V2.1**, must be fetched here
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
