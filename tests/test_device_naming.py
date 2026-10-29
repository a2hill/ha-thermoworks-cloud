"""Naming and identity contracts exposed by our entities to Home Assistant."""

from types import SimpleNamespace
from unittest import TestCase

from thermoworks_cloud.models import Fan

from custom_components.thermoworks_cloud.binary_sensor import HighAlarmBinarySensor
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
        coordinator = SimpleNamespace()

        # Act
        battery = BatterySensor("sensor.battery", coordinator, device)
        fan = FanStateSensor("sensor.fan", coordinator, device)

        # Assert
        self.assertEqual(battery.device_info["name"], "Patio BBQ")
        self.assertEqual(fan.device_info["name"], "Patio BBQ Fan")

    def test_fan_name_falls_back_when_cloud_label_is_missing(self):
        # Setup
        device = ThermoworksDevice(
            serial="RFX123",
            label=None,
            device_name="RFX Gateway",
            fan=Fan(connected=True),
        )

        # Act
        fan = FanStateSensor("sensor.fan", SimpleNamespace(), device)

        # Assert
        self.assertEqual(
            fan.device_info["name"], "unnamed device (RFX Gateway - RFX123) Fan"
        )

    def test_fan_name_falls_back_when_cloud_label_is_empty(self):
        # Setup
        device = ThermoworksDevice(
            serial="RFX123",
            label="",
            device_name="RFX Gateway",
            fan=Fan(connected=True),
        )

        # Act
        fan = FanStateSensor("sensor.fan", SimpleNamespace(), device)

        # Assert
        self.assertEqual(
            fan.device_info["name"], "unnamed device (RFX Gateway - RFX123) Fan"
        )

    def test_channel_name_capitalization(self):
        cases = [
            ("PORK Shoulder", "Pork shoulder (ch. 1)", "PORK Shoulder (Ch. 1)"),
            ("dry box", "Dry box (ch. 1)", "dry box (Ch. 1)"),
            ("Air TEMP", "Air temp (ch. 1)", "Air TEMP (Ch. 1)"),
        ]
        for label, reading_name, alarm_name in cases:
            with self.subTest(label=label):
                # Setup
                temperature_channel = ThermoworksChannel(
                    number="1", value=100, units="F", status="ok", label=label
                )
                humidity_channel = ThermoworksChannel(
                    number="1", value=50, units="H", status="ok", label=label
                )
                coordinator = SimpleNamespace()

                # Act
                temperature = TemperatureSensor(
                    "sensor.temperature", coordinator, "RFX123", temperature_channel
                )
                humidity = HumiditySensor(
                    "sensor.humidity", coordinator, "RFX123", humidity_channel
                )
                threshold = HighAlarmThresholdSensor(
                    "sensor.threshold", coordinator, "RFX123", temperature_channel
                )
                alarm = HighAlarmBinarySensor(
                    "binary_sensor.alarm", coordinator, "RFX123", temperature_channel
                )

                # Assert
                self.assertEqual(temperature.name, reading_name)
                self.assertEqual(humidity.name, reading_name)
                self.assertEqual(threshold.name, alarm_name + " High Alarm Threshold")
                self.assertEqual(alarm.name, alarm_name + " High Alarm")

    def test_channel_names_fall_back_when_label_is_missing(self):
        # Setup
        channel = ThermoworksChannel(
            number="1", value=100, units="F", status="ok", label=None
        )
        coordinator = SimpleNamespace()

        # Act
        temperature = TemperatureSensor(
            "sensor.temperature", coordinator, "RFX123", channel
        )
        threshold = HighAlarmThresholdSensor(
            "sensor.threshold", coordinator, "RFX123", channel
        )
        alarm = HighAlarmBinarySensor(
            "binary_sensor.alarm", coordinator, "RFX123", channel
        )

        # Assert
        self.assertEqual(temperature.name, "Unnamed channel (ch. 1)")
        self.assertEqual(threshold.name, "unnamed channel (Ch. 1) High Alarm Threshold")
        self.assertEqual(alarm.name, "unnamed channel (Ch. 1) High Alarm")

    def test_channel_names_fall_back_when_label_is_empty(self):
        # Setup
        channel = ThermoworksChannel(
            number="1", value=100, units="F", status="ok", label=""
        )
        coordinator = SimpleNamespace()

        # Act
        temperature = TemperatureSensor(
            "sensor.temperature", coordinator, "RFX123", channel
        )
        threshold = HighAlarmThresholdSensor(
            "sensor.threshold", coordinator, "RFX123", channel
        )
        alarm = HighAlarmBinarySensor(
            "binary_sensor.alarm", coordinator, "RFX123", channel
        )

        # Assert
        self.assertEqual(temperature.name, "Unnamed channel (ch. 1)")
        self.assertEqual(threshold.name, "unnamed channel (Ch. 1) High Alarm Threshold")
        self.assertEqual(alarm.name, "unnamed channel (Ch. 1) High Alarm")

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
        battery = BatterySensor("sensor.battery", coordinator, device)
        temperature = TemperatureSensor(
            "sensor.temperature", coordinator, device.get_identifier(), channel
        )
        fan = FanStateSensor("sensor.fan", coordinator, device)

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
        battery = BatterySensor("sensor.battery", coordinator, device)
        temperature = TemperatureSensor(
            "sensor.temperature", coordinator, device.get_identifier(), channel
        )
        fan = FanStateSensor("sensor.fan", coordinator, device)

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
