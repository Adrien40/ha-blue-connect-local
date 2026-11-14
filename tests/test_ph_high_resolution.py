"""High-resolution pH: electrical frame + the probe's own 2-point calibration.

The probe converts the electrode potential to a pH by linear interpolation
between the two calibration points it stores, then rounds it to 0.1 in the
calculated frame. The integration applies the same formula to the potential of
the electrical frame to keep the 2 decimals.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir

from custom_components.blue_connect_local.chemistry import compute_ph_two_point
from custom_components.blue_connect_local.const import (
    CHAR_LAST_PH_CALIB_UUID,
    CONF_PASSIVE_MEASURES,
    CONF_PH_HR_CALIB_MV_4,
    CONF_PH_HR_CALIB_MV_7,
    DOMAIN,
    PH_HR_CALIBRATION_SOURCE_INTEGRATION,
    PH_HR_CALIBRATION_SOURCE_PROBE,
    PH_SOURCE_HIGH_RESOLUTION,
    PH_SOURCE_STANDARD,
)
from custom_components.blue_connect_local.protocol import (
    parse_electrical_frame,
    parse_ph_calibration,
)
from custom_components.blue_connect_local.repairs import async_create_fix_flow

from .conftest import entity_id, make_entry
from .helpers import (
    ACCESS_CODE,
    UUID_PH_CALIB_MV_1,
    UUID_PH_CALIB_MV_2,
    UUID_PH_CALIB_PH_1,
    UUID_PH_CALIB_PH_2,
    UUID_RAW_SENSORS,
    build_electrical_frame,
    build_frame,
    ph_calibration_reads,
)

COMPONENT_DIR = (
    Path(__file__).parent.parent / "custom_components" / "blue_connect_local"
)

# Calibration read from a real Blue Connect Gold (registers 70ea0015..0018).
CALIBRATION = {"ph_1": 4.0, "ph_2": 7.0, "mv_1": 178.2, "mv_2": 2.8}

# (potential in mV, pH of the calculated frame) taken from real frames of that
# probe: the frame pH is the rounded value of the formula.
REAL_FRAMES = [
    (49.0, 6.2),
    (44.7, 6.3),
    (37.1, 6.4),
    (-3.5, 7.1),
    (-6.5, 7.2),
    (-61.5, 8.1),
    (-67.4, 8.2),
    (-76.3, 8.4),
    (-84.6, 8.5),
    (-90.3, 8.6),
]


def _seen(frame: bytes) -> SimpleNamespace:
    return SimpleNamespace(manufacturer_data={0x1234: frame}, service_data={})


def _arm(ble, *, mv=37.1, calc_ph=6.4, calibration=None):
    """Next active analysis: calculated frame + electrical frame + calibration."""
    ble.client.frames[:] = [build_frame(ph=calc_ph)]
    ble.client.reads[UUID_RAW_SENSORS] = build_electrical_frame(mv)
    ble.client.reads.update(calibration or ph_calibration_reads())
    ble.client.is_connected = True


async def _analysis(coordinator, ble, **kwargs):
    _arm(ble, **kwargs)
    await coordinator.async_refresh()


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------
def test_electrical_frame_gives_potential():
    # Frame read on 6 November 2026: 37.1 mV.
    frame = bytes.fromhex(
        "04360173030701 2D091B080BFFF70EE8FFFE09D903E80CC80CE50CD70EE8".replace(" ", "")
    )
    assert len(frame) == 30
    assert parse_electrical_frame(frame) == 37.1


def test_electrical_frame_negative_potential():
    frame = bytes.fromhex(
        "0471FD52023A0F1B08B60805FFF40EDD000302EC03E80E380E440E3E0EDD"
    )
    assert parse_electrical_frame(frame) == -68.6


def test_electrical_frame_too_short_is_ignored():
    assert parse_electrical_frame(bytes.fromhex("010203")) is None


def test_ph_calibration_is_decoded():
    assert (
        parse_ph_calibration(
            bytes.fromhex("0028"),
            bytes.fromhex("0046"),
            bytes.fromhex("06F6"),
            bytes.fromhex("001C"),
        )
        == CALIBRATION
    )


def test_ph_calibration_potentials_are_signed():
    calibration = parse_ph_calibration(
        bytes.fromhex("0028"),
        bytes.fromhex("0046"),
        bytes.fromhex("06F6"),
        bytes.fromhex("FFE2"),
    )
    assert calibration is not None
    assert calibration["mv_2"] == -3.0


@pytest.mark.parametrize(
    ("point_1_ph", "point_2_ph", "point_1_mv", "point_2_mv"),
    [
        ("00", "0046", "06F6", "001C"),  # value too short
        ("0028", "0028", "06F6", "001C"),  # same buffer twice
        ("0028", "0046", "001C", "001C"),  # same potential twice
        ("FFFF", "0000", "06F6", "001C"),  # unwritten registers
        ("0000", "0046", "06F6", "001C"),  # pH 0 is not a buffer
        ("0028", "008C", "06F6", "001C"),  # pH 14 is not a buffer
        ("0028", "0046", "001C", "06F6"),  # potential rises with the pH
    ],
)
def test_ph_calibration_unusable_is_rejected(
    point_1_ph, point_2_ph, point_1_mv, point_2_mv
):
    assert (
        parse_ph_calibration(
            bytes.fromhex(point_1_ph),
            bytes.fromhex(point_2_ph),
            bytes.fromhex(point_1_mv),
            bytes.fromhex(point_2_mv),
        )
        is None
    )


# ---------------------------------------------------------------------------
# Formula
# ---------------------------------------------------------------------------
def test_formula_returns_the_calibration_points():
    assert compute_ph_two_point(178.2, CALIBRATION) == pytest.approx(4.0)
    assert compute_ph_two_point(2.8, CALIBRATION) == pytest.approx(7.0)


def test_formula_values_checked_on_the_probe():
    assert compute_ph_two_point(37.1, CALIBRATION) == pytest.approx(6.4133, abs=1e-4)
    assert compute_ph_two_point(-68.6, CALIBRATION) == pytest.approx(8.2212, abs=1e-4)


@pytest.mark.parametrize(("mv", "frame_ph"), REAL_FRAMES)
def test_formula_rounds_to_the_ph_of_the_calculated_frame(mv, frame_ph):
    assert round(compute_ph_two_point(mv, CALIBRATION), 1) == frame_ph


# ---------------------------------------------------------------------------
# Active analysis
# ---------------------------------------------------------------------------
async def test_active_analysis_gives_the_high_resolution_ph(coordinator, ble):
    await _analysis(coordinator, ble)
    data = coordinator.data
    assert data["ph"] == pytest.approx(6.41)
    # The calculated frame's pH (probe calibration, 0.1), unchanged:
    assert data["ph_probe_calibrated"] == pytest.approx(6.4)
    # The pH read from the electrode alone: 7 - 37.1 / 59.16, no calibration.
    assert data["ph_raw"] == pytest.approx(6.37)
    assert data["ph_raw_mv"] == 37.1
    assert data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert data["ph_hr_calibration"] == CALIBRATION
    assert data["ph_hr_available"] is True


async def test_unreadable_electrical_frame_keeps_the_standard_ph(coordinator, ble):
    _arm(ble)
    del ble.client.reads[UUID_RAW_SENSORS]
    await coordinator.async_refresh()
    assert coordinator.data["ph"] == pytest.approx(6.4)
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD


async def test_previous_electrical_frame_is_never_paired_again(coordinator, ble):
    await _analysis(coordinator, ble)
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    _arm(ble, calc_ph=6.5)
    del ble.client.reads[UUID_RAW_SENSORS]  # this time the read fails
    await coordinator.async_refresh()
    assert coordinator.data["ph"] == pytest.approx(6.5)
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD
    assert coordinator.data["ph_raw_mv"] is None


async def test_unreadable_calibration_keeps_the_standard_ph(coordinator, ble, caplog):
    _arm(ble)
    del ble.client.reads[UUID_PH_CALIB_MV_1]
    with caplog.at_level(logging.DEBUG):
        await coordinator.async_refresh()
    assert coordinator.data["ph"] == pytest.approx(6.4)
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD
    assert "Failed to read pH calibration" in caplog.text


async def test_unusable_calibration_keeps_the_standard_ph(coordinator, ble):
    await _analysis(
        coordinator, ble, calibration=ph_calibration_reads(mv_1=2.8, mv_2=2.8)
    )
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD
    assert coordinator.data["ph"] == pytest.approx(6.4)


async def test_impossible_ph_falls_back_to_the_standard_ph(coordinator, ble, caplog):
    with caplog.at_level(logging.WARNING):
        await _analysis(coordinator, ble, mv=-600.0)
    assert coordinator.data["ph"] == pytest.approx(6.4)
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD
    # The potential is still shown, so that it can be used to calibrate.
    assert coordinator.data["ph_raw_mv"] == -600.0
    assert "out of the physical range" in caplog.text


async def test_integration_ph_calibration_does_not_apply_to_high_resolution(
    setup_integration, ble
):
    from custom_components.blue_connect_local.const import (
        CONF_PH_CALIB_4,
        CONF_PH_CALIB_7,
    )

    coordinator = await setup_integration(
        make_entry(**{CONF_PH_CALIB_7: 7.5, CONF_PH_CALIB_4: 4.5})
    )
    await _analysis(coordinator, ble)
    assert coordinator.data["ph"] == pytest.approx(6.41)
    # The standard pH, on the other hand, goes through that calibration.
    coordinator._on_ble_seen(_seen(build_frame(ph=6.4, battery_adc=3999)), None)
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD
    assert coordinator.data["ph"] != pytest.approx(6.4)


async def test_recompute_keeps_the_high_resolution_ph(coordinator, ble):
    await _analysis(coordinator, ble)
    coordinator.recompute_derived_values()
    assert coordinator.data["ph"] == pytest.approx(6.41)
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert coordinator.data["ph_raw_mv"] == 37.1


# A probe that was never calibrated (or whose calibration cannot be read) still
# sends the potential: "Raw pH (mV)" must show it, it is what the person reads
# to calibrate.
async def test_raw_potential_stays_readable_without_a_probe_calibration(
    coordinator, ble
):
    _arm(ble, mv=25.0)
    del ble.client.reads[UUID_PH_CALIB_MV_1]
    await coordinator.async_refresh()
    data = coordinator.data
    assert data["ph_source"] == PH_SOURCE_STANDARD
    assert data["ph"] == pytest.approx(6.4)
    assert data["ph_raw_mv"] == 25.0
    assert data["ph_raw"] == pytest.approx(6.58)
    assert data["ph_hr_calibration"] is None


async def test_recompute_keeps_the_raw_potential_of_a_standard_analysis(
    coordinator, ble
):
    _arm(ble, mv=25.0)
    del ble.client.reads[UUID_PH_CALIB_MV_1]
    await coordinator.async_refresh()
    coordinator.recompute_derived_values()
    assert coordinator.data["ph_raw_mv"] == 25.0
    assert coordinator.data["ph_raw"] == pytest.approx(6.58)
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD


async def test_own_calibration_saved_in_the_options_applies_at_once(
    hass, coordinator, ble
):
    await _analysis(coordinator, ble)
    assert coordinator.data["ph"] == pytest.approx(6.41)
    assert (
        coordinator.data["ph_hr_calibration_source"] == PH_HR_CALIBRATION_SOURCE_PROBE
    )

    own = {"ph_1": 4.0, "ph_2": 7.0, "mv_1": 170.0, "mv_2": 10.0}
    hass.config_entries.async_update_entry(
        coordinator.entry,
        options={
            **coordinator.entry.options,
            CONF_PH_HR_CALIB_MV_4: own["mv_1"],
            CONF_PH_HR_CALIB_MV_7: own["mv_2"],
        },
    )
    coordinator.recompute_derived_values()  # no new analysis in between
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert coordinator.data["ph"] == pytest.approx(
        compute_ph_two_point(37.1, own), abs=0.005
    )
    assert coordinator.data["ph"] != pytest.approx(6.41)
    assert (
        coordinator.data["ph_hr_calibration_source"]
        == PH_HR_CALIBRATION_SOURCE_INTEGRATION
    )

    # Emptying the two fields goes back to the probe's own calibration.
    options = dict(coordinator.entry.options)
    options.pop(CONF_PH_HR_CALIB_MV_4)
    options.pop(CONF_PH_HR_CALIB_MV_7)
    hass.config_entries.async_update_entry(coordinator.entry, options=options)
    coordinator.recompute_derived_values()
    assert coordinator.data["ph"] == pytest.approx(6.41)
    assert (
        coordinator.data["ph_hr_calibration_source"] == PH_HR_CALIBRATION_SOURCE_PROBE
    )


async def test_own_calibration_applies_to_a_standard_analysis_at_once(
    hass, coordinator, ble
):
    """A probe without a usable calibration: filling in one gives the 2 decimals."""
    _arm(ble, mv=25.0)
    del ble.client.reads[UUID_PH_CALIB_MV_1]
    await coordinator.async_refresh()
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD
    hass.config_entries.async_update_entry(
        coordinator.entry,
        options={
            **coordinator.entry.options,
            CONF_PH_HR_CALIB_MV_4: 170.0,
            CONF_PH_HR_CALIB_MV_7: 10.0,
        },
    )
    coordinator.recompute_derived_values()
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert coordinator.data["ph_hr_calibration_source"] == (
        PH_HR_CALIBRATION_SOURCE_INTEGRATION
    )


async def test_recompute_falls_back_to_the_calibration_kept_with_the_ph(
    coordinator, ble
):
    """The probe's calibration cache is gone: the one used by the last analysis stays."""
    await _analysis(coordinator, ble)
    coordinator.data.pop("probe_ph_calibration")
    coordinator.recompute_derived_values()
    assert coordinator.data["ph"] == pytest.approx(6.41)
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert (
        coordinator.data["ph_hr_calibration_source"] == PH_HR_CALIBRATION_SOURCE_PROBE
    )


