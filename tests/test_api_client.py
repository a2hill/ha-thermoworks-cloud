"""Verify API setup and coordinator behavior through the existing model boundary."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from thermoworks_cloud import ApiAuthenticationError, RateLimitError
from thermoworks_cloud.models import Account, Device, DeviceChannel

from custom_components.thermoworks_cloud import config_flow
from custom_components.thermoworks_cloud.const import (
    CLOUD_PROVIDERS,
    PROVIDER_THERMOWORKS,
)
from custom_components.thermoworks_cloud.coordinator import ThermoworksCoordinator


def test_setup_uses_account_identity_and_provider_endpoint():
    client = SimpleNamespace(get_me=AsyncMock(return_value=Account(account_id="account-1")))
    with (
        patch.object(config_flow, "async_get_clientsession", return_value="session"),
        patch.object(config_flow, "ThermoworksClient", return_value=client) as factory,
    ):
        result = asyncio.run(
            config_flow.validate_input(
                None, {"api_key": "opaque-key"}, PROVIDER_THERMOWORKS
            )
        )
    assert result["user"] == "thermoworks:account-1"
    factory.assert_called_once_with(
        "session",
        "opaque-key",
        base_url=CLOUD_PROVIDERS[PROVIDER_THERMOWORKS]["base_url"],
    )


def test_coordinator_keeps_existing_device_and_channel_identifiers():
    channel = DeviceChannel(number="1", value=23.0, units="C")
    device = Device(
        device_id="device-1", serial="serial-1", label="Kitchen", channels=[channel]
    )
    client = SimpleNamespace(get_devices=AsyncMock(return_value=[device]))
    coordinator = object.__new__(ThermoworksCoordinator)
    coordinator.client = client
    coordinator.provider = PROVIDER_THERMOWORKS
    coordinator.poll_interval = 60
    result = asyncio.run(coordinator.async_update_data())
    assert result.devices[0].get_identifier() == "device-1"
    assert result.device_channels["device-1"][0].number == "1"
    assert result.device_channels["device-1"][0].value == 23.0


@pytest.mark.parametrize(
    "error, expected",
    [
        (ApiAuthenticationError("rejected"), ConfigEntryAuthFailed),
        (RuntimeError("offline"), UpdateFailed),
    ],
)
def test_coordinator_distinguishes_authentication_and_service_errors(error, expected):
    coordinator = object.__new__(ThermoworksCoordinator)
    coordinator.client = SimpleNamespace(get_devices=AsyncMock(side_effect=error))
    coordinator.provider = PROVIDER_THERMOWORKS
    coordinator.poll_interval = 60
    with pytest.raises(expected):
        asyncio.run(coordinator.async_update_data())


def test_coordinator_passes_rate_limit_delay_to_update_failed():
    coordinator = object.__new__(ThermoworksCoordinator)
    coordinator.client = SimpleNamespace(
        get_devices=AsyncMock(side_effect=RateLimitError("limited", retry_after=12))
    )
    coordinator.provider = PROVIDER_THERMOWORKS
    coordinator.poll_interval = 60
    with pytest.raises(UpdateFailed) as error:
        asyncio.run(coordinator.async_update_data())
    assert error.value.retry_after == 12


def test_coordinator_keeps_device_without_channels():
    device = Device(device_id="device-1", serial="serial-1", channels=None)
    coordinator = object.__new__(ThermoworksCoordinator)
    coordinator.client = SimpleNamespace(get_devices=AsyncMock(return_value=[device]))
    coordinator.provider = PROVIDER_THERMOWORKS
    coordinator.poll_interval = 60
    result = asyncio.run(coordinator.async_update_data())
    assert result.device_channels["device-1"] == []
