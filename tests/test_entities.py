"""Entities: sensors (including raw Redox), alerts, numbers, switches, button."""

from __future__ import annotations

from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.blue_connect_local.binary_sensor import BlueConnectAlertSensor
from custom_components.blue_connect_local.const import (
    BT_STATUS_OUT_OF_RANGE,
    BT_STATUS_PAUSED,
    BT_STATUS_WAITING,
    CONF_ACCESS_CODE,
    CONF_CHLORINE_MODEL,
    CONF_CYA,
    CONF_MAC_ADDRESS,
    CONF_ORP_CALIB,
    CONF_ORP_MAX,
    CONF_ORP_REF,
    CONF_PASSIVE_MEASURES,
    CONF_PH_MAX,
    CONF_REFERENCE_TIME,
    CONF_SCAN_INTERVAL,
    CONF_TAC,
    CONF_TEMP_MAX,
    DEFAULT_PH_MAX,
    DOMAIN,
)
from custom_components.blue_connect_local.switch import (
    BlueConnectActiveMeasuresSwitch,
    BlueConnectPassiveMeasuresSwitch,
)

from .conftest import entity_id, make_entry
from .helpers import ACCESS_CODE, MAC, FakeBlueClient, build_frame


async def _call(hass, domain, service, entity, **data):
    await hass.services.async_call(
        domain, service, {"entity_id": entity, **data}, blocking=True
    )
    await hass.async_block_till_done()


async def _measured(hass, coordinator):
    await coordinator.async_refresh()
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------
async def test_measurement_sensors(hass, coordinator):
    await _measured(hass, coordinator)

    def state(key):
        return hass.states.get(entity_id(hass, "sensor", key)).state

    assert float(state("temperature")) == pytest.approx(25.02)
    assert float(state("ph")) == pytest.approx(7.4)
    assert float(state("orp")) == 700
    assert float(state("orp_raw")) == 700
    assert float(state("ph_raw")) == pytest.approx(7.4)
    assert float(state("battery_level")) == 80
    assert float(state("conductivity")) == 1200
    assert float(state("salinity")) == pytest.approx(3.5)
    assert state("receive_method") == "active"
    assert state("bluetooth_status") == "success"
    assert state("lsi_status") == "unknown"
    assert state("cloud_id") == "CLOUD42"


async def test_raw_orp_is_not_affected_by_calibration_offset(
    hass, setup_integration, ble
):
    """Raw Redox is used to *establish* the offset: it stays the probe's value."""
    ble.client = FakeBlueClient([build_frame(orp_mv=700)])
    coord = await setup_integration(
        make_entry(**{CONF_ORP_CALIB: 640, CONF_ORP_REF: 650})
    )
    await _measured(hass, coord)
    raw = hass.states.get(entity_id(hass, "sensor", "orp_raw"))
    calibrated = hass.states.get(entity_id(hass, "sensor", "orp"))
    assert float(raw.state) == 700
    assert float(calibrated.state) == 710
    assert raw.attributes["unit_of_measurement"] == "mV"


async def test_raw_orp_is_a_diagnostic_entity(hass, coordinator):
    reg = er.async_get(hass).async_get(entity_id(hass, "sensor", "orp_raw"))
    assert reg.entity_category is EntityCategory.DIAGNOSTIC


async def test_every_entity_has_a_translated_name(hass, entry, coordinator):
    for reg in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        assert reg.original_name, f"{reg.unique_id} has no translated name"


