# UART protocol between the main board and the display module

Status: **partially reverse-engineered** (phase 0, 09.09.2026). Physical layer, the boot-ROM
handshake, and the module's own outgoing attempt are confirmed experimentally. The main board's
side of the conversation has not been observed yet — that is phase 1.

## Experimental setup

Captured with the display module extracted from the keyboard and connected standalone to a
USB-UART adapter (CP2102). The main board was **not** part of the circuit. This means the frames
below are the module talking to nobody, retrying on its own timeout, then giving up — not a
real exchange. Real main-board replies are still unknown.

## Physical layer

| Parameter | Value | Status |
|---|---|---|
| Contacts | 4 module pogo pins: `GND / RX / TX / VCC` | fact (silkscreen) |
| Baud rate | 115200 | fact (phase 0) |
| Frame format | 8N1, no flow control | fact (phase 0) |
| Voltage levels | 3.3 V | hypothesis |

> ⚠️ **Wiring warning.** The pogo pin labels are silkscreened from the **main board's** point of
> view, not the module's. The intuitive rule "TX goes to RX" is **wrong here** and produces total
> silence on the port — no boot banner, nothing. The working connection is direct, name-to-name:
> adapter TXD → module `TX` pin, adapter RXD → module `RX` pin, GND → GND. The crossed variant
> does not work.

## Boot-ROM handshake (confirmed, phase 0)

About **2.3 s** after power is applied, the boot ROM prints to the port:

```
freqchip
chip id & mac:
```

followed by the MAC address in **reversed byte order**: `E7 DD FB 79 75 04`, which read backwards
is the known `04:75:79:FB:DD:E7`. This independently confirms module identity and, together with
the fact that this happens at all on these pins, confirms the pogo `RX`/`TX` contacts are wired to
the FR8008HP bootloader UART (`PA0`/`PA1`, see `STAGE1_DISPLAY_MODULE.md` §2.4) — closing open
question 1 there.

## Application-layer frame protocol (partially decoded)

After the boot banner, the module's application firmware (not the boot ROM) starts talking on the
same lines without waiting to be addressed. Captured frames:

```
a5 31 00 02 00 00 cc
a5 31 00 02 00 01 cb
a5 31 00 02 00 02 ca
```

### Frame structure

```
A5 | msg_id(1) | len(2, big-endian) | payload | checksum(1)
```

In the captured frames: `msg_id = 0x31`, `len = 0x0002`, and `payload` is a 2-byte big-endian
counter (`0x0000`, `0x0001`, `0x0002`).

### Checksum

```
checksum = 0xFF - (sum(msg_id, len_hi, len_lo, payload bytes) mod 256)
```

Verified on all three captured frames. Frame 1: `0x31 + 0x00 + 0x02 + 0x00 + 0x00 = 0x33`;
`0xFF - 0x33 = 0xCC`, matching the trailing byte. Frames 2 and 3 check out the same way
(`0xCB`, `0xCA`).

### Behavior: three attempts, then silence

The module makes **three attempts** to reach the main board, incrementing the counter in the
payload each time, then stops:

| Attempt | Delay |
|---|---|
| 1 | ~0.76 s after the boot banner |
| 2 | 65 ms after attempt 1 |
| 3 | ~2.36 s after attempt 2 |

The growing delay between attempts 1→2 and 2→3 looks like an increasing timeout/backoff; ~65 ms
appears to be the window the module gives the main board to reply before retrying. Behavior is
deterministic — reproduced byte-for-byte across separate power cycles.

### Unconfirmed observation

In one of two capture runs, a block of 64 bytes of `0xFF` appeared on the line between the second
and third frame. It did not reproduce on the other run. Most likely explanation is contact bounce
on the pogo pins rather than a real part of the protocol — **not confirmed**, recorded for
awareness only.

### Rejected hypothesis

~~The module may speak the FreqChip SDK's stock AT command set (115200 8N1) or its transparent
passthrough mode.~~ Tested in phase 0: no response to `AT+CIVER?` or any other AT command on the
pogo lines. Meletrix's application firmware uses its own binary framed protocol instead (above),
not the SDK's AT example — closes open question 8 in `STAGE1_DISPLAY_MODULE.md`.

## Capture method (still needed — phase 1)

The frames above only show the module's outgoing attempts in isolation. To see the main board's
side of the conversation and decode other `msg_id` values, the module must be captured while
actually talking to the main board:

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

`msg_id 0x31` looks like a handshake/announce message carrying an attempt counter — plausibly the
module announcing itself to the main board on boot. Meaning of other `msg_id` values, and the
main board's replies (including whether it replies at all within the module's window), are
unknown — pending phase 1 capture with the module installed in the keyboard.
