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


# --------------------------------------------------------------------------- #
#  Commands
# --------------------------------------------------------------------------- #
#
# Vectors below are the literal frames the BougeRV app emitted, captured in
# order via PacketLogger on 2026-07-28. Each one is tied to a known user action,
# and the capture included a reversal pass that returned every setting to its
# original value — which is what disambiguated SC6 from SC7, since run mode and
# display unit share the same 001/002 encoding.


def test_setpoint_commands_match_the_captured_frames() -> None:
    assert protocol.set_setpoint(1, 35) == b"/SC3/1/+35\n"  # zone 1 up
    assert protocol.set_setpoint(1, 34) == b"/SC3/1/+34\n"  # zone 1 back down
    assert protocol.set_setpoint(2, 35) == b"/SC5/1/+35\n"  # zone 2 up
    assert protocol.set_setpoint(2, 34) == b"/SC5/1/+34\n"  # zone 2 back down


def test_run_mode_commands_match_the_captured_frames() -> None:
    assert protocol.set_run_mode("eco") == b"/SC6/1/001\n"
    assert protocol.set_run_mode("max") == b"/SC6/1/002\n"


def test_display_unit_commands_match_the_captured_frames() -> None:
    assert protocol.set_display_unit(fahrenheit=False) == b"/SC7/1/001\n"
    assert protocol.set_display_unit(fahrenheit=True) == b"/SC7/1/002\n"


def test_battery_protection_commands_match_the_captured_frames() -> None:
    assert protocol.set_battery_protection("high") == b"/SC4/1/003\n"
    assert protocol.set_battery_protection("medium") == b"/SC4/1/002\n"
    # Low was never exercised by the capture; included for completeness.
    assert protocol.set_battery_protection("low") == b"/SC4/1/001\n"


def test_power_commands_match_the_captured_frames() -> None:
    assert protocol.set_power(False) == b"/SC1/1/000\n"
    assert protocol.set_power(True) == b"/SC1/1/001\n"


def test_negative_and_three_digit_setpoints_stay_signed_and_padded() -> None:
    assert protocol.set_setpoint(1, -1) == b"/SC3/1/-01\n"
    assert protocol.set_setpoint(1, -20) == b"/SC3/1/-20\n"
    assert protocol.set_setpoint(1, 0) == b"/SC3/1/+00\n"
    assert protocol.set_setpoint(2, 100) == b"/SC5/1/+100\n"


def test_command_enums_use_the_same_vocabulary_as_the_status_frame() -> None:
    """Both directions share one encoding; a divergence here would be a bug."""
    status = parse_frame(CAPTURE_ECO)
    assert protocol.set_run_mode(status.run_mode) == b"/SC6/1/001\n"
    assert protocol.set_battery_protection(status.battery_protection) == b"/SC4/1/002\n"


@pytest.mark.parametrize(
    "call",
    [
        lambda: protocol.set_setpoint(3, 34),
        lambda: protocol.set_run_mode("turbo"),
        lambda: protocol.set_battery_protection("extreme"),
    ],
)
def test_invalid_command_arguments_raise(call) -> None:
    with pytest.raises(ValueError):
        call()