async def test_no_chlorine_sensors(hass, entry, coordinator):
    ids = {
        e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    assert not any("free_chlorine" in u or "hocl" in u for u in ids)


async def test_sensor_unknown_before_first_measurement(hass, coordinator):
    assert hass.states.get(entity_id(hass, "sensor", "ph")).state == STATE_UNKNOWN


async def test_rssi_sensor_reads_advertisements(hass, coordinator, ble):
    assert hass.states.get(entity_id(hass, "sensor", "rssi")).state == str(ble.rssi)


async def test_next_analysis_unknown_when_no_slot_scheduled(hass, coordinator):
    coordinator.next_slot = None
    coordinator.async_set_updated_data(dict(coordinator.data))
    await hass.async_block_till_done()
    # `available` depends on native_value here, so no scheduled slot means
    # "unavailable", not "unknown".
    assert hass.states.get(entity_id(hass, "sensor", "next_analysis")).state == (
        STATE_UNAVAILABLE
    )


async def test_next_analysis_converts_naive_slot_to_utc(hass, coordinator):
    """next_slot is normally tz-aware; a naive value must still be handled."""
    naive = dt_util.utcnow().replace(tzinfo=None)
    coordinator.next_slot = naive
    coordinator.async_set_updated_data(dict(coordinator.data))
    await hass.async_block_till_done()
    state = hass.states.get(entity_id(hass, "sensor", "next_analysis"))
    assert dt_util.parse_datetime(state.state) == dt_util.as_utc(naive).replace(
        microsecond=0
    )


async def test_next_analysis_converts_naive_slot_to_utc_in_passive_mode(
    hass, setup_integration
):
    """Same conversion, but for a device with no access code (passive mode)."""
    coordinator = await setup_integration(make_entry(access_code=None))
    naive = dt_util.utcnow().replace(tzinfo=None)
    coordinator.next_slot = naive
    coordinator.async_set_updated_data(dict(coordinator.data))
    await hass.async_block_till_done()
    state = hass.states.get(entity_id(hass, "sensor", "next_analysis"))
    assert dt_util.parse_datetime(state.state) == dt_util.as_utc(naive).replace(
        microsecond=0
    )


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["ph_status", "orp_status", "temperature_status"])
async def test_alerts_off_in_range(hass, coordinator, key):
    await _measured(hass, coordinator)
    assert hass.states.get(entity_id(hass, "binary_sensor", key)).state == STATE_OFF


async def test_alerts_unknown_without_measurement(hass, coordinator):
    assert (
        hass.states.get(entity_id(hass, "binary_sensor", "ph_status")).state
        == STATE_UNKNOWN
    )


async def test_ph_alert_follows_thresholds(hass, coordinator):
    await _measured(hass, coordinator)
    alert = entity_id(hass, "binary_sensor", "ph_status")
    coordinator.update_local_state({CONF_PH_MAX: 7.2})  # pH 7.4 > 7.2
    await hass.async_block_till_done()
    assert hass.states.get(alert).state == STATE_ON
    coordinator.update_local_state({CONF_PH_MAX: 8.0})
    await hass.async_block_till_done()
    assert hass.states.get(alert).state == STATE_OFF


async def test_orp_and_temperature_alerts(hass, coordinator):
    await _measured(hass, coordinator)
    coordinator.update_local_state({CONF_ORP_MAX: 690, CONF_TEMP_MAX: 20.0})
    await hass.async_block_till_done()
    assert (
        hass.states.get(entity_id(hass, "binary_sensor", "orp_status")).state
        == STATE_ON
    )
    assert (
        hass.states.get(entity_id(hass, "binary_sensor", "temperature_status")).state
        == STATE_ON
    )


async def test_alert_threshold_itself_is_not_an_alert(hass, coordinator):
    await _measured(hass, coordinator)
    coordinator.update_local_state({CONF_ORP_MAX: 700})  # ORP == 700
    await hass.async_block_till_done()
    assert (
        hass.states.get(entity_id(hass, "binary_sensor", "orp_status")).state
        == STATE_OFF
    )


async def test_alert_is_on_none_with_no_coordinator_data(hass, coordinator):
    coordinator.async_set_updated_data({})
    await hass.async_block_till_done()
    assert (
        hass.states.get(entity_id(hass, "binary_sensor", "ph_status")).state
        == STATE_UNKNOWN
    )


async def test_alert_is_on_returns_none_for_unknown_data_key(hass, coordinator):
    """Defensive fallback: only ph/orp/temperature are meaningful data_keys."""
    sensor = BlueConnectAlertSensor(
        coordinator,
        "fake_entry_id",
        coordinator.mac,
        "Blue Connect",
        "scan_interval_status",
        "scan_interval",
    )
    assert sensor.is_on is None


