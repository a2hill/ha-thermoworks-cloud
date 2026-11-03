"""Regression tests for the supported API and snapshot mapping."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientConnectionError, ClientSession, web
from aiohttp.test_utils import TestServer
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_API_KEY, CONF_SCAN_INTERVAL
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.helpers import device_registry as dr

from custom_components.thermoworks_cloud.api import (
    ApiAuthError,
    ApiError,
    ApiRateLimited,
    IntegrationsApi,
    parse_snapshot,
)
from custom_components.thermoworks_cloud.const import API_BASE_URL, minimum_scan_interval
from custom_components.thermoworks_cloud.coordinator import ThermoworksCoordinator
from custom_components.thermoworks_cloud.number import ScanIntervalNumber
from custom_components.thermoworks_cloud.models import ThermoworksDevice
from custom_components.thermoworks_cloud.sensor import (
    BatterySensor, FanSetTemperatureSensor, FanStateSensor, TemperatureSensor,
)
from custom_components.thermoworks_cloud.binary_sensor import (
    FanConnectedSensor, HighAlarmBinarySensor,
)


def snapshot():
    """Include channel zero, a non-contiguous channel and an empty device."""
    return {
        "generatedAt": "2026-11-03T20:00:00Z",
        "devices": [
            {
                "id": "device123",
                "serial": "serial123",
                "model": "NODE",
                "wifiSignal": -40,
                "gatewaySignal": -60,
                "channels": [
                    {
                        "id": "0",
                        "number": 0,
                        "value": 20.5,
                        "units": "C",
                        "enabled": True,
                        "probeFailed": False,
                        "lastTelemetrySaved": "2025-07-01T10:15:00Z",
                        "alarmHigh": {
                            "enabled": True,
                            "alarming": True,
                            "value": 20,
                        },
                    },
                    {
                        "id": "7",
                        "number": None,
                        "value": None,
                        "units": None,
                        "enabled": False,
                        "probeFailed": True,
                    },
                ],
            },
            {"id": "empty", "channels": []},
        ],
    }


def response(status=200, payload=None, headers=None):
    """Build an aiohttp context-manager response."""
    result = MagicMock(status=status, headers=headers or {})
    result.json = AsyncMock(return_value=payload)
    result.__aenter__ = AsyncMock(return_value=result)
    result.__aexit__ = AsyncMock(return_value=False)
    return result


def test_snapshot_mapping_preserves_ids_nulls_timestamps_and_alarms():
    devices, channels = parse_snapshot(snapshot())
    assert devices[0].get_identifier() == "device123"
    assert devices[0].serial == "serial123"
    assert devices[0].signal_strength == -60
    assert devices[0].fan is None
    assert channels["empty"] == []
    assert [channel.number for channel in channels["device123"]] == ["0", "7"]
    channel = channels["device123"][0]
    assert channel.last_telemetry_saved == datetime(2025, 7, 1, 10, 15, tzinfo=timezone.utc)
    assert channel.alarm_high.alarming is True
    assert channel.alarm_high.units == "C"
    assert channels["device123"][1].value is None
    assert channels["device123"][1].units is None


def test_snapshot_maps_every_device_field_and_drives_existing_fan_entities():
    payload = snapshot()
    payload["devices"][0].update({
        "label": "Smoker",
        "displayUnits": "F",
        "firmware": "1.2.3",
        "battery": 82,
        "batteryState": "charging",
        "lastSeen": "2026-11-03T20:00:00Z",
        "transmitIntervalSeconds": 60,
        "fan": {"connected": True, "channel": "0", "setTemp": 150, "state": 1},
    })
    devices, _ = parse_snapshot(payload)
    device = devices[0]
    assert device.serial == "serial123"
    assert device.device_id == "device123"
    assert device.label == "Smoker"
    assert device.device_name == "NODE"
    assert device.device_display_units == "F"
    assert device.firmware == "1.2.3"
    assert device.battery == 82
    assert device.battery_state == "charging"
    assert device.wifi_strength == -40
    assert device.signal_strength == -60
    assert device.last_seen == datetime(2026, 11, 3, 20, tzinfo=timezone.utc)
    assert device.transmit_interval_in_seconds == 60
    assert device.fan.connected is True
    assert device.fan.connection is True
    coord = SimpleNamespace(
        last_update_success=True, get_device_by_id=lambda _: device
    )
    battery = BatterySensor("sensor.battery", coord, device)
    connected = FanConnectedSensor("binary_sensor.fan", coord, device)
    state = FanStateSensor("sensor.fan_state", coord, device)
    target = FanSetTemperatureSensor("sensor.fan_target", coord, device)
    assert battery.icon == "mdi:battery-charging-100"
    assert connected.is_on is True
    assert state.native_value == "Blowing"
    assert state.available is True
    assert target.native_value == 150
    assert target.native_unit_of_measurement == "°F"
    assert target.extra_state_attributes == {"channel": "0"}
    assert connected.device_info == state.device_info == target.device_info
    assert state.unique_id == "thermoworks_cloud-device123-fan-state"


@pytest.mark.parametrize("connected", [False, None])
def test_fan_mapping_preserves_false_zero_and_unknown_values(connected):
    payload = snapshot()
    payload["devices"][0]["fan"] = {
        "connected": connected, "channel": "0", "setTemp": 0, "state": 0,
    }
    devices, _ = parse_snapshot(payload)
    device = devices[0]
    assert device.fan.connected is connected
    assert device.fan.set_temp == 0
    assert device.fan.state_name == "Paused"
    coord = SimpleNamespace(last_update_success=True, get_device_by_id=lambda _: device)
    assert FanConnectedSensor("binary_sensor.fan", coord, device).is_on is connected
    assert FanStateSensor("sensor.fan", coord, device).available is False


def test_partial_fan_and_missing_optional_fields_do_not_invent_values():
    payload = {"devices": [{"id": "id123", "fan": {"state": 2}, "channels": []}]}
    devices, _ = parse_snapshot(payload)
    device = devices[0]
    assert device.serial == "id123"
    assert device.device_display_units is None
    assert device.battery_state is None
    assert device.fan.connected is None
    assert device.fan.fan_channel is None
    assert device.fan.set_temp is None
    assert device.fan.state_name == "Pulsing"

@pytest.mark.parametrize("payload", [{}, {"devices": [None]}, {"devices": [{"id": ""}]}])
def test_malformed_snapshot_fails_explicitly(payload):
    with pytest.raises(ApiError, match="Invalid device/channel"):
        parse_snapshot(payload)


def test_one_snapshot_request_and_etag_304_reuses_data():
    async def run():
        session = MagicMock()
        payload = snapshot()
        session.get.side_effect = [
            response(payload=payload, headers={"ETag": '"snapshot1"'}),
            response(status=304),
        ]
        api = IntegrationsApi(session, "test-key-not-real")
        assert await api.get_devices() == payload
        assert await api.get_devices() == payload
        assert session.get.call_count == 2
        args, kwargs = session.get.call_args
        assert args == (f"{API_BASE_URL}/devices",)
        assert kwargs["headers"] == {
            "Authorization": "Bearer test-key-not-real",
            "If-None-Match": '"snapshot1"',
        }
        assert kwargs["allow_redirects"] is False
    asyncio.run(run())


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_request_reauthentication(status):
    session = MagicMock()
    session.get.return_value = response(status=status)
    with pytest.raises(ApiAuthError):
        asyncio.run(IntegrationsApi(session, "test-key").get_devices())


@pytest.mark.parametrize("status", [302, 404, 500, 503])
def test_http_errors_do_not_become_success_or_auth_failure(status):
    session = MagicMock()
    session.get.return_value = response(status=status)
    with pytest.raises(ApiError, match=f"HTTP {status}"):
        asyncio.run(IntegrationsApi(session, "test-key").get_devices())


def test_network_failure_has_no_credential_in_error():
    session = MagicMock()
    session.get.side_effect = ClientConnectionError("test-key")
    with pytest.raises(ApiError) as err:
        asyncio.run(IntegrationsApi(session, "test-key").get_devices())
    assert "test-key" not in str(err.value)


def test_rate_limit_blocks_subsequent_requests_until_retry_after():
    async def run():
        session = MagicMock()
        session.get.side_effect = [
            response(status=429, headers={"Retry-After": "120"}),
            response(payload=snapshot()),
        ]
        api = IntegrationsApi(session, "test-key")
        with patch("custom_components.thermoworks_cloud.api.time.monotonic", return_value=100):
            with pytest.raises(ApiRateLimited):
                await api.get_devices()
        with patch("custom_components.thermoworks_cloud.api.time.monotonic", return_value=219):
            with pytest.raises(ApiRateLimited):
                await api.get_devices()
            assert session.get.call_count == 1
        with patch("custom_components.thermoworks_cloud.api.time.monotonic", return_value=220):
            assert await api.get_devices() == snapshot()
    asyncio.run(run())


def test_304_requires_cache_and_bad_json_is_not_cached():
    async def run():
        session = MagicMock()
        session.get.side_effect = [
            response(status=304),
            response(payload={"devices": [None]}, headers={"ETag": '"invalid"'}),
            response(payload=snapshot()),
        ]
        api = IntegrationsApi(session, "test-key")
        with pytest.raises(ApiError, match="without a cached"):
            await api.get_devices()
        with pytest.raises(ApiError):
            await api.get_devices()
        await api.get_devices()
        assert "If-None-Match" not in session.get.call_args.kwargs["headers"]
    asyncio.run(run())


def coordinator(api):
    """Exercise the actual update method without HA scheduler plumbing."""
    result = object.__new__(ThermoworksCoordinator)
    result.provider = "thermoworks"
    result.poll_interval = 60
    result.integrations_api = api
    result._registered_identifiers = set()
    return result


def test_coordinator_fetches_all_channels_once():
    api = SimpleNamespace(get_devices=AsyncMock(return_value=snapshot()))
    result = asyncio.run(coordinator(api).async_update_data())
    assert len(result.devices) == 2
    assert len(result.device_channels["device123"]) == 2
    api.get_devices.assert_awaited_once()


def test_migration_retains_legacy_serial_identifiers():
    api = SimpleNamespace(get_devices=AsyncMock(return_value=snapshot()))
    coord = coordinator(api)
    coord._registered_identifiers = {"serial123"}
    result = asyncio.run(coord.async_update_data())
    assert result.devices[0].get_identifier() == "serial123"
    assert "device123" not in result.device_channels
    assert result.device_channels["serial123"][0].number == "0"


@pytest.mark.parametrize("error,expected", [
    (ApiAuthError("revoked"), ConfigEntryAuthFailed),
    (ApiRateLimited("backoff"), UpdateFailed),
    (ApiError("server unavailable"), UpdateFailed),
])
def test_coordinator_distinguishes_authentication_and_transient_errors(error, expected):
    api = SimpleNamespace(get_devices=AsyncMock(side_effect=error))
    with pytest.raises(expected):
        asyncio.run(coordinator(api).async_update_data())


def test_legacy_thermoworks_entry_requires_key_without_password_login():
    with pytest.raises(ConfigEntryAuthFailed, match="API key"):
        asyncio.run(coordinator(None).async_update_data())


def test_old_sample_remains_available_but_failed_or_removed_probe_does_not():
    _, channels = parse_snapshot(snapshot())
    channel = channels["device123"][0]
    current = channel
    coord = SimpleNamespace(
        last_update_success=True,
        get_device_channel_by_id=lambda *args: current,
    )
    entity = TemperatureSensor("sensor.probe", coord, "device123", channel)
    alarm = HighAlarmBinarySensor("binary_sensor.alarm", coord, "device123", channel)
    assert entity.available is True
    assert alarm.available is True
    assert entity.native_value == 20.5
    assert entity.unique_id == "thermoworks_cloud-device123-0"
    assert entity.extra_state_attributes == {
        "lastTelemetrySaved": "2025-07-01T10:15:00+00:00"
    }
    channel.probe_failed = True
    assert entity.available is False
    assert alarm.available is False
    channel.probe_failed = False
    channel.value = None
    assert entity.native_value is None
    current = None
    assert entity.available is False
    assert alarm.available is False


def test_key_entries_share_polling_floor_and_reject_service_bypass():
    entry = SimpleNamespace(
        data={CONF_API_KEY: "test-key", "recommended_poll_seconds": 90},
        options={CONF_SCAN_INTERVAL: 5},
        entry_id="test",
        title="ThermoWorks",
    )
    entity = ScanIntervalNumber(entry)
    assert minimum_scan_interval(entry.data) == 90
    assert entity.native_min_value == 90
    assert entity.native_value == 90
    with pytest.raises(HomeAssistantError, match="90"):
        asyncio.run(entity.async_set_native_value(5))


def test_real_http_session_handles_json_html_and_304():
    async def run():
        requests = []

        async def handler(request):
            requests.append(request)
            assert request.headers["Authorization"] == "Bearer test-key"
            if request.path.endswith("/me"):
                return web.json_response({"accountId": "account123"})
            if request.headers.get("If-None-Match") == '"test"':
                return web.Response(status=304)
            return web.json_response(snapshot(), headers={"ETag": '"test"'})

        app = web.Application()
        app.router.add_get("/v1/{resource}", handler)
        async with TestServer(app) as server, ClientSession() as session:
            with patch(
                "custom_components.thermoworks_cloud.api.API_BASE_URL",
                str(server.make_url("/v1")),
            ):
                api = IntegrationsApi(session, "test-key")
                assert (await api.get_me())["accountId"] == "account123"
                assert await api.get_devices() == snapshot()
                assert await api.get_devices() == snapshot()
                assert len(requests) == 3

        async def html_handler(request):
            return web.Response(text="<html>SPA</html>")

        app = web.Application()
        app.router.add_get("/v1/devices", html_handler)
        async with TestServer(app) as server, ClientSession() as session:
            with patch(
                "custom_components.thermoworks_cloud.api.API_BASE_URL",
                str(server.make_url("/v1")),
            ):
                with pytest.raises(ApiError, match="Unable to read"):
                    await IntegrationsApi(session, "test-key").get_devices()

    asyncio.run(run())


def test_real_coordinator_initialization_clamps_interval_without_firebase(tmp_path):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        await dr.async_load(hass)
        entry = SimpleNamespace(
            data={CONF_API_KEY: "test-key"},
            options={CONF_SCAN_INTERVAL: 5},
            unique_id="account123",
            entry_id="test-entry",
        )
        with (
            patch("custom_components.thermoworks_cloud.coordinator.async_get_clientsession"),
            patch("custom_components.thermoworks_cloud.coordinator.AuthFactory") as factory,
        ):
            coord = ThermoworksCoordinator(hass, entry)
            assert coord.update_interval.total_seconds() == 60
            assert coord.integrations_api is not None
            factory.assert_not_called()
            await coord.async_shutdown()
    asyncio.run(run())


def test_removed_channel_and_device_callbacks_write_unavailable_state(tmp_path):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        _, channels = parse_snapshot(snapshot())
        coord = SimpleNamespace(
            last_update_success=True,
            get_device_channel_by_id=lambda *args, **kwargs: None,
            get_device_by_id=lambda *args: None,
        )
        reading = TemperatureSensor(
            "sensor.test_reading", coord, "device123", channels["device123"][0]
        )
        alarm = HighAlarmBinarySensor(
            "binary_sensor.test_alarm", coord, "device123", channels["device123"][0]
        )
        battery = BatterySensor(
            "sensor.test_battery", coord, ThermoworksDevice(serial="device123", battery=80)
        )
        for entity in (reading, alarm, battery):
            entity.hass = hass
            entity.platform = SimpleNamespace(
                platform_name="thermoworks_cloud",
                domain=entity.entity_id.split(".")[0],
                default_language_platform_translations={},
                component_translations={},
                platform_translations={},
            )
            entity._handle_coordinator_update()
            assert hass.states.get(entity.entity_id).state == "unavailable"
    asyncio.run(run())
