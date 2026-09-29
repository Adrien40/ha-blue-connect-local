"""Config flow and options flow (with Home Assistant); validation in test_config_flow.py."""

from __future__ import annotations

from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    SOURCE_BLUETOOTH,
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
)
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blue_connect_local.config_flow import (
    GENERIC_MODEL_NAME,
    _model_from_service_info,
)
from custom_components.blue_connect_local.const import (
    CONF_ACCESS_CODE,
    CONF_CHLORINE_MODEL,
    CONF_CYA,
    CONF_IGNORE_ECHOES,
    CONF_MAC_ADDRESS,
    CONF_ORP_CALIB,
    CONF_ORP_MAX,
    CONF_ORP_MIN,
    CONF_ORP_REF,
    CONF_PASSIVE_MEASURES,
    CONF_PH_CALIB_4,
    CONF_PH_CALIB_7,
    CONF_PH_MAX,
    CONF_PH_MIN,
    CONF_PH_REF_4,
    CONF_PH_REF_7,
    CONF_REFERENCE_TIME,
    CONF_SCAN_INTERVAL,
    CONF_TAC,
    CONF_TEMP_MAX,
    CONF_TEMP_MIN,
    CONF_TEMP_OFFSET,
    DOMAIN,
)

from .conftest import entity_id, make_entry
from .helpers import ACCESS_CODE, MAC, build_frame

DISCOVERED = (
    "custom_components.blue_connect_local.config_flow.async_discovered_service_info"
)
SETUP = "custom_components.blue_connect_local.async_setup_entry"
PARSE = "custom_components.blue_connect_local.config_flow.parse_raw_frame"


def _info(
    frame: bytes | None = None, name: str = "BC3-1234"
) -> BluetoothServiceInfoBleak:
    manufacturer = {0x1234: frame} if frame else {}
    return BluetoothServiceInfoBleak(
        name=name,
        address=MAC,
        rssi=-60,
        manufacturer_data=manufacturer,
        service_data={},
        service_uuids=[],
        source="local",
        device=BLEDevice(MAC, name, {}),
        advertisement=AdvertisementData(
            local_name=name,
            manufacturer_data=manufacturer,
            service_data={},
            service_uuids=[],
            rssi=-60,
            tx_power=None,
            platform_data=(),
        ),
        connectable=True,
        time=monotonic(),
        tx_power=None,
    )


def _sections(**over) -> dict:
    return {
        "general": {
            CONF_CHLORINE_MODEL: "chlorine",
            CONF_CYA: 40,
            **over.pop("general", {}),
        },
        "synchronization": {
            CONF_SCAN_INTERVAL: 60,
            CONF_REFERENCE_TIME: "08:00:00",
            CONF_PASSIVE_MEASURES: True,
            CONF_IGNORE_ECHOES: True,
            **over.pop("synchronization", {}),
        },
        "probes_calibration": {
            CONF_PH_CALIB_7: 7.0,
            CONF_PH_REF_7: 7.0,
            CONF_PH_CALIB_4: 4.0,
            CONF_PH_REF_4: 4.0,
            CONF_ORP_CALIB: 650,
            CONF_ORP_REF: 650,
            CONF_TEMP_OFFSET: 0.0,
            **over.pop("probes_calibration", {}),
        },
        **over,
    }


def _default_of(result, field: str):
    for key in result["data_schema"].schema:
        if key == field:
            return key.default()
    raise AssertionError(f"{field} not in schema")


async def _start_discovery(hass, frame=None):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_info(frame)
    )


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------
async def test_discovery_creates_entry_with_access_code(hass):
    frame = build_frame(conductivity=1200)
    with (
        patch(DISCOVERED, return_value=[_info(frame)]),
        patch(SETUP, return_value=True),
    ):
        result = await _start_discovery(hass, frame)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        selection = _default_of(result, CONF_MAC_ADDRESS)
        assert MAC in selection and "Gold" in selection

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_MAC_ADDRESS: selection, CONF_ACCESS_CODE: ACCESS_CODE, **_sections()},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_MAC_ADDRESS: MAC,
        CONF_ACCESS_CODE: ACCESS_CODE,
        "has_conductivity": True,
    }
    assert result["result"].unique_id == MAC
    assert result["options"][CONF_CYA] == 40
    assert result["options"][CONF_CHLORINE_MODEL] == "chlorine"
    assert "general" not in result["options"]  # sections flattened


