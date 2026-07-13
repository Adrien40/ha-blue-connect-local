"""Tests for two-point pH calibration (chemistry.compute_ph_calibrated).

Extracted from coordinator.py: _compute_ph_calibrated never used self.
Note: the real function does NOT round its result (unlike what an example
"7.4 -> 7.5357" might suggest) — hence pytest.approx instead of strict
equality.
"""

import pytest

from ._load_pure import load_pure_module

compute_ph_calibrated = load_pure_module("chemistry.py").compute_ph_calibrated


def test_calibration_default_is_identity():
    result = compute_ph_calibrated(7.4, c4_meas=4.0, c7_meas=7.0, ref_4=4.0, ref_7=7.0)
    assert result == pytest.approx(7.4)


def test_calibration_with_drift():
    result = compute_ph_calibrated(7.4, c4_meas=4.1, c7_meas=6.9, ref_4=4.0, ref_7=7.0)
    assert result == pytest.approx(7.535714, abs=1e-5)


def test_calibration_guard_measured_points_nearly_identical():
    # measured gap < 0.01 -> ph_raw returned unchanged
    result = compute_ph_calibrated(
        7.4, c4_meas=5.0, c7_meas=5.005, ref_4=4.0, ref_7=7.0
    )
    assert result == 7.4


def test_calibration_guard_near_zero_slope():
    # normal measured gap, but identical references -> zero slope -> ref_7
    result = compute_ph_calibrated(7.4, c4_meas=4.0, c7_meas=7.0, ref_4=5.0, ref_7=5.0)
    assert result == 5.0
