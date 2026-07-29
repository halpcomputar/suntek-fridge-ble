"""Frame parsing for SUNTEK SC-BLE fridges.

Deliberately free of Home Assistant imports so it can be tested standalone.
See PROTOCOL.md at the repo root for the field map and how it was established.
"""

from __future__ import annotations

from dataclasses import dataclass

FRAME_PREFIX = "/SC"
TERMINATOR = b"\n"

# Field 2. Whichever unit the fridge is displaying is the unit it reports in.
UNIT_CELSIUS = "1"
UNIT_FAHRENHEIT = "2"

# Field 7, matching the app's L/M/H selector and its documented cut-off bands.
BATTERY_PROTECTION = {"1": "low", "2": "medium", "3": "high"}

# Field 9.
RUN_MODE = {"1": "eco", "2": "max"}

# Header plus 12 fields.
EXPECTED_PARTS = 13


class FrameError(ValueError):
    """Raised when a frame cannot be parsed."""


@dataclass(frozen=True, slots=True)
class FridgeStatus:
    """One decoded status frame.

    Temperatures are normalised to Celsius regardless of what unit the fridge is
    displaying, so Home Assistant can present them in the user's preferred unit
    without the native unit changing underneath long-term statistics.
    """

    powered: bool
    displays_fahrenheit: bool
    zone1_temp: float
    zone2_temp: float
    zone1_setpoint: float
    zone2_setpoint: float
    battery_protection: str | None
    voltage: float
    run_mode: str | None
    firmware: str
    raw: str


def to_celsius(reading: int, from_fahrenheit: bool) -> float:
    """Convert a raw integer temperature to Celsius."""
    if from_fahrenheit:
        return round((reading - 32) * 5 / 9, 1)
    return float(reading)


def parse_frame(frame: str) -> FridgeStatus:
    """Decode one status frame.

    Raises FrameError on anything unexpected rather than guessing — a malformed
    frame should surface, not silently become plausible-looking sensor values.
    """
    text = frame.strip()
    if not text.startswith(FRAME_PREFIX):
        raise FrameError(f"missing {FRAME_PREFIX!r} prefix: {text!r}")

    parts = text.split(",")
    if len(parts) != EXPECTED_PARTS:
        raise FrameError(f"expected {EXPECTED_PARTS} parts, got {len(parts)}: {text!r}")

    fields = parts[1:]
    try:
        fahrenheit = fields[1] == UNIT_FAHRENHEIT
        return FridgeStatus(
            powered=fields[0] == "1",
            displays_fahrenheit=fahrenheit,
            zone1_temp=to_celsius(int(fields[2]), fahrenheit),
            zone2_temp=to_celsius(int(fields[3]), fahrenheit),
            zone1_setpoint=to_celsius(int(fields[4]), fahrenheit),
            zone2_setpoint=to_celsius(int(fields[5]), fahrenheit),
            battery_protection=BATTERY_PROTECTION.get(fields[6]),
            voltage=int(fields[7]) / 10,
            run_mode=RUN_MODE.get(fields[8]),
            # Fields 10 and 11 are unidentified and constant on all known hardware;
            # see PROTOCOL.md. Not surfaced rather than guessed at.
            firmware=fields[11],
            raw=text,
        )
    except ValueError as err:
        raise FrameError(f"bad numeric field in {text!r}: {err}") from err


class FrameBuffer:
    """Reassembles chunked notifications into whole frames.

    A status frame is ~47 bytes, comfortably over the default 23-byte ATT MTU, so
    one notification is not one frame. Callers must feed every chunk through here.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[str]:
        """Add received bytes, returning any complete frames they finished."""
        self._buf.extend(chunk)
        frames: list[str] = []
        while TERMINATOR in self._buf:
            line, _, rest = bytes(self._buf).partition(TERMINATOR)
            self._buf = bytearray(rest)
            if text := line.decode("ascii", errors="replace").strip():
                frames.append(text)
        return frames

    def reset(self) -> None:
        """Drop partial data, e.g. after a reconnect."""
        self._buf.clear()