async def test_discovery_of_a_silver_is_remembered(hass):
    frame = build_frame(conductivity=None)
    with (
        patch(DISCOVERED, return_value=[_info(frame)]),
        patch(SETUP, return_value=True),
    ):
        result = await _start_discovery(hass, frame)
        selection = _default_of(result, CONF_MAC_ADDRESS)
        assert "Silver" in selection
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_MAC_ADDRESS: selection, **_sections()}
        )
    assert result["data"]["has_conductivity"] is False
    assert result["data"][CONF_ACCESS_CODE] == ""  # passive mode only
    assert "Silver" in result["title"]


async def test_already_configured_device_aborts(hass):
    make_entry().add_to_hass(hass)
    result = await _start_discovery(hass, build_frame())
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_discovered_device_disappears_from_cache_before_form_renders(hass):
    """The advertisement that triggered async_step_bluetooth already gave us
    the MAC/model (self._mac_address, self._discovered_name); the device
    doesn't need to still be in the discovery cache by the time the form
    renders (e.g. brief signal drop) for the dropdown to still offer it."""
    frame = build_frame(conductivity=1200)
    with (
        patch(DISCOVERED, return_value=[]),  # nothing found on re-scan
        patch(SETUP, return_value=True),
    ):
        result = await _start_discovery(hass, frame)
        assert result["type"] is FlowResultType.FORM
        selection = _default_of(result, CONF_MAC_ADDRESS)
    assert MAC in selection and "Gold" in selection


@pytest.mark.parametrize("code", ["short", "TOOLONG1234", "ABCDEFGH!", "ÉÉÉÉÉÉÉÉÉ"])
async def test_invalid_access_code_is_rejected(hass, code):
    with patch(DISCOVERED, return_value=[_info()]), patch(SETUP, return_value=True):
        result = await _start_discovery(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_MAC_ADDRESS: _default_of(result, CONF_MAC_ADDRESS),
                CONF_ACCESS_CODE: code,
                **_sections(),
            },
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ACCESS_CODE: "invalid_access_code"}


async def test_invalid_calibration_shows_error(hass):
    with patch(DISCOVERED, return_value=[_info()]), patch(SETUP, return_value=True):
        result = await _start_discovery(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_MAC_ADDRESS: _default_of(result, CONF_MAC_ADDRESS),
                **_sections(
                    probes_calibration={CONF_PH_CALIB_4: 7.5, CONF_PH_CALIB_7: 4.5}
                ),
            },
        )
    assert result["errors"] == {CONF_PH_CALIB_7: "ph_slope_mismatch"}


async def test_manual_mac_entry(hass):
    with patch(DISCOVERED, return_value=[]), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        bad = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"manual_mac_address": "not-a-mac", **_sections()}
        )
        assert bad["errors"] == {"manual_mac_address": "invalid_mac"}

        good = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"manual_mac_address": MAC.lower(), **_sections()}
        )
    assert good["type"] is FlowResultType.CREATE_ENTRY
    assert good["data"][CONF_MAC_ADDRESS] == MAC


async def test_manual_mac_matching_a_live_scanned_device_is_enriched(hass):
    """A manually-typed MAC (`final_mac != self._mac_address`, since a plain
    SOURCE_USER flow never had one) that happens to also show up in a fresh
    scan: the re-scan loop must find it and pull its name/model from there,
    the same way the bluetooth-discovery flow does via `self._bt_name`/
    `self._has_conductivity`. Every other manual-mac test mocks an empty
    scan, so that loop never actually matched anything until now."""
    frame = build_frame(conductivity=1200)
    with (
        patch(DISCOVERED, return_value=[_info(frame)]),
        patch(SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"manual_mac_address": MAC, **_sections()}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MAC_ADDRESS] == MAC
    assert result["data"]["has_conductivity"] is True
    assert "Gold" in result["title"]


async def test_no_mac_provided(hass):
    with patch(DISCOVERED, return_value=[]), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _sections()
        )
    assert result["errors"] == {"base": "no_mac_provided"}


async def test_conflicting_dropdown_and_manual_mac(hass):
    with patch(DISCOVERED, return_value=[_info()]), patch(SETUP, return_value=True):
        result = await _start_discovery(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_MAC_ADDRESS: _default_of(result, CONF_MAC_ADDRESS),
                "manual_mac_address": "11:22:33:44:55:66",
                **_sections(),
            },
        )
    assert result["errors"] == {"base": "mac_conflict"}


