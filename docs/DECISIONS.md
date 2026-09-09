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
| 09.09.2026 | Stage 2 screen: route pads for both nice!view and the native module | Five-pin footprint (SPI) plus four-pin UART connector; costs almost nothing, keeps both paths open | accepted |
