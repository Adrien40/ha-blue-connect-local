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
# Integration-side ORP calibration (optional, empty by default): the raw
# electrode potential (mV) measured by the probe in a reference solution
# (CONF_ORP_CALIB, from the "Raw ORP (mV)" sensor) and the potential of that
# solution (CONF_ORP_REF). When both are filled in, they take priority over
# the calibration stored in the probe.
CONF_ORP_CALIB = "orp_calib"
CONF_ORP_REF = "orp_ref"
CONF_TEMP_OFFSET = "temp_offset"

# Integration-side mV calibration for the high-resolution pH (optional, empty
# by default): two points, in millivolts, measured by the probe itself
# while dipped in two buffer solutions, with the pH of each solution
# (CONF_PH_HR_REF_*, separate from the CONF_PH_REF_* of the standard pH
# calibration above so that each method is entered in one place). When both
# potentials are filled in, it takes priority over the calibration stored in
# the probe for the high-resolution pH.
CONF_PH_HR_REF_7 = "ph_hr_ref_7"
CONF_PH_HR_REF_4 = "ph_hr_ref_4"
CONF_PH_HR_CALIB_MV_4 = "ph_hr_calib_mv_4"
CONF_PH_HR_CALIB_MV_7 = "ph_hr_calib_mv_7"
# Tick box of the options form, never stored: writes the pH and ORP
# calibrations entered in the form into the probe's own registers
# (70ea0015..0018 for the pH, 70ea001b/001c for the ORP) at the next analysis.
# Only what is filled in and has changed since the last successful push is
# written.
CONF_CALIB_PUSH = "calib_push"

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

# Origin of the pH sensor value (coordinator.data["ph_source"]).
# High resolution: electrode potential read in the electrical frame, converted
# with the calibration stored in the probe (2 decimals, active analysis only).
# Standard: pH of the calculated frame (0.1 resolution), calibrated.
PH_SOURCE_HIGH_RESOLUTION = "high_resolution"
PH_SOURCE_STANDARD = "standard"
PH_RESOLUTION_HIGH = 0.01
PH_RESOLUTION_STANDARD = 0.1

# Where the calibration used for the high-resolution pH came from
# (coordinator.data["ph_hr_calibration_source"]): the integration's own mV
# calibration (CONF_PH_HR_CALIB_MV_*), which takes priority when set, or
# the calibration stored in the probe (70ea0015..0018) otherwise.
PH_HR_CALIBRATION_SOURCE_INTEGRATION = "integration"
PH_HR_CALIBRATION_SOURCE_PROBE = "probe"

# Same idea for the ORP (coordinator.data["orp_calibration_source"]): the
# integration's own calibration (CONF_ORP_*), or the probe's (70ea001b/001c).
ORP_CALIBRATION_SOURCE_INTEGRATION = "integration"
ORP_CALIBRATION_SOURCE_PROBE = "probe"

# Calibration sanity checks, used to raise a (non-blocking) repair: the person
# stays free to keep and even push any calibration. These are generic
# electrode rules of thumb, not a Blue Connect specification.
# ORP: gap between the potential of the reference solution and the one the
# probe measured in it (a good electrode is within a few tens of mV).
ORP_CALIBRATION_MAX_OFFSET_MV = 100.0
# pH: electrode slope in mV per pH unit (59.16 theoretical at 25 C; about
# 85-106 % of it), and offset at pH 7 (deviation of the pH 7 potential from 0).
PH_CALIBRATION_MIN_SLOPE_MV = 50.0
PH_CALIBRATION_MAX_SLOPE_MV = 63.0
PH_CALIBRATION_MAX_OFFSET_MV = 60.0