async def test_manual_mac_already_configured_aborts(hass):
    make_entry().add_to_hass(hass)
    with patch(DISCOVERED, return_value=[]), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"manual_mac_address": MAC, **_sections()}
        )
    assert result["type"] is FlowResultType.ABORT


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------
def _options_input(access_code=ACCESS_CODE, **over) -> dict:
    thresholds = {
        CONF_PH_MIN: 6.9,
        CONF_PH_MAX: 7.4,
        CONF_ORP_MIN: 650,
        CONF_ORP_MAX: 750,
        CONF_TEMP_MIN: 6.0,
        CONF_TEMP_MAX: 32.0,
    }
    thresholds.update(over.pop("alert_thresholds", {}))
    sections = _sections(**over)
    # In the options form, the access code lives in the "general" section.
    sections["general"] = {CONF_ACCESS_CODE: access_code, **sections["general"]}
    return {**sections, "alert_thresholds": thresholds}


async def test_options_form_prefills_current_values(hass, entry, coordinator):
    coordinator.update_local_state({CONF_CYA: 55, CONF_CHLORINE_MODEL: "bromine"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    general = result["data_schema"].schema["general"].schema.schema
    defaults = {str(k): k.default() for k in general if str(k) != CONF_ACCESS_CODE}
    assert defaults[CONF_CYA] == 55
    assert defaults[CONF_CHLORINE_MODEL] == "bromine"


async def test_options_form_uses_entry_fallbacks_when_coordinator_not_loaded(
    hass, entry
):
    """Without a loaded coordinator (`entry` alone, no `coordinator` fixture),
    every `coordinator.data.get(...)` prefill falls back to entry.options /
    entry.data instead - the branch normally masked by the live coordinator
    the other options-flow tests always have."""
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={CONF_CYA: 55, CONF_CHLORINE_MODEL: "bromine"}
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    general = result["data_schema"].schema["general"].schema.schema
    defaults = {str(k): k.default() for k in general if str(k) != CONF_ACCESS_CODE}
    assert defaults[CONF_CYA] == 55
    assert defaults[CONF_CHLORINE_MODEL] == "bromine"


async def test_options_save_without_a_loaded_coordinator_does_not_raise(hass, entry):
    """Same "no coordinator" situation, but saving: `if coordinator:` must
    skip pushing live state/triggering a refresh instead of raising on
    `getattr(entry, "runtime_data", None)` being None."""
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _options_input()
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_saved_and_pushed_to_coordinator(hass, entry, coordinator):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _options_input(
            general={CONF_CYA: 70, CONF_CHLORINE_MODEL: "bromine"},
            probes_calibration={CONF_TEMP_OFFSET: 1.5},
            alert_thresholds={CONF_PH_MAX: 7.8},
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_CYA] == 70
    assert entry.options[CONF_CHLORINE_MODEL] == "bromine"
    assert coordinator.data[CONF_CYA] == 70
    assert coordinator.data[CONF_PH_MAX] == 7.8
    assert coordinator.data[CONF_TEMP_OFFSET] == 1.5


async def test_changing_access_code_triggers_analysis(hass, entry, coordinator):
    coordinator._force_one_shot = False
    coordinator.async_request_refresh = AsyncMock()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _options_input(access_code="ZZ99YY88X")
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator._force_one_shot is True
    coordinator.async_request_refresh.assert_awaited()


async def test_unchanged_access_code_does_not_trigger_analysis(
    hass, entry, coordinator
):
    coordinator._force_one_shot = False
    coordinator.async_request_refresh = AsyncMock()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], _options_input()
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator._force_one_shot is False
    coordinator.async_request_refresh.assert_not_awaited()


async def test_options_reject_invalid_access_code(hass, entry, coordinator):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _options_input(access_code="bad")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ACCESS_CODE: "invalid_access_code"}


@pytest.mark.parametrize(
    ("over", "field", "code"),
    [
        (
            {"alert_thresholds": {CONF_PH_MIN: 7.6, CONF_PH_MAX: 7.0}},
            CONF_PH_MIN,
            "ph_threshold_error",
        ),
        (
            {"alert_thresholds": {CONF_TEMP_MIN: 40, CONF_TEMP_MAX: 10}},
            CONF_TEMP_MIN,
            "temp_threshold_error",
        ),
        (
            {"alert_thresholds": {CONF_ORP_MIN: 900, CONF_ORP_MAX: 700}},
            CONF_ORP_MIN,
            "orp_threshold_error",
        ),
        (
            {"probes_calibration": {CONF_PH_CALIB_4: 7.5, CONF_PH_CALIB_7: 4.5}},
            CONF_PH_CALIB_7,
            "ph_slope_mismatch",
        ),
    ],
)
async def test_options_validation_errors(hass, entry, coordinator, over, field, code):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _options_input(**over)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: code}


