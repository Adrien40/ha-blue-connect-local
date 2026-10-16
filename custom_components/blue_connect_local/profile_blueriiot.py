# Copyright (c) 2026 Adrien40
# This file is part of Blue Connect Local.

"""GATT profile of Blueriiot-based Blue Connect probes.

Blueriiot probes expose a different GATT layout than the Zodiac probes handled
by the rest of the integration. This module only knows about those UUIDs and
decides, from the services a connected device exposes, which profile applies.

Every helper is defensive: anything that is not a usable GATT service
collection is simply "not Blueriiot", so a Zodiac probe always falls back to
the original code path.
"""

from __future__ import annotations

from typing import Any

# Authentication: the access code is written here.
BLUERIIOT_CHAR_AUTH_UUID = "f3300002-f0a2-9b06-0c59-1bc4763b5c00"

# Writing 0x02 here starts a measurement.
BLUERIIOT_CHAR_TRIGGER_UUID = "f3300005-f0a2-9b06-0c59-1bc4763b5c00"

# The measurement may be notified on any of these characteristics; only the
# ones the device really exposes (with the "notify" property) are used.
BLUERIIOT_NOTIFY_UUIDS: tuple[str, ...] = (
    "f3300003-f0a2-9b06-0c59-1bc4763b5c00",
    "f3300006-f0a2-9b06-0c59-1bc4763b5c00",
    "f3300010-f0a2-9b06-0c59-1bc4763b5c00",
)

# On Blue Connect Plus (firmware 2.3.0), the measurement only starts once 0x02
# is also written to the authentication characteristic (f3300002) right after
# the access code and the main trigger (confirmed by A/B testing in PR #5).
# Unrelated writable characteristics (f3300007, f3300020) are not written to:
# they are not needed and can cause GATT 133 errors on weak BLE links.
BLUERIIOT_EXTRA_TRIGGER_UUIDS: tuple[str, ...] = (BLUERIIOT_CHAR_AUTH_UUID,)

_WRITE_PROPERTIES = frozenset({"write", "write-without-response"})


def _characteristics(services: Any) -> list[Any]:
    """Flatten the GATT services into a list of characteristics.

    Returns an empty list when `services` is missing or not iterable.
    """
    try:
        return [
            characteristic
            for service in services
            for characteristic in service.characteristics
        ]
    except TypeError, AttributeError:
        return []


def _uuids(services: Any) -> set[str]:
    return {str(char.uuid).lower() for char in _characteristics(services)}


def describe_gatt_characteristics(services: Any) -> list[str]:
    """One "uuid [properties]" entry per characteristic, for debug logging.

    Lets a user compare the table Home Assistant received (directly or through
    a Bluetooth proxy) with what a GATT browser such as nRF Connect shows.
    Returns an empty list when `services` is missing or not iterable.
    """
    return [
        f"{str(char.uuid).lower()} [{','.join(sorted(char.properties))}]"
        for char in _characteristics(services)
    ]


def is_blueriiot_services(services: Any) -> bool:
    """True when the services expose the Blueriiot auth and trigger characteristics."""
    return {BLUERIIOT_CHAR_AUTH_UUID, BLUERIIOT_CHAR_TRIGGER_UUID} <= _uuids(services)


def _matching_uuids(
    services: Any, candidates: tuple[str, ...], properties: frozenset[str]
) -> list[str]:
    """Candidates exposed with at least one of `properties`, in candidate order."""
    available = {
        str(char.uuid).lower()
        for char in _characteristics(services)
        if properties & set(char.properties)
    }
    return [uuid for uuid in candidates if uuid in available]


def blueriiot_notify_uuids(services: Any) -> list[str]:
    """Known Blueriiot characteristics that can notify."""
    return _matching_uuids(services, BLUERIIOT_NOTIFY_UUIDS, frozenset({"notify"}))


def blueriiot_extra_trigger_uuids(services: Any) -> list[str]:
    """Known extra trigger characteristics that can be written."""
    return _matching_uuids(services, BLUERIIOT_EXTRA_TRIGGER_UUIDS, _WRITE_PROPERTIES)
