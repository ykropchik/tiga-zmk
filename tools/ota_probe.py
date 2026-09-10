#!/usr/bin/env python3
"""
Probe the FreqChip OTA service on a BLE device (e.g. the Zoom75 TIGA display module).

READ-ONLY. This script never erases, writes or reboots the target.
It only issues informational OTA commands and one small test read.

Requires:  pip install bleak

Usage:
    python ota_probe.py                  scan and pick from a list
    python ota_probe.py 04:75:79:FB:DD:E7   connect straight to an address
    python ota_probe.py --scan 20        longer scan window
"""

import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner

# --- FreqChip stock OTA service (components/ble/profiles/ble_ota) ----------

SVC = "02f00000-0000-0000-0000-00000000fe00"
CH_TX = "02f00000-0000-0000-0000-00000000ff00"
CH_RX = "02f00000-0000-0000-0000-00000000ff01"  # write: commands
CH_NOTI = "02f00000-0000-0000-0000-00000000ff02"  # notify: responses
CH_VER = "02f00000-0000-0000-0000-00000000ff03"  # read: version info

# --- opcodes (from ota.h) --------------------------------------------------

CMD_NVDS_TYPE = 0x00
CMD_GET_STR_BASE = 0x01
CMD_READ_FW_VER = 0x02
CMD_READ_DATA = 0x06
# 0x03 PAGE_ERASE, 0x04 CHIP_ERASE, 0x05 WRITE_DATA, 0x09 REBOOT
# are deliberately NOT defined here. Do not add them to this script.

RSP = {0x00: "SUCCESS", 0x01: "ERROR", 0x02: "UNKNOWN_CMD"}

inbox: asyncio.Queue = asyncio.Queue()


def build(opcode: int, payload: bytes = b"\x00\x00\x00\x00") -> bytes:
    """Request frame: Opcode(1) | Length(2, LE) | Payload"""
    return bytes([opcode]) + len(payload).to_bytes(2, "little") + payload


def show(tag: str, data: bytes) -> None:
    print(f"  {tag} {data.hex(' ')}")


def parse(data: bytes) -> None:
    """Response frame: Result(1) | Opcode(1) | Length(2, LE) | Payload"""
    if len(data) < 4:
        print("  !! response too short")
        return
    result, opcode = data[0], data[1]
    length = int.from_bytes(data[2:4], "little")
    payload = data[4:]
    print(f"  -> result={RSP.get(result, hex(result))} "
          f"opcode=0x{opcode:02X} len={length} payload={payload.hex(' ')}")


def on_notify(_sender, data: bytearray) -> None:
    show("NOTI", bytes(data))
    inbox.put_nowait(bytes(data))


async def ask(client: BleakClient, opcode: int, payload: bytes = b"\x00\x00\x00\x00",
              label: str = "") -> bytes | None:
    """Send one OTA command and wait for the notification."""
    frame = build(opcode, payload)
    print(f"\n[{label or hex(opcode)}]")
    show("TX  ", frame)
    while not inbox.empty():
        inbox.get_nowait()
    await client.write_gatt_char(CH_RX, frame, response=False)
    try:
        data = await asyncio.wait_for(inbox.get(), timeout=5.0)
    except asyncio.TimeoutError:
        print("  !! no notification within 5 s")
        return None
    parse(data)
    return data


