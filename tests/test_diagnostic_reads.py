"""Tests for the diagnostic GATT reads (hardware/firmware versions, dates,
probe serial number) of the Zodiac profile and for their sensors."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from homeassistant.helpers import device_registry as dr

from custom_components.blue_connect_local.const import (
    BT_STATUS_SUCCESS,
    CHAR_ESP32_FW_UUID,
    CHAR_FIRST_CONNECTION_UUID,
    CHAR_HW_VERSION_UUID,
    CHAR_LAST_PH_CALIB_UUID,
    CHAR_NRF_FW_UUID,
    CHAR_PROBE_REPLACEMENT_UUID,
    CHAR_PROBE_SERIAL_UUID,
)
from custom_components.blue_connect_local.coordinator import find_device, store_key
from custom_components.blue_connect_local.sensor import BlueConnectSensor

from .conftest import make_entry
from .helpers import MAC, build_frame

FIRST_TS = 1_700_000_000
CALIB_TS = 1_750_000_000
NEW_SENSORS = (
    "probe_serial_number",
    "first_connection",
    "probe_replacement",
    "last_ph_calib",
)


async def _refresh_again(coordinator, ble) -> None:
    """Run another active cycle: the fake probe answers one frame per trigger."""
    ble.client.frames.append(build_frame())
    ble.client.is_connected = True
    await coordinator.async_refresh()


def _diagnostic_reads() -> dict[str, bytes]:
    return {
        CHAR_HW_VERSION_UUID: bytes([3, 2, 1, 0]),
        CHAR_NRF_FW_UUID: bytes([4, 31, 0, 0]),
        CHAR_ESP32_FW_UUID: bytes([5, 13, 0, 0]),
        CHAR_FIRST_CONNECTION_UUID: FIRST_TS.to_bytes(4, "big"),
        CHAR_PROBE_REPLACEMENT_UUID: bytes(4),  # 0 = never replaced
        CHAR_LAST_PH_CALIB_UUID: CALIB_TS.to_bytes(4, "big"),
        CHAR_PROBE_SERIAL_UUID: b"PSN9876\x00",
    }


async def test_diagnostic_reads_populate_data(coordinator, ble):
    ble.client.reads.update(_diagnostic_reads())
    await coordinator.async_refresh()
    d = coordinator.data
    assert d["bluetooth_status"] == BT_STATUS_SUCCESS
    assert d["hardware_version"] == "1.2.3"
    assert d["firmware_version"] == "NRF 0.31.4 / ESP32 0.13.5"
    assert d["first_connection"] == datetime.fromtimestamp(FIRST_TS, tz=UTC)
    assert d["last_ph_calib"] == datetime.fromtimestamp(CALIB_TS, tz=UTC)
    assert d["probe_replacement"] is None  # timestamp 0 = never replaced
    assert d["probe_serial_number"] == "PSN9876"


async def test_firmware_version_with_a_single_chip(coordinator, ble):
    reads = _diagnostic_reads()
    del reads[CHAR_ESP32_FW_UUID]
    ble.client.reads.update(reads)
    await coordinator.async_refresh()
    assert coordinator.data["firmware_version"] == "NRF 0.31.4"


async def test_firmware_version_with_the_esp32_only(coordinator, ble):
    reads = _diagnostic_reads()
    del reads[CHAR_NRF_FW_UUID]
    ble.client.reads.update(reads)
    await coordinator.async_refresh()
    assert coordinator.data["firmware_version"] == "ESP32 0.13.5"


async def test_diagnostic_reads_that_fail_leave_the_cycle_successful(coordinator, ble):
    await coordinator.async_refresh()  # default reads: no diagnostic UUID
    assert coordinator.data["bluetooth_status"] == BT_STATUS_SUCCESS
    for key in (*NEW_SENSORS, "hardware_version", "firmware_version"):
        assert key not in coordinator.data


async def test_diagnostic_reads_ignore_short_or_undecodable_values(coordinator, ble):
    ble.client.reads.update(
        {
            CHAR_HW_VERSION_UUID: b"\x01",
            CHAR_NRF_FW_UUID: b"\x01",
            CHAR_ESP32_FW_UUID: b"\x01",
            CHAR_FIRST_CONNECTION_UUID: b"\x01",
            CHAR_PROBE_REPLACEMENT_UUID: b"\x01",
            CHAR_LAST_PH_CALIB_UUID: b"\x01",
            CHAR_PROBE_SERIAL_UUID: b"\xff\xfe",
        }
    )
    await coordinator.async_refresh()
    assert coordinator.data["bluetooth_status"] == BT_STATUS_SUCCESS
    for key in (*NEW_SENSORS, "hardware_version", "firmware_version"):
        assert key not in coordinator.data


async def test_device_registry_gets_hardware_and_firmware_versions(
    hass, coordinator, ble
):
    ble.client.reads.update(_diagnostic_reads())
    await coordinator.async_refresh()
    device = find_device(
        dr.async_get(hass), ("blue_connect_local", MAC), coordinator.entry_id
    )
    assert device.hw_version == "1.2.3"
    assert device.sw_version == "NRF 0.31.4 / ESP32 0.13.5"


async def test_diagnostic_values_survive_a_restart(
    hass, coordinator, ble, hass_storage
):
    ble.client.reads.update(_diagnostic_reads())
    await coordinator.async_refresh()
    await coordinator.async_save_to_disk()
    saved = hass_storage[store_key(MAC)]["data"]
    assert (
        saved["first_connection"]
        == datetime.fromtimestamp(FIRST_TS, tz=UTC).isoformat()
    )
    assert saved["firmware_version"] == "NRF 0.31.4 / ESP32 0.13.5"


async def test_restore_diagnostic_values(setup_integration, hass_storage):
    hass_storage[store_key(MAC)] = {
        "version": 1,
        "minor_version": 1,
        "key": store_key(MAC),
        "data": {
            "cloud_id": "CLOUD42",
            "hardware_version": "1.2.3",
            "firmware_version": "NRF 0.31.4 / ESP32 0.13.5",
            "probe_serial_number": "PSN9876",
            "first_connection": "2023-11-14T22:13:20+00:00",
            "probe_replacement": "not-a-date",
            "last_ph_calib": "2025-06-15T14:26:40+00:00",
        },
    }
    coord = await setup_integration(make_entry())
    assert coord.data["first_connection"].year == 2023
    assert coord.data["last_ph_calib"].year == 2025
    assert "probe_replacement" not in coord.data  # unreadable date dropped
    # The firmware string must never be taken for the legacy Cloud ID key.
    assert coord.data["cloud_id"] == "CLOUD42"
    assert coord.data["firmware_version"] == "NRF 0.31.4 / ESP32 0.13.5"
    assert coord.data["hardware_version"] == "1.2.3"


async def test_restore_drops_empty_diagnostic_values(setup_integration, hass_storage):
    hass_storage[store_key(MAC)] = {
        "version": 1,
        "minor_version": 1,
        "key": store_key(MAC),
        "data": {
            "hardware_version": "",
            "firmware_version": "",
            "probe_serial_number": "",
            "tac": 10,
        },
    }
    coord = await setup_integration(make_entry())
    for key in ("hardware_version", "firmware_version", "probe_serial_number"):
        assert key not in coord.data


@pytest.mark.parametrize("key", NEW_SENSORS)
async def test_new_diagnostic_sensors_are_unavailable_on_blueriiot(coordinator, key):
    sensor = BlueConnectSensor(
        coordinator, MAC, key, None, None, model_name="Blue Connect"
    )
    assert sensor.available is True
    coordinator.data["device_type"] = "blueriiot"
    assert sensor.available is False


async def test_diagnostic_reads_with_unset_dates_and_empty_serial(coordinator, ble):
    ble.client.reads.update(
        {
            CHAR_FIRST_CONNECTION_UUID: bytes(4),
            CHAR_PROBE_REPLACEMENT_UUID: FIRST_TS.to_bytes(4, "big"),
            CHAR_LAST_PH_CALIB_UUID: bytes(4),
            CHAR_PROBE_SERIAL_UUID: b"\x00\x00",
        }
    )
    await coordinator.async_refresh()
    d = coordinator.data
    assert d["probe_replacement"] == datetime.fromtimestamp(FIRST_TS, tz=UTC)
    for key in ("first_connection", "last_ph_calib", "probe_serial_number"):
        assert key not in d


async def test_static_values_are_read_once_and_dates_every_cycle(coordinator, ble):
    ble.client.reads.update(_diagnostic_reads())
    await coordinator.async_refresh()
    first = dict(coordinator.data)

    # The probe now answers differently: static values must not be read
    # again, the two dates that can change must.
    new_calib = CALIB_TS + 86_400
    ble.client.reads.update(
        {
            CHAR_HW_VERSION_UUID: bytes([9, 9, 9, 0]),
            CHAR_NRF_FW_UUID: bytes([9, 9, 9, 0]),
            CHAR_ESP32_FW_UUID: bytes([9, 9, 9, 0]),
            CHAR_FIRST_CONNECTION_UUID: (FIRST_TS + 5).to_bytes(4, "big"),
            CHAR_PROBE_SERIAL_UUID: b"OTHER\x00",
            CHAR_LAST_PH_CALIB_UUID: new_calib.to_bytes(4, "big"),
        }
    )
    await _refresh_again(coordinator, ble)
    d = coordinator.data
    for key in (
        "hardware_version",
        "firmware_version",
        "first_connection",
        "probe_serial_number",
    ):
        assert d[key] == first[key], key
    assert d["last_ph_calib"] == datetime.fromtimestamp(new_calib, tz=UTC)


async def test_probe_replacement_is_reset_when_the_probe_says_never(coordinator, ble):
    ble.client.reads.update(_diagnostic_reads())
    ble.client.reads[CHAR_PROBE_REPLACEMENT_UUID] = FIRST_TS.to_bytes(4, "big")
    await coordinator.async_refresh()
    assert coordinator.data["probe_replacement"] is not None
    ble.client.reads[CHAR_PROBE_REPLACEMENT_UUID] = bytes(4)
    await _refresh_again(coordinator, ble)
    assert coordinator.data["probe_replacement"] is None


async def test_probe_serial_is_read_again_after_a_probe_replacement(coordinator, ble):
    ble.client.reads.update(_diagnostic_reads())
    await coordinator.async_refresh()
    assert coordinator.data["probe_serial_number"] == "PSN9876"
    ble.client.reads[CHAR_PROBE_REPLACEMENT_UUID] = FIRST_TS.to_bytes(4, "big")
    ble.client.reads[CHAR_PROBE_SERIAL_UUID] = b"NEWPROBE\x00"
    await _refresh_again(coordinator, ble)
    assert coordinator.data["probe_serial_number"] == "NEWPROBE"
