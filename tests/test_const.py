"""Tests for model-detection helpers.

get_blue_connect_model/model_has_conductivity now live in model.py (not
const.py): const.py imports homeassistant.helpers.device_registry at module
level (for blue_connect_device_info), so importing them straight from
const.py would have required installing homeassistant. const.py still
re-exports these names for sensor.py / switch.py / etc.
"""

from ._load_pure import load_pure_module

_model = load_pure_module("model.py")
get_blue_connect_model = _model.get_blue_connect_model
model_has_conductivity = _model.model_has_conductivity
model_has_salinity = _model.model_has_salinity


def test_get_blue_connect_model_gold():
    assert get_blue_connect_model("WA000100-REV2") == "Blue Connect Gold"


def test_get_blue_connect_model_silver():
    assert get_blue_connect_model("WA000099-REV1") == "Blue Connect Silver"


def test_get_blue_connect_model_is_case_insensitive():
    assert get_blue_connect_model("wa000100-rev2") == "Blue Connect Gold"
    assert get_blue_connect_model("wa000099-rev1") == "Blue Connect Silver"


def test_get_blue_connect_model_unknown_hw_version_gives_generic():
    assert get_blue_connect_model("SOME-OTHER-HW") == "Blue Connect"


def test_get_blue_connect_model_none_gives_generic():
    assert get_blue_connect_model(None) == "Blue Connect"


def test_model_has_salinity_silver_is_disabled():
    assert model_has_salinity("WA000099-REV1") is False


def test_model_has_salinity_gold_and_unknown_are_enabled():
    assert model_has_salinity("WA000100-REV2") is True
    assert model_has_salinity("SOME-OTHER-HW") is True


def test_model_has_salinity_unknown_hw_version_defaults_enabled():
    # No hw_version read yet (fresh setup, or no access_code ever provided):
    # optimistic default so Gold owners aren't hidden behind a guess.
    assert model_has_salinity(None) is True


def test_hw_version_takes_priority_over_has_conductivity():
    # A known SKU is authoritative - it must win even if the passive
    # conductivity signal would suggest the opposite (e.g. stale data,
    # or a Gold unit with a transiently unavailable probe).
    assert get_blue_connect_model("WA000100", has_conductivity=False) == (
        "Blue Connect Gold"
    )
    assert model_has_salinity("WA000100", has_conductivity=False) is True
    assert get_blue_connect_model("WA000099", has_conductivity=True) == (
        "Blue Connect Silver"
    )
    assert model_has_salinity("WA000099", has_conductivity=True) is False


def test_has_conductivity_fallback_when_hw_version_unknown():
    # Passive mode, no access_code: hw_version is never known, so
    # has_conductivity (from passive frames) is the only available signal.
    assert get_blue_connect_model(None, has_conductivity=True) == "Blue Connect Gold"
    assert get_blue_connect_model(None, has_conductivity=False) == "Blue Connect Silver"
    assert model_has_salinity(None, has_conductivity=True) is True
    assert model_has_salinity(None, has_conductivity=False) is False


def test_neither_signal_available_defaults_to_generic_optimistic():
    assert get_blue_connect_model(None, has_conductivity=None) == "Blue Connect"
    assert model_has_salinity(None, has_conductivity=None) is True


def test_model_has_salinity_is_an_alias_of_model_has_conductivity():
    # Salinity is computed on-device from conductivity: a model without a
    # conductivity sensor never has real salinity data either. They must
    # stay identical, not just equivalent - a future edit to one that
    # forgets the other should fail this test.
    assert model_has_salinity is model_has_conductivity
