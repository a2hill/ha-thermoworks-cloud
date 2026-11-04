"""Tests for ThermoWorks fan accessory entities."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import UpdateFailed
from thermoworks_cloud.models import Fan

from custom_components.thermoworks_cloud import PLATFORMS, async_setup_entry
from custom_components.thermoworks_cloud import binary_sensor, sensor
from custom_components.thermoworks_cloud.binary_sensor import FanConnectedSensor
from custom_components.thermoworks_cloud.const import DOMAIN
from custom_components.thermoworks_cloud.models import ThermoworksDevice
from custom_components.thermoworks_cloud.sensor import (
    FanSetTemperatureSensor,
    FanStateSensor,
)


@pytest.mark.parametrize("device_id", [None, "aabbccddeeff"])
def test_setup_registers_fan_link_before_platforms(device_id: str | None) -> None:
    """Link the fan to its registered gateway even without gateway entities."""
    device = ThermoworksDevice(
        serial="RFX123", device_id=device_id, fan=Fan(connected=False)
    )
    coordinator = SimpleNamespace(
        api=object(),
        data=SimpleNamespace(
            devices=[device, ThermoworksDevice(serial="NOFAN")], device_channels={}
        ),
        async_config_entry_first_refresh=AsyncMock(),
    )
    registry = Mock()
    registry.async_get_or_create.return_value = SimpleNamespace(id="gateway-id")

    def lookup_parent(identifier, config_entry_id):
        registry.async_get_or_create.assert_called_once_with(
            config_entry_id=config_entry_id, identifiers={identifier}
        )
        return SimpleNamespace(id="gateway-id")

    registry.async_get_device_by_identifier.side_effect = lookup_parent

    async def forward_platforms(entry, platforms):
        # Both platforms resolve the parent using the real HA lookup helper.
        entities = []
        with (
            patch.object(
                binary_sensor, "async_generate_entity_id", return_value="binary_sensor.fan"
            ),
            patch.object(sensor, "async_generate_entity_id", return_value="sensor.fan"),
        ):
            await binary_sensor.async_setup_entry(hass, entry, entities.extend)
            await sensor.async_setup_entry(hass, entry, entities.extend)
        assert len(entities) == 3
        assert registry.async_get_device_by_identifier.call_args_list == [
            call((DOMAIN, format_mac(device.get_identifier())), entry.entry_id),
            call((DOMAIN, format_mac(device.get_identifier())), entry.entry_id),
        ]
        # Reading device info must not require another registry lookup.
        registry.async_get_device_by_identifier.reset_mock()
        assert all(
            entity.device_info["via_device_id"] == "gateway-id" for entity in entities
        )
        registry.async_get_device_by_identifier.assert_not_called()
        assert platforms == PLATFORMS

    hass = SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(side_effect=forward_platforms)
        ),
    )
    entry = Mock(entry_id="config-entry-id")
    with (
        patch(
            "custom_components.thermoworks_cloud.ThermoworksCoordinator",
            return_value=coordinator,
        ),
        patch("custom_components.thermoworks_cloud.dr.async_get", return_value=registry),
    ):
        assert asyncio.run(async_setup_entry(hass, entry)) is True

    identifier = format_mac(device.get_identifier())
    assert registry.async_get_or_create.call_args_list == [
        call(config_entry_id=entry.entry_id, identifiers={(DOMAIN, identifier)}),
    ]
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS
    )


@pytest.mark.parametrize("platform", [binary_sensor, sensor])
def test_fan_setup_rejects_missing_parent(platform) -> None:
    """A missing parent produces HA's descriptive registry lookup error."""
    device = ThermoworksDevice(serial="RFX123", fan=Fan(connected=True))
    coordinator = SimpleNamespace(data=SimpleNamespace(devices=[device]))
    entry = SimpleNamespace(entry_id="config-entry-id")
    hass = SimpleNamespace(
        data={DOMAIN: {entry.entry_id: SimpleNamespace(coordinator=coordinator)}}
    )
    registry = Mock()
    registry.async_get_device_by_identifier.return_value = None
    add_entities = Mock()
    with (
        patch("custom_components.thermoworks_cloud.dr.async_get", return_value=registry),
        patch.object(platform, "async_generate_entity_id", return_value="sensor.fan"),
        pytest.raises(ValueError, match="There is no device with identifier"),
    ):
        asyncio.run(platform.async_setup_entry(hass, entry, add_entities))
    add_entities.assert_not_called()


