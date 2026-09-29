"""Setup, unload, removal, and the 1.1 -> 1.4 migration chain."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.blue_connect_local import (
    async_migrate_entry,
    async_remove_entry,
    async_unload_entry,
)
from custom_components.blue_connect_local.const import (
    CONF_CHLORINE_MODEL,
    CONF_CYA,
    CONF_MAC_ADDRESS,
    DOMAIN,
    PLATFORMS,
)
from custom_components.blue_connect_local.coordinator import store_key

from .conftest import make_entry
from .helpers import MAC

EXPECTED_ENTITIES = {
    ("binary_sensor", "ph_status"),
    ("binary_sensor", "orp_status"),
    ("binary_sensor", "temperature_status"),
    ("button", "force_analysis"),
    ("number", "cya"),
    ("number", "scan_interval"),
    ("number", "tac"),
    ("number", "th"),
    ("number", "tds"),
    ("switch", "active_measures"),
    ("switch", "passive_measures"),
    ("time", "reference_time"),
    *{
        ("sensor", key)
        for key in (
            "accelerometer",
            "battery",
            "battery_adc",
            "battery_level",
            "bluetooth_status",
            "cloud_id",
            "conductivity",
            "float_status",
            "last_received",
            "lsi",
            "lsi_status",
            "next_analysis",
            "orp",
            "orp_raw",
            "ph",
            "ph_raw",
            "raw_frame",
            "raw_frame_0005",
            "receive_method",
            "rssi",
            "salinity",
            "target_equilibrium_ph",
            "temperature",
        )
    },
}


def test_platforms():
    assert set(PLATFORMS) == {
        "sensor",
        "binary_sensor",
        "button",
        "number",
        "switch",
        "time",
    }


async def test_setup_creates_the_expected_entities(hass, entry, coordinator):
    registered = {
        (e.domain, e.unique_id.removeprefix(f"{MAC}_"))
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    assert registered == EXPECTED_ENTITIES


async def test_entry_loaded_and_coordinator_registered(hass, entry, coordinator):
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is coordinator


async def test_unload(hass, entry, coordinator):
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert coordinator.is_shutdown is True


async def test_unload_saves_to_disk(hass, entry, coordinator, hass_storage):
    await coordinator.async_refresh()
    await hass.config_entries.async_unload(entry.entry_id)
    assert hass_storage[store_key(MAC)]["data"]["ph_raw"] == pytest.approx(7.4)


async def test_remove_entry_deletes_stored_data(hass, entry, coordinator, hass_storage):
    await coordinator.async_save_to_disk()
    assert store_key(MAC) in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert store_key(MAC) not in hass_storage


async def test_migrate_entry_rejects_future_major_version(hass):
    """Called directly: Home Assistant's own core intercepts this case first
    in the normal setup flow, so the integration's own guard is never
    reached via `hass.config_entries.async_setup`."""
    entry = make_entry(version=2)
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry) is False


async def test_unload_entry_skips_shutdown_when_platforms_fail(
    hass, coordinator, entry
):
    """If unloading the platforms fails, the coordinator must not be shut down."""
    original_unload_platforms = hass.config_entries.async_unload_platforms
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
    try:
        assert await async_unload_entry(hass, entry) is False
        assert coordinator.is_shutdown is False
    finally:
        # Restore before returning: the `coordinator` fixture's teardown
        # calls the real `hass.config_entries.async_unload(...)` right
        # after this test function returns, and that goes through this
        # same method to actually unload the platforms and shut the
        # coordinator down cleanly.
        hass.config_entries.async_unload_platforms = original_unload_platforms


async def test_unload_entry_noop_without_coordinator(hass):
    """Guards against a stale/duplicate unload before setup ever ran."""
    entry = make_entry()
    entry.add_to_hass(hass)
    entry.runtime_data = None
    assert await async_unload_entry(hass, entry) is True


async def test_remove_entry_without_mac_is_a_noop(hass):
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={k: v for k, v in entry.data.items() if k != CONF_MAC_ADDRESS}
    )
    await async_remove_entry(hass, entry)  # must not raise


async def test_reload_works(hass, entry, coordinator):
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED


async def test_passive_only_setup(hass, setup_integration):
    entry = make_entry(access_code=None)
    await setup_integration(entry)
    assert entry.state is ConfigEntryState.LOADED


# ---------------------------------------------------------------------------
# Migration chain
# ---------------------------------------------------------------------------
async def test_migration_1_1_drops_stale_model_field(hass, setup_integration):
    entry = make_entry(minor_version=1)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "model": "Guess"})
    await setup_integration(entry)
    assert "model" not in entry.data
    assert entry.data[CONF_MAC_ADDRESS] == MAC
    assert entry.minor_version == 4


async def test_migration_removes_orphaned_serial_and_hw_version(
    hass, setup_integration
):
    entry = make_entry(minor_version=2)
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    for key in ("serial_number", "hw_version", "ph"):
        reg.async_get_or_create("sensor", DOMAIN, f"{MAC}_{key}", config_entry=entry)
    await setup_integration(entry)
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_serial_number") is None
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_hw_version") is None
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_ph") is not None  # kept


async def test_migration_renames_sw_version_in_place(hass, setup_integration):
    """The entity is renamed (unique_id) without losing its entity_id or history."""
    entry = make_entry(minor_version=3)
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    old = reg.async_get_or_create(
        "sensor", DOMAIN, f"{MAC}_sw_version", config_entry=entry
    )
    await setup_integration(entry)
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_sw_version") is None
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_cloud_id") == old.entity_id


async def test_migration_keeps_cya_and_chlorine_model(setup_integration):
    entry = make_entry(
        minor_version=1, **{CONF_CYA: 60, CONF_CHLORINE_MODEL: "bromine"}
    )
    await setup_integration(entry)
    assert entry.options[CONF_CYA] == 60
    assert entry.options[CONF_CHLORINE_MODEL] == "bromine"


async def test_current_version_entry_is_untouched(hass, setup_integration):
    entry = make_entry(minor_version=4)
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "sensor", DOMAIN, f"{MAC}_serial_number", config_entry=entry
    )
    await setup_integration(entry)
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_serial_number") is not None


async def test_future_major_version_is_refused(hass, enable_bluetooth, ble):
    entry = make_entry(version=2)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_same_major_newer_minor_still_loads(setup_integration):
    entry = make_entry(minor_version=9)
    await setup_integration(entry)
    assert entry.state is ConfigEntryState.LOADED
