"""Sensors representing a Thermoworks thermometer.

Each sensor's `parse` method says what it needs from a device or channel, and the base
classes in `entity.py` handle updates and availability the same way for all of them.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import format_mac, DeviceInfo
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from thermoworks_cloud.models import Alarm, Fan

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator
from .entity import ThermoworksChannelEntity, ThermoworksDeviceEntity
from .models import ThermoworksChannel, ThermoworksDevice

_LOGGER: logging.Logger = logging.getLogger(__package__)

# Channel units the API reports, mapped to Home Assistant units
TEMPERATURE_UNITS = {"F": UnitOfTemperature.FAHRENHEIT, "C": UnitOfTemperature.CELSIUS}
HUMIDITY_UNIT = "H"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""

    coordinator: ThermoworksCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ].coordinator

    new_entities: list[SensorEntity] = []
    for device in coordinator.data.devices.values():
        identifier = device.get_identifier()

        for device_sensor in DEVICE_SENSORS:
            if not device_sensor.supported(device):
                _LOGGER.debug("Not creating %s sensor for device %s",
                              device_sensor.entity_suffix, device.display_name())
                continue
            new_entities.append(
                device_sensor(
                    entity_id=async_generate_entity_id(
                        ENTITY_ID_FORMAT,
                        f"{identifier}_{device_sensor.entity_suffix}",
                        hass=hass,
                    ),
                    coordinator=coordinator,
                    device=device,
                )
            )

        for device_channel in device.channels.values():
            if device_channel.units not in (*TEMPERATURE_UNITS, HUMIDITY_UNIT):
                _LOGGER.warning(
                    "Unsupported sensor unit '%s' for device %s channel %s - skipping",
                    device_channel.units,
                    device.display_name(),
                    device_channel.display_name()
                )

            for channel_sensor in CHANNEL_SENSORS:
                if not channel_sensor.supported(device_channel):
                    continue
                new_entities.append(
                    channel_sensor(
                        entity_id=async_generate_entity_id(
                            ENTITY_ID_FORMAT,
                            f"{identifier}_ch_{device_channel.number}_{channel_sensor.entity_suffix}",
                            hass=hass,
                        ),
                        coordinator=coordinator,
                        device_serial=identifier,
                        device_channel=device_channel,
                    )
                )

    if len(new_entities) > 0:
        _LOGGER.debug("New entities to create: %d", len(new_entities))
        async_add_entities(new_entities)
    else:
        _LOGGER.debug("No new entities created")


@dataclass(frozen=True)
class BatteryReading:
    """Battery level and whether it's charging."""

    level: float
    charging: bool


class DeviceSensor[T](ThermoworksDeviceEntity[T], SensorEntity):
    """Base class for sensors on the device itself."""

    # Used in the entity id: {device identifier}_{entity_suffix}
    entity_suffix: str

    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Identifiers are what group entities into the same device.
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{format_mac(self._device.get_identifier())}",
                )
            }
        )


class BatterySensor(DeviceSensor[BatteryReading]):
    """Implementation of a sensor."""

    entity_suffix = "battery"

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
    _attr_device_class = SensorDeviceClass.BATTERY

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
    _attr_state_class = SensorStateClass.MEASUREMENT

    # Naming
    # https://developers.home-assistant.io/docs/core/entity#entity-naming
    # https://developers.home-assistant.io/docs/internationalization/core/#name-of-entities
    _attr_translation_key = "battery"

    # API data is in percent with no decimal place
    # https://developers.home-assistant.io/docs/core/entity/sensor#properties
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> BatteryReading | None:
        if device.battery is None:
            return None
        return BatteryReading(float(device.battery), device.battery_state == "charging")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # The battery sensor registers the device's details; the others only reference it.
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{format_mac(self._device.get_identifier())}",
                )
            },
            name=self._device.label,
            sw_version=self._device.firmware,
            manufacturer="ThermoWorks",
            model=self._device.device_name,
            serial_number=self._device.serial,
        )

    @property
    def icon(self) -> str | None:
        """Return the icon to use in the frontend, if any."""
        # Only handle charging, as HA doesn't natively support a charging icon
        if self._value is not None and self._value.charging:
            return "mdi:battery-charging-100"

        return None

    @property
    def native_value(self) -> float | None:
        """Return the state of the entity."""
        return self._value.level if self._value is not None else None

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.  Think carefully what you want this to be as
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{format_mac(self._device.get_identifier())}"


