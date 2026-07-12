# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import logging
from homeassistant.components.number import RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import (
    DOMAIN,
    CONF_MAC_ADDRESS,
    CONF_CYA,
    CONF_TAC,
    CONF_TH,
    CONF_TDS,
    CONF_SCAN_INTERVAL,
    CONF_CHLORINE_MODEL,
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
        [
            BlueConnectUpdateIntervalNumber(coordinator, mac, model_name, entry_id),
            BlueConnectWaterConfigNumber(
                coordinator,
                mac,
                CONF_TAC,
                0,
                500,
                1,
                0,
                "mdi:water-percent",
                entry_id,
                model_name,
                "mg/L",
            ),
            BlueConnectWaterConfigNumber(
                coordinator,
                mac,
                CONF_TDS,
                0,
                5000,
                1,
                0,
                "mdi:blur",
                entry_id,
                model_name,
                "ppm",
            ),
            BlueConnectWaterConfigNumber(
                coordinator,
                mac,
                CONF_TH,
                0,
                800,
                1,
                0,
                "mdi:water-outline",
                entry_id,
                model_name,
                "mg/L",
            ),
            BlueConnectWaterConfigNumber(
                coordinator,
                mac,
                CONF_CYA,
                0,
                150,
                1,
                40,
                "mdi:shield-sun",
                entry_id,
                model_name,
                "mg/L",
            ),
        ]
    )


class BlueConnectUpdateIntervalNumber(CoordinatorEntity, RestoreNumber):
    _attr_has_entity_name = True
    _attr_translation_key = "scan_interval"

    def __init__(self, coordinator, mac: str, model_name: str, entry_id: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._entry_id = entry_id
        self._attr_unique_id = f"{mac}_{CONF_SCAN_INTERVAL}"
        self._attr_native_min_value = 5
        self._attr_native_max_value = 1440
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "min"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:sync"
        self._attr_mode = "box"
        self._attr_device_info = blue_connect_device_info(mac, model_name)

    @property
    def available(self) -> bool:
        if not self.coordinator.access_code:
            return False
        return super().available

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        val = self.coordinator.data.get(CONF_SCAN_INTERVAL)
        if val is None:
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry and CONF_SCAN_INTERVAL in entry.options:
                val = round(float(entry.options[CONF_SCAN_INTERVAL]))
            elif entry and CONF_SCAN_INTERVAL in entry.data:
                val = round(float(entry.data[CONF_SCAN_INTERVAL]))

        if val is None:
            last = await self.async_get_last_number_data()
            val = (
                round(float(last.native_value))
                if last and last.native_value is not None
                else 60
            )

        val = max(self._attr_native_min_value, min(val, self._attr_native_max_value))
        self._attr_native_value = val

        self.coordinator.update_volatile_state({CONF_SCAN_INTERVAL: val})
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        val = round(float(value))
        val = max(self._attr_native_min_value, min(val, self._attr_native_max_value))
        self._attr_native_value = val

        self.coordinator.update_local_state({CONF_SCAN_INTERVAL: val})


class BlueConnectWaterConfigNumber(CoordinatorEntity, RestoreNumber):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        mac: str,
        key: str,
        min_val: float,
        max_val: float,
        step: float,
        default_val: float,
        icon: str,
        entry_id: str,
        model_name: str,
        unit: str,
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._key = key
        self._entry_id = entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._default_val = default_val
        self._attr_mode = "box"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = blue_connect_device_info(mac, model_name)

    @property
    def available(self) -> bool:
        if self._key == CONF_CYA:
            val = (
                self.coordinator.data.get(CONF_CHLORINE_MODEL)
                if self.coordinator.data
                else None
            )
            if val is None:
                entry = self.hass.config_entries.async_get_entry(self._entry_id)
                if entry:
                    val = entry.options.get(
                        CONF_CHLORINE_MODEL,
                        entry.data.get(CONF_CHLORINE_MODEL, "chlorine"),
                    )
            return val != "bromine"
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        val = self.coordinator.data.get(self._key) if self.coordinator.data else None
        if val is None:
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry and self._key in entry.options:
                val = round(float(entry.options[self._key]))
        if val is None:
            last = await self.async_get_last_number_data()
            val = (
                round(float(last.native_value))
                if last and last.native_value is not None
                else self._default_val
            )

        val = max(self._attr_native_min_value, min(val, self._attr_native_max_value))
        self._attr_native_value = val

        self.coordinator.update_volatile_state({self._key: val})
        self.async_write_ha_state()
        self.coordinator.request_deferred_recompute()

    async def async_set_native_value(self, value: float) -> None:
        int_val = round(float(value))
        int_val = max(
            int(self._attr_native_min_value),
            min(int_val, int(self._attr_native_max_value)),
        )
        self._attr_native_value = int_val

        self.coordinator.update_local_state({self._key: int_val})
        self.coordinator.request_deferred_recompute()