async def test_passive_frame_replaces_the_high_resolution_ph(coordinator, ble):
    await _analysis(coordinator, ble)
    coordinator._on_ble_seen(_seen(build_frame(ph=6.4, battery_adc=3990)), None)
    data = coordinator.data
    assert data["ph"] == pytest.approx(6.4)
    assert data["ph_source"] == PH_SOURCE_STANDARD
    assert data["ph_raw_mv"] is None
    assert data["ph_hr_calibration"] is None
    assert data["ph_hr_available"] is True  # capability, kept


# ---------------------------------------------------------------------------
# Calibration cache: 0015-0018 are re-read only when the calibration
# timestamp (0029) has changed, since those 4 registers practically never
# change between two calibrations done with the probe's own app.
# ---------------------------------------------------------------------------
def _set_calibration_timestamp(ble, raw: bytes) -> None:
    ble.client.reads[CHAR_LAST_PH_CALIB_UUID] = raw


async def test_unchanged_timestamp_reuses_the_cached_calibration(coordinator, ble):
    _set_calibration_timestamp(ble, (1_700_000_000).to_bytes(4, "big"))
    await _analysis(coordinator, ble)
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert coordinator.data["ph_calibration_source_ts"] == 1_700_000_000

    _arm(ble)
    _set_calibration_timestamp(ble, (1_700_000_000).to_bytes(4, "big"))
    for uuid in (
        UUID_PH_CALIB_PH_1,
        UUID_PH_CALIB_PH_2,
        UUID_PH_CALIB_MV_1,
        UUID_PH_CALIB_MV_2,
    ):
        del ble.client.reads[uuid]  # the registers are removed: must not be read
    await coordinator.async_refresh()
    assert coordinator.data["ph"] == pytest.approx(6.41)  # served from the cache
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION


