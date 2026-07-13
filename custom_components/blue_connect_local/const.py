# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

from datetime import timedelta
from homeassistant.helpers.device_registry import DeviceInfo

from .model import get_blue_connect_model, model_has_salinity  # noqa: F401 (re-export)

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

SERVICE_AUTH_UUID = "1fb21fd9-02c9-4001-bc9b-a2d1b18fab45"
CHAR_AUTH_UUID = "1fb20001-02c9-4001-bc9b-a2d1b18fab45"
SERVICE_TRIGGER_UUID = "70ea1476-7a29-4fdf-93d2-838665e72677"
CHAR_TRIGGER_UUID = "70ea0003-7a29-4fdf-93d2-838665e72677"
CHAR_NOTIFY_UUID = "70ea0004-7a29-4fdf-93d2-838665e72677"

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=60)
TIMEOUT_BLE_CONN = 30.0
TIMEOUT_GATT_OP = 10.0
TIMEOUT_NOTIFICATION_WAIT = 60.0
TIMEOUT_SAFETY_MARGIN = 30.0
POST_PAYLOAD_READ_COUNT = 5
# Worst case: one connection, up to 2 full auth+trigger+notification cycles,
# then the post-payload reads (raw_frame_0005, accelerometer, serial number,
# HW version, SW version), each individually bounded by TIMEOUT_GATT_OP.
TIMEOUT_FORCE_REFRESH = (
    TIMEOUT_BLE_CONN
    + 2 * (2 * TIMEOUT_GATT_OP + TIMEOUT_NOTIFICATION_WAIT)
    + POST_PAYLOAD_READ_COUNT * TIMEOUT_GATT_OP
    + TIMEOUT_SAFETY_MARGIN
)
DEBOUNCE_COOLDOWN = 0.3
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


def blue_connect_device_info(mac: str, model_name: str) -> DeviceInfo:
    mac_suffix = mac.replace(":", "")[-4:].upper() if mac else ""
    display_name = f"{model_name} ({mac_suffix})" if mac_suffix else model_name
    return DeviceInfo(
        identifiers={(DOMAIN, mac)},
        name=display_name,
        manufacturer="Zodiac",
        model=model_name,
    )