async def pick_device(scan_time: float):
    """Scan and let the user choose a device from a numbered list."""
    print(f"scanning for {scan_time:.0f} s ...")
    found = await BleakScanner.discover(timeout=scan_time, return_adv=True)

    entries = sorted(
        found.values(),
        key=lambda pair: (pair[1].rssi if pair[1].rssi is not None else -999),
        reverse=True,
    )
    if not entries:
        sys.exit("no BLE devices found at all — is Bluetooth on?")

    print(f"\n{len(entries)} device(s), strongest first:\n")
    print(f"  {'#':>3}  {'address':<20} {'rssi':>5}  name")
    print(f"  {'-'*3}  {'-'*20} {'-'*5}  {'-'*24}")
    for i, (dev, adv) in enumerate(entries):
        name = dev.name or adv.local_name or "(unnamed)"
        rssi = f"{adv.rssi}" if adv.rssi is not None else "  ?"
        mark = "  <-- has OTA service" if any(
            u.lower().endswith("fe00") for u in (adv.service_uuids or [])
        ) else ""
        print(f"  {i:>3}  {dev.address:<20} {rssi:>5}  {name}{mark}")

    while True:
        choice = input("\nnumber to connect (q to quit): ").strip()
        if choice.lower() in ("q", "quit", ""):
            sys.exit("cancelled")
        if choice.isdigit() and 0 <= int(choice) < len(entries):
            return entries[int(choice)][0]
        print("  not a valid number")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("address", nargs="?",
                    help="BLE address; omit to scan and choose from a list")
    ap.add_argument("--scan", type=float, default=10.0,
                    metavar="SECONDS", help="scan window (default 10)")
    args = ap.parse_args()

    if args.address:
        print(f"looking for {args.address} ...")
        device = await BleakScanner.find_device_by_address(args.address,
                                                           timeout=args.scan)
        if device is None:
            sys.exit("not found — is it powered and not connected elsewhere?")
    else:
        device = await pick_device(args.scan)

    print(f"\nconnecting to {device.address} ({device.name}) ...")
    async with BleakClient(device) as client:
        print(f"connected, mtu={client.mtu_size}")

        services = client.services
        if services.get_service(SVC) is None:
            print("\nservices present:")
            for s_ in services:
                print(f"  {s_.uuid}")
            sys.exit("\nOTA service 02f0...fe00 not present on this device — stop here")

        print("\nservices:")
        for s in services:
            print(f"  {s.uuid}")
            for c in s.characteristics:
                print(f"    {c.uuid}  {','.join(c.properties)}")

        # --- plain GATT reads, no commands involved ------------------------
        for uuid, label in ((CH_VER, "ff03 version_info"), (CH_TX, "ff00 tx")):
            try:
                val = await client.read_gatt_char(uuid)
                print(f"\nread {label}: {bytes(val).hex(' ')}  {bytes(val)!r}")
            except Exception as exc:
                print(f"\nread {label} failed: {exc}")

        await client.start_notify(CH_NOTI, on_notify)

        # --- informational commands ---------------------------------------
        ver = await ask(client, CMD_READ_FW_VER, label="0x02 READ_FW_VER")
        if ver is None:
            print("\nThe OTA service does not answer commands. "
                  "No backup path over BLE. Stop and reassess.")
            await client.stop_notify(CH_NOTI)
            return

        await ask(client, CMD_NVDS_TYPE, label="0x00 NVDS_TYPE")
        base_rsp = await ask(client, CMD_GET_STR_BASE, label="0x01 GET_STR_BASE")

        base = 0
        if base_rsp and len(base_rsp) >= 8 and base_rsp[0] == 0x00:
            base = int.from_bytes(base_rsp[4:8], "little")
            print(f"  storage base address = 0x{base:08X}")

        # --- the decisive test: can we read flash back? --------------------
        print("\n" + "=" * 60)
        print("TEST READ — this determines whether a backup is possible")
        print("=" * 60)

        for addr in (0x00000000, 0x00060000):
            payload = addr.to_bytes(4, "little") + (32).to_bytes(2, "little")
            rsp = await ask(client, CMD_READ_DATA, payload,
                            label=f"0x06 READ_DATA @0x{addr:X} len=32")

            # The notification for READ_DATA is only an acknowledgement echoing
            # base_addr + length. Per ota.c the payload itself is handed over via
            # a plain GATT Read on one of the readable characteristics.
            for uuid, tag in ((CH_TX, "ff00"), (CH_NOTI, "ff02"),
                              (CH_VER, "ff03")):
                try:
                    val = bytes(await client.read_gatt_char(uuid))
                except Exception as exc:
                    print(f"  read {tag} failed: {exc}")
                    continue
                if not val:
                    print(f"  read {tag}: empty")
                    continue
                print(f"  read {tag}: {val.hex(' ')}")
                printable = bytes(c if 32 <= c < 127 else 46 for c in val)
                print(f"          {printable.decode('ascii')}")

        await client.stop_notify(CH_NOTI)
        print("\ndone — nothing was written or erased")


if __name__ == "__main__":
    asyncio.run(main())
