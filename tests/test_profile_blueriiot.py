"""Tests for the Blueriiot GATT profile detection (profile_blueriiot.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.blue_connect_local.const import (
    CHAR_AUTH_UUID,
    CHAR_TRIGGER_UUID,
)

from .helpers_blueriiot import (
    AUTH,
    EXTRA_1,
    EXTRA_2,
    EXTRA_AUTH,
    NOTIFY_1,
    NOTIFY_2,
    NOTIFY_3,
    PROFILE,
    TRIGGER,
    blueriiot_layout,
    make_services,
)


def test_blueriiot_profile_is_detected():
    assert PROFILE.is_blueriiot_services(make_services(blueriiot_layout()))


def test_detection_is_case_insensitive():
    layout = {AUTH.upper(): ["write"], TRIGGER.upper(): ["write"]}
    assert PROFILE.is_blueriiot_services(make_services(layout))


@pytest.mark.parametrize(
    "layout",
    [
        {},
        {AUTH: ["write"]},  # trigger missing
        {TRIGGER: ["write"]},  # auth missing
        {CHAR_AUTH_UUID: ["write"], CHAR_TRIGGER_UUID: ["write"]},  # Zodiac
    ],
)
def test_other_layouts_are_not_blueriiot(layout):
    assert not PROFILE.is_blueriiot_services(make_services(layout))


@pytest.mark.parametrize("services", [None, 42, [object()], [SimpleNamespace()]])
def test_unusable_services_are_never_blueriiot(services):
    assert not PROFILE.is_blueriiot_services(services)
    assert PROFILE.blueriiot_notify_uuids(services) == []
    assert PROFILE.blueriiot_extra_trigger_uuids(services) == []


def test_notify_uuids_keep_only_exposed_notifying_characteristics():
    layout = blueriiot_layout()
    layout[NOTIFY_2] = ["read"]  # exposed but cannot notify
    del layout[NOTIFY_3]  # not exposed
    services = make_services(layout)
    assert PROFILE.blueriiot_notify_uuids(services) == [NOTIFY_1]


def test_gatt_table_is_described_for_debug_logging():
    services = make_services({AUTH: ["write", "read"], NOTIFY_1: ["notify"]})
    assert PROFILE.describe_gatt_characteristics(services) == [
        f"{AUTH} [read,write]",
        f"{NOTIFY_1} [notify]",
    ]


@pytest.mark.parametrize("services", [None, [], object()])
def test_gatt_table_description_is_empty_without_usable_services(services):
    assert PROFILE.describe_gatt_characteristics(services) == []


def test_extra_triggers_ignore_unrelated_writable_characteristics():
    """f3300007 / f3300020 are exposed and writable but never used."""
    services = make_services(blueriiot_layout())
    assert EXTRA_1 in {c.uuid for s in services for c in s.characteristics}
    assert EXTRA_2 in {c.uuid for s in services for c in s.characteristics}
    assert PROFILE.blueriiot_extra_trigger_uuids(services) == [EXTRA_AUTH]


def test_authentication_characteristic_is_the_only_extra_trigger():
    """Blue Connect Plus (fw 2.3.0) only measures once it also gets 0x02 there."""
    assert EXTRA_AUTH == AUTH
    assert PROFILE.BLUERIIOT_EXTRA_TRIGGER_UUIDS == (AUTH,)


def test_authentication_trigger_is_skipped_when_not_writable():
    layout = blueriiot_layout()
    layout[AUTH] = ["read"]
    services = make_services(layout)
    assert PROFILE.blueriiot_extra_trigger_uuids(services) == []
