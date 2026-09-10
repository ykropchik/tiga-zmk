#!/usr/bin/env python3
"""
Download every HPLX image container from the display module's flash over BLE.

Walks the container chain, saves each one as a .bin and a .png, and can be
stopped and restarted at any point — already-downloaded containers are skipped.
Builds a contact sheet at the end.

READ-ONLY. Only opcode 0x06 is used. Nothing is erased or written.

Requires:  pip install bleak pillow

Usage:
    python hplx_grab.py                     download everything into ./images
    python hplx_grab.py --out shots         different output directory
    python hplx_grab.py --limit 20          only the first 20
    python hplx_grab.py --skip-render       .bin only, render later
    python hplx_grab.py --sheet-only        rebuild the contact sheet offline
"""

import argparse
import asyncio
import os
import struct
import sys
import time

MAGIC = b"HPLX"
HDR = 0x30

SVC = "02f00000-0000-0000-0000-00000000fe00"
CH_TX = "02f00000-0000-0000-0000-00000000ff00"
CH_RX = "02f00000-0000-0000-0000-00000000ff01"
CH_NOTI = "02f00000-0000-0000-0000-00000000ff02"
CMD_READ_DATA = 0x06

inbox: "asyncio.Queue" = None


def container_size_from_table(head: bytes, h: int) -> int:
    """True size = data_offset + max(row_offset + row_size).

    Rows are variable length: most are 8 + width*2, but some are longer
    (segmented / partially encoded), so the size cannot be computed from
    width and height alone.  head must contain the header plus the whole
    row table, i.e. at least 0x28 + h*8 bytes.
    """
    dat = struct.unpack_from("<I", head, 0x24)[0]
    tbl = struct.unpack_from("<I", head, 0x20)[0]
    end = 0
    for y in range(h):
        off, size = struct.unpack_from("<II", head, tbl + y * 8)
        end = max(end, off + size)
    return dat + end


