"""Tests for the Blueriiot measurement frame decoder (protocol_blueriiot.py)."""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from ._load_pure import load_pure_module
from .helpers import build_frame
from .helpers_blueriiot import FRAME_HEX_LEN, PROTOCOL, build_blueriiot_frame

_ZODIAC = load_pure_module("protocol.py")
parse_blueriiot_frame = PROTOCOL.parse_blueriiot_frame
is_blueriiot_frame = PROTOCOL.is_blueriiot_frame


def test_parse_valid_frame():
    parsed = parse_blueriiot_frame(build_blueriiot_frame())
    assert parsed["device_type"] == "blueriiot"
    assert parsed["temp_raw"] == pytest.approx(25.02)
    assert parsed["ph_raw"] == pytest.approx(7.4, abs=0.01)
    assert parsed["orp_raw"] == pytest.approx(700.0)
    assert parsed["conductivity"] == pytest.approx(1061.5)
    assert parsed["salinity"] == pytest.approx(0.53)
    assert parsed["battery"] == 3520
    assert parsed["battery_percent"] == 50


def test_parse_accepts_bytearray():
    assert parse_blueriiot_frame(bytearray(build_blueriiot_frame())) is not None


def test_parse_zero_conductivity_means_no_reading():
    parsed = parse_blueriiot_frame(build_blueriiot_frame(conductivity_raw=0))
    assert parsed["conductivity"] is None
    assert parsed["salinity"] is None


def test_conductivity_sensor_is_flagged_only_when_a_reading_exists():
    with_reading = parse_blueriiot_frame(build_blueriiot_frame(conductivity_raw=1000))
    assert with_reading["has_conductivity"] is True
    # A zero is ambiguous (no sensor or no reading): never declare "absent".
    without = parse_blueriiot_frame(build_blueriiot_frame(conductivity_raw=0))
    assert "has_conductivity" not in without


@pytest.mark.parametrize(
    ("battery_mv", "expected"),
    [(3000, 0), (3400, 0), (3520, 50), (3640, 100), (4200, 100)],
)
def test_battery_percent_is_clamped(battery_mv, expected):
    parsed = parse_blueriiot_frame(build_blueriiot_frame(battery_mv=battery_mv))
    assert parsed["battery_percent"] == expected


@pytest.mark.parametrize(
    "frame",
    [
        b"",
        build_blueriiot_frame(length=11),
        build_blueriiot_frame(length=13),
        build_blueriiot_frame(marker=0x00),
        build_frame(),  # a Zodiac frame is not a Blueriiot frame
    ],
)
def test_parse_rejects_anything_but_a_measurement_frame(frame):
    assert not is_blueriiot_frame(frame)
    assert parse_blueriiot_frame(frame) is None


def test_hex_length_matches_frame_length():
    assert len(build_blueriiot_frame().hex()) == FRAME_HEX_LEN == 24


@given(st.binary(max_size=40))
def test_parse_never_raises(data):
    parsed = parse_blueriiot_frame(data)
    assert (parsed is not None) == is_blueriiot_frame(data)


def test_frame_matching_blue_connect_plus_fw_2_3_0():
    """Values reported on PR #5 (Blue Connect Plus, firmware 2.3.0).

    The official app agreed with them. The frame is rebuilt from those decoded
    values (it was not captured), so this pins the formulas to a real probe.
    """
    parsed = parse_blueriiot_frame(
        build_blueriiot_frame(
            temp_c=25.15,
            ph_raw=1913,
            orp_raw=2596,
            conductivity_raw=1008,
            battery_mv=3621,
        )
    )
    assert parsed["temp_raw"] == pytest.approx(25.15)
    assert round(parsed["ph_raw"], 2) == 7.58
    assert parsed["orp_raw"] == pytest.approx(644.0)
    assert parsed["conductivity"] == pytest.approx(1053.1)
    assert parsed["battery_percent"] == 92


def test_blue_connect_plus_advertisement_is_not_a_zodiac_frame():
    """The 11-byte advertisement of a Blue Connect Plus must stay unparsed.

    Zodiac passive broadcasts are 18 or 19 bytes: anything else is ignored by
    the passive listener and by the config flow.
    """
    advertisement = bytes.fromhex("19EA037C07DE4D30FE8905")
    assert len(advertisement) == 11
    assert _ZODIAC.extract_raw_payload({305: advertisement}, {}) is None
    assert _ZODIAC.parse_raw_frame(advertisement) is None
    assert not is_blueriiot_frame(advertisement)
