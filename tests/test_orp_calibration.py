"""ORP: electrical frame + the probe's own calibration, like the pH.

The calculated frame carries an ORP the probe already corrected with its own
calibration (ref - mes, signed 16-bit values in mV). The electrical frame
(70ea0005, word 2) carries the potential of the electrode before any
correction: with it the integration shows a real "raw" ORP, and can apply its
own calibration instead of stacking one on top of the probe's.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.blue_connect_local.chemistry import (
    compute_orp_calibrated,
    compute_orp_raw_from_calibrated,
    orp_calibration_offset,
    ph_calibration_quality,
)
from custom_components.blue_connect_local.const import (
    CHAR_LAST_ORP_CALIB_UUID,
    CONF_CALIB_PUSH,
    CONF_ORP_CALIB,
    CONF_ORP_REF,
    CONF_PH_HR_CALIB_MV_4,
    CONF_PH_HR_CALIB_MV_7,
    DEVICE_TYPE_BLUERIIOT,
    DOMAIN,
    ORP_CALIBRATION_SOURCE_INTEGRATION,
    ORP_CALIBRATION_SOURCE_PROBE,
)
from custom_components.blue_connect_local.coordinator import store_key
from custom_components.blue_connect_local.protocol import (
    parse_electrical_frame,
    parse_electrical_orp,
    parse_orp_calibration,
)
from custom_components.blue_connect_local.sensor import BlueConnectSensor
from custom_components.blue_connect_local.validation import validate_calibration

from .conftest import make_entry
from .helpers import (
    MAC,
    UUID_ORP_CALIB_MEAS,
    UUID_ORP_CALIB_REF,
    UUID_ORP_CALIB_STATUS,
    UUID_PH_CALIB_MV_1,
    UUID_RAW_SENSORS,
    build_electrical_frame,
    build_frame,
    clean_hex,
    orp_calibration_reads,
    ph_calibration_reads,
)
from .test_flows import _options_input

# Frames read from a real Blue Connect Gold on 6-13 November 2026: the ORP of
# the calculated frame is the raw potential of the electrical frame minus 4 mV
# (register ref 468, register mes 472).
REAL_ORP_FRAMES = [(775, 771), (794, 790), (759, 755)]
REAL_ELECTRICAL_FRAME = (
    "04340173031A012D091B080BFFF80EEB000409D403E80CC60CE70CD70EE7"  # 794 mV
)


def _seen(frame: bytes) -> SimpleNamespace:
    return SimpleNamespace(manufacturer_data={0x1234: frame}, service_data={})


def _arm(
    ble,
    *,
    frame_orp=689,
    raw_orp=693,
    ref=468,
    mes=472,
    ts=1794470254,
    electrical=True,
):
    """Next active analysis: calculated frame + electrical frame + calibration."""
    ble.client.frames[:] = [build_frame(orp_mv=frame_orp)]
    if electrical:
        ble.client.reads[UUID_RAW_SENSORS] = build_electrical_frame(orp_mv=raw_orp)
    else:
        ble.client.reads.pop(UUID_RAW_SENSORS, None)
    ble.client.reads.update(ph_calibration_reads())
    ble.client.reads.update(orp_calibration_reads(ref=ref, mes=mes, ts=ts))
    ble.client.is_connected = True


def _count_reads(ble) -> dict[str, int]:
    counts: dict[str, int] = {}
    real_read = ble.client.read_gatt_char

    async def read(uuid):
        counts[uuid] = counts.get(uuid, 0) + 1
        return await real_read(uuid)

    ble.client.read_gatt_char = read
    return counts


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------
def test_electrical_frame_gives_the_orp_potential():
    frame = bytes.fromhex(REAL_ELECTRICAL_FRAME)
    assert parse_electrical_orp(frame) == 794
    # The pH potential of the same frame is untouched.
    assert parse_electrical_frame(frame) == 37.1


def test_electrical_frame_orp_is_signed():
    assert parse_electrical_orp(build_electrical_frame(orp_mv=-120)) == -120


def test_electrical_frame_too_short_for_the_orp_is_ignored():
    assert parse_electrical_orp(bytes.fromhex("0102030405")) is None
    # ... while the same frame is long enough for the pH potential.
    assert parse_electrical_frame(bytes.fromhex("0102030405")) is not None


def test_orp_calibration_is_decoded():
    assert parse_orp_calibration(bytes.fromhex("01D4"), bytes.fromhex("01D8")) == {
        "ref": 468,
        "mes": 472,
    }
    # Registers read after the calibration made in the pool on 13 November.
    assert parse_orp_calibration(bytes.fromhex("01D4"), bytes.fromhex("02C7")) == {
        "ref": 468,
        "mes": 711,
    }


def test_orp_calibration_registers_are_signed():
    assert parse_orp_calibration(b"\xff\x9c", b"\xff\x38") == {"ref": -100, "mes": -200}


@pytest.mark.parametrize(
    ("ref", "mes"),
    [
        (b"\x00\x00", b"\x01\xd8"),  # unwritten
        (b"\x01\xd4", b"\x00\x00"),
        (b"\xff\xff", b"\x01\xd8"),  # erased flash
        (b"\x01\xd4", b"\xff\xff"),
        (b"\x27\x10", b"\x01\xd8"),  # 10 V: not a potential
        (b"\x01", b"\x01\xd8"),  # too short
        (b"\x01\xd4", b""),
    ],
)
def test_unusable_orp_calibration_is_refused(ref, mes):
    assert parse_orp_calibration(ref, mes) is None


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("raw", "calculated"), REAL_ORP_FRAMES)
def test_probe_correction_matches_real_frames(raw, calculated):
    assert compute_orp_calibrated(raw, 468, 472) == calculated
    assert compute_orp_raw_from_calibrated(calculated, 468, 472) == raw


def test_orp_offset_is_reference_minus_measured():
    assert orp_calibration_offset(468, 472) == -4
    assert orp_calibration_offset(468, 711) == -243


def test_ph_calibration_quality_of_a_real_probe():
    slope, offset = ph_calibration_quality(
        {"ph_1": 4.0, "ph_2": 7.0, "mv_1": 178.2, "mv_2": 2.8}
    )
    assert slope == pytest.approx(58.47, abs=0.01)  # about 99 % of 59.16
    assert offset == pytest.approx(2.8)


def test_ph_calibration_quality_does_not_depend_on_the_order_of_points():
    slope, offset = ph_calibration_quality(
        {"ph_1": 7.0, "ph_2": 4.0, "mv_1": 2.8, "mv_2": 178.2}
    )
    assert slope == pytest.approx(58.47, abs=0.01)
    assert offset == pytest.approx(2.8)


@pytest.mark.parametrize(
    "calibration",
    [
        {"ph_1": 4.0, "ph_2": 4.0, "mv_1": 100.0, "mv_2": 0.0},  # same pH
        {"ph_1": 4.0, "ph_2": 7.0, "mv_1": 50.0, "mv_2": 50.0},  # flat
        {"ph_1": 4.0, "ph_2": 7.0, "mv_1": 0.0, "mv_2": 170.0},  # wrong sign
    ],
)
def test_ph_calibration_quality_of_an_unusable_calibration(calibration):
    assert ph_calibration_quality(calibration) is None


# ---------------------------------------------------------------------------
# Options validation
# ---------------------------------------------------------------------------
_BASE = {"ph_calib_4": 4.0, "ph_calib_7": 7.0, "ph_ref_4": 4.0, "ph_ref_7": 7.0}


def test_empty_orp_calibration_is_stored_as_none():
    result = validate_calibration({**_BASE})
    assert result["orp_ref"] is None
    assert result["orp_calib"] is None
    result = validate_calibration({**_BASE, "orp_ref": "", "orp_calib": None})
    assert result["orp_ref"] is None
    assert result["orp_calib"] is None


def test_complete_orp_calibration_is_normalized_to_integers():
    result = validate_calibration({**_BASE, "orp_ref": "468", "orp_calib": 711.0})
    assert result["orp_ref"] == 468
    assert result["orp_calib"] == 711
    assert isinstance(result["orp_calib"], int)


def test_negative_orp_calibration_is_accepted():
    result = validate_calibration({**_BASE, "orp_ref": -50, "orp_calib": -80})
    assert (result["orp_ref"], result["orp_calib"]) == (-50, -80)


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"orp_ref": 468}, "orp_calib"),
        ({"orp_calib": 472}, "orp_ref"),
        ({"orp_ref": 468, "orp_calib": ""}, "orp_calib"),
    ],
)
def test_half_filled_orp_calibration_is_refused(data, field):
    assert validate_calibration({**_BASE, **data}) == (field, "orp_calib_incomplete")


@pytest.mark.parametrize(
    "data", [{"orp_ref": "abc", "orp_calib": 472}, {"orp_ref": 468, "orp_calib": "nan"}]
)
def test_orp_calibration_that_is_not_a_number_is_refused(data):
    assert validate_calibration({**_BASE, **data}) == ("orp_calib", "unknown")


# ---------------------------------------------------------------------------
# Active analysis
# ---------------------------------------------------------------------------
async def test_probe_calibration_is_read_and_shown(coordinator, ble):
    _arm(ble)
    await coordinator.async_refresh()
    data = coordinator.data
    assert data["probe_orp_calibration"] == {"ref": 468, "mes": 472, "status": 0}
    assert data["last_orp_calib"] == dt_util.utc_from_timestamp(1794470254)
    # Without an integration calibration the ORP is the probe's own.
    assert data["orp"] == 689
    assert data["orp_probe_calibrated"] == 689
    assert data["orp_raw_mv"] == 693
    assert data["orp_calibration_source"] == ORP_CALIBRATION_SOURCE_PROBE
    assert "orp_raw" not in data


async def test_integration_calibration_applies_to_the_raw_potential(
    setup_integration, ble
):
    # The probe holds the calibration made in the pool (468 vs 711 mV), the
    # integration its own one (468 vs 472): the integration's takes priority.
    coordinator = await setup_integration(
        make_entry(**{CONF_ORP_REF: 468, CONF_ORP_CALIB: 472})
    )
    _arm(ble, frame_orp=450, raw_orp=693, ref=468, mes=711)
    await coordinator.async_refresh()
    data = coordinator.data
    assert data["orp"] == 689  # 693 + (468 - 472), not the probe's 450
    assert data["orp_probe_calibrated"] == 450
    assert data["orp_raw_mv"] == 693
    assert data["orp_calibration_source"] == ORP_CALIBRATION_SOURCE_INTEGRATION


async def test_integration_calibration_is_not_stacked_on_the_probe_one(
    setup_integration, ble
):
    """The old behaviour added the integration's offset to an ORP that the
    probe had already corrected."""
    coordinator = await setup_integration(
        make_entry(**{CONF_ORP_REF: 650, CONF_ORP_CALIB: 640})
    )
    _arm(ble, frame_orp=689, raw_orp=693, ref=468, mes=472)
    await coordinator.async_refresh()
    assert coordinator.data["orp"] == 703  # 693 + 10, not 689 + 10 = 699


async def test_orp_without_the_electrical_frame_is_the_calculated_one(
    setup_integration, ble
):
    coordinator = await setup_integration(
        make_entry(**{CONF_ORP_REF: 468, CONF_ORP_CALIB: 472})
    )
    _arm(ble, electrical=False)
    await coordinator.async_refresh()
    # Raw potential recovered from the probe's calibration read in this analysis.
    assert coordinator.data["orp_raw_mv"] == 693
    assert coordinator.data["orp"] == 689


async def test_unusable_probe_calibration_keeps_the_calculated_orp(coordinator, ble):
    _arm(ble, ref=0)
    await coordinator.async_refresh()
    assert coordinator.data["probe_orp_calibration"] is None
    assert coordinator.data["orp"] == 689
    assert coordinator.data["orp_calibration_source"] is None


async def test_unreadable_probe_calibration_keeps_the_calculated_orp(
    coordinator, ble, caplog
):
    _arm(ble)
    del ble.client.reads[UUID_ORP_CALIB_MEAS]
    with caplog.at_level(logging.DEBUG):
        await coordinator.async_refresh()
    assert coordinator.data["probe_orp_calibration"] is None
    assert coordinator.data["orp"] == 689
    assert "Failed to read ORP calibration" in caplog.text


async def test_missing_calibration_date_does_not_break_the_analysis(
    coordinator, ble, caplog
):
    _arm(ble, ts=None)
    with caplog.at_level(logging.DEBUG):
        await coordinator.async_refresh()
    assert "Failed to read the last ORP calibration date" in caplog.text
    assert coordinator.data["probe_orp_calibration"]["ref"] == 468
    assert coordinator.data.get("last_orp_calib") is None
    assert coordinator.data["orp"] == 689


async def test_truncated_calibration_date_is_ignored(coordinator, ble):
    _arm(ble)
    ble.client.reads[CHAR_LAST_ORP_CALIB_UUID] = b"\x6a\xf5"
    await coordinator.async_refresh()
    assert coordinator.data.get("last_orp_calib") is None
    assert coordinator.data["probe_orp_calibration"]["ref"] == 468


async def test_unreadable_status_code_keeps_the_calibration(coordinator, ble, caplog):
    _arm(ble)
    del ble.client.reads[UUID_ORP_CALIB_STATUS]
    with caplog.at_level(logging.DEBUG):
        await coordinator.async_refresh()
    assert coordinator.data["probe_orp_calibration"] == {
        "ref": 468,
        "mes": 472,
        "status": None,
    }
    assert "Failed to read the ORP calibration status" in caplog.text


async def test_empty_status_code_is_unknown(coordinator, ble):
    _arm(ble)
    ble.client.reads[UUID_ORP_CALIB_STATUS] = b""
    await coordinator.async_refresh()
    assert coordinator.data["probe_orp_calibration"]["status"] is None


def test_integration_orp_calibration_is_none_without_a_config_entry(
    coordinator, monkeypatch
):
    monkeypatch.setattr(type(coordinator), "entry", property(lambda self: None))
    assert coordinator._integration_orp_calibration() is None


async def test_never_calibrated_probe_has_no_date(coordinator, ble):
    _arm(ble, ts=0)
    await coordinator.async_refresh()
    assert coordinator.data.get("last_orp_calib") is None
    assert coordinator.data["probe_orp_calibration"] is not None


async def test_calibration_registers_are_read_again_only_after_a_new_date(
    coordinator, ble
):
    counts = _count_reads(ble)
    _arm(ble)
    await coordinator.async_refresh()
    assert counts[UUID_ORP_CALIB_REF] == 1
    _arm(ble)
    await coordinator.async_refresh()
    assert counts[UUID_ORP_CALIB_REF] == 1  # same date: kept
    assert counts[CHAR_LAST_ORP_CALIB_UUID] == 2  # the date is always read
    # A calibration made in the pool (or with the app): new date, new registers.
    _arm(ble, ts=1794578971, mes=711, frame_orp=450)
    await coordinator.async_refresh()
    assert counts[UUID_ORP_CALIB_REF] == 2
    assert coordinator.data["probe_orp_calibration"]["mes"] == 711
    assert coordinator.data["last_orp_calib"] == dt_util.utc_from_timestamp(1794578971)


async def test_calibration_registers_are_read_every_time_without_a_date(
    coordinator, ble
):
    counts = _count_reads(ble)
    for _ in range(2):
        _arm(ble, ts=None)
        await coordinator.async_refresh()
    assert counts[UUID_ORP_CALIB_REF] == 2


# ---------------------------------------------------------------------------
# Frames the probe broadcasts on its own
# ---------------------------------------------------------------------------
async def test_passive_frame_gives_the_same_orp_as_an_active_one(
    setup_integration, ble
):
    coordinator = await setup_integration(
        make_entry(**{CONF_ORP_REF: 468, CONF_ORP_CALIB: 480})
    )
    _arm(ble)  # probe: -4 mV, integration: -12 mV, raw 693
    await coordinator.async_refresh()
    assert coordinator.data["orp"] == 681
    # A broadcast frame: the probe's ORP, raw potential 704 (700 + 4).
    coordinator._on_ble_seen(_seen(build_frame(orp_mv=700)), None)
    assert coordinator.data["receive_method"] == "passive"
    assert coordinator.data["orp_probe_calibrated"] == 700
    assert coordinator.data["orp_raw_mv"] == 704
    assert coordinator.data["orp"] == 692  # 704 - 12
    assert coordinator.data["orp_calibration_source"] == (
        ORP_CALIBRATION_SOURCE_INTEGRATION
    )


async def test_passive_frame_is_the_probe_orp_without_an_integration_calibration(
    coordinator, ble
):
    _arm(ble)
    await coordinator.async_refresh()
    coordinator._on_ble_seen(_seen(build_frame(orp_mv=700)), None)
    assert coordinator.data["orp"] == 700
    assert coordinator.data["orp_calibration_source"] == ORP_CALIBRATION_SOURCE_PROBE


async def test_passive_frame_before_the_probe_calibration_is_known(
    setup_integration, ble
):
    """No way to recover the raw potential yet: the probe's ORP is shown, never
    an integration offset stacked on a value the probe already corrected."""
    coordinator = await setup_integration(
        make_entry(**{CONF_ORP_REF: 468, CONF_ORP_CALIB: 480})
    )
    coordinator._on_ble_seen(_seen(build_frame(orp_mv=700)), None)
    assert coordinator.data["orp"] == 700
    assert coordinator.data["orp_raw_mv"] is None
    assert coordinator.data["orp_calibration_source"] is None


async def test_blueriiot_frame_is_already_the_raw_potential(setup_integration):
    """A Blueriiot probe has no calibration of its own."""
    coordinator = await setup_integration(
        make_entry(**{CONF_ORP_REF: 650, CONF_ORP_CALIB: 640})
    )
    coordinator.data["device_type"] = DEVICE_TYPE_BLUERIIOT
    parsed = {"temp_raw": 25.0, "ph_raw": 7.0, "orp_raw": 700, "battery_percent": 80}
    new_data = coordinator._apply_new_measurements(parsed, "AA")
    assert new_data["orp"] == 710
    assert new_data["orp_raw_mv"] is None
    assert new_data["orp_calibration_source"] == ORP_CALIBRATION_SOURCE_INTEGRATION
    coordinator.hass.config_entries.async_update_entry(
        coordinator.entry, options={CONF_ORP_REF: None, CONF_ORP_CALIB: None}
    )
    assert coordinator._apply_new_measurements(parsed, "AA")["orp"] == 700


async def test_changing_the_options_recomputes_the_orp(hass, setup_integration, ble):
    coordinator = await setup_integration(make_entry())
    _arm(ble)
    await coordinator.async_refresh()
    assert coordinator.data["orp"] == 689
    hass.config_entries.async_update_entry(
        coordinator.entry, options={CONF_ORP_REF: 468, CONF_ORP_CALIB: 480}
    )
    coordinator.recompute_derived_values()
    assert coordinator.data["orp"] == 681  # raw 693, offset -12
    hass.config_entries.async_update_entry(
        coordinator.entry, options={CONF_ORP_REF: None, CONF_ORP_CALIB: None}
    )
    coordinator.recompute_derived_values()
    assert coordinator.data["orp"] == 689


async def test_cleared_options_do_not_bring_back_an_old_value(hass, setup_integration):
    """A value entered when the entry was created lives in its data: the form
    stores None, which wins over it."""
    coordinator = await setup_integration(
        make_entry(**{CONF_ORP_REF: None, CONF_ORP_CALIB: None})
    )
    hass.config_entries.async_update_entry(
        coordinator.entry,
        data={**coordinator.entry.data, CONF_ORP_REF: 468, CONF_ORP_CALIB: 472},
    )
    assert coordinator._integration_orp_calibration() is None


# ---------------------------------------------------------------------------
# Storage and entry migration
# ---------------------------------------------------------------------------
async def test_stored_orp_raw_moves_to_probe_calibrated(
    setup_integration, hass_storage
):
    hass_storage[store_key(MAC)] = {
        "version": 1,
        "minor_version": 1,
        "key": store_key(MAC),
        "data": {"raw_frame": clean_hex(build_frame()), "orp": 690, "orp_raw": 688},
    }
    coordinator = await setup_integration(make_entry())
    assert coordinator.data["orp_probe_calibrated"] == 688
    assert "orp_raw" not in coordinator.data


async def test_stored_dates_and_probe_calibration_survive_a_restart(
    hass, setup_integration, ble, hass_storage
):
    coordinator = await setup_integration(make_entry())
    _arm(ble)
    await coordinator.async_refresh()
    await coordinator.async_save_to_disk()
    saved = hass_storage[store_key(MAC)]["data"]
    assert isinstance(saved["last_orp_calib"], str)
    assert saved["probe_orp_calibration"] == {"ref": 468, "mes": 472, "status": 0}
    await hass.config_entries.async_reload(coordinator.entry.entry_id)
    await hass.async_block_till_done()
    restored = coordinator.entry.runtime_data
    assert restored.data["last_orp_calib"] == dt_util.utc_from_timestamp(1794470254)
    assert restored.data["probe_orp_calibration"]["ref"] == 468


async def test_migration_moves_the_orp_entity_and_clears_the_old_calibration(
    hass, setup_integration
):
    entry = make_entry(minor_version=4, **{CONF_ORP_REF: 650, CONF_ORP_CALIB: 640})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_ORP_REF: 650, CONF_ORP_CALIB: 650}
    )
    reg = er.async_get(hass)
    old = reg.async_get_or_create(
        "sensor", DOMAIN, f"{MAC}_orp_raw", config_entry=entry
    )
    await setup_integration(entry)
    assert entry.minor_version == 5
    # Same entity (history, entity_id), new unique_id.
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_orp_raw") is None
    assert (
        reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_orp_probe_calibrated")
        == old.entity_id
    )
    # The integration's own ORP calibration no longer means what it did.
    for key in (CONF_ORP_REF, CONF_ORP_CALIB):
        assert key not in entry.options
        assert key not in entry.data


async def test_migration_keeps_the_other_options(hass, setup_integration):
    entry = make_entry(minor_version=4, **{CONF_ORP_REF: 650, "cya": 55})
    await setup_integration(entry)
    assert entry.options["cya"] == 55


async def test_migration_without_an_orp_entity_is_harmless(setup_integration):
    entry = make_entry(minor_version=4)
    await setup_integration(entry)
    assert entry.minor_version == 5


# ---------------------------------------------------------------------------
# Sending the calibrations to the probe
# ---------------------------------------------------------------------------
def _orp_entry(**extra):
    return make_entry(**{CONF_ORP_REF: 468, CONF_ORP_CALIB: 711, **extra})


def _both_entry(**extra):
    return _orp_entry(
        **{CONF_PH_HR_CALIB_MV_4: 177.0, CONF_PH_HR_CALIB_MV_7: 0.0, **extra}
    )


async def test_orp_push_writes_the_two_registers_and_the_date(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(_orp_entry())
    _arm(ble)
    assert coordinator.request_calibration_push() is True
    await coordinator.async_refresh()

    writes = dict(ble.client.writes)
    assert writes[UUID_ORP_CALIB_REF] == (468).to_bytes(2, "big", signed=True)
    assert writes[UUID_ORP_CALIB_MEAS] == (711).to_bytes(2, "big", signed=True)
    stamp = writes[CHAR_LAST_ORP_CALIB_UUID]
    assert len(stamp) == 4
    assert abs(int.from_bytes(stamp, "big") - dt_util.utcnow().timestamp()) < 120
    # Nothing filled in for the pH: not a single pH register is written.
    assert UUID_PH_CALIB_MV_1 not in writes
    assert coordinator.data["pushed_orp_calibration"] == {"ref": 468, "mes": 711}
    assert "pushed_ph_calibration" not in coordinator.data
    assert coordinator._calibration_push_pending is False


async def test_orp_push_is_written_before_the_measurement_is_triggered(
    setup_integration, ble
):
    coordinator = await setup_integration(_orp_entry())
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    order = [uuid for uuid, _ in ble.client.writes]
    assert order.index(UUID_ORP_CALIB_MEAS) < len(order) - 1
    assert ble.client.writes[-1][1] == b"\x02"  # the trigger comes last


async def test_orp_registers_are_read_again_after_a_push(setup_integration, ble):
    coordinator = await setup_integration(_orp_entry())
    _arm(ble)
    await coordinator.async_refresh()
    counts = _count_reads(ble)
    coordinator.request_calibration_push()
    _arm(ble)  # same date on the probe: only the push invalidates the cache
    await coordinator.async_refresh()
    assert counts[UUID_ORP_CALIB_REF] == 1
    assert "orp_calibration_source_ts" in coordinator.data  # refreshed afterwards


async def test_ph_registers_are_read_again_after_a_push(setup_integration, ble):
    """Even with the "Blue Connect pH calibration" sensor off (the default)."""
    coordinator = await setup_integration(
        make_entry(**{CONF_PH_HR_CALIB_MV_4: 177.0, CONF_PH_HR_CALIB_MV_7: 0.0})
    )
    counts = _count_reads(ble)
    _arm(ble)
    await coordinator.async_refresh()
    # Own calibration in use and nothing asking for the probe's: not read.
    assert counts.get(UUID_PH_CALIB_MV_1, 0) == 0
    assert coordinator.data.get("probe_ph_calibration") is None

    coordinator.request_calibration_push()
    _arm(ble)
    await coordinator.async_refresh()
    assert counts[UUID_PH_CALIB_MV_1] == 1  # read once, right after the write
    assert coordinator.data["probe_ph_calibration"] is not None
    assert coordinator._ph_calibration_reread is False

    _arm(ble)
    await coordinator.async_refresh()
    assert counts[UUID_PH_CALIB_MV_1] == 1  # and not on every analysis


async def test_unchanged_orp_calibration_is_not_written_again(setup_integration, ble):
    coordinator = await setup_integration(_orp_entry())
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    ble.client.writes.clear()

    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    written = {uuid for uuid, _ in ble.client.writes}
    assert UUID_ORP_CALIB_REF not in written
    assert CHAR_LAST_ORP_CALIB_UUID not in written  # no false date either


async def test_changed_orp_calibration_is_written_again(hass, setup_integration, ble):
    coordinator = await setup_integration(_orp_entry())
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    ble.client.writes.clear()

    hass.config_entries.async_update_entry(
        coordinator.entry, options={CONF_ORP_REF: 468, CONF_ORP_CALIB: 472}
    )
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    assert dict(ble.client.writes)[UUID_ORP_CALIB_MEAS] == (472).to_bytes(
        2, "big", signed=True
    )
    assert coordinator.data["pushed_orp_calibration"] == {"ref": 468, "mes": 472}


async def test_negative_orp_calibration_is_written_as_signed(setup_integration, ble):
    coordinator = await setup_integration(
        make_entry(**{CONF_ORP_REF: -50, CONF_ORP_CALIB: -80})
    )
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    writes = dict(ble.client.writes)
    assert writes[UUID_ORP_CALIB_REF] == b"\xff\xce"
    assert writes[UUID_ORP_CALIB_MEAS] == b"\xff\xb0"


async def test_failed_orp_write_is_not_remembered(setup_integration, ble):
    coordinator = await setup_integration(_orp_entry())
    _arm(ble)
    # 1st write = access code, 2nd = reference register, 3rd = measured one.
    ble.client.write_errors = [None, None, OSError("gone")]
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    assert "pushed_orp_calibration" not in coordinator.data
    assert coordinator._calibration_push_pending is False

    # Ticking the box again tries again: nothing was stored as sent.
    ble.client.writes.clear()
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    assert UUID_ORP_CALIB_MEAS in dict(ble.client.writes)
    assert coordinator.data["pushed_orp_calibration"] == {"ref": 468, "mes": 711}


async def test_orp_push_survives_a_refused_date(
    setup_integration, ble, caplog, monkeypatch
):
    coordinator = await setup_integration(_orp_entry())
    _arm(ble)
    real_write = ble.client.write_gatt_char

    async def write(uuid, data, response=True):
        if uuid == CHAR_LAST_ORP_CALIB_UUID:
            raise OSError("refused")
        await real_write(uuid, data, response)

    monkeypatch.setattr(ble.client, "write_gatt_char", write)
    with caplog.at_level(logging.WARNING):
        coordinator.request_calibration_push()
        await coordinator.async_refresh()
    assert "could not be updated" in caplog.text
    assert coordinator.data["pushed_orp_calibration"] == {"ref": 468, "mes": 711}


async def test_one_tick_sends_the_ph_and_the_orp(setup_integration, ble):
    coordinator = await setup_integration(_both_entry())
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    writes = dict(ble.client.writes)
    assert UUID_PH_CALIB_MV_1 in writes
    assert UUID_ORP_CALIB_REF in writes
    assert "pushed_ph_calibration" in coordinator.data
    assert "pushed_orp_calibration" in coordinator.data


async def test_changing_only_the_orp_does_not_rewrite_the_ph(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(_both_entry())
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    ble.client.writes.clear()

    options = dict(coordinator.entry.options)
    options[CONF_ORP_CALIB] = 500
    hass.config_entries.async_update_entry(coordinator.entry, options=options)
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    written = {uuid for uuid, _ in ble.client.writes}
    assert UUID_ORP_CALIB_MEAS in written
    assert UUID_PH_CALIB_MV_1 not in written  # and no new pH calibration date


async def test_changing_only_the_ph_does_not_rewrite_the_orp(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(_both_entry())
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    ble.client.writes.clear()

    options = dict(coordinator.entry.options)
    options[CONF_PH_HR_CALIB_MV_4] = 176.0
    hass.config_entries.async_update_entry(coordinator.entry, options=options)
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    written = {uuid for uuid, _ in ble.client.writes}
    assert UUID_PH_CALIB_MV_1 in written
    assert UUID_ORP_CALIB_REF not in written
    assert CHAR_LAST_ORP_CALIB_UUID not in written


async def test_failed_ph_write_does_not_block_the_orp(setup_integration, ble):
    coordinator = await setup_integration(_both_entry())
    _arm(ble)
    ble.client.write_errors = [None, OSError("gone")]  # 1st pH register fails
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    assert "pushed_ph_calibration" not in coordinator.data
    assert coordinator.data["pushed_orp_calibration"] == {"ref": 468, "mes": 711}


async def test_sent_calibrations_are_kept_in_storage(
    setup_integration, ble, hass_storage
):
    coordinator = await setup_integration(_both_entry())
    _arm(ble)
    coordinator.request_calibration_push()
    await coordinator.async_refresh()
    await coordinator.async_save_to_disk()
    saved = hass_storage[store_key(MAC)]["data"]
    assert saved["pushed_orp_calibration"] == {"ref": 468, "mes": 711}
    assert "pushed_ph_calibration" in saved


# ---------------------------------------------------------------------------
# The tick box of the options form
# ---------------------------------------------------------------------------
async def _submit_options(hass, entry, **probes):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], _options_input(probes_calibration=probes)
    )


async def test_tick_with_only_the_orp_filled_in_is_accepted(hass, entry, coordinator):
    result = await _submit_options(
        hass, entry, **{CONF_ORP_REF: 468, CONF_ORP_CALIB: 711, CONF_CALIB_PUSH: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_CALIB_PUSH not in result["data"]
    assert coordinator._calibration_push_pending is True
    assert result["data"][CONF_ORP_REF] == 468
    assert result["data"][CONF_ORP_CALIB] == 711


async def test_tick_with_nothing_to_send_is_refused(hass, entry, coordinator):
    result = await _submit_options(hass, entry, **{CONF_CALIB_PUSH: True})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CALIB_PUSH: "calib_push_unavailable"}
    assert coordinator._calibration_push_pending is False


async def test_half_filled_orp_calibration_is_refused_by_the_form(
    hass, entry, coordinator
):
    result = await _submit_options(hass, entry, **{CONF_ORP_REF: 468})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ORP_CALIB: "orp_calib_incomplete"}


async def test_form_stores_nothing_for_an_empty_orp_calibration(
    hass, entry, coordinator
):
    result = await _submit_options(hass, entry)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ORP_REF] is None
    assert result["data"][CONF_ORP_CALIB] is None
    assert coordinator._integration_orp_calibration() is None


async def test_form_is_empty_by_default_and_shows_the_stored_values(hass, entry):
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    section = result["data_schema"].schema["probes_calibration"].schema.schema
    fields = {str(key): key for key in section}
    for name in (CONF_ORP_REF, CONF_ORP_CALIB):
        assert fields[name].default is vol.UNDEFINED  # empty, not 650
        assert fields[name].description == {"suggested_value": None}


async def test_orp_calibration_that_the_probe_cannot_receive_is_refused_on_blueriiot(
    hass, entry, coordinator
):
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "device_type": DEVICE_TYPE_BLUERIIOT}
    )
    result = await _submit_options(
        hass, entry, **{CONF_ORP_REF: 468, CONF_ORP_CALIB: 711, CONF_CALIB_PUSH: True}
    )
    assert result["errors"] == {CONF_CALIB_PUSH: "calib_push_unavailable"}


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------
def _sensor(coordinator, key):
    return BlueConnectSensor(coordinator, MAC, key, enabled_default=False)


async def test_orp_calibration_sensor_shows_the_probe_calibration(coordinator):
    sensor = _sensor(coordinator, "probe_orp_calibration")
    assert sensor.native_value is None
    assert sensor.extra_state_attributes is None
    coordinator.data["probe_orp_calibration"] = {"ref": 468, "mes": 472, "status": 2}
    assert sensor.native_value == "ORP 468 mV = 472 mV"
    assert sensor.extra_state_attributes == {
        "reference": 468,
        "measured": 472,
        "correction": -4,
        "status_code": 2,
    }
    coordinator.data["probe_orp_calibration"] = {"ref": 468, "mes": 711, "status": None}
    assert sensor.native_value == "ORP 468 mV = 711 mV"
    assert sensor.extra_state_attributes["correction"] == -243
    assert "status_code" not in sensor.extra_state_attributes


async def test_orp_sensor_tells_which_calibration_it_used(coordinator):
    sensor = _sensor(coordinator, "orp")
    assert sensor.extra_state_attributes is None
    coordinator.data["orp_calibration_source"] = ORP_CALIBRATION_SOURCE_INTEGRATION
    assert sensor.extra_state_attributes == {"calibration_source": "integration"}
    coordinator.data["device_type"] = DEVICE_TYPE_BLUERIIOT
    assert sensor.extra_state_attributes is None


@pytest.mark.parametrize(
    "key", ["orp_raw_mv", "probe_orp_calibration", "last_orp_calib"]
)
async def test_zodiac_only_orp_sensors_need_an_access_code_and_a_zodiac(
    coordinator, key
):
    sensor = _sensor(coordinator, key)
    assert sensor.available is True
    coordinator.data["device_type"] = DEVICE_TYPE_BLUERIIOT
    assert sensor.available is False
    coordinator.data["device_type"] = "zodiac"
    coordinator.data["access_code"] = ""
    assert sensor.available is False


async def test_probe_calibrated_orp_stays_available_on_blueriiot(coordinator):
    """It replaces the old "Raw ORP", which Blueriiot users already have."""
    sensor = _sensor(coordinator, "orp_probe_calibrated")
    coordinator.data["device_type"] = DEVICE_TYPE_BLUERIIOT
    assert sensor.available is True


# ---------------------------------------------------------------------------
# Repairs for an abnormal calibration (never blocking)
# ---------------------------------------------------------------------------
def _issue(hass, entry, key):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{key}_{entry.entry_id}")


async def test_a_normal_calibration_raises_nothing(hass, coordinator, ble):
    _arm(ble)
    await coordinator.async_refresh()
    for key in ("orp_calibration", "ph_calibration_slope", "ph_calibration_offset"):
        assert _issue(hass, coordinator.entry, key) is None


async def test_a_large_orp_gap_raises_a_repair(hass, coordinator, ble, caplog):
    # What the app wrote when the probe was calibrated in the pool.
    _arm(ble, ref=468, mes=711)
    with caplog.at_level(logging.WARNING):
        await coordinator.async_refresh()
    issue = _issue(hass, coordinator.entry, "orp_calibration")
    assert issue is not None
    assert issue.translation_key == "orp_calibration_offset"
    assert issue.translation_placeholders["source"] == "ORP"
    assert issue.translation_placeholders["ecart"] == "243"
    assert issue.is_fixable is False
    assert issue.severity == ir.IssueSeverity.WARNING
    assert "abnormal ORP calibration" in caplog.text
    # Never blocking: the value is shown as usual.
    assert coordinator.data["orp"] == 689


async def test_the_gap_threshold_is_exclusive(hass, coordinator, ble):
    _arm(ble, ref=468, mes=568)  # exactly 100 mV
    await coordinator.async_refresh()
    assert _issue(hass, coordinator.entry, "orp_calibration") is None
    _arm(ble, ref=468, mes=569, ts=1794578971)  # 101 mV
    await coordinator.async_refresh()
    assert _issue(hass, coordinator.entry, "orp_calibration") is not None


async def test_the_repair_is_logged_once_and_cleared_when_fixed(
    hass, coordinator, ble, caplog
):
    _arm(ble, ref=468, mes=711)
    with caplog.at_level(logging.WARNING):
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert caplog.text.count("abnormal ORP calibration") == 1
    # A new calibration brings it back to normal: the repair goes away.
    _arm(ble, ref=468, mes=472, ts=1794578971)
    await coordinator.async_refresh()
    assert _issue(hass, coordinator.entry, "orp_calibration") is None


async def test_the_integration_calibration_is_judged_instead_of_the_probe_one(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(
        make_entry(**{CONF_ORP_REF: 468, CONF_ORP_CALIB: 472})
    )
    _arm(ble, ref=468, mes=711)  # abnormal, but not the one in use
    await coordinator.async_refresh()
    assert _issue(hass, coordinator.entry, "orp_calibration") is None
    hass.config_entries.async_update_entry(
        coordinator.entry, options={CONF_ORP_REF: 468, CONF_ORP_CALIB: 700}
    )
    coordinator.recompute_derived_values()
    assert _issue(hass, coordinator.entry, "orp_calibration") is not None


async def test_a_flat_electrode_raises_the_slope_repair(hass, coordinator, ble):
    _arm(ble)
    ble.client.reads.update(ph_calibration_reads(mv_1=90.0, mv_2=2.8))  # 29 mV/pH
    with patch_sensor_enabled(coordinator):
        await coordinator.async_refresh()
    issue = _issue(hass, coordinator.entry, "ph_calibration_slope")
    assert issue is not None
    assert issue.translation_key == "ph_calibration_slope"
    assert issue.translation_placeholders["source"] == "pH"
    assert issue.translation_placeholders["slope"] == "29.1"
    assert issue.translation_placeholders["min"] == "50"
    assert issue.translation_placeholders["max"] == "63"
    assert _issue(hass, coordinator.entry, "ph_calibration_offset") is None


async def test_a_large_ph_offset_raises_the_offset_repair(hass, coordinator, ble):
    _arm(ble)
    # Slope 60 mV/pH (fine) but 120 mV at pH 7.
    ble.client.reads.update(ph_calibration_reads(mv_1=300.0, mv_2=120.0))
    with patch_sensor_enabled(coordinator):
        await coordinator.async_refresh()
    issue = _issue(hass, coordinator.entry, "ph_calibration_offset")
    assert issue is not None
    assert issue.translation_placeholders["ecart"] == "+120.0"
    assert issue.translation_placeholders["limit"] == "60"
    assert _issue(hass, coordinator.entry, "ph_calibration_slope") is None


async def test_the_ph_calibration_of_the_integration_is_judged_when_filled_in(
    hass, setup_integration, ble
):
    coordinator = await setup_integration(
        make_entry(**{CONF_PH_HR_CALIB_MV_4: 100.0, CONF_PH_HR_CALIB_MV_7: 0.0})
    )
    _arm(ble)  # the probe's own calibration is fine
    await coordinator.async_refresh()
    issue = _issue(hass, coordinator.entry, "ph_calibration_slope")
    assert issue is not None  # 33 mV/pH
    assert issue.translation_placeholders["slope"] == "33.3"


async def test_no_repair_for_an_unusable_ph_calibration(hass, coordinator, ble):
    _arm(ble)
    ble.client.reads.update(ph_calibration_reads(mv_1=2.8, mv_2=2.8))
    with patch_sensor_enabled(coordinator):
        await coordinator.async_refresh()
    for key in ("ph_calibration_slope", "ph_calibration_offset"):
        assert _issue(hass, coordinator.entry, key) is None


async def test_blueriiot_has_no_probe_calibration_to_judge(hass, coordinator):
    coordinator.data["device_type"] = DEVICE_TYPE_BLUERIIOT
    coordinator.data["probe_orp_calibration"] = {"ref": 468, "mes": 900, "status": 0}
    coordinator._sync_calibration_issues()
    assert _issue(hass, coordinator.entry, "orp_calibration") is None


async def test_repairs_left_by_a_previous_instance_are_cleared(hass, coordinator):
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"orp_calibration_{coordinator.entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="orp_calibration_offset",
    )
    coordinator._sync_calibration_issues()
    assert _issue(hass, coordinator.entry, "orp_calibration") is None


def patch_sensor_enabled(coordinator):
    from unittest.mock import patch

    return patch.object(
        coordinator, "_probe_calibration_sensor_enabled", return_value=True
    )