# ---------------------------------------------------------------------------
# Reauthentication
# ---------------------------------------------------------------------------
async def test_invalid_access_code_starts_reauth(hass, entry, coordinator):
    entry.async_start_reauth(hass)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    reauth_flows = [f for f in flows if f["context"]["source"] == SOURCE_REAUTH]
    assert len(reauth_flows) == 1
    assert reauth_flows[0]["context"]["entry_id"] == entry.entry_id


async def test_reauth_confirm_updates_access_code(hass, entry, coordinator):
    entry.async_start_reauth(hass)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    reauth_flow_id = flows[0]["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        reauth_flow_id, {CONF_ACCESS_CODE: "NEWCODE99"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_ACCESS_CODE] == "NEWCODE99"


# ---------------------------------------------------------------------------
# Reconfigure flow (swapping the physical device / access code)
# ---------------------------------------------------------------------------
NEW_MAC = "11:22:33:44:55:66"


async def _start_reconfigure(hass, entry):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )


async def test_reconfigure_form_prefills_current_values(hass, entry, coordinator):
    result = await _start_reconfigure(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    schema_defaults = {
        field.schema: field.default()
        for field in result["data_schema"].schema
        if field.default is not vol.UNDEFINED
    }
    assert schema_defaults[CONF_MAC_ADDRESS] == MAC
    assert schema_defaults[CONF_ACCESS_CODE] == ACCESS_CODE


async def test_reconfigure_updates_mac_and_access_code(hass, entry, coordinator):
    result = await _start_reconfigure(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MAC_ADDRESS: NEW_MAC, CONF_ACCESS_CODE: "NEWCODE99"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_MAC_ADDRESS] == NEW_MAC
    assert entry.data[CONF_ACCESS_CODE] == "NEWCODE99"
    assert entry.unique_id == NEW_MAC


async def test_reconfigure_rejects_invalid_mac(hass, entry, coordinator):
    result = await _start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MAC_ADDRESS: "not-a-mac", CONF_ACCESS_CODE: ACCESS_CODE},
    )
    assert result["errors"] == {CONF_MAC_ADDRESS: "invalid_mac"}
    # The original entry must be untouched.
    assert entry.data[CONF_MAC_ADDRESS] == MAC


async def test_reconfigure_rejects_invalid_access_code(hass, entry, coordinator):
    result = await _start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MAC_ADDRESS: MAC, CONF_ACCESS_CODE: "short"},
    )
    assert result["errors"] == {CONF_ACCESS_CODE: "invalid_access_code"}


async def test_reconfigure_can_keep_the_same_mac(hass, entry, coordinator):
    """Just correcting the access code, without changing the device."""
    result = await _start_reconfigure(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MAC_ADDRESS: MAC, CONF_ACCESS_CODE: "NEWCODE99"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_ACCESS_CODE] == "NEWCODE99"


async def test_reconfigure_aborts_if_mac_used_by_another_entry(
    hass, entry, coordinator
):
    other_mac = "AA:AA:AA:AA:AA:AA"
    other_entry = make_entry()
    other_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(other_entry, unique_id=other_mac)

    result = await _start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MAC_ADDRESS: other_mac, CONF_ACCESS_CODE: ACCESS_CODE},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # The original entry must be untouched.
    assert entry.data[CONF_MAC_ADDRESS] == MAC


# ---------------------------------------------------------------------------
# Regression: the new access code must be the one actually used after reauth /
# reconfigure, whatever the entry state (options saved or not, stale storage).
# ---------------------------------------------------------------------------
async def _start_reauth(hass, entry) -> str:
    entry.async_start_reauth(hass)
    await hass.async_block_till_done()
    return hass.config_entries.flow.async_progress_by_handler(DOMAIN)[0]["flow_id"]


