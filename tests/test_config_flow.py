"""Tests for config flow validation.

_to_float, _flatten_sections and validate_calibration now live in
validation.py (not config_flow.py): config_flow.py imports homeassistant.*
at module level, so testing them from that module would have required
installing homeassistant.

Literal keys ("ph_min", etc.) are used here rather than the CONF_* constants
from const.py, because const.py ALSO imports homeassistant
(homeassistant.helpers.device_registry — see model.py / test_const.py).
Same values, so behavior is unchanged.
"""

import pytest

from ._load_pure import load_pure_module

_validation = load_pure_module("validation.py")
_to_float = _validation._to_float
_flatten_sections = _validation._flatten_sections
validate_calibration = _validation.validate_calibration

VALID_INPUT = {
    "ph_calib_4": "4.1",
    "ph_calib_7": "6.9",
    "ph_ref_4": "4.0",
    "ph_ref_7": "7.0",
    "ph_min": "6.8",
    "ph_max": "7.6",
    "orp_min": "600",
    "orp_max": "750",
    "temp_min": "10",
    "temp_max": "32",
}


def test_to_float_french_comma():
    assert _to_float("7,2") == 7.2


def test_to_float_nan_inf_raises_value_error():
    with pytest.raises(ValueError):
        _to_float("nan")
    with pytest.raises(ValueError):
        _to_float("inf")


def test_flatten_sections_flattens_sections():
    nested = {"probes_calibration": {"ph_calib_4": "4.1"}, "ph_min": "6.8"}
    assert _flatten_sections(nested) == {"ph_calib_4": "4.1", "ph_min": "6.8"}


def test_validate_calibration_valid_case():
    result = validate_calibration(VALID_INPUT)
    assert isinstance(result, dict)
    assert result["ph_calib_4"] == pytest.approx(4.1)
    assert isinstance(result["ph_calib_4"], float)
    assert result["passive_measures"] is True
    assert result["ignore_echoes"] is True


def test_validate_calibration_thresholds_min_ge_max():
    cases = [
        ({"ph_min": "7.6", "ph_max": "6.8"}, ("ph_min", "ph_threshold_error")),
        ({"temp_min": "32", "temp_max": "10"}, ("temp_min", "temp_threshold_error")),
        ({"orp_min": "750", "orp_max": "600"}, ("orp_min", "orp_threshold_error")),
    ]
    for overrides, expected in cases:
        assert validate_calibration({**VALID_INPUT, **overrides}) == expected


def test_validate_calibration_measured_points_nearly_equal():
    # real threshold: measured gap < 0.1 (not 0.01)
    bad = {**VALID_INPUT, "ph_calib_4": "5.0", "ph_calib_7": "5.05"}
    assert validate_calibration(bad) == ("ph_calib_7", "ph_calibration_equal")


def test_validate_calibration_ph_ref_out_of_bounds():
    bad = {**VALID_INPUT, "ph_ref_4": "6.0"}  # outside the expected [2.5, 5.5] range
    assert validate_calibration(bad) == ("ph_ref_4", "ph_ref_out_of_range")


def test_validate_calibration_reversed_slope():
    bad = {**VALID_INPUT, "ph_calib_4": "6.9", "ph_calib_7": "4.1"}
    assert validate_calibration(bad) == ("ph_calib_7", "ph_slope_mismatch")


def test_validate_calibration_non_numeric_value():
    bad = {**VALID_INPUT, "ph_calib_4": "not a number"}
    assert validate_calibration(bad) == ("ph_calib_4", "unknown")
