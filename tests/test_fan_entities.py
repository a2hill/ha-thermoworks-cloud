"""Tests for ThermoWorks fan accessory entities."""

from types import SimpleNamespace

from homeassistant.const import UnitOfTemperature
from thermoworks_cloud.models import Device, Fan

from custom_components.thermoworks_cloud.binary_sensor import FanConnectedSensor
from custom_components.thermoworks_cloud.const import DOMAIN
from custom_components.thermoworks_cloud.models import ThermoworksDevice
from custom_components.thermoworks_cloud.sensor import (
    FanSetTemperatureSensor,
    FanStateSensor,
)

def _fan_entities(fan: Fan):
    """Build the fan entities for a gateway with this fan."""
    coordinator = SimpleNamespace(last_update_success=True)
    gateway = ThermoworksDevice.from_api_device(
        Device(serial="RFX123", label="RFX Gateway", device_display_units="F", fan=fan)
    )
    return (
        FanConnectedSensor("binary_sensor.rfx_fan_connected", coordinator, gateway),
        FanStateSensor("sensor.rfx_fan_state", coordinator, gateway),
        FanSetTemperatureSensor("sensor.rfx_fan_set_temperature", coordinator, gateway),
    )


def test_fan_entities_share_child_device_info() -> None:
    """Fan accessory entities attach to the fan's own device."""
    connected, state, set_temperature = _fan_entities(
        Fan(connected=True, fan_channel="1", set_temp=150, state=1)
    )

    assert connected.device_info == state.device_info == set_temperature.device_info
    assert connected.device_info["identifiers"] == {(DOMAIN, "RFX123-fan")}
    assert connected.is_on is True
    assert state.native_value == "Blowing"
    assert set_temperature.native_value == 150
    assert set_temperature.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT
    assert set_temperature.extra_state_attributes == {"channel": "1"}


def test_fan_value_sensors_unavailable_when_disconnected() -> None:
    """Fan state and set temperature are unavailable when the fan is disconnected."""
    connected, state, set_temperature = _fan_entities(
        Fan(connected=False, fan_channel="1", set_temp=None, state=None)
    )

    assert connected.is_on is False
    assert connected.available is True
    assert state.available is False
    assert set_temperature.available is False
