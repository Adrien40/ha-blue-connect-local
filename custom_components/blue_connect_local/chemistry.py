# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import logging
import math
from collections.abc import Mapping

_LOGGER = logging.getLogger(__name__)


# "Raw pH": the electrode potential read as a pH with no calibration at all.
# Any mV -> pH conversion needs a slope and a zero, so this one is a fixed
# reference, identical for everyone: pH 7 at 0 mV and the theoretical slope of
# a glass electrode at 25 degC (2.303 R T / F = 59.16 mV per pH unit).
PH_RAW_NEUTRAL_MV = 0.0
PH_RAW_SLOPE_MV_PER_PH = 59.16


def compute_ph_raw_from_mv(ph_mv: float | None) -> float | None:
    """pH read straight from the electrode potential, without calibration.

    None when there is no potential, or when the result is outside 0-14.
    """
    if ph_mv is None or not math.isfinite(ph_mv):
        return None
    ph = 7.0 - (ph_mv - PH_RAW_NEUTRAL_MV) / PH_RAW_SLOPE_MV_PER_PH
    return round(ph, 2) if 0.0 <= ph <= 14.0 else None


def compute_ph_two_point(ph_mv: float, calibration: Mapping[str, float]) -> float:
    """pH from the electrode potential, with the calibration stored in the probe.

    The probe calibrates its pH electrode on two buffer solutions and keeps,
    for each, the pH and the potential measured (mV). Its firmware converts
    a potential to a pH by linear interpolation between these two points, with
    no temperature compensation. The calculated frame carries that pH rounded
    to 0.1: this function gives it without the rounding.

    Raises ValueError when the two points coincide (a probe never calibrated,
    or a wrong entry): there is no line through them, and any pH computed from
    it would be made up.
    """
    ph_gap = calibration["ph_1"] - calibration["ph_2"]
    mv_gap = calibration["mv_1"] - calibration["mv_2"]
    if abs(ph_gap) < 1e-9 or abs(mv_gap) < 1e-9:
        raise ValueError("Degenerate pH calibration")
    slope = mv_gap / ph_gap
    return calibration["ph_2"] + (ph_mv - calibration["mv_2"]) / slope


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


def orp_calibration_offset(ref: float, mes: float) -> float:
    """Correction (mV) of an ORP calibration: the reference minus what was measured.

    The probe adds it to the raw electrode potential; the integration's own
    calibration does the same.
    """
    return ref - mes


def compute_orp_calibrated(orp_raw_mv: float, ref: float, mes: float) -> float:
    """ORP (mV) from the raw electrode potential and an ORP calibration."""
    return orp_raw_mv + orp_calibration_offset(ref, mes)


def compute_orp_raw_from_calibrated(
    orp_calibrated: float, ref: float, mes: float
) -> float:
    """Raw electrode potential (mV) behind an ORP the probe already corrected.

    Inverse of compute_orp_calibrated, for a frame the probe broadcasts on its
    own (the raw potential is only read during an active analysis): ``ref`` and
    ``mes`` are the probe's own calibration.
    """
    return orp_calibrated - orp_calibration_offset(ref, mes)


def ph_calibration_quality(
    calibration: Mapping[str, float],
) -> tuple[float, float] | None:
    """Slope and offset of a two-point pH calibration, to judge the electrode.

    Returns ``(slope, offset)``: ``slope`` is the electrode response in mV per
    pH unit (a positive number, 59.16 in theory at 25 degC) and ``offset`` is
    the potential, in mV, the line gives at pH 7 (0 for a perfect electrode).
    None when the two points coincide, or when the slope has the wrong sign
    (the more acidic buffer must read the higher potential).
    """
    ph_1, ph_2 = calibration["ph_1"], calibration["ph_2"]
    mv_1, mv_2 = calibration["mv_1"], calibration["mv_2"]
    if abs(ph_2 - ph_1) < 1e-9 or abs(mv_2 - mv_1) < 1e-9:
        return None
    signed_slope = (mv_2 - mv_1) / (ph_2 - ph_1)
    if signed_slope >= 0:
        return None
    offset = mv_1 + signed_slope * (7.0 - ph_1)
    return -signed_slope, offset
