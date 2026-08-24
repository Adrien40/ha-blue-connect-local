"""Tests for BLE frame decoding. Loaded via _load_pure (see that file)."""

from ._load_pure import load_pure_module

_protocol = load_pure_module("protocol.py")
parse_raw_frame = _protocol.parse_raw_frame
extract_raw_payload = _protocol.extract_raw_payload
CONDUCTIVITY_SENSOR_ABSENT = _protocol.CONDUCTIVITY_SENSOR_ABSENT

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
        "has_conductivity": True,
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


def test_conductivity_sentinel_neutralizes_conductivity_and_salinity():
    # Real Blue Connect Silver capture: conductivity field is the 0xFFFF
    # "no sensor" sentinel, and salinity - derived on-device from
    # conductivity - decodes to a fixed, meaningless value alongside it.
    frame = bytearray(FRAME_18)
    frame[9:11] = CONDUCTIVITY_SENSOR_ABSENT.to_bytes(2, "big")  # conductivity
    result = parse_raw_frame(bytes(frame))
    assert result["conductivity"] is None
    assert result["salinity"] is None
    assert result["has_conductivity"] is False


def test_real_conductivity_value_is_kept():
    result = parse_raw_frame(FRAME_18)
    assert result["conductivity"] == 1200
    assert result["salinity"] == 3.5
    assert result["has_conductivity"] is True


def test_extract_raw_payload_prefers_manufacturer_data():
    other_payload = bytes(19)
    result = extract_raw_payload(
        manufacturer_data={1234: FRAME_18, 5678: other_payload},
        service_data={"some-uuid": FRAME_18},
    )
    assert result == FRAME_18


def test_extract_raw_payload_falls_back_to_service_data():
    result = extract_raw_payload(
        manufacturer_data={1234: bytes(5)},  # wrong length, ignored
        service_data={"some-uuid": FRAME_18},
    )
    assert result == FRAME_18


def test_extract_raw_payload_no_match_returns_none():
    result = extract_raw_payload(
        manufacturer_data={1234: bytes(5)},
        service_data={"some-uuid": bytes(10)},
    )
    assert result is None
