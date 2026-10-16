# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

"""Decoding of the measurement frame sent by Blueriiot-based probes.

An active measurement is notified as a 12-byte frame starting with 0x33.
Layout (little-endian):

- byte 0      : marker 0x33
- bytes 1-2   : temperature, hundredths of a degree
- bytes 3-4   : raw pH value
- bytes 5-6   : raw ORP value
- bytes 7-8   : raw conductivity value (0 = no reading)
- bytes 9-10  : battery voltage, mV
- byte 11     : not used

Kept apart from protocol.py (Zodiac frames) on purpose.
"""

from __future__ import annotations

from typing import Any

FRAME_LENGTH = 12
FRAME_MARKER = 0x33

# Length of a stored frame once hex-encoded (see coordinator.async_initialize).
FRAME_HEX_LEN = FRAME_LENGTH * 2

BATTERY_EMPTY_MV = 3400
BATTERY_FULL_MV = 3640
CONDUCTIVITY_COEFFICIENT = 1.0615


def is_blueriiot_frame(frame: bytes | bytearray) -> bool:
    """True when `frame` has the length and marker of a measurement frame."""
    return len(frame) == FRAME_LENGTH and frame[0] == FRAME_MARKER


def _battery_percent(voltage_mv: int) -> int:
    """Battery voltage as a percentage clamped to 0-100."""
    span = BATTERY_FULL_MV - BATTERY_EMPTY_MV
    return max(0, min(100, round((voltage_mv - BATTERY_EMPTY_MV) / span * 100)))


def parse_blueriiot_frame(frame: bytes | bytearray) -> dict[str, Any] | None:
    """Decode a measurement frame, or return None if it is not one.

    The returned keys match what protocol.parse_raw_frame provides, so the
    coordinator applies offsets and calibration the same way. `temp_raw`,
    `ph_raw` and `orp_raw` are the probe values before any user calibration.
    """
    if not is_blueriiot_frame(frame):
        return None

    temperature = int.from_bytes(frame[1:3], "little") / 100.0
    ph = (2048 - int.from_bytes(frame[3:5], "little")) / 232.0 + 7.0
    orp = int.from_bytes(frame[5:7], "little") / 4.0 - 5.0
    conductivity_raw = int.from_bytes(frame[7:9], "little")
    battery_mv = int.from_bytes(frame[9:11], "little")

    conductivity: float | None = None
    salinity: float | None = None
    if conductivity_raw:
        conductivity = round(
            1 / (conductivity_raw * 1e-6) * CONDUCTIVITY_COEFFICIENT, 1
        )
        salinity = round(
            1 / (conductivity_raw * 0.001) * CONDUCTIVITY_COEFFICIENT * 0.5, 2
        )

    result: dict[str, Any] = {
        "device_type": "blueriiot",
        "temp_raw": temperature,
        "ph_raw": ph,
        "orp_raw": orp,
        "conductivity": conductivity,
        "salinity": salinity,
        "battery": battery_mv,
        "battery_percent": _battery_percent(battery_mv),
    }
    # A zero reading is ambiguous (no sensor, or no reading): only ever
    # promote to True, never overwrite a known value with False.
    if conductivity_raw:
        result["has_conductivity"] = True
    return result
