# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

from __future__ import annotations

SKU_SILVER = "WA000099"
SKU_GOLD = "WA000100"

DEVICE_TYPE_BLUERIIOT = "blueriiot"
MODEL_BLUE_CONNECT_PLUS = "Blue Connect Plus"

MANUFACTURER_ZODIAC = "Zodiac"
MANUFACTURER_BLUERIIOT = "Blueriiot"

KNOWN_MODELS = {
    SKU_GOLD: "Blue Connect Gold",
    SKU_SILVER: "Blue Connect Silver",
}


def get_blue_connect_model(
    sku: str | None,
    has_conductivity: bool | None = None,
    device_type: str | None = None,
) -> str:
    """Return the commercial model name based on the SKU.

    sku (from an authenticated GATT read) is the authoritative source
    when known. When it isn't - no access_code was ever provided, or no
    authenticated read has happened yet - has_conductivity (derived from
    passive BLE frames, no access_code required) is used as a fallback
    signal instead of guessing.

    A Blueriiot-profile probe (device_type "blueriiot") is a Blue Connect
    Plus: it has no ZODIAC SKU nor passive frame to look at.
    """
    if device_type == DEVICE_TYPE_BLUERIIOT:
        return MODEL_BLUE_CONNECT_PLUS

    if sku:
        sku_upper = sku.upper()
        for sku_candidate, model_name in KNOWN_MODELS.items():
            if sku_candidate in sku_upper:
                return model_name
        return "Blue Connect"

    if has_conductivity is True:
        return "Blue Connect Gold"
    if has_conductivity is False:
        return "Blue Connect Silver"

    return "Blue Connect"


def model_has_conductivity(
    sku: str | None, has_conductivity: bool | None = None
) -> bool:
    """Check if conductivity (and therefore salinity) should be enabled
    by default.

    Same priority as get_blue_connect_model(): sku first, then
    has_conductivity as a passive-mode fallback, then the optimistic
    default when neither signal is available yet.
    """
    if sku:
        return SKU_SILVER not in sku.upper()

    if has_conductivity is not None:
        return has_conductivity

    return True


# Salinity is computed on-device from conductivity: a model without a
# conductivity sensor never has real salinity data either. Kept as a
# separate name at call sites (clearer than gating a salinity entity on
# "model_has_conductivity") even though the logic is identical.
model_has_salinity = model_has_conductivity


def get_manufacturer(model_name: str) -> str:
    """Brand of the probe: only the Blue Connect Plus is a Blueriiot probe."""
    if model_name == MODEL_BLUE_CONNECT_PLUS:
        return MANUFACTURER_BLUERIIOT
    return MANUFACTURER_ZODIAC
