# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import logging
import math

_LOGGER = logging.getLogger(__name__)


def _compute_ph_s(temp_c: float, tac_c: float, th_c: float, tds_c: float) -> float:
    a = (math.log10(tds_c) - 1.0) / 10.0
    b = -13.12 * math.log10(temp_c + 273.15) + 34.55
    c = math.log10(th_c) - 0.4
    d = math.log10(tac_c)
    return (9.3 + a + b) - (c + d)


def _all_finite(*values: float | None) -> bool:
    return all(v is not None and math.isfinite(float(v)) for v in values)


def compute_lsi(
    temp: float | None,
    ph: float | None,
    tac: float | None,
    th: float | None,
    tds: float | None,
) -> float | None:
    if not _all_finite(temp, ph, tac, th, tds):
        return None
    # _all_finite() just confirmed none of these are None; make that visible
    # to mypy (it can't narrow through an opaque function call).
    assert temp is not None
    assert ph is not None
    assert tac is not None
    assert th is not None
    assert tds is not None
    if tac <= 0 or th <= 0 or tds <= 0:
        return None
    try:
        ph_s = _compute_ph_s(temp, tac, th, tds)
        result = round(ph - ph_s, 2)
    except (ValueError, OverflowError, ZeroDivisionError) as e:
        _LOGGER.warning("Math error in compute_lsi: %s", e)
        return None
    return result if math.isfinite(result) else None


def compute_ph_equilibrium(
    temp: float | None,
    tac: float | None,
    th: float | None,
    tds: float | None,
) -> float | None:
    if not _all_finite(temp, tac, th, tds):
        return None
    # _all_finite() just confirmed none of these are None; make that visible
    # to mypy (it can't narrow through an opaque function call).
    assert temp is not None
    assert tac is not None
    assert th is not None
    assert tds is not None
    if tac <= 0 or th <= 0 or tds <= 0:
        return None
    try:
        result = round(_compute_ph_s(temp, tac, th, tds), 2)
    except (ValueError, OverflowError, ZeroDivisionError) as e:
        _LOGGER.warning("Math error in compute_ph_equilibrium: %s", e)
        return None
    return result if math.isfinite(result) else None


def compute_ph_calibrated(
    ph_raw: float, c4_meas: float, c7_meas: float, ref_4: float, ref_7: float
) -> float:
    """pH calibrated via the line through the two calibration points.

    Raises ValueError if the calibration is degenerate (measured points
    coincide, or zero slope): silently returning the raw pH or `ref_7` would
    mask a miscalibration made by the user.
    """
    if abs(c7_meas - c4_meas) < 0.01:
        raise ValueError("Degenerate pH calibration")
    slope = (ref_7 - ref_4) / (c7_meas - c4_meas)
    if abs(slope) < 1e-9:
        raise ValueError("Degenerate pH calibration")
    return ref_7 + (ph_raw - c7_meas) * slope
