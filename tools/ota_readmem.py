#!/usr/bin/env python3
"""
Read RAM from a live FreqChip FR800x device over BLE (Zoom75 TIGA display module).

Uses OTA_CMD_READ_MEM (0x08), the memory counterpart of READ_DATA (0x06).
Handy for inspecting globals whose values cannot be determined statically.

READ-ONLY. Only opcode 0x08 is used. Nothing is written or erased.

Requires:  pip install bleak

Usage:
    python ota_readmem.py 0x11003934 16          read 16 bytes
    python ota_readmem.py 0x11003934 16 --u16    also print as 16-bit words
    python ota_readmem.py 0x11003800 512 --out ram.bin
    python ota_readmem.py --address 04:75:79:FB:DD:E7 0x11003934 8

Known addresses of interest on this module:
    0x11003934   display context: +0 busy flag, +2 window X offset, +4 window Y offset
    0x110038A0   framebuffer 0 pointer
    0x110038A4   framebuffer 1 pointer
    0x110038D0   draw context flags
    0x110038E0   active framebuffer pointer
"""

import argparse
import asyncio
import struct
import sys

from bleak import BleakClient, BleakScanner

SVC = "02f00000-0000-0000-0000-00000000fe00"
CH_TX = "02f00000-0000-0000-0000-00000000ff00"
CH_RX = "02f00000-0000-0000-0000-00000000ff01"
CH_NOTI = "02f00000-0000-0000-0000-00000000ff02"

CMD_READ_MEM = 0x08
CMD_READ_DATA = 0x06

MIN_READ = 32          # the module rejects smaller requests
MAX_CHUNK = 240

inbox: asyncio.Queue = asyncio.Queue()


def on_notify(_s, data: bytearray) -> None:
    inbox.put_nowait(bytes(data))


async def command(client, opcode: int, payload: bytes, timeout=5.0):
    while not inbox.empty():
        inbox.get_nowait()
    frame = bytes([opcode]) + len(payload).to_bytes(2, "little") + payload
    await client.write_gatt_char(CH_RX, frame, response=False)
    try:
        return await asyncio.wait_for(inbox.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def read_mem(client, addr: int, size: int, opcode: int):
    """One round trip: command, acknowledgement, then a plain GATT read."""
    payload = addr.to_bytes(4, "little") + size.to_bytes(2, "little")
    ack = await command(client, opcode, payload)
    if ack is None:
        print(f"  no acknowledgement for 0x{addr:08X}")
        return None
    if len(ack) < 2 or ack[0] != 0x00:
        print(f"  device refused: {ack.hex(' ')}")
        return None
    data = bytes(await client.read_gatt_char(CH_TX))
    return data or None


async def pick_device(scan_time: float):
    print(f"scanning for {scan_time:.0f} s ...")
    found = await BleakScanner.discover(timeout=scan_time, return_adv=True)
    entries = sorted(found.values(),
                     key=lambda p: p[1].rssi if p[1].rssi is not None else -999,
                     reverse=True)
    for i, (dev, adv) in enumerate(entries):
        print(f"  {i:>3}  {dev.address:<20} {adv.rssi:>5}  "
              f"{dev.name or adv.local_name or '(unnamed)'}")
    c = input("\nnumber to connect (q to quit): ").strip()
    if not c.isdigit() or not (0 <= int(c) < len(entries)):
        sys.exit("cancelled")
    return entries[int(c)][0]


def dump(addr: int, data: bytes, as_u16: bool, as_u32: bool) -> None:
    for i in range(0, len(data), 16):
        row = data[i:i + 16]
        text = "".join(chr(c) if 32 <= c < 127 else "." for c in row)
        print(f"  {addr + i:08X}  {row.hex(' '):<47}  {text}")

    if as_u16:
        print("\n  as 16-bit little-endian:")
        for i in range(0, len(data) - 1, 2):
            v = struct.unpack_from("<H", data, i)[0]
            print(f"    +0x{i:02X}  0x{v:04X}  {v}")

    if as_u32:
        print("\n  as 32-bit little-endian:")
        for i in range(0, len(data) - 3, 4):
            v = struct.unpack_from("<I", data, i)[0]
            print(f"    +0x{i:02X}  0x{v:08X}  {v}")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("addr", type=lambda v: int(v, 0), help="address, e.g. 0x11003934")
    ap.add_argument("size", nargs="?", type=lambda v: int(v, 0), default=32)
    ap.add_argument("--address", help="BLE address; omit to scan and choose")
    ap.add_argument("--flash", action="store_true",
                    help="use READ_DATA (0x06) instead of READ_MEM (0x08)")
    ap.add_argument("--u16", action="store_true", help="also print 16-bit words")
    ap.add_argument("--u32", action="store_true", help="also print 32-bit words")
    ap.add_argument("--out", help="write the raw bytes to this file")
    ap.add_argument("--scan", type=float, default=10.0)
    args = ap.parse_args()

    opcode = CMD_READ_DATA if args.flash else CMD_READ_MEM

    device = (await BleakScanner.find_device_by_address(args.address, timeout=args.scan)
              if args.address else await pick_device(args.scan))
    if device is None:
        sys.exit("device not found")

    print(f"connecting to {device.address} ({device.name}) ...")
    async with BleakClient(device) as client:
        print(f"connected, mtu={client.mtu_size}")
        if client.services.get_service(SVC) is None:
            sys.exit("OTA service not present")
        await client.start_notify(CH_NOTI, on_notify)

        out = bytearray()
        addr = args.addr
        remaining = args.size

        print(f"\nreading 0x{args.addr:08X} .. 0x{args.addr + args.size:08X} "
              f"with opcode 0x{opcode:02X}\n")

        while remaining > 0:
            want = min(remaining, MAX_CHUNK)
            req = max(want, MIN_READ)          # over-read, then trim
            blk = await read_mem(client, addr + len(out), req, opcode)
            if blk is None:
                print("\nstopping — the device did not return data")
                break
            out += blk[:want]
            remaining -= want

        await client.stop_notify(CH_NOTI)

        if not out:
            sys.exit("nothing read")

        print(f"got {len(out)} bytes:\n")
        dump(args.addr, bytes(out), args.u16, args.u32)

        if args.out:
            open(args.out, "wb").write(bytes(out))
            print(f"\nwrote {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
