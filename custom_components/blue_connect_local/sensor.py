# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

from __future__ import annotations

import logging
from datetime import datetime as dt_datetime
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_last_service_info,
    async_register_callback,
)
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BlueConnectConfigEntry
from .const import (
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
    CONF_MAC_ADDRESS,
    DEVICE_TYPE_BLUERIIOT,
    PH_RESOLUTION_HIGH,
    PH_RESOLUTION_STANDARD,
    PH_SOURCE_HIGH_RESOLUTION,
    blue_connect_device_info,
    get_blue_connect_model,
    model_has_conductivity,
    model_has_salinity,
)
from .coordinator import BlueConnectCoordinator

_LOGGER = logging.getLogger(__name__)


# Coordinator centralizes updates; entities are read-only.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlueConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    mac_address = entry.data[CONF_MAC_ADDRESS]
    sku = coordinator.data.get("sku")
    has_conductivity = coordinator.data.get("has_conductivity")
    model_name = get_blue_connect_model(
        sku, has_conductivity, coordinator.data.get("device_type")
    )

    sensors = [
        BlueConnectSensor(
            coordinator,
            mac_address,
            "temperature",
            SensorDeviceClass.TEMPERATURE,
            UnitOfTemperature.CELSIUS,
            2,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "ph",
            SensorDeviceClass.PH,
            None,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "orp",
            None,
            "mV",
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "conductivity",
            None,
            "µS/cm",
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
            enabled_default=model_has_conductivity(sku, has_conductivity),
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "target_equilibrium_ph",
            SensorDeviceClass.PH,
            None,
            2,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "lsi",
            None,
            None,
            2,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        # Entity in the Diagnostic category. Developer's choice, do not remove this comment.
        BlueConnectSensor(
            coordinator,
            mac_address,
            "lsi_status",
            SensorDeviceClass.ENUM,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            options=["corrosive", "balanced", "scaling", "unknown"],
        ),
        # Entity in the Diagnostic category. Developer's choice, do not remove this comment.
        BlueConnectSensor(
            coordinator,
            mac_address,
            "float_status",
            SensorDeviceClass.ENUM,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            options=["vertical", "tilted", "horizontal", "upside_down"],
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "accelerometer",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "ph_raw",
            None,
            None,
            2,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "ph_probe_calibrated",
            None,
            None,
            1,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "probe_ph_calibration",
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "ph_raw_mv",
            SensorDeviceClass.VOLTAGE,
            "mV",
            1,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "orp_raw_mv",
            SensorDeviceClass.VOLTAGE,
            "mV",
            0,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "orp_probe_calibrated",
            None,
            "mV",
            0,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "probe_orp_calibration",
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "battery_level",
            SensorDeviceClass.BATTERY,
            "%",
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "battery",
            SensorDeviceClass.VOLTAGE,
            "mV",
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "battery_adc",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "last_received",
            SensorDeviceClass.TIMESTAMP,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "raw_frame",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "raw_frame_0005",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "cloud_id",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "probe_serial_number",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "first_connection",
            SensorDeviceClass.TIMESTAMP,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "probe_replacement",
            SensorDeviceClass.TIMESTAMP,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "last_ph_calib",
            SensorDeviceClass.TIMESTAMP,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "last_orp_calib",
            SensorDeviceClass.TIMESTAMP,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            enabled_default=False,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "receive_method",
            SensorDeviceClass.ENUM,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            options=["passive", "active", "unknown"],
            enabled_default=False,
        ),
        BlueConnectBluetoothStatusSensor(coordinator, mac_address, model_name),
        BlueConnectRealTimeRSSISensor(coordinator, mac_address, model_name),
        BlueConnectNextAnalysisSensor(coordinator, mac_address, model_name),
    ]

    sensors.append(
        BlueConnectSensor(
            coordinator,
            mac_address,
            "salinity",
            None,
            "g/L",
            2,
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
            enabled_default=model_has_salinity(sku, has_conductivity),
        )
    )

    async_add_entities(sensors)


class BlueConnectSensor(CoordinatorEntity[BlueConnectCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BlueConnectCoordinator,
        mac: str,
        key: str,
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        precision: int | None = None,
        category: EntityCategory | None = None,
        model_name: str = "Blue Connect",
        options: list[str] | None = None,
        state_class: SensorStateClass | None = None,
        enabled_default: bool = True,
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_suggested_display_precision = precision
        self._attr_entity_category = category
        self._attr_state_class = state_class
        self._attr_entity_registry_enabled_default = enabled_default
        if options:
            self._attr_options = options
        self._attr_device_info = blue_connect_device_info(
            mac,
            model_name,
            model_id=coordinator.data.get("sku"),
            serial_number=coordinator.data.get("serial_number"),
            hw_version=coordinator.data.get("hardware_version"),
            sw_version=coordinator.data.get("firmware_version"),
        )

    @property
    def native_value(self) -> Any | None:
        if not self.coordinator.data:
            return None
        if self._key == "probe_ph_calibration":
            calibration = self.coordinator.data.get(self._key)
            if not calibration:
                return None
            # pH 7 first, like the calibration forms (the probe stores pH 4
            # in its first point, so sort rather than follow its order).
            points = sorted(
                (
                    (calibration["ph_1"], calibration["mv_1"]),
                    (calibration["ph_2"], calibration["mv_2"]),
                ),
                reverse=True,
            )
            return " · ".join(f"pH {ph:.1f} = {mv:.1f} mV" for ph, mv in points)
        if self._key == "probe_orp_calibration":
            orp_calibration = self.coordinator.data.get(self._key)
            if not orp_calibration:
                return None
            # The stored calibration, like the pH one: the reference solution's
            # potential, then the raw potential the electrode read in it. The
            # correction (their difference) is an attribute.
            return f"ORP {orp_calibration['ref']} mV = {orp_calibration['mes']} mV"
        return self.coordinator.data.get(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Origin and resolution of the pH value, or the calibration values."""
        if self._key == "probe_ph_calibration":
            calibration = self.coordinator.data.get(self._key)
            return dict(calibration) if calibration else None
        if self._key == "probe_orp_calibration":
            orp_calibration = self.coordinator.data.get(self._key)
            if not orp_calibration:
                return None
            attributes_orp: dict[str, Any] = {
                "reference": orp_calibration["ref"],
                "measured": orp_calibration["mes"],
                # What the probe adds to its raw potential.
                "correction": orp_calibration["ref"] - orp_calibration["mes"],
            }
            if orp_calibration.get("status") is not None:
                # Shown as read: what the codes mean is not documented.
                attributes_orp["status_code"] = orp_calibration["status"]
            return attributes_orp
        if self._key == "orp":
            if self.coordinator.data.get("device_type") == DEVICE_TYPE_BLUERIIOT:
                return None
            orp_source = self.coordinator.data.get("orp_calibration_source")
            if orp_source is None:
                return None
            # Which calibration the ORP used: the integration's own, when
            # filled in, takes priority over the one stored in the probe.
            return {"calibration_source": orp_source}
        if self._key != "ph" or (
            self.coordinator.data.get("device_type") == DEVICE_TYPE_BLUERIIOT
        ):
            return None
        source = self.coordinator.data.get("ph_source")
        if source is None:
            return None
        attributes = {
            "source": source,
            "resolution": (
                PH_RESOLUTION_HIGH
                if source == PH_SOURCE_HIGH_RESOLUTION
                else PH_RESOLUTION_STANDARD
            ),
        }
        calibration_source = self.coordinator.data.get("ph_hr_calibration_source")
        if calibration_source is not None:
            # Which calibration the high-resolution pH used: the
            # integration's own mV calibration, when turned on, takes
            # priority over the one stored in the probe.
            attributes["calibration_source"] = calibration_source
        return attributes

    @property
    def available(self) -> bool:
        is_blueriiot = self.coordinator.data.get("device_type") == DEVICE_TYPE_BLUERIIOT
        if self._key in (
            "raw_frame_0005",
            "ph_raw",
            "ph_raw_mv",
            "probe_ph_calibration",
            "orp_raw_mv",
            "probe_orp_calibration",
            "accelerometer",
            "float_status",
            "cloud_id",
            "probe_serial_number",
            "first_connection",
            "probe_replacement",
            "last_ph_calib",
            "last_orp_calib",
        ) and (not self.coordinator.access_code or is_blueriiot):
            return False
        # Zodiac-only characteristic: never exposed by the Blueriiot profile.
        if self._key == "battery_adc" and is_blueriiot:
            return False
        return super().available


class BlueConnectBluetoothStatusSensor(
    CoordinatorEntity[BlueConnectCoordinator], SensorEntity
):
    _attr_has_entity_name = True
    # Entity in the Diagnostic category. Developer's choice, do not remove this comment.
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "bluetooth_status"
    _attr_options: list[str] = [
        BT_STATUS_WAITING,
        BT_STATUS_CONNECTING,
        BT_STATUS_AUTHENTICATING,
        BT_STATUS_REQUESTING,
        BT_STATUS_READING,
        BT_STATUS_SUCCESS,
        BT_STATUS_ERROR,
        BT_STATUS_ERROR_RETRY,
        BT_STATUS_WRITE_FAILED,
        BT_STATUS_AUTH_FAILED,
        BT_STATUS_PAUSED,
        BT_STATUS_OUT_OF_RANGE,
        "passive_mode",
    ]

    def __init__(
        self, coordinator: BlueConnectCoordinator, mac: str, model_name: str
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{mac}_bluetooth_status"
        self._attr_device_info = blue_connect_device_info(
            mac,
            model_name,
            model_id=coordinator.data.get("sku"),
            serial_number=coordinator.data.get("serial_number"),
            hw_version=coordinator.data.get("hardware_version"),
            sw_version=coordinator.data.get("firmware_version"),
        )

    @property
    def native_value(self) -> str:
        if not self.coordinator.data:
            return (
                "passive_mode"
                if not self.coordinator.access_code
                else BT_STATUS_WAITING
            )
        return str(
            self.coordinator.data.get(
                "bluetooth_status",
                "passive_mode"
                if not self.coordinator.access_code
                else BT_STATUS_WAITING,
            )
        )


class BlueConnectRealTimeRSSISensor(
    CoordinatorEntity[BlueConnectCoordinator], RestoreSensor
):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = "dBm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    # Entity in the Diagnostic category. Developer's choice, do not remove this comment.
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "rssi"
    _attr_should_poll = False

    def __init__(
        self, coordinator: BlueConnectCoordinator, mac: str, model_name: str
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{mac}_rssi"
        self._attr_device_info = blue_connect_device_info(
            mac,
            model_name,
            model_id=coordinator.data.get("sku"),
            serial_number=coordinator.data.get("serial_number"),
            hw_version=coordinator.data.get("hardware_version"),
            sw_version=coordinator.data.get("firmware_version"),
        )
        self._attr_native_value = None

    @property
    def available(self) -> bool:
        if (
            self.coordinator.data
            and self.coordinator.data.get("bluetooth_status") == BT_STATUS_OUT_OF_RANGE
        ):
            return False
        return self.coordinator.ble_available and self._attr_native_value is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_info = async_last_service_info(self.hass, self._mac, connectable=False)
        if last_info and hasattr(last_info, "rssi"):
            self._attr_native_value = last_info.rssi
        else:
            last_sensor_data = await self.async_get_last_sensor_data()
            if last_sensor_data and last_sensor_data.native_value is not None:
                self._attr_native_value = last_sensor_data.native_value

        self.async_write_ha_state()

        @callback
        def _async_on_bluetooth_change(
            info: BluetoothServiceInfoBleak, change: BluetoothChange
        ) -> None:
            self._attr_native_value = info.rssi
            self.async_write_ha_state()

        self.async_on_remove(
            async_register_callback(
                self.hass,
                _async_on_bluetooth_change,
                BluetoothCallbackMatcher(address=self._mac),
                BluetoothScanningMode.PASSIVE,
            )
        )


class BlueConnectNextAnalysisSensor(
    CoordinatorEntity[BlueConnectCoordinator], SensorEntity
):
    _attr_has_entity_name = True
    # Entity in the Diagnostic category. Developer's choice, do not remove this comment.
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "next_analysis"

    def __init__(
        self, coordinator: BlueConnectCoordinator, mac: str, model_name: str
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{mac}_next_analysis"
        self._attr_device_info = blue_connect_device_info(
            mac,
            model_name,
            model_id=coordinator.data.get("sku"),
            serial_number=coordinator.data.get("serial_number"),
            hw_version=coordinator.data.get("hardware_version"),
            sw_version=coordinator.data.get("firmware_version"),
        )

    @property
    def native_value(self) -> dt_datetime | None:
        if not self.coordinator.data:
            return None

        if not self.coordinator.access_code:
            next_slot = getattr(self.coordinator, "next_slot", None)
            if next_slot is not None and next_slot.tzinfo is None:
                next_slot = dt_util.as_utc(next_slot)
            return next_slot

        if not self.coordinator.data.get("active_measures", True):
            return None
        if self.coordinator.data.get("action_running", False):
            return None

        next_slot = getattr(self.coordinator, "next_slot", None)
        if next_slot is None:
            return None

        if next_slot.tzinfo is None:
            next_slot = dt_util.as_utc(next_slot)

        return next_slot

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None
