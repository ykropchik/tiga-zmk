#!/usr/bin/env python3
"""
Validate the BLE OTA write path (erase -> write -> read back -> erase again)
on a small, known-empty patch of flash on the Zoom75 TIGA display module.

This is a METHOD TEST, not an image uploader. It never touches anything but
a single 4 KB page deep inside the confirmed-empty tail of flash (see
docs/STAGE1_DISPLAY_MODULE.md §4.6: 0x929940-0xFFFFFF is erased/free, ~6 MB).
By default it targets 0xC00000, roughly the middle of that free range —
deliberately not the very last page. Where NVDS/MAC/calibration data actually
lives is still an open question (§4.5/§4.6 open questions 12-13; `0x60000`
reads as erased despite being the documented MAC location, and NVDS_TYPE
returns an unrecognised value), and on this class of chip such data commonly
sits in the top-most sector(s) of flash even where undocumented — so the
default deliberately keeps ~2.8 MB of margin from the end of the real HPLX
chain (0x929940) and a full 4 MB of margin from the top of the 16 MB part
(0x1000000).

Uses opcodes 0x01 GET_STR_BASE, 0x02 READ_FW_VER, 0x03 PAGE_ERASE,
0x05 WRITE_DATA, 0x06 READ_DATA. 0x04 CHIP_ERASE and 0x09 REBOOT are
deliberately NOT defined anywhere in this file. Do not add them.

Safety, enforced in code, not just in this comment:
  - hard floor at 0x80000 (start of the resource area; nothing below this is
    ever a valid target, no flag can override it)
  - default target range restricted to the confirmed-empty tail
    (0x929940-0xFFFFFF); --address outside that range is refused unless
    --force is also given, and --force still cannot cross the 0x80000 floor
  - target address must be 4 KB-aligned (PAGE_ERASE works in 4 KB units)
  - interactive y/n confirmation before touching flash, unless --yes is given

Requires:  pip install bleak

Usage:
    python ota_write_test.py                      scan, confirm, run the test
    python ota_write_test.py 04:75:79:FB:DD:E7     connect straight to an address
    python ota_write_test.py --address 0xA00000    pick a different page (still checked)
    python ota_write_test.py --yes                 skip the interactive prompt
"""

import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner

# --- FreqChip stock OTA service (components/ble/profiles/ble_ota) ----------

SVC = "02f00000-0000-0000-0000-00000000fe00"
CH_TX = "02f00000-0000-0000-0000-00000000ff00"    # read: payload lands here
CH_RX = "02f00000-0000-0000-0000-00000000ff01"    # write: commands
CH_NOTI = "02f00000-0000-0000-0000-00000000ff02"  # notify: acknowledgements

# --- opcodes actually used here (from ota.h) --------------------------------
# 0x04 CHIP_ERASE and 0x09 REBOOT are intentionally absent — this script has
# no business ever sending them.

CMD_GET_STR_BASE = 0x01
CMD_READ_FW_VER = 0x02
CMD_PAGE_ERASE = 0x03
CMD_WRITE_DATA = 0x05
CMD_READ_DATA = 0x06

RSP = {0x00: "SUCCESS", 0x01: "ERROR", 0x02: "UNKNOWN_CMD"}

# --- safety constants --------------------------------------------------------

HARD_FLOOR = 0x80000          # absolute, non-overridable: start of the resource area
SAFE_START = 0x929940         # end of the real HPLX chain, per §4.6
SAFE_END = 0x1000000          # 16 MB, end of flash
PAGE_SIZE = 0x1000            # PAGE_ERASE granularity

DEFAULT_ADDRESS = 0xC00000    # ~middle of the free region — margin from both the end of the
                               # HPLX chain and the top of flash (possible NVDS/calibration area)

# Deterministic, easy-to-eyeball test payload: an ASCII marker followed by a
# short byte ramp. Same content every run, so a read-back mismatch is obvious.
TEST_DATA = b"TIGA-OTA-WRITE-TEST\x00" + bytes((i * 7 + 3) & 0xFF for i in range(48))

inbox: "asyncio.Queue" = asyncio.Queue()


def build(opcode: int, payload: bytes) -> bytes:
    """Request frame: Opcode(1) | Length(2, LE) | Payload"""
    return bytes([opcode]) + len(payload).to_bytes(2, "little") + payload


def on_notify(_sender, data: bytearray) -> None:
    inbox.put_nowait(bytes(data))


