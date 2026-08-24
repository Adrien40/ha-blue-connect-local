# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BT_STATUS_OUT_OF_RANGE,
    BT_STATUS_PAUSED,
    BT_STATUS_WAITING,
    CONF_MAC_ADDRESS,
    CONF_PASSIVE_MEASURES,
    DOMAIN,
    blue_connect_device_info,
    get_blue_connect_model,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    mac = entry.data[CONF_MAC_ADDRESS]
    entry_id = entry.entry_id
    hw_version = coordinator.data.get("hw_version")
    has_conductivity = coordinator.data.get("has_conductivity")
    model_name = get_blue_connect_model(hw_version, has_conductivity)

    async_add_entities(
        [
            BlueConnectActiveMeasuresSwitch(coordinator, mac, model_name, entry_id),
            BlueConnectPassiveMeasuresSwitch(coordinator, mac, model_name, entry_id),
        ]
    )


class BlueConnectActiveMeasuresSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "active_measures"
    _attr_icon = "mdi:clock-check-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, mac: str, model_name: str, entry_id: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._entry_id = entry_id
        self._attr_unique_id = f"{mac}_active_measures"
        self._attr_device_info = blue_connect_device_info(
            mac,
            model_name,
            hw_version=coordinator.data.get("hw_version"),
            serial_number=coordinator.data.get("serial_number"),
        )

    @property
    def available(self) -> bool:
        if not self.coordinator.access_code:
            return False
        return super().available

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return True
        return self.coordinator.data.get("active_measures", True)

    async def async_turn_on(self, **kwargs) -> None:
        if not self.coordinator.ble_available:
            self.coordinator.update_local_state(
                {
                    "active_measures": True,
                    "bluetooth_status": BT_STATUS_OUT_OF_RANGE,
                }
            )
            return

        self.coordinator.update_local_state(
            {
                "active_measures": True,
                "bluetooth_status": BT_STATUS_WAITING,
            }
        )

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.update_local_state(
            {
                "active_measures": False,
                "bluetooth_status": BT_STATUS_PAUSED,
            }
        )


class BlueConnectPassiveMeasuresSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "passive_measures"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, mac: str, model_name: str, entry_id: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._entry_id = entry_id
        self._attr_unique_id = f"{mac}_passive_measures"
        self._attr_device_info = blue_connect_device_info(
            mac,
            model_name,
            hw_version=coordinator.data.get("hw_version"),
            serial_number=coordinator.data.get("serial_number"),
        )

    @property
    def is_on(self) -> bool:
        val = self.coordinator.data.get(CONF_PASSIVE_MEASURES)
        if val is not None:
            return val
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry and CONF_PASSIVE_MEASURES in entry.options:
            return entry.options[CONF_PASSIVE_MEASURES]
        return entry.data.get(CONF_PASSIVE_MEASURES, True) if entry else True

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.update_local_state({CONF_PASSIVE_MEASURES: True})

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.update_local_state({CONF_PASSIVE_MEASURES: False})
