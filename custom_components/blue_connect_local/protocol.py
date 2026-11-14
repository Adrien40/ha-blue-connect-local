# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

"""Pure decoders for the data the Blue Connect probe exposes over BLE.

Covers the 18/19-byte measurement payload (advertisement or notification),
the electrical frame (pH and ORP electrode potentials) and the pH and ORP
calibration registers stored in the probe. None of them touches Home Assistant or a BLE
client, so they can be tested without either.
"""

from __future__ import annotations

from typing import Any

# Sentinel value the probe sends in the conductivity field when it has no
# conductivity sensor wired (Blue Connect Silver). Salinity is derived from
# conductivity on-device, so when conductivity is this sentinel, salinity
# is not a real reading either - it decodes to a fixed, meaningless value.
CONDUCTIVITY_SENSOR_ABSENT = 0xFFFF


def extract_raw_payload(
    manufacturer_data: dict[Any, bytes], service_data: dict[Any, bytes]
) -> bytes | None:
    """Pick the raw 18/19-byte sensor payload out of a BLE advertisement.

    Shared between the coordinator's passive listener (coordinator.py) and
    the config flow (config_flow.py, which peeks at the advertisement
    during discovery - before any active connection exists - to guess
    Gold vs Silver for display purposes only).
    """
    for mfr_data in manufacturer_data.values():
        if len(mfr_data) in (18, 19):
            return mfr_data
    for svc_data in service_data.values():
        if len(svc_data) in (18, 19):
            return svc_data
    return None


def parse_raw_frame(data: bytes) -> dict[str, Any] | None:
    """Decode an 18/19-byte measurement payload of a ZODIAC Blue Connect.

    Returns None for any other length. ``ph_raw`` and ``orp_raw`` are the pH
    and ORP of the calculated frame (probe calibration applied; 0.1 resolution
    for the pH), not the uncalibrated electrode potentials: the coordinator
    stores them as ``ph_probe_calibrated`` and ``orp_probe_calibrated``.
    """
    if len(data) not in (18, 19):
        return None

    # The length check above guarantees every index below is in range
    # (the highest one read is 15 for 18 bytes, 16 for 19 bytes).
    offset = 4 if len(data) == 19 else 3
    raw_temp = ((data[offset] << 8) | data[offset + 1]) / 100.0
    raw_ph = ((data[offset + 2] << 8) | data[offset + 3]) / 10.0
    raw_orp = (data[offset + 4] << 8) | data[offset + 5]
    cond = (data[offset + 6] << 8) | data[offset + 7]
    salinity = ((data[offset + 8] << 8) | data[offset + 9]) / 100.0
    battery_percent = data[offset + 10]
    battery_adc = (data[offset + 11] << 8) | data[offset + 12]
    battery_mv = int(battery_adc * 0.8791)

    has_conductivity = cond != CONDUCTIVITY_SENSOR_ABSENT

    return {
        "temp_raw": raw_temp,
        "ph_raw": raw_ph,
        "orp_raw": raw_orp,
        "conductivity": cond if has_conductivity else None,
        "salinity": round(salinity, 2) if has_conductivity else None,
        "battery_percent": battery_percent,
        "battery_adc": battery_adc,
        "battery": battery_mv,
        "has_conductivity": has_conductivity,
    }


# The electrical frame (characteristic 70ea0005) is a sequence of 16-bit
# big-endian words. Two are decoded: word 1, the pH electrode potential
# (signed, 0.1 mV), and word 2, the ORP electrode potential (signed, 1 mV).
ELECTRICAL_FRAME_MIN_LEN = 4
ELECTRICAL_FRAME_ORP_MIN_LEN = 6


def parse_electrical_frame(data: bytes) -> float | None:
    """Decode the pH electrode potential (mV, 0.1 mV resolution) of the frame.

    None when the frame is too short to hold it.
    """
    if len(data) < ELECTRICAL_FRAME_MIN_LEN:
        return None
    return int.from_bytes(data[2:4], byteorder="big", signed=True) / 10.0


def parse_electrical_orp(data: bytes) -> int | None:
    """Decode the ORP electrode potential (mV) of the electrical frame.

    This is the potential read by the electrode before any calibration: the
    ORP of the calculated frame is this value plus the probe's own offset
    (ref - mes, see parse_orp_calibration). None when the frame is too short
    to hold it.
    """
    if len(data) < ELECTRICAL_FRAME_ORP_MIN_LEN:
        return None
    return int.from_bytes(data[4:6], byteorder="big", signed=True)


def parse_ph_calibration(
    point_1_ph: bytes, point_2_ph: bytes, point_1_mv: bytes, point_2_mv: bytes
) -> dict[str, float] | None:
    """Decode the pH calibration stored in the probe (two buffer solutions).

    Each value is a 16-bit big-endian word: the pH of the buffer (x10) and the
    electrode potential measured in it (0.1 mV, signed). Returns None when the
    calibration cannot be trusted:

    - a value is missing;
    - a buffer pH is outside 0-14 (an unwritten register reads 0 or 6553.5);
    - the two buffers or the two potentials are identical, since the slope
      could not be computed;
    - the slope has the wrong sign: a pH electrode reads a lower potential as
      the pH rises, so the more acidic buffer must have the higher potential.
    """
    if any(
        len(value) < 2 for value in (point_1_ph, point_2_ph, point_1_mv, point_2_mv)
    ):
        return None
    calibration = {
        "ph_1": int.from_bytes(point_1_ph[:2], byteorder="big") / 10.0,
        "ph_2": int.from_bytes(point_2_ph[:2], byteorder="big") / 10.0,
        "mv_1": int.from_bytes(point_1_mv[:2], byteorder="big", signed=True) / 10.0,
        "mv_2": int.from_bytes(point_2_mv[:2], byteorder="big", signed=True) / 10.0,
    }
    if not all(0.0 < calibration[key] < 14.0 for key in ("ph_1", "ph_2")):
        return None
    if calibration["ph_1"] == calibration["ph_2"]:
        return None
    if calibration["mv_1"] == calibration["mv_2"]:
        return None
    if (calibration["ph_2"] - calibration["ph_1"]) * (
        calibration["mv_2"] - calibration["mv_1"]
    ) > 0:
        return None
    return calibration


# An ORP meter cannot read beyond about +-2 V: anything larger is not a
# potential but garbage.
_ORP_CALIBRATION_MAX_ABS_MV = 2000


def parse_orp_calibration(ref: bytes, meas: bytes) -> dict[str, int] | None:
    """Decode the ORP calibration stored in the probe.

    Two signed 16-bit big-endian words, directly in mV: ``ref`` is the
    potential of the reference solution, ``mes`` the raw potential the
    electrode measured in it. The probe adds ``ref - mes`` to the raw
    potential. Returns None when the calibration cannot be trusted: a
    register is missing, or reads 0 or -1 (an unwritten register), or is
    beyond the physical range of an ORP electrode.
    """
    if len(ref) < 2 or len(meas) < 2:
        return None
    calibration = {
        "ref": int.from_bytes(ref[:2], byteorder="big", signed=True),
        "mes": int.from_bytes(meas[:2], byteorder="big", signed=True),
    }
    if any(
        value in (0, -1) or abs(value) > _ORP_CALIBRATION_MAX_ABS_MV
        for value in calibration.values()
    ):
        return None
    return calibration