class SignalSensor(DeviceSensor[float]):
    """Implementation of a sensor."""

    entity_suffix = "signal"

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
    _attr_state_class = SensorStateClass.MEASUREMENT

    _attr_translation_key = "signal"

    # API data is in negative decibels with no decimal place
    # https://developers.home-assistant.io/docs/core/entity/sensor#properties
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_suggested_display_precision = 0

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> float | None:
        if device.signal_strength is None:
            return None
        return float(device.signal_strength)

    @property
    def native_value(self) -> float | None:
        """Return the state of the entity."""
        return self._value

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{format_mac(self._device.get_identifier())}-signal"


class LastSeenSensor(DeviceSensor[datetime]):
    """Implementation of a last seen timestamp sensor."""

    entity_suffix = "last_seen"

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_seen"

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> datetime | None:
        # Already parsed into UTC by the device model
        return device.last_seen

    @property
    def native_value(self) -> datetime | None:
        return self._value

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}-{format_mac(self._device.get_identifier())}-last-seen"


class TransmitIntervalSensor(DeviceSensor[int]):
    """Implementation of a transmit interval sensor."""

    entity_suffix = "transmit_interval"

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_translation_key = "transmit_interval"

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> int | None:
        return device.transmit_interval_in_seconds

    @property
    def native_value(self) -> int | None:
        return self._value

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}-{format_mac(self._device.get_identifier())}-transmit-interval"


class FanSensor(DeviceSensor[Fan]):
    """Base class for Thermoworks fan accessory sensors.

    Created for any device that reports a fan, but only available while the fan is
    connected, since a disconnected fan still reports its last values.
    """

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> Fan | None:
        return device.connected_fan

    @classmethod
    def supported(cls, device: ThermoworksDevice) -> bool:
        return device.fan is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return fan device information."""
        gateway_identifier = format_mac(self._device.get_identifier())
        return DeviceInfo(
            identifiers={(DOMAIN, f"{gateway_identifier}-fan")},
            name=f"{self._device.label or self._device.display_name()} Fan",
            manufacturer="ThermoWorks",
            via_device=(DOMAIN, gateway_identifier),
        )


class FanStateSensor(FanSensor):
    """Implementation of a Thermoworks fan state sensor."""

    entity_suffix = "fan_state"

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["Paused", "Blowing", "Pulsing"]
    _attr_translation_key = "fan_state"

    @property
    def native_value(self) -> str | None:
        """Return the fan state name."""
        return self._value.state_name if self._value is not None else None

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{format_mac(self._device.get_identifier())}-fan-state"


class FanSetTemperatureSensor(FanSensor):
    """Implementation of a Thermoworks fan set temperature sensor."""

    entity_suffix = "fan_set_temperature"

    _attr_suggested_display_precision = 0
    _attr_translation_key = "fan_set_temperature"

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class when the API reports a temperature unit."""
        return (
            SensorDeviceClass.TEMPERATURE
            if self.native_unit_of_measurement is not None
            else None
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of temperature."""
        return TEMPERATURE_UNITS.get(self._device.device_display_units)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return fan set temperature attributes."""
        if self._value is None or self._value.fan_channel is None:
            return {}

        return {"channel": self._value.fan_channel}

    @property
    def native_value(self) -> int | None:
        """Return the fan set temperature."""
        return self._value.set_temp if self._value is not None else None

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{format_mac(self._device.get_identifier())}-fan-set-temperature"


class ChannelSensor[T](ThermoworksChannelEntity[T], SensorEntity):
    """Base class for thermoworks channel sensors."""

    # Used in the entity id: {device identifier}_ch_{channel number}_{entity_suffix}
    entity_suffix: str

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    # Changes on device contact without a new measurement, which would bloat the recorder
    _unrecorded_attributes = frozenset({"last_seen"})

    # API data is given at higher precision, but that isn't needed
    # https://developers.home-assistant.io/docs/core/entity/sensor#properties
    _attr_suggested_display_precision = 1

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{format_mac(self._device_serial)}",
                )
            }
        )

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        # This is the name that will be shown in the Entity UI.
        # It is the name of the channel, not the device.
        return self._device_channel.display_name().capitalize()

    @property
    def translation_placeholders(self) -> Mapping[str, str]:
        """Placeholder values for string internationalization."""
        return {"channel_name": self._device_channel.display_name()}

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        """Expose source metadata separately from Home Assistant's state update time."""
        channel = self._device_channel
        return {
            "channel_id": channel.id,
            "status": channel.status,
            "enabled": channel.enabled,
            "probe_failed": channel.probe_failed,
            "alarming": channel.alarming,
            "last_telemetry_saved": (
                channel.last_telemetry_saved.isoformat() if channel.last_telemetry_saved else None
            ),
            "last_seen": channel.last_seen.isoformat() if channel.last_seen else None,
        }

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.  Think carefully what you want this to be as
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{format_mac(self._device_serial)}-{self._device_channel.number}"


