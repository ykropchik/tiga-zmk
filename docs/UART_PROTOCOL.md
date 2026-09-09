# UART protocol between the main board and the display module

Status: **not captured yet**. To be filled in during stage 1, phase 1.

## Physical layer

| Parameter | Value | Status |
|---|---|---|
| Contacts | 4 module pogo pins: `GND / RX / TX / VCC` | fact (silkscreen) |
| Voltage levels | 3.3 V | hypothesis |
| Baud rate | ? | not determined |
| Frame format | ? | not determined |

## Leading hypothesis

The module may speak the FreqChip SDK's stock **AT command set** (115200 8N1) or its transparent
passthrough mode — see `STAGE1_DISPLAY_MODULE.md` §3.2. Test this before reaching for a logic
analyser: send `AT+CIVER?` terminated with CR LF at 115200 and look for a `+VER:...OK` reply.

## Capture method

1. Module installed in the keyboard; solder onto the main board TX line — listen only.
2. Record the traffic for each event in the table below.
3. Match events to packets.

## Event table for capture

| Event | Key combo | Packet | Notes |
|---|---|---|---|
| Power on | — | | |
| Bluetooth 1 | Fn+Z | | |
| Bluetooth 2 | Fn+X | | |
| Bluetooth 3 | Fn+C | | |
| 2.4 GHz mode | Fn+V | | |
| USB mode | Fn+Space | | |
| Windows layout | Fn+Q | | |
| Mac layout | Fn+W | | |
| Screen on/off | Fn+Delete | | |
| Page forward | Fn+PageDown | | |
| Page back | Fn+PageUp | | |
| Enter subpage | Fn+Enter | | |
| Go back | Fn+RShift+Enter | | |
| Charger connected | — | | |
| Battery level change | — | | |

## Recovered format

_Fill in after capture._
