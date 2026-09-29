# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant

from . import BlueConnectConfigEntry
from .const import CONF_ACCESS_CODE, CONF_MAC_ADDRESS

# The title embeds the BLE name (model + end of the MAC), and serial_number /
# cloud_id identify one specific probe: none of them must end up in a public
# issue. `sku` stays visible: it is useful for support and not identifying.
TO_REDACT = {CONF_MAC_ADDRESS, CONF_ACCESS_CODE, "serial_number", "cloud_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BlueConnectConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    # The number/time/switch entities store the value actually in use in the
    # coordinator, not in entry.options, which keeps the value saved the last
    # time the Configure form was submitted. Reporting the stored options
    # as-is would show settings that are no longer applied, so overlay the
    # values currently in use.
    options_in_use = {
        key: coordinator.data.get(key, value) for key, value in entry.options.items()
    }

    return {
        "entry": {
            "title": REDACTED,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(options_in_use, TO_REDACT),
            "options_note": (
                "Stored options overlaid with the values currently in use "
                "(changing a value from an entity does not rewrite the stored "
                "options)."
            ),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "ble_available": coordinator.ble_available,
            "retry_count": coordinator.retry_count,
            "update_interval": str(coordinator.update_interval),
            "next_slot": str(coordinator.next_slot) if coordinator.next_slot else None,
            "data": async_redact_data(dict(coordinator.data), TO_REDACT),
        },
    }
