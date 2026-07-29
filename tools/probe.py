#!/usr/bin/env python3
"""Live probe for SUNTEK SC-BLE fridges (BougeRV CRD2 V2.0 and likely rebadges).

Connects, subscribes to the FFF4 status characteristic, reassembles newline-framed
ASCII frames, and prints each one decoded — highlighting which fields changed since
the previous frame. That diff is the whole point: change one setting on the fridge
panel, see exactly which field moves.

Raw frames are appended to ../captures/ so nothing observed gets lost.

Usage:
    python3 probe.py                    # scan for SYZ-D, stream until Ctrl-C
    python3 probe.py --name FRIDGE      # different advertised name
    python3 probe.py --address <uuid>   # skip the scan
    python3 probe.py --list             # just show nearby BLE devices and exit

See PROTOCOL.md for the field map. Fields marked "?" there are what this tool is for.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import pathlib
import sys

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak is not installed.  pip install -r requirements.txt")

SERVICE_FFF0 = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_STATUS = "0000fff4-0000-1000-8000-00805f9b34fb"  # read/notify
CHAR_COMMAND = "0000fff1-0000-1000-8000-00805f9b34fb"  # write (format unknown)

DEFAULT_NAME = "SYZ-D"
CAPTURE_DIR = pathlib.Path(__file__).resolve().parent.parent / "captures"
LAST_FRAME = CAPTURE_DIR / "last-frame.txt"

# Field labels, in frame order after the /SC0/4/2 header. See PROTOCOL.md.
FIELDS = [
    "power",
    "temp_unit",
    "zone1_current",
    "zone2_current",
    "zone1_setpoint",
    "zone2_setpoint",
    "battery_protect",  # 1=L 2=M 3=H, matching the app's L/M/H selector
    "voltage",
    "run_mode",  # 2=Max, 1=Eco
    "unknown_10",  # constant 100 — hypothesis: battery %, untestable without the pack
    "unknown_11",  # constant 1 — hypothesis: external power present
    "firmware",  # b01 — matches "Firmware number" in the app
]

RESET, BOLD, DIM, YELLOW, GREEN = "\033[0m", "\033[1m", "\033[2m", "\033[33m", "\033[32m"


def interpret(name: str, raw: str, unit_field: str | None) -> str:
    """Human-readable gloss for a field, or '' when we have nothing to add."""
    if name == "power":
        return "on" if raw == "1" else "off" if raw == "0" else "?"
    if name == "temp_unit":
        return {"1": "°C", "2": "°F"}.get(raw, "? (unmapped)")
    if name == "run_mode":
        return {"2": "Max", "1": "Eco"}.get(raw, "? (unmapped)")
    if name == "battery_protect":
        return {"1": "L (9.6-10.9V)", "2": "M (10.1-11.4V)", "3": "H (11.1-12.4V)"}.get(
            raw, "? (unmapped)"
        )
    if name.endswith(("_current", "_setpoint")):
        unit = {"1": "°C", "2": "°F"}.get(unit_field or "", "°?")
        return f"{int(raw)}{unit}" if raw.lstrip("+-").isdigit() else "?"
    if name == "voltage":
        return f"{int(raw) / 10:.1f} V" if raw.isdigit() else "?"
    return ""


def render(header: str, fields: list[str], previous: list[str] | None) -> str:
    unit = fields[1] if len(fields) > 1 else None
    stamp = dt.datetime.now().strftime("%H:%M:%S")
    out = [f"{DIM}{stamp}{RESET}  {BOLD}{header}{RESET}"]

    for i, raw in enumerate(fields):
        name = FIELDS[i] if i < len(FIELDS) else f"extra_{i + 1}"
        gloss = interpret(name, raw, unit)
        gloss = f"  {DIM}{gloss}{RESET}" if gloss else ""

        changed = previous is not None and i < len(previous) and previous[i] != raw
        if changed:
            out.append(
                f"  {YELLOW}▸ {name:<16}{RESET} {DIM}{previous[i]}{RESET} "
                f"{YELLOW}→{RESET} {BOLD}{raw}{RESET}{gloss}"
            )
        else:
            out.append(f"    {name:<16} {raw}{gloss}")

    if previous is not None and len(previous) != len(fields):
        out.append(f"  {YELLOW}! field count changed: {len(previous)} → {len(fields)}{RESET}")
    return "\n".join(out)


class FrameReader:
    """Reassembles chunked notifications into newline-terminated frames.

    The status frame is ~47 bytes, well over the default 23-byte ATT MTU, so a single
    frame usually arrives as several notifications. Never assume 1 notify == 1 frame.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[str]:
        self._buf.extend(chunk)
        frames = []
        while b"\n" in self._buf:
            line, _, rest = bytes(self._buf).partition(b"\n")
            self._buf = bytearray(rest)
            text = line.decode("ascii", errors="replace").strip()
            if text:
                frames.append(text)
        return frames


