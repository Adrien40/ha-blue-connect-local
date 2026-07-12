# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import logging
import asyncio
import math
from typing import Any
import homeassistant.util.dt as dt_util
from bleak import BleakClient
from bleak_retry_connector import establish_connection
from time import monotonic
from homeassistant.components.bluetooth import (
    async_ble_device_from_address,
    async_last_service_info,
    async_scanner_count,
    async_register_callback,
    async_track_unavailable,
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothServiceInfoBleak,
    BluetoothScanningMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, CALLBACK_TYPE
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_call_later
from datetime import timedelta

from .chemistry import (
    compute_lsi,
    compute_ph_equilibrium,
)
from .const import (
    DOMAIN,
    CONF_ACCESS_CODE,
    CONF_PH_CALIB_4,
    CONF_PH_CALIB_7,
    CONF_PH_REF_7,
    CONF_PH_REF_4,
    CONF_ORP_REF,
    CONF_ORP_CALIB,
    CONF_TEMP_OFFSET,
    CONF_CYA,
    CONF_TAC,
    CONF_TH,
    CONF_TDS,
    CONF_CHLORINE_MODEL,
    CONF_SCAN_INTERVAL,
    CONF_REFERENCE_TIME,
    CONF_PASSIVE_MEASURES,
    CONF_IGNORE_ECHOES,
    CHAR_AUTH_UUID,
    CHAR_TRIGGER_UUID,
    CHAR_NOTIFY_UUID,
    TIMEOUT_BLE_CONN,
    SAVE_DEBOUNCE_DELAY,
    DEBOUNCE_COOLDOWN,
    BLE_RECENTLY_SEEN_THRESHOLD_S,
    DEFAULT_PH_CALIB_4,
    DEFAULT_PH_CALIB_7,
    DEFAULT_PH_REF_4,
    DEFAULT_PH_REF_7,
    DEFAULT_ORP_CALIB,
    DEFAULT_ORP_REF,
    TIMEOUT_GATT_OP,
    TIMEOUT_NOTIFICATION_WAIT,
    BT_STATUS_WAITING,
    BT_STATUS_CONNECTING,
    BT_STATUS_AUTHENTICATING,
    BT_STATUS_REQUESTING,
    BT_STATUS_READING,
    BT_STATUS_SUCCESS,
    BT_STATUS_ERROR,
    BT_STATUS_ERROR_RETRY,
    BT_STATUS_WRITE_FAILED,
    BT_STATUS_PAUSED,
    BT_STATUS_OUT_OF_RANGE,
    EXPECTED_FRAME_HEX_LEN_18,
    ECHO_MARKER,
    ACCEL_THRESHOLD,
)

UUID_RAW_SENSORS = "70ea0005-7a29-4fdf-93d2-838665e72677"
UUID_ACCELEROMETER = "70ea000a-7a29-4fdf-93d2-838665e72677"
UUID_SERIAL_NUMBER = "70ea0020-7a29-4fdf-93d2-838665e72677"
UUID_HW_VERSION = "70ea0021-7a29-4fdf-93d2-838665e72677"
UUID_SW_VERSION = "70ea0022-7a29-4fdf-93d2-838665e72677"

_LOGGER = logging.getLogger(__name__)

# Keys in self.data that describe a specific BLE reading and are only
# trustworthy alongside a valid raw_frame. Everything else stored in
# self.data (preferences: active_measures, passive_measures, ignore_echoes,
# chlorine_model, cya, tac/th/tds, scan_interval, reference_time, access_code,
# and device identity: serial_number/hw_version/sw_version) is independent
# of whether a BLE frame was ever successfully parsed and must always be
# restored when present.
_MEASUREMENT_ONLY_KEYS = frozenset(
    {
        "raw_frame",
        "raw_frame_0005",
        "temp_raw",
        "ph_raw",
        "orp_raw",
        "conductivity",
        "salinity",
        "battery_percent",
        "battery_adc",
        "battery",
        "battery_level",
        "temperature",
        "ph",
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


async def _safely_disconnect(client: BleakClient | None) -> None:
    if client and client.is_connected:
        try:
            await asyncio.wait_for(client.disconnect(), timeout=TIMEOUT_GATT_OP)
        except Exception as err:
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
            name=f"Blue Connect {safe_mac}",
            update_interval=timedelta(minutes=60),
        )
        self._entry_id = entry.entry_id
        self.mac = mac
        self.safe_mac = safe_mac
        self.store = Store(hass, 1, store_key(mac))

        self.ble_lock = asyncio.Lock()
        self.retry_count = 0
        self._is_shutdown = False
        self.next_slot: dt_util.dt.datetime | None = None

        self._retry_cancel: CALLBACK_TYPE | None = None
        self._recalc_cancel: CALLBACK_TYPE | None = None
        self._save_cancel: asyncio.TimerHandle | None = None
        self._force_one_shot = False

        self._ble_available = True
        self._ble_unavail_cancel: CALLBACK_TYPE | None = None
        self._ble_avail_cancel: CALLBACK_TYPE | None = None

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

        self.update_schedule()

    @property
    def entry_id(self) -> str:
        return self._entry_id

    @property
    def entry(self) -> ConfigEntry | None:
        return self.hass.config_entries.async_get_entry(self._entry_id)

    @property
    def access_code(self) -> str:
        return self.data.get(CONF_ACCESS_CODE, "").strip()

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
        except Exception:
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

    def request_deferred_recompute(self) -> None:
        if self._recalc_cancel:
            self._recalc_cancel()
            self._recalc_cancel = None

        @callback
        def _do_recompute(_now) -> None:
            self._recalc_cancel = None
            if self.data:
                self.recompute_derived_values()

        self._recalc_cancel = async_call_later(
            self.hass, DEBOUNCE_COOLDOWN, _do_recompute
        )

    @callback
    def _on_ble_unavailable(self, _info: BluetoothServiceInfoBleak) -> None:
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
        self._ble_available = True
        current_status = self.data.get("bluetooth_status")
        active = self.data.get("active_measures", True)

        if current_status == BT_STATUS_OUT_OF_RANGE and active:
            self._set_bt_status(
                "passive_mode" if not self.access_code else BT_STATUS_WAITING
            )

        if self.data.get("action_running"):
            return

        has_initial_data = self.data.get("ph") is not None

        passive_enabled = self.data.get(CONF_PASSIVE_MEASURES)
        if passive_enabled is None:
            passive_enabled = _get_opt(self.entry, CONF_PASSIVE_MEASURES, True)

        if not passive_enabled:
            return

        raw_payload = None

        for mfr_data in info.manufacturer_data.values():
            if len(mfr_data) in (18, 19):
                raw_payload = mfr_data
                break

        if not raw_payload:
            for svc_data in info.service_data.values():
                if len(svc_data) in (18, 19):
                    raw_payload = svc_data
                    break

        if raw_payload:
            clean_payload = raw_payload[1:] if len(raw_payload) == 19 else raw_payload
            hex_frame = clean_payload.hex().upper()

            if hex_frame != self.data.get("raw_frame"):
                ignore_echoes = self.data.get(CONF_IGNORE_ECHOES)
                if ignore_echoes is None:
                    ignore_echoes = _get_opt(self.entry, CONF_IGNORE_ECHOES, True)

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
                parsed = self._parse_raw_frame(raw_payload)
                if parsed:
                    new_state = self._apply_new_measurements(parsed, hex_frame)
                    new_state["receive_method"] = "passive"
                    self.update_local_state(new_state)

    async def async_initialize(self) -> None:
        saved_data = await self.store.async_load()

        if saved_data:
            rf = saved_data.get("raw_frame")
            raw_frame_valid = (
                isinstance(rf, str) and len(rf) == EXPECTED_FRAME_HEX_LEN_18
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
                # No (valid) cached reading yet: don't restore stale/absent
                # measurement fields, but still restore every preference and
                # device-identity key below - they have nothing to do with
                # whether a BLE frame was ever captured.
                for key in _MEASUREMENT_ONLY_KEYS:
                    saved_data.pop(key, None)

            for transient in ("bluetooth_status", "action_running"):
                saved_data.pop(transient, None)

            for static_key in ("serial_number", "hw_version", "sw_version"):
                if static_key in saved_data and not saved_data[static_key]:
                    saved_data.pop(static_key, None)

            if saved_data:
                self.data.update(saved_data)
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
            def _trigger_first_analysis(_now) -> None:
                if not self._is_shutdown:
                    self.hass.async_create_task(_run_first_analysis())

            async_call_later(self.hass, 2.0, _trigger_first_analysis)

    async def async_shutdown(self) -> None:
        self._is_shutdown = True
        if self._ble_unavail_cancel:
            self._ble_unavail_cancel()
        if self._ble_avail_cancel:
            self._ble_avail_cancel()
        if self._retry_cancel:
            self._retry_cancel()
        if self._recalc_cancel:
            self._recalc_cancel()
        if self._save_cancel:
            self._save_cancel.cancel()
        await self.async_save_to_disk()

    async def async_save_to_disk(self) -> None:
        data_to_save = dict(self.data)
        ts_val = data_to_save.get("last_received")
        if ts_val is not None and hasattr(ts_val, "isoformat"):
            data_to_save["last_received"] = ts_val.isoformat()
        for transient in ("bluetooth_status", "action_running"):
            data_to_save.pop(transient, None)
        await self.store.async_save(data_to_save)

    def _schedule_save(self) -> None:
        if self._is_shutdown:
            return
        if self._save_cancel:
            self._save_cancel.cancel()
        loop = asyncio.get_running_loop()

        def _schedule_save_callback():
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

    def update_volatile_state(self, updates: dict[str, Any]) -> None:
        self.data.update(updates)
        self.update_schedule()
        self.async_set_updated_data(self.data)

    def _set_bt_status(self, status: str) -> None:
        self.update_volatile_state({"bluetooth_status": status})

    def _compute_ph_calibrated(
        self, ph_raw: float, c4_meas: float, c7_meas: float, ref_4: float, ref_7: float
    ) -> float:
        if abs(c7_meas - c4_meas) < 0.01:
            return ph_raw
        slope = (ref_7 - ref_4) / (c7_meas - c4_meas)
        if abs(slope) < 1e-9:
            return ref_7
        return ref_7 + (ph_raw - c7_meas) * slope

    def _load_ph_calibration(
        self, entry: ConfigEntry
    ) -> tuple[float, float, float, float]:
        c4_meas = float(_get_opt(entry, CONF_PH_CALIB_4, DEFAULT_PH_CALIB_4))
        c7_meas = float(_get_opt(entry, CONF_PH_CALIB_7, DEFAULT_PH_CALIB_7))
        ref_7 = float(_get_opt(entry, CONF_PH_REF_7, DEFAULT_PH_REF_7))
        ref_4 = float(_get_opt(entry, CONF_PH_REF_4, DEFAULT_PH_REF_4))
        return c4_meas, c7_meas, ref_4, ref_7

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
        self, parsed_data: dict[str, Any], hex_frame: str
    ) -> dict[str, Any]:
        current_entry = self.entry
        if not current_entry:
            return self.data

        now = dt_util.utcnow()
        raw_temp = parsed_data["temp_raw"]
        raw_ph = parsed_data["ph_raw"]
        raw_orp = parsed_data["orp_raw"]

        temp_offset = float(_get_opt(current_entry, CONF_TEMP_OFFSET, 0.0))
        orp_target = float(_get_opt(current_entry, CONF_ORP_REF, DEFAULT_ORP_REF))
        orp_measured = float(_get_opt(current_entry, CONF_ORP_CALIB, DEFAULT_ORP_CALIB))
        orp_offset = orp_target - orp_measured

        temp = raw_temp + temp_offset
        orp = raw_orp + orp_offset

        c4_meas, c7_meas, ref_4, ref_7 = self._load_ph_calibration(current_entry)
        ph_calculated = self._compute_ph_calibrated(
            raw_ph, c4_meas, c7_meas, ref_4, ref_7
        )

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
            "temperature": round(temp, 2),
            "ph": round(ph_calculated, 2),
            "orp": round(orp),
            "battery_level": bat_pct,
            "last_received": now,
            "raw_frame": hex_frame,
            "bluetooth_status": BT_STATUS_SUCCESS,
        }

        new_data.update(
            self._build_chemistry_updates(
                round(temp, 2),
                round(ph_calculated, 2),
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
        raw_ph = self.data.get("ph_raw")
        raw_orp = self.data.get("orp_raw")
        hex_frame = self.data.get("raw_frame", "")

        if raw_temp is not None and raw_ph is not None and raw_orp is not None:
            parsed_data = {
                "temp_raw": raw_temp,
                "ph_raw": raw_ph,
                "orp_raw": raw_orp,
                "conductivity": self.data.get("conductivity", 0),
                "salinity": self.data.get("salinity", 0),
                "battery_percent": self.data.get("battery_percent", 0),
                "battery_adc": self.data.get("battery_adc", 0),
                "battery": self.data.get("battery", 0),
            }

            updates = self._apply_new_measurements(parsed_data, hex_frame)

            updates["last_received"] = self.data.get("last_received")
            updates["bluetooth_status"] = self.data.get("bluetooth_status")

            changed_updates = {
                k: v
                for k, v in updates.items()
                if k not in self.data or self.data[k] != v
            }
            if changed_updates:
                self.update_volatile_state(changed_updates)

    def _parse_raw_frame(self, data: bytes) -> dict[str, Any] | None:
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
                self._set_bt_status(BT_STATUS_OUT_OF_RANGE)
                self.retry_count = 0
                self.update_schedule()
                if self.data.get("ph_raw") is not None:
                    return self.data
                raise UpdateFailed(
                    f"Blue Connect {self.safe_mac} out of range and no "
                    "history available"
                )

            device = async_ble_device_from_address(
                self.hass, self.mac, connectable=True
            )
            if not device:
                return self._handle_ble_error(
                    f"Blue Connect {self.safe_mac}: device not found "
                    "in Bluetooth cache",
                    BT_STATUS_OUT_OF_RANGE,
                )

            client: BleakClient | None = None
            notify_started = False
            received_payload: bytes | None = None
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

                    received_data_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4)

                    def _put(data: bytes) -> None:
                        try:
                            received_data_queue.put_nowait(data)
                        except asyncio.QueueFull:
                            pass

                    def notification_handler(sender, data: bytes) -> None:
                        loop.call_soon_threadsafe(_put, data)

                    await asyncio.wait_for(
                        client.start_notify(CHAR_NOTIFY_UUID, notification_handler),
                        timeout=TIMEOUT_GATT_OP,
                    )
                    notify_started = True

                    for attempt in range(1, 3):
                        while not received_data_queue.empty():
                            received_data_queue.get_nowait()

                        self._set_bt_status(BT_STATUS_AUTHENTICATING)
                        try:
                            await asyncio.wait_for(
                                client.write_gatt_char(
                                    CHAR_AUTH_UUID,
                                    self.access_code.encode("ascii"),
                                    response=True,
                                ),
                                timeout=TIMEOUT_GATT_OP,
                            )
                            await asyncio.sleep(0.2)

                            self._set_bt_status(BT_STATUS_REQUESTING)
                            await asyncio.wait_for(
                                client.write_gatt_char(
                                    CHAR_TRIGGER_UUID, bytearray([0x02]), response=True
                                ),
                                timeout=TIMEOUT_GATT_OP,
                            )
                        except Exception as write_err:
                            _LOGGER.warning(
                                "GATT write failed on attempt %d: %s",
                                attempt,
                                write_err,
                            )
                            if attempt == 2:
                                return self._handle_ble_error(
                                    f"Write failed: {write_err}", BT_STATUS_WRITE_FAILED
                                )
                            await asyncio.sleep(1.0)
                            continue

                        self._set_bt_status(BT_STATUS_READING)
                        try:
                            received_payload = await asyncio.wait_for(
                                received_data_queue.get(),
                                timeout=TIMEOUT_NOTIFICATION_WAIT,
                            )
                            if received_payload:
                                break
                        except asyncio.TimeoutError:
                            _LOGGER.warning(
                                "Timeout waiting for notification on attempt %d",
                                attempt,
                            )

                    if not received_payload:
                        return self._handle_ble_error(
                            "No valid data received from Blue Connect.", BT_STATUS_ERROR
                        )

                    try:
                        raw_0005 = await asyncio.wait_for(
                            client.read_gatt_char(UUID_RAW_SENSORS),
                            timeout=TIMEOUT_GATT_OP,
                        )
                        self.data["raw_frame_0005"] = raw_0005.hex().upper()
                    except Exception as err:
                        _LOGGER.debug(
                            "Failed to read raw sensors frame (0x0005): %s", err
                        )

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
                            elif abs(x) > ACCEL_THRESHOLD or abs(z) > ACCEL_THRESHOLD:
                                self.data["float_status"] = "horizontal"
                            else:
                                self.data["float_status"] = "tilted"
                    except Exception as err:
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
                        except Exception as err:
                            _LOGGER.debug("Failed to read serial number: %s", err)

                    if not self.data.get("hw_version"):
                        try:
                            hw = await asyncio.wait_for(
                                client.read_gatt_char(UUID_HW_VERSION),
                                timeout=TIMEOUT_GATT_OP,
                            )
                            val = hw.decode("ascii").replace("\x00", "").strip()
                            if val:
                                self.data["hw_version"] = val
                        except Exception as err:
                            _LOGGER.debug("Failed to read hardware version: %s", err)

                    if not self.data.get("sw_version"):
                        try:
                            sw = await asyncio.wait_for(
                                client.read_gatt_char(UUID_SW_VERSION),
                                timeout=TIMEOUT_GATT_OP,
                            )
                            val = sw.decode("ascii").replace("\x00", "").strip()
                            if val:
                                self.data["sw_version"] = val
                        except Exception as err:
                            _LOGGER.debug("Failed to read software version: %s", err)

                except Exception as err:
                    return self._handle_ble_error(
                        f"Communication error: {err}", BT_STATUS_ERROR
                    )
                finally:
                    if notify_started and client and client.is_connected:
                        try:
                            await asyncio.wait_for(
                                client.stop_notify(CHAR_NOTIFY_UUID),
                                timeout=TIMEOUT_GATT_OP,
                            )
                        except Exception as err:
                            _LOGGER.debug("Ignored error during stop_notify: %s", err)
                    await _safely_disconnect(client)

            self.retry_count = 0
            parsed_data = self._parse_raw_frame(received_payload)

            if not parsed_data:
                return self._handle_ble_error("Payload parsing error", BT_STATUS_ERROR)

            clean_payload = (
                received_payload[1:]
                if len(received_payload) == 19
                else received_payload
            )
            hex_frame = clean_payload.hex().upper()

            new_data = self._apply_new_measurements(parsed_data, hex_frame)
            new_data["receive_method"] = "active"

            self.data.update(new_data)
            self._schedule_save()
            self.update_schedule()
            return self.data
        finally:
            self.update_volatile_state({"action_running": False})

    def _handle_ble_error(
        self, error_msg: str, status: str = BT_STATUS_ERROR
    ) -> dict[str, Any]:
        if status in (BT_STATUS_ERROR, BT_STATUS_WRITE_FAILED) and self.retry_count < 2:
            self.retry_count += 1
            self._set_bt_status(BT_STATUS_ERROR_RETRY)
            if self._retry_cancel:
                self._retry_cancel()

            @callback
            def _trigger_retry(_now) -> None:
                self._retry_cancel = None
                if not self._is_shutdown:
                    self.hass.async_create_task(self.async_request_refresh())

            self._retry_cancel = async_call_later(self.hass, 60, _trigger_retry)
            self.update_schedule()
            return self.data

        self._set_bt_status(status)
        self.retry_count = 0
        self.update_schedule()
        if self.data.get("ph_raw") is not None:
            return self.data
        raise UpdateFailed(f"Blue Connect unreachable: {error_msg}")