async def test_alert_threshold_falls_back_to_default_when_entry_is_gone(
    hass, coordinator
):
    """_threshold must not crash if the config entry vanished."""
    sensor = BlueConnectAlertSensor(
        coordinator, "fake_entry_id", coordinator.mac, "Blue Connect", "ph_status", "ph"
    )
    sensor.hass = hass
    original_async_get_entry = hass.config_entries.async_get_entry
    hass.config_entries.async_get_entry = lambda entry_id: (
        None if entry_id == "fake_entry_id" else original_async_get_entry(entry_id)
    )
    try:
        # coordinator.data has no "ph_max" key, so _threshold must fall
        # through to the (now unreachable) entry lookup, and finally to
        # _DEFAULT_THRESHOLDS.
        assert sensor._threshold(CONF_PH_MAX) == DEFAULT_PH_MAX
    finally:
        hass.config_entries.async_get_entry = original_async_get_entry


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("key", "maximum"), [("tac", 500), ("th", 800), ("tds", 5000)])
async def test_water_parameter_bounds(hass, coordinator, key, maximum):
    entity = entity_id(hass, "number", key)
    await _call(hass, "number", "set_value", entity, value=maximum)
    assert float(hass.states.get(entity).state) == maximum
    with pytest.raises(ServiceValidationError):
        await _call(hass, "number", "set_value", entity, value=maximum + 1)


async def test_water_parameters_drive_langelier(hass, coordinator):
    await _measured(hass, coordinator)
    for key, value in (("tac", 100), ("th", 200), ("tds", 1000)):
        await _call(
            hass, "number", "set_value", entity_id(hass, "number", key), value=value
        )
    coordinator.recompute_derived_values()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "sensor", "lsi")).state not in (
        STATE_UNKNOWN,
        STATE_UNAVAILABLE,
    )


async def test_scan_interval_bounds_and_effect(hass, coordinator):
    entity = entity_id(hass, "number", "scan_interval")
    await _call(hass, "number", "set_value", entity, value=30)
    assert coordinator.data[CONF_SCAN_INTERVAL] == 30
    with pytest.raises(ServiceValidationError):
        await _call(hass, "number", "set_value", entity, value=4)


async def test_cya_is_kept_and_editable(hass, coordinator):
    entity = entity_id(hass, "number", "cya")
    await _call(hass, "number", "set_value", entity, value=60)
    assert float(hass.states.get(entity).state) == 60
    assert coordinator.data[CONF_CYA] == 60


async def test_cya_unavailable_with_bromine(hass, coordinator):
    cya = entity_id(hass, "number", "cya")
    coordinator.update_local_state({CONF_CHLORINE_MODEL: "bromine"})
    await hass.async_block_till_done()
    assert hass.states.get(cya).state == STATE_UNAVAILABLE
    coordinator.update_local_state({CONF_CHLORINE_MODEL: "chlorine"})
    await hass.async_block_till_done()
    assert hass.states.get(cya).state != STATE_UNAVAILABLE


async def test_cya_survives_unrelated_setting_changes(hass, coordinator):
    """CyA and treatment type are kept: another setting must not overwrite them."""
    cya = entity_id(hass, "number", "cya")
    await _call(hass, "number", "set_value", cya, value=80)
    coordinator.update_local_state({CONF_CHLORINE_MODEL: "bromine"})
    coordinator.update_local_state({CONF_CHLORINE_MODEL: "chlorine"})
    coordinator.update_local_state({CONF_PH_MAX: 7.5})
    await hass.async_block_till_done()
    assert float(hass.states.get(cya).state) == 80


# ---------------------------------------------------------------------------
# Switches, reference time, button
# ---------------------------------------------------------------------------
async def test_active_measures_switch(hass, coordinator):
    switch = entity_id(hass, "switch", "active_measures")
    assert hass.states.get(switch).state == STATE_ON
    await _call(hass, "switch", "turn_off", switch)
    assert hass.states.get(switch).state == STATE_OFF
    assert coordinator.data["bluetooth_status"] == BT_STATUS_PAUSED
    await _call(hass, "switch", "turn_on", switch)
    assert hass.states.get(switch).state == STATE_ON
    assert coordinator.data["bluetooth_status"] == BT_STATUS_WAITING


async def test_active_measures_resume_without_bluetooth(hass, coordinator, ble):
    switch = entity_id(hass, "switch", "active_measures")
    await _call(hass, "switch", "turn_off", switch)
    ble.scanner_count = 0
    await _call(hass, "switch", "turn_on", switch)
    assert coordinator.data["bluetooth_status"] == BT_STATUS_OUT_OF_RANGE


