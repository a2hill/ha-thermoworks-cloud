"""Tests for ThermoWorks fan accessory entities."""

import logging
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.entity_component import EntityComponent
from thermoworks_cloud.models import Fan

from custom_components.thermoworks_cloud.binary_sensor import FanConnectedSensor
from custom_components.thermoworks_cloud.const import DOMAIN
from custom_components.thermoworks_cloud.coordinator import (
    ThermoworksCoordinator,
    ThermoworksData,
)
from custom_components.thermoworks_cloud.device import (
    fan_metadata,
    get_identifier_for_device,
)
from custom_components.thermoworks_cloud.models import ThermoworksDevice
from custom_components.thermoworks_cloud.sensor import (
    FanSetTemperatureSensor,
    FanStateSensor,
)


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
        "binary_sensor.rfx_fan_connected",
        coordinator,
        device,
        registry_identifier=f"{get_identifier_for_device(device)}-fan",
    )
    state = FanStateSensor(
        "sensor.rfx_fan_state",
        coordinator,
        device,
        registry_identifier=f"{get_identifier_for_device(device)}-fan",
    )
    set_temperature = FanSetTemperatureSensor(
        "sensor.rfx_fan_set_temperature",
        coordinator,
        device,
        registry_identifier=f"{get_identifier_for_device(device)}-fan",
    )

    assert connected.device_info == state.device_info == set_temperature.device_info
    assert connected.device_info["identifiers"] == {(DOMAIN, "RFX123-fan")}
    assert fan_metadata(device)["name"] == "RFX Gateway Fan"
    assert fan_metadata(device)["via_device"] == (DOMAIN, "RFX123")
    assert connected.unique_id == "thermoworks_cloud-RFX123-fan-connected"
    assert state.unique_id == "thermoworks_cloud-RFX123-fan-state"
    assert set_temperature.unique_id == "thermoworks_cloud-RFX123-fan-set-temperature"
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
        "binary_sensor.rfx_fan_connected",
        coordinator,
        device,
        registry_identifier=f"{get_identifier_for_device(device)}-fan",
    )
    state = FanStateSensor(
        "sensor.rfx_fan_state",
        coordinator,
        device,
        registry_identifier=f"{get_identifier_for_device(device)}-fan",
    )
    set_temperature = FanSetTemperatureSensor(
        "sensor.rfx_fan_set_temperature",
        coordinator,
        device,
        registry_identifier=f"{get_identifier_for_device(device)}-fan",
    )

    assert connected.is_on is False
    assert connected.available is True
    assert state.available is False
    assert set_temperature.available is False


def test_fan_connection_sensor_uses_the_supplied_device_identifier() -> None:
    # Setup
    device = ThermoworksDevice(serial="RFX123", fan=Fan(connected=True))
    coordinator = SimpleNamespace()

    # Act
    connected = FanConnectedSensor(
        "binary_sensor.fan_connected",
        coordinator,
        device,
        registry_identifier="chosen-fan",
    )

    # Assert
    assert connected.device_info["identifiers"] == {(DOMAIN, "chosen-fan")}
    assert connected.unique_id == "thermoworks_cloud-chosen-fan-connected"


class TestFanConnectionUpdates(IsolatedAsyncioTestCase):
    async def test_refresh_reads_source_device_and_preserves_fan_registry_identity(
        self,
    ):
        # Setup
        hass = HomeAssistant(self.enterContext(TemporaryDirectory()))
        await device_registry.async_load(hass)
        await entity_registry.async_load(hass)
        entry = SimpleNamespace(
            data={"email": "test@example.com", "password": "test"},
            options={},
            unique_id="account-one",
        )
        coordinator = ThermoworksCoordinator(hass, entry)
        self.addAsyncCleanup(hass.async_stop, force=True)
        device = ThermoworksDevice(
            serial="RFX123", device_id="AABBCCDDEEFF", fan=Fan(connected=True)
        )
        coordinator.async_set_updated_data(ThermoworksData([device], {}))
        connected = FanConnectedSensor(
            "binary_sensor.fan_connected",
            coordinator,
            device,
            registry_identifier="aa:bb:cc:dd:ee:ff-fan",
        )
        component = EntityComponent(logging.getLogger(__name__), "binary_sensor", hass)
        await component.async_add_entities([connected])
        self.addAsyncCleanup(connected.async_remove)
        self.assertTrue(connected.is_on)

        # Act
        updated_device = ThermoworksDevice(
            serial="RFX123", device_id="AABBCCDDEEFF", fan=Fan(connected=False)
        )
        coordinator.async_set_updated_data(ThermoworksData([updated_device], {}))

        # Assert
        self.assertEqual(hass.states.get(connected.entity_id).state, "off")
        self.assertFalse(connected.is_on)
        self.assertEqual(
            connected.device_info["identifiers"],
            {(DOMAIN, "aa:bb:cc:dd:ee:ff-fan")},
        )
        self.assertEqual(
            connected.unique_id, "thermoworks_cloud-aa:bb:cc:dd:ee:ff-fan-connected"
        )