async def test_changed_timestamp_forces_a_fresh_read(coordinator, ble):
    _set_calibration_timestamp(ble, (1_700_000_000).to_bytes(4, "big"))
    await _analysis(coordinator, ble)
    assert coordinator.data["ph_calibration_source_ts"] == 1_700_000_000

    # A different slope (mv_1=200.0 instead of 178.2): 37.1 mV now rounds to
    # 6.5, not 6.4, so the calculated frame's pH must say 6.5 too.
    _arm(ble, calc_ph=6.5, calibration=ph_calibration_reads(mv_1=200.0))
    _set_calibration_timestamp(ble, (1_800_000_000).to_bytes(4, "big"))
    await coordinator.async_refresh()
    assert coordinator.data["ph_calibration_source_ts"] == 1_800_000_000
    assert coordinator.data["ph_hr_calibration"]["mv_1"] == 200.0
    assert coordinator.data["ph"] == pytest.approx(6.48, abs=1e-2)


async def test_unreadable_timestamp_is_not_cached(coordinator, ble):
    _set_calibration_timestamp(ble, b"\x01\x02")  # too short to be a timestamp
    await _analysis(coordinator, ble)
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert coordinator.data.get("ph_calibration_source_ts") is None


# ---------------------------------------------------------------------------
# Integration-side mV calibration: off by default, takes priority over the
# probe's own calibration when turned on.
# ---------------------------------------------------------------------------
def test_integration_calibration_is_none_when_the_mv_fields_are_empty(coordinator):
    assert coordinator._integration_ph_hr_calibration() is None


