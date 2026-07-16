# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

from __future__ import annotations

KNOWN_MODELS = {
    "BC3-QX25003300": "Blue Connect Gold",
    "BC3-QX25001952": "Blue Connect Silver",
}


def get_blue_connect_model(name: str | None) -> str:
    if not name:
        return "Blue Connect Silver"

    name_upper = name.upper()

    for prefix, model_name in KNOWN_MODELS.items():
        if name_upper.startswith(prefix):
            return model_name

    return "Blue Connect Silver"


def model_has_salinity(model_name: str) -> bool:
    return "Silver" not in model_name
