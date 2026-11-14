"""Repairs: suggest ignoring the probe's passive frames once pH is high resolution."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import async_delete_issue

from .const import CONF_PASSIVE_MEASURES, DOMAIN


class PassiveHighResolutionRepairFlow(ConfirmRepairFlow):
    """Turn off the use of the passive frames for one probe, after confirmation."""

    def __init__(self, entry_id: str | None) -> None:
        self._entry_id = entry_id

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> Any:
        if user_input is not None:
            entry = (
                self.hass.config_entries.async_get_entry(self._entry_id)
                if self._entry_id
                else None
            )
            if entry is not None and entry.state is ConfigEntryState.LOADED:
                # Same effect as the "Blue Connect Internal Analysis (Passive)"
                # switch; the coordinator then clears this issue by itself.
                entry.runtime_data.update_local_state({CONF_PASSIVE_MEASURES: False})
            else:
                # The probe is gone or not loaded: nothing left to fix.
                async_delete_issue(self.hass, DOMAIN, self.issue_id)
        return await super().async_step_confirm(user_input)


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow of a repair issue raised by this integration."""
    entry_id = data.get("entry_id") if data else None
    return PassiveHighResolutionRepairFlow(
        entry_id if isinstance(entry_id, str) else None
    )
