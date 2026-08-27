# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import CONF_ACCESS_CODE, CONF_MAC_ADDRESS, DOMAIN, PLATFORMS
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
        # setup from the live SKU instead - drop the stale field so it
        # can no longer shadow that.
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

    if entry.minor_version < 3:
        # 1.0.3 -> 1.1.0 moved the Serial Number and HW Version (SKU) from
        # standalone sensors into the device header (see const.py's
        # blue_connect_device_info). Their old unique_ids
        # ("{mac}_serial_number" / "{mac}_hw_version") are no longer
        # produced by any platform, so they'd otherwise be stuck forever
        # as orphaned, disabled-looking entities in the registry.
        registry = er.async_get(hass)
        mac = entry.data.get(CONF_MAC_ADDRESS, "")
        stale_unique_ids = (f"{mac}_serial_number", f"{mac}_hw_version")
        removed = 0
        for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if reg_entry.unique_id in stale_unique_ids:
                registry.async_remove(reg_entry.entity_id)
                removed += 1
        if removed:
            _LOGGER.info(
                "Blue Connect entry %s.%s: removed %d orphaned entities "
                "(Serial Number / HW Version, now shown in the device header)",
                entry.version,
                entry.minor_version,
                removed,
            )
        hass.config_entries.async_update_entry(entry, minor_version=3)

    if entry.minor_version < 4:
        # The "sw_version" sensor never actually reported a firmware
        # version - it's the device's Cloud ID / serial-like identifier
        # read from UUID_SW_VERSION (a GATT characteristic name, not a
        # description of the value). Renamed to "cloud_id" for clarity.
        # Unlike the 1.1.0 cleanup above, this entity is still produced
        # today, so its unique_id is migrated in place rather than
        # dropped - this preserves entity history, dashboards, and
        # automations built on the existing entity_id.
        registry = er.async_get(hass)
        mac = entry.data.get(CONF_MAC_ADDRESS, "")
        old_unique_id = f"{mac}_sw_version"
        new_unique_id = f"{mac}_cloud_id"
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, old_unique_id)
        if entity_id:
            registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
            _LOGGER.info(
                "Blue Connect entry %s.%s: migrated sw_version -> cloud_id unique_id",
                entry.version,
                entry.minor_version,
            )
        hass.config_entries.async_update_entry(entry, minor_version=4)

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
