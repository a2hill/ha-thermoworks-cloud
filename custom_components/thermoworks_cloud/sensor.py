"""Sensors representing a Thermoworks thermometer.

Each sensor's `parse` method builds a view of everything it shows from a device or channel,
and the base classes in `entity.py` handle identity, updates and availability the same way
for all of them.
"""
from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from thermoworks_cloud.models import Alarm

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator
from .entity import (
    ChannelView,
    ThermoworksChannelEntity,
    ThermoworksDeviceEntity,
    ThermoworksFanEntity,
    View,
)
from .models import ThermoworksChannel, ThermoworksDevice, ThermoworksFan

_LOGGER: logging.Logger = logging.getLogger(__package__)

# Units the API reports, mapped to Home Assistant units. All unit conversion goes
# through this map; unknown units map to None.
API_UNITS: dict[str, str] = {
    "F": UnitOfTemperature.FAHRENHEIT,
    "C": UnitOfTemperature.CELSIUS,
    "H": PERCENTAGE,
}
TEMPERATURE_UNITS = (UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS)


def _ha_unit(api_unit: str | None) -> str | None:
    """Return the Home Assistant unit for an API unit, or None if it isn't known."""
    return API_UNITS.get(api_unit)


def _channel_attributes(channel: ThermoworksChannel) -> dict[str, Any]:
    """Return the channel metadata shown on its measurement sensors."""
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
        # The sensor lists are at the end of the file, after their classes
        for device_sensor in DEVICE_SENSORS:
            if not device_sensor.supported(device):
                _LOGGER.debug("Not creating %s sensor for device %s",
                              device_sensor.entity_suffix, device.display_name())
                continue
            new_entities.append(device_sensor.build(hass, coordinator, device))

        if device.fan is not None:
            new_entities.extend(
                fan_sensor.build(hass, coordinator, device) for fan_sensor in FAN_SENSORS
            )

        for device_channel in device.channels.values():
            if _ha_unit(device_channel.units) is None:
                _LOGGER.warning(
                    "Unsupported sensor unit '%s' for device %s channel %s - skipping",
                    device_channel.units,
                    device.display_name(),
                    device_channel.display_name()
                )

            for channel_sensor in CHANNEL_SENSORS:
                if not channel_sensor.supported(device_channel):
                    _LOGGER.debug("Not creating %s sensor for device %s channel %s",
                                  channel_sensor.entity_suffix, device.display_name(),
                                  device_channel.display_name())
                    continue
                new_entities.append(
                    channel_sensor.build(hass, coordinator, device, device_channel)
                )


    if len(new_entities) > 0:
        _LOGGER.debug("New entities to create: %d", len(new_entities))
        async_add_entities(new_entities)
    else:
        _LOGGER.debug("No new entities created")


class DeviceSensor[R](ThermoworksDeviceEntity[R], SensorEntity):
    """Base class for sensors on the device itself."""

    entity_id_format = ENTITY_ID_FORMAT

    _attr_has_entity_name = True


@dataclass(frozen=True)
class BatteryState:
    """Battery level, and whether it's charging."""

    level: float
    charging: bool


class BatterySensor(DeviceSensor[BatteryState]):
    """Battery level of the device, with a charging icon while it charges."""

    entity_suffix = "battery"
    unique_id_suffix = None

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
    def parse(cls, device: ThermoworksDevice) -> View[BatteryState]:
        if device.battery is None:
            return View(entity_state=None)
        return View(entity_state=BatteryState(
            level=float(device.battery), charging=device.battery_state == "charging"
        ))

    @property
    def icon(self) -> str | None:
        """Return the icon to use in the frontend, if any."""
        # Only handle charging, as HA doesn't natively support a charging icon.
        # The icon is read even while unavailable, so it can't assume an entity state.
        state = self._view.entity_state
        return "mdi:battery-charging-100" if state and state.charging else None

    @property
    def native_value(self) -> float:
        """Return the battery level."""
        return self._entity_state.level


class SignalSensor(DeviceSensor[float]):
    """Signal strength of the device's connection, in dBm."""

    entity_suffix = "signal"
    unique_id_suffix = "signal"

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
    def parse(cls, device: ThermoworksDevice) -> View[float]:
        signal = device.signal_strength
        return View(entity_state=float(signal) if signal is not None else None)

    @property
    def native_value(self) -> float:
        """Return the signal strength."""
        return self._entity_state


class LastSeenSensor(DeviceSensor[datetime]):
    """When the device last contacted ThermoWorks Cloud."""

    entity_suffix = "last_seen"
    unique_id_suffix = "last-seen"

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_seen"

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> View[datetime]:
        # Already parsed into UTC by the device model
        return View(entity_state=device.last_seen)

    @property
    def native_value(self) -> datetime:
        """Return when the device was last seen."""
        return self._entity_state


