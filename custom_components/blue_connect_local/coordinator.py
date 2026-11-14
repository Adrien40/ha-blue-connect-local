# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import asyncio
import logging
import math
from datetime import datetime, timedelta
from time import monotonic
from typing import Any, cast

import homeassistant.util.dt as dt_util
from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_last_service_info,
    async_register_callback,
    async_scanner_count,
    async_track_unavailable,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .chemistry import (
    compute_lsi,
    compute_orp_calibrated,
    compute_orp_raw_from_calibrated,
    compute_ph_calibrated,
    compute_ph_equilibrium,
    compute_ph_raw_from_mv,
    compute_ph_two_point,
    ph_calibration_quality,
)
from .const import (
    ACCEL_THRESHOLD,
    AUTH_SETTLE_DELAY,
    AUTH_STATUS_RETRY_DELAY,
    BLE_RECENTLY_SEEN_THRESHOLD_S,
    BT_STATUS_AUTH_FAILED,
    BT_STATUS_AUTHENTICATING,
    BT_STATUS_CONNECTING,
    BT_STATUS_ERROR,
    BT_STATUS_ERROR_RETRY,
    BT_STATUS_OUT_OF_RANGE,
    BT_STATUS_PAUSED,
    BT_STATUS_READING,
    BT_STATUS_REQUESTING,
    BT_STATUS_SUCCESS,
    BT_STATUS_WAITING,
    BT_STATUS_WRITE_FAILED,
    CHAR_AUTH_STATUS_UUID,
    CHAR_AUTH_UUID,
    CHAR_ESP32_FW_UUID,
    CHAR_FIRST_CONNECTION_UUID,
    CHAR_HW_VERSION_UUID,
    CHAR_LAST_ORP_CALIB_UUID,
    CHAR_LAST_PH_CALIB_UUID,
    CHAR_NOTIFY_UUID,
    CHAR_NRF_FW_UUID,
    CHAR_ORP_CALIB_MEAS_UUID,
    CHAR_ORP_CALIB_REF_UUID,
    CHAR_ORP_CALIB_STATUS_UUID,
    CHAR_PH_CALIB_POINT_1_MV_UUID,
    CHAR_PH_CALIB_POINT_1_PH_UUID,
    CHAR_PH_CALIB_POINT_2_MV_UUID,
    CHAR_PH_CALIB_POINT_2_PH_UUID,
    CHAR_PROBE_REPLACEMENT_UUID,
    CHAR_PROBE_SERIAL_UUID,
    CHAR_TRIGGER_UUID,
    CONF_ACCESS_CODE,
    CONF_CHLORINE_MODEL,
    CONF_CYA,
    CONF_IGNORE_ECHOES,
    CONF_ORP_CALIB,
    CONF_ORP_REF,
    CONF_PASSIVE_MEASURES,
    CONF_PH_CALIB_4,
    CONF_PH_CALIB_7,
    CONF_PH_HR_CALIB_MV_4,
    CONF_PH_HR_CALIB_MV_7,
    CONF_PH_HR_REF_4,
    CONF_PH_HR_REF_7,
    CONF_PH_REF_4,
    CONF_PH_REF_7,
    CONF_REFERENCE_TIME,
    CONF_SCAN_INTERVAL,
    CONF_TAC,
    CONF_TDS,
    CONF_TEMP_OFFSET,
    CONF_TH,
    DEBOUNCE_COOLDOWN,
    DEFAULT_PH_CALIB_4,
    DEFAULT_PH_CALIB_7,
    DEFAULT_PH_REF_4,
    DEFAULT_PH_REF_7,
    DEVICE_TYPE_BLUERIIOT,
    DOMAIN,
    ECHO_MARKER,
    ERROR_RETRY_DELAY,
    EXPECTED_FRAME_HEX_LEN_18,
    FIRST_ANALYSIS_DELAY,
    GATT_WRITE_RETRY_DELAY,
    ORP_CALIBRATION_MAX_OFFSET_MV,
    ORP_CALIBRATION_SOURCE_INTEGRATION,
    ORP_CALIBRATION_SOURCE_PROBE,
    PH_CALIBRATION_MAX_OFFSET_MV,
    PH_CALIBRATION_MAX_SLOPE_MV,
    PH_CALIBRATION_MIN_SLOPE_MV,
    PH_HR_CALIBRATION_SOURCE_INTEGRATION,
    PH_HR_CALIBRATION_SOURCE_PROBE,
    PH_SOURCE_HIGH_RESOLUTION,
    PH_SOURCE_STANDARD,
    REPAIR_STALE_AFTER,
    SAVE_DEBOUNCE_DELAY,
    TIMEOUT_BLE_CONN,
    TIMEOUT_GATT_OP,
    TIMEOUT_NOTIFICATION_WAIT,
    get_blue_connect_model,
    get_manufacturer,
    mac_short_id,
    model_has_conductivity,
)
from .profile_blueriiot import (
    BLUERIIOT_CHAR_AUTH_UUID,
    BLUERIIOT_CHAR_TRIGGER_UUID,
    blueriiot_extra_trigger_uuids,
    blueriiot_notify_uuids,
    describe_gatt_characteristics,
    is_blueriiot_services,
)
from .protocol import (
    extract_raw_payload,
    parse_electrical_frame,
    parse_electrical_orp,
    parse_orp_calibration,
    parse_ph_calibration,
    parse_raw_frame,
)
from .protocol_blueriiot import (
    FRAME_HEX_LEN as BLUERIIOT_FRAME_HEX_LEN,
    is_blueriiot_frame,
    parse_blueriiot_frame,
)

UUID_RAW_SENSORS = "70ea0005-7a29-4fdf-93d2-838665e72677"
UUID_ACCELEROMETER = "70ea000a-7a29-4fdf-93d2-838665e72677"
UUID_SERIAL_NUMBER = "70ea0020-7a29-4fdf-93d2-838665e72677"
UUID_HW_VERSION = "70ea0021-7a29-4fdf-93d2-838665e72677"
UUID_SW_VERSION = "70ea0022-7a29-4fdf-93d2-838665e72677"

_LOGGER = logging.getLogger(__name__)

# Repair issues raised for an abnormal calibration (see _sync_calibration_issues).
_CALIBRATION_ISSUE_KEYS = frozenset(
    {"orp_calibration", "ph_calibration_slope", "ph_calibration_offset"}
)

# Errors expected from BLE I/O (connect/disconnect/read/write/notify) across
# bleak backends: protocol errors, dropped/refused connections, and timeouts.
_BLE_IO_ERRORS = (BleakError, OSError, TimeoutError, EOFError)

# Keys in self.data that describe a specific BLE reading and are only
# trustworthy alongside a valid raw_frame. Everything else stored in
# self.data (preferences: active_measures, passive_measures, ignore_echoes,
# chlorine_model, cya, tac/th/tds, scan_interval, reference_time, access_code,
# and device identity: serial_number/sku/cloud_id) is independent
# of whether a BLE frame was ever successfully parsed and must always be
# restored when present.
_MEASUREMENT_ONLY_KEYS = frozenset(
    {
        "raw_frame",
        "raw_frame_0005",
        "temp_raw",
        "ph_raw",
        "ph_probe_calibrated",
        "orp_probe_calibrated",
        "orp_raw_mv",
        "orp_calibration_source",
        "probe_orp_calibration",
        "orp_calibration_source_ts",
        "conductivity",
        "salinity",
        "has_conductivity",
        "battery_percent",
        "battery_adc",
        "battery",
        "battery_level",
        "temperature",
        "ph",
        "ph_raw_mv",
        "ph_source",
        "ph_hr_calibration",
        "ph_hr_calibration_source",
        "ph_example_hr",
        "ph_example_low",
        "ph_calibration_source_ts",
        "probe_ph_calibration",
        "orp",
        "last_received",
        "accelerometer",
        "float_status",
        "target_equilibrium_ph",
        "lsi",
        "lsi_status",
        "receive_method",
    }
)


def store_key(mac: str) -> str:
    return f"{DOMAIN}_{mac.replace(':', '').lower()}"


def format_mac_safe(mac: str | None) -> str:
    if not mac or len(mac) < 17:
        return "XX:XX:XX:XX:XX:XX"
    return f"{mac[:8]}:XX:XX:XX"


def find_device(
    registry: dr.DeviceRegistry, identifier: tuple[str, str], config_entry_id: str
) -> dr.DeviceEntry | None:
    """Find a device by identifier, across all supported HA versions.

    `async_get_device` is deprecated (identifiers are no longer unique across
    entries) but its replacement does not exist yet on HA 2026.3.0.
    """
    finder = getattr(registry, "async_get_device_by_identifier", None)
    if finder is not None:
        # getattr() erases the type; this is the future replacement method
        # feature-detected above, its real signature matches when present.
        return cast("dr.DeviceEntry | None", finder(identifier, config_entry_id))
    return registry.async_get_device(identifiers={identifier})


async def _safely_disconnect(client: BleakClient | None) -> None:
    if client and client.is_connected:
        try:
            await asyncio.wait_for(client.disconnect(), timeout=TIMEOUT_GATT_OP)
        except _BLE_IO_ERRORS as err:
            _LOGGER.debug("Ignored error during disconnect: %s", err)