async def test_passive_measures_switch(hass, coordinator):
    switch = entity_id(hass, "switch", "passive_measures")
    assert hass.states.get(switch).state == STATE_ON  # enabled by default
    await _call(hass, "switch", "turn_off", switch)
    assert coordinator.data[CONF_PASSIVE_MEASURES] is False
    assert hass.states.get(switch).state == STATE_OFF
    await _call(hass, "switch", "turn_on", switch)
    assert coordinator.data[CONF_PASSIVE_MEASURES] is True
    assert hass.states.get(switch).state == STATE_ON


async def test_active_measures_switch_defaults_on_with_no_coordinator_data(
    hass, coordinator
):
    """is_on defaults to True when coordinator.data is empty.

    Checked directly on the property: going through the HASS state would
    also hit `available` (which separately depends on `access_code`, itself
    read from `coordinator.data`), masking the behavior under test.
    """
    coordinator.async_set_updated_data({})
    switch = BlueConnectActiveMeasuresSwitch(
        coordinator, coordinator.mac, "Blue Connect", "fake_entry_id"
    )
    assert switch.is_on is True


async def test_passive_measures_defaults_true_when_entry_is_gone(hass, coordinator):
    """is_on must not crash if the config entry vanished; defaults to True."""
    data_without_key = {
        k: v for k, v in coordinator.data.items() if k != CONF_PASSIVE_MEASURES
    }
    coordinator.async_set_updated_data(data_without_key)
    switch = BlueConnectPassiveMeasuresSwitch(
        coordinator, coordinator.mac, "Blue Connect", "fake_entry_id"
    )
    switch.hass = hass
    assert switch.is_on is True


async def test_active_controls_unavailable_without_access_code(hass, setup_integration):
    coord = await setup_integration(make_entry(access_code=None))
    for domain, key in (("switch", "active_measures"), ("time", "reference_time")):
        assert hass.states.get(entity_id(hass, domain, key)).state == STATE_UNAVAILABLE
    assert coord.access_code == ""


async def test_reference_time_entity(hass, coordinator):
    entity = entity_id(hass, "time", "reference_time")
    assert hass.states.get(entity).state == "08:00:00"
    await _call(hass, "time", "set_value", entity, time=time(6, 30).isoformat())
    assert coordinator.data[CONF_REFERENCE_TIME] == "06:30"
    assert hass.states.get(entity).state == "06:30:00"


async def test_button_requests_one_shot_analysis(hass, coordinator):
    coordinator._force_one_shot = False
    coordinator.async_request_refresh = AsyncMock()
    await _call(hass, "button", "press", entity_id(hass, "button", "force_analysis"))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator._force_one_shot is True
    coordinator.async_request_refresh.assert_awaited_once()
    assert coordinator.data["action_running"] is False


async def test_button_ignored_while_analysis_running(hass, coordinator):
    coordinator.update_volatile_state({"action_running": True})
    coordinator.async_request_refresh = AsyncMock()
    await _call(hass, "button", "press", entity_id(hass, "button", "force_analysis"))
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator.async_request_refresh.assert_not_awaited()


async def test_button_swallows_refresh_errors(hass, coordinator):
    coordinator.async_request_refresh = AsyncMock(side_effect=RuntimeError("boom"))
    await _call(hass, "button", "press", entity_id(hass, "button", "force_analysis"))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.data["action_running"] is False


async def test_button_swallows_unexpected_error_types(hass, coordinator):
    # KeyError is neither HomeAssistantError nor RuntimeError: this is exactly
    # what the narrower except clause used to miss.
    coordinator.async_request_refresh = AsyncMock(side_effect=KeyError("unexpected"))
    await _call(hass, "button", "press", entity_id(hass, "button", "force_analysis"))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.data["action_running"] is False