def test_fan_entities_share_child_device_info() -> None:
    """Fan accessory entities are grouped under a child fan device."""
    coordinator = SimpleNamespace(last_update_success=True)
    device = ThermoworksDevice(
        serial="RFX123",
        label="RFX Gateway",
        device_display_units="F",
        fan=Fan(connected=True, fan_channel="1", set_temp=150, state=1),
    )

    connected = FanConnectedSensor(
        "binary_sensor.rfx_fan_connected", coordinator, device,
        gateway_registry_id="gateway-registry-id",
    )
    state = FanStateSensor(
        "sensor.rfx_fan_state", coordinator, device,
        gateway_registry_id="gateway-registry-id",
    )
    set_temperature = FanSetTemperatureSensor(
        "sensor.rfx_fan_set_temperature", coordinator, device,
        gateway_registry_id="gateway-registry-id",
    )

    assert connected.device_info == state.device_info == set_temperature.device_info
    assert connected.device_info["identifiers"] == {(DOMAIN, "RFX123-fan")}
    assert connected.device_info["name"] == "RFX Gateway Fan"
    assert "via_device" not in connected.device_info
    assert connected.device_info["via_device_id"] == "gateway-registry-id"
    assert connected.is_on is True
    assert state.native_value == "Blowing"
    assert set_temperature.native_value == 150
    assert set_temperature.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT
    assert set_temperature.extra_state_attributes == {"channel": "1"}


def test_fan_value_sensors_unavailable_when_disconnected() -> None:
    """Fan state and set temperature are unavailable when the fan is disconnected."""
    coordinator = SimpleNamespace(last_update_success=True)
    device = ThermoworksDevice(
        serial="RFX123",
        label="RFX Gateway",
        device_display_units="F",
        fan=Fan(connected=False, fan_channel="1", set_temp=None, state=None),
    )

    connected = FanConnectedSensor(
        "binary_sensor.rfx_fan_connected", coordinator, device,
        gateway_registry_id="gateway-registry-id",
    )
    state = FanStateSensor(
        "sensor.rfx_fan_state", coordinator, device,
        gateway_registry_id="gateway-registry-id",
    )
    set_temperature = FanSetTemperatureSensor(
        "sensor.rfx_fan_set_temperature", coordinator, device,
        gateway_registry_id="gateway-registry-id",
    )

    assert connected.is_on is False
    assert connected.available is True
    assert state.available is False
    assert set_temperature.available is False


@pytest.mark.parametrize(
    "entity_class", [FanConnectedSensor, FanStateSensor, FanSetTemperatureSensor]
)
def test_fan_entities_refresh_shared_device_information(entity_class) -> None:
    """All fan entity types adopt updated device data and publish their state."""
    device = ThermoworksDevice(serial="RFX123", fan=Fan(connected=True))
    updated_device = ThermoworksDevice(
        serial="RFX123", label="Renamed Gateway", fan=Fan(connected=False)
    )
    coordinator = SimpleNamespace(
        last_update_success=True,
        get_device_by_id=Mock(return_value=updated_device),
    )
    entity = entity_class(
        "sensor.fan", coordinator, device, gateway_registry_id="gateway-id"
    )
    with patch.object(entity, "async_write_ha_state") as write_state:
        entity._handle_coordinator_update()
    coordinator.get_device_by_id.assert_called_once_with("RFX123")
    write_state.assert_called_once_with()
    assert entity.device_info["name"] == "Renamed Gateway Fan"
    assert entity.device_info["via_device_id"] == "gateway-id"
    assert entity.available is (entity_class is FanConnectedSensor)


@pytest.mark.parametrize(
    "entity_class", [FanConnectedSensor, FanStateSensor, FanSetTemperatureSensor]
)
@pytest.mark.parametrize(
    "updated_device, error",
    [
        (None, "is not found"),
        (ThermoworksDevice(serial="RFX123"), "missing required attribute"),
    ],
)
def test_fan_entities_reject_invalid_updates(entity_class, updated_device, error) -> None:
    """Missing devices and missing fan data fail consistently across platforms."""
    device = ThermoworksDevice(serial="RFX123", fan=Fan(connected=True))
    coordinator = SimpleNamespace(get_device_by_id=Mock(return_value=updated_device))
    entity = entity_class(
        "sensor.fan", coordinator, device, gateway_registry_id="gateway-id"
    )
    # Name translation normally requires the platform to have added the entity.
    entity._attr_name = "Fan"
    with (
        patch.object(entity, "async_write_ha_state") as write_state,
        pytest.raises(UpdateFailed, match=error),
    ):
        entity._handle_coordinator_update()
    write_state.assert_not_called()
