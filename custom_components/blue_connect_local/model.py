# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

"""Model (Gold/Silver) detection from the advertised BLE name.

Extracted from const.py: const.py imports homeassistant.helpers.device_registry
at module level (for blue_connect_device_info), which prevented testing
get_blue_connect_model/model_has_salinity without installing homeassistant,
even though they don't depend on it themselves.

const.py re-exports both names (`from .model import ...`) so nothing breaks:
sensor.py, binary_sensor.py, button.py, number.py, switch.py, time.py and
config_flow.py all import them from `.const`.
"""

from __future__ import annotations


def get_blue_connect_model(name: str | None) -> str:
    if not name:
        return "Blue Connect Silver"
    name_upper = name.upper()
    if name_upper.startswith("BC3-QX25003300"):
        return "Blue Connect Gold"
    return "Blue Connect Silver"


def model_has_salinity(model_name: str) -> bool:
    return "Silver" not in model_name
