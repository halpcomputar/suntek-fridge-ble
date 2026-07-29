"""Tests for the frame parser. Run with: python3 -m pytest tests/ -q"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

# Load protocol.py directly rather than importing the package: the package __init__
# pulls in Home Assistant, and the whole point of protocol.py is that it does not.
_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "suntek_fridge_ble"
    / "protocol.py"
)
_spec = importlib.util.spec_from_file_location("suntek_protocol", _PATH)
protocol = importlib.util.module_from_spec(_spec)
# Must be registered before exec: @dataclass resolves via sys.modules[cls.__module__].
sys.modules[_spec.name] = protocol
_spec.loader.exec_module(protocol)

FrameBuffer = protocol.FrameBuffer
FrameError = protocol.FrameError
parse_frame = protocol.parse_frame
to_celsius = protocol.to_celsius

# Live capture, BougeRV CRD2 V2.0, 2026-07-28. Fridge on Max, freshly loaded with
# room-temperature bottled water, battery protection M, running off an EcoFlow.
CAPTURE_MAX = "/SC0/4/2,1,2,+54,+44,+34,+34,2,118,2,100,1,b01"

# Same unit after toggling to Eco; note the supply voltage recovering to 12.3 V.
CAPTURE_ECO = "/SC0/4/2,1,2,+56,+41,+34,+34,2,123,1,100,1,b01"


def test_parses_reference_capture() -> None:
    status = parse_frame(CAPTURE_MAX)
    assert status.powered is True
    assert status.displays_fahrenheit is True
    assert status.battery_protection == "medium"
    assert status.run_mode == "max"
    assert status.voltage == 11.8
    assert status.firmware == "b01"


def test_temperatures_normalised_to_celsius() -> None:
    status = parse_frame(CAPTURE_MAX)
    assert status.zone1_temp == pytest.approx(12.2, abs=0.05)  # 54°F
    assert status.zone2_temp == pytest.approx(6.7, abs=0.05)  # 44°F
    assert status.zone1_setpoint == pytest.approx(1.1, abs=0.05)  # 34°F
    assert status.zone2_setpoint == pytest.approx(1.1, abs=0.05)


def test_celsius_round_trips_back_to_the_displayed_fahrenheit_integer() -> None:
    """Users see whole degrees F in the app; conversion must not drift off by one."""
    for reading in range(-20, 100):
        celsius = to_celsius(reading, from_fahrenheit=True)
        assert round(celsius * 9 / 5 + 32) == reading


def test_eco_capture() -> None:
    status = parse_frame(CAPTURE_ECO)
    assert status.run_mode == "eco"
    assert status.voltage == 12.3


# Live capture after switching the app to °C and battery protection to H, 2026-07-28.
# Note the zero-padded, explicitly signed temperatures: "+04", "-01".
CAPTURE_CELSIUS = "/SC0/4/2,1,1,+13,+04,+01,-01,3,123,1,100,1,b01"


def test_celsius_mode_is_passed_through_unconverted() -> None:
    status = parse_frame(CAPTURE_CELSIUS)
    assert status.displays_fahrenheit is False
    assert status.zone1_temp == 13.0
    assert status.zone1_setpoint == 1.0


def test_zero_padded_and_negative_celsius_values() -> None:
    """The fridge pads to two digits in °C mode, including below zero."""
    status = parse_frame(CAPTURE_CELSIUS)
    assert status.zone2_temp == 4.0  # "+04"
    assert status.zone2_setpoint == -1.0  # "-01"


def test_high_battery_protection() -> None:
    assert parse_frame(CAPTURE_CELSIUS).battery_protection == "high"


def test_negative_temperatures() -> None:
    status = parse_frame("/SC0/4/2,1,2,-4,+41,-4,+34,2,123,1,100,1,b01")
    assert status.zone1_temp == pytest.approx(-20.0, abs=0.05)  # -4°F


def test_power_off() -> None:
    assert parse_frame("/SC0/4/2,0,2,+56,+41,+34,+34,2,123,1,100,1,b01").powered is False


def test_unmapped_enum_values_become_none_rather_than_a_wrong_guess() -> None:
    status = parse_frame("/SC0/4/2,1,2,+56,+41,+34,+34,9,123,9,100,1,b01")
    assert status.battery_protection is None
    assert status.run_mode is None


@pytest.mark.parametrize(
    "bad",
    [
        "nonsense",
        "/SC0/4/2,1,2,+56",  # truncated
        "/SC0/4/2,1,2,+56,+41,+34,+34,2,123,1,100,1,b01,extra",  # too many fields
        "/SC0/4/2,1,2,abc,+41,+34,+34,2,123,1,100,1,b01",  # non-numeric temp
    ],
)
def test_malformed_frames_raise(bad: str) -> None:
    with pytest.raises(FrameError):
        parse_frame(bad)


def test_buffer_reassembles_frames_split_across_notifications() -> None:
    """The 47-byte frame exceeds the default 23-byte MTU, so this is the normal case."""
    blob = (CAPTURE_MAX + "\n" + CAPTURE_ECO + "\n").encode()
    buf = FrameBuffer()
    frames: list[str] = []
    for i in range(0, len(blob), 20):
        frames += buf.feed(blob[i : i + 20])
    assert frames == [CAPTURE_MAX, CAPTURE_ECO]


def test_buffer_holds_incomplete_frames() -> None:
    buf = FrameBuffer()
    assert buf.feed(b"/SC0/4/2,1,2,") == []
    assert buf.feed(b"+56,+41,+34,+34,2,123,1,100,1,b01\n") == [CAPTURE_ECO]


def test_buffer_reset_discards_partial_data() -> None:
    buf = FrameBuffer()
    buf.feed(b"/SC0/4/2,1,2,junk")
    buf.reset()
    assert buf.feed((CAPTURE_ECO + "\n").encode()) == [CAPTURE_ECO]
