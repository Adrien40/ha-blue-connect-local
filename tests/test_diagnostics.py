"""diagnostics.py: presence of expected data; MAC, access code, serial, cloud ID and title redacted."""

from __future__ import annotations

from custom_components.blue_connect_local.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import ACCESS_CODE, MAC


async def test_diagnostics_redacts_sensitive_data(hass, coordinator, entry):
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["entry"]["data"]["mac_address"] == "**REDACTED**"
    assert MAC not in str(result)
    assert ACCESS_CODE not in str(result)


async def test_diagnostics_includes_coordinator_state(hass, coordinator, entry):
    await coordinator.async_refresh()
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator"]["last_update_success"] is True
    assert "ph" in result["coordinator"]["data"]
    assert result["entry"]["version"] == entry.version


async def test_diagnostics_redacts_device_identifiers(hass, coordinator, entry):
    """Serial number, cloud ID and title are redacted; the SKU stays visible."""
    coordinator.data["serial_number"] = "SN1234567"
    coordinator.data["cloud_id"] = "CLOUD-ABC-123"
    coordinator.data["sku"] = "WA000100"
    hass.config_entries.async_update_entry(entry, title="Blue Connect (BC3-EEFF)")

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "SN1234567" not in str(result)
    assert "CLOUD-ABC-123" not in str(result)
    assert "EEFF" not in str(result)
    assert result["entry"]["title"] == "**REDACTED**"
    assert result["coordinator"]["data"]["sku"] == "WA000100"


async def test_diagnostics_options_show_values_in_use(hass, coordinator, entry):
    """Options changed from an entity are reported, not the stale stored ones."""
    hass.config_entries.async_update_entry(
        entry, options={"scan_interval": 22, "cya": 22, "ph_min": 6.9}
    )
    coordinator.data["scan_interval"] = 60
    coordinator.data["cya"] = 30

    result = await async_get_config_entry_diagnostics(hass, entry)

    options = result["entry"]["options"]
    assert options["scan_interval"] == 60
    assert options["cya"] == 30
    assert options["ph_min"] == 6.9  # no coordinator value: stored one kept
    assert "options_note" in result["entry"]
