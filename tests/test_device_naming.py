"""Naming and identity contracts exposed by our entities to Home Assistant."""

from types import SimpleNamespace

import pytest
from thermoworks_cloud.models import Fan

from custom_components.thermoworks_cloud.binary_sensor import (
    HighAlarmBinarySensor,
    LowAlarmBinarySensor,
)
from custom_components.thermoworks_cloud.models import (
    ThermoworksChannel,
    ThermoworksDevice,
)
from custom_components.thermoworks_cloud.sensor import (
    BatterySensor,
    FanStateSensor,
    HighAlarmThresholdSensor,
    HumiditySensor,
    LowAlarmThresholdSensor,
    TemperatureSensor,
)


@pytest.mark.parametrize(
    "label, fan_name",
    [
        ("Patio BBQ", "Patio BBQ Fan"),
        (None, "unnamed device (RFX Gateway - RFX123) Fan"),
        ("", "unnamed device (RFX Gateway - RFX123) Fan"),
    ],
)
def test_device_names_preserve_cloud_labels_and_fan_fallback(label, fan_name):
    """Preserve labels verbatim; only the fan supplies its own fallback name."""
    # Setup
    coordinator = SimpleNamespace()
    device = ThermoworksDevice(
        serial="RFX123", label=label, device_name="RFX Gateway", fan=Fan(connected=True)
    )

    # Act
    battery = BatterySensor("sensor.battery", coordinator, device)
    fan = FanStateSensor("sensor.fan", coordinator, device)

    # Assert
    assertEqual(battery.device_info["name"], label)
    assertEqual(fan.device_info["name"], fan_name)


@pytest.mark.parametrize(
    "entity_class, suffix",
    [
        (TemperatureSensor, ""),
        (HumiditySensor, ""),
        (HighAlarmThresholdSensor, " High Alarm Threshold"),
        (LowAlarmThresholdSensor, " Low Alarm Threshold"),
        (HighAlarmBinarySensor, " High Alarm"),
        (LowAlarmBinarySensor, " Low Alarm"),
    ],
)
@pytest.mark.parametrize(
    "label, reading_name, alarm_name",
    [
        ("PORK Shoulder", "Pork shoulder (ch. 1)", "PORK Shoulder (Ch. 1)"),
        (None, "Unnamed channel (ch. 1)", "unnamed channel (Ch. 1)"),
        ("", "Unnamed channel (ch. 1)", "unnamed channel (Ch. 1)"),
    ],
)
def test_channel_names_preserve_existing_case_and_fallbacks(
    entity_class, suffix, label, reading_name, alarm_name
):
    """Reading names and alarm names currently use different capitalization."""
    # Setup
    channel = ThermoworksChannel(
        number="1", value=100, units="F", status="ok", label=label
    )
    entity = entity_class("sensor.channel", SimpleNamespace(), "RFX123", channel)

    # Act
    name = entity.name

    # Assert
    assert name == (alarm_name + suffix if suffix else reading_name)


@pytest.mark.parametrize(
    "device_id, expected_identifier",
    [(None, "RFX123"), ("AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff")],
)
def test_entity_identity_and_device_grouping_survive_device_id_fallback(
    device_id, expected_identifier
):
    """Existing installations depend on these IDs and device associations."""
    # Setup
    coordinator = SimpleNamespace()
    device = ThermoworksDevice(
        serial="RFX123", device_id=device_id, fan=Fan(connected=True)
    )
    channel = ThermoworksChannel(
        number="1", value=100, units="F", status="ok", label="Probe"
    )
    battery = BatterySensor("sensor.battery", coordinator, device)
    temperature = TemperatureSensor(
        "sensor.temperature", coordinator, device.get_identifier(), channel
    )
    fan = FanStateSensor("sensor.fan", coordinator, device)

    # Act
    battery_identifiers = battery.device_info["identifiers"]
    temperature_identifiers = temperature.device_info["identifiers"]
    fan_identifiers = fan.device_info["identifiers"]
    battery_unique_id = battery.unique_id
    temperature_unique_id = temperature.unique_id
    fan_unique_id = fan.unique_id

    # Assert
    parent = {("thermoworks_cloud", expected_identifier)}
    assert battery_identifiers == parent
    assert temperature_identifiers == parent
    assert fan_identifiers == {("thermoworks_cloud", f"{expected_identifier}-fan")}
    assert battery_unique_id == f"thermoworks_cloud-{expected_identifier}"
    assert temperature_unique_id == f"thermoworks_cloud-{expected_identifier}-1"
    assert fan_unique_id == f"thermoworks_cloud-{expected_identifier}-fan-state"
