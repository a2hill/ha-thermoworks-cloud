"""Tests for ThermoWorks fan accessory entities."""

from types import SimpleNamespace

from homeassistant.const import UnitOfTemperature
from thermoworks_cloud.models import Fan

from custom_components.thermoworks_cloud.binary_sensor import FanConnectedSensor
from custom_components.thermoworks_cloud.const import DOMAIN
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
        identifier=f"{get_identifier_for_device(device)}-fan",
    )
    state = FanStateSensor(
        "sensor.rfx_fan_state",
        coordinator,
        device,
        identifier=f"{get_identifier_for_device(device)}-fan",
    )
    set_temperature = FanSetTemperatureSensor(
        "sensor.rfx_fan_set_temperature",
        coordinator,
        device,
        identifier=f"{get_identifier_for_device(device)}-fan",
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
        identifier=f"{get_identifier_for_device(device)}-fan",
    )
    state = FanStateSensor(
        "sensor.rfx_fan_state",
        coordinator,
        device,
        identifier=f"{get_identifier_for_device(device)}-fan",
    )
    set_temperature = FanSetTemperatureSensor(
        "sensor.rfx_fan_set_temperature",
        coordinator,
        device,
        identifier=f"{get_identifier_for_device(device)}-fan",
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
        "binary_sensor.fan_connected", coordinator, device, identifier="chosen-fan"
    )

    # Assert
    assert connected.device_info["identifiers"] == {(DOMAIN, "chosen-fan")}
    assert connected.unique_id == "thermoworks_cloud-chosen-fan-connected"
