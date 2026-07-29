"""Frame parsing and command building for SUNTEK SC-BLE fridges.

Deliberately free of Home Assistant imports so it can be tested standalone.
See PROTOCOL.md at the repo root for the field map and how it was established.
"""

from __future__ import annotations

from dataclasses import dataclass

FRAME_PREFIX = "/SC"
TERMINATOR = b"\n"

# Field 2 of the status frame, and the payload of the SC7 command.
# Whichever unit the fridge displays is the unit it reports *and* accepts.
UNIT_CELSIUS = "1"
UNIT_FAHRENHEIT = "2"

# Field 7, matching the app's L/M/H selector and its documented cut-off bands.
BATTERY_PROTECTION = {"1": "low", "2": "medium", "3": "high"}

# Field 9.
RUN_MODE = {"1": "eco", "2": "max"}

_BATTERY_PROTECTION_VALUES = {v: k for k, v in BATTERY_PROTECTION.items()}
_RUN_MODE_VALUES = {v: k for k, v in RUN_MODE.items()}

# Header plus 12 fields.
EXPECTED_PARTS = 13

# Command indices, all confirmed against a capture of the vendor app.
CMD_POWER = 1
CMD_ZONE1_SETPOINT = 3
CMD_BATTERY_PROTECTION = 4
CMD_ZONE2_SETPOINT = 5
CMD_RUN_MODE = 6
CMD_DISPLAY_UNIT = 7

# Advertised operating range of the reference hardware (BougeRV CRD2: -4°F to 68°F).
MIN_SETPOINT_C = -20
MAX_SETPOINT_C = 20


class FrameError(ValueError):
    """Raised when a frame cannot be parsed."""


@dataclass(frozen=True, slots=True)
class FridgeStatus:
    """One decoded status frame.

    Temperatures are carried twice on purpose. The `*_raw` ints are exactly what the
    fridge reported, in whatever unit it is currently displaying — that is the unit
    commands must be written in, so control needs them unmodified. The float fields
    are normalised to Celsius so sensors keep a stable native unit and long-term
    statistics survive the user flipping the fridge between °F and °C.
    """

    powered: bool
    displays_fahrenheit: bool
    zone1_temp: float
    zone2_temp: float
    zone1_setpoint: float
    zone2_setpoint: float
    zone1_temp_raw: int
    zone2_temp_raw: int
    zone1_setpoint_raw: int
    zone2_setpoint_raw: int
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
        raw = [int(fields[i]) for i in (2, 3, 4, 5)]
        return FridgeStatus(
            powered=fields[0] == "1",
            displays_fahrenheit=fahrenheit,
            zone1_temp=to_celsius(raw[0], fahrenheit),
            zone2_temp=to_celsius(raw[1], fahrenheit),
            zone1_setpoint=to_celsius(raw[2], fahrenheit),
            zone2_setpoint=to_celsius(raw[3], fahrenheit),
            zone1_temp_raw=raw[0],
            zone2_temp_raw=raw[1],
            zone1_setpoint_raw=raw[2],
            zone2_setpoint_raw=raw[3],
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


# --------------------------------------------------------------------------- #
#  Commands
# --------------------------------------------------------------------------- #
#
#  /SC<index>/1/<value>\n  — the "1" is the payload item count; every known
#  command carries exactly one. There is no checksum.
#
#  Enumerated values are zero-padded to three digits and reuse the *same*
#  vocabulary as the status frame. Temperatures are signed and zero-padded to
#  two digits, matching how the fridge reports them, and must be expressed in
#  the unit the fridge is currently displaying.


def build_command(index: int, value: str) -> bytes:
    """Assemble one command frame."""
    return f"/SC{index}/1/{value}\n".encode("ascii")


def _enum(value: int) -> str:
    return f"{value:03d}"


def _temperature(degrees: int) -> str:
    # "+35", "-01", and "+100" if a °F setpoint ever needs three digits.
    return f"{degrees:+03d}"


def set_power(on: bool) -> bytes:
    return build_command(CMD_POWER, _enum(1 if on else 0))


def set_setpoint(zone: int, degrees: int) -> bytes:
    """Set a zone's target. `degrees` must be in the fridge's displayed unit."""
    if zone not in (1, 2):
        raise ValueError(f"zone must be 1 or 2, got {zone}")
    index = CMD_ZONE1_SETPOINT if zone == 1 else CMD_ZONE2_SETPOINT
    return build_command(index, _temperature(degrees))


def set_run_mode(mode: str) -> bytes:
    if mode not in _RUN_MODE_VALUES:
        raise ValueError(f"unknown run mode {mode!r}")
    return build_command(CMD_RUN_MODE, _enum(int(_RUN_MODE_VALUES[mode])))


def set_battery_protection(level: str) -> bytes:
    if level not in _BATTERY_PROTECTION_VALUES:
        raise ValueError(f"unknown battery protection level {level!r}")
    return build_command(
        CMD_BATTERY_PROTECTION, _enum(int(_BATTERY_PROTECTION_VALUES[level]))
    )


def set_display_unit(fahrenheit: bool) -> bytes:
    """Change the unit shown on the fridge's own panel.

    This also changes the unit of every temperature in the status frame and the
    unit setpoint commands must use, so callers must re-read before writing.
    """
    unit = UNIT_FAHRENHEIT if fahrenheit else UNIT_CELSIUS
    return build_command(CMD_DISPLAY_UNIT, _enum(int(unit)))


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
