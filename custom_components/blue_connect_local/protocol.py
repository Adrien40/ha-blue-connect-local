# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

"""Decoding of raw BLE frames sent by the Blue Connect probe.

Extracted from coordinator.py: _parse_raw_frame never used self, it was a
pure function disguised as a method. Body unchanged, no behavior change —
only `self` was removed.
"""

from __future__ import annotations

from typing import Any


def parse_raw_frame(data: bytes) -> dict[str, Any] | None:
    if len(data) not in (18, 19):
        return None

    offset = 4 if len(data) == 19 else 3
    try:
        raw_temp = ((data[offset] << 8) | data[offset + 1]) / 100.0
        raw_ph = ((data[offset + 2] << 8) | data[offset + 3]) / 10.0
        raw_orp = (data[offset + 4] << 8) | data[offset + 5]
        cond = (data[offset + 6] << 8) | data[offset + 7]
        salinity = ((data[offset + 8] << 8) | data[offset + 9]) / 100.0
        battery_percent = data[offset + 10]
        battery_adc = (data[offset + 11] << 8) | data[offset + 12]
        battery_mv = int(battery_adc * 0.8791)

        return {
            "temp_raw": raw_temp,
            "ph_raw": raw_ph,
            "orp_raw": raw_orp,
            "conductivity": cond,
            "salinity": round(salinity, 2),
            "battery_percent": battery_percent,
            "battery_adc": battery_adc,
            "battery": battery_mv,
        }
    except IndexError:
        return None
