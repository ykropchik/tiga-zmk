#!/usr/bin/env python3
"""
Dump flash from a FreqChip FR800x device over BLE (Zoom75 TIGA display module).

READ-ONLY. Only opcodes 0x01/0x02/0x06 are used. Nothing is erased or written.

Requires:  pip install bleak

Usage:
    python ota_dump.py                          dump bank A (0x0 .. storage_base)
    python ota_dump.py --start 0 --length 0x32000
    python ota_dump.py --out fw_bankA.bin
    python ota_dump.py --address 04:75:79:FB:DD:E7
    python ota_dump.py --chunk 64               force a chunk size
"""

import argparse
import asyncio
import hashlib
import sys
import time

from bleak import BleakClient, BleakScanner

SVC = "02f00000-0000-0000-0000-00000000fe00"
CH_TX = "02f00000-0000-0000-0000-00000000ff00"   # read: payload lands here
CH_RX = "02f00000-0000-0000-0000-00000000ff01"   # write: commands
CH_NOTI = "02f00000-0000-0000-0000-00000000ff02"  # notify: acknowledgements

CMD_GET_STR_BASE = 0x01
CMD_READ_FW_VER = 0x02
CMD_READ_DATA = 0x06

CHUNK_CANDIDATES = (240, 224, 192, 128, 96, 64, 48, 32)

inbox: asyncio.Queue = asyncio.Queue()


def on_notify(_sender, data: bytearray) -> None:
    inbox.put_nowait(bytes(data))


def build(opcode: int, payload: bytes) -> bytes:
    return bytes([opcode]) + len(payload).to_bytes(2, "little") + payload


async def command(client: BleakClient, opcode: int, payload: bytes,
                  timeout: float = 5.0) -> bytes | None:
    while not inbox.empty():
        inbox.get_nowait()
    await client.write_gatt_char(CH_RX, build(opcode, payload), response=False)
    try:
        return await asyncio.wait_for(inbox.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def read_block(client: BleakClient, addr: int, size: int) -> bytes | None:
    """One READ_DATA round trip: command, acknowledgement, then GATT read."""
    payload = addr.to_bytes(4, "little") + size.to_bytes(2, "little")
    ack = await command(client, CMD_READ_DATA, payload)
    if ack is None or len(ack) < 2 or ack[0] != 0x00 or ack[1] != CMD_READ_DATA:
        return None
    data = bytes(await client.read_gatt_char(CH_TX))
    return data if data else None


async def probe_chunk(client: BleakClient, addr: int) -> int:
    """Find the largest block size the device will hand back in one go."""
    for size in CHUNK_CANDIDATES:
        data = await read_block(client, addr, size)
        if data and len(data) == size:
            print(f"chunk size: {size} bytes")
            return size
        got = len(data) if data else 0
        print(f"  {size} -> {got} bytes, trying smaller")
    sys.exit("no usable chunk size — device refuses reads")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--address", help="BLE address; omit to scan and choose")
    ap.add_argument("--start", type=lambda v: int(v, 0), default=0x0)
    ap.add_argument("--length", type=lambda v: int(v, 0), default=None,
                    help="bytes to read; default = storage base address")
    ap.add_argument("--chunk", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--scan", type=float, default=10.0)
    args = ap.parse_args()

    if args.address:
        device = await BleakScanner.find_device_by_address(args.address,
                                                           timeout=args.scan)
        if device is None:
            sys.exit("device not found")
    else:
        print(f"scanning for {args.scan:.0f} s ...")
        found = await BleakScanner.discover(timeout=args.scan, return_adv=True)
        entries = sorted(found.values(),
                         key=lambda p: p[1].rssi if p[1].rssi is not None else -999,
                         reverse=True)
        for i, (dev, adv) in enumerate(entries):
            print(f"  {i:>3}  {dev.address:<20} {adv.rssi:>5}  "
                  f"{dev.name or adv.local_name or '(unnamed)'}")
        choice = input("\nnumber to connect (q to quit): ").strip()
        if not choice.isdigit() or not (0 <= int(choice) < len(entries)):
            sys.exit("cancelled")
        device = entries[int(choice)][0]

    print(f"connecting to {device.address} ({device.name}) ...")
    async with BleakClient(device) as client:
        print(f"connected, mtu={client.mtu_size}")
        if client.services.get_service(SVC) is None:
            sys.exit("OTA service not present on this device")

        await client.start_notify(CH_NOTI, on_notify)

        ver = await command(client, CMD_READ_FW_VER, b"\x00" * 4)
        base = await command(client, CMD_GET_STR_BASE, b"\x00" * 4)
        version = int.from_bytes(ver[4:8], "little") if ver and len(ver) >= 8 else None
        storage = int.from_bytes(base[4:8], "little") if base and len(base) >= 8 else None
        print(f"firmware version: {version}")
        print(f"storage base:     0x{storage:08X}" if storage else "storage base: ?")

        length = args.length if args.length is not None else storage
        if not length:
            sys.exit("cannot determine length — pass --length explicitly")

        chunk = args.chunk or await probe_chunk(client, args.start)

        out = args.out or f"dump_0x{args.start:X}_0x{length:X}.bin"
        print(f"\nreading 0x{args.start:X} .. 0x{args.start + length:X} "
              f"({length} bytes) into {out}\n")

        buf = bytearray()
        addr = args.start
        end = args.start + length
        started = time.time()
        failures = 0

        while addr < end:
            size = min(chunk, end - addr)
            data = await read_block(client, addr, size)

            if data is None or len(data) != size:
                failures += 1
                if failures > 5:
                    print(f"\n!! giving up at 0x{addr:X} after repeated failures")
                    break
                print(f"\n   retry at 0x{addr:X} (got "
                      f"{len(data) if data else 0}/{size})")
                await asyncio.sleep(0.3)
                continue

            failures = 0
            buf += data
            addr += size

            done = addr - args.start
            elapsed = time.time() - started
            rate = done / elapsed if elapsed else 0
            eta = (length - done) / rate if rate else 0
            pct = 100 * done / length
            print(f"\r  0x{addr:06X}  {pct:5.1f}%  {rate:6.0f} B/s  "
                  f"eta {eta:4.0f}s", end="", flush=True)

        await client.stop_notify(CH_NOTI)

        with open(out, "wb") as fh:
            fh.write(buf)

        print(f"\n\nwrote {len(buf)} bytes to {out}")
        print(f"sha256: {hashlib.sha256(buf).hexdigest()}")
        if len(buf) != length:
            print(f"WARNING: incomplete — expected {length} bytes")

        blank = buf.count(0xFF)
        print(f"0xFF bytes: {blank} ({100 * blank / max(len(buf), 1):.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
