# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

from __future__ import annotations

from datetime import datetime as dt_datetime
from typing import Any
import logging
import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
    RestoreSensor,
)
from homeassistant.components.bluetooth import (
    async_register_callback,
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothServiceInfoBleak,
    async_last_service_info,
    BluetoothScanningMode,
)
from homeassistant.const import UnitOfTemperature, EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import (
    DOMAIN,
    CONF_MAC_ADDRESS,
    get_blue_connect_model,
    blue_connect_device_info,
    model_has_salinity,
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
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    mac_address = entry.data[CONF_MAC_ADDRESS]
    model_name = entry.data.get("model") or get_blue_connect_model(entry.title)

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
            2,
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
        BlueConnectSensor(
            coordinator,
            mac_address,
            "float_status",
            SensorDeviceClass.ENUM,
            None,
            category=EntityCategory.DIAGNOSTIC,
            model_name=model_name,
            options=["vertical", "tilted", "horizontal", "upside_down"],
            icon="mdi:lifebuoy",
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "accelerometer",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            icon="mdi:axis-y-arrow",
            model_name=model_name,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "ph_raw",
            None,
            None,
            2,
            category=EntityCategory.DIAGNOSTIC,
            icon="mdi:lightning-bolt",
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
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
            icon="mdi:battery-bluetooth",
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
            icon="mdi:sine-wave",
            model_name=model_name,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "last_received",
            SensorDeviceClass.TIMESTAMP,
            None,
            category=EntityCategory.DIAGNOSTIC,
            icon="mdi:clock-check",
            model_name=model_name,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "raw_frame",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            icon="mdi:bluetooth-transfer",
            model_name=model_name,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "raw_frame_0005",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            icon="mdi:memory",
            model_name=model_name,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "serial_number",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            icon="mdi:identifier",
            model_name=model_name,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "hw_version",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            icon="mdi:chip",
            model_name=model_name,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "sw_version",
            None,
            None,
            category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cloud",
            model_name=model_name,
        ),
        BlueConnectSensor(
            coordinator,
            mac_address,
            "receive_method",
            SensorDeviceClass.ENUM,
            None,
            category=EntityCategory.DIAGNOSTIC,
            icon="mdi:signal-variant",
            model_name=model_name,
            options=["passive", "active", "unknown"],
        ),
        BlueConnectBluetoothStatusSensor(coordinator, mac_address, model_name),
        BlueConnectRealTimeRSSISensor(coordinator, mac_address, model_name),
        BlueConnectNextAnalysisSensor(coordinator, mac_address, model_name),
    ]

    if model_has_salinity(model_name):
        sensors.append(
            BlueConnectSensor(
                coordinator,
                mac_address,
                "salinity",
                None,
                "g/L",
                2,
                icon="mdi:shaker",
                model_name=model_name,
                state_class=SensorStateClass.MEASUREMENT,
            )
        )

    async_add_entities(sensors)


class BlueConnectSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        mac: str,
        key: str,
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        precision: int | None = None,
        category: EntityCategory | None = None,
        icon: str | None = None,
        model_name: str = "Blue Connect",
        options: list[str] | None = None,
        state_class: SensorStateClass | None = None,
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
        self._attr_icon = icon
        if options:
            self._attr_options = options
        self._attr_device_info = blue_connect_device_info(mac, model_name)

    @property
    def native_value(self) -> Any | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._key)

    @property
    def available(self) -> bool:
        if self._key in (
            "raw_frame_0005",
            "accelerometer",
            "float_status",
            "serial_number",
            "hw_version",
            "sw_version",
        ):
            if not self.coordinator.access_code:
                return False
        return super().available


class BlueConnectBluetoothStatusSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "bluetooth_status"
    _attr_options = [
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
        "passive_mode",
    ]

    def __init__(self, coordinator, mac: str, model_name: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{mac}_bluetooth_status"
        self._attr_device_info = blue_connect_device_info(mac, model_name)

    @property
    def native_value(self) -> str:
        if not self.coordinator.data:
            return (
                "passive_mode"
                if not self.coordinator.access_code
                else BT_STATUS_WAITING
            )
        return self.coordinator.data.get(
            "bluetooth_status",
            "passive_mode" if not self.coordinator.access_code else BT_STATUS_WAITING,
        )

    @property
    def icon(self) -> str:
        icons = {
            BT_STATUS_WAITING: "mdi:bluetooth-off",
            BT_STATUS_CONNECTING: "mdi:bluetooth-connect",
            BT_STATUS_AUTHENTICATING: "mdi:bluetooth-settings",
            BT_STATUS_REQUESTING: "mdi:bluetooth-transfer",
            BT_STATUS_READING: "mdi:bluetooth-transfer",
            BT_STATUS_SUCCESS: "mdi:bluetooth",
            BT_STATUS_ERROR: "mdi:bluetooth-off",
            BT_STATUS_ERROR_RETRY: "mdi:timer-sand",
            BT_STATUS_WRITE_FAILED: "mdi:alert-circle",
            BT_STATUS_PAUSED: "mdi:pause-circle",
            BT_STATUS_OUT_OF_RANGE: "mdi:bluetooth-off",
            "passive_mode": "mdi:ear-hearing",
        }
        return icons.get(self.native_value, "mdi:bluetooth-alert")


class BlueConnectRealTimeRSSISensor(CoordinatorEntity, RestoreSensor):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = "dBm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "rssi"
    _attr_should_poll = False

    def __init__(self, coordinator, mac: str, model_name: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{mac}_rssi"
        self._attr_device_info = blue_connect_device_info(mac, model_name)
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


class BlueConnectNextAnalysisSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "next_analysis"
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator, mac: str, model_name: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{mac}_next_analysis"
        self._attr_device_info = blue_connect_device_info(mac, model_name)

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
