"""Coordinator: active cycle (GATT), passive mode (adverts), persistence."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blue_connect_local.const import (
    BT_STATUS_AUTH_FAILED,
    BT_STATUS_ERROR,
    BT_STATUS_ERROR_RETRY,
    BT_STATUS_OUT_OF_RANGE,
    BT_STATUS_PAUSED,
    BT_STATUS_SUCCESS,
    BT_STATUS_WAITING,
    BT_STATUS_WRITE_FAILED,
    CHAR_AUTH_UUID,
    CHAR_TRIGGER_UUID,
    CONF_ACCESS_CODE,
    CONF_IGNORE_ECHOES,
    CONF_MAC_ADDRESS,
    CONF_ORP_CALIB,
    CONF_ORP_REF,
    CONF_PASSIVE_MEASURES,
    CONF_PH_CALIB_4,
    CONF_PH_CALIB_7,
    CONF_REFERENCE_TIME,
    CONF_SCAN_INTERVAL,
    CONF_TAC,
    CONF_TDS,
    CONF_TEMP_OFFSET,
    CONF_TH,
    DOMAIN,
)
from custom_components.blue_connect_local.coordinator import (
    _get_opt,
    find_device,
    format_mac_safe,
    store_key,
)

from .conftest import make_entry
from .helpers import (
    ACCESS_CODE,
    MAC,
    FakeBlueClient,
    build_frame,
    clean_hex,
)


def _seen(frame: bytes, *, service: bool = False) -> SimpleNamespace:
    """Bluetooth advertisement carrying `frame` (manufacturer or service data)."""
    if service:
        return SimpleNamespace(manufacturer_data={}, service_data={"uuid": frame})
    return SimpleNamespace(manufacturer_data={0x1234: frame}, service_data={})


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def test_store_key_is_normalized():
    assert store_key("AA:BB:CC:DD:EE:FF") == "blue_connect_local_aabbccddeeff"


@pytest.mark.parametrize("mac", [None, "", "AA:BB", "short"])
def test_format_mac_safe_hides_invalid(mac):
    assert format_mac_safe(mac) == "XX:XX:XX:XX:XX:XX"


def test_format_mac_safe_masks_device_part():
    assert format_mac_safe("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:XX:XX:XX"


# ---------------------------------------------------------------------------
# Nominal active cycle
# ---------------------------------------------------------------------------
async def test_active_cycle_populates_data(coordinator):
    await coordinator.async_refresh()
    d = coordinator.data
    assert d["bluetooth_status"] == BT_STATUS_SUCCESS
    assert d["receive_method"] == "active"
    assert d["temperature"] == pytest.approx(25.02)
    assert d["ph"] == pytest.approx(7.4)
    assert d["orp"] == 700
    assert d["conductivity"] == 1200
    assert d["salinity"] == pytest.approx(3.5)
    assert d["has_conductivity"] is True
    assert d["battery_level"] == 80
    assert d["battery"] == int(4000 * 0.8791)
    assert d["raw_frame"] == clean_hex(build_frame())
    # Additional GATT reads
    assert d["raw_frame_0005"] == "0102030405"
    assert d["accelerometer"] == "X: 0 | Y: 900 | Z: 0"
    assert d["float_status"] == "vertical"
    assert d["serial_number"] == "SN12345"
    assert d["sku"] == "WA000100"
    assert d["cloud_id"] == "CLOUD42"


async def test_active_cycle_authenticates_then_triggers(coordinator, ble):
    await coordinator.async_refresh()
    assert ble.client.writes[0] == (CHAR_AUTH_UUID, ACCESS_CODE.encode("ascii"))
    assert ble.client.writes[1] == (CHAR_TRIGGER_UUID, b"\x02")
    assert ble.client.notify_started
    assert ble.client.notify_stopped
    assert ble.client.disconnected


async def test_no_chlorine_values_are_computed(coordinator):
    await coordinator.async_refresh()
    assert not any("chlorine" in k or "hocl" in k for k in coordinator.data)


@pytest.mark.parametrize(
    ("tilt", "expected"),
    [
        ((0, 900, 0), "vertical"),
        ((0, -900, 0), "upside_down"),
        ((900, 0, 0), "horizontal"),
        ((0, 0, -900), "horizontal"),
        ((100, 100, 100), "tilted"),
    ],
)
async def test_float_orientation(coordinator, ble, tilt, expected):
    x, y, z = tilt
    ble.client.reads["70ea000a-7a29-4fdf-93d2-838665e72677"] = b"".join(
        v.to_bytes(2, "big", signed=True) for v in (x, y, z)
    )
    await coordinator.async_refresh()
    assert coordinator.data["float_status"] == expected


async def test_optional_reads_may_fail_without_failing_the_cycle(coordinator, ble):
    ble.client.reads.clear()  # no additional characteristic readable
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_SUCCESS
    assert "serial_number" not in coordinator.data


async def test_device_identity_is_read_only_once(coordinator, ble):
    await coordinator.async_refresh()
    ble.client.reads["70ea0020-7a29-4fdf-93d2-838665e72677"] = b"OTHER\x00"
    ble.client.frames = [build_frame(ph=7.5)]
    await coordinator.async_refresh()
    assert coordinator.data["serial_number"] == "SN12345"  # unchanged


async def test_device_registry_gets_model_and_serial(hass, coordinator):
    await coordinator.async_refresh()
    device = find_device(
        dr.async_get(hass), ("blue_connect_local", MAC), coordinator.entry_id
    )
    assert device.model == "Blue Connect Gold"
    assert device.model_id == "WA000100"
    assert device.serial_number == "SN12345"


# ---------------------------------------------------------------------------
# Calibration, offsets, Langelier
# ---------------------------------------------------------------------------
async def test_calibration_and_offsets_are_applied(setup_integration, ble):
    ble.client = FakeBlueClient([build_frame(temp_c=25.0, ph=7.4, orp_mv=700)])
    coord = await setup_integration(
        make_entry(
            **{
                CONF_PH_CALIB_4: 4.1,
                CONF_PH_CALIB_7: 6.9,  # probe drift
                CONF_TEMP_OFFSET: 1.5,
                CONF_ORP_REF: 650,
                CONF_ORP_CALIB: 640,
            }
        )
    )
    await coord.async_refresh()
    assert coord.data["ph"] == pytest.approx(7.54, abs=0.01)
    assert coord.data["temperature"] == pytest.approx(26.5)
    assert coord.data["orp"] == 710
    # Raw values stay intact (to recompute without a new measurement).
    assert coord.data["ph_raw"] == pytest.approx(7.4)
    assert coord.data["orp_raw"] == 700


async def test_degenerate_calibration_falls_back_to_raw_ph(setup_integration, ble):
    ble.client = FakeBlueClient([build_frame(temp_c=25.0, ph=7.4, orp_mv=700)])
    coord = await setup_integration(
        make_entry(
            **{
                CONF_PH_CALIB_4: 5.0,
                CONF_PH_CALIB_7: 5.005,  # calibration points nearly identical
            }
        )
    )
    await coord.async_refresh()
    # Degenerate calibration: falls back to raw pH rather than crashing
    # or silently returning an irrelevant value.
    assert coord.data["ph"] == pytest.approx(7.4)
    assert coord.data["ph_raw"] == pytest.approx(7.4)


async def test_notification_queue_full_is_logged(setup_integration, ble, caplog):
    # 6 distinct frames delivered at once by the same trigger: the queue
    # (maxsize=4) is bound to overflow, which must now be logged (not silent).
    frames = [build_frame(battery_adc=4000 + i) for i in range(6)]
    ble.client = FakeBlueClient(frames=frames, frames_per_trigger=6)
    coord = await setup_integration(make_entry())
    with caplog.at_level(logging.DEBUG):
        await coord.async_refresh()
    assert "Notification queue full" in caplog.text
    # The cycle still succeeds: the last frames of the burst are enough.
    assert coord.data["bluetooth_status"] == BT_STATUS_SUCCESS


async def test_langelier_follows_water_parameters(coordinator):
    await coordinator.async_refresh()
    assert coordinator.data["lsi"] is None
    assert coordinator.data["lsi_status"] == "unknown"
    coordinator.update_local_state({CONF_TAC: 100, CONF_TH: 200, CONF_TDS: 1000})
    coordinator.recompute_derived_values()
    assert coordinator.data["lsi"] is not None
    assert coordinator.data["lsi_status"] in {"corrosive", "balanced", "scaling"}
    assert coordinator.data["target_equilibrium_ph"] is not None


async def test_recompute_keeps_receive_method(coordinator):
    await coordinator.async_refresh()
    coordinator.update_local_state({CONF_TAC: 100, CONF_TH: 200, CONF_TDS: 1000})
    coordinator.recompute_derived_values()
    assert coordinator.data["receive_method"] == "active"
    assert coordinator.data["bluetooth_status"] == BT_STATUS_SUCCESS


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
async def test_rejected_access_code(hass, coordinator, ble):
    ble.client.auth_ok = False
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_AUTH_FAILED
    assert coordinator.last_update_success is False  # no history

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    reauth_flows = [f for f in flows if f["context"]["source"] == SOURCE_REAUTH]
    assert len(reauth_flows) == 1
    assert not [w for w in ble.client.writes if w[0] == CHAR_TRIGGER_UUID]


async def test_rejected_access_code_keeps_history(coordinator, ble):
    await coordinator.async_refresh()
    ble.client.auth_ok = False
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_AUTH_FAILED
    assert coordinator.data["ph"] == pytest.approx(7.4)
    assert coordinator.last_update_success


async def test_unreadable_auth_status_falls_back_to_notification(coordinator, ble):
    ble.client.auth_ok = None
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_SUCCESS


# ---------------------------------------------------------------------------
# BLE errors and retries
# ---------------------------------------------------------------------------
async def test_write_failure_then_success(coordinator, ble):
    ble.client.write_errors = [OSError("gatt"), None, None]
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_SUCCESS


async def test_write_failure_on_both_attempts_schedules_retry(coordinator, ble):
    ble.client.write_errors = [OSError("gatt")] * 2
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_ERROR_RETRY
    assert coordinator.retry_count == 1
    assert coordinator._retry_cancel is not None
    assert ble.client.disconnected


async def test_write_failed_status_once_retries_are_exhausted(coordinator, ble):
    await coordinator.async_refresh()  # history
    coordinator.retry_count = 2
    ble.client.write_errors = [OSError("gatt")] * 2
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_WRITE_FAILED


async def test_no_notification_is_an_error(coordinator, ble):
    ble.client.frames = []
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_ERROR_RETRY


async def test_invalid_payload_retry_budget_runs_out(coordinator, ble):
    """Regression: retry_count was reset to 0 before decoding, so an invalid
    frame relaunched "retry" indefinitely without ever giving up."""
    ble.client.frames = [b"\x00" * 5 for _ in range(3)]
    statuses = []
    for _ in range(3):
        await coordinator.async_refresh()
        statuses.append(coordinator.data["bluetooth_status"])
    assert statuses == [BT_STATUS_ERROR_RETRY, BT_STATUS_ERROR_RETRY, BT_STATUS_ERROR]
    assert coordinator.retry_count == 0
    assert coordinator.last_update_success is False  # no history


async def test_invalid_payload_keeps_history(coordinator, ble):
    await coordinator.async_refresh()
    ble.client.frames = [b"\x00" * 5 for _ in range(3)]
    for _ in range(3):
        await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_ERROR
    assert coordinator.data["ph"] == pytest.approx(7.4)
    assert coordinator.last_update_success


async def test_connection_error_is_contained(coordinator, ble):
    ble.establish.side_effect = OSError("connection refused")
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_ERROR_RETRY


async def test_device_missing_from_cache(coordinator, ble):
    ble.device_present = False
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_OUT_OF_RANGE
    assert coordinator.last_update_success is False


async def test_falls_back_to_non_connectable_device(coordinator, ble):
    # Device only found via connectable=False (e.g. seen by a scanner that
    # cannot connect to it directly): must not be treated as missing.
    ble.device_requires_non_connectable = True
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_SUCCESS


@pytest.mark.parametrize(
    "condition",
    [{"scanner_count": 0}, {"last_seen_age": 500}, {"last_seen_age": None}],
)
async def test_unavailable_bluetooth_does_not_connect(coordinator, ble, condition):
    await coordinator.async_refresh()
    ble.establish.reset_mock()
    for attr, value in condition.items():
        setattr(ble, attr, value)
    await coordinator.async_refresh()
    ble.establish.assert_not_called()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_OUT_OF_RANGE
    assert coordinator.data["ph"] is not None  # history kept


async def test_unavailable_bluetooth_is_logged(coordinator, ble, caplog):
    await coordinator.async_refresh()
    ble.last_seen_age = 500
    with caplog.at_level(logging.DEBUG):
        await coordinator.async_refresh()
    assert "Bluetooth signal unavailable" in caplog.text


async def test_forced_analysis_bypasses_stale_advertisement_check(coordinator, ble):
    ble.last_seen_age = 500
    coordinator.request_one_shot_analysis()
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_SUCCESS


# ---------------------------------------------------------------------------
# Pause, forced analysis, no access code, shutdown
# ---------------------------------------------------------------------------
async def test_paused_measurements_skip_connection(coordinator, ble):
    coordinator._force_one_shot = False  # the startup analysis is forced
    coordinator.update_volatile_state({"active_measures": False})
    await coordinator.async_refresh()
    ble.establish.assert_not_called()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_PAUSED


async def test_one_shot_works_while_paused_then_flag_is_consumed(coordinator, ble):
    coordinator._force_one_shot = False
    coordinator.update_volatile_state({"active_measures": False})
    coordinator.request_one_shot_analysis()
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_SUCCESS
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_PAUSED


async def test_no_access_code_means_passive_only(setup_integration, ble):
    coord = await setup_integration(make_entry(access_code=None))
    await coord.async_refresh()
    ble.establish.assert_not_called()
    assert coord.data["bluetooth_status"] == "passive_mode"
    coord.request_one_shot_analysis()
    assert coord._force_one_shot is False  # no code, no active analysis


async def test_no_connection_after_shutdown(coordinator, ble):
    await coordinator.async_shutdown()
    await coordinator.async_refresh()
    ble.establish.assert_not_called()


async def test_shutdown_is_idempotent_and_cancels_timers(coordinator, ble):
    ble.client.frames = [b"\x00" * 5]
    await coordinator.async_refresh()  # schedules a retry in 60 s
    assert coordinator._retry_cancel is not None
    await coordinator.async_shutdown()
    await coordinator.async_shutdown()  # 2nd call (HA + async_unload_entry): no error
    assert coordinator._retry_cancel is None
    assert coordinator._ble_unavail_cancel is None
    assert coordinator._save_cancel is None


async def test_first_analysis_timer_is_cancelled_on_unload(
    hass, setup_integration, entry, ble
):
    """The 1st analysis (2 s) is scheduled at startup: unloading must cancel it,
    otherwise a timer survives the entry."""
    coord = await setup_integration(entry)
    assert coord._first_analysis_cancel is not None
    await hass.config_entries.async_unload(entry.entry_id)
    assert coord._first_analysis_cancel is None
    ble.establish.assert_not_called()


async def test_first_analysis_runs_at_startup(
    monkeypatch, setup_integration, entry, ble
):
    monkeypatch.setattr(
        "custom_components.blue_connect_local.coordinator.FIRST_ANALYSIS_DELAY", 0.0
    )
    coord = await setup_integration(entry)
    for _ in range(20):
        if coord.data.get("ph") is not None:
            break
        await coord.hass.async_block_till_done(wait_background_tasks=True)
        import asyncio

        await asyncio.sleep(0.05)
    assert coord.data["ph"] == pytest.approx(7.4)


# ---------------------------------------------------------------------------
# Passive mode (Bluetooth advertisements)
# ---------------------------------------------------------------------------
async def test_passive_frame_updates_measurements(coordinator):
    coordinator._on_ble_seen(_seen(build_frame(ph=7.6)), None)
    assert coordinator.data["ph"] == pytest.approx(7.6)
    assert coordinator.data["receive_method"] == "passive"


async def test_passive_frame_in_service_data(coordinator):
    coordinator._on_ble_seen(_seen(build_frame(ph=7.1), service=True), None)
    assert coordinator.data["ph"] == pytest.approx(7.1)


async def test_passive_frame_with_prefix_byte(coordinator):
    frame = build_frame(ph=7.3, prefixed=True)
    coordinator._on_ble_seen(_seen(frame), None)
    assert coordinator.data["ph"] == pytest.approx(7.3)
    assert coordinator.data["raw_frame"] == clean_hex(frame)  # prefix stripped


async def test_identical_passive_frame_is_ignored(coordinator):
    frame = build_frame()
    coordinator._on_ble_seen(_seen(frame), None)
    first = coordinator.data["last_received"]
    coordinator._on_ble_seen(_seen(frame), None)
    assert coordinator.data["last_received"] == first


async def test_echo_frame_is_ignored_once_data_exists(coordinator):
    coordinator._on_ble_seen(_seen(build_frame(ph=7.4)), None)
    coordinator._on_ble_seen(_seen(build_frame(ph=6.0, echo=True)), None)
    assert coordinator.data["ph"] == pytest.approx(7.4)


async def test_echo_frame_is_accepted_when_there_is_no_data_yet(coordinator):
    coordinator._on_ble_seen(_seen(build_frame(ph=6.0, echo=True)), None)
    assert coordinator.data["ph"] == pytest.approx(6.0)


async def test_echo_frame_is_accepted_when_option_disabled(setup_integration):
    coord = await setup_integration(make_entry(**{CONF_IGNORE_ECHOES: False}))
    coord._on_ble_seen(_seen(build_frame(ph=7.4)), None)
    coord._on_ble_seen(_seen(build_frame(ph=6.0, echo=True)), None)
    assert coord.data["ph"] == pytest.approx(6.0)


async def test_passive_disabled_ignores_frames(setup_integration):
    coord = await setup_integration(make_entry(**{CONF_PASSIVE_MEASURES: False}))
    coord._on_ble_seen(_seen(build_frame()), None)
    assert coord.data.get("ph") is None


async def test_passive_frame_ignored_while_analysis_running(coordinator):
    coordinator.update_volatile_state({"action_running": True})
    coordinator._on_ble_seen(_seen(build_frame()), None)
    assert coordinator.data.get("ph") is None


@pytest.mark.parametrize("payload", [b"", b"\x00" * 5, b"\x00" * 17, b"\x00" * 20])
async def test_garbage_advertisement_is_ignored(coordinator, payload):
    coordinator._on_ble_seen(_seen(payload), None)
    assert coordinator.data.get("ph") is None


async def test_signal_lost_then_found(coordinator, caplog):
    with caplog.at_level(logging.DEBUG):
        coordinator._on_ble_unavailable(None)
        assert coordinator.data["bluetooth_status"] == BT_STATUS_OUT_OF_RANGE
        coordinator._on_ble_seen(
            SimpleNamespace(manufacturer_data={}, service_data={}), None
        )
    assert coordinator.data["bluetooth_status"] == BT_STATUS_WAITING
    assert "BLE signal lost" in caplog.text
    assert "BLE signal found" in caplog.text


async def test_signal_found_in_passive_mode(setup_integration):
    coord = await setup_integration(make_entry(access_code=None))
    coord._on_ble_unavailable(None)
    coord._on_ble_seen(SimpleNamespace(manufacturer_data={}, service_data={}), None)
    assert coord.data["bluetooth_status"] == "passive_mode"


# ---------------------------------------------------------------------------
# Blue Connect Silver (no conductivity sensor)
# ---------------------------------------------------------------------------
async def test_silver_has_no_conductivity_or_salinity(hass, coordinator):
    coordinator._on_ble_seen(_seen(build_frame(conductivity=None)), None)
    assert coordinator.data["has_conductivity"] is False
    assert coordinator.data["conductivity"] is None
    assert coordinator.data["salinity"] is None


async def test_silver_disables_conductivity_entities_once(hass, entry, coordinator):
    coordinator._on_ble_seen(_seen(build_frame(conductivity=None)), None)
    reg = er.async_get(hass)
    for key in ("conductivity", "salinity"):
        entity = reg.async_get(
            reg.async_get_entity_id("sensor", "blue_connect_local", f"{MAC}_{key}")
        )
        assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    # Manual re-enable by the user: must not be re-disabled.
    entity_id = reg.async_get_entity_id(
        "sensor", "blue_connect_local", f"{MAC}_salinity"
    )
    reg.async_update_entity(entity_id, disabled_by=None)
    coordinator._on_ble_seen(_seen(build_frame(conductivity=None, ph=7.0)), None)
    assert reg.async_get(entity_id).disabled_by is None


async def test_gold_keeps_conductivity_entities_enabled(hass, coordinator):
    coordinator._on_ble_seen(_seen(build_frame(conductivity=1500)), None)
    reg = er.async_get(hass)
    entity_id = reg.async_get_entity_id(
        "sensor", "blue_connect_local", f"{MAC}_conductivity"
    )
    assert reg.async_get(entity_id).disabled_by is None


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
async def test_schedule_is_aligned_on_reference_time(setup_integration):
    coord = await setup_integration(
        make_entry(**{CONF_SCAN_INTERVAL: 120, CONF_REFERENCE_TIME: "08:00"})
    )
    coord.update_schedule()
    slot = coord.next_slot
    assert slot.minute == 0
    assert (slot.hour - 8) % 2 == 0  # slots at 08:00, 10:00, 12:00...
    assert 0 < coord.update_interval.total_seconds() <= 2 * 3600


def _armed_refresh_delay(hass, action) -> float:
    """Run `action` and return the delay (s) of the coordinator refresh timer it armed.

    Only the DataUpdateCoordinator refresh timer is captured (not the save
    debounce, which also goes through loop.call_at).
    """
    captured: list[float] = []
    real_call_at = hass.loop.call_at

    def spy(when, callback, *args, **kwargs):
        if "wrap_handle_refresh_interval" in getattr(callback, "__name__", ""):
            captured.append(when - hass.loop.time())
        return real_call_at(when, callback, *args, **kwargs)

    hass.loop.call_at = spy
    try:
        action()
    finally:
        hass.loop.call_at = real_call_at
    assert captured, "no refresh timer was armed"
    return captured[-1]


async def test_interval_change_rearms_refresh_timer_immediately(
    hass, setup_integration, freezer
):
    """A new Analysis Interval must be used by the very next timer, not one update later."""
    from datetime import datetime

    coord = await setup_integration(
        make_entry(**{CONF_SCAN_INTERVAL: 60, CONF_REFERENCE_TIME: "08:00"})
    )
    tz = dt_util.get_default_time_zone()
    freezer.move_to(datetime(2026, 6, 1, 10, 2, 10, tzinfo=tz))
    delay = _armed_refresh_delay(
        hass, lambda: coord.update_local_state({CONF_SCAN_INTERVAL: 5})
    )
    assert delay == pytest.approx(170, abs=2.5)  # next 5 min slot: 10:05:00
    assert delay == pytest.approx(coord.update_interval.total_seconds(), abs=2.5)


async def test_reference_time_change_rearms_refresh_timer_immediately(
    hass, setup_integration, freezer
):
    from datetime import datetime

    coord = await setup_integration(
        make_entry(**{CONF_SCAN_INTERVAL: 1440, CONF_REFERENCE_TIME: "08:00"})
    )
    tz = dt_util.get_default_time_zone()
    freezer.move_to(datetime(2026, 6, 1, 10, 0, 30, tzinfo=tz))
    delay = _armed_refresh_delay(
        hass, lambda: coord.update_local_state({CONF_REFERENCE_TIME: "13:00"})
    )
    assert delay == pytest.approx(2 * 3600 + 59 * 60 + 30, abs=2.5)  # 13:00:00 today


async def test_state_update_does_not_delay_the_timer_past_its_slot(
    hass, setup_integration, freezer
):
    """A status update 30 min after the last schedule computation must not re-arm the
    timer with the stale delay (60 min): the next slot is 30 min away."""
    from datetime import datetime

    from homeassistant.util import dt as dt_util

    coord = await setup_integration(
        make_entry(**{CONF_SCAN_INTERVAL: 60, CONF_REFERENCE_TIME: "08:00"})
    )
    tz = dt_util.get_default_time_zone()
    freezer.move_to(datetime(2026, 6, 1, 10, 0, 5, tzinfo=tz))
    coord.update_schedule()  # next slot 11:00 -> ~3595 s
    freezer.move_to(datetime(2026, 6, 1, 10, 30, 0, tzinfo=tz))

    delay = _armed_refresh_delay(
        hass, lambda: coord.update_volatile_state({"bluetooth_status": "waiting"})
    )
    assert delay == pytest.approx(30 * 60, abs=2.5)


async def test_schedule_tolerates_garbage_reference_time(setup_integration):
    coord = await setup_integration(make_entry(**{CONF_REFERENCE_TIME: "garbage"}))
    coord.update_schedule()
    assert coord.next_slot is not None


async def test_no_schedule_without_access_code(setup_integration):
    coord = await setup_integration(make_entry(access_code=None))
    assert coord.next_slot is None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _stored(**data):
    key = store_key(MAC)
    return {"version": 1, "minor_version": 1, "key": key, "data": data}


async def test_save_strips_transient_state(coordinator, hass_storage):
    await coordinator.async_refresh()
    await coordinator.async_save_to_disk()
    saved = hass_storage[store_key(MAC)]["data"]
    assert "bluetooth_status" not in saved
    assert "action_running" not in saved
    assert isinstance(saved["last_received"], str)
    assert saved["ph_raw"] == pytest.approx(7.4)


async def test_restore_valid_measurements(setup_integration, hass_storage):
    hass_storage[store_key(MAC)] = _stored(
        raw_frame=clean_hex(build_frame()),
        last_received="2026-01-02T03:04:05+00:00",
        ph=7.1,
        ph_raw=7.1,
        orp=690,
        tac=90,
        sku="WA000099",
        serial_number="SN1",
    )
    coord = await setup_integration(make_entry())
    assert coord.data["ph"] == 7.1
    assert coord.data["tac"] == 90
    assert coord.data["last_received"].year == 2026
    assert coord.data["sku"] == "WA000099"


async def test_restore_invalid_raw_frame_discards_measurements_but_keeps_preferences(
    setup_integration, hass_storage, caplog
):
    hass_storage[store_key(MAC)] = _stored(
        raw_frame="TOO-SHORT", ph=9.9, tac=90, cya=55, sku="WA000100"
    )
    with caplog.at_level(logging.WARNING):
        coord = await setup_integration(make_entry())
    assert "ph" not in coord.data  # measurement discarded
    assert coord.data["tac"] == 90  # preferences kept
    assert coord.data["cya"] == 55
    assert coord.data["sku"] == "WA000100"
    assert "Invalid raw_frame" in caplog.text


async def test_restore_legacy_keys(setup_integration, hass_storage):
    hass_storage[store_key(MAC)] = _stored(hw_version="WA000099", sw_version="OLDCLOUD")
    coord = await setup_integration(make_entry())
    assert coord.data["sku"] == "WA000099"
    assert coord.data["cloud_id"] == "OLDCLOUD"
    assert "hw_version" not in coord.data
    assert "sw_version" not in coord.data


async def test_restore_drops_empty_identity_values(setup_integration, hass_storage):
    hass_storage[store_key(MAC)] = _stored(
        serial_number="", sku="", cloud_id="", tac=10
    )
    coord = await setup_integration(make_entry())
    for key in ("serial_number", "sku", "cloud_id"):
        assert key not in coord.data


async def test_restore_corrupted_timestamp(setup_integration, hass_storage):
    hass_storage[store_key(MAC)] = _stored(
        raw_frame=clean_hex(build_frame()), last_received="not-a-date", ph=7.0
    )
    coord = await setup_integration(make_entry())
    assert "last_received" not in coord.data


async def test_access_code_comes_from_config_entry(coordinator):
    assert coordinator.access_code == ACCESS_CODE
    assert coordinator.data[CONF_ACCESS_CODE] == ACCESS_CODE


def test_get_opt_falls_back_to_entry_data():
    """Options take priority, but a value only in entry.data is still found."""
    custom_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={CONF_MAC_ADDRESS: MAC, "some_legacy_key": "from_data"},
        options={},
    )
    assert _get_opt(custom_entry, "some_legacy_key", "default") == "from_data"
    assert _get_opt(custom_entry, "missing_key", "default") == "default"


async def test_update_schedule_is_a_noop_while_shutting_down(coordinator):
    before = coordinator.update_interval
    coordinator._is_shutdown = True
    try:
        coordinator.update_schedule()
        assert coordinator.update_interval == before
    finally:
        coordinator._is_shutdown = False


async def test_update_schedule_is_a_noop_without_config_entry(hass, coordinator):
    before = coordinator.update_interval
    original_async_get_entry = hass.config_entries.async_get_entry
    hass.config_entries.async_get_entry = lambda entry_id: None
    try:
        coordinator.update_schedule()
        assert coordinator.update_interval == before
    finally:
        # Restore before returning: the `coordinator` fixture's teardown
        # relies on this same method to unload the entry cleanly.
        hass.config_entries.async_get_entry = original_async_get_entry


async def test_has_conductivity_is_seeded_from_config_entry_data(setup_integration):
    """Discovery can persist a has_conductivity guess in entry.data (see
    config_flow.py); the coordinator must seed it immediately so
    conductivity/salinity's enabled_default is right from the first entity
    registration, without waiting for a live BLE frame."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={
            CONF_MAC_ADDRESS: MAC,
            CONF_ACCESS_CODE: ACCESS_CODE,
            "has_conductivity": True,
        },
        options={},
    )
    coordinator = await setup_integration(entry)
    assert coordinator.data["has_conductivity"] is True
