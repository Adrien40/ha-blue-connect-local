# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import logging
from datetime import time
from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_MAC_ADDRESS,
    CONF_REFERENCE_TIME,
    get_blue_connect_model,
    blue_connect_device_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    mac = entry.data[CONF_MAC_ADDRESS]
    entry_id = entry.entry_id
    model_name = entry.data.get("model") or get_blue_connect_model(entry.title)

    async_add_entities(
        [BlueConnectReferenceTime(coordinator, mac, model_name, entry_id)]
    )


class BlueConnectReferenceTime(CoordinatorEntity, TimeEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "reference_time"
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, mac: str, model_name: str, entry_id: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._entry_id = entry_id
        self._attr_unique_id = f"{mac}_{CONF_REFERENCE_TIME}"
        self._attr_device_info = blue_connect_device_info(mac, model_name)

    @property
    def available(self) -> bool:
        if not self.coordinator.access_code:
            return False
        return super().available

    @property
    def native_value(self) -> time | None:
        time_str = self.coordinator.data.get(CONF_REFERENCE_TIME)
        if time_str is None:
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry:
                time_str = entry.options.get(
                    CONF_REFERENCE_TIME, entry.data.get(CONF_REFERENCE_TIME, "08:00")
                )
        if time_str:
            try:
                parts = time_str.split(":")
                return time(hour=int(parts[0]), minute=int(parts[1]))
            except (ValueError, IndexError):
                pass
        return time(hour=8, minute=0)

    async def async_set_value(self, value: time) -> None:
        time_str = value.strftime("%H:%M")
        self.coordinator.update_local_state({CONF_REFERENCE_TIME: time_str})