class TransmitIntervalSensor(DeviceSensor[int]):
    """How often the device sends readings, in seconds."""

    entity_suffix = "transmit_interval"
    unique_id_suffix = "transmit-interval"

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_translation_key = "transmit_interval"

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> View[int]:
        return View(entity_state=device.transmit_interval_in_seconds)

    @property
    def native_value(self) -> int:
        """Return the transmit interval."""
        return self._entity_state


class FanSensor[R](ThermoworksFanEntity[R], SensorEntity):
    """Base class for Thermoworks fan accessory sensors.

    Created for every fan, but only available while it's connected, since a disconnected
    fan still reports its last state and set temperature, which aren't current.
    """

    entity_id_format = ENTITY_ID_FORMAT

    _attr_has_entity_name = True

    @classmethod
    def supported(cls, fan: ThermoworksFan) -> bool:
        return True


@dataclass(frozen=True)
class FanStatus:
    """What a connected fan is doing. None if it doesn't say, shown as unknown."""

    state_name: str | None


class FanStateSensor(FanSensor[FanStatus]):
    """What the fan is doing: paused, blowing or pulsing."""

    entity_suffix = "state"
    unique_id_suffix = "state"

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["Paused", "Blowing", "Pulsing"]
    _attr_translation_key = "fan_state"

    @classmethod
    def parse(cls, fan: ThermoworksFan) -> View[FanStatus]:
        if fan.connected is not True:
            return View(entity_state=None)
        return View(entity_state=FanStatus(fan.state_name))

    @property
    def native_value(self) -> str | None:
        """Return the fan state name."""
        return self._entity_state.state_name


@dataclass(frozen=True)
class FanSetpoint:
    """A connected fan's set temperature, None if it doesn't say, and the channel it follows."""

    temperature: int | None
    fan_channel: str | None


@dataclass(frozen=True)
class FanSetTemperatureView(View[FanSetpoint]):
    """The fan's setpoint, and the temperature unit the device displays."""

    unit: str | None


class FanSetTemperatureSensor(FanSensor[FanSetpoint]):
    """The temperature the fan is set to hold."""

    entity_suffix = "set_temperature"
    unique_id_suffix = "set-temperature"

    _view: FanSetTemperatureView

    _attr_suggested_display_precision = 0
    _attr_translation_key = "fan_set_temperature"

    @classmethod
    def parse(cls, fan: ThermoworksFan) -> FanSetTemperatureView:
        unit = _ha_unit(fan.display_units)
        return FanSetTemperatureView(
            entity_state=(
                FanSetpoint(fan.set_temp, fan.fan_channel) if fan.connected is True else None
            ),
            # A number without a known temperature unit is shown as a plain number
            unit=unit if unit in TEMPERATURE_UNITS else None,
        )

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class when the API reports a temperature unit."""
        return SensorDeviceClass.TEMPERATURE if self._view.unit is not None else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of temperature."""
        return self._view.unit

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the channel the fan follows."""
        if self._entity_state.fan_channel is None:
            return {}

        return {"channel": self._entity_state.fan_channel}

    @property
    def native_value(self) -> int | None:
        """Return the fan set temperature."""
        return self._entity_state.temperature


class ChannelSensor[R](ThermoworksChannelEntity[R], SensorEntity):
    """Base class for thermoworks channel sensors."""

    entity_id_format = ENTITY_ID_FORMAT

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    # API data is given at higher precision, but that isn't needed
    # https://developers.home-assistant.io/docs/core/entity/sensor#properties
    _attr_suggested_display_precision = 1

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        # This is the name that will be shown in the Entity UI.
        # It is the name of the channel, not the device.
        return self._view.name.capitalize()

    @property
    def translation_placeholders(self) -> Mapping[str, str]:
        """Placeholder values for string internationalization."""
        return {"channel_name": self._view.name}


@dataclass(frozen=True)
class Measurement:
    """A channel's valid reading, and the channel metadata shown alongside it."""

    value: float
    attributes: dict[str, Any]


@dataclass(frozen=True)
class MeasurementView(ChannelView[Measurement]):
    """A channel's measurement, and the unit it's in."""

    unit: str | None