async def find_device(name: str, timeout: float):
    print(f"Scanning for a device named {name!r} ...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, _adv: bool(d.name and name.lower() in d.name.lower()),
        timeout=timeout,
    )
    if device is None:
        sys.exit(
            f"No device matching {name!r} found.\n"
            "  - Is the fridge powered on and in range?\n"
            "  - Is the BougeRV app connected? It holds the single BLE slot — force-quit it.\n"
            "  - Try --list to see what is actually advertising."
        )
    return device


async def list_devices(timeout: float) -> None:
    for d in await BleakScanner.discover(timeout=timeout):
        print(f"  {d.address}  {d.name or '(no name)'}")


async def run(args: argparse.Namespace) -> None:
    if args.list:
        await list_devices(args.timeout)
        return

    target = args.address or await find_device(args.name, args.timeout)

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    logfile = CAPTURE_DIR / f"session-{dt.datetime.now():%Y%m%d-%H%M%S}.log"

    reader = FrameReader()
    got_one = asyncio.Event()

    # Baseline carries across runs. The fridge allows only one BLE connection, so
    # mapping app-only settings means: disconnect, change one thing in the app, quit
    # it, reconnect. Persisting the last frame makes that diff work anyway.
    previous: list[str] | None = None
    if LAST_FRAME.exists():
        saved = LAST_FRAME.read_text().strip()
        if saved.startswith("/SC"):
            previous = saved.split(",")[1:]
            age = dt.datetime.fromtimestamp(LAST_FRAME.stat().st_mtime)
            print(f"{DIM}Baseline from previous session ({age:%Y-%m-%d %H:%M:%S}).{RESET}")

    def show(frame: str, sink) -> None:
        nonlocal previous
        sink.write(f"{dt.datetime.now().isoformat()}  {frame}\n")
        sink.flush()

        parts = frame.split(",")
        if not parts[0].startswith("/SC"):
            print(f"{YELLOW}unrecognised frame:{RESET} {frame}")
            return
        header, fields = parts[0], parts[1:]
        print(render(header, fields, previous))
        print()
        previous = fields
        LAST_FRAME.write_text(frame + "\n")
        got_one.set()

    async with BleakClient(target) as client:
        print(f"{GREEN}Connected.{RESET}  Logging to {logfile}")
        if not args.once:
            print(
                f"{DIM}Change ONE setting at a time on the fridge panel and watch the "
                f"highlighted diff.  Ctrl-C to stop.{RESET}"
            )
        print()

        with logfile.open("a") as sink:
            # Prime with a direct read so there is a baseline before anything changes.
            with contextlib.suppress(Exception):
                for frame in reader.feed(bytes(await client.read_gatt_char(CHAR_STATUS)) + b"\n"):
                    show(frame, sink)

            await client.start_notify(
                CHAR_STATUS, lambda _h, data: [show(f, sink) for f in reader.feed(bytes(data))]
            )
            try:
                if args.once:
                    # The read above usually satisfies this instantly; otherwise wait
                    # for the ~4s heartbeat.
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(got_one.wait(), timeout=15)
                    return
                while client.is_connected:
                    await asyncio.sleep(1)
            finally:
                with contextlib.suppress(Exception):
                    await client.stop_notify(CHAR_STATUS)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default=DEFAULT_NAME, help=f"advertised name to match (default: {DEFAULT_NAME})")
    p.add_argument("--address", help="connect directly; skip the scan")
    p.add_argument("--timeout", type=float, default=15.0, help="scan timeout in seconds")
    p.add_argument("--once", action="store_true", help="grab a single frame and exit")
    p.add_argument("--list", action="store_true", help="list nearby BLE devices and exit")
    args = p.parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
