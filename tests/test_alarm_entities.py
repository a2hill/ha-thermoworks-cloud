"""Tests for ThermoWorks channel alarm entities."""

from types import SimpleNamespace

from homeassistant.const import UnitOfTemperature
from thermoworks_cloud.models import Alarm

from custom_components.thermoworks_cloud.binary_sensor import (
    HighAlarmBinarySensor,
    LowAlarmBinarySensor,
)
from custom_components.thermoworks_cloud.sensor import (
    HighAlarmThresholdSensor,
    LowAlarmThresholdSensor,
)
from custom_components.thermoworks_cloud.models import ThermoworksChannel


def test_alarm_entities_expose_thresholds_and_active_states() -> None:
    """Channel alarms expose configured values and active alarm state."""
    coordinator = SimpleNamespace(last_update_success=True)
    channel = ThermoworksChannel(
        number="1",
        value=150,
        units="F",
        status="ok",
        label="Air",
        alarm_high=Alarm(enabled=True, alarming=False, value=175, units="F"),
        alarm_low=Alarm(enabled=True, alarming=True, value=125, units="F"),
    )

    high_threshold = HighAlarmThresholdSensor(
        "sensor.rfx_air_high_alarm", coordinator, "RFX123", channel
    )
    low_threshold = LowAlarmThresholdSensor(
        "sensor.rfx_air_low_alarm", coordinator, "RFX123", channel
    )
    high_active = HighAlarmBinarySensor(
        "binary_sensor.rfx_air_high_alarm", coordinator, "RFX123", channel
    )
    low_active = LowAlarmBinarySensor(
        "binary_sensor.rfx_air_low_alarm", coordinator, "RFX123", channel
    )

    assert high_threshold.name == "Air (Ch. 1) High Alarm Threshold"
    assert high_threshold.native_value == 175
    assert high_threshold.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT
    assert high_threshold.extra_state_attributes == {
        "enabled": True,
        "alarming": False,
    }
    assert low_threshold.name == "Air (Ch. 1) Low Alarm Threshold"
    assert low_threshold.native_value == 125
    assert low_threshold.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT
    assert low_threshold.extra_state_attributes == {
        "enabled": True,
        "alarming": True,
    }
    assert high_active.name == "Air (Ch. 1) High Alarm"
    assert high_active.is_on is False
    assert high_active.extra_state_attributes == {
        "enabled": True,
        "value": 175,
        "units": "F",
    }
    assert low_active.name == "Air (Ch. 1) Low Alarm"
    assert low_active.is_on is True
    assert low_active.extra_state_attributes == {
        "enabled": True,
        "value": 125,
        "units": "F",
    }


def test_disabled_alarm_is_not_active() -> None:
    """Disabled channel alarms do not report an active problem."""
    coordinator = SimpleNamespace(last_update_success=True)
    channel = ThermoworksChannel(
        number="1",
        value=150,
        units="F",
        status="ok",
        label="Air",
        alarm_high=Alarm(enabled=False, alarming=True, value=175, units="F"),
    )

    high_active = HighAlarmBinarySensor(
        "binary_sensor.rfx_air_high_alarm", coordinator, "RFX123", channel
    )

    assert high_active.is_on is False