def _get_opt(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    if key in entry.options:
        return entry.options[key]
    if key in entry.data:
        return entry.data[key]
    return default


class BlueConnectCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        mac: str,
        safe_mac: str,
        access_code: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Blue Connect {safe_mac}",
            update_interval=timedelta(minutes=60),
        )
        self._entry_id = entry.entry_id
        self.mac = mac
        self.safe_mac = safe_mac
        self.store: Store[dict[str, Any]] = Store(hass, 1, store_key(mac))

        self.ble_lock = asyncio.Lock()
        self.retry_count = 0
        self._is_shutdown = False
        self.next_slot: datetime | None = None

        self._retry_cancel: CALLBACK_TYPE | None = None
        self._recalc_cancel: CALLBACK_TYPE | None = None
        self._save_cancel: asyncio.TimerHandle | None = None
        self._force_one_shot = False
        self._first_analysis_cancel: CALLBACK_TYPE | None = None

        self._passive_issue_active = False
        self._calibration_push_pending = False
        # Set after the pH calibration was written to the probe: its own
        # registers are then read once more, whatever else would skip it.
        self._ph_calibration_reread = False
        # Repair issues currently raised for an abnormal calibration.
        self._calibration_issues_active: set[str] = set()

        self._ble_available = True
        self._ble_unavail_cancel: CALLBACK_TYPE | None = None
        self._ble_avail_cancel: CALLBACK_TYPE | None = None

        # coordinator.data is always initialized as a dict and never set to None
        self.data: dict[str, Any] = {CONF_ACCESS_CODE: access_code}
        self.data.update(
            {
                "active_measures": True,
                "action_running": False,
                "bluetooth_status": "passive_mode"
                if not self.access_code
                else BT_STATUS_WAITING,
                "receive_method": "unknown",
            }
        )

        # Best-effort seed from the config flow's discovery-time snapshot
        # (only present when async_step_bluetooth saw the device in an
        # advertisement - not for manually-entered MACs). This lets
        # conductivity/salinity's enabled_default be correct on the very
        # first entity registration for the common auto-discovery case.
        # It's a guess, not authoritative: any real value later loaded
        # from storage or read from a live BLE frame overwrites it, and
        # _correct_stale_enabled_entities() remains the fallback for
        # whichever devices never got seeded here (manual MAC entry) or
        # whose seed turns out to be wrong.
        seeded_has_conductivity = entry.data.get("has_conductivity")
        if seeded_has_conductivity is not None:
            self.data["has_conductivity"] = seeded_has_conductivity
        # Same idea for the GATT profile: a Blueriiot probe discovered by its
        # B20* name is registered as Blue Connect Plus / Blueriiot right away,
        # before the first GATT connection confirms the profile.
        seeded_device_type = entry.data.get("device_type")
        if seeded_device_type is not None:
            self.data["device_type"] = seeded_device_type

        self.update_schedule()

    @property
    def entry_id(self) -> str:
        return self._entry_id

    @property
    def display_label(self) -> str:
        """Short label of the probe for messages shown to the user.

        The name the user gave the device, otherwise its model ("Blue Connect
        Gold"). When several Blue Connect are installed, the last 4 hex digits
        of the address are added so that they can be told apart. Not the
        masked address used in logs, which is the same for every probe of a
        maker.
        """
        device = find_device(
            dr.async_get(self.hass), (DOMAIN, self.mac), self._entry_id
        )
        label = (
            (device.name_by_user or device.model) if device is not None else None
        ) or "Blue Connect"
        if len(self.hass.config_entries.async_entries(DOMAIN)) > 1:
            label = f"{label} {mac_short_id(self.mac)}".strip()
        return label

    def _format_ph(self, value: float, decimals: int) -> str:
        """pH as written in the user's language (decimal comma or point)."""
        text = f"{value:.{decimals}f}"
        if self.hass.config.language.split("-")[0] in ("en", "zh", "ja", "ko"):
            return text
        return text.replace(".", ",")

    @property
    def entry(self) -> ConfigEntry | None:
        return self.hass.config_entries.async_get_entry(self._entry_id)

    @property
    def access_code(self) -> str:
        return str(self.data.get(CONF_ACCESS_CODE, "")).strip()

    @property
    def is_shutdown(self) -> bool:
        return self._is_shutdown

    @property
    def ble_available(self) -> bool:
        if async_scanner_count(self.hass, connectable=False) == 0:
            return False
        if not self._ble_available:
            return False
        last_info = async_last_service_info(self.hass, self.mac, connectable=False)
        if last_info:
            return (monotonic() - last_info.time) <= BLE_RECENTLY_SEEN_THRESHOLD_S
        return False

    def _update_device_registry(self) -> None:
        """Update device registry entry with hardware and serial metadata."""
        device_registry = dr.async_get(self.hass)
        device_entry = find_device(device_registry, (DOMAIN, self.mac), self.entry_id)
        if device_entry:
            sku = self.data.get("sku")
            model_name = get_blue_connect_model(
                sku, self.data.get("has_conductivity"), self.data.get("device_type")
            )
            device_registry.async_update_device(
                device_entry.id,
                manufacturer=get_manufacturer(model_name),
                model=model_name,
                model_id=sku,
                hw_version=self.data.get("hardware_version"),
                sw_version=self.data.get("firmware_version"),
                serial_number=self.data.get("serial_number"),
            )

        self._correct_stale_enabled_entities()

    def _correct_stale_enabled_entities(self) -> None:
        """One-shot correction for the conductivity/salinity entities.

        Home Assistant only honors `entity_registry_enabled_default` at
        first entity creation. On a fresh install, no BLE frame has been
        received yet when entities are created, so has_conductivity/sku
        are both None and the entities default to enabled (see
        model_has_conductivity). If the device later turns out to be a
        Silver (no conductivity sensor), those entities stay enabled
        forever unless corrected here. This runs once per resolution and
        never overrides an explicit choice the user made afterwards.
        """
        if self.data.get("_conductivity_default_corrected"):
            return

        sku = self.data.get("sku")
        has_conductivity = self.data.get("has_conductivity")
        if sku is None and has_conductivity is None:
            return  # Model still unknown - nothing to correct yet.

        if model_has_conductivity(sku, has_conductivity):
            # Gold (or genuinely unresolved) - the optimistic default was
            # correct, nothing to disable.
            self.data["_conductivity_default_corrected"] = True
            self._schedule_save()
            return

        registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(registry, self.entry_id)
        stale_unique_ids = (f"{self.mac}_conductivity", f"{self.mac}_salinity")
        for reg_entry in entries:
            if reg_entry.unique_id not in stale_unique_ids:
                continue
            if reg_entry.disabled_by is not None:
                continue  # User (or a previous run of this fix) already set it.
            registry.async_update_entity(
                reg_entry.entity_id,
                disabled_by=RegistryEntryDisabler.INTEGRATION,
            )
            _LOGGER.info(
                "Disabled %s: this Blue Connect has no conductivity sensor",
                reg_entry.entity_id,
            )

        self.data["_conductivity_default_corrected"] = True
        self._schedule_save()

    def update_schedule(self) -> None:
        if self._is_shutdown:
            return

        entry = self.entry
        if not entry:
            return

        if not self.access_code:
            if self.data.get("last_received"):
                self.update_interval = timedelta(minutes=60)
            self.next_slot = None
            return

        interval_m = self.data.get(CONF_SCAN_INTERVAL)
        if interval_m is None:
            interval_m = _get_opt(entry, CONF_SCAN_INTERVAL, 60)

        ref_time_str = self.data.get(CONF_REFERENCE_TIME)
        if ref_time_str is None:
            ref_time_str = _get_opt(entry, CONF_REFERENCE_TIME, "08:00")

        try:
            parts = ref_time_str.split(":")
            hour = int(parts[0]) if len(parts) > 0 else 0
            minute = int(parts[1]) if len(parts) > 1 else 0
        # PEP 758 (Python 3.14): parentheses are optional when there is no `as` clause. Intentional.
        except ValueError, AttributeError, IndexError:
            hour, minute = 0, 0

        now = dt_util.now()
        base_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        interval_s = interval_m * 60
        delta_seconds = (now - base_dt).total_seconds()

        n_slots = math.floor(delta_seconds / interval_s)
        last_slot = base_dt + timedelta(seconds=n_slots * interval_s)
        next_slot = last_slot + timedelta(seconds=interval_s)

        if (next_slot - now).total_seconds() < 10:
            next_slot += timedelta(seconds=interval_s)

        self.next_slot = next_slot
        self.update_interval = next_slot - now
        _LOGGER.debug(
            "Blue Connect %s: Next scheduled analysis aligned to %s",
            self.safe_mac,
            next_slot.strftime("%H:%M:%S"),
        )

    def request_one_shot_analysis(self) -> None:
        if self.access_code:
            self._force_one_shot = True

    def request_calibration_push(self) -> bool:
        """Ask the next analysis to write the integration's calibrations to the probe.

        Called by the options form when the person ticks the box, before the
        new options are saved: which calibration (pH, ORP, or both) there
        really is to write, and whether it changed since the last successful
        push, is checked again at the moment of the write. Returns False when there
        is no access code to authenticate with, or on a Blueriiot probe (which
        has no such registers). The request lives in memory only: it is never
        saved, so a restart cannot trigger a write.
        """
        if (
            not self.access_code
            or self.data.get("device_type") == DEVICE_TYPE_BLUERIIOT
        ):
            return False
        self._calibration_push_pending = True
        self.request_one_shot_analysis()
        return True

    def request_deferred_recompute(self) -> None:
        if self._recalc_cancel:
            self._recalc_cancel()
            self._recalc_cancel = None

        @callback
        def _do_recompute(_now: datetime) -> None:
            self._recalc_cancel = None
            if self.data:
                self.recompute_derived_values()

        self._recalc_cancel = async_call_later(
            self.hass, DEBOUNCE_COOLDOWN, _do_recompute
        )

    @callback
    def _on_ble_unavailable(self, _info: BluetoothServiceInfoBleak) -> None:
        # Logged once per transition (Home Assistant fires this callback only
        # when the probe goes from seen to unseen), as the log-when-unavailable
        # rule asks for.
        _LOGGER.info("Blue Connect %s: BLE signal lost", self.safe_mac)
        self._ble_available = False
        self._set_bt_status(BT_STATUS_OUT_OF_RANGE)
        if self._retry_cancel:
            self._retry_cancel()
            self._retry_cancel = None
        self.retry_count = 0

    @callback
    def _on_ble_seen(
        self, info: BluetoothServiceInfoBleak, _change: BluetoothChange
    ) -> None:
        previously_unavailable = not self._ble_available
        self._ble_available = True
        current_status = self.data.get("bluetooth_status")
        active = self.data.get("active_measures", True)

        if previously_unavailable:
            _LOGGER.info("Blue Connect %s: BLE signal found", self.safe_mac)

        if current_status == BT_STATUS_OUT_OF_RANGE and active:
            if not previously_unavailable:
                _LOGGER.debug(
                    "Blue Connect %s: recovering from stale out_of_range status",
                    self.safe_mac,
                )
            self._set_bt_status(
                "passive_mode" if not self.access_code else BT_STATUS_WAITING
            )

        if self.data.get("action_running"):
            return

        has_initial_data = self.data.get("ph") is not None

        if not self._passive_frames_enabled():
            return

        raw_payload = extract_raw_payload(info.manufacturer_data, info.service_data)

        if raw_payload:
            clean_payload = raw_payload[1:] if len(raw_payload) == 19 else raw_payload
            hex_frame = clean_payload.hex().upper()

            if hex_frame != self.data.get("raw_frame"):
                ignore_echoes = self.data.get(CONF_IGNORE_ECHOES)
                if ignore_echoes is None:
                    ignore_echoes = (
                        _get_opt(self.entry, CONF_IGNORE_ECHOES, True)
                        if self.entry
                        else True
                    )

                if (
                    ignore_echoes
                    and has_initial_data
                    and len(hex_frame) >= 4
                    and hex_frame[-4] == ECHO_MARKER
                ):
                    _LOGGER.debug(
                        "Blue Connect %s: Passive echo frame ignored (B marker): %s",
                        self.safe_mac,
                        hex_frame,
                    )
                    return

                _LOGGER.debug(
                    "Blue Connect %s: Passive broadcast frame intercepted: %s",
                    self.safe_mac,
                    hex_frame,
                )
                parsed = parse_raw_frame(raw_payload)
                if parsed:
                    self._clear_stale_issue()
                    new_state = self._apply_new_measurements(parsed, hex_frame)
                    new_state["receive_method"] = "passive"
                    self.update_local_state(new_state)
                    self._update_device_registry()

    async def async_initialize(self) -> None:
        saved_data = await self.store.async_load()

        if saved_data:
            # Pre-refactor storage used the "hw_version" key for what is
            # actually the commercial SKU. Migrate it once so existing
            # installs keep their already-detected model on upgrade.
            if "hw_version" in saved_data and "sku" not in saved_data:
                saved_data["sku"] = saved_data.pop("hw_version")

            # Before 1.4.0 "ph_raw" held the pH of the calculated frame. It
            # now is the pH read from the electrode potential, and the former
            # value lives in "ph_probe_calibrated".
            if "ph_probe_calibrated" not in saved_data and "ph_raw" in saved_data:
                saved_data["ph_probe_calibrated"] = saved_data.pop("ph_raw")

            # Same for the ORP: "orp_raw" always held the ORP of the calculated
            # frame (probe calibration applied). It is now "orp_probe_calibrated",
            # and "orp_raw_mv" holds the real electrode potential.
            if "orp_raw" in saved_data:
                saved_data.setdefault("orp_probe_calibrated", saved_data["orp_raw"])
                del saved_data["orp_raw"]

            rf = saved_data.get("raw_frame")
            raw_frame_valid = isinstance(rf, str) and len(rf) in (
                EXPECTED_FRAME_HEX_LEN_18,
                BLUERIIOT_FRAME_HEX_LEN,
            )

            if "raw_frame" in saved_data and not raw_frame_valid:
                _LOGGER.warning(
                    "Invalid raw_frame in storage for %s, discarding stored "
                    "measurements only (preferences are kept)",
                    self.safe_mac,
                )

            if raw_frame_valid:
                ts_val = saved_data.get("last_received")
                if isinstance(ts_val, str):
                    parsed = dt_util.parse_datetime(ts_val)
                    if parsed:
                        saved_data["last_received"] = parsed
                    else:
                        saved_data.pop("last_received", None)
            else:
                for key in _MEASUREMENT_ONLY_KEYS:
                    saved_data.pop(key, None)

            for transient in ("bluetooth_status", "action_running"):
                saved_data.pop(transient, None)

            # The access code lives in the config entry (data/options), which
            # is the source of truth. A copy restored from storage (written by
            # older versions) would override a code just fixed via reauth or
            # reconfigure.
            saved_data.pop(CONF_ACCESS_CODE, None)

            # Storage predates the sw_version -> cloud_id rename and has no
            # migration function of its own (Store(hass, 1, ...) below), so
            # normalize the legacy key here instead of bumping its version.
            if "sw_version" in saved_data:
                saved_data["cloud_id"] = saved_data.pop("sw_version")

            # Static values read once from GATT: drop empty stored values so
            # they are read again on the next cycle.
            for static_key in (
                "serial_number",
                "sku",
                "cloud_id",
                "hardware_version",
                "firmware_version",
                "probe_serial_number",
            ):
                if static_key in saved_data and not saved_data[static_key]:
                    saved_data.pop(static_key, None)

            # Dates are stored as ISO strings: parse them back, and drop
            # anything unreadable rather than showing a wrong date.
            for date_key in (
                "first_connection",
                "probe_replacement",
                "last_ph_calib",
                "last_orp_calib",
            ):
                if date_key in saved_data and isinstance(saved_data[date_key], str):
                    parsed_dt = dt_util.parse_datetime(saved_data[date_key])
                    if parsed_dt:
                        saved_data[date_key] = parsed_dt
                    else:
                        saved_data.pop(date_key, None)

            if saved_data:
                self.data.update(saved_data)
                self._update_device_registry()
            self.update_schedule()

        last_info = async_last_service_info(self.hass, self.mac, connectable=False)
        self._ble_available = (
            last_info is not None
            and (monotonic() - last_info.time) <= BLE_RECENTLY_SEEN_THRESHOLD_S
        )
        if not self._ble_available:
            self.data["bluetooth_status"] = BT_STATUS_OUT_OF_RANGE

        self._ble_unavail_cancel = async_track_unavailable(
            self.hass, self._on_ble_unavailable, self.mac, connectable=False
        )
        self._ble_avail_cancel = async_register_callback(
            self.hass,
            self._on_ble_seen,
            BluetoothCallbackMatcher(address=self.mac),
            BluetoothScanningMode.PASSIVE,
        )

        self._sync_passive_issue()
        self._sync_calibration_issues()

        if self.access_code:
            _LOGGER.debug(
                "Blue Connect %s: Starting, launching active analysis in background",
                self.safe_mac,
            )
            self.request_one_shot_analysis()

            async def _run_first_analysis() -> None:
                self.update_volatile_state({"action_running": True})
                try:
                    await self.async_request_refresh()
                finally:
                    self.update_volatile_state({"action_running": False})

            @callback
            def _trigger_first_analysis(_now: datetime) -> None:
                if not self._is_shutdown:
                    self.hass.async_create_task(_run_first_analysis())

            self._first_analysis_cancel = async_call_later(
                self.hass, FIRST_ANALYSIS_DELAY, _trigger_first_analysis
            )

    async def async_shutdown(self) -> None:
        """Idempotent shutdown: called by HA on unload AND by async_unload_entry."""
        self._is_shutdown = True
        # The parent cancels the scheduled refresh and the debouncer; without this
        # call, they would survive the entry unload.
        await super().async_shutdown()

        for attr in (
            "_ble_unavail_cancel",
            "_ble_avail_cancel",
            "_retry_cancel",
            "_recalc_cancel",
            "_first_analysis_cancel",
        ):
            cancel = getattr(self, attr)
            if cancel:
                setattr(self, attr, None)  # before the call: never cancelled twice
                cancel()
        if self._save_cancel:
            self._save_cancel.cancel()
            self._save_cancel = None
        await self.async_save_to_disk()

    async def async_save_to_disk(self) -> None:
        data_to_save = dict(self.data)
        # datetime values are not JSON serializable: store them as ISO strings.
        for key in (
            "last_received",
            "first_connection",
            "probe_replacement",
            "last_ph_calib",
            "last_orp_calib",
        ):
            val = data_to_save.get(key)
            if val is not None and hasattr(val, "isoformat"):
                data_to_save[key] = val.isoformat()
        for transient in ("bluetooth_status", "action_running"):
            data_to_save.pop(transient, None)
        # Never persist the secret outside the config entry.
        data_to_save.pop(CONF_ACCESS_CODE, None)
        await self.store.async_save(data_to_save)

    def _schedule_save(self) -> None:
        if self._is_shutdown:
            return
        if self._save_cancel:
            self._save_cancel.cancel()
        loop = asyncio.get_running_loop()

        def _schedule_save_callback() -> None:
            self._save_cancel = None
            self.hass.async_create_task(self.async_save_to_disk())

        self._save_cancel = loop.call_later(
            SAVE_DEBOUNCE_DELAY, _schedule_save_callback
        )

    def update_local_state(self, updates: dict[str, Any]) -> None:
        self.data.update(updates)
        self.update_schedule()
        self.async_set_updated_data(self.data)
        self._schedule_save()
        self._sync_passive_issue()

    def update_volatile_state(self, updates: dict[str, Any]) -> None:
        self.data.update(updates)
        self.update_schedule()
        self.async_set_updated_data(self.data)

    def _set_bt_status(self, status: str) -> None:
        self.update_volatile_state({"bluetooth_status": status})

    def _issue_id(self) -> str:
        return f"stale_{self._entry_id}"

    def _check_stale_issue(self) -> None:
        """Create a repair issue if unreachable for longer than REPAIR_STALE_AFTER."""
        last = self.data.get("last_received")
        if not last:
            return
        if last.tzinfo is None:
            last = dt_util.as_utc(last)
        age = dt_util.utcnow() - last
        if age < REPAIR_STALE_AFTER:
            return
        async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id(),
            is_fixable=False,
            is_persistent=False,
            severity=IssueSeverity.WARNING,
            translation_key="device_unreachable",
            translation_placeholders={
                "name": self.display_label,
                "days": str(age.days),
            },
        )

    def _clear_stale_issue(self) -> None:
        async_delete_issue(self.hass, DOMAIN, self._issue_id())

    async def _read_ph_calibration_timestamp(self, client: BleakClient) -> int | None:
        """Raw Unix timestamp of 70ea0029, used only to detect a new calibration.

        The "Last pH Calibration" sensor reads the same characteristic again
        later in this same analysis and turns it into the datetime shown;
        that second read is deliberately kept separate and untouched.
        """
        try:
            raw = await asyncio.wait_for(
                client.read_gatt_char(CHAR_LAST_PH_CALIB_UUID),
                timeout=TIMEOUT_GATT_OP,
            )
        except _BLE_IO_ERRORS as err:
            _LOGGER.debug("Failed to read the pH calibration timestamp: %s", err)
            return None
        return int.from_bytes(raw[:4], byteorder="big") if len(raw) >= 4 else None

    async def _write_ph_calibration_to_probe(
        self, client: BleakClient, calibration: dict[str, float]
    ) -> bool:
        """Write the integration's mV calibration into the probe's own registers.

        This makes the probe's own standard pH (and whatever the official app
        shows) use the same two-point calibration as this integration's
        high-resolution pH - the same operation the app itself does when the
        person calibrates with buffer solutions, just written by the
        integration instead. It also affects the probe's own onboard alert
        thresholds, which compare against its calibrated pH: push it only
        with calibration values the person trusts.
        """
        writes = (
            (CHAR_PH_CALIB_POINT_1_PH_UUID, round(calibration["ph_1"] * 10), False),
            (CHAR_PH_CALIB_POINT_2_PH_UUID, round(calibration["ph_2"] * 10), False),
            (CHAR_PH_CALIB_POINT_1_MV_UUID, round(calibration["mv_1"] * 10), True),
            (CHAR_PH_CALIB_POINT_2_MV_UUID, round(calibration["mv_2"] * 10), True),
        )
        for uuid, value, signed in writes:
            try:
                await asyncio.wait_for(
                    client.write_gatt_char(
                        uuid,
                        value.to_bytes(2, byteorder="big", signed=signed),
                        response=True,
                    ),
                    timeout=TIMEOUT_GATT_OP,
                )
            except _BLE_IO_ERRORS as err:
                _LOGGER.warning(
                    "Blue Connect %s: failed to push the pH calibration to the "
                    "probe (%s): %s",
                    self.safe_mac,
                    uuid,
                    err,
                )
                return False
        # The official app also stamps the calibration date (4-byte big-endian
        # Unix time, the format "Last pH Calibration" reads back). Best effort:
        # the calibration itself is already written if the probe refuses this.
        try:
            await asyncio.wait_for(
                client.write_gatt_char(
                    CHAR_LAST_PH_CALIB_UUID,
                    int(dt_util.utcnow().timestamp()).to_bytes(4, byteorder="big"),
                    response=True,
                ),
                timeout=TIMEOUT_GATT_OP,
            )
        except _BLE_IO_ERRORS as err:
            _LOGGER.warning(
                "Blue Connect %s: the pH calibration was written but its date "
                "could not be updated: %s",
                self.safe_mac,
                err,
            )
        _LOGGER.info(
            "Blue Connect %s: pushed the integration's pH calibration to the probe",
            self.safe_mac,
        )
        return True

    async def _read_ph_calibration(
        self, client: BleakClient
    ) -> dict[str, float] | None:
        """Read the pH calibration the probe keeps for its electrode."""
        values: list[bytes] = []
        for uuid in (
            CHAR_PH_CALIB_POINT_1_PH_UUID,
            CHAR_PH_CALIB_POINT_2_PH_UUID,
            CHAR_PH_CALIB_POINT_1_MV_UUID,
            CHAR_PH_CALIB_POINT_2_MV_UUID,
        ):
            try:
                values.append(
                    bytes(
                        await asyncio.wait_for(
                            client.read_gatt_char(uuid), timeout=TIMEOUT_GATT_OP
                        )
                    )
                )
            except _BLE_IO_ERRORS as err:
                _LOGGER.debug("Failed to read pH calibration (%s): %s", uuid, err)
                return None
        calibration = parse_ph_calibration(*values)
        if calibration is None:
            _LOGGER.debug(
                "Blue Connect %s: the pH calibration stored in the probe is "
                "unusable (registers: %s)",
                self.safe_mac,
                [value.hex() for value in values],
            )
        return calibration

    async def _write_orp_calibration_to_probe(
        self, client: BleakClient, calibration: dict[str, int]
    ) -> bool:
        """Write the integration's ORP calibration into the probe's own registers.

        The probe then applies the same ``ref - mes`` correction to its own ORP
        (and whatever the official app shows) as this integration does. Like
        the pH, it also changes what the probe's onboard alert thresholds
        compare against: push it only with values the person trusts.
        """
        writes = (
            (CHAR_ORP_CALIB_REF_UUID, calibration["ref"]),
            (CHAR_ORP_CALIB_MEAS_UUID, calibration["mes"]),
        )
        for uuid, value in writes:
            try:
                await asyncio.wait_for(
                    client.write_gatt_char(
                        uuid,
                        value.to_bytes(2, byteorder="big", signed=True),
                        response=True,
                    ),
                    timeout=TIMEOUT_GATT_OP,
                )
            except _BLE_IO_ERRORS as err:
                _LOGGER.warning(
                    "Blue Connect %s: failed to push the ORP calibration to the "
                    "probe (%s): %s",
                    self.safe_mac,
                    uuid,
                    err,
                )
                return False
        # The official app also stamps the calibration date. Best effort: the
        # calibration itself is already written if the probe (or an ESPHome
        # proxy that does not cache this far) refuses this.
        try:
            await asyncio.wait_for(
                client.write_gatt_char(
                    CHAR_LAST_ORP_CALIB_UUID,
                    int(dt_util.utcnow().timestamp()).to_bytes(4, byteorder="big"),
                    response=True,
                ),
                timeout=TIMEOUT_GATT_OP,
            )
        except _BLE_IO_ERRORS as err:
            _LOGGER.warning(
                "Blue Connect %s: the ORP calibration was written but its date "
                "could not be updated: %s",
                self.safe_mac,
                err,
            )
        _LOGGER.info(
            "Blue Connect %s: pushed the integration's ORP calibration to the probe",
            self.safe_mac,
        )
        return True

    async def _push_calibrations_to_probe(self, client: BleakClient) -> None:
        """Write what the options form holds, and only what changed, to the probe.

        The pH and the ORP are independent: each one is written only when it
        is filled in and differs from what was last pushed successfully (kept
        in storage), so ticking the box to send one never rewrites the other
        nor refreshes its calibration date. A failed write is not remembered,
        so it is tried again the next time the box is ticked.
        """
        ph_calibration = self._integration_ph_hr_calibration()
        if ph_calibration is not None:
            if ph_calibration == self.data.get("pushed_ph_calibration"):
                _LOGGER.debug(
                    "Blue Connect %s: the pH calibration is unchanged since the "
                    "last push, nothing to write",
                    self.safe_mac,
                )
            else:
                if await self._write_ph_calibration_to_probe(client, ph_calibration):
                    self.data["pushed_ph_calibration"] = dict(ph_calibration)
                    self._schedule_save()
                # A write invalidates the cached copy of the probe's own
                # calibration: it is read again during this analysis, even
                # when the diagnostic sensor that shows it is turned off.
                self.data.pop("ph_calibration_source_ts", None)
                self._ph_calibration_reread = True

        orp_calibration = self._integration_orp_calibration()
        if orp_calibration is not None:
            if orp_calibration == self.data.get("pushed_orp_calibration"):
                _LOGGER.debug(
                    "Blue Connect %s: the ORP calibration is unchanged since the "
                    "last push, nothing to write",
                    self.safe_mac,
                )
            else:
                if await self._write_orp_calibration_to_probe(client, orp_calibration):
                    self.data["pushed_orp_calibration"] = dict(orp_calibration)
                    self._schedule_save()
                self.data.pop("orp_calibration_source_ts", None)

    async def _read_orp_calibration_timestamp(self, client: BleakClient) -> int | None:
        """Date of the last ORP calibration (70ea0036), best effort.

        Also detects a new calibration, so that the two registers are re-read
        only then. Behind an ESPHome proxy that caches too few characteristics
        this one may be out of reach: that leaves the date unknown and the
        registers read on every analysis, without failing anything.
        """
        try:
            raw = await asyncio.wait_for(
                client.read_gatt_char(CHAR_LAST_ORP_CALIB_UUID),
                timeout=TIMEOUT_GATT_OP,
            )
        except _BLE_IO_ERRORS as err:
            _LOGGER.debug("Failed to read the last ORP calibration date: %s", err)
            return None
        if len(raw) < 4:
            return None
        timestamp = int.from_bytes(raw[:4], byteorder="big")
        if timestamp > 0:
            self.data["last_orp_calib"] = dt_util.utc_from_timestamp(timestamp)
        return timestamp

    async def _read_orp_calibration(
        self, client: BleakClient
    ) -> dict[str, int | None] | None:
        """Read the ORP calibration the probe keeps for its electrode."""
        values: list[bytes] = []
        for uuid in (CHAR_ORP_CALIB_REF_UUID, CHAR_ORP_CALIB_MEAS_UUID):
            try:
                values.append(
                    bytes(
                        await asyncio.wait_for(
                            client.read_gatt_char(uuid), timeout=TIMEOUT_GATT_OP
                        )
                    )
                )
            except _BLE_IO_ERRORS as err:
                _LOGGER.debug("Failed to read ORP calibration (%s): %s", uuid, err)
                return None
        parsed = parse_orp_calibration(*values)
        if parsed is None:
            _LOGGER.debug(
                "Blue Connect %s: the ORP calibration stored in the probe is "
                "unusable (registers: %s)",
                self.safe_mac,
                [value.hex() for value in values],
            )
            return None
        # The status code is only shown, never interpreted (its meaning is not
        # documented, and it did not follow the pH one in the logs we have).
        status: int | None = None
        try:
            status_raw = await asyncio.wait_for(
                client.read_gatt_char(CHAR_ORP_CALIB_STATUS_UUID),
                timeout=TIMEOUT_GATT_OP,
            )
            status = status_raw[0] if len(status_raw) >= 1 else None
        except _BLE_IO_ERRORS as err:
            _LOGGER.debug("Failed to read the ORP calibration status: %s", err)
        return {**parsed, "status": status}

    def _integration_orp_calibration(self) -> dict[str, int] | None:
        """The integration's own ORP calibration (reference, measured), in mV.

        None unless the person filled in both values (empty by default): when
        set, it takes priority over the calibration stored in the probe. The
        measured value is the raw electrode potential, as shown by the "Raw
        ORP (mV)" sensor with the probe in the reference solution.
        """
        entry = self.entry
        if not entry:
            return None
        ref = _get_opt(entry, CONF_ORP_REF, None)
        mes = _get_opt(entry, CONF_ORP_CALIB, None)
        if ref in (None, "") or mes in (None, ""):
            return None
        return {"ref": int(float(ref)), "mes": int(float(mes))}

    def _probe_calibration_sensor_enabled(self) -> bool:
        """Whether the "probe calibration" diagnostic sensor is turned on.

        It is disabled by default: the 4 registers are only read for it when
        the person enabled it, so nobody else pays for the extra reads.
        """
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{self.mac}_probe_ph_calibration"
        )
        if entity_id is None:
            return False
        entity = registry.async_get(entity_id)
        return entity is not None and entity.disabled_by is None

    def _passive_frames_enabled(self) -> bool:
        """Whether the frames the probe broadcasts on its own are used."""
        passive_enabled = self.data.get(CONF_PASSIVE_MEASURES)
        if passive_enabled is None:
            # self.entry can be None if the entry was removed from hass
            # while a callback was already scheduled; fall back to the
            # same default _get_opt() would have used.
            passive_enabled = (
                _get_opt(self.entry, CONF_PASSIVE_MEASURES, True)
                if self.entry
                else True
            )
        return bool(passive_enabled)

    def _passive_issue_id(self) -> str:
        return f"passive_hr_{self._entry_id}"

    def _sync_passive_issue(self) -> None:
        """Suggest ignoring the passive frames once high resolution works.

        A passive frame arrives shortly after each analysis and replaces the
        high-resolution pH (2 decimals) with the 0.1 one. The repair is
        offered when an access code is set, the passive frames are used and
        a high-resolution pH has already been obtained on this probe (the
        flag and the pH values of that analysis are kept in storage). It
        disappears as soon as one of these conditions no longer holds, and
        its example values are refreshed after each analysis.
        """
        if self._is_shutdown:
            return
        ph_hr = self.data.get("ph_example_hr")
        ph_low = self.data.get("ph_example_low")
        wanted = bool(
            self.access_code
            and self.data.get("ph_hr_available")
            and ph_hr is not None
            and ph_low is not None
            and self._passive_frames_enabled()
        )
        if not wanted:
            if self._passive_issue_active:
                self._passive_issue_active = False
                async_delete_issue(self.hass, DOMAIN, self._passive_issue_id())
            return
        assert ph_hr is not None and ph_low is not None  # implied by `wanted`
        self._passive_issue_active = True
        # Creating an existing issue only updates it: an issue the user chose
        # to ignore stays ignored.
        async_create_issue(
            self.hass,
            DOMAIN,
            self._passive_issue_id(),
            is_fixable=True,
            is_persistent=False,
            severity=IssueSeverity.WARNING,
            translation_key="passive_high_resolution",
            translation_placeholders={
                "name": self.display_label,
                "ph_hr": self._format_ph(ph_hr, 2),
                "ph_low": self._format_ph(ph_low, 1),
            },
            data={"entry_id": self._entry_id},
        )

    def _sync_calibration_issues(self) -> None:
        """Raise a repair when the calibration in use looks wrong.

        The calibration in use is the integration's own one when it is filled
        in, otherwise the one stored in the probe (as last read). Warns when
        the ORP gap between the reference and the measured value, or the pH
        electrode slope or offset at pH 7, is out of the usual range: a wrong
        buffer solution, a dirty electrode, or a probe at the end of its life.
        It never blocks anything - the person stays free to keep the
        calibration - and disappears as soon as the values look normal again.
        """
        if self._is_shutdown:
            return
        is_blueriiot = self.data.get("device_type") == DEVICE_TYPE_BLUERIIOT
        name = self.display_label
        wanted: dict[str, tuple[str, dict[str, str]]] = {}

        orp_calibration = self._integration_orp_calibration()
        if orp_calibration is None and not is_blueriiot:
            probe_orp = self.data.get("probe_orp_calibration")
            if probe_orp:
                orp_calibration = {"ref": probe_orp["ref"], "mes": probe_orp["mes"]}
        if orp_calibration is not None:
            gap = abs(orp_calibration["ref"] - orp_calibration["mes"])
            if gap > ORP_CALIBRATION_MAX_OFFSET_MV:
                wanted["orp_calibration"] = (
                    "orp_calibration_offset",
                    {"name": name, "source": "ORP", "ecart": str(gap)},
                )

        ph_calibration = self._integration_ph_hr_calibration()
        if ph_calibration is None and not is_blueriiot:
            ph_calibration = self.data.get("probe_ph_calibration")
        quality = ph_calibration_quality(ph_calibration) if ph_calibration else None
        if quality is not None:
            slope, offset = quality
            if not (
                PH_CALIBRATION_MIN_SLOPE_MV <= slope <= PH_CALIBRATION_MAX_SLOPE_MV
            ):
                wanted["ph_calibration_slope"] = (
                    "ph_calibration_slope",
                    {
                        "name": name,
                        "source": "pH",
                        "slope": f"{slope:.1f}",
                        "min": f"{PH_CALIBRATION_MIN_SLOPE_MV:g}",
                        "max": f"{PH_CALIBRATION_MAX_SLOPE_MV:g}",
                    },
                )
            if abs(offset) > PH_CALIBRATION_MAX_OFFSET_MV:
                wanted["ph_calibration_offset"] = (
                    "ph_calibration_offset",
                    {
                        "name": name,
                        "source": "pH",
                        "ecart": f"{offset:+.1f}",
                        "limit": f"{PH_CALIBRATION_MAX_OFFSET_MV:g}",
                    },
                )

        # Deleting an issue that does not exist is a no-op: all of them are
        # cleared, not only the ones this instance raised, so that none is left
        # behind by a previous instance of the coordinator (entry reload).
        for key in _CALIBRATION_ISSUE_KEYS - wanted.keys():
            async_delete_issue(self.hass, DOMAIN, f"{key}_{self._entry_id}")
        for key, (translation_key, placeholders) in wanted.items():
            if key not in self._calibration_issues_active:
                _LOGGER.warning(
                    "Blue Connect %s: abnormal %s calibration (%s)",
                    self.safe_mac,
                    placeholders["source"],
                    ", ".join(
                        f"{k}={v}"
                        for k, v in placeholders.items()
                        if k not in ("name", "source")
                    ),
                )
            # Creating an existing issue only updates it: one the person chose
            # to ignore stays ignored.
            async_create_issue(
                self.hass,
                DOMAIN,
                f"{key}_{self._entry_id}",
                is_fixable=False,
                is_persistent=False,
                severity=IssueSeverity.WARNING,
                translation_key=translation_key,
                translation_placeholders=placeholders,
            )
        self._calibration_issues_active = set(wanted)

    def _load_ph_calibration(
        self, entry: ConfigEntry
    ) -> tuple[float, float, float, float]:
        c4_meas = float(_get_opt(entry, CONF_PH_CALIB_4, DEFAULT_PH_CALIB_4))
        c7_meas = float(_get_opt(entry, CONF_PH_CALIB_7, DEFAULT_PH_CALIB_7))
        ref_7 = float(_get_opt(entry, CONF_PH_REF_7, DEFAULT_PH_REF_7))
        ref_4 = float(_get_opt(entry, CONF_PH_REF_4, DEFAULT_PH_REF_4))
        return c4_meas, c7_meas, ref_4, ref_7

    def _integration_ph_hr_calibration(self) -> dict[str, float] | None:
        """The integration's own mV calibration for the high-resolution pH.

        None unless the person filled in the two potentials (empty by default):
        when set, it takes priority over the calibration stored in the probe,
        the same way the official app's own calibration would. The two points
        are the electrode potential read in each buffer solution (from the
        "Raw pH (mV)" sensor) and the pH of that solution.
        """
        entry = self.entry
        if not entry:
            return None
        mv_4 = _get_opt(entry, CONF_PH_HR_CALIB_MV_4, None)
        mv_7 = _get_opt(entry, CONF_PH_HR_CALIB_MV_7, None)
        if mv_4 in (None, "") or mv_7 in (None, ""):
            return None
        return {
            "ph_1": float(_get_opt(entry, CONF_PH_HR_REF_4, DEFAULT_PH_REF_4)),
            "ph_2": float(_get_opt(entry, CONF_PH_HR_REF_7, DEFAULT_PH_REF_7)),
            "mv_1": float(mv_4),
            "mv_2": float(mv_7),
        }

    def _build_chemistry_updates(
        self,
        temp: float | None,
        ph: float | None,
        orp: float | None,
        tac: float,
        th: float,
        tds: float,
        cya: float,
        chlorine_model: str,
    ) -> dict[str, Any]:
        updates: dict[str, Any] = {}

        if temp is not None and tac > 0 and th > 0:
            updates["target_equilibrium_ph"] = compute_ph_equilibrium(
                temp, tac, th, tds
            )
        else:
            updates["target_equilibrium_ph"] = None

        if temp is not None and ph is not None and tac > 0 and th > 0:
            lsi_val = compute_lsi(temp, ph, tac, th, tds)
            updates["lsi"] = lsi_val
            if lsi_val is not None:
                if lsi_val < -0.3:
                    updates["lsi_status"] = "corrosive"
                elif lsi_val > 0.3:
                    updates["lsi_status"] = "scaling"
                else:
                    updates["lsi_status"] = "balanced"
            else:
                updates["lsi_status"] = "unknown"
        else:
            updates["lsi"] = None
            updates["lsi_status"] = "unknown"

        return updates

    def _apply_new_measurements(
        self,
        parsed_data: dict[str, Any],
        hex_frame: str,
        ph_mv: float | None = None,
        ph_calibration: dict[str, float] | None = None,
        ph_calibration_source: str | None = None,
        orp_mv: float | None = None,
    ) -> dict[str, Any]:
        """Turn the decoded frame into the values shown by the sensors.

        ``ph_mv`` is the pH electrode potential read in the electrical frame
        of the same measurement, ``ph_calibration`` the two-point calibration
        to convert it (either the integration's own, or the one stored in the
        probe - ``ph_calibration_source`` says which). When both are given,
        the pH is that formula's result without any rounding (2 decimals);
        the integration's standard pH calibration (options) is never applied
        to it. Otherwise the pH is that of the calculated frame (0.1
        resolution), with the standard calibration applied as before.

        ``orp_mv`` is the ORP electrode potential read in the electrical frame
        of the same measurement. The ORP is that raw potential plus the
        ``ref - mes`` correction of the integration's own calibration when
        there is one, otherwise the ORP of the calculated frame, which already
        carries the probe's own correction. A frame the probe broadcast on its
        own has no electrical frame: the raw potential is then recovered by
        removing the probe's correction (read earlier) from that ORP, so the
        value does not change with the way the frame arrived.
        """
        current_entry = self.entry
        if not current_entry:
            return self.data

        now = dt_util.utcnow()
        raw_temp = parsed_data["temp_raw"]
        raw_ph = parsed_data["ph_raw"]
        raw_orp = parsed_data["orp_raw"]

        temp_offset = float(_get_opt(current_entry, CONF_TEMP_OFFSET, 0.0))
        temp = raw_temp + temp_offset

        # ORP. A Blueriiot probe has no calibration of its own: its frame is
        # already the raw electrode potential.
        is_blueriiot = self.data.get("device_type") == DEVICE_TYPE_BLUERIIOT
        probe_orp_calibration = (
            None if is_blueriiot else self.data.get("probe_orp_calibration")
        )
        orp_electrode: float | None
        if is_blueriiot:
            orp_electrode = float(raw_orp)
        elif orp_mv is not None:
            orp_electrode = float(orp_mv)
        elif probe_orp_calibration:
            orp_electrode = compute_orp_raw_from_calibrated(
                raw_orp, probe_orp_calibration["ref"], probe_orp_calibration["mes"]
            )
        else:
            orp_electrode = None
        orp_calibration_source: str | None = None
        orp: float = raw_orp
        integration_orp_calibration = self._integration_orp_calibration()
        if integration_orp_calibration is not None and orp_electrode is not None:
            orp = compute_orp_calibrated(
                orp_electrode,
                integration_orp_calibration["ref"],
                integration_orp_calibration["mes"],
            )
            orp_calibration_source = ORP_CALIBRATION_SOURCE_INTEGRATION
        elif probe_orp_calibration:
            orp_calibration_source = ORP_CALIBRATION_SOURCE_PROBE

        # The electrode potential as read, before any calibration: it also
        # gives the "Raw pH", whichever pH ends up being displayed.
        ph_raw_from_mv = compute_ph_raw_from_mv(ph_mv)

        ph_source = PH_SOURCE_STANDARD
        ph_calculated: float | None
        if ph_mv is not None and ph_calibration is not None:
            assert ph_calibration_source is not None
            try:
                ph_calculated = compute_ph_two_point(ph_mv, ph_calibration)
            except ValueError:
                ph_calculated = None
                _LOGGER.warning(
                    "The pH calibration (%s) of %s is unusable (the two points "
                    "coincide) - using the standard pH",
                    ph_calibration_source,
                    self.safe_mac,
                )
            else:
                if 0.0 <= ph_calculated <= 14.0:
                    ph_source = PH_SOURCE_HIGH_RESOLUTION
                else:
                    _LOGGER.warning(
                        "High-resolution pH %.2f for %s is out of the physical "
                        "range - using the standard pH",
                        ph_calculated,
                        self.safe_mac,
                    )

        if ph_source == PH_SOURCE_STANDARD:
            ph_calibration = None
            ph_calibration_source = None
            c4_meas, c7_meas, ref_4, ref_7 = self._load_ph_calibration(current_entry)
            try:
                ph_calculated = compute_ph_calibrated(
                    raw_ph, c4_meas, c7_meas, ref_4, ref_7
                )
            except ValueError:
                _LOGGER.warning(
                    "Degenerate pH calibration for %s - falling back to raw pH",
                    self.safe_mac,
                )
                ph_calculated = float(raw_ph)
        # Both branches above always set a float (never None) - the range
        # check right below is the first thing allowed to set it back to
        # None. Make that visible to mypy.
        assert ph_calculated is not None
        if not 0.0 <= ph_calculated <= 14.0:
            # A pH outside 0-14 is physically impossible (faulty probe or
            # calibration): better "unknown" than a wrong value displayed.
            _LOGGER.warning(
                "Computed pH %.2f for %s is out of the physical range - ignored",
                ph_calculated,
                self.safe_mac,
            )
            ph_calculated = None

        tac_val = self.data.get(CONF_TAC) or 0
        th_val = self.data.get(CONF_TH) or 0
        tds_val = self.data.get(CONF_TDS) or 0

        cya_raw = self.data.get(CONF_CYA)
        cya_val = float(cya_raw) if cya_raw is not None else 40.0

        chlorine_model = self.data.get(CONF_CHLORINE_MODEL)
        if chlorine_model is None:
            chlorine_model = _get_opt(current_entry, CONF_CHLORINE_MODEL, "chlorine")

        bat_pct = parsed_data.get("battery_percent", 0)

        new_data: dict[str, Any] = {
            **self.data,
            **parsed_data,
            # parsed_data["ph_raw"] is the calculated frame's pH (probe
            # calibration, 0.1): it is stored as "ph_probe_calibrated".
            "ph_raw": ph_raw_from_mv,
            "ph_probe_calibrated": raw_ph,
            # Likewise "orp_raw" (the calculated frame's ORP) is stored as
            # "orp_probe_calibrated"; "orp_raw_mv" is the electrode potential.
            "orp_probe_calibrated": raw_orp,
            "orp_raw_mv": (
                None if is_blueriiot or orp_electrode is None else round(orp_electrode)
            ),
            "orp_calibration_source": orp_calibration_source,
            "temperature": round(temp, 2),
            "ph": None if ph_calculated is None else round(ph_calculated, 2),
            "ph_raw_mv": ph_mv,
            "ph_hr_calibration": ph_calibration,
            "ph_hr_calibration_source": ph_calibration_source,
            "ph_source": ph_source,
            "orp": round(orp),
            "battery_level": bat_pct,
            "last_received": now,
            "raw_frame": hex_frame,
            "bluetooth_status": BT_STATUS_SUCCESS,
        }
        # parsed_data["orp_raw"] only carries the frame's ORP into this method.
        new_data.pop("orp_raw", None)
        if ph_source == PH_SOURCE_HIGH_RESOLUTION and ph_calculated is not None:
            # Real values shown in the "keep the 2-decimal pH" repair.
            new_data["ph_example_hr"] = round(ph_calculated, 2)
            new_data["ph_example_low"] = raw_ph

        new_data.update(
            self._build_chemistry_updates(
                round(temp, 2),
                None if ph_calculated is None else round(ph_calculated, 2),
                round(orp),
                tac_val,
                th_val,
                tds_val,
                cya_val,
                chlorine_model,
            )
        )
        return new_data

    def recompute_derived_values(self) -> None:
        if not self.data:
            return

        current_entry = self.entry
        if not current_entry:
            return

        raw_temp = self.data.get("temp_raw")
        raw_ph = self.data.get("ph_probe_calibrated")
        raw_orp = self.data.get("orp_probe_calibrated")
        hex_frame = self.data.get("raw_frame", "")

        if raw_temp is not None and raw_ph is not None and raw_orp is not None:
            parsed_data = {
                "temp_raw": raw_temp,
                "ph_raw": raw_ph,
                "orp_raw": raw_orp,
                "battery_percent": self.data.get("battery_percent", 0),
            }

            ph_mv = self.data.get("ph_raw_mv")
            ph_calibration: dict[str, float] | None = None
            ph_calibration_source: str | None = None
            if ph_mv is not None:
                integration_calibration = self._integration_ph_hr_calibration()
                if integration_calibration is not None:
                    ph_calibration = integration_calibration
                    ph_calibration_source = PH_HR_CALIBRATION_SOURCE_INTEGRATION
                elif self.data.get("probe_ph_calibration") is not None:
                    ph_calibration = self.data.get("probe_ph_calibration")
                    ph_calibration_source = PH_HR_CALIBRATION_SOURCE_PROBE
                elif (
                    self.data.get("ph_hr_calibration_source")
                    == PH_HR_CALIBRATION_SOURCE_PROBE
                ):
                    ph_calibration = self.data.get("ph_hr_calibration")
                    ph_calibration_source = PH_HR_CALIBRATION_SOURCE_PROBE
            updates = self._apply_new_measurements(
                parsed_data,
                hex_frame,
                ph_mv=ph_mv,
                ph_calibration=ph_calibration,
                ph_calibration_source=ph_calibration_source,
                orp_mv=self.data.get("orp_raw_mv"),
            )

            updates["last_received"] = self.data.get("last_received")
            updates["bluetooth_status"] = self.data.get("bluetooth_status")

            changed_updates = {
                k: v
                for k, v in updates.items()
                if k not in self.data or self.data[k] != v
            }
            if changed_updates:
                self.update_volatile_state(changed_updates)

        self._sync_calibration_issues()

    async def _async_update_data(self) -> dict[str, Any]:
        self.update_volatile_state({"action_running": True})
        try:
            if self._is_shutdown:
                return self.data

            if not self.access_code:
                self._set_bt_status("passive_mode")
                self.retry_count = 0
                self.update_schedule()
                return self.data

            force_one_shot = self._force_one_shot
            self._force_one_shot = False

            if not self.data.get("active_measures", True):
                if force_one_shot:
                    _LOGGER.debug("Force one-shot analysis requested")
                else:
                    self._set_bt_status(BT_STATUS_PAUSED)
                    self.retry_count = 0
                    self.update_schedule()
                    return self.data

            if not self.ble_available and not force_one_shot:
                _LOGGER.debug(
                    "Blue Connect %s: Bluetooth signal unavailable, connection ignored",
                    self.safe_mac,
                )
                self._set_bt_status(BT_STATUS_OUT_OF_RANGE)
                self.retry_count = 0
                self.update_schedule()
                self._check_stale_issue()
                if self.data.get("ph_probe_calibrated") is not None:
                    return self.data
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="out_of_range_no_history",
                    translation_placeholders={"name": self.display_label},
                )

            device = async_ble_device_from_address(
                self.hass, self.mac, connectable=True
            )
            if not device:
                device = async_ble_device_from_address(
                    self.hass, self.mac, connectable=False
                )
            if not device:
                return self._handle_ble_error(
                    f"Blue Connect {self.safe_mac}: device not found "
                    "in Bluetooth cache",
                    BT_STATUS_OUT_OF_RANGE,
                )

            client: BleakClient | None = None
            started_notify_uuids: list[str] = []
            received_payload: bytes | None = None
            # Zodiac GATT profile by default; switched to Blueriiot below only
            # when the connected device exposes the Blueriiot characteristics.
            is_blueriiot = False
            auth_uuid = CHAR_AUTH_UUID
            trigger_uuid = CHAR_TRIGGER_UUID
            notify_uuids = [CHAR_NOTIFY_UUID]
            extra_trigger_uuids: list[str] = []
            # Electrical frame read during THIS analysis only: a value kept
            # from an earlier analysis (read failed this time) must never be
            # used for the new measurement.
            electrical_mv: float | None = None
            electrical_orp: int | None = None
            ph_calibration: dict[str, float] | None = None
            ph_calibration_source: str | None = None
            loop = asyncio.get_running_loop()

            async with self.ble_lock:
                try:
                    self._set_bt_status(BT_STATUS_CONNECTING)

                    client = await asyncio.wait_for(
                        establish_connection(
                            BleakClient,
                            device,
                            self.mac,
                            max_attempts=3,
                            use_services_cache=True,
                        ),
                        timeout=TIMEOUT_BLE_CONN,
                    )

                    # bleak raises when service discovery is not available (and
                    # for an empty collection): detecting the profile must never
                    # break a ZODIAC cycle, which never needed the services.
                    # Deliberately broad (not _BLE_IO_ERRORS): this is a
                    # best-effort detection added on top of the original
                    # ZODIAC sequence, which never needed `services`. Any
                    # failure here, whatever the backend raises, must fall
                    # back to ZODIAC, not fail the cycle.
                    try:
                        services = client.services
                    except Exception as services_err:
                        _LOGGER.debug(
                            "Blue Connect %s: GATT services unreadable (%s), "
                            "assuming the ZODIAC profile",
                            self.safe_mac,
                            services_err,
                        )
                        services = None
                    # Full GATT table as received (through a Bluetooth proxy
                    # it can be shorter than what the probe really exposes).
                    gatt_table = describe_gatt_characteristics(services)
                    if gatt_table:
                        _LOGGER.debug(
                            "Blue Connect %s: GATT table (%d characteristics): %s",
                            self.safe_mac,
                            len(gatt_table),
                            "; ".join(gatt_table),
                        )
                    is_blueriiot = is_blueriiot_services(services)
                    if is_blueriiot:
                        _LOGGER.debug(
                            "Blue Connect %s: Blueriiot GATT profile detected",
                            self.safe_mac,
                        )
                        auth_uuid = BLUERIIOT_CHAR_AUTH_UUID
                        trigger_uuid = BLUERIIOT_CHAR_TRIGGER_UUID
                        notify_uuids = blueriiot_notify_uuids(services)
                        extra_trigger_uuids = blueriiot_extra_trigger_uuids(services)

                    received_data_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4)

                    def _put(data: bytes) -> None:
                        try:
                            received_data_queue.put_nowait(data)
                        except asyncio.QueueFull:
                            _LOGGER.debug(
                                "Notification queue full for %s, dropping frame",
                                self.safe_mac,
                            )

                    def notification_handler(
                        _sender: BleakGATTCharacteristic, data: bytearray
                    ) -> None:
                        # Blueriiot probes notify on several characteristics:
                        # only a measurement frame must reach the queue.
                        if is_blueriiot and not is_blueriiot_frame(data):
                            _LOGGER.debug(
                                "Blue Connect %s: ignoring Blueriiot notification "
                                "(len=%d)",
                                self.safe_mac,
                                len(data),
                            )
                            return
                        loop.call_soon_threadsafe(_put, bytes(data))

                    for notify_uuid in notify_uuids:
                        try:
                            await asyncio.wait_for(
                                client.start_notify(notify_uuid, notification_handler),
                                timeout=TIMEOUT_GATT_OP,
                            )
                        except _BLE_IO_ERRORS as notify_err:
                            if not is_blueriiot:
                                raise
                            _LOGGER.debug(
                                "Blue Connect %s: cannot subscribe to %s: %s",
                                self.safe_mac,
                                notify_uuid,
                                notify_err,
                            )
                            continue
                        started_notify_uuids.append(notify_uuid)
                    if not started_notify_uuids:
                        raise BleakError("No usable Blueriiot notification")

                    for attempt in range(1, 3):
                        while not received_data_queue.empty():
                            received_data_queue.get_nowait()

                        self._set_bt_status(BT_STATUS_AUTHENTICATING)
                        try:
                            await asyncio.wait_for(
                                client.write_gatt_char(
                                    auth_uuid,
                                    self.access_code.encode("ascii"),
                                    response=True,
                                ),
                                timeout=TIMEOUT_GATT_OP,
                            )
                            await asyncio.sleep(AUTH_SETTLE_DELAY)

                            # The auth status characteristic only exists on the
                            # Zodiac profile: skip it on Blueriiot probes.
                            auth_status = None
                            if not is_blueriiot:
                                try:
                                    auth_status = await asyncio.wait_for(
                                        client.read_gatt_char(CHAR_AUTH_STATUS_UUID),
                                        timeout=TIMEOUT_GATT_OP,
                                    )
                                    # Some BLE proxies or slower firmwares might
                                    # need an extra moment to flip the byte.
                                    if auth_status and auth_status[0] == 0x00:
                                        await asyncio.sleep(AUTH_STATUS_RETRY_DELAY)
                                        auth_status = await asyncio.wait_for(
                                            client.read_gatt_char(
                                                CHAR_AUTH_STATUS_UUID
                                            ),
                                            timeout=TIMEOUT_GATT_OP,
                                        )
                                except _BLE_IO_ERRORS as status_err:
                                    # Some firmware/backends may not expose this
                                    # characteristic reliably. Fall back to the
                                    # old behavior (wait for the measurement
                                    # notification) rather than failing the
                                    # whole update over it.
                                    _LOGGER.debug(
                                        "Failed to read auth status (1fb20002): %s",
                                        status_err,
                                    )
                                    auth_status = None

                            if auth_status and auth_status[0] == 0x00:
                                _LOGGER.warning(
                                    "Blue Connect rejected the access code for %s",
                                    self.safe_mac,
                                )
                                current_entry = self.entry
                                if current_entry:
                                    current_entry.async_start_reauth(self.hass)
                                return self._handle_ble_error(
                                    "Invalid access code", BT_STATUS_AUTH_FAILED
                                )

                            if not is_blueriiot and self._calibration_push_pending:
                                self._calibration_push_pending = False
                                await self._push_calibrations_to_probe(client)

                            self._set_bt_status(BT_STATUS_REQUESTING)
                            await asyncio.wait_for(
                                client.write_gatt_char(
                                    trigger_uuid, bytearray([0x02]), response=True
                                ),
                                timeout=TIMEOUT_GATT_OP,
                            )
                            for extra_uuid in extra_trigger_uuids:
                                try:
                                    await asyncio.wait_for(
                                        client.write_gatt_char(
                                            extra_uuid, bytearray([0x02]), response=True
                                        ),
                                        timeout=TIMEOUT_GATT_OP,
                                    )
                                except _BLE_IO_ERRORS as extra_err:
                                    _LOGGER.debug(
                                        "Blue Connect %s: extra trigger %s failed: %s",
                                        self.safe_mac,
                                        extra_uuid,
                                        extra_err,
                                    )
                        except _BLE_IO_ERRORS as write_err:
                            _LOGGER.warning(
                                "GATT write failed on attempt %d: %s",
                                attempt,
                                write_err,
                            )
                            if attempt == 2:
                                return self._handle_ble_error(
                                    f"Write failed: {write_err}", BT_STATUS_WRITE_FAILED
                                )
                            await asyncio.sleep(GATT_WRITE_RETRY_DELAY)
                            continue

                        self._set_bt_status(BT_STATUS_READING)
                        try:
                            received_payload = await asyncio.wait_for(
                                received_data_queue.get(),
                                timeout=TIMEOUT_NOTIFICATION_WAIT,
                            )
                            if received_payload:
                                break
                        except TimeoutError:
                            _LOGGER.warning(
                                "Timeout waiting for notification on attempt %d",
                                attempt,
                            )

                    if not received_payload:
                        return self._handle_ble_error(
                            "No valid data received from Blue Connect.", BT_STATUS_ERROR
                        )

                    self._clear_stale_issue()

                    # These reads target Zodiac-only characteristics: on a
                    # Blueriiot probe they just fail and add noise.
                    if not is_blueriiot:
                        try:
                            raw_0005 = await asyncio.wait_for(
                                client.read_gatt_char(UUID_RAW_SENSORS),
                                timeout=TIMEOUT_GATT_OP,
                            )
                            self.data["raw_frame_0005"] = raw_0005.hex().upper()
                            electrical_mv = parse_electrical_frame(bytes(raw_0005))
                            electrical_orp = parse_electrical_orp(bytes(raw_0005))
                        except _BLE_IO_ERRORS as err:
                            _LOGGER.debug(
                                "Failed to read raw sensors frame (0x0005): %s", err
                            )

                        # The calibration stored in the probe is read when it
                        # converts the potential of the electrical frame (unless
                        # the integration's own calibration takes priority), or
                        # when the "probe calibration" diagnostic sensor is
                        # turned on, or once after the pH calibration was
                        # written to the probe.
                        integration_calibration = self._integration_ph_hr_calibration()
                        probe_calibration: dict[str, float] | None = None
                        if (
                            (
                                electrical_mv is not None
                                and integration_calibration is None
                            )
                            or self._probe_calibration_sensor_enabled()
                            or self._ph_calibration_reread
                        ):
                            self._ph_calibration_reread = False
                            # The 4 registers practically never change between
                            # two calibrations, so they are re-read only when
                            # the calibration timestamp has: this saves 4 GATT
                            # round trips (connection time, probe radio time)
                            # on every other analysis.
                            calib_ts = await self._read_ph_calibration_timestamp(client)
                            cached_calibration = self.data.get("probe_ph_calibration")
                            if (
                                calib_ts is not None
                                and cached_calibration is not None
                                and calib_ts
                                == self.data.get("ph_calibration_source_ts")
                            ):
                                probe_calibration = cached_calibration
                            else:
                                probe_calibration = await self._read_ph_calibration(
                                    client
                                )
                                if (
                                    probe_calibration is not None
                                    and calib_ts is not None
                                ):
                                    self.data["ph_calibration_source_ts"] = calib_ts
                            self.data["probe_ph_calibration"] = probe_calibration
                        if electrical_mv is not None:
                            if integration_calibration is not None:
                                # The integration's own mV calibration takes
                                # priority for the high-resolution pH.
                                ph_calibration = integration_calibration
                                ph_calibration_source = (
                                    PH_HR_CALIBRATION_SOURCE_INTEGRATION
                                )
                            else:
                                ph_calibration = probe_calibration
                                ph_calibration_source = PH_HR_CALIBRATION_SOURCE_PROBE

                        # The ORP calibration stored in the probe, read on every
                        # analysis (a passive frame can only be turned back into
                        # the raw electrode potential with it, and the repair
                        # for an abnormal calibration needs it). Like the pH
                        # one, its two registers are re-read only when the
                        # calibration date has changed.
                        orp_calib_ts = await self._read_orp_calibration_timestamp(
                            client
                        )
                        if (
                            orp_calib_ts is not None
                            and self.data.get("probe_orp_calibration") is not None
                            and orp_calib_ts
                            == self.data.get("orp_calibration_source_ts")
                        ):
                            pass
                        else:
                            self.data[
                                "probe_orp_calibration"
                            ] = await self._read_orp_calibration(client)
                            if (
                                self.data["probe_orp_calibration"] is not None
                                and orp_calib_ts is not None
                            ):
                                self.data["orp_calibration_source_ts"] = orp_calib_ts

                        try:
                            raw_accel = await asyncio.wait_for(
                                client.read_gatt_char(UUID_ACCELEROMETER),
                                timeout=TIMEOUT_GATT_OP,
                            )
                            if len(raw_accel) >= 6:
                                x = int.from_bytes(
                                    raw_accel[0:2], byteorder="big", signed=True
                                )
                                y = int.from_bytes(
                                    raw_accel[2:4], byteorder="big", signed=True
                                )
                                z = int.from_bytes(
                                    raw_accel[4:6], byteorder="big", signed=True
                                )

                                self.data["accelerometer"] = f"X: {x} | Y: {y} | Z: {z}"

                                if y > ACCEL_THRESHOLD:
                                    self.data["float_status"] = "vertical"
                                elif y < -ACCEL_THRESHOLD:
                                    self.data["float_status"] = "upside_down"
                                elif (
                                    abs(x) > ACCEL_THRESHOLD or abs(z) > ACCEL_THRESHOLD
                                ):
                                    self.data["float_status"] = "horizontal"
                                else:
                                    self.data["float_status"] = "tilted"
                        except _BLE_IO_ERRORS as err:
                            _LOGGER.debug("Failed to read accelerometer data: %s", err)

                        if not self.data.get("serial_number"):
                            try:
                                sn = await asyncio.wait_for(
                                    client.read_gatt_char(UUID_SERIAL_NUMBER),
                                    timeout=TIMEOUT_GATT_OP,
                                )
                                val = sn.decode("ascii").replace("\x00", "").strip()
                                if val:
                                    self.data["serial_number"] = val
                            except (*_BLE_IO_ERRORS, UnicodeDecodeError) as err:
                                _LOGGER.debug("Failed to read serial number: %s", err)

                        if not self.data.get("sku"):
                            try:
                                # UUID_HW_VERSION is the GATT characteristic's own
                                # name (Bluetooth SIG naming), but the value it
                                # returns is actually the commercial SKU.
                                hw = await asyncio.wait_for(
                                    client.read_gatt_char(UUID_HW_VERSION),
                                    timeout=TIMEOUT_GATT_OP,
                                )
                                val = hw.decode("ascii").replace("\x00", "").strip()
                                if val:
                                    self.data["sku"] = val
                            except (*_BLE_IO_ERRORS, UnicodeDecodeError) as err:
                                _LOGGER.debug("Failed to read SKU: %s", err)

                        if not self.data.get("cloud_id"):
                            try:
                                # UUID_SW_VERSION is the GATT characteristic's own
                                # name, but the value it returns is the device's
                                # Cloud ID, not a firmware version.
                                sw = await asyncio.wait_for(
                                    client.read_gatt_char(UUID_SW_VERSION),
                                    timeout=TIMEOUT_GATT_OP,
                                )
                                val = sw.decode("ascii").replace("\x00", "").strip()
                                if val:
                                    self.data["cloud_id"] = val
                            except (*_BLE_IO_ERRORS, UnicodeDecodeError) as err:
                                _LOGGER.debug("Failed to read Cloud ID: %s", err)

                        # Diagnostic characteristics (hardware revision, firmware versions,
                        # dates, probe serial number). Each read is best-effort: a failure only
                        # leaves the matching sensor unknown and never fails the cycle. The
                        # static values are read once and then kept (like the serial number,
                        # SKU and Cloud ID); only the two dates that can change are read on
                        # every analysis.
                        if not self.data.get("hardware_version"):
                            try:
                                hw_ver_raw = await asyncio.wait_for(
                                    client.read_gatt_char(CHAR_HW_VERSION_UUID),
                                    timeout=TIMEOUT_GATT_OP,
                                )
                                if len(hw_ver_raw) >= 4:
                                    self.data["hardware_version"] = (
                                        f"{hw_ver_raw[2]}.{hw_ver_raw[1]}.{hw_ver_raw[0]}"
                                    )
                            except _BLE_IO_ERRORS as err:
                                _LOGGER.debug(
                                    "Failed to read hardware version: %s", err
                                )

                        # Stored under "firmware_version", not "sw_version": that legacy
                        # storage key held the Cloud ID and is migrated to "cloud_id" on load.
                        if not self.data.get("firmware_version"):
                            nrf_fw = ""
                            try:
                                nrf_raw = await asyncio.wait_for(
                                    client.read_gatt_char(CHAR_NRF_FW_UUID),
                                    timeout=TIMEOUT_GATT_OP,
                                )
                                if len(nrf_raw) >= 4:
                                    nrf_fw = f"{nrf_raw[2]}.{nrf_raw[1]}.{nrf_raw[0]}"
                            except _BLE_IO_ERRORS as err:
                                _LOGGER.debug(
                                    "Failed to read NRF firmware version: %s", err
                                )

                            esp_fw = ""
                            try:
                                esp_raw = await asyncio.wait_for(
                                    client.read_gatt_char(CHAR_ESP32_FW_UUID),
                                    timeout=TIMEOUT_GATT_OP,
                                )
                                if len(esp_raw) >= 4:
                                    esp_fw = f"{esp_raw[2]}.{esp_raw[1]}.{esp_raw[0]}"
                            except _BLE_IO_ERRORS as err:
                                _LOGGER.debug(
                                    "Failed to read ESP32 firmware version: %s", err
                                )

                            # Only the chips that answered, without a dangling separator.
                            fw_parts = [
                                part
                                for part in (
                                    f"NRF {nrf_fw}" if nrf_fw else "",
                                    f"ESP32 {esp_fw}" if esp_fw else "",
                                )
                                if part
                            ]
                            if fw_parts:
                                self.data["firmware_version"] = " / ".join(fw_parts)

                        if not self.data.get("first_connection"):
                            try:
                                fc_raw = await asyncio.wait_for(
                                    client.read_gatt_char(CHAR_FIRST_CONNECTION_UUID),
                                    timeout=TIMEOUT_GATT_OP,
                                )
                                if len(fc_raw) >= 4:
                                    ts = int.from_bytes(fc_raw[:4], byteorder="big")
                                    if ts > 0:
                                        self.data["first_connection"] = (
                                            dt_util.utc_from_timestamp(ts)
                                        )
                            except _BLE_IO_ERRORS as err:
                                _LOGGER.debug(
                                    "Failed to read first connection date: %s", err
                                )

                        prev_replacement = self.data.get("probe_replacement")
                        try:
                            pr_raw = await asyncio.wait_for(
                                client.read_gatt_char(CHAR_PROBE_REPLACEMENT_UUID),
                                timeout=TIMEOUT_GATT_OP,
                            )
                            if len(pr_raw) >= 4:
                                ts = int.from_bytes(pr_raw[:4], byteorder="big")
                                # 0 = never replaced: reset a previously stored date.
                                self.data["probe_replacement"] = (
                                    dt_util.utc_from_timestamp(ts) if ts > 0 else None
                                )
                        except _BLE_IO_ERRORS as err:
                            _LOGGER.debug(
                                "Failed to read probe replacement date: %s", err
                            )

                        try:
                            cal_raw = await asyncio.wait_for(
                                client.read_gatt_char(CHAR_LAST_PH_CALIB_UUID),
                                timeout=TIMEOUT_GATT_OP,
                            )
                            if len(cal_raw) >= 4:
                                ts = int.from_bytes(cal_raw[:4], byteorder="big")
                                if ts > 0:
                                    self.data["last_ph_calib"] = (
                                        dt_util.utc_from_timestamp(ts)
                                    )
                        except _BLE_IO_ERRORS as err:
                            _LOGGER.debug(
                                "Failed to read last pH calibration date: %s", err
                            )

                        # A replaced probe has a new serial number: read it again then.
                        if (
                            not self.data.get("probe_serial_number")
                            or self.data.get("probe_replacement") != prev_replacement
                        ):
                            try:
                                psn_raw = await asyncio.wait_for(
                                    client.read_gatt_char(CHAR_PROBE_SERIAL_UUID),
                                    timeout=TIMEOUT_GATT_OP,
                                )
                                val = (
                                    psn_raw.decode("ascii").replace("\x00", "").strip()
                                )
                                if val:
                                    self.data["probe_serial_number"] = val
                            except (*_BLE_IO_ERRORS, UnicodeDecodeError) as err:
                                _LOGGER.debug(
                                    "Failed to read probe serial number: %s", err
                                )

                except (*_BLE_IO_ERRORS, ValueError, RuntimeError) as err:
                    return self._handle_ble_error(
                        f"Communication error: {err}", BT_STATUS_ERROR
                    )
                finally:
                    if client and client.is_connected:
                        for notify_uuid in started_notify_uuids:
                            try:
                                await asyncio.wait_for(
                                    client.stop_notify(notify_uuid),
                                    timeout=TIMEOUT_GATT_OP,
                                )
                            except _BLE_IO_ERRORS as err:
                                _LOGGER.debug(
                                    "Ignored error during stop_notify: %s", err
                                )
                    await _safely_disconnect(client)

            parsed_data = (
                parse_blueriiot_frame(received_payload)
                if is_blueriiot
                else parse_raw_frame(received_payload)
            )

            if not parsed_data:
                return self._handle_ble_error("Payload parsing error", BT_STATUS_ERROR)

            # Only reset now: before, an invalid frame reset the counter
            # to 0 on every cycle and the retry budget never ran out.
            self.retry_count = 0

            clean_payload = (
                received_payload[1:]
                if len(received_payload) == 19
                else received_payload
            )
            hex_frame = clean_payload.hex().upper()

            # The electrode potential read during this very analysis (never
            # one kept from an earlier analysis).
            ph_mv = electrical_mv if not is_blueriiot else None
            orp_mv = electrical_orp if not is_blueriiot else None

            new_data = self._apply_new_measurements(
                parsed_data,
                hex_frame,
                ph_mv=ph_mv,
                ph_calibration=ph_calibration,
                ph_calibration_source=ph_calibration_source,
                orp_mv=orp_mv,
            )
            new_data["receive_method"] = "active"
            if new_data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION:
                new_data["ph_hr_available"] = True

            self.data.update(new_data)
            self._update_device_registry()
            self._schedule_save()
            self.update_schedule()
            self._sync_passive_issue()
            self._sync_calibration_issues()
            return self.data
        finally:
            self.update_volatile_state({"action_running": False})

    def _handle_ble_error(
        self, error_msg: str, status: str = BT_STATUS_ERROR
    ) -> dict[str, Any]:
        _LOGGER.debug(
            "Blue Connect %s: %s (status=%s, retry=%d)",
            self.safe_mac,
            error_msg,
            status,
            self.retry_count,
        )
        if status in (BT_STATUS_ERROR, BT_STATUS_WRITE_FAILED) and self.retry_count < 2:
            self.retry_count += 1
            self._set_bt_status(BT_STATUS_ERROR_RETRY)
            if self._retry_cancel:
                self._retry_cancel()

            @callback
            def _trigger_retry(_now: datetime) -> None:
                self._retry_cancel = None
                if not self._is_shutdown:
                    self.hass.async_create_task(self.async_request_refresh())

            self._retry_cancel = async_call_later(
                self.hass, ERROR_RETRY_DELAY, _trigger_retry
            )
            self.update_schedule()
            return self.data

        self._set_bt_status(status)
        self.retry_count = 0
        self.update_schedule()
        if self.data.get("ph_probe_calibrated") is not None:
            return self.data
        raise UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="unreachable_no_history",
            translation_placeholders={"error": error_msg},
        )