async def test_integration_calibration_takes_priority_over_the_probe(
    hass, setup_integration, ble
):
    from custom_components.blue_connect_local.const import (
        CONF_PH_HR_CALIB_MV_4,
        CONF_PH_HR_CALIB_MV_7,
        PH_HR_CALIBRATION_SOURCE_INTEGRATION,
    )

    coordinator = await setup_integration(
        make_entry(
            **{
                CONF_PH_HR_CALIB_MV_4: 177.0,
                CONF_PH_HR_CALIB_MV_7: 0.0,
            }
        )
    )
    _arm(ble)
    # The probe's own registers are removed: the integration's calibration
    # must be used without even reading them.
    for uuid in (
        UUID_PH_CALIB_PH_1,
        UUID_PH_CALIB_PH_2,
        UUID_PH_CALIB_MV_1,
        UUID_PH_CALIB_MV_2,
    ):
        del ble.client.reads[uuid]
    await coordinator.async_refresh()
    data = coordinator.data
    assert data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert data["ph_hr_calibration_source"] == PH_HR_CALIBRATION_SOURCE_INTEGRATION
    assert data["ph_hr_calibration"] == {
        "ph_1": 4.0,
        "ph_2": 7.0,
        "mv_1": 177.0,
        "mv_2": 0.0,
    }
    assert data["ph"] == pytest.approx(6.37, abs=1e-2)


async def test_disabled_integration_calibration_still_reads_the_probe(coordinator, ble):
    from custom_components.blue_connect_local.const import (
        PH_HR_CALIBRATION_SOURCE_PROBE,
    )

    await _analysis(coordinator, ble)
    assert (
        coordinator.data["ph_hr_calibration_source"] == PH_HR_CALIBRATION_SOURCE_PROBE
    )


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------
async def test_ph_attributes_tell_the_source(hass, coordinator, ble):
    ph_entity = entity_id(hass, "sensor", "ph")
    assert hass.states.get(ph_entity).attributes.get("source") is None

    await _analysis(coordinator, ble)
    await hass.async_block_till_done()
    state = hass.states.get(ph_entity)
    assert state.state == "6.41"
    assert state.attributes["source"] == "high_resolution"
    assert state.attributes["resolution"] == 0.01

    coordinator._on_ble_seen(_seen(build_frame(ph=6.4, battery_adc=3990)), None)
    await hass.async_block_till_done()
    state = hass.states.get(ph_entity)
    assert state.state == "6.4"
    assert state.attributes["source"] == "standard"
    assert state.attributes["resolution"] == 0.1


async def test_ph_attributes_are_not_shown_on_a_blueriiot_probe(hass, coordinator, ble):
    from custom_components.blue_connect_local.const import DEVICE_TYPE_BLUERIIOT

    await _analysis(coordinator, ble)
    coordinator.data["device_type"] = DEVICE_TYPE_BLUERIIOT
    coordinator.async_set_updated_data(coordinator.data)
    await hass.async_block_till_done()
    attributes = hass.states.get(entity_id(hass, "sensor", "ph")).attributes
    assert "source" not in attributes
    assert "resolution" not in attributes


@pytest.mark.usefixtures("all_sensors_enabled")
async def test_raw_ph_millivolt_sensor(hass, coordinator, ble):
    mv_entity = entity_id(hass, "sensor", "ph_raw_mv")
    await _analysis(coordinator, ble)
    await hass.async_block_till_done()
    state = hass.states.get(mv_entity)
    assert state.state == "37.1"
    assert state.attributes["unit_of_measurement"] == "mV"

    coordinator._on_ble_seen(_seen(build_frame(ph=6.4, battery_adc=3990)), None)
    await hass.async_block_till_done()
    assert hass.states.get(mv_entity).state == "unknown"  # no stale value


@pytest.mark.usefixtures("all_sensors_enabled")
async def test_raw_ph_millivolt_sensor_needs_an_access_code(
    hass, setup_integration, ble
):
    await setup_integration(make_entry(access_code=None))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "sensor", "ph_raw_mv")).state == (
        "unavailable"
    )


# ---------------------------------------------------------------------------
# Repair suggestion: stop using the passive frames
# ---------------------------------------------------------------------------
def _issue(hass, coordinator):
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"passive_hr_{coordinator.entry_id}"
    )


async def test_repair_is_suggested_once_high_resolution_works(hass, coordinator, ble):
    assert _issue(hass, coordinator) is None
    await _analysis(coordinator, ble)
    issue = _issue(hass, coordinator)
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_key == "passive_high_resolution"
    assert issue.data == {"entry_id": coordinator.entry.entry_id}


async def test_repair_is_not_suggested_without_high_resolution(hass, coordinator, ble):
    _arm(ble)
    del ble.client.reads[UUID_RAW_SENSORS]  # no electrical frame: no high resolution
    await coordinator.async_refresh()
    assert _issue(hass, coordinator) is None


