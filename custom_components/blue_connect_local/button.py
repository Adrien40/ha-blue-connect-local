# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import logging
import asyncio
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import (
    DOMAIN,
    CONF_MAC_ADDRESS,
    get_blue_connect_model,
    blue_connect_device_info,
    TIMEOUT_FORCE_REFRESH,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    mac = entry.data[CONF_MAC_ADDRESS]
    model_name = entry.data.get("model") or get_blue_connect_model(entry.title)

    async_add_entities([BlueConnectForceAnalysisButton(coordinator, mac, model_name)])


class BlueConnectForceAnalysisButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "force_analysis"

    def __init__(self, coordinator, mac: str, model_name: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{mac}_force_analysis"
        self._attr_icon = "mdi:refresh-circle"
        self._attr_device_info = blue_connect_device_info(mac, model_name)

    @property
    def available(self) -> bool:
        if not self.coordinator.access_code:
            return False
        return super().available

    async def async_press(self) -> None:
        if self.coordinator.is_shutdown:
            _LOGGER.debug(
                "Ignoring button press for %s: coordinator is shutting down",
                self.coordinator.safe_mac,
            )
            return

        if self.coordinator.data and self.coordinator.data.get("action_running", False):
            _LOGGER.warning(
                "Analysis already running on Blue Connect (timeout: %ss)",
                TIMEOUT_FORCE_REFRESH,
            )
            return

        self.coordinator.request_one_shot_analysis()
        self.coordinator.update_volatile_state({"action_running": True})

        _LOGGER.info(
            "New analysis requested for %s (~60s)...",
            self.coordinator.safe_mac,
        )

        async def _run_analysis() -> None:
            try:
                await asyncio.wait_for(
                    self.coordinator.async_request_refresh(),
                    timeout=TIMEOUT_FORCE_REFRESH,
                )
            except asyncio.TimeoutError:
                _LOGGER.exception(
                    "Analysis exceeded timeout of %s seconds for %s",
                    TIMEOUT_FORCE_REFRESH,
                    self.coordinator.safe_mac,
                )
            except Exception:
                _LOGGER.exception(
                    "Analysis failed for %s",
                    self.coordinator.safe_mac,
                )
            finally:
                self.coordinator.update_volatile_state({"action_running": False})

        entry = self.hass.config_entries.async_get_entry(self.coordinator.entry_id)
        if entry:
            entry.async_create_background_task(
                self.hass,
                _run_analysis(),
                "blue_connect_button_refresh",
            )
