"""Tests for water chemistry calculations (compute_lsi, compute_ph_equilibrium).

Loaded via _load_pure (see that file): __init__.py imports homeassistant and
bleak transitively, so a normal package import fails without them.
"""

from ._load_pure import load_pure_module

_chemistry = load_pure_module("chemistry.py")
compute_lsi = _chemistry.compute_lsi
compute_ph_equilibrium = _chemistry.compute_ph_equilibrium


def test_lsi_none_if_missing_data():
    assert compute_lsi(None, 7.4, 100, 250, 1000) is None


def test_lsi_none_if_tac_th_tds_not_positive():
    assert compute_lsi(28, 7.4, 0, 250, 1000) is None
    assert compute_lsi(28, 7.4, 100, -5, 1000) is None


def test_lsi_balanced_water():
    # Re-verified against the real code (Kelvin = +273.15, not +273):
    # temp=27, ph=7.4, tac=100, th=250, tds=1000 -> LSI=-0.15
    assert compute_lsi(27, 7.4, 100, 250, 1000) == -0.15


def test_lsi_corrosive_water():
    assert compute_lsi(15, 6.8, 30, 50, 200) < -0.3


def test_lsi_scaling_water():
    assert compute_lsi(32, 8.2, 300, 600, 3000) > 0.3


def test_ph_equilibrium_plausible():
    phs = compute_ph_equilibrium(temp=27, tac=100, th=250, tds=1000)
    assert 6.5 < phs < 8.5  # re-verified against the real code: 7.55
