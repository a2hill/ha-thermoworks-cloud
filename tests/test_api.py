"""Tests for the ThermoWorks Integrations API client and its mapping onto the entity models."""

from datetime import datetime, timezone
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import format_mac

from custom_components.thermoworks_cloud.api import (
    InvalidApiKeyError,
    RateLimitedError,
    ThermoworksApiClient,
    parse_device,
)
from custom_components.thermoworks_cloud.coordinator import ThermoworksCoordinator
from custom_components.thermoworks_cloud.models import ThermoworksChannel, ThermoworksDevice

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def hass():
    """A minimal stand-in: the coordinator only needs a loop and a client session."""
    fake = MagicMock()
    fake.loop = asyncio.get_running_loop()
    with patch(
        "custom_components.thermoworks_cloud.coordinator.async_get_clientsession",
        return_value=MagicMock(),
    ):
        yield fake


DEVICE_JSON = {
    "id": "30:C6:F7:F7:6B:E0",
    "serial": "30:C6:F7:F7:6B:E0",
    "displayUnits": "F",
    "batteryState": "discharging",
    "label": "GE Fridge Garage",
    "model": "node",
    "type": "node",
    "firmware": "2.1.8-30",
    "battery": 100,
    "wifiSignal": -61,
    "gatewaySignal": None,
    "lastSeen": "2026-11-03T20:00:00Z",
    "transmitIntervalSeconds": 1800,
    "channels": [
        {
            "id": "1", "number": 1, "label": "Ambient", "enabled": True, "value": 74.5,
            "units": "F", "probeFailed": False, "alarming": False,
            "alarmHigh": {"enabled": True, "value": 90, "alarming": False},
            "alarmLow": None,
            "lastTelemetrySaved": "2026-11-03T19:59:00Z",
        },
        {
            "id": "3", "number": 3, "label": "Freezer", "enabled": True, "value": 20.4,
            "units": "F", "probeFailed": False, "alarming": True,
            "alarmHigh": {"enabled": True, "value": 10, "alarming": True},
            "alarmLow": {"enabled": False, "value": -30, "alarming": False},
        },
        {
            "id": "4", "number": 4, "label": None, "enabled": False, "value": None,
            "units": None, "probeFailed": False, "alarming": False,
        },
    ],
}


def test_parse_device_keeps_old_identifier_and_attribute_names():
    device = parse_device(DEVICE_JSON)
    td = ThermoworksDevice.from_api_device(device)
    # unique_ids are f"{DOMAIN}-{format_mac(identifier)}..."; must match what HA already has
    assert format_mac(td.get_identifier()) == "30:c6:f7:f7:6b:e0"
    assert td.device_name == "node"
    assert td.device_display_units == "F"
    assert td.battery_state == "discharging"
    assert td.battery == 100
    assert td.signal_strength == -61
    assert td.transmit_interval_in_seconds == 1800
    assert td.last_seen == datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc)


def test_parse_channel_number_is_string_and_alarm_units_follow_channel():
    device = parse_device(DEVICE_JSON)
    ch = ThermoworksChannel.from_api_channel(device.channels[1])
    assert ch.number == "3"
    assert ch.value == 20.4
    assert ch.alarm_high.units == "F"
    assert ch.alarm_high.alarming is True
    assert ch.alarm_low.enabled is False
    assert device.channels[0].alarm_low is None


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def json(self, content_type=None):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        return self.responses.pop(0)


async def test_client_sends_bearer_and_uses_etag():
    body = {"generatedAt": "2026-11-03T20:00:00Z", "devices": [DEVICE_JSON]}
    session = _Session(_Resp(200, body, {"ETag": 'W/"abc"'}), _Resp(304))
    client = ThermoworksApiClient(session, "  twk_id_secret \n")
    first = await client.get_devices()
    second = await client.get_devices()
    assert session.calls[0][0] == "https://cloud.thermoworks.com/api/v1/devices"
    assert session.calls[0][1]["Authorization"] == "Bearer twk_id_secret"
    assert "If-None-Match" not in session.calls[0][1]
    assert session.calls[1][1]["If-None-Match"] == 'W/"abc"'
    assert second is first


async def test_client_401_and_429():
    err = {"error": {"code": "invalid_api_key", "message": "bad"}}
    client = ThermoworksApiClient(_Session(_Resp(401, err)), "k")
    with pytest.raises(InvalidApiKeyError):
        await client.get_devices()
    client = ThermoworksApiClient(_Session(_Resp(429, {}, {"Retry-After": "12"})), "k")
    with pytest.raises(RateLimitedError) as exc:
        await client.get_devices()
    assert exc.value.retry_after == 12


async def test_coordinator_requires_api_key_for_old_entries(hass):
    entry = MagicMock()
    entry.data = {"email": "x@example.com", "password": "pw"}
    entry.options = {}
    with pytest.raises(ConfigEntryAuthFailed):
        ThermoworksCoordinator(hass, entry)


async def test_coordinator_maps_devices_and_skips_disabled_channels(hass):
    entry = MagicMock()
    entry.data = {"api_key": "twk_x"}
    entry.options = {"scan_interval": 5}
    entry.unique_id = "acct"
    coordinator = ThermoworksCoordinator(hass, entry)
    assert coordinator.poll_interval == 60  # clamped to the API minimum

    async def fake_get_devices():
        return [parse_device(DEVICE_JSON)]

    coordinator.api.get_devices = fake_get_devices
    data = await coordinator.async_update_data()
    assert [d.get_identifier() for d in data.devices] == ["30:C6:F7:F7:6B:E0"]
    assert [c.number for c in data.device_channels["30:C6:F7:F7:6B:E0"]] == ["1", "3"]


async def test_coordinator_revoked_key_triggers_reauth(hass):
    entry = MagicMock()
    entry.data = {"api_key": "twk_x"}
    entry.options = {}
    entry.unique_id = "acct"
    coordinator = ThermoworksCoordinator(hass, entry)

    async def revoked():
        raise InvalidApiKeyError("expired_api_key: expired")

    coordinator.api.get_devices = revoked
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_update_data()