def render(data: bytes, path: str) -> None:
    from PIL import Image
    w = struct.unpack_from("<I", data, 8)[0]
    h = struct.unpack_from("<I", data, 0x0C)[0]
    tbl = struct.unpack_from("<I", data, 0x20)[0]
    dat = struct.unpack_from("<I", data, 0x24)[0]
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        off, _ = struct.unpack_from("<II", data, tbl + y * 8)
        p = dat + off + 8
        for x in range(w):
            v = struct.unpack_from("<H", data, p + x * 2)[0]
            px[x, y] = (((v >> 11) & 0x1F) * 255 // 31,
                        ((v >> 5) & 0x3F) * 255 // 63,
                        (v & 0x1F) * 255 // 31)
    img.save(path)


def build_sheet(outdir: str, columns: int = 4) -> None:
    from PIL import Image
    files = sorted(f for f in os.listdir(outdir) if f.endswith(".png")
                   and f != "contact_sheet.png")
    if not files:
        print("no PNGs to assemble")
        return
    tiles = [Image.open(os.path.join(outdir, f)) for f in files]
    tw = max(t.width for t in tiles)
    th = max(t.height for t in tiles)
    rows = (len(tiles) + columns - 1) // columns
    pad = 6
    sheet = Image.new("RGB",
                      (columns * (tw + pad) + pad, rows * (th + pad) + pad),
                      (30, 30, 30))
    for i, t in enumerate(tiles):
        x = pad + (i % columns) * (tw + pad)
        y = pad + (i // columns) * (th + pad)
        sheet.paste(t, (x, y))
    path = os.path.join(outdir, "contact_sheet.png")
    sheet.save(path)
    print(f"contact sheet: {path}  ({len(tiles)} images)")


# ---------------------------------------------------------------- BLE plumbing

def on_notify(_s, data: bytearray) -> None:
    inbox.put_nowait(bytes(data))


async def read_block(client, addr: int, size: int):
    while not inbox.empty():
        inbox.get_nowait()
    payload = addr.to_bytes(4, "little") + size.to_bytes(2, "little")
    frame = bytes([CMD_READ_DATA]) + len(payload).to_bytes(2, "little") + payload
    await client.write_gatt_char(CH_RX, frame, response=False)
    try:
        ack = await asyncio.wait_for(inbox.get(), timeout=5.0)
    except asyncio.TimeoutError:
        return None
    if len(ack) < 2 or ack[0] != 0x00 or ack[1] != CMD_READ_DATA:
        return None
    data = bytes(await client.read_gatt_char(CH_TX))
    return data or None


async def read_range(client, addr: int, length: int, chunk: int, label: str) -> bytes:
    out = bytearray()
    t0 = time.time()
    MIN_READ = 32          # the module rejects very small reads (8 bytes fails)
    while len(out) < length:
        n = min(chunk, length - len(out))
        req = max(n, MIN_READ)          # over-read, then trim
        blk = None
        for attempt in range(8):
            blk = await read_block(client, addr + len(out), req)
            if blk is not None and len(blk) == req:
                break
            await asyncio.sleep(0.2 * (attempt + 1))
        if blk is None or len(blk) != req:
            raise IOError(f"read failed at 0x{addr + len(out):X} "
                          f"(requested {req} bytes)")
        out += blk[:n]
        el = time.time() - t0
        rate = len(out) / el if el else 0
        print(f"\r  {label}  {100*len(out)/length:5.1f}%  {rate:6.0f} B/s",
              end="", flush=True)
    print()
    return bytes(out)


async def pick_device(scan_time: float):
    from bleak import BleakScanner
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


async def main() -> None:
    global inbox
    from bleak import BleakClient, BleakScanner

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--address")
    ap.add_argument("--start", type=lambda v: int(v, 0), default=0x80000)
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--out", default="images")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--sheet-only", action="store_true")
    ap.add_argument("--scan", type=float, default=10.0)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if args.sheet_only:
        build_sheet(args.out)
        return

    inbox = asyncio.Queue()

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

        chunk = 240
        while chunk >= 32:
            p = await read_block(client, args.start, chunk)
            if p and len(p) == chunk:
                break
            chunk //= 2
        print(f"chunk size: {chunk}\n")

        addr = args.start
        total_bytes = 0
        t_start = time.time()

        for idx in range(args.limit):
            head = None
            for attempt in range(5):
                head = await read_block(client, addr, HDR)
                if head is not None and len(head) >= HDR:
                    break
                print(f"  header read retry {attempt + 1} at 0x{addr:X}")
                await asyncio.sleep(0.5)
            if head is None or len(head) < HDR:
                print(f"\nheader read failed at 0x{addr:X} after 5 attempts")
                break

            if head[:4] != MAGIC:
                # try to resync: the previous size may have been mispredicted
                found = None
                back = 128
                probe = await read_range(client, addr - back, 4096, chunk,
                                         f"resync @0x{addr:X}")
                hit = probe.find(MAGIC)
                if hit >= 0:
                    found = addr - back + hit
                if found is None:
                    print(f"\nchain ends at 0x{addr:X}")
                    print(f"  bytes there: {head[:16].hex(' ')}")
                    break
                print(f"  resynced: 0x{addr:X} -> 0x{found:X} "
                      f"({found - addr:+d} bytes)")
                addr = found
                head = await read_block(client, addr, HDR)
                if head is None or head[:4] != MAGIC:
                    print("  resync failed, stopping")
                    break

            w = struct.unpack_from("<I", head, 8)[0]
            h = struct.unpack_from("<I", head, 0x0C)[0]
            if not (0 < w <= 4096 and 0 < h <= 4096):
                print(f"\nimplausible {w}x{h} at 0x{addr:X} — stopping")
                break

            # need the full row table to know the real size
            need = 0x28 + h * 8
            try:
                table = await read_range(client, addr, need, chunk,
                                         f"idx {idx} table") \
                    if need > HDR else head
            except IOError as exc:
                print(f"\n  {exc}\n  stopping — rerun to resume from here")
                break
            size = container_size_from_table(table, h)
            # containers are padded with 0xFF up to a 4-byte boundary, and the
            # last row's size field sometimes under-reports its final span,
            # so this is only a starting guess — resync fixes the remainder
            size = (size + 3) & ~3
            stem = os.path.join(args.out, f"hplx_{idx:03d}_{w}x{h}")

            if os.path.exists(stem + ".bin") and \
                    os.path.getsize(stem + ".bin") == size:
                print(f"{idx:>4}  0x{addr:08X}  {w}x{h}  already have it")
                addr += size
                continue

            print(f"{idx:>4}  0x{addr:08X}  {w}x{h}  {size} bytes")
            try:
                blob = await read_range(client, addr, size, chunk, f"idx {idx}")
            except IOError as exc:
                print(f"\n  {exc}\n  stopping — rerun to resume from here")
                break

            open(stem + ".bin", "wb").write(blob)
            total_bytes += size
            if not args.skip_render:
                try:
                    render(blob, stem + ".png")
                except Exception as exc:
                    print(f"  render skipped: {exc}")

            addr += size

        await client.stop_notify(CH_NOTI)

        el = time.time() - t_start
        print(f"\ndownloaded {total_bytes} bytes this run in {el:.0f}s "
              f"({total_bytes/el if el else 0:.0f} B/s)")

    if not args.skip_render:
        build_sheet(args.out)


if __name__ == "__main__":
    asyncio.run(main())