async def test_button_ignored_while_shutting_down(hass, coordinator):
    """A press during shutdown must be a no-op, not raise or schedule anything."""
    coordinator.async_request_refresh = AsyncMock()
    coordinator._is_shutdown = True
    try:
        assert coordinator.is_shutdown is True  # public property reads it back
        await _call(
            hass, "button", "press", entity_id(hass, "button", "force_analysis")
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        coordinator.async_request_refresh.assert_not_awaited()
    finally:
        # Restore normal state so the `coordinator`/`setup_integration` fixture
        # can unload the entry cleanly at the end of the test.
        coordinator._is_shutdown = False


async def test_button_logs_timeout_without_leaving_action_running(hass, coordinator):
    """A refresh that exceeds TIMEOUT_FORCE_REFRESH is logged, not raised."""
    coordinator.async_request_refresh = AsyncMock(side_effect=TimeoutError())
    await _call(hass, "button", "press", entity_id(hass, "button", "force_analysis"))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.data["action_running"] is False


async def test_button_does_not_schedule_task_when_entry_is_gone(hass, coordinator):
    """If the config entry disappeared mid-press, no background task is scheduled."""
    coordinator.async_request_refresh = AsyncMock()
    original_async_get_entry = hass.config_entries.async_get_entry
    hass.config_entries.async_get_entry = lambda entry_id: None
    try:
        await _call(
            hass, "button", "press", entity_id(hass, "button", "force_analysis")
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        coordinator.async_request_refresh.assert_not_awaited()
    finally:
        # Restore before returning: Home Assistant's own entry-unload
        # machinery (run by the `coordinator` fixture's teardown, right
        # after this test function returns) relies on this same method.
        hass.config_entries.async_get_entry = original_async_get_entry


# ---------------------------------------------------------------------------
# Bluetooth signal sensor
# ---------------------------------------------------------------------------
async def test_rssi_sensor_restores_its_last_value_without_advertisement(
    hass, setup_integration, entry, ble
):
    ble.last_seen_age = None  # nothing in the Bluetooth cache at startup
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("sensor.blue_connect_eeff_bluetooth_signal", "-70"),
                {"native_value": -70, "native_unit_of_measurement": "dBm"},
            )
        ],
    )
    coord = await setup_integration(entry)
    ble.last_seen_age = 0.0  # the probe is heard again after startup
    coord._on_ble_seen(SimpleNamespace(manufacturer_data={}, service_data={}), None)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "sensor", "rssi")).state == "-70"


async def test_rssi_sensor_without_history_or_advertisement_stays_unavailable(
    hass, setup_integration, entry, ble
):
    ble.last_seen_age = None
    await setup_integration(entry)
    assert hass.states.get(entity_id(hass, "sensor", "rssi")).state == (
        STATE_UNAVAILABLE
    )


async def test_rssi_sensor_follows_new_advertisements(
    hass, setup_integration, entry, ble
):
    callbacks = []

    def fake_register(_hass, callback, _matcher, _mode):
        callbacks.append(callback)
        return lambda: None

    with patch(
        "custom_components.blue_connect_local.sensor.async_register_callback",
        side_effect=fake_register,
    ):
        await setup_integration(entry)
    callbacks[0](SimpleNamespace(rssi=-42), None)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "sensor", "rssi")).state == "-42"


# ---------------------------------------------------------------------------
# Numbers: fallbacks
# ---------------------------------------------------------------------------
async def test_numbers_keep_their_value_when_the_coordinator_data_is_invalid(
    hass, coordinator
):
    interval = entity_id(hass, "number", CONF_SCAN_INTERVAL)
    tac = entity_id(hass, "number", CONF_TAC)
    before = (hass.states.get(interval).state, hass.states.get(tac).state)
    coordinator.data[CONF_SCAN_INTERVAL] = "not a number"
    coordinator.data[CONF_TAC] = "not a number"
    coordinator.async_set_updated_data(coordinator.data)
    await hass.async_block_till_done()
    assert (hass.states.get(interval).state, hass.states.get(tac).state) == before


async def test_interval_number_reads_the_config_entry_data_as_a_last_resort(
    hass, setup_integration
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        title="Blue Connect",
        version=1,
        minor_version=4,
        data={
            CONF_MAC_ADDRESS: MAC,
            CONF_ACCESS_CODE: ACCESS_CODE,
            CONF_SCAN_INTERVAL: 45,
        },
    )
    await setup_integration(entry)
    assert hass.states.get(entity_id(hass, "number", CONF_SCAN_INTERVAL)).state == "45"