async def test_repair_is_not_suggested_when_passive_frames_are_off(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(make_entry(**{CONF_PASSIVE_MEASURES: False}))
    await _analysis(coordinator, ble)
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert _issue(hass, coordinator) is None


async def test_repair_stays_when_a_passive_frame_arrives(hass, coordinator, ble):
    await _analysis(coordinator, ble)
    coordinator._on_ble_seen(_seen(build_frame(ph=6.4, battery_adc=3990)), None)
    assert _issue(hass, coordinator) is not None


async def test_repair_follows_the_passive_switch(hass, coordinator, ble):
    await _analysis(coordinator, ble)
    assert _issue(hass, coordinator) is not None
    coordinator.update_local_state({CONF_PASSIVE_MEASURES: False})
    assert _issue(hass, coordinator) is None
    coordinator.update_local_state({CONF_PASSIVE_MEASURES: True})
    assert _issue(hass, coordinator) is not None


async def test_repair_is_restored_from_a_previous_run(hass, coordinator):
    coordinator.data.update(
        {"ph_hr_available": True, "ph_example_hr": 6.43, "ph_example_low": 6.4}
    )
    coordinator._sync_passive_issue()
    assert _issue(hass, coordinator) is not None


async def test_repair_waits_for_example_values(hass, coordinator):
    # Flag saved by an earlier version: no pH values to show yet.
    coordinator.data["ph_hr_available"] = True
    coordinator._sync_passive_issue()
    assert _issue(hass, coordinator) is None


async def test_repair_shows_the_real_ph_values(hass, coordinator, ble):
    await _analysis(coordinator, ble)
    placeholders = _issue(hass, coordinator).translation_placeholders
    assert placeholders == {
        "name": coordinator.display_label,
        "ph_hr": f"{coordinator.data['ph']:.2f}",
        "ph_low": "6.4",
    }


async def test_repair_values_follow_the_language(hass, coordinator, ble):
    hass.config.language = "fr"
    await _analysis(coordinator, ble)
    placeholders = _issue(hass, coordinator).translation_placeholders
    assert placeholders["ph_low"] == "6,4"
    assert "," in placeholders["ph_hr"]


async def test_repair_values_are_refreshed_by_each_analysis(hass, coordinator, ble):
    await _analysis(coordinator, ble)
    assert _issue(hass, coordinator).translation_placeholders["ph_low"] == "6.4"
    await _analysis(coordinator, ble, calc_ph=6.8)
    assert _issue(hass, coordinator).translation_placeholders["ph_low"] == "6.8"


async def test_repair_stays_ignored_when_its_values_are_refreshed(
    hass, coordinator, ble
):
    await _analysis(coordinator, ble)
    ir.async_ignore_issue(hass, DOMAIN, _issue(hass, coordinator).issue_id, True)
    await _analysis(coordinator, ble, calc_ph=6.8)
    issue = _issue(hass, coordinator)
    assert issue.translation_placeholders["ph_low"] == "6.8"
    assert issue.dismissed_version is not None


async def test_repair_is_not_created_while_shutting_down(hass, coordinator):
    coordinator.data["ph_hr_available"] = True
    coordinator._is_shutdown = True
    coordinator._sync_passive_issue()
    assert _issue(hass, coordinator) is None
    coordinator._is_shutdown = False


async def test_fix_flow_stops_using_the_passive_frames(hass, coordinator, ble):
    await _analysis(coordinator, ble)
    issue = _issue(hass, coordinator)
    flow = await async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = issue.issue_id

    form = await flow.async_step_init()
    assert form["type"] == "form"
    assert form["step_id"] == "confirm"
    assert coordinator._passive_frames_enabled()  # nothing changes before confirm
    assert set(form["description_placeholders"]) == {"name", "ph_hr", "ph_low"}
    # Every language can be rendered with what the dialog really receives
    # (a missing variable breaks the whole repair dialog in the frontend).
    for path in [
        *COMPONENT_DIR.glob("translations/*.json"),
        COMPONENT_DIR / "strings.json",
    ]:
        confirm = json.loads(path.read_text(encoding="utf-8"))["issues"][
            "passive_high_resolution"
        ]["fix_flow"]["step"]["confirm"]
        confirm["description"].format(**form["description_placeholders"])

    done = await flow.async_step_confirm({})
    assert done["type"] == "create_entry"
    assert not coordinator._passive_frames_enabled()
    assert _issue(hass, coordinator) is None


@pytest.mark.parametrize("data", [None, {"entry_id": "unknown"}, {"entry_id": 3}])
async def test_fix_flow_without_a_loaded_probe_just_clears_the_issue(hass, data):
    ir.async_create_issue(
        hass,
        DOMAIN,
        "passive_hr_gone",
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="passive_high_resolution",
        translation_placeholders={"name": "gone"},
    )
    flow = await async_create_fix_flow(hass, "passive_hr_gone", data)
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = "passive_hr_gone"

    done = await flow.async_step_confirm({})
    assert done["type"] == "create_entry"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "passive_hr_gone") is None


# ---------------------------------------------------------------------------
# Setup form
# ---------------------------------------------------------------------------
from unittest.mock import AsyncMock, patch  # noqa: E402

from custom_components.blue_connect_local.const import CONF_ACCESS_CODE  # noqa: E402

from .test_flows import (  # noqa: E402
    DISCOVERED,
    SETUP,
    _default_of,
    _info,
    _sections,
    _start_discovery,
)


async def _submit_setup(hass, *, access_code: str | None, passive: bool):
    frame = build_frame(conductivity=1200)
    with (
        patch(DISCOVERED, return_value=[_info(frame)]),
        patch(SETUP, return_value=True),
    ):
        result = await _start_discovery(hass, frame)
        selection = _default_of(result, "mac_address")
        user_input = {
            "mac_address": selection,
            **_sections(synchronization={CONF_PASSIVE_MEASURES: passive}),
        }
        if access_code:
            user_input[CONF_ACCESS_CODE] = access_code
        return result, await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )


async def test_setup_form_leaves_the_passive_frames_off_by_default(hass):
    form, _ = await _submit_setup(hass, access_code=ACCESS_CODE, passive=False)
    sync = form["data_schema"].schema["synchronization"].schema.schema
    defaults = {str(k): k.default() for k in sync}
    assert defaults[CONF_PASSIVE_MEASURES] is False


@pytest.mark.parametrize("passive", [False, True])
async def test_setup_with_an_access_code_keeps_the_passive_choice(hass, passive):
    _, result = await _submit_setup(hass, access_code=ACCESS_CODE, passive=passive)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_PASSIVE_MEASURES] is passive


async def test_setup_without_an_access_code_forces_the_passive_frames(hass):
    _, result = await _submit_setup(hass, access_code=None, passive=False)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ACCESS_CODE] == ""
    assert result["options"][CONF_PASSIVE_MEASURES] is True


# ---------------------------------------------------------------------------
# Sending the integration's calibration to the probe (tick box of the options)
# ---------------------------------------------------------------------------
def _calib_entry(**extra):
    from custom_components.blue_connect_local.const import (
        CONF_PH_HR_CALIB_MV_4,
        CONF_PH_HR_CALIB_MV_7,
    )

    return make_entry(
        **{
            CONF_PH_HR_CALIB_MV_4: 177.0,
            CONF_PH_HR_CALIB_MV_7: 0.0,
            **extra,
        }
    )