class MeasurementSensor(ChannelSensor[Measurement]):
    """Base class for sensors showing a channel's reading.

    Created from the channel's units, even before it has a reading, so a probe that
    isn't plugged in yet still gets its entity. It's available only with a valid reading.
    """

    # The reading's unit. Must be one of these for the sensor to be created.
    supported_units: tuple[str, ...]

    unique_id_suffix = None

    _view: MeasurementView

    # Changes on device contact without a new measurement, which would bloat the recorder
    _unrecorded_attributes = frozenset({"last_seen"})

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> MeasurementView:
        unit = _ha_unit(channel.units)
        supported = unit in cls.supported_units
        measurement = None
        if supported and channel.reading is not None:
            measurement = Measurement(
                value=channel.reading,
                # Source metadata, kept separate from Home Assistant's state update time
                attributes=_channel_attributes(channel),
            )
        return MeasurementView(
            entity_state=measurement,
            name=channel.display_name(),
            unit=unit if supported else None,
        )

    @classmethod
    def supported(cls, channel: ThermoworksChannel) -> bool:
        return _ha_unit(channel.units) in cls.supported_units

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the reading's unit."""
        return self._view.unit

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the channel metadata."""
        return self._entity_state.attributes

    @property
    def native_value(self) -> float:
        """Return the reading."""
        return self._entity_state.value


class TemperatureSensor(MeasurementSensor):
    """Temperature reading from a channel's probe."""

    entity_suffix = "temperature"
    supported_units = TEMPERATURE_UNITS

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    # Naming
    # https://developers.home-assistant.io/docs/core/entity#entity-naming
    # https://developers.home-assistant.io/docs/internationalization/core/#name-of-entities
    _attr_translation_key = "temperature"


class HumiditySensor(MeasurementSensor):
    """Humidity reading from a channel's sensor."""

    entity_suffix = "humidity"
    supported_units = (PERCENTAGE,)

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
    _attr_device_class = SensorDeviceClass.HUMIDITY

    # Naming
    # https://developers.home-assistant.io/docs/core/entity#entity-naming
    # https://developers.home-assistant.io/docs/internationalization/core/#name-of-entities
    _attr_translation_key = "humidity"


@dataclass(frozen=True)
class AlarmThreshold:
    """An alarm's configured threshold, None if it isn't set, and whether it's on and going off."""

    value: float | None
    enabled: bool | None
    alarming: bool | None


@dataclass(frozen=True)
class AlarmThresholdView(ChannelView[AlarmThreshold]):
    """An alarm's threshold, and the unit it's in."""

    unit: str | None


class AlarmThresholdSensor(ChannelSensor[AlarmThreshold]):
    """Base class for Thermoworks channel alarm threshold sensors.

    Created when the channel has the alarm. The threshold is a setting, not a measurement,
    so it doesn't depend on the reading.
    """

    _view: AlarmThresholdView

    _attr_suggested_display_precision = 0

    @classmethod
    @abstractmethod
    def _alarm(cls, channel: ThermoworksChannel) -> Alarm | None:
        """Return the alarm this sensor shows."""

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> AlarmThresholdView:
        alarm = cls._alarm(channel)
        if alarm is None:
            return AlarmThresholdView(entity_state=None, name=channel.display_name(), unit=None)
        return AlarmThresholdView(
            entity_state=AlarmThreshold(alarm.value, alarm.enabled, alarm.alarming),
            name=channel.display_name(),
            unit=_ha_unit(alarm.units),
        )

    @classmethod
    def supported(cls, channel: ThermoworksChannel) -> bool:
        return cls._alarm(channel) is not None

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the alarm threshold device class."""
        if self._view.unit in TEMPERATURE_UNITS:
            return SensorDeviceClass.TEMPERATURE
        if self._view.unit == PERCENTAGE:
            return SensorDeviceClass.HUMIDITY

        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return alarm threshold unit."""
        return self._view.unit

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        """Return alarm metadata."""
        return {
            "enabled": self._entity_state.enabled,
            "alarming": self._entity_state.alarming,
        }

    @property
    def native_value(self) -> float | None:
        """Return the configured alarm threshold."""
        return self._entity_state.value


class HighAlarmThresholdSensor(AlarmThresholdSensor):
    """The channel's high alarm threshold."""

    entity_suffix = "high_alarm_threshold"
    unique_id_suffix = "high-alarm-threshold"

    _attr_translation_key = "high_alarm_threshold"

    @classmethod
    def _alarm(cls, channel: ThermoworksChannel) -> Alarm | None:
        return channel.alarm_high

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._view.name} High Alarm Threshold"


class LowAlarmThresholdSensor(AlarmThresholdSensor):
    """The channel's low alarm threshold."""

    entity_suffix = "low_alarm_threshold"
    unique_id_suffix = "low-alarm-threshold"

    _attr_translation_key = "low_alarm_threshold"

    @classmethod
    def _alarm(cls, channel: ThermoworksChannel) -> Alarm | None:
        return channel.alarm_low

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._view.name} Low Alarm Threshold"


DEVICE_SENSORS: list[type[DeviceSensor]] = [
    BatterySensor,
    SignalSensor,
    LastSeenSensor,
    TransmitIntervalSensor,
]
FAN_SENSORS: list[type[FanSensor]] = [
    FanStateSensor,
    FanSetTemperatureSensor,
]
CHANNEL_SENSORS: list[type[ChannelSensor]] = [
    HumiditySensor,
    TemperatureSensor,
    HighAlarmThresholdSensor,
    LowAlarmThresholdSensor,
]
