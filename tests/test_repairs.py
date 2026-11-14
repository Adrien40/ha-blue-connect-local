"""Repair issue: created when unreachable for too long, cleared on recovery."""

from __future__ import annotations

from datetime import timedelta

import homeassistant.util.dt as dt_util
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blue_connect_local.const import DOMAIN, mac_short_id
from custom_components.blue_connect_local.coordinator import find_device

from .helpers import MAC, build_frame


async def test_stale_device_creates_repair_issue(hass, coordinator, ble):
    await coordinator.async_refresh()  # consume the default first-analysis flag
    coordinator.update_volatile_state(
        {"last_received": dt_util.utcnow() - timedelta(days=5)}
    )
    ble.last_seen_age = 999
    await coordinator.async_refresh()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"stale_{coordinator.entry_id}")
    assert issue is not None


async def test_recovered_device_clears_repair_issue(hass, coordinator, ble):
    await coordinator.async_refresh()  # consume the default first-analysis flag
    coordinator.update_volatile_state(
        {"last_received": dt_util.utcnow() - timedelta(days=5)}
    )
    ble.last_seen_age = 999
    await coordinator.async_refresh()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"stale_{coordinator.entry_id}")
        is not None
    )

    ble.last_seen_age = 0.0
    ble.client.frames = [build_frame(battery_adc=4001)]
    await coordinator.async_refresh()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"stale_{coordinator.entry_id}")
    assert issue is None


async def test_recent_unavailability_does_not_create_issue(coordinator, ble, hass):
    ble.last_seen_age = 999
    await coordinator.async_refresh()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"stale_{coordinator.entry_id}")
    assert issue is None


async def _make_stale(coordinator, ble):
    await coordinator.async_refresh()  # consume the default first-analysis flag
    coordinator.update_volatile_state(
        {"last_received": dt_util.utcnow() - timedelta(days=5)}
    )
    ble.last_seen_age = 999
    await coordinator.async_refresh()


async def test_repair_shows_the_short_id_not_a_masked_address(hass, coordinator, ble):
    await _make_stale(coordinator, ble)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"stale_{coordinator.entry_id}")
    assert issue.translation_placeholders["name"] == coordinator.display_label
    assert "XX" not in issue.translation_placeholders["name"]


async def test_repair_shows_the_name_the_user_gave_the_device(hass, coordinator, ble):
    registry = dr.async_get(hass)
    device = find_device(registry, (DOMAIN, MAC), coordinator.entry_id)
    registry.async_update_device(device.id, name_by_user="Piscine")

    await _make_stale(coordinator, ble)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"stale_{coordinator.entry_id}")
    assert issue.translation_placeholders["name"] == "Piscine"


async def test_label_is_the_model_by_default(hass, coordinator):
    device = find_device(dr.async_get(hass), (DOMAIN, MAC), coordinator.entry_id)
    assert device.model
    assert coordinator.display_label == device.model


async def test_label_shows_the_user_name_as_is(hass, coordinator):
    registry = dr.async_get(hass)
    device = find_device(registry, (DOMAIN, MAC), coordinator.entry_id)
    registry.async_update_device(device.id, name_by_user="Blue Connect Gold")
    assert coordinator.display_label == "Blue Connect Gold"


async def test_label_tells_probes_apart_when_there_are_several(hass, coordinator):
    MockConfigEntry(domain=DOMAIN, unique_id="11:22:33:44:55:66").add_to_hass(hass)
    assert coordinator.display_label.endswith(f" {mac_short_id(MAC)}")


def test_label_without_a_device_is_generic(coordinator, monkeypatch):
    monkeypatch.setattr(coordinator, "mac", "")
    assert coordinator.display_label == "Blue Connect"
