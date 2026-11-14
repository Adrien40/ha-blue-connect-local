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
from typing import Any


def _to_float(val: str | int | float) -> float:
    if isinstance(val, str):
        val = val.replace(",", ".")
    result = float(val)
    if math.isnan(result) or math.isinf(result):
        raise ValueError("NaN/Inf is not a valid calibration value")
    return result


def _flatten_sections(
    user_input: dict[str, Any],
) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for value in user_input.values():
        if isinstance(value, dict):
            flat.update(value)
    for k, v in user_input.items():
        if not isinstance(v, dict):
            flat.setdefault(k, v)
    return flat


def validate_calibration(
    data: dict[str, Any],
) -> dict[str, Any] | tuple[str, str]:
    try:
        c4_meas = _to_float(data.get("ph_calib_4", 4.00))
        c7_meas = _to_float(data.get("ph_calib_7", 7.00))
        ref4 = _to_float(data.get("ph_ref_4", 4.00))
        ref7 = _to_float(data.get("ph_ref_7", 7.00))
    # PEP 758 (Python 3.14): parentheses are optional when there is no `as` clause. Intentional.
    except ValueError, TypeError:
        return ("ph_calib_4", "unknown")

    try:
        if "ph_min" in data and "ph_max" in data:
            ph_min = _to_float(data["ph_min"])
            ph_max = _to_float(data["ph_max"])
            if ph_min >= ph_max:
                return ("ph_min", "ph_threshold_error")
    # PEP 758 (Python 3.14): parentheses are optional when there is no `as` clause. Intentional.
    except ValueError, TypeError:
        return ("ph_min", "unknown")

    try:
        if "temp_min" in data and "temp_max" in data:
            temp_min = _to_float(data["temp_min"])
            temp_max = _to_float(data["temp_max"])
            if temp_min >= temp_max:
                return ("temp_min", "temp_threshold_error")
    # PEP 758 (Python 3.14): parentheses are optional when there is no `as` clause. Intentional.
    except ValueError, TypeError:
        return ("temp_min", "unknown")

    try:
        if "orp_min" in data and "orp_max" in data:
            orp_min = int(_to_float(data["orp_min"]))
            orp_max = int(_to_float(data["orp_max"]))
            if orp_min >= orp_max:
                return ("orp_min", "orp_threshold_error")
    # PEP 758 (Python 3.14): parentheses are optional when there is no `as` clause. Intentional.
    except ValueError, TypeError:
        return ("orp_min", "unknown")

    if ref4 < 2.5 or ref4 > 5.5 or ref7 < 6.5 or ref7 > 7.5:
        return ("ph_ref_4", "ph_ref_out_of_range")
    if abs(c7_meas - c4_meas) < 0.1:
        return ("ph_calib_7", "ph_calibration_equal")
    if c4_meas > c7_meas:
        return ("ph_calib_7", "ph_slope_mismatch")

    # The integration's own mV calibration is only checked when the person
    # filled it in (both potentials empty means "use the probe's calibration"):
    # both must be given, they must differ, and the pH 4 solution reads a
    # higher potential than the pH 7 one (the formula divides by their gap).
    mv_4_raw: Any = data.get("ph_hr_calib_mv_4")
    mv_7_raw: Any = data.get("ph_hr_calib_mv_7")
    has_mv_4 = mv_4_raw not in (None, "")
    has_mv_7 = mv_7_raw not in (None, "")
    normalized_hr: dict[str, float] = {}
    if has_mv_4 or has_mv_7:
        if not has_mv_4:
            return ("ph_hr_calib_mv_4", "ph_hr_mv_incomplete")
        if not has_mv_7:
            return ("ph_hr_calib_mv_7", "ph_hr_mv_incomplete")
        try:
            mv_4 = _to_float(mv_4_raw)
            mv_7 = _to_float(mv_7_raw)
        # PEP 758 (Python 3.14): parentheses are optional when there is no `as` clause. Intentional.
        except ValueError, TypeError:
            return ("ph_hr_calib_mv_4", "unknown")
        try:
            hr_ref_4 = _to_float(data.get("ph_hr_ref_4", 4.00))
            hr_ref_7 = _to_float(data.get("ph_hr_ref_7", 7.00))
        # PEP 758 (Python 3.14): parentheses are optional when there is no `as` clause. Intentional.
        except ValueError, TypeError:
            return ("ph_hr_ref_4", "unknown")
        if hr_ref_4 < 2.5 or hr_ref_4 > 5.5 or hr_ref_7 < 6.5 or hr_ref_7 > 7.5:
            return ("ph_hr_ref_4", "ph_ref_out_of_range")
        if abs(mv_4 - mv_7) < 1.0:
            return ("ph_hr_calib_mv_7", "ph_hr_calibration_equal")
        if mv_4 < mv_7:
            return ("ph_hr_calib_mv_7", "ph_hr_slope_mismatch")
        normalized_hr = {
            "ph_hr_calib_mv_4": mv_4,
            "ph_hr_calib_mv_7": mv_7,
            "ph_hr_ref_4": hr_ref_4,
            "ph_hr_ref_7": hr_ref_7,
        }

    # The integration's own ORP calibration works the same way: both values
    # empty means "use the probe's calibration"; otherwise both are needed.
    # Unlike the pH, a gap between them is only a warning raised afterwards
    # (a repair): the person keeps the last word.
    orp_ref_raw: Any = data.get("orp_ref")
    orp_calib_raw: Any = data.get("orp_calib")
    has_orp_ref = orp_ref_raw not in (None, "")
    has_orp_calib = orp_calib_raw not in (None, "")
    normalized_orp: dict[str, int] = {}
    if has_orp_ref or has_orp_calib:
        if not has_orp_calib:
            return ("orp_calib", "orp_calib_incomplete")
        if not has_orp_ref:
            return ("orp_ref", "orp_calib_incomplete")
        try:
            normalized_orp = {
                "orp_ref": int(_to_float(orp_ref_raw)),
                "orp_calib": int(_to_float(orp_calib_raw)),
            }
        # PEP 758 (Python 3.14): parentheses are optional when there is no `as` clause. Intentional.
        except ValueError, TypeError:
            return ("orp_calib", "unknown")

    normalized = dict(data)
    normalized.update(normalized_hr)
    # Empty is stored as None, not left out: the options replace the whole
    # set of values, and an absent key would let a value entered when the
    # entry was created (kept in the entry's data) come back.
    normalized["orp_ref"] = None
    normalized["orp_calib"] = None
    normalized.update(normalized_orp)
    normalized["ph_calib_4"] = c4_meas
    normalized["ph_calib_7"] = c7_meas
    normalized["ph_ref_4"] = ref4
    normalized["ph_ref_7"] = ref7

    for key, cast in (
        ("temp_offset", float),
        ("cya", int),
        ("scan_interval", int),
    ):
        if key in data:
            try:
                normalized[key] = cast(_to_float(data[key]))
            # PEP 758 (Python 3.14): parentheses are optional when there is no `as` clause. Intentional.
            except ValueError, TypeError:
                return (key, "unknown")
    if "reference_time" in data:
        normalized["reference_time"] = str(data["reference_time"])

    normalized["passive_measures"] = bool(data.get("passive_measures", True))
    normalized["ignore_echoes"] = bool(data.get("ignore_echoes", True))

    return normalized
