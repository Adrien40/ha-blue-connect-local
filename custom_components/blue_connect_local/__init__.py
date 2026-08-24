# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, CONF_ACCESS_CODE, CONF_MAC_ADDRESS, PLATFORMS
from .coordinator import BlueConnectCoordinator, format_mac_safe, store_key

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug(
        "Checking Blue Connect entry %s.%s for migration",
        entry.version,
        entry.minor_version,
    )

    if entry.version > 1:
        # Newer entry than this version of the integration knows how to
        # read: refuse rather than silently mis-handling unknown fields.
        _LOGGER.error(
            "Blue Connect entry version %s.%s is not supported by this "
            "version of the integration",
            entry.version,
            entry.minor_version,
        )
        return False

    if entry.minor_version < 2:
        # Older entries persisted a "model" guess (Gold/Silver) derived
        # from the advertised BLE name at config-flow time. That name
        # never actually carries the real SKU, so the guess was wrong
        # for anyone who wasn't running the exact device this was
        # developed against. The model is now derived on every platform
        # setup from the live hw_version instead - drop the stale field
        # so it can no longer shadow that.
        if "model" in entry.data:
            new_data = {k: v for k, v in entry.data.items() if k != "model"}
            hass.config_entries.async_update_entry(
                entry, data=new_data, minor_version=2
            )
            _LOGGER.debug(
                "Blue Connect entry %s.%s migrated to 1.2: dropped stale 'model' field",
                entry.version,
                entry.minor_version,
            )
        else:
            hass.config_entries.async_update_entry(entry, minor_version=2)

    _LOGGER.debug(
        "Blue Connect entry %s.%s already up to date, no migration needed",
        entry.version,
        entry.minor_version,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    mac = entry.data[CONF_MAC_ADDRESS]
    safe_mac = format_mac_safe(mac)

    access_code = entry.options.get(
        CONF_ACCESS_CODE, entry.data.get(CONF_ACCESS_CODE, "")
    ).strip()

    coordinator = BlueConnectCoordinator(hass, entry, mac, safe_mac, access_code)
    await coordinator.async_initialize()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if ok:
        coordinator: BlueConnectCoordinator | None = hass.data[DOMAIN].get(
            entry.entry_id
        )
        if coordinator:
            await coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    mac = entry.data.get(CONF_MAC_ADDRESS)
    if mac:
        store = Store(hass, 1, store_key(mac))
        await store.async_remove()
