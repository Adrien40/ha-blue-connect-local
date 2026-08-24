# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

from __future__ import annotations

SKU_SILVER = "WA000099"
SKU_GOLD = "WA000100"

KNOWN_MODELS = {
    SKU_GOLD: "Blue Connect Gold",
    SKU_SILVER: "Blue Connect Silver",
}


def get_blue_connect_model(
    hw_version: str | None, has_conductivity: bool | None = None
) -> str:
    """Return the commercial model name based on hardware revision (SKU).

    hw_version (from an authenticated GATT read) is the authoritative
    source when known. When it isn't - no access_code was ever provided,
    or no authenticated read has happened yet - has_conductivity (derived
    from passive BLE frames, no access_code required) is used as a
    fallback signal instead of guessing.
    """
    if hw_version:
        hw_upper = hw_version.upper()
        for sku, model_name in KNOWN_MODELS.items():
            if sku in hw_upper:
                return model_name
        return "Blue Connect"

    if has_conductivity is True:
        return "Blue Connect Gold"
    if has_conductivity is False:
        return "Blue Connect Silver"

    return "Blue Connect"


def model_has_conductivity(
    hw_version: str | None, has_conductivity: bool | None = None
) -> bool:
    """Check if conductivity (and therefore salinity) should be enabled
    by default.

    Same priority as get_blue_connect_model(): hw_version first, then
    has_conductivity as a passive-mode fallback, then the optimistic
    default when neither signal is available yet.
    """
    if hw_version:
        return SKU_SILVER not in hw_version.upper()

    if has_conductivity is not None:
        return has_conductivity

    return True


# Salinity is computed on-device from conductivity: a model without a
# conductivity sensor never has real salinity data either. Kept as a
# separate name at call sites (clearer than gating a salinity entity on
# "model_has_conductivity") even though the logic is identical.
model_has_salinity = model_has_conductivity