CHAR_AUTH_UUID = "1fb20001-02c9-4001-bc9b-a2d1b18fab45"
# Auth result flag: 0x01 once the probe has validated the code written to
# CHAR_AUTH_UUID, 0x00 if it rejected it. Reading this lets us detect a
# bad access code immediately instead of waiting out the full
# TIMEOUT_NOTIFICATION_WAIT x2 (the probe never sends a measurement
# notification if auth failed).
CHAR_AUTH_STATUS_UUID = "1fb20002-02c9-4001-bc9b-a2d1b18fab45"
CHAR_TRIGGER_UUID = "70ea0003-7a29-4fdf-93d2-838665e72677"
# pH calibration stored in the probe (Zodiac profile only): the pH of the two
# buffer solutions (x10) and the electrode potential measured in each (0.1 mV).
CHAR_PH_CALIB_POINT_1_PH_UUID = "70ea0015-7a29-4fdf-93d2-838665e72677"
CHAR_PH_CALIB_POINT_2_PH_UUID = "70ea0016-7a29-4fdf-93d2-838665e72677"
CHAR_PH_CALIB_POINT_1_MV_UUID = "70ea0017-7a29-4fdf-93d2-838665e72677"
CHAR_PH_CALIB_POINT_2_MV_UUID = "70ea0018-7a29-4fdf-93d2-838665e72677"
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
# last pH calibration (the ORP one is 70ea0036 below): decoded as a big-endian Unix timestamp from the first
# 4 bytes (0 = never).
CHAR_FIRST_CONNECTION_UUID = "70ea0027-7a29-4fdf-93d2-838665e72677"
CHAR_PROBE_REPLACEMENT_UUID = "70ea0028-7a29-4fdf-93d2-838665e72677"
CHAR_LAST_PH_CALIB_UUID = "70ea0029-7a29-4fdf-93d2-838665e72677"
# ORP calibration stored in the probe (Zodiac profile only): the potential of
# the reference solution (ref) and the raw potential the electrode measured in
# it (mes), both signed 16-bit big-endian integers in mV. The calculated frame
# applies ref - mes to the raw electrode potential. The status register holds
# a code whose meaning is not documented (read as is, never interpreted).
CHAR_ORP_CALIB_STATUS_UUID = "70ea001a-7a29-4fdf-93d2-838665e72677"
CHAR_ORP_CALIB_REF_UUID = "70ea001b-7a29-4fdf-93d2-838665e72677"
CHAR_ORP_CALIB_MEAS_UUID = "70ea001c-7a29-4fdf-93d2-838665e72677"
# Date of the last ORP calibration: same format as the pH one (0 = never).
CHAR_LAST_ORP_CALIB_UUID = "70ea0036-7a29-4fdf-93d2-838665e72677"
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
POST_PAYLOAD_READ_COUNT = 20
# Pushing the integration's calibrations to the probe (once, on the analysis
# that follows the request, no retry): pH = four calibration registers and the
# calibration date, ORP = two calibration registers and the calibration date.
CALIB_PUSH_WRITE_COUNT = 8
# Worst case: one connection, up to 2 full auth+trigger+notification cycles,
# the calibration push, then the post-payload reads (raw_frame_0005, the four
# pH calibration values, the ORP calibration date, status and two values,
# accelerometer, serial number, SKU, Cloud ID, hardware version, NRF and ESP32
# firmware, first connection, probe replacement, last pH calibration, probe
# serial number), each individually bounded by TIMEOUT_GATT_OP.
TIMEOUT_FORCE_REFRESH = (
    TIMEOUT_BLE_CONN
    + 2 * (2 * TIMEOUT_GATT_OP + TIMEOUT_NOTIFICATION_WAIT)
    + CALIB_PUSH_WRITE_COUNT * TIMEOUT_GATT_OP
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

DEFAULT_PH_CALIB_7: float = 7.00
DEFAULT_PH_CALIB_4: float = 4.00
DEFAULT_PH_REF_7: float = 7.00
DEFAULT_PH_REF_4: float = 4.00


def mac_short_id(mac: str | None) -> str:
    """Last 4 hex digits of a MAC address, as shown in the device name."""
    return mac.replace(":", "")[-4:].upper() if mac else ""


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
    mac_suffix = mac_short_id(mac)
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