def _entry_with_code(data_code: str, options: dict) -> MockConfigEntry:
    """Entry whose access code is in `data`, and optionally also in `options`."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        title="Blue Connect",
        version=1,
        minor_version=4,
        data={CONF_MAC_ADDRESS: MAC, CONF_ACCESS_CODE: data_code},
        options=options,
    )


@pytest.mark.parametrize("options", [{}, {CONF_ACCESS_CODE: "WRONGCODE"}])
async def test_reauth_new_code_is_used_by_coordinator(hass, setup_integration, options):
    entry = _entry_with_code("WRONGCODE", options)
    await setup_integration(entry)
    flow_id = await _start_reauth(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ACCESS_CODE: "NEWCODE99"}
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert result["reason"] == "reauth_successful"
    assert entry.runtime_data.access_code == "NEWCODE99"


async def test_reauth_rejects_invalid_code_format(hass, entry, coordinator):
    flow_id = await _start_reauth(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ACCESS_CODE: "short"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ACCESS_CODE: "invalid_access_code"}
    assert entry.data[CONF_ACCESS_CODE] == ACCESS_CODE


async def test_reconfigure_new_code_is_used_when_options_hold_old_one(
    hass, setup_integration
):
    entry = _entry_with_code("", {CONF_ACCESS_CODE: ""})
    await setup_integration(entry)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MAC_ADDRESS: MAC, CONF_ACCESS_CODE: "NEWCODE99"}
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.runtime_data.access_code == "NEWCODE99"


async def test_access_code_is_never_written_to_storage(hass, entry, coordinator):
    await coordinator.async_save_to_disk()
    stored = await coordinator.store.async_load()
    assert stored is not None
    assert CONF_ACCESS_CODE not in stored


async def test_stale_access_code_in_storage_does_not_override_entry(
    hass, setup_integration
):
    """Storage written by <= 1.2.0 contains the old code: it must be ignored."""
    entry = _entry_with_code("NEWCODE99", {})
    with patch(
        "homeassistant.helpers.storage.Store.async_load",
        return_value={CONF_ACCESS_CODE: "OLDCODE00", "cya": 40},
    ):
        coordinator = await setup_integration(entry)
    assert coordinator.access_code == "NEWCODE99"


# ---------------------------------------------------------------------------
# Regression: values saved from the Configure screen must reach the number
# entities (they used to keep displaying the value they had at startup).
# ---------------------------------------------------------------------------
async def test_options_change_is_reflected_by_number_entities(hass, entry, coordinator):
    interval = entity_id(hass, "number", CONF_SCAN_INTERVAL)
    cya = entity_id(hass, "number", CONF_CYA)
    assert hass.states.get(interval).state == "60"
    assert hass.states.get(cya).state == "40"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _options_input(
            general={CONF_CYA: 70}, synchronization={CONF_SCAN_INTERVAL: 30}
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert hass.states.get(interval).state == "30"
    assert hass.states.get(cya).state == "70"


async def test_number_entities_follow_the_coordinator(hass, entry, coordinator):
    tac = entity_id(hass, "number", CONF_TAC)
    coordinator.update_local_state({CONF_TAC: 120})
    await hass.async_block_till_done()
    assert hass.states.get(tac).state == "120"


# ---------------------------------------------------------------------------
# Config flow: defensive branches
# ---------------------------------------------------------------------------
def test_model_falls_back_to_generic_when_the_frame_cannot_be_parsed():
    with patch(PARSE, return_value=None):
        assert _model_from_service_info(_info(build_frame())) == (
            GENERIC_MODEL_NAME,
            None,
        )


def _stranger(name):
    """A discovered Bluetooth device that is not a Blue Connect."""
    return SimpleNamespace(
        name=name,
        address="11:22:33:44:55:66",
        manufacturer_data={},
        service_data={},
    )


async def test_device_picker_ignores_unnamed_and_foreign_devices(hass):
    seen = [_stranger(None), _stranger("Some Other Device"), _info(build_frame())]
    with patch(DISCOVERED, return_value=seen), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.FORM
    (picker,) = (
        selector
        for key, selector in result["data_schema"].schema.items()
        if key == CONF_MAC_ADDRESS
    )
    options = [
        o if isinstance(o, str) else o["value"] for o in picker.config["options"]
    ]
    assert len(options) == 1 and MAC in options[0]  # only the Blue Connect is offered


async def test_manual_mac_skips_other_devices_in_the_scan(hass):
    seen = [_stranger("Some Other Device"), _info(build_frame(conductivity=1200))]
    with patch(DISCOVERED, return_value=seen), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"manual_mac_address": MAC, **_sections()}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "Gold" in result["title"]  # picked up from the matching device only


async def test_options_form_prefers_the_live_coordinator_values(
    hass, entry, coordinator
):
    coordinator.update_volatile_state(
        {
            CONF_REFERENCE_TIME: "09:30",
            CONF_PASSIVE_MEASURES: False,
            CONF_IGNORE_ECHOES: False,
        }
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    sync = result["data_schema"].schema["synchronization"].schema.schema
    defaults = {str(k): k.default() for k in sync}
    assert str(defaults[CONF_REFERENCE_TIME]).startswith("09:30")
    assert defaults[CONF_PASSIVE_MEASURES] is False
    assert defaults[CONF_IGNORE_ECHOES] is False
