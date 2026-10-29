"""Naming and identity contracts exposed to Home Assistant."""

from types import SimpleNamespace
from unittest import TestCase

from thermoworks_cloud.models import Fan

from custom_components.thermoworks_cloud.binary_sensor import HighAlarmBinarySensor
from custom_components.thermoworks_cloud.device import (
    device_metadata,
    fan_metadata,
    get_identifier_for_device,
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
    TemperatureSensor,
)


class TestDeviceNaming(TestCase):
    def test_device_names_use_the_cloud_label(self):
        # Setup
        device = ThermoworksDevice(
            serial="RFX123", label="Patio BBQ", fan=Fan(connected=True)
        )

        # Act
        device_info = device_metadata(device)
        fan_info = fan_metadata(device)

        # Assert
        self.assertEqual(device_info["name"], "Patio BBQ")
        self.assertEqual(fan_info["name"], "Patio BBQ Fan")

    def test_fan_name_falls_back_for_missing_or_empty_cloud_label(self):
        # Setup
        missing_label_device = ThermoworksDevice(
            serial="RFX123",
            label=None,
            device_name="RFX Gateway",
            fan=Fan(connected=True),
        )
        empty_label_device = ThermoworksDevice(
            serial="RFX123",
            label="",
            device_name="RFX Gateway",
            fan=Fan(connected=True),
        )

        # Act
        missing_label_fan_info = fan_metadata(missing_label_device)
        empty_label_fan_info = fan_metadata(empty_label_device)

        # Assert
        self.assertEqual(
            missing_label_fan_info["name"],
            "unnamed device (RFX Gateway - RFX123) Fan",
        )
        self.assertEqual(
            empty_label_fan_info["name"],
            "unnamed device (RFX Gateway - RFX123) Fan",
        )

    def test_channel_name_capitalization(self):
        # Setup
        temperature_channel = ThermoworksChannel(
            number="1", value=100, units="F", status="ok", label="PORK Shoulder"
        )
        humidity_channel = ThermoworksChannel(
            number="2", value=50, units="H", status="ok", label="dry box"
        )
        alarm_channel = ThermoworksChannel(
            number="3", value=200, units="F", status="ok", label="Air TEMP"
        )
        coordinator = SimpleNamespace()
        device = ThermoworksDevice(serial="RFX123")

        # Act
        temperature = TemperatureSensor(
            "sensor.temperature",
            coordinator,
            device,
            temperature_channel,
            identifier=get_identifier_for_device(device),
        )
        humidity = HumiditySensor(
            "sensor.humidity",
            coordinator,
            device,
            humidity_channel,
            identifier=get_identifier_for_device(device),
        )
        threshold = HighAlarmThresholdSensor(
            "sensor.threshold",
            coordinator,
            device,
            alarm_channel,
            identifier=get_identifier_for_device(device),
        )
        alarm = HighAlarmBinarySensor(
            "binary_sensor.alarm",
            coordinator,
            device,
            alarm_channel,
            identifier=get_identifier_for_device(device),
        )

        # Assert
        self.assertEqual(temperature.name, "Pork shoulder (ch. 1)")
        self.assertEqual(humidity.name, "Dry box (ch. 2)")
        self.assertEqual(threshold.name, "Air TEMP (Ch. 3) High Alarm Threshold")
        self.assertEqual(alarm.name, "Air TEMP (Ch. 3) High Alarm")

    def test_channel_names_fall_back_for_missing_or_empty_label(self):
        # Setup
        missing_label_channel = ThermoworksChannel(
            number="1", value=100, units="F", status="ok", label=None
        )
        empty_label_channel = ThermoworksChannel(
            number="2", value=100, units="F", status="ok", label=""
        )
        coordinator = SimpleNamespace()
        device = ThermoworksDevice(serial="RFX123")

        # Act
        missing_label_temperature = TemperatureSensor(
            "sensor.missing_label_temperature",
            coordinator,
            device,
            missing_label_channel,
            identifier=get_identifier_for_device(device),
        )
        empty_label_temperature = TemperatureSensor(
            "sensor.empty_label_temperature",
            coordinator,
            device,
            empty_label_channel,
            identifier=get_identifier_for_device(device),
        )
        missing_label_threshold = HighAlarmThresholdSensor(
            "sensor.missing_label_threshold",
            coordinator,
            device,
            missing_label_channel,
            identifier=get_identifier_for_device(device),
        )
        empty_label_threshold = HighAlarmThresholdSensor(
            "sensor.empty_label_threshold",
            coordinator,
            device,
            empty_label_channel,
            identifier=get_identifier_for_device(device),
        )
        missing_label_alarm = HighAlarmBinarySensor(
            "binary_sensor.missing_label_alarm",
            coordinator,
            device,
            missing_label_channel,
            identifier=get_identifier_for_device(device),
        )
        empty_label_alarm = HighAlarmBinarySensor(
            "binary_sensor.empty_label_alarm",
            coordinator,
            device,
            empty_label_channel,
            identifier=get_identifier_for_device(device),
        )

        # Assert
        self.assertEqual(missing_label_temperature.name, "Unnamed channel (ch. 1)")
        self.assertEqual(empty_label_temperature.name, "Unnamed channel (ch. 2)")
        self.assertEqual(
            missing_label_threshold.name, "unnamed channel (Ch. 1) High Alarm Threshold"
        )
        self.assertEqual(
            empty_label_threshold.name, "unnamed channel (Ch. 2) High Alarm Threshold"
        )
        self.assertEqual(missing_label_alarm.name, "unnamed channel (Ch. 1) High Alarm")
        self.assertEqual(empty_label_alarm.name, "unnamed channel (Ch. 2) High Alarm")

    def test_entity_identity_uses_device_id_when_available(self):
        # Setup
        device = ThermoworksDevice(
            serial="RFX123", device_id="AABBCCDDEEFF", fan=Fan(connected=True)
        )
        channel = ThermoworksChannel(
            number="1", value=100, units="F", status="ok", label="Probe"
        )
        coordinator = SimpleNamespace()

        # Act
        battery = BatterySensor(
            "sensor.battery",
            coordinator,
            device,
            identifier=get_identifier_for_device(device),
        )
        temperature = TemperatureSensor(
            "sensor.temperature",
            coordinator,
            device,
            channel,
            identifier=get_identifier_for_device(device),
        )
        fan = FanStateSensor(
            "sensor.fan",
            coordinator,
            device,
            identifier=f"{get_identifier_for_device(device)}-fan",
        )

        # Assert
        self.assertEqual(
            battery.device_info["identifiers"],
            {("thermoworks_cloud", "aa:bb:cc:dd:ee:ff")},
        )
        self.assertEqual(
            temperature.device_info["identifiers"], battery.device_info["identifiers"]
        )
        self.assertEqual(
            fan.device_info["identifiers"],
            {("thermoworks_cloud", "aa:bb:cc:dd:ee:ff-fan")},
        )
        self.assertEqual(battery.unique_id, "thermoworks_cloud-aa:bb:cc:dd:ee:ff")
        self.assertEqual(temperature.unique_id, "thermoworks_cloud-aa:bb:cc:dd:ee:ff-1")
        self.assertEqual(fan.unique_id, "thermoworks_cloud-aa:bb:cc:dd:ee:ff-fan-state")

    def test_entity_identity_falls_back_to_serial_when_device_id_is_missing(self):
        # Setup
        device = ThermoworksDevice(
            serial="RFX123", device_id=None, fan=Fan(connected=True)
        )
        channel = ThermoworksChannel(
            number="1", value=100, units="F", status="ok", label="Probe"
        )
        coordinator = SimpleNamespace()

        # Act
        battery = BatterySensor(
            "sensor.battery",
            coordinator,
            device,
            identifier=get_identifier_for_device(device),
        )
        temperature = TemperatureSensor(
            "sensor.temperature",
            coordinator,
            device,
            channel,
            identifier=get_identifier_for_device(device),
        )
        fan = FanStateSensor(
            "sensor.fan",
            coordinator,
            device,
            identifier=f"{get_identifier_for_device(device)}-fan",
        )

        # Assert
        self.assertEqual(
            battery.device_info["identifiers"], {("thermoworks_cloud", "RFX123")}
        )
        self.assertEqual(
            temperature.device_info["identifiers"], battery.device_info["identifiers"]
        )
        self.assertEqual(
            fan.device_info["identifiers"], {("thermoworks_cloud", "RFX123-fan")}
        )
        self.assertEqual(battery.unique_id, "thermoworks_cloud-RFX123")
        self.assertEqual(temperature.unique_id, "thermoworks_cloud-RFX123-1")
        self.assertEqual(fan.unique_id, "thermoworks_cloud-RFX123-fan-state")