async def test_request_without_an_access_code_does_nothing(setup_integration):
    from custom_components.blue_connect_local.const import CONF_ACCESS_CODE

    coordinator = await setup_integration(_calib_entry(**{CONF_ACCESS_CODE: ""}))
    assert coordinator.request_calibration_push() is False
    assert coordinator._calibration_push_pending is False


async def test_request_on_a_blueriiot_probe_does_nothing(setup_integration):
    from custom_components.blue_connect_local.const import DEVICE_TYPE_BLUERIIOT

    coordinator = await setup_integration(_calib_entry())
    coordinator.data["device_type"] = DEVICE_TYPE_BLUERIIOT
    assert coordinator.request_calibration_push() is False
    assert coordinator._calibration_push_pending is False


async def test_request_is_kept_in_memory_only(setup_integration):
    coordinator = await setup_integration(_calib_entry())
    assert coordinator.request_calibration_push() is True
    assert coordinator._calibration_push_pending is True
    # Never part of the data saved to disk: a restart cannot trigger a write.
    assert "ph_calibration_push_pending" not in coordinator.data


async def test_requested_push_writes_the_four_registers(hass, setup_integration, ble):
    coordinator = await setup_integration(_calib_entry())
    _arm(ble)
    assert coordinator.request_calibration_push() is True
    await coordinator.async_refresh()

    assert coordinator._calibration_push_pending is False
    writes = dict(ble.client.writes)
    assert writes[UUID_PH_CALIB_PH_1] == (40).to_bytes(2, "big")
    assert writes[UUID_PH_CALIB_PH_2] == (70).to_bytes(2, "big")
    assert writes[UUID_PH_CALIB_MV_1] == (1770).to_bytes(2, "big", signed=True)
    assert writes[UUID_PH_CALIB_MV_2] == (0).to_bytes(2, "big", signed=True)
    # The probe's calibration cache must not survive a fresh write.
    assert "ph_calibration_source_ts" not in coordinator.data


async def test_a_failed_write_does_not_retry_itself(hass, setup_integration, ble):
    coordinator = await setup_integration(_calib_entry())
    _arm(ble)
    ble.client.write_errors = [None, OSError("gone")]
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    assert coordinator._calibration_push_pending is False


async def test_push_is_dropped_when_the_calibration_was_turned_off(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(make_entry())
    _arm(ble)
    assert coordinator.request_calibration_push() is True
    await coordinator.async_refresh()
    assert coordinator._calibration_push_pending is False
    assert UUID_PH_CALIB_PH_1 not in dict(ble.client.writes)


# ---------------------------------------------------------------------------
# The tick box in the options form
# ---------------------------------------------------------------------------
from .test_flows import _options_input  # noqa: E402


def _push_input(*, with_mv=True, access_code=ACCESS_CODE, tick=True):
    from custom_components.blue_connect_local.const import (
        CONF_CALIB_PUSH,
        CONF_PH_HR_CALIB_MV_4,
        CONF_PH_HR_CALIB_MV_7,
    )

    mv = {CONF_PH_HR_CALIB_MV_4: 177.0, CONF_PH_HR_CALIB_MV_7: 0.0} if with_mv else {}
    return _options_input(
        access_code=access_code,
        probes_calibration={**mv, CONF_CALIB_PUSH: tick},
    )


async def test_options_tick_requests_the_push_and_is_never_stored(
    hass, entry, coordinator
):
    from custom_components.blue_connect_local.const import CONF_CALIB_PUSH

    coordinator.async_request_refresh = AsyncMock()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _push_input()
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_CALIB_PUSH not in result["data"]
    assert CONF_CALIB_PUSH not in coordinator.data
    assert coordinator._calibration_push_pending is True
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator.async_request_refresh.assert_awaited()


async def test_options_without_the_tick_do_not_push(hass, entry, coordinator):
    coordinator.async_request_refresh = AsyncMock()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _push_input(tick=False)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert coordinator._calibration_push_pending is False


@pytest.mark.parametrize(("with_mv", "access_code"), [(False, ACCESS_CODE), (True, "")])
async def test_options_tick_is_refused_when_it_cannot_work(
    hass, entry, coordinator, with_mv, access_code
):
    from custom_components.blue_connect_local.const import CONF_CALIB_PUSH

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _push_input(with_mv=with_mv, access_code=access_code)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CALIB_PUSH: "calib_push_unavailable"}
    assert coordinator._calibration_push_pending is False


async def test_options_tick_is_refused_on_a_blueriiot_probe(hass, entry, coordinator):
    from custom_components.blue_connect_local.const import (
        CONF_CALIB_PUSH,
        DEVICE_TYPE_BLUERIIOT,
    )

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "device_type": DEVICE_TYPE_BLUERIIOT}
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _push_input()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CALIB_PUSH: "calib_push_unavailable"}


# ---------------------------------------------------------------------------
# The "probe calibration" diagnostic sensor (registers 70ea0015..0018)
# ---------------------------------------------------------------------------
def _calibration_sensor(coordinator):
    from homeassistant.const import EntityCategory

    from custom_components.blue_connect_local.sensor import BlueConnectSensor

    from .helpers import MAC

    return BlueConnectSensor(
        coordinator,
        MAC,
        "probe_ph_calibration",
        category=EntityCategory.DIAGNOSTIC,
        enabled_default=False,
    )


