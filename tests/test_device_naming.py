"""Naming and identity contracts exposed by our entities to Home Assistant."""

from types import SimpleNamespace
from unittest import TestCase

from thermoworks_cloud.models import Fan

from custom_components.thermoworks_cloud.binary_sensor import HighAlarmBinarySensor
from custom_components.thermoworks_cloud.models import (
    ThermoworksChannel,
    ThermoworksDevice,
    ThermoworksFan,
)
from custom_components.thermoworks_cloud.sensor import (
    BatterySensor,
    FanStateSensor,
    HighAlarmThresholdSensor,
    HumiditySensor,
    TemperatureSensor,
)

RFX_DEVICE = ThermoworksDevice(serial="RFX123")


class TestDeviceNaming(TestCase):
    # Device names come from the device registry, see test_api_client.py

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

        # Act
        temperature = TemperatureSensor(
            "sensor.temperature", coordinator, RFX_DEVICE, temperature_channel
        )
        humidity = HumiditySensor(
            "sensor.humidity", coordinator, RFX_DEVICE, humidity_channel
        )
        threshold = HighAlarmThresholdSensor(
            "sensor.threshold", coordinator, RFX_DEVICE, alarm_channel
        )
        alarm = HighAlarmBinarySensor(
            "binary_sensor.alarm", coordinator, RFX_DEVICE, alarm_channel
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

        # Act
        missing_label_temperature = TemperatureSensor(
            "sensor.missing_label_temperature",
            coordinator,
            RFX_DEVICE,
            missing_label_channel,
        )
        empty_label_temperature = TemperatureSensor(
            "sensor.empty_label_temperature", coordinator, RFX_DEVICE, empty_label_channel
        )
        missing_label_threshold = HighAlarmThresholdSensor(
            "sensor.missing_label_threshold",
            coordinator,
            RFX_DEVICE,
            missing_label_channel,
        )
        empty_label_threshold = HighAlarmThresholdSensor(
            "sensor.empty_label_threshold", coordinator, RFX_DEVICE, empty_label_channel
        )
        missing_label_alarm = HighAlarmBinarySensor(
            "binary_sensor.missing_label_alarm",
            coordinator,
            RFX_DEVICE,
            missing_label_channel,
        )
        empty_label_alarm = HighAlarmBinarySensor(
            "binary_sensor.empty_label_alarm",
            coordinator,
            RFX_DEVICE,
            empty_label_channel,
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
            serial="RFX123", device_id="AABBCCDDEEFF"
        )
        channel = ThermoworksChannel(
            number="1", value=100, units="F", status="ok", label="Probe"
        )
        coordinator = SimpleNamespace()

        # Act
        battery = BatterySensor("sensor.battery", coordinator, device)
        temperature = TemperatureSensor(
            "sensor.temperature", coordinator, device, channel
        )
        fan = FanStateSensor(
            "sensor.fan", coordinator, ThermoworksFan.from_api_fan(Fan(connected=True), device)
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
            serial="RFX123", device_id=None
        )
        channel = ThermoworksChannel(
            number="1", value=100, units="F", status="ok", label="Probe"
        )
        coordinator = SimpleNamespace()

        # Act
        battery = BatterySensor("sensor.battery", coordinator, device)
        temperature = TemperatureSensor(
            "sensor.temperature", coordinator, device, channel
        )
        fan = FanStateSensor(
            "sensor.fan", coordinator, ThermoworksFan.from_api_fan(Fan(connected=True), device)
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
