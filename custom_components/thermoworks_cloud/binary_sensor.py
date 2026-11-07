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
from homeassistant.helpers.device_registry import DeviceInfo, format_mac
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from thermoworks_cloud.models import Alarm

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator
from .entity import ChannelView, ThermoworksChannelEntity, ThermoworksDeviceEntity, View
from .models import ThermoworksChannel, ThermoworksDevice


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
        identifier = device.get_identifier()

        if FanConnectedSensor.supported(device):
            new_entities.append(FanConnectedSensor.build(hass, coordinator, device))

        for device_channel in device.channels.values():
            for alarm_sensor in (HighAlarmBinarySensor, LowAlarmBinarySensor):
                if alarm_sensor.supported(device_channel):
                    new_entities.append(
                        alarm_sensor.build(hass, coordinator, identifier, device_channel)
                    )

    async_add_entities(new_entities)


@dataclass(frozen=True)
class FanConnection:
    """Whether the fan is connected. None if it doesn't say, shown as unknown."""

    connected: bool | None


class FanConnectedSensor(ThermoworksDeviceEntity[FanConnection], BinarySensorEntity):
    """Whether the fan accessory is connected.

    Unlike the fan sensors, this stays available while the fan is disconnected, since
    showing that is its job.
    """

    entity_id_format = ENTITY_ID_FORMAT
    entity_suffix = "fan_connected"
    unique_id_suffix = "fan-connected"

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_translation_key = "fan_connected"

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> View[FanConnection]:
        fan = device.fan
        return View(entity_state=FanConnection(fan.connected) if fan is not None else None)

    @property
    def device_info(self) -> DeviceInfo:
        """Attach the entity to the fan's own device, registered by `devices.py`."""
        return DeviceInfo(identifiers={(DOMAIN, f"{format_mac(self._device_identifier)}-fan")})

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
    units: str | None


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
    def _alarm(cls, channel: ThermoworksChannel) -> Alarm | None:
        """Return the alarm this sensor shows."""

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> ChannelView[AlarmState]:
        alarm = cls._alarm(channel)
        if alarm is None or channel.reading is None:
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

    @classmethod
    def supported(cls, channel: ThermoworksChannel) -> bool:
        return cls._alarm(channel) is not None

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

    entity_suffix = "high_alarm"
    unique_id_suffix = "high-alarm"

    _attr_translation_key = "high_alarm"

    @classmethod
    def _alarm(cls, channel: ThermoworksChannel) -> Alarm | None:
        return channel.alarm_high

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._view.name} High Alarm"


class LowAlarmBinarySensor(AlarmBinarySensor):
    """Whether the channel's low alarm is going off."""

    entity_suffix = "low_alarm"
    unique_id_suffix = "low-alarm"

    _attr_translation_key = "low_alarm"

    @classmethod
    def _alarm(cls, channel: ThermoworksChannel) -> Alarm | None:
        return channel.alarm_low

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._view.name} Low Alarm"
