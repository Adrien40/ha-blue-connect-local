"""Robustness: invalid inputs, impossible values, HA version compatibility."""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace

import pytest
from homeassistant.const import STATE_UNKNOWN
from hypothesis import given, strategies as st

from custom_components.blue_connect_local.const import (
    CONF_PH_CALIB_4,
    CONF_PH_CALIB_7,
    CONF_PH_REF_4,
    CONF_PH_REF_7,
)
from custom_components.blue_connect_local.coordinator import find_device

from ._load_pure import load_pure_module
from .conftest import entity_id, make_entry
from .helpers import FakeBlueClient, build_frame

_chemistry = load_pure_module("chemistry.py")
_protocol = load_pure_module("protocol.py")
_validation = load_pure_module("validation.py")

compute_lsi = _chemistry.compute_lsi
compute_ph_equilibrium = _chemistry.compute_ph_equilibrium
parse_raw_frame = _protocol.parse_raw_frame
validate_calibration = _validation.validate_calibration

VALID = {"ph_calib_4": 4.0, "ph_calib_7": 7.0, "ph_ref_4": 4.0, "ph_ref_7": 7.0}


# ---------------------------------------------------------------------------
# Langelier: never NaN nor an exception
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("temp", "ph", "tac", "th", "tds"),
    [
        (float("nan"), 7.4, 100, 200, 1000),
        (25, float("nan"), 100, 200, 1000),
        (25, 7.4, float("inf"), 200, 1000),
        (25, 7.4, 100, 200, float("-inf")),
        (-273.15, 7.4, 100, 200, 1000),  # log10(0)
        (-300, 7.4, 100, 200, 1000),
        (25, 7.4, 0, 200, 1000),
        (None, 7.4, 100, 200, 1000),
    ],
)
def test_lsi_rejects_invalid_inputs(temp, ph, tac, th, tds):
    assert compute_lsi(temp, ph, tac, th, tds) is None


@given(
    st.floats(allow_nan=True, allow_infinity=True),
    st.floats(allow_nan=True, allow_infinity=True),
    st.floats(allow_nan=True, allow_infinity=True),
    st.floats(allow_nan=True, allow_infinity=True),
    st.floats(allow_nan=True, allow_infinity=True),
)
def test_lsi_and_equilibrium_never_yield_nan(temp, ph, tac, th, tds):
    for result in (
        compute_lsi(temp, ph, tac, th, tds),
        compute_ph_equilibrium(temp, tac, th, tds),
    ):
        assert result is None or math.isfinite(result)


def test_lsi_reference_value():
    assert compute_lsi(25, 7.5, 100, 200, 1000) == -0.18
    assert compute_ph_equilibrium(25, 100, 200, 1000) == 7.68


# ---------------------------------------------------------------------------
# Frame decoding: robust to any content
# ---------------------------------------------------------------------------
@given(st.binary(min_size=0, max_size=40))
def test_parse_raw_frame_never_raises(data):
    result = parse_raw_frame(data)
    if result is not None:
        assert len(data) in (18, 19)


# ---------------------------------------------------------------------------
# Validation: protected numeric conversions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("orp_ref", "abc"),
        ("orp_calib", "nan"),
        ("temp_offset", "x"),
        ("cya", "x"),
        ("scan_interval", "soon"),
    ],
)
def test_non_numeric_values_return_an_error_instead_of_raising(key, value):
    """Regression: these values used to raise an unhandled ValueError."""
    assert validate_calibration({**VALID, key: value}) == (key, "unknown")


@pytest.mark.parametrize(
    ("low_key", "high_key"),
    [
        ("ph_min", "ph_max"),
        ("temp_min", "temp_max"),
        ("orp_min", "orp_max"),
    ],
)
def test_non_numeric_threshold_returns_an_error_instead_of_raising(low_key, high_key):
    """Same regression as above, for the min/max threshold pairs: both keys
    must be present together to enter the try block, so a single-field
    override (like the parametrize above) never reaches this except."""
    assert validate_calibration({**VALID, low_key: "abc", high_key: 7}) == (
        low_key,
        "unknown",
    )


def test_numeric_strings_are_normalized():
    result = validate_calibration(
        {**VALID, "cya": "40.7", "scan_interval": "30", "temp_offset": "1,5"}
    )
    assert result["cya"] == 40
    assert result["scan_interval"] == 30
    assert result["temp_offset"] == 1.5


# ---------------------------------------------------------------------------
# Physically impossible pH
# ---------------------------------------------------------------------------
async def test_impossible_ph_becomes_unknown(hass, setup_integration, ble, caplog):
    ble.client = FakeBlueClient([build_frame(ph=7.4)])
    coord = await setup_integration(
        make_entry(
            **{
                CONF_PH_CALIB_7: 7.0,
                CONF_PH_REF_7: 7.0,
                CONF_PH_CALIB_4: 7.02,  # calibration points nearly identical -> absurd pH
                CONF_PH_REF_4: 4.0,
            }
        )
    )
    with caplog.at_level(logging.WARNING):
        await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.data["ph"] is None
    assert coord.data["lsi"] is None
    assert "out of the physical range" in caplog.text
    assert hass.states.get(entity_id(hass, "sensor", "ph")).state == STATE_UNKNOWN


# ---------------------------------------------------------------------------
# Compatibility: device registry (HA 2026.3 <-> 2026.9)
# ---------------------------------------------------------------------------
class _NewRegistry:
    def __init__(self):
        self.calls = []

    def async_get_device_by_identifier(self, identifier, config_entry_id):
        self.calls.append((identifier, config_entry_id))
        return "new-api-device"

    def async_get_device(self, **_):  # must not be called
        raise AssertionError("deprecated API used although the new one exists")


class _OldRegistry:
    def async_get_device(self, identifiers):
        return SimpleNamespace(identifiers=identifiers)


def test_find_device_prefers_the_new_api():
    registry = _NewRegistry()
    assert find_device(registry, ("d", "m"), "entry1") == "new-api-device"
    assert registry.calls == [(("d", "m"), "entry1")]


def test_find_device_falls_back_on_older_home_assistant():
    device = find_device(_OldRegistry(), ("d", "m"), "entry1")
    assert device.identifiers == {("d", "m")}


# ---------------------------------------------------------------------------
# Equal thresholds and nearby slots (edge cases found by mutation testing)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("low", "high", "code"),
    [
        ("ph_min", "ph_max", "ph_threshold_error"),
        ("temp_min", "temp_max", "temp_threshold_error"),
        ("orp_min", "orp_max", "orp_threshold_error"),
    ],
)
def test_equal_min_and_max_thresholds_are_rejected(low, high, code):
    assert validate_calibration({**VALID, low: 7, high: 7}) == (low, code)
    assert isinstance(validate_calibration({**VALID, low: 6, high: 7}), dict)


async def test_slot_less_than_10_seconds_away_is_skipped(
    hass, setup_integration, freezer
):
    """5 s before the 11:00 slot, the next analysis is scheduled for 12:00."""
    from datetime import datetime

    import homeassistant.util.dt as dt_util

    coord = await setup_integration(
        make_entry(**{"scan_interval": 60, "reference_time": "08:00"})
    )
    tz = dt_util.get_default_time_zone()

    freezer.move_to(datetime(2026, 6, 1, 10, 59, 55, tzinfo=tz))
    coord.update_schedule()
    assert (coord.next_slot.hour, coord.next_slot.minute) == (12, 0)

    freezer.move_to(datetime(2026, 6, 1, 10, 59, 45, tzinfo=tz))
    coord.update_schedule()
    assert (coord.next_slot.hour, coord.next_slot.minute) == (11, 0)