async def command(client: BleakClient, opcode: int, payload: bytes,
                  timeout: float = 5.0, response: bool = False) -> bytes | None:
    while not inbox.empty():
        inbox.get_nowait()
    await client.write_gatt_char(CH_RX, build(opcode, payload), response=response)
    try:
        return await asyncio.wait_for(inbox.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


def check_result(rsp: bytes | None, opcode: int, label: str) -> bool:
    if rsp is None:
        print(f"  !! {label}: no notification within timeout")
        return False
    if len(rsp) < 2:
        print(f"  !! {label}: response too short ({rsp.hex(' ')})")
        return False
    result, org_opcode = rsp[0], rsp[1]
    if result != 0x00:
        print(f"  !! {label}: result={RSP.get(result, hex(result))}")
        return False
    if org_opcode != opcode:
        print(f"  !! {label}: opcode mismatch, expected 0x{opcode:02X} got 0x{org_opcode:02X}")
        return False
    return True


async def erase_page(client: BleakClient, addr: int) -> bool:
    print(f"\n[0x03 PAGE_ERASE] @0x{addr:X}")
    rsp = await command(client, CMD_PAGE_ERASE, addr.to_bytes(4, "little"))
    ok = check_result(rsp, CMD_PAGE_ERASE, "PAGE_ERASE")
    print(f"  {'ok' if ok else 'FAILED'}")
    return ok


async def write_data(client: BleakClient, addr: int, data: bytes, chunk: int) -> bool:
    print(f"\n[0x05 WRITE_DATA] @0x{addr:X} len={len(data)} chunk={chunk}")
    pos = 0
    while pos < len(data):
        block = data[pos:pos + chunk]
        cur_addr = addr + pos
        payload = cur_addr.to_bytes(4, "little") + len(block).to_bytes(2, "little") + block
        # Write WITH response (GATT Write Request, ATT-acknowledged) — unlike the small
        # erase/read commands (a handful of bytes), this frame is large enough (~70+ bytes
        # here, more for bigger payloads) that plain Write Without Response has been observed
        # to be silently dropped in practice, leaving the notification wait to time out with
        # nothing actually sent. ff01 advertises both WRITE and WRITE NO RESP
        # (docs/STAGE1_DISPLAY_MODULE.md §4.2), so the acknowledged mode is available.
        rsp = await command(client, CMD_WRITE_DATA, payload, response=True)
        if not check_result(rsp, CMD_WRITE_DATA, f"WRITE_DATA @0x{cur_addr:X}"):
            return False
        pos += len(block)
    print("  ok")
    return True


async def read_data(client: BleakClient, addr: int, length: int) -> bytes | None:
    """One READ_DATA round trip: command, acknowledgement, then GATT read."""
    payload = addr.to_bytes(4, "little") + length.to_bytes(2, "little")
    rsp = await command(client, CMD_READ_DATA, payload)
    if not check_result(rsp, CMD_READ_DATA, f"READ_DATA @0x{addr:X}"):
        return None
    return bytes(await client.read_gatt_char(CH_TX))


# Candidates for the largest single READ_DATA block the device/MTU will hand back
# in one round trip (same list ota_dump.py uses; single reads bigger than the
# negotiated MTU get silently truncated, not rejected, so this must be probed).
READ_CHUNK_CANDIDATES = (240, 224, 192, 128, 96, 64, 48, 32)


async def probe_read_chunk(client: BleakClient, addr: int) -> int:
    """Find the largest block size READ_DATA will hand back whole, at addr."""
    for size in READ_CHUNK_CANDIDATES:
        data = await read_data(client, addr, size)
        if data and len(data) == size:
            print(f"  read chunk size: {size} bytes")
            return size
    sys.exit("no usable READ_DATA chunk size — device refuses reads, stopping")


async def read_full(client: BleakClient, addr: int, size: int, chunk: int) -> bytes | None:
    """Read exactly `size` bytes starting at addr, in `chunk`-sized blocks, with
    a few retries per block. Used to see an ENTIRE flash page before erasing it —
    a partial read at offset 0 only is not enough to call a 4 KB page blank."""
    buf = bytearray()
    pos = 0
    while pos < size:
        block_len = min(chunk, size - pos)
        data = None
        for _attempt in range(3):
            data = await read_data(client, addr + pos, block_len)
            if data and len(data) == block_len:
                break
            await asyncio.sleep(0.2)
        if not data or len(data) != block_len:
            print(f"  !! read failed at 0x{addr + pos:X} after retries")
            return None
        buf += data
        pos += block_len
    return bytes(buf)


def validate_address(addr: int, force: bool) -> None:
    if addr % PAGE_SIZE != 0:
        sys.exit(f"address 0x{addr:X} is not 4 KB-aligned — refusing")
    if addr < HARD_FLOOR:
        sys.exit(f"address 0x{addr:X} is below the hard floor 0x{HARD_FLOOR:X} "
                 f"(resource area start) — refusing, no override exists for this")
    if not (SAFE_START <= addr < SAFE_END):
        if not force:
            sys.exit(f"address 0x{addr:X} is outside the confirmed-empty range "
                     f"0x{SAFE_START:X}-0x{SAFE_END:X} (§4.6) — pass --force to override "
                     f"(still refused below 0x{HARD_FLOOR:X})")
        print(f"  !! --force: writing outside the confirmed-empty range, "
              f"at your own risk (0x{addr:X})")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address_arg", nargs="?", metavar="BLE_ADDRESS",
                    help="BLE address; omit to scan and choose from a list")
    ap.add_argument("--address", type=lambda v: int(v, 0), default=DEFAULT_ADDRESS,
                    help=f"flash target, 4 KB-aligned (default 0x{DEFAULT_ADDRESS:X})")
    ap.add_argument("--force", action="store_true",
                    help="allow a target outside the confirmed-empty tail (still >= 0x80000)")
    ap.add_argument("--yes", action="store_true",
                    help="skip the interactive confirmation prompt")
    ap.add_argument("--scan", type=float, default=10.0, metavar="SECONDS")
    args = ap.parse_args()

    validate_address(args.address, args.force)
    target = args.address

    print("=" * 70)
    print("BLE OTA WRITE-PATH TEST")
    print("=" * 70)
    print(f"target address : 0x{target:X}")
    print(f"test data       : {len(TEST_DATA)} bytes, {TEST_DATA[:20]!r}...")
    print("sequence        : read first and abort if not blank -> erase page -> write test")
    print("                  data -> read back and compare -> erase page again -> read back")
    print("                  and confirm blank (0xFF)")
    print()
    print("This WILL erase and write one 4 KB flash page on the connected device")
    print("(but only after confirming, by reading it, that it is already blank).")

    if not args.yes:
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            sys.exit("cancelled")

    if args.address_arg:
        print(f"\nlooking for {args.address_arg} ...")
        device = await BleakScanner.find_device_by_address(args.address_arg,
                                                            timeout=args.scan)
        if device is None:
            sys.exit("not found — is it powered and not connected elsewhere?")
    else:
        print(f"\nscanning for {args.scan:.0f} s ...")
        found = await BleakScanner.discover(timeout=args.scan, return_adv=True)
        entries = sorted(found.values(),
                         key=lambda p: p[1].rssi if p[1].rssi is not None else -999,
                         reverse=True)
        if not entries:
            sys.exit("no BLE devices found at all — is Bluetooth on?")
        for i, (dev, adv) in enumerate(entries):
            mark = "  <-- has OTA service" if any(
                u.lower().endswith("fe00") for u in (adv.service_uuids or [])
            ) else ""
            print(f"  {i:>3}  {dev.address:<20} {adv.rssi:>5}  "
                  f"{dev.name or adv.local_name or '(unnamed)'}{mark}")
        choice = input("\nnumber to connect (q to quit): ").strip()
        if not choice.isdigit() or not (0 <= int(choice) < len(entries)):
            sys.exit("cancelled")
        device = entries[int(choice)][0]

    print(f"\nconnecting to {device.address} ({device.name}) ...")
    async with BleakClient(device) as client:
        print(f"connected, mtu={client.mtu_size}")
        if client.services.get_service(SVC) is None:
            sys.exit("OTA service not present on this device")

        await client.start_notify(CH_NOTI, on_notify)

        ver = await command(client, CMD_READ_FW_VER, b"\x00" * 4)
        base = await command(client, CMD_GET_STR_BASE, b"\x00" * 4)
        version = int.from_bytes(ver[4:8], "little") if ver and len(ver) >= 8 else None
        storage = int.from_bytes(base[4:8], "little") if base and len(base) >= 8 else None
        print(f"firmware version : {version}")
        print(f"storage base      : 0x{storage:08X}" if storage else "storage base: ?")
        # storage_base is a DIFFERENT, much lower threshold than HARD_FLOOR above — it is
        # the SDK's own bank-B address (ota.c: app_otas_get_storage_address(), measured at
        # 0x32000 in phase 0.5), the point below which the device itself refuses PAGE_ERASE
        # and disconnects. HARD_FLOOR (0x80000) is our own, unrelated, much stricter floor —
        # the start of the real resource area. This check only guards against storage_base
        # somehow being reported above our target, which validate_address() already makes
        # very unlikely (target is always >= 0x80000, storage_base has never been seen above
        # the ~0x32000-0x64000 firmware-bank range) — a cheap extra sanity check, not the
        # real safety boundary.
        if storage and target < storage:
            sys.exit(f"target 0x{target:X} is below the device's own storage base "
                     f"0x{storage:X} — the device will disconnect on PAGE_ERASE, refusing to try")

        # Chunk WRITE_DATA to fit one ATT write: opcode+len(3) + base_addr+len(6) = 9 bytes overhead
        write_chunk = max(1, client.mtu_size - 3 - 9)

        print(f"\nprobing READ_DATA chunk size @0x{target:X}")
        read_chunk = await probe_read_chunk(client, target)

        # --- step 0: read the WHOLE page BEFORE touching anything -------------
        # PAGE_ERASE erases all 4096 bytes. A partial read at offset 0 only can
        # miss something that lives further into the page (a header in the
        # middle, data near the end, ...) and falsely call the page blank right
        # before erasing all of it. So the pre-check must cover the full page,
        # not just the first few dozen bytes.
        print(f"\n[pre-check] reading the FULL 4 KB page @0x{target:X} "
              f"before doing anything destructive")
        before = await read_full(client, target, PAGE_SIZE, read_chunk)
        if before is None:
            sys.exit("pre-check read failed — stopping before touching flash")
        if any(b != 0xFF for b in before):
            first_bad = next(i for i, b in enumerate(before) if b != 0xFF)
            print(f"  first non-0xFF byte at offset 0x{first_bad:X}: "
                  f"{before[first_bad:first_bad + 16].hex(' ')}")
            sys.exit(f"\n!! target 0x{target:X} is NOT blank — refusing to erase or write.\n"
                     f"   Either the free-region assumption is wrong for this address, or\n"
                     f"   something real lives here. Investigate before touching it.")
        print("  ok, entire page confirmed blank (all 4096 bytes) — safe to proceed")

        ok = True

        # --- step 1: erase --------------------------------------------------
        ok = ok and await erase_page(client, target)

        # --- step 2: confirm the WHOLE page is blank after erase --------------
        if ok:
            blank_check = await read_full(client, target, PAGE_SIZE, read_chunk)
            if blank_check is None:
                ok = False
            else:
                all_ff = all(b == 0xFF for b in blank_check)
                print(f"  {'ok, entire page is 0xFF' if all_ff else '!! not blank after erase'}")
                ok = ok and all_ff

        # --- step 3: write ----------------------------------------------------
        if ok:
            write_acked = await write_data(client, target, TEST_DATA, write_chunk)
            if not write_acked:
                print("\n  no acknowledgement for WRITE_DATA — that alone does not prove")
                print("  nothing was written. Reading the page back anyway to find out")
                print("  whether the data landed and only the notification is missing.")

            # --- step 4: read back and compare, REGARDLESS of whether WRITE_DATA
            # acked. A missing notification is not proof the write itself failed —
            # only the actual flash contents can settle that.
            readback = await read_full(client, target, PAGE_SIZE, read_chunk)
            if readback is None:
                print("  !! read-back failed too — cannot tell whether the write landed")
                ok = False
            else:
                region = readback[:len(TEST_DATA)]
                rest = readback[len(TEST_DATA):]
                matches = region == TEST_DATA
                rest_blank = all(b == 0xFF for b in rest)

                print(f"  target region : {region.hex(' ')}")
                if not matches:
                    print(f"  expected      : {TEST_DATA.hex(' ')}")
                print(f"  rest of page  : {'still 0xFF' if rest_blank else '!! NOT 0xFF — unexpected'}")

                if write_acked and matches:
                    print("  ok — write path fully verified (data landed AND was acknowledged)")
                elif (not write_acked) and matches:
                    print("\n  !! DATA WAS WRITTEN despite no acknowledgement.")
                    print("     Conclusion: the flash write itself works — the WRITE_DATA")
                    print("     notification path specifically is what's broken or unreliable.")
                elif write_acked and not matches:
                    print("  !! acknowledged, but the data does not match — unexpected, investigate")
                else:
                    print("  confirmed: nothing was written (consistent with the earlier timeout)")

                ok = ok and matches and rest_blank

        # --- step 5: erase again, leave the WHOLE page blank -------------------
        cleaned = await erase_page(client, target)
        if cleaned:
            final = await read_full(client, target, PAGE_SIZE, read_chunk)
            if final is not None:
                all_ff = all(b == 0xFF for b in final)
                print(f"  {'ok, entire page left blank' if all_ff else '!! page NOT left blank'}")
                ok = ok and all_ff

        await client.stop_notify(CH_NOTI)

        print("\n" + "=" * 70)
        print("RESULT: " + ("PASS — erase/write/read-back all work as documented" if ok
                            else "FAIL — see the messages above"))
        print("=" * 70)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