class MeasurementSensor(ChannelSensor[float]):
    """Base class for sensors showing a channel's reading.

    Created from the channel's units, even before it has a reading, so a probe that
    isn't plugged in yet still gets its entity. It's available only with a valid reading.
    """

    @property
    def native_value(self) -> float | None:
        """Return the state of the entity."""
        return self._value


class TemperatureSensor(MeasurementSensor):
    """Implementation of a thermoworks temperature sensor."""

    entity_suffix = "temperature"

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    # Naming
    # https://developers.home-assistant.io/docs/core/entity#entity-naming
    # https://developers.home-assistant.io/docs/internationalization/core/#name-of-entities
    _attr_translation_key = "temperature"

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> float | None:
        return channel.reading if cls.supported(channel) else None

    @classmethod
    def supported(cls, channel: ThermoworksChannel) -> bool:
        return channel.units in TEMPERATURE_UNITS

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of temperature."""
        return TEMPERATURE_UNITS.get(self._device_channel.units)


class HumiditySensor(MeasurementSensor):
    """Implementation of a thermoworks humidity sensor."""

    entity_suffix = "humidity"

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
    _attr_device_class = SensorDeviceClass.HUMIDITY

    # Naming
    # https://developers.home-assistant.io/docs/core/entity#entity-naming
    # https://developers.home-assistant.io/docs/internationalization/core/#name-of-entities
    _attr_translation_key = "humidity"

    # API data is in percent
    # https://developers.home-assistant.io/docs/core/entity/sensor#properties
    _attr_native_unit_of_measurement = PERCENTAGE

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> float | None:
        return channel.reading if cls.supported(channel) else None

    @classmethod
    def supported(cls, channel: ThermoworksChannel) -> bool:
        return channel.units == HUMIDITY_UNIT


class AlarmThresholdSensor(ChannelSensor[Alarm]):
    """Base class for Thermoworks channel alarm threshold sensors.

    The threshold is a setting, not a measurement, so it doesn't depend on the reading.
    """

    _attr_suggested_display_precision = 0

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the alarm threshold device class."""
        if self.native_unit_of_measurement in TEMPERATURE_UNITS.values():
            return SensorDeviceClass.TEMPERATURE
        if self.native_unit_of_measurement == PERCENTAGE:
            return SensorDeviceClass.HUMIDITY

        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return alarm threshold unit."""
        if self._value is None:
            return None
        if self._value.units == HUMIDITY_UNIT:
            return PERCENTAGE
        return TEMPERATURE_UNITS.get(self._value.units)

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        """Return alarm metadata."""
        if self._value is None:
            return {
                "enabled": None,
                "alarming": None,
            }
        return {
            "enabled": self._value.enabled,
            "alarming": self._value.alarming,
        }

    @property
    def native_value(self) -> float | None:
        """Return the configured alarm threshold."""
        return self._value.value if self._value is not None else None


class HighAlarmThresholdSensor(AlarmThresholdSensor):
    """Implementation of a Thermoworks channel high alarm threshold sensor."""

    entity_suffix = "high_alarm_threshold"

    _attr_translation_key = "high_alarm_threshold"

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> Alarm | None:
        return channel.alarm_high

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._device_channel.display_name()} High Alarm Threshold"

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{format_mac(self._device_serial)}-{self._device_channel.number}-high-alarm-threshold"


class LowAlarmThresholdSensor(AlarmThresholdSensor):
    """Implementation of a Thermoworks channel low alarm threshold sensor."""

    entity_suffix = "low_alarm_threshold"

    _attr_translation_key = "low_alarm_threshold"

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> Alarm | None:
        return channel.alarm_low

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._device_channel.display_name()} Low Alarm Threshold"

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{format_mac(self._device_serial)}-{self._device_channel.number}-low-alarm-threshold"


# Created in this order, which matters only when generated entity ids collide
DEVICE_SENSORS: list[type[DeviceSensor]] = [
    BatterySensor,
    SignalSensor,
    LastSeenSensor,
    TransmitIntervalSensor,
    FanStateSensor,
    FanSetTemperatureSensor,
]
CHANNEL_SENSORS: list[type[ChannelSensor]] = [
    HumiditySensor,
    TemperatureSensor,
    HighAlarmThresholdSensor,
    LowAlarmThresholdSensor,
]
