# UART protocol between the main board and the display module

Status: **largely reverse-engineered** (10.09.2026). Physical layer and the module's outgoing
frame were confirmed experimentally in phase 0; the frame format, checksum and the full message
vocabulary were then recovered by decompiling the firmware in Ghidra. What remains unknown is
which message ids correspond to which user-visible keyboard actions — that still wants a live
capture.

Key addresses: parser `0x10021706`, dispatcher `0x10021228`, reply path `0x10020E26`.
A reconstruction of the parser is in `research/uart_parser_reconstructed.c`.

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

---

## Recovered from the firmware (10.09.2026)

### Frame format, confirmed against the parser

```
A5 | msg_id | len_hi | len_lo | payload[len] | checksum
```

- length is **big-endian**, assembled at `0x10021742`
- payload is capped at `0x43` = 67 bytes; longer frames are dropped and the parser resyncs
- checksum = `~(msg_id + len_hi + len_lo + Σ payload) & 0xFF`, matching the `0xFF - sum` formula
  derived from the captured frames
- **a checksum byte of `0xFF` is accepted without verification** (`0x100217A0`) — useful while
  experimenting
- on mismatch the module replies with code `0xFD`

Nearly every handler begins with `cmp payload[0], #0`, so **byte 0 of the payload acts as a
direction or sub-type flag** and must be zero on the request path. `payload[1]` usually selects a
variant. All multi-byte numeric fields are big-endian — the dispatcher is full of `rev16`.

### Message vocabulary

| msg_id | Meaning | Confidence |
|---|---|---|
| `0x01` | control / reset; variant 1 rewrites a clock register and spins forever | high |
| `0x02` | **arm a data transfer**: 32-bit address, 32-bit length, 16-bit chunk size | high |
| `0x03` | **transfer a data block** at the running address, acks `0xFE` | high |
| `0x04` | **set UART baud rate**; recognises `0x1C200` (115200) and `0xE1000` (921600) | high |
| `0x31` | the module's own announce/poll frame, with a retry counter | fact (captured) |
| `0x32` | **set mode**, `payload[1]` ∈ {1,2,3,4} | high |
| `0x33` | accepted, no visible effect on this path | low |
| `0x34` | fires two callbacks when `payload[1] == 1` | medium |
| `0x35` | two 16-bit values plus a byte | medium |
| `0x36` | accepted, falls through | low |
| `0x37` | **signed 16-bit measurement ÷10**; `0xFFFF` means "no data" | high |
| `0x38` | **packs a date/time into one 32-bit word** via `bfi` (year−2000 in bits 26–31) | high |
| `0x39` | four actions selected by `payload[1]` → codes 5..8 | medium |
| `0x3A` | 16-bit value, acts only on change, then raises event 7 | medium |
| `0xFB` | **builds a 10-byte reply** from a global — identity or version report | high |
| `0xFD` | two 16-bit values plus a byte | medium |
| `0xFE` | **three signed 16-bit measurements ÷10**, same `0xFFFF` convention | high |
| `0xFF` | **date and time**: five consecutive 16-bit big-endian fields | high |

Reply codes: `0xFE` accepted, `0xFD` checksum error, `0xFA` transfer not armed, `0xF9` parameter
out of range.

### The `0x02` / `0x03` transfer sequence

This is how the main board pushes images into the module's flash over the wire.

`0x02` arms the transfer and validates (`0x1002169A`–`0x100216AC`):

- chunk size ≤ `0x400` (1024), else `0xF9`
- target address ≥ `0x80000` — **the resource area only; the firmware banks are off limits**
- target address below the length bound, and 4 KB-aligned

`0x03` then pushes blocks, advancing the address and decrementing a counter, replying `0xFE` each
time and clearing the busy flag when the counter reaches zero. Sending `0x03` without `0x02`
first returns `0xFA`.

> Consequence for stage 2: a custom ZMK board can reload the module's image library over the
> wire, with no BLE involved. It cannot touch the firmware itself — that needs BLE OTA or the
> boot ROM.

### Still unknown

- the payload layout of `0x31` beyond the two-byte retry counter
- whether `0x33` and `0x36` do anything at all
- which ids correspond to channel switching, battery level, Caps Lock and page navigation —
  needs a capture from a live keyboard

The ÷10 signed fields and the date/time messages suggest the module also displays sensor readings
and a clock, consistent with the vendor app's weather and time features.

