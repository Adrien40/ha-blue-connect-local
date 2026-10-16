# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

from __future__ import annotations

from datetime import timedelta

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

# The "as X" re-exports below are the explicit-reexport idiom mypy --strict
# requires (implicit_reexport is off in strict mode): a plain import here
# would make the names unusable via `from .const import get_blue_connect_model`
# elsewhere in the package.
from .model import (
    DEVICE_TYPE_BLUERIIOT as DEVICE_TYPE_BLUERIIOT,
    MODEL_BLUE_CONNECT_PLUS as MODEL_BLUE_CONNECT_PLUS,
    get_blue_connect_model as get_blue_connect_model,
    get_manufacturer as get_manufacturer,
    model_has_conductivity as model_has_conductivity,
    model_has_salinity as model_has_salinity,
)

DOMAIN = "blue_connect_local"

PLATFORMS = ["sensor", "binary_sensor", "button", "number", "switch", "time"]

CONF_MAC_ADDRESS = "mac_address"
CONF_ACCESS_CODE = "access_code"

CONF_PH_CALIB_4 = "ph_calib_4"
CONF_PH_CALIB_7 = "ph_calib_7"
CONF_PH_REF_7 = "ph_ref_7"
CONF_PH_REF_4 = "ph_ref_4"
CONF_ORP_CALIB = "orp_calib"
CONF_ORP_REF = "orp_ref"
CONF_TEMP_OFFSET = "temp_offset"

CONF_PH_MIN = "ph_min"
CONF_PH_MAX = "ph_max"
CONF_ORP_MIN = "orp_min"
CONF_ORP_MAX = "orp_max"
CONF_TEMP_MIN = "temp_min"
CONF_TEMP_MAX = "temp_max"

CONF_TAC = "tac"
CONF_TH = "th"
CONF_TDS = "tds"
CONF_CYA = "cya"
CONF_CHLORINE_MODEL = "chlorine_model"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_REFERENCE_TIME = "reference_time"
CONF_PASSIVE_MEASURES = "passive_measures"
CONF_IGNORE_ECHOES = "ignore_echoes"

CHAR_AUTH_UUID = "1fb20001-02c9-4001-bc9b-a2d1b18fab45"
# Auth result flag: 0x01 once the probe has validated the code written to
# CHAR_AUTH_UUID, 0x00 if it rejected it. Reading this lets us detect a
# bad access code immediately instead of waiting out the full
# TIMEOUT_NOTIFICATION_WAIT x2 (the probe never sends a measurement
# notification if auth failed).
CHAR_AUTH_STATUS_UUID = "1fb20002-02c9-4001-bc9b-a2d1b18fab45"
CHAR_TRIGGER_UUID = "70ea0003-7a29-4fdf-93d2-838665e72677"
CHAR_NOTIFY_UUID = "70ea0004-7a29-4fdf-93d2-838665e72677"
# Diagnostic characteristics read once the measurement has been received
# (Zodiac profile only; never read on Blueriiot probes).
# Hardware revision, decoded as bytes[2].bytes[1].bytes[0] (e.g. "1.0.0").
CHAR_HW_VERSION_UUID = "70ea0023-7a29-4fdf-93d2-838665e72677"
# Firmware of the ESP32 and of the nRF chips, same layout as the hardware
# revision.
CHAR_ESP32_FW_UUID = "70ea0024-7a29-4fdf-93d2-838665e72677"
CHAR_NRF_FW_UUID = "70ea0025-7a29-4fdf-93d2-838665e72677"
# Date of the first connection, of the last probe replacement and of the
# last pH calibration: decoded as a big-endian Unix timestamp from the first
# 4 bytes (0 = never).
CHAR_FIRST_CONNECTION_UUID = "70ea0027-7a29-4fdf-93d2-838665e72677"
CHAR_PROBE_REPLACEMENT_UUID = "70ea0028-7a29-4fdf-93d2-838665e72677"
CHAR_LAST_PH_CALIB_UUID = "70ea0029-7a29-4fdf-93d2-838665e72677"
# Serial number of the probe itself (not of the Blue Connect hub).
CHAR_PROBE_SERIAL_UUID = "70ea0030-7a29-4fdf-93d2-838665e72677"

