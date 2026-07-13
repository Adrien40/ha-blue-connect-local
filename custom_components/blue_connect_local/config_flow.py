# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

import voluptuous as vol
import re
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_MAC_ADDRESS,
    CONF_ACCESS_CODE,
    CONF_PH_CALIB_4,
    CONF_PH_CALIB_7,
    CONF_PH_MIN,
    CONF_PH_MAX,
    CONF_ORP_MIN,
    CONF_ORP_MAX,
    CONF_ORP_CALIB,
    CONF_ORP_REF,
    CONF_TEMP_MIN,
    CONF_TEMP_MAX,
    CONF_TEMP_OFFSET,
    CONF_PH_REF_7,
    CONF_PH_REF_4,
    CONF_CHLORINE_MODEL,
    CONF_CYA,
    CONF_SCAN_INTERVAL,
    CONF_REFERENCE_TIME,
    CONF_PASSIVE_MEASURES,
    CONF_IGNORE_ECHOES,
    get_blue_connect_model,
    DEFAULT_PH_MIN,
    DEFAULT_PH_MAX,
    DEFAULT_ORP_MIN,
    DEFAULT_ORP_MAX,
    DEFAULT_TEMP_MIN,
    DEFAULT_TEMP_MAX,
    DEFAULT_PH_CALIB_4,
    DEFAULT_PH_CALIB_7,
    DEFAULT_PH_REF_4,
    DEFAULT_PH_REF_7,
    DEFAULT_ORP_CALIB,
    DEFAULT_ORP_REF,
)
from .validation import _flatten_sections, validate_calibration

CONF_MANUAL_MAC = "manual_mac_address"
MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

CHLORINE_MODEL_OPTIONS = ["chlorine", "bromine"]


class BlueConnectConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self):
        super().__init__()
        self._mac_address: str | None = None
        self._bt_name: str | None = None
        self._discovered_name: str = "Blue Connect"

    def _get_display_name(self, bt_name: str | None, model: str) -> str:
        if (
            bt_name
            and bt_name != "Blue Connect"
            and not bt_name.startswith("Blue Connect")
        ):
            return f"{model} ({bt_name})"
        return model

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> config_entries.FlowResult:
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured(reload_on_update=False)

        self._mac_address = discovery_info.address.upper()
        self._bt_name = discovery_info.name or ""

        model = get_blue_connect_model(self._bt_name)
        self._discovered_name = self._get_display_name(self._bt_name, model)

        self.context["title_placeholders"] = {"name": self._discovered_name}

        return await self.async_step_user()

    async def async_step_user(self, user_input=None) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            flat_input: dict = _flatten_sections(user_input)

            dropdown_raw = (user_input.get(CONF_MAC_ADDRESS) or "").strip()
            manual_raw = (flat_input.get(CONF_MANUAL_MAC, "") or "").strip()
            manual_mac = manual_raw.upper() if manual_raw else ""

            if manual_mac and not MAC_PATTERN.match(manual_mac):
                errors[CONF_MANUAL_MAC] = "invalid_mac"

            dropdown_mac = ""
            if dropdown_raw:
                mac_match = re.search(
                    r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", dropdown_raw
                )
                dropdown_mac = (
                    mac_match.group(0).upper() if mac_match else dropdown_raw.upper()
                )

            if (
                not errors
                and dropdown_mac
                and manual_mac
                and dropdown_mac != manual_mac
            ):
                errors["base"] = "mac_conflict"

            access_code = flat_input.get(CONF_ACCESS_CODE, "").strip()
            if access_code and (
                len(access_code) != 9
                or not access_code.isascii()
                or not access_code.isalnum()
            ):
                errors[CONF_ACCESS_CODE] = "invalid_access_code"

            if not errors:
                validation = validate_calibration(flat_input)
                if isinstance(validation, tuple):
                    field, error_key = validation
                    errors[field] = error_key
                else:
                    normalized_input = validation

                    final_mac = dropdown_mac or manual_mac

                    if not final_mac or not MAC_PATTERN.match(final_mac):
                        errors["base"] = "no_mac_provided"
                    else:
                        bt_name = (
                            self._bt_name if final_mac == self._mac_address else None
                        )

                        if final_mac != self._mac_address:
                            await self.async_set_unique_id(final_mac)
                            self._abort_if_unique_id_configured(reload_on_update=False)

                        if not bt_name:
                            for info in async_discovered_service_info(self.hass, False):
                                if info.address.upper() == final_mac and info.name:
                                    bt_name = info.name
                                    break

                        model = get_blue_connect_model(bt_name)
                        title = self._get_display_name(bt_name, model)

                        final_access_code = normalized_input.pop(CONF_ACCESS_CODE, "")

                        entry_data = {
                            CONF_MAC_ADDRESS: final_mac,
                            CONF_ACCESS_CODE: final_access_code,
                            "model": model,
                        }
                        normalized_input.pop(CONF_MAC_ADDRESS, None)
                        normalized_input.pop(CONF_MANUAL_MAC, None)
                        normalized_input.pop("model", None)

                        return self.async_create_entry(
                            title=title, data=entry_data, options=normalized_input
                        )

        device_entries: list[str] = []
        mac_to_display: dict[str, str] = {}
        for info in async_discovered_service_info(self.hass, False):
            if info.name:
                name_up = info.name.upper()
                if name_up.startswith("BC3"):
                    list_model = get_blue_connect_model(info.name)
                    display = self._get_display_name(info.name, list_model)
                    entry = f"{display} ({info.address.upper()})"
                    device_entries.append(entry)
                    mac_to_display[info.address.upper()] = entry

        default_selection: str | None = None
        if self._mac_address:
            if self._mac_address in mac_to_display:
                default_selection = mac_to_display[self._mac_address]
            else:
                model_auto = get_blue_connect_model(self._bt_name)
                display_auto = self._get_display_name(self._bt_name, model_auto)
                auto_entry = f"{display_auto} ({self._mac_address})"
                device_entries.insert(0, auto_entry)
                mac_to_display[self._mac_address] = auto_entry
                default_selection = auto_entry

        schema: dict = {}
        if device_entries:
            mac_key = (
                vol.Optional(CONF_MAC_ADDRESS, default=default_selection)
                if default_selection
                else vol.Optional(CONF_MAC_ADDRESS)
            )
            schema[mac_key] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=device_entries,
                    mode=selector.SelectSelectorMode.LIST,
                    sort=False,
                )
            )

        schema[vol.Optional(CONF_MANUAL_MAC, default="")] = selector.TextSelector()

        schema.update(
            {
                vol.Optional(CONF_ACCESS_CODE, default=""): str,
                vol.Required("general"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_CHLORINE_MODEL, default="chlorine"
                            ): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=CHLORINE_MODEL_OPTIONS,
                                    mode=selector.SelectSelectorMode.LIST,
                                    translation_key="chlorine_model",
                                    sort=False,
                                )
                            ),
                            vol.Required(CONF_CYA, default=40): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0,
                                    max=150,
                                    step=1,
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required("synchronization"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_SCAN_INTERVAL, default=60
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=5,
                                    max=1440,
                                    step=1,
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Required(
                                CONF_REFERENCE_TIME, default="08:00"
                            ): selector.TimeSelector(),
                            vol.Optional(
                                CONF_PASSIVE_MEASURES, default=True
                            ): selector.BooleanSelector(),
                            vol.Optional(
                                CONF_IGNORE_ECHOES, default=True
                            ): selector.BooleanSelector(),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required("probes_calibration"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_PH_CALIB_7, default=DEFAULT_PH_CALIB_7
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0,
                                    max=14,
                                    step=0.01,
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Required(
                                CONF_PH_REF_7, default=DEFAULT_PH_REF_7
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0,
                                    max=14,
                                    step=0.01,
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Required(
                                CONF_PH_CALIB_4, default=DEFAULT_PH_CALIB_4
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0,
                                    max=14,
                                    step=0.01,
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Required(
                                CONF_PH_REF_4, default=float(DEFAULT_PH_REF_4)
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0,
                                    max=14,
                                    step=0.01,
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Required(
                                CONF_ORP_CALIB, default=int(DEFAULT_ORP_CALIB)
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0,
                                    max=1000,
                                    step=1,
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Required(
                                CONF_ORP_REF, default=int(DEFAULT_ORP_REF)
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0,
                                    max=1000,
                                    step=1,
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Required(
                                CONF_TEMP_OFFSET, default=0.0
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=-5.0,
                                    max=5.0,
                                    step=0.1,
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BlueConnectOptionsFlowHandler()


class BlueConnectOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self) -> None:
        super().__init__()
        self._pending_data: dict | None = None

    async def async_step_init(self, user_input=None) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry

        current_access_code = entry.options.get(
            CONF_ACCESS_CODE, entry.data.get(CONF_ACCESS_CODE, "")
        )

        if user_input is not None:
            flat_input: dict = _flatten_sections(user_input)

            access_code = flat_input.get(CONF_ACCESS_CODE, "").strip()
            if access_code and (
                len(access_code) != 9
                or not access_code.isascii()
                or not access_code.isalnum()
            ):
                errors[CONF_ACCESS_CODE] = "invalid_access_code"

            if not errors:
                validation = validate_calibration(flat_input)
                if isinstance(validation, tuple):
                    field, error_key = validation
                    errors[field] = error_key
                else:
                    normalized_input = validation
                    normalized_input[CONF_ACCESS_CODE] = access_code

                    coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
                    if coordinator:
                        coordinator.update_local_state(normalized_input)
                        coordinator.request_deferred_recompute()

                        if access_code and not current_access_code:
                            coordinator.request_one_shot_analysis()
                            entry.async_create_background_task(
                                self.hass,
                                coordinator.async_request_refresh(),
                                "blue_connect_manual_refresh",
                            )

                    return self.async_create_entry(title="", data=normalized_input)

        coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)

        cya_coord = (
            coordinator.data.get(CONF_CYA) if coordinator and coordinator.data else None
        )
        current_cya = (
            cya_coord
            if cya_coord is not None
            else entry.options.get(CONF_CYA, entry.data.get(CONF_CYA, 40))
        )

        current_model = (
            coordinator.data.get(CONF_CHLORINE_MODEL)
            if coordinator and coordinator.data
            else None
        )
        if current_model is None:
            current_model = entry.options.get(
                CONF_CHLORINE_MODEL, entry.data.get(CONF_CHLORINE_MODEL, "chlorine")
            )

        scan_interval = (
            coordinator.data.get(CONF_SCAN_INTERVAL)
            if coordinator and coordinator.data
            else None
        )
        if scan_interval is None:
            scan_interval = entry.options.get(
                CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, 60)
            )

        current_reference_time = (
            coordinator.data.get(CONF_REFERENCE_TIME)
            if coordinator and coordinator.data
            else None
        )
        if current_reference_time is None:
            current_reference_time = entry.options.get(
                CONF_REFERENCE_TIME, entry.data.get(CONF_REFERENCE_TIME, "08:00")
            )

        passive_measures = (
            coordinator.data.get(CONF_PASSIVE_MEASURES)
            if coordinator and coordinator.data
            else None
        )
        if passive_measures is None:
            passive_measures = entry.options.get(
                CONF_PASSIVE_MEASURES, entry.data.get(CONF_PASSIVE_MEASURES, True)
            )

        ignore_echoes = (
            coordinator.data.get(CONF_IGNORE_ECHOES)
            if coordinator and coordinator.data
            else None
        )
        if ignore_echoes is None:
            ignore_echoes = entry.options.get(
                CONF_IGNORE_ECHOES, entry.data.get(CONF_IGNORE_ECHOES, True)
            )

        _c7_opt = entry.options.get(CONF_PH_CALIB_7)
        c7 = (
            _c7_opt
            if _c7_opt is not None
            else entry.data.get(CONF_PH_CALIB_7, DEFAULT_PH_CALIB_7)
        )

        _c4_opt = entry.options.get(CONF_PH_CALIB_4)
        c4 = (
            _c4_opt
            if _c4_opt is not None
            else entry.data.get(CONF_PH_CALIB_4, DEFAULT_PH_CALIB_4)
        )

        ph_ref_7 = entry.options.get(
            CONF_PH_REF_7, entry.data.get(CONF_PH_REF_7, DEFAULT_PH_REF_7)
        )
        ph_ref_4 = entry.options.get(
            CONF_PH_REF_4, entry.data.get(CONF_PH_REF_4, DEFAULT_PH_REF_4)
        )
        orp_target = entry.options.get(
            CONF_ORP_REF, entry.data.get(CONF_ORP_REF, DEFAULT_ORP_REF)
        )
        orp_measured = entry.options.get(
            CONF_ORP_CALIB, entry.data.get(CONF_ORP_CALIB, DEFAULT_ORP_CALIB)
        )
        temp_offset = entry.options.get(
            CONF_TEMP_OFFSET, entry.data.get(CONF_TEMP_OFFSET, 0.0)
        )

        ph_min = entry.options.get(CONF_PH_MIN, DEFAULT_PH_MIN)
        ph_max = entry.options.get(CONF_PH_MAX, DEFAULT_PH_MAX)
        orp_min = entry.options.get(CONF_ORP_MIN, DEFAULT_ORP_MIN)
        orp_max = entry.options.get(CONF_ORP_MAX, DEFAULT_ORP_MAX)
        temp_min = entry.options.get(CONF_TEMP_MIN, DEFAULT_TEMP_MIN)
        temp_max = entry.options.get(CONF_TEMP_MAX, DEFAULT_TEMP_MAX)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("general"): section(
                        vol.Schema(
                            {
                                vol.Optional(
                                    CONF_ACCESS_CODE,
                                    description={
                                        "suggested_value": current_access_code
                                    },
                                ): str,
                                vol.Required(
                                    CONF_CHLORINE_MODEL, default=current_model
                                ): selector.SelectSelector(
                                    selector.SelectSelectorConfig(
                                        options=CHLORINE_MODEL_OPTIONS,
                                        mode=selector.SelectSelectorMode.LIST,
                                        translation_key="chlorine_model",
                                        sort=False,
                                    )
                                ),
                                vol.Required(
                                    CONF_CYA, default=int(current_cya)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=150,
                                        step=1,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                            }
                        ),
                        {"collapsed": False},
                    ),
                    vol.Required("synchronization"): section(
                        vol.Schema(
                            {
                                vol.Required(
                                    CONF_SCAN_INTERVAL, default=int(scan_interval)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=5,
                                        max=1440,
                                        step=1,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_REFERENCE_TIME, default=current_reference_time
                                ): selector.TimeSelector(),
                                vol.Optional(
                                    CONF_PASSIVE_MEASURES,
                                    default=bool(passive_measures),
                                ): selector.BooleanSelector(),
                                vol.Optional(
                                    CONF_IGNORE_ECHOES, default=bool(ignore_echoes)
                                ): selector.BooleanSelector(),
                            }
                        ),
                        {"collapsed": True},
                    ),
                    vol.Required("probes_calibration"): section(
                        vol.Schema(
                            {
                                vol.Required(
                                    CONF_PH_CALIB_7, default=float(c7)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=14,
                                        step=0.01,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_PH_REF_7, default=float(ph_ref_7)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=14,
                                        step=0.01,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_PH_CALIB_4, default=float(c4)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=14,
                                        step=0.01,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_PH_REF_4, default=float(ph_ref_4)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=14,
                                        step=0.01,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_ORP_CALIB, default=int(orp_measured)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=1000,
                                        step=1,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_ORP_REF, default=int(orp_target)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=1000,
                                        step=1,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_TEMP_OFFSET, default=float(temp_offset)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=-5.0,
                                        max=5.0,
                                        step=0.1,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                            }
                        ),
                        {"collapsed": True},
                    ),
                    vol.Required("alert_thresholds"): section(
                        vol.Schema(
                            {
                                vol.Required(
                                    CONF_PH_MIN, default=float(ph_min)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=14,
                                        step=0.01,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_PH_MAX, default=float(ph_max)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=14,
                                        step=0.01,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_ORP_MIN, default=int(orp_min)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=1200,
                                        step=1,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_ORP_MAX, default=int(orp_max)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=1200,
                                        step=1,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_TEMP_MIN, default=float(temp_min)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=50,
                                        step=0.5,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_TEMP_MAX, default=float(temp_max)
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=0,
                                        max=50,
                                        step=0.5,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                            }
                        ),
                        {"collapsed": True},
                    ),
                }
            ),
            errors=errors,
        )
