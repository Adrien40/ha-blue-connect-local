"""Coordinator edge cases: error paths, defensive branches and rarely-hit states.

The nominal behaviour lives in test_coordinator.py; this file pins down what
happens when things go wrong (BLE errors, signal changes, missing config
entry, odd stored data) so that none of these paths can silently regress.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.blue_connect_local.const import (
    BT_STATUS_OUT_OF_RANGE,
    BT_STATUS_WAITING,
    CONF_CHLORINE_MODEL,
    CONF_IGNORE_ECHOES,
    CONF_PASSIVE_MEASURES,
    DOMAIN,
    ERROR_RETRY_DELAY,
    REPAIR_STALE_AFTER,
)
from custom_components.blue_connect_local.coordinator import (
    _safely_disconnect,
    store_key,
)

from .conftest import make_entry
from .helpers import (
    MAC,
    UUID_ACCELEROMETER,
    UUID_HW_VERSION,
    UUID_SERIAL_NUMBER,
    UUID_SW_VERSION,
    FakeBlueClient,
    build_frame,
    clean_hex,
)

_COORDINATOR = "custom_components.blue_connect_local.coordinator"


def _seen(frame: bytes) -> SimpleNamespace:
    """Bluetooth advertisement carrying `frame`."""
    return SimpleNamespace(manufacturer_data={0x1234: frame}, service_data={})


def _stored(**data):
    return {"version": 1, "minor_version": 1, "key": store_key(MAC), "data": data}


# ---------------------------------------------------------------------------
# Errors while talking to the probe
# ---------------------------------------------------------------------------
async def test_disconnect_error_is_swallowed(caplog):
    client = FakeBlueClient()

    async def boom() -> None:
        raise OSError("link lost")

    client.disconnect = boom
    with caplog.at_level(logging.DEBUG):
        await _safely_disconnect(client)
    assert "Ignored error during disconnect" in caplog.text


async def test_stop_notify_error_does_not_fail_the_cycle(coordinator, ble, caplog):
    async def boom(_uuid: str) -> None:
        raise OSError("gone")

    ble.client.stop_notify = boom
    with caplog.at_level(logging.DEBUG):
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data["ph"] == pytest.approx(7.4)
    assert "Ignored error during stop_notify" in caplog.text


async def test_short_accelerometer_read_is_ignored(coordinator, ble):
    ble.client.reads[UUID_ACCELEROMETER] = b"\x00\x01"
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert "accelerometer" not in coordinator.data


@pytest.mark.parametrize(
    ("uuid", "key"),
    [
        (UUID_SERIAL_NUMBER, "serial_number"),
        (UUID_HW_VERSION, "sku"),
        (UUID_SW_VERSION, "cloud_id"),
    ],
)
async def test_blank_identity_read_is_not_stored(coordinator, ble, uuid, key):
    ble.client.reads[uuid] = b"\x00\x00"  # only NUL padding
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert key not in coordinator.data


async def test_empty_notification_is_retried_and_stale_frames_are_dropped(
    coordinator, ble
):
    """An empty payload is not a measurement: the 2nd attempt first drains what the
    1st one left in the queue, then asks again."""
    fresh = build_frame(ph=7.1)
    stale = build_frame(ph=5.0)
    ble.client.frames = [b"", stale, fresh]
    ble.client.frames_per_trigger = 2  # the 1st trigger delivers b"" and `stale`
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data["ph"] == pytest.approx(7.1)  # not the stale 5.0


async def test_rejected_code_without_config_entry_does_not_crash(
    hass, coordinator, ble
):
    ble.client.auth_ok = False
    original = hass.config_entries.async_get_entry
    hass.config_entries.async_get_entry = lambda _entry_id: None
    try:
        await coordinator.async_refresh()
    finally:
        hass.config_entries.async_get_entry = original
    assert coordinator.data["bluetooth_status"] == "auth_failed"


async def test_out_of_range_without_history_fails_the_update(coordinator, ble):
    coordinator._force_one_shot = False  # the startup analysis would bypass the check
    ble.scanner_count = 0
    await coordinator.async_refresh()
    assert not coordinator.last_update_success


async def test_update_returns_current_data_after_shutdown(coordinator):
    coordinator._is_shutdown = True
    try:
        assert await coordinator._async_update_data() is coordinator.data
    finally:
        coordinator._is_shutdown = False


async def test_retry_is_requested_when_its_timer_fires(hass, coordinator, ble):
    ble.client.write_errors = [OSError("gatt")] * 2
    await coordinator.async_refresh()
    assert coordinator.retry_count == 1
    coordinator.async_request_refresh = AsyncMock()
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=ERROR_RETRY_DELAY + 1)
    )
    await hass.async_block_till_done()
    coordinator.async_request_refresh.assert_awaited()


async def test_retry_timer_does_nothing_after_shutdown(hass, coordinator, ble):
    ble.client.write_errors = [OSError("gatt")] * 2
    await coordinator.async_refresh()
    coordinator.async_request_refresh = AsyncMock()
    coordinator._is_shutdown = True
    try:
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(seconds=ERROR_RETRY_DELAY + 1)
        )
        await hass.async_block_till_done()
    finally:
        coordinator._is_shutdown = False
    coordinator.async_request_refresh.assert_not_awaited()


# ---------------------------------------------------------------------------
# Signal availability
# ---------------------------------------------------------------------------
async def test_ble_is_unavailable_once_the_signal_was_lost(coordinator, ble):
    coordinator._ble_available = False
    assert coordinator.ble_available is False


async def test_signal_lost_cancels_a_pending_retry(coordinator):
    cancel = MagicMock()
    coordinator._retry_cancel = cancel
    coordinator.retry_count = 1
    coordinator._on_ble_unavailable(None)
    cancel.assert_called_once()
    assert coordinator._retry_cancel is None
    assert coordinator.retry_count == 0


async def test_signal_seen_recovers_from_a_stale_out_of_range_status(
    coordinator, caplog
):
    coordinator._ble_available = True  # signal never actually lost
    coordinator.data["bluetooth_status"] = BT_STATUS_OUT_OF_RANGE
    with caplog.at_level(logging.DEBUG):
        coordinator._on_ble_seen(
            SimpleNamespace(manufacturer_data={}, service_data={}), None
        )
    assert coordinator.data["bluetooth_status"] == BT_STATUS_WAITING
    assert "recovering from stale out_of_range" in caplog.text


async def test_startup_without_any_advertisement_starts_out_of_range(
    setup_integration, entry, ble
):
    ble.last_seen_age = None  # the probe was never seen
    coord = await setup_integration(entry)
    assert coord.data["bluetooth_status"] == BT_STATUS_OUT_OF_RANGE


# ---------------------------------------------------------------------------
# Passive advertisements
# ---------------------------------------------------------------------------
async def test_passive_options_present_in_data_take_precedence(coordinator):
    coordinator.update_volatile_state(
        {CONF_PASSIVE_MEASURES: True, CONF_IGNORE_ECHOES: True}
    )
    coordinator._on_ble_seen(_seen(build_frame(ph=7.4)), None)
    coordinator._on_ble_seen(_seen(build_frame(ph=6.0, echo=True)), None)
    assert coordinator.data["ph"] == pytest.approx(7.4)  # echo ignored
    assert coordinator.data["receive_method"] == "passive"


async def test_unparsable_passive_frame_is_dropped(coordinator):
    with patch(f"{_COORDINATOR}.parse_raw_frame", return_value=None):
        coordinator._on_ble_seen(_seen(build_frame()), None)
    assert coordinator.data.get("ph") is None


async def test_passive_frame_without_config_entry_is_not_processed(hass, coordinator):
    original = hass.config_entries.async_get_entry
    hass.config_entries.async_get_entry = lambda _entry_id: None
    try:
        coordinator._on_ble_seen(_seen(build_frame()), None)
    finally:
        hass.config_entries.async_get_entry = original
    assert coordinator.data.get("ph") is None


# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("args", "status"),
    [
        ((25, 6.6, 40, 60, 500), "corrosive"),  # LSI < -0.3
        ((25, 7.4, 100, 250, 1000), "balanced"),
        ((25, 8.2, 200, 400, 1000), "scaling"),  # LSI > +0.3
        ((25, 7.4, 100, 250, 0), "unknown"),  # TDS missing: no index
    ],
)
async def test_langelier_status_bands(coordinator, args, status):
    temp, ph, tac, th, tds = args
    updates = coordinator._build_chemistry_updates(
        temp, ph, None, tac, th, tds, 40.0, "chlorine"
    )
    assert updates["lsi_status"] == status


async def test_recompute_uses_the_chlorine_model_kept_in_data(coordinator):
    coordinator._on_ble_seen(_seen(build_frame()), None)
    coordinator.update_volatile_state({CONF_CHLORINE_MODEL: "bromine"})
    coordinator.recompute_derived_values()  # must not fall back to the entry option
    assert coordinator.data[CONF_CHLORINE_MODEL] == "bromine"


async def test_recompute_without_changes_publishes_nothing(coordinator):
    coordinator._on_ble_seen(_seen(build_frame()), None)
    coordinator.recompute_derived_values()  # settle
    with patch.object(coordinator, "update_volatile_state") as publish:
        coordinator.recompute_derived_values()
    publish.assert_not_called()


async def test_recompute_without_data_does_nothing(coordinator):
    saved = coordinator.data
    coordinator.data = {}
    try:
        with patch.object(coordinator, "_apply_new_measurements") as apply:
            coordinator.recompute_derived_values()
        apply.assert_not_called()
    finally:
        coordinator.data = saved


async def test_deferred_recompute_without_data_does_nothing(hass, coordinator):
    saved = coordinator.data
    coordinator.data = {}
    try:
        with patch.object(coordinator, "recompute_derived_values") as recompute:
            coordinator.request_deferred_recompute()
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
            await hass.async_block_till_done()
        recompute.assert_not_called()
    finally:
        coordinator.data = saved


async def test_recompute_and_apply_without_config_entry_do_nothing(hass, coordinator):
    coordinator._on_ble_seen(_seen(build_frame()), None)
    original = hass.config_entries.async_get_entry
    hass.config_entries.async_get_entry = lambda _entry_id: None
    try:
        with patch.object(coordinator, "update_volatile_state") as publish:
            coordinator.recompute_derived_values()
        publish.assert_not_called()
        parsed = {"temp_raw": 25.0, "ph_raw": 7.0, "orp_raw": 700}
        assert coordinator._apply_new_measurements(parsed, "AA") is coordinator.data
    finally:
        hass.config_entries.async_get_entry = original


# ---------------------------------------------------------------------------
# Devices seen for a long time / no access code
# ---------------------------------------------------------------------------
async def test_no_access_code_polls_hourly_once_data_was_received(setup_integration):
    coord = await setup_integration(make_entry(access_code=None))
    coord.data["last_received"] = dt_util.utcnow()
    coord.update_schedule()
    assert coord.update_interval == timedelta(minutes=60)
    assert coord.next_slot is None


async def test_user_disabled_conductivity_entity_is_left_alone(hass, coordinator):
    reg = er.async_get(hass)
    conductivity = reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_conductivity")
    reg.async_update_entity(conductivity, disabled_by=er.RegistryEntryDisabler.USER)
    coordinator._on_ble_seen(_seen(build_frame(conductivity=None)), None)
    assert reg.async_get(conductivity).disabled_by is er.RegistryEntryDisabler.USER
    salinity = reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_salinity")
    assert reg.async_get(salinity).disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_stale_issue_needs_a_reception_time(hass, coordinator):
    coordinator.data["last_received"] = None
    coordinator._check_stale_issue()
    assert ir.async_get(hass).async_get_issue(DOMAIN, coordinator._issue_id()) is None


async def test_stale_issue_handles_a_naive_timestamp(hass, coordinator):
    # A naive timestamp is read as local time (dt_util.as_utc semantics).
    old = dt_util.now() - REPAIR_STALE_AFTER - timedelta(hours=1)
    coordinator.data["last_received"] = old.replace(tzinfo=None)
    coordinator._check_stale_issue()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, coordinator._issue_id()) is not None
    )


# ---------------------------------------------------------------------------
# Persistence and lifecycle
# ---------------------------------------------------------------------------
async def test_schedule_save_is_ignored_after_shutdown(coordinator):
    coordinator._is_shutdown = True
    try:
        coordinator._schedule_save()
        assert coordinator._save_cancel is None
    finally:
        coordinator._is_shutdown = False


async def test_debounced_save_writes_to_storage(
    hass, coordinator, hass_storage, monkeypatch
):
    monkeypatch.setattr(f"{_COORDINATOR}.SAVE_DEBOUNCE_DELAY", 0.0)
    coordinator._on_ble_seen(_seen(build_frame(ph=7.1)), None)  # -> _schedule_save
    for _ in range(20):
        await hass.async_block_till_done(wait_background_tasks=True)
        if store_key(MAC) in hass_storage:
            break
        await __import__("asyncio").sleep(0.01)
    assert hass_storage[store_key(MAC)]["data"]["ph"] == pytest.approx(7.1)


async def test_restore_without_reception_time_keeps_measurements(
    setup_integration, hass_storage
):
    hass_storage[store_key(MAC)] = _stored(raw_frame=clean_hex(build_frame()), ph=7.1)
    coord = await setup_integration(make_entry())
    assert coord.data["ph"] == 7.1
    assert "last_received" not in coord.data


async def test_restore_of_transient_state_only_adds_nothing(
    setup_integration, hass_storage
):
    hass_storage[store_key(MAC)] = _stored(
        bluetooth_status="success", action_running=True
    )
    coord = await setup_integration(make_entry())
    assert coord.data.get("bluetooth_status") != "success"
    assert not coord.data.get("action_running")


async def test_first_analysis_timer_does_nothing_after_shutdown(
    hass, setup_integration, entry, ble, monkeypatch
):
    monkeypatch.setattr(f"{_COORDINATOR}.FIRST_ANALYSIS_DELAY", 1.0)
    coord = await setup_integration(entry)
    coord._is_shutdown = True  # timer still armed: flag set without cancelling
    try:
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
        await hass.async_block_till_done()
    finally:
        coord._is_shutdown = False
    ble.establish.assert_not_called()