async def test_calibration_sensor_shows_both_points_in_one_line(coordinator):
    sensor = _calibration_sensor(coordinator)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes is None
    coordinator.data["probe_ph_calibration"] = CALIBRATION
    assert sensor.native_value == "pH 7.0 = 2.8 mV · pH 4.0 = 178.2 mV"
    assert sensor.extra_state_attributes == CALIBRATION
    # pH 7 stays first whatever the order of the probe's two points.
    coordinator.data["probe_ph_calibration"] = {
        "ph_1": 7.0,
        "ph_2": 4.0,
        "mv_1": 2.8,
        "mv_2": 178.2,
    }
    assert sensor.native_value == "pH 7.0 = 2.8 mV · pH 4.0 = 178.2 mV"


async def test_calibration_sensor_is_unavailable_without_access_code_or_on_blueriiot(
    coordinator,
):
    sensor = _calibration_sensor(coordinator)
    assert sensor.available is True
    coordinator.data["device_type"] = "blueriiot"
    assert sensor.available is False
    coordinator.data["device_type"] = "zodiac"
    coordinator.data["access_code"] = ""
    assert sensor.available is False


async def test_registers_are_read_for_the_sensor_even_with_own_calibration(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(_calib_entry())
    _arm(ble)
    with patch.object(
        coordinator, "_probe_calibration_sensor_enabled", return_value=True
    ):
        await coordinator.async_refresh()
    assert coordinator.data["probe_ph_calibration"] == CALIBRATION
    # The pH itself still uses the integration's calibration.
    assert coordinator.data["ph_hr_calibration_source"] == "integration"
    assert coordinator.data["ph_hr_calibration"]["mv_1"] == 177.0


async def test_registers_are_not_read_when_nobody_needs_them(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(_calib_entry())
    await _analysis(coordinator, ble)
    assert coordinator.data["ph_source"] == PH_SOURCE_HIGH_RESOLUTION
    assert coordinator.data.get("probe_ph_calibration") is None


async def test_registers_are_read_for_the_sensor_without_electrical_frame(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(make_entry())
    _arm(ble)
    del ble.client.reads[UUID_RAW_SENSORS]
    with patch.object(
        coordinator, "_probe_calibration_sensor_enabled", return_value=True
    ):
        await coordinator.async_refresh()
    assert coordinator.data["probe_ph_calibration"] == CALIBRATION
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD


async def test_sensor_enabled_lookup_follows_the_entity_registry(coordinator):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    registry = MagicMock()
    target = "custom_components.blue_connect_local.coordinator.er.async_get"
    with patch(target, return_value=registry):
        registry.async_get_entity_id.return_value = None
        assert coordinator._probe_calibration_sensor_enabled() is False
        registry.async_get_entity_id.return_value = "sensor.probe_ph_calibration"
        registry.async_get.return_value = None
        assert coordinator._probe_calibration_sensor_enabled() is False
        registry.async_get.return_value = SimpleNamespace(disabled_by="integration")
        assert coordinator._probe_calibration_sensor_enabled() is False
        registry.async_get.return_value = SimpleNamespace(disabled_by=None)
        assert coordinator._probe_calibration_sensor_enabled() is True


# ---------------------------------------------------------------------------
# Checks on the integration's own mV calibration
# ---------------------------------------------------------------------------
from custom_components.blue_connect_local.validation import (  # noqa: E402
    validate_calibration,
)

_BASE_CALIBRATION = {
    "ph_calib_4": 4.0,
    "ph_calib_7": 7.0,
    "ph_ref_4": 4.0,
    "ph_ref_7": 7.0,
}


@pytest.mark.parametrize(
    "calibration",
    [
        {"ph_1": 4.0, "ph_2": 7.0, "mv_1": 177.0, "mv_2": 177.0},
        {"ph_1": 4.0, "ph_2": 4.0, "mv_1": 177.0, "mv_2": 0.0},
    ],
)
def test_two_point_formula_refuses_coinciding_points(calibration):
    with pytest.raises(ValueError, match="Degenerate"):
        compute_ph_two_point(10.0, calibration)


def test_empty_mv_calibration_is_not_checked():
    # Both empty: the calibration stored in the probe is used.
    assert isinstance(validate_calibration(dict(_BASE_CALIBRATION)), dict)
    data = {**_BASE_CALIBRATION, "ph_hr_calib_mv_4": "", "ph_hr_calib_mv_7": None}
    assert isinstance(validate_calibration(data), dict)


@pytest.mark.parametrize(
    ("given", "missing"),
    [
        ({"ph_hr_calib_mv_4": 177.0}, "ph_hr_calib_mv_7"),
        ({"ph_hr_calib_mv_7": 0.0}, "ph_hr_calib_mv_4"),
    ],
)
def test_mv_calibration_needs_both_values(given, missing):
    assert validate_calibration({**_BASE_CALIBRATION, **given}) == (
        missing,
        "ph_hr_mv_incomplete",
    )


def test_mv_calibration_must_have_two_different_values():
    data = {
        **_BASE_CALIBRATION,
        "ph_hr_calib_mv_4": 12.0,
        "ph_hr_calib_mv_7": 12.5,
    }
    assert validate_calibration(data) == (
        "ph_hr_calib_mv_7",
        "ph_hr_calibration_equal",
    )


def test_mv_calibration_pH4_must_read_higher_than_pH7():
    data = {
        **_BASE_CALIBRATION,
        "ph_hr_calib_mv_4": 0.0,
        "ph_hr_calib_mv_7": 177.0,
    }
    assert validate_calibration(data) == ("ph_hr_calib_mv_7", "ph_hr_slope_mismatch")


def test_mv_calibration_that_is_not_a_number_is_refused():
    data = {
        **_BASE_CALIBRATION,
        "ph_hr_calib_mv_4": "abc",
        "ph_hr_calib_mv_7": 0.0,
    }
    assert validate_calibration(data) == ("ph_hr_calib_mv_4", "unknown")


def test_valid_mv_calibration_is_kept_as_numbers():
    data = {
        **_BASE_CALIBRATION,
        "ph_hr_calib_mv_4": "177,5",
        "ph_hr_calib_mv_7": "0.5",
    }
    result = validate_calibration(data)
    assert isinstance(result, dict)
    assert result["ph_hr_calib_mv_4"] == pytest.approx(177.5)
    assert result["ph_hr_calib_mv_7"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("mv_4", "mv_7", "error"),
    [
        (10.0, 10.0, "ph_hr_calibration_equal"),
        (0.0, 100.0, "ph_hr_slope_mismatch"),
    ],
)
async def test_options_refuse_a_wrong_mv_calibration(
    hass, entry, coordinator, mv_4, mv_7, error
):
    from custom_components.blue_connect_local.const import (
        CONF_PH_HR_CALIB_MV_4,
        CONF_PH_HR_CALIB_MV_7,
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _options_input(
            probes_calibration={
                CONF_PH_HR_CALIB_MV_4: mv_4,
                CONF_PH_HR_CALIB_MV_7: mv_7,
            }
        ),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PH_HR_CALIB_MV_7: error}


async def test_a_stored_degenerate_mv_calibration_keeps_the_standard_ph(
    setup_integration, ble, caplog
):
    # Options edited by hand (or by an older version): no check in the form.
    coordinator = await setup_integration(
        _calib_entry(ph_hr_calib_mv_4=50.0, ph_hr_calib_mv_7=50.0)
    )
    with caplog.at_level(logging.WARNING):
        await _analysis(coordinator, ble)
    assert coordinator.data["ph_source"] == PH_SOURCE_STANDARD
    assert coordinator.data["ph"] == pytest.approx(6.4)
    assert "unusable" in caplog.text


def test_form_sections_put_the_mv_calibration_first_and_the_ph_values_apart():
    import inspect

    from custom_components.blue_connect_local import config_flow

    source = inspect.getsource(config_flow)
    assert source.index('"probes_calibration"') < source.index('"ph_value_calibration"')


def test_mv_calibration_targets_are_checked_too():
    data = {
        **_BASE_CALIBRATION,
        "ph_hr_calib_mv_4": 177.0,
        "ph_hr_calib_mv_7": 0.0,
        "ph_hr_ref_4": 7.0,
    }
    assert validate_calibration(data) == ("ph_hr_ref_4", "ph_ref_out_of_range")


def test_mv_calibration_targets_are_normalized():
    data = {
        **_BASE_CALIBRATION,
        "ph_hr_calib_mv_4": 177.0,
        "ph_hr_calib_mv_7": 0.0,
        "ph_hr_ref_4": "4,00",
        "ph_hr_ref_7": "7,02",
    }
    result = validate_calibration(data)
    assert result["ph_hr_ref_4"] == pytest.approx(4.0)
    assert result["ph_hr_ref_7"] == pytest.approx(7.02)


async def test_mv_calibration_uses_its_own_targets(setup_integration):
    coordinator = await setup_integration(
        _calib_entry(ph_hr_ref_4=4.0, ph_hr_ref_7=7.02, ph_ref_7=7.3, ph_ref_4=4.3)
    )
    calibration = coordinator._integration_ph_hr_calibration()
    assert calibration["ph_1"] == pytest.approx(4.0)
    assert calibration["ph_2"] == pytest.approx(7.02)


async def test_push_also_stamps_the_calibration_date(hass, setup_integration, ble):
    from homeassistant.util import dt as dt_util

    from custom_components.blue_connect_local.const import CHAR_LAST_PH_CALIB_UUID

    coordinator = await setup_integration(_calib_entry())
    _arm(ble)
    assert coordinator.request_calibration_push() is True
    await coordinator.async_refresh()

    stamp = dict(ble.client.writes)[CHAR_LAST_PH_CALIB_UUID]
    assert len(stamp) == 4
    assert abs(int.from_bytes(stamp, "big") - dt_util.utcnow().timestamp()) < 120


async def test_half_filled_stored_calibration_is_ignored(setup_integration):
    coordinator = await setup_integration(make_entry(ph_hr_calib_mv_4=177.0))
    assert coordinator._integration_ph_hr_calibration() is None


async def test_options_refuse_a_half_filled_mv_calibration(hass, entry, coordinator):
    from custom_components.blue_connect_local.const import (
        CONF_PH_HR_CALIB_MV_4,
        CONF_PH_HR_CALIB_MV_7,
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _options_input(probes_calibration={CONF_PH_HR_CALIB_MV_4: 177.0}),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PH_HR_CALIB_MV_7: "ph_hr_mv_incomplete"}


async def test_push_survives_a_refused_calibration_date(
    hass, setup_integration, ble, caplog, monkeypatch
):
    """The 4 registers are written; only the best-effort date stamp fails."""
    coordinator = await setup_integration(_calib_entry())
    _arm(ble)
    real_write = ble.client.write_gatt_char

    async def write(uuid, data, response=True):
        # Only the date stamp is refused, whatever the writes made before it.
        if uuid == CHAR_LAST_PH_CALIB_UUID:
            raise OSError("refused")
        await real_write(uuid, data, response)

    monkeypatch.setattr(ble.client, "write_gatt_char", write)
    with caplog.at_level(logging.WARNING):
        assert coordinator.request_calibration_push() is True
        await coordinator.async_refresh()

    assert coordinator._calibration_push_pending is False
    assert "could not be updated" in caplog.text
    assert dict(ble.client.writes)[UUID_PH_CALIB_MV_1] == (1770).to_bytes(
        2, "big", signed=True
    )


def test_integration_calibration_is_none_without_a_config_entry(
    coordinator, monkeypatch
):
    monkeypatch.setattr(type(coordinator), "entry", property(lambda self: None))
    assert coordinator._integration_ph_hr_calibration() is None


def test_mv_calibration_reference_that_is_not_a_number_is_refused():
    data = {
        **_BASE_CALIBRATION,
        "ph_hr_calib_mv_4": 177.0,
        "ph_hr_calib_mv_7": 0.0,
        "ph_hr_ref_4": "abc",
    }
    assert validate_calibration(data) == ("ph_hr_ref_4", "unknown")