TIMEOUT_BLE_CONN = 30.0
TIMEOUT_GATT_OP = 10.0
TIMEOUT_NOTIFICATION_WAIT = 60.0
TIMEOUT_SAFETY_MARGIN = 30.0
# BLE cycle pauses (named so they can be shortened in tests).
AUTH_SETTLE_DELAY = 0.2  # let the probe process the written access code
AUTH_STATUS_RETRY_DELAY = 0.5  # 2nd read of the authentication status
GATT_WRITE_RETRY_DELAY = 1.0  # pause before retrying a write
ERROR_RETRY_DELAY = 60  # seconds before retrying after a BLE error
FIRST_ANALYSIS_DELAY = 2.0  # delay before the 1st active analysis at startup
POST_PAYLOAD_READ_COUNT = 12
# Worst case: one connection, up to 2 full auth+trigger+notification cycles,
# then the post-payload reads (raw_frame_0005, accelerometer, serial number,
# SKU, Cloud ID, hardware version, NRF and ESP32 firmware, first connection,
# probe replacement, last pH calibration, probe serial number), each
# individually bounded by TIMEOUT_GATT_OP.
TIMEOUT_FORCE_REFRESH = (
    TIMEOUT_BLE_CONN
    + 2 * (2 * TIMEOUT_GATT_OP + TIMEOUT_NOTIFICATION_WAIT)
    + POST_PAYLOAD_READ_COUNT * TIMEOUT_GATT_OP
    + TIMEOUT_SAFETY_MARGIN
)
DEBOUNCE_COOLDOWN = 0.3
REPAIR_STALE_AFTER = timedelta(days=3)
SAVE_DEBOUNCE_DELAY = 2.0

BLE_RECENTLY_SEEN_THRESHOLD_S: int = 120

EXPECTED_FRAME_HEX_LEN_18: int = 36
ECHO_MARKER = "B"
ACCEL_THRESHOLD = 700

BT_STATUS_WAITING = "waiting"
BT_STATUS_CONNECTING = "connecting"
BT_STATUS_AUTHENTICATING = "authenticating"
BT_STATUS_REQUESTING = "requesting"
BT_STATUS_READING = "reading"
BT_STATUS_SUCCESS = "success"
BT_STATUS_ERROR = "error"
BT_STATUS_ERROR_RETRY = "error_retry"
BT_STATUS_WRITE_FAILED = "write_failed"
BT_STATUS_PAUSED = "paused"
BT_STATUS_OUT_OF_RANGE = "out_of_range"
BT_STATUS_AUTH_FAILED = "auth_failed"

DEFAULT_PH_MIN: float = 6.90
DEFAULT_PH_MAX: float = 7.40
DEFAULT_ORP_MIN: float = 650.0
DEFAULT_ORP_MAX: float = 750.0
DEFAULT_TEMP_MIN: float = 6.0
DEFAULT_TEMP_MAX: float = 32.0

DEFAULT_ORP_CALIB: float = 650.0
DEFAULT_ORP_REF: float = 650.0

DEFAULT_PH_CALIB_7: float = 7.00
DEFAULT_PH_CALIB_4: float = 4.00
DEFAULT_PH_REF_7: float = 7.00
DEFAULT_PH_REF_4: float = 4.00


def blue_connect_device_info(
    mac: str,
    model_name: str,
    model_id: str | None = None,
    serial_number: str | None = None,
    hw_version: str | None = None,
    sw_version: str | None = None,
) -> DeviceInfo:
    """Return device registry information for the Blue Connect device.

    `model_id` is the commercial SKU read from GATT characteristic
    70ea0021 (e.g. "WA000100"), stored internally as
    coordinator.data["sku"]. It is not a real hardware revision, so it
    is surfaced here as `model_id` - the HA DeviceInfo field reserved
    for part numbers/SKUs.
    `hw_version` is the real hardware revision read from 70ea0023
    (e.g. "1.0.0"), stored as coordinator.data["hardware_version"].
    `sw_version` combines the NRF firmware (70ea0025, e.g. "0.31.4") and the
    ESP32 firmware (70ea0024, e.g. "0.13.5"), stored as
    coordinator.data["firmware_version"].
    """
    mac_suffix = mac.replace(":", "")[-4:].upper() if mac else ""
    display_name = f"{model_name} ({mac_suffix})" if mac_suffix else model_name
    return DeviceInfo(
        identifiers={(DOMAIN, mac)},
        connections={(CONNECTION_BLUETOOTH, mac)},
        name=display_name,
        manufacturer=get_manufacturer(model_name),
        model=model_name,
        model_id=model_id,
        serial_number=serial_number,
        hw_version=hw_version,
        sw_version=sw_version,
    )
