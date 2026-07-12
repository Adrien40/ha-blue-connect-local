# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import math
import logging

_LOGGER = logging.getLogger(__name__)


def _compute_ph_s(temp_c: float, tac_c: float, th_c: float, tds_c: float) -> float:
    a = (math.log10(tds_c) - 1.0) / 10.0
    b = -13.12 * math.log10(temp_c + 273.15) + 34.55
    c = math.log10(th_c) - 0.4
    d = math.log10(tac_c)
    return (9.3 + a + b) - (c + d)


def compute_lsi(
    temp: float | None,
    ph: float | None,
    tac: float | None,
    th: float | None,
    tds: float | None,
) -> float | None:
    if any(v is None for v in [temp, ph, tac, th, tds]):
        return None
    if float(tac) <= 0 or float(th) <= 0 or float(tds) <= 0:
        return None
    try:
        ph_s = _compute_ph_s(float(temp), float(tac), float(th), float(tds))
        return round(float(ph) - ph_s, 2)
    except (ValueError, OverflowError, ZeroDivisionError) as e:
        _LOGGER.warning("Math error in compute_lsi: %s", e)
        return None


def compute_ph_equilibrium(
    temp: float | None,
    tac: float | None,
    th: float | None,
    tds: float | None,
) -> float | None:
    if any(v is None for v in [temp, tac, th, tds]):
        return None
    if float(tac) <= 0 or float(th) <= 0 or float(tds) <= 0:
        return None
    try:
        return round(_compute_ph_s(float(temp), float(tac), float(th), float(tds)), 2)
    except (ValueError, OverflowError, ZeroDivisionError) as e:
        _LOGGER.warning("Math error in compute_ph_equilibrium: %s", e)
        return None
