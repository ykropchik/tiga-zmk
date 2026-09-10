#!/usr/bin/env python3
"""
Map the flash of a FreqChip FR800x device over BLE (Zoom75 TIGA display module).

Reads a small probe from each step across the address space and classifies it:
erased, all-zero, firmware header, text, or data. Prints a map and writes a CSV.

READ-ONLY. Only opcodes 0x01/0x02/0x06 are used. Nothing is erased or written.

Requires:  pip install bleak

Usage:
    python ota_scan.py                        scan 0..16 MB, 64 KB step
    python ota_scan.py --end 0x100000         first megabyte only
    python ota_scan.py --step 0x1000          finer resolution (slower)
    python ota_scan.py --probe 64             bytes read at each step
    python ota_scan.py --address 04:75:79:FB:DD:E7
"""

import argparse
import asyncio
import csv
import sys
import time

from bleak import BleakClient, BleakScanner

SVC = "02f00000-0000-0000-0000-00000000fe00"
CH_TX = "02f00000-0000-0000-0000-00000000ff00"
CH_RX = "02f00000-0000-0000-0000-00000000ff01"
CH_NOTI = "02f00000-0000-0000-0000-00000000ff02"

CMD_GET_STR_BASE = 0x01
CMD_READ_FW_VER = 0x02
CMD_READ_DATA = 0x06

FW_MAGIC = bytes.fromhex("33333333")  # at offset +0x08 of a firmware header

inbox: asyncio.Queue = asyncio.Queue()


def on_notify(_sender, data: bytearray) -> None:
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


async def read_block(client, addr: int, size: int):
    payload = addr.to_bytes(4, "little") + size.to_bytes(2, "little")
    ack = await command(client, CMD_READ_DATA, payload)
    if ack is None or len(ack) < 2 or ack[0] != 0x00 or ack[1] != CMD_READ_DATA:
        return None
    data = bytes(await client.read_gatt_char(CH_TX))
    return data or None


def classify(data: bytes) -> tuple[str, str]:
    """Return (tag, note). Tag is a single char for the map line."""
    if not data:
        return "?", "no data"
    if all(b == 0xFF for b in data):
        return ".", "erased"
    if all(b == 0x00 for b in data):
        return "0", "zeros"

    if len(data) >= 12 and data[8:12] == FW_MAGIC:
        ver = int.from_bytes(data[0x18:0x1C], "little") if len(data) >= 0x1C else None
        size = int.from_bytes(data[4:8], "little") if len(data) >= 8 else None
        note = "FIRMWARE HEADER"
        if size is not None:
            note += f" image_size=0x{size:X}"
        if ver is not None:
            note += f" version={ver}"
        return "H", note

    printable = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    ratio = printable / len(data)
    if ratio > 0.85:
        text = bytes(b if 32 <= b < 127 else 46 for b in data[:32]).decode("ascii")
        return "T", f"text: {text}"

    distinct = len(set(data))
    if distinct <= 4:
        return "u", f"uniform, {distinct} distinct values"
    return "#", f"data, {distinct} distinct, entropy-ish"


async def pick_device(scan_time: float):
    print(f"scanning for {scan_time:.0f} s ...")
    found = await BleakScanner.discover(timeout=scan_time, return_adv=True)
    entries = sorted(found.values(),
                     key=lambda p: p[1].rssi if p[1].rssi is not None else -999,
                     reverse=True)
    if not entries:
        sys.exit("no BLE devices found")
    for i, (dev, adv) in enumerate(entries):
        print(f"  {i:>3}  {dev.address:<20} {adv.rssi:>5}  "
              f"{dev.name or adv.local_name or '(unnamed)'}")
    choice = input("\nnumber to connect (q to quit): ").strip()
    if not choice.isdigit() or not (0 <= int(choice) < len(entries)):
        sys.exit("cancelled")
    return entries[int(choice)][0]


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--address", help="BLE address; omit to scan and choose")
    ap.add_argument("--start", type=lambda v: int(v, 0), default=0x0)
    ap.add_argument("--end", type=lambda v: int(v, 0), default=0x1000000,
                    help="exclusive end address (default 16 MB)")
    ap.add_argument("--step", type=lambda v: int(v, 0), default=0x10000,
                    help="probe every N bytes (default 64 KB)")
    ap.add_argument("--probe", type=int, default=64,
                    help="bytes to read at each step (default 64)")
    ap.add_argument("--csv", default="flash_map.csv")
    ap.add_argument("--scan", type=float, default=10.0)
    args = ap.parse_args()

    if args.address:
        device = await BleakScanner.find_device_by_address(args.address,
                                                           timeout=args.scan)
        if device is None:
            sys.exit("device not found")
    else:
        device = await pick_device(args.scan)

    print(f"connecting to {device.address} ({device.name}) ...")
    async with BleakClient(device) as client:
        print(f"connected, mtu={client.mtu_size}")
        if client.services.get_service(SVC) is None:
            sys.exit("OTA service not present on this device")

        await client.start_notify(CH_NOTI, on_notify)

        ver = await command(client, CMD_READ_FW_VER, b"\x00" * 4)
        base = await command(client, CMD_GET_STR_BASE, b"\x00" * 4)
        if ver and len(ver) >= 8:
            print(f"firmware version: {int.from_bytes(ver[4:8], 'little')}")
        if base and len(base) >= 8:
            print(f"storage base:     0x{int.from_bytes(base[4:8], 'little'):08X}")

        steps = list(range(args.start, args.end, args.step))
        print(f"\nprobing {len(steps)} points, {args.probe} bytes each, "
              f"0x{args.start:X}..0x{args.end:X} step 0x{args.step:X}\n")

        rows = []
        started = time.time()
        interesting = []

        for n, addr in enumerate(steps):
            data = await read_block(client, addr, args.probe)
            tag, note = classify(data or b"")
            rows.append({"address": f"0x{addr:08X}", "tag": tag, "note": note,
                         "head": (data or b"")[:32].hex(" ")})

            if tag not in (".", "?"):
                interesting.append((addr, tag, note))
                print(f"  0x{addr:08X}  [{tag}]  {note}")
            if tag == "H":
                print(f"             {(data or b'')[:32].hex(' ')}")

            if (n + 1) % 32 == 0 or n + 1 == len(steps):
                done = n + 1
                el = time.time() - started
                rate = done / el if el else 0
                eta = (len(steps) - done) / rate if rate else 0
                print(f"    ... {done}/{len(steps)}  eta {eta:.0f}s", flush=True)

        await client.stop_notify(CH_NOTI)

        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["address", "tag", "note", "head"])
            w.writeheader()
            w.writerows(rows)

        # compact visual map, 64 cells per line
        print("\nmap  (. erased  0 zeros  H header  T text  # data  u uniform  ? none)")
        per_line = 64
        for i in range(0, len(rows), per_line):
            addr = args.start + i * args.step
            line = "".join(r["tag"] for r in rows[i:i + per_line])
            print(f"  0x{addr:08X}  {line}")

        print(f"\nnon-erased probes: {len(interesting)} of {len(rows)}")
        headers = [x for x in interesting if x[1] == "H"]
        if headers:
            print("\nfirmware headers found:")
            for addr, _, note in headers:
                print(f"  0x{addr:08X}  {note}")
        else:
            print("\nno additional firmware headers found in the scanned range")
        print(f"\nwrote {args.csv}")


if __name__ == "__main__":
    asyncio.run(main())
