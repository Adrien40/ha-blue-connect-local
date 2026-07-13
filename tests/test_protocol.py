"""Tests for BLE frame decoding. Loaded via _load_pure (see that file)."""

from ._load_pure import load_pure_module

parse_raw_frame = load_pure_module("protocol.py").parse_raw_frame

FRAME_18 = bytes.fromhex("0000000AAF004A028A04B0015E550BB80000")


def test_frame_18_bytes_valid():
    assert parse_raw_frame(FRAME_18) == {
        "temp_raw": 27.35,
        "ph_raw": 7.4,
        "orp_raw": 650,
        "conductivity": 1200,
        "salinity": 3.5,
        "battery_percent": 85,
        "battery_adc": 3000,
        "battery": 2637,
    }


def test_frame_19_bytes_same_result_shifted_offset():
    frame_19 = b"\x00" + FRAME_18
    assert parse_raw_frame(frame_19) == parse_raw_frame(FRAME_18)


def test_invalid_length_returns_none():
    assert parse_raw_frame(bytes(10)) is None
    assert parse_raw_frame(bytes(20)) is None


def test_battery_mv_truncates_not_rounds():
    # battery_adc = 1137 -> 1137 * 0.8791 = 999.5367 -> int() truncates to 999
    # (round() would give 1000: this test would catch a regression from
    # int() to round())
    frame = bytearray(FRAME_18)
    frame[14:16] = (1137).to_bytes(2, "big")
    result = parse_raw_frame(bytes(frame))
    assert result["battery_adc"] == 1137
    assert result["battery"] == 999
