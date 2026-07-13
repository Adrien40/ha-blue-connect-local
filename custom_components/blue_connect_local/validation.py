# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

"""Pure parsing/validation helpers for the config flow.

Extracted from config_flow.py: that file imports homeassistant.config_entries,
homeassistant.components.bluetooth, etc. at module level. Importing
_to_float / _flatten_sections / validate_calibration (which don't actually
depend on any of that) directly from config_flow.py would therefore have
required installing homeassistant just to test them.

Configuration keys are hardcoded here ("ph_calib_4", etc.) rather than
imported from .const, because const.py has the same homeassistant-import
problem (see model.py). Same values as CONF_PH_CALIB_4 etc. in const.py —
behavior unchanged.
"""

from __future__ import annotations

import math


def _to_float(val: object) -> float:
    if isinstance(val, str):
        val = val.replace(",", ".")
    result = float(val)
    if math.isnan(result) or math.isinf(result):
        raise ValueError("NaN/Inf is not a valid calibration value")
    return result


def _flatten_sections(user_input: dict) -> dict:
    flat: dict = {}
    for value in user_input.values():
        if isinstance(value, dict):
            flat.update(value)
    for k, v in user_input.items():
        if not isinstance(v, dict):
            flat.setdefault(k, v)
    return flat


def validate_calibration(data: dict) -> dict | tuple[str, str]:
    try:
        c4_meas = _to_float(data.get("ph_calib_4", 4.00))
        c7_meas = _to_float(data.get("ph_calib_7", 7.00))
        ref4 = _to_float(data.get("ph_ref_4", 4.00))
        ref7 = _to_float(data.get("ph_ref_7", 7.00))
    except (ValueError, TypeError):
        return ("ph_calib_4", "unknown")

    try:
        if "ph_min" in data and "ph_max" in data:
            ph_min = _to_float(data["ph_min"])
            ph_max = _to_float(data["ph_max"])
            if ph_min >= ph_max:
                return ("ph_min", "ph_threshold_error")
    except (ValueError, TypeError):
        return ("ph_min", "unknown")

    try:
        if "temp_min" in data and "temp_max" in data:
            temp_min = _to_float(data["temp_min"])
            temp_max = _to_float(data["temp_max"])
            if temp_min >= temp_max:
                return ("temp_min", "temp_threshold_error")
    except (ValueError, TypeError):
        return ("temp_min", "unknown")

    try:
        if "orp_min" in data and "orp_max" in data:
            orp_min = int(_to_float(data["orp_min"]))
            orp_max = int(_to_float(data["orp_max"]))
            if orp_min >= orp_max:
                return ("orp_min", "orp_threshold_error")
    except (ValueError, TypeError):
        return ("orp_min", "unknown")

    if ref4 < 2.5 or ref4 > 5.5 or ref7 < 6.5 or ref7 > 7.5:
        return ("ph_ref_4", "ph_ref_out_of_range")
    if abs(c7_meas - c4_meas) < 0.1:
        return ("ph_calib_7", "ph_calibration_equal")
    if c4_meas > c7_meas:
        return ("ph_calib_7", "ph_slope_mismatch")

    normalized = dict(data)
    normalized["ph_calib_4"] = c4_meas
    normalized["ph_calib_7"] = c7_meas
    normalized["ph_ref_4"] = ref4
    normalized["ph_ref_7"] = ref7

    if "orp_ref" in data:
        normalized["orp_ref"] = int(_to_float(data["orp_ref"]))
    if "orp_calib" in data:
        normalized["orp_calib"] = int(_to_float(data["orp_calib"]))
    if "temp_offset" in data:
        normalized["temp_offset"] = float(_to_float(data["temp_offset"]))
    if "cya" in data:
        normalized["cya"] = int(_to_float(data["cya"]))
    if "scan_interval" in data:
        normalized["scan_interval"] = int(_to_float(data["scan_interval"]))
    if "reference_time" in data:
        normalized["reference_time"] = str(data["reference_time"])

    normalized["passive_measures"] = bool(data.get("passive_measures", True))
    normalized["ignore_echoes"] = bool(data.get("ignore_echoes", True))

    return normalized
