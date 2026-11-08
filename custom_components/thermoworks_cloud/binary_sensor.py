"""Binary sensors for Thermoworks Cloud fan accessories and channel alarms."""

from abc import abstractmethod
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator
from .entity import ChannelView, ThermoworksChannelEntity, ThermoworksFanEntity, View
from .models import ThermoworksAlarm, ThermoworksChannel, ThermoworksFan, Unit


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add binary sensors for passed config_entry in HA."""
    coordinator: ThermoworksCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ].coordinator

    new_entities: list[BinarySensorEntity] = []
    for device in coordinator.data.devices.values():
        # BINARY_SENSORS is at the end of the file, after the classes it lists
        for binary_sensor in BINARY_SENSORS:
            for source in binary_sensor.sources(device):
                entity = binary_sensor.build(hass, coordinator, device, source)
                if entity is not None:
                    new_entities.append(entity)

    async_add_entities(new_entities)


@dataclass(frozen=True)
class FanConnection:
    """Whether the fan is connected. None if it doesn't say, shown as unknown."""

    connected: bool | None


class FanConnectedSensor(ThermoworksFanEntity[FanConnection], BinarySensorEntity):
    """Whether the fan accessory is connected.

    Unlike the fan sensors, this stays available while the fan is disconnected, since
    showing that is its job.
    """

    entity_id_format = ENTITY_ID_FORMAT
    suffix = "connected"

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_translation_key = "fan_connected"

    @classmethod
    def parse(cls, fan: ThermoworksFan) -> View[FanConnection]:
        return View(entity_state=FanConnection(fan.connected))

    @property
    def is_on(self) -> bool | None:
        """Return true if the fan accessory is connected."""
        return self._entity_state.connected


@dataclass(frozen=True)
class AlarmState:
    """Whether an alarm is going off, plus its configuration."""

    active: bool
    enabled: bool | None
    value: float | None
    units: Unit | None


class AlarmBinarySensor(ThermoworksChannelEntity[AlarmState], BinarySensorEntity):
    """Base class for Thermoworks channel alarm binary sensors.

    Created when the channel has the alarm, but only available while the channel has a
    valid reading. Without one, the alarm's state is an old evaluation, not a current one.
    """

    entity_id_format = ENTITY_ID_FORMAT

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True

    @classmethod
    @abstractmethod
    def _alarm(cls, channel: ThermoworksChannel) -> ThermoworksAlarm | None:
        """Return the alarm this sensor shows."""

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> ChannelView[AlarmState] | None:
        alarm = cls._alarm(channel)
        if alarm is None:
            return None
        if channel.reading is None:
            return ChannelView(entity_state=None, name=channel.display_name())
        return ChannelView(
            entity_state=AlarmState(
                active=alarm.enabled is True and alarm.alarming is True,
                enabled=alarm.enabled,
                value=alarm.value,
                units=alarm.units,
            ),
            name=channel.display_name(),
        )

    @property
    def extra_state_attributes(self) -> dict[str, bool | float | str | None]:
        """Return alarm metadata."""
        return {
            "enabled": self._entity_state.enabled,
            "value": self._entity_state.value,
            "units": self._entity_state.units,
        }

    @property
    def is_on(self) -> bool:
        """Return true if the alarm is active."""
        return self._entity_state.active


class HighAlarmBinarySensor(AlarmBinarySensor):
    """Whether the channel's high alarm is going off."""

    suffix = "high-alarm"

    _attr_translation_key = "high_alarm"

    @classmethod
    def _alarm(cls, channel: ThermoworksChannel) -> ThermoworksAlarm | None:
        return channel.alarm_high

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._view.name} High Alarm"


class LowAlarmBinarySensor(AlarmBinarySensor):
    """Whether the channel's low alarm is going off."""

    suffix = "low-alarm"

    _attr_translation_key = "low_alarm"

    @classmethod
    def _alarm(cls, channel: ThermoworksChannel) -> ThermoworksAlarm | None:
        return channel.alarm_low

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._view.name} Low Alarm"


# Every binary sensor type. Each is created for the sources on a device that have it.
BINARY_SENSORS: list[type[FanConnectedSensor | AlarmBinarySensor]] = [
    FanConnectedSensor,
    HighAlarmBinarySensor,
    LowAlarmBinarySensor,
]
