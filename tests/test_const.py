"""Tests for model-detection helpers.

get_blue_connect_model/model_has_salinity now live in model.py (not
const.py): const.py imports homeassistant.helpers.device_registry at module
level (for blue_connect_device_info), so importing them straight from
const.py would have required installing homeassistant. const.py still
re-exports both names for sensor.py / switch.py / etc.
"""

from ._load_pure import load_pure_module

_model = load_pure_module("model.py")
get_blue_connect_model = _model.get_blue_connect_model
model_has_salinity = _model.model_has_salinity


def test_get_blue_connect_model_gold():
    assert get_blue_connect_model("BC3-QX25003300-1A2B3C") == "Blue Connect Gold"


def test_get_blue_connect_model_silver_otherwise():
    assert get_blue_connect_model("BC3-XX00000000-1A2B3C") == "Blue Connect Silver"


def test_get_blue_connect_model_none_gives_silver():
    assert get_blue_connect_model(None) == "Blue Connect Silver"


def test_model_has_salinity_gold_yes_silver_no():
    assert model_has_salinity("Blue Connect Gold") is True
    assert model_has_salinity("Blue Connect Silver") is False
