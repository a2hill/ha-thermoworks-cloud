"""Verify API setup and coordinator behavior through the existing model boundary."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from thermoworks_cloud import ApiAuthenticationError, ApiError
from thermoworks_cloud.models import Device, DeviceChannel

from custom_components.thermoworks_cloud import config_flow
from custom_components.thermoworks_cloud.const import (
    CLOUD_PROVIDERS,
    PROVIDER_THERMOWORKS,
)
from custom_components.thermoworks_cloud.coordinator import ThermoworksCoordinator


def test_setup_uses_account_identity_and_provider_endpoint():
    client = SimpleNamespace(get_me=AsyncMock(return_value={"accountId": "account-1"}))
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
    device = Device(device_id="device-1", serial="serial-1", label="Kitchen")
    channel = DeviceChannel(number="1", value=23.0, units="C")
    client = SimpleNamespace(
        get_devices=AsyncMock(return_value=[device]),
        get_device_channels=lambda identifier: (
            [channel] if identifier == "device-1" else []
        ),
    )
    coordinator = object.__new__(ThermoworksCoordinator)
    coordinator.client = client
    result = asyncio.run(coordinator._async_update_api_data())
    assert result.devices[0].get_identifier() == "device-1"
    assert result.device_channels["device-1"][0].number == "1"
    assert result.device_channels["device-1"][0].value == 23.0


@pytest.mark.parametrize(
    "error, expected",
    [
        (ApiAuthenticationError("rejected"), ConfigEntryAuthFailed),
        (ApiError("offline"), UpdateFailed),
    ],
)
def test_coordinator_distinguishes_authentication_and_service_errors(error, expected):
    coordinator = object.__new__(ThermoworksCoordinator)
    coordinator.client = SimpleNamespace(get_devices=AsyncMock(side_effect=error))
    with pytest.raises(expected):
        asyncio.run(coordinator._async_update_api_data())
