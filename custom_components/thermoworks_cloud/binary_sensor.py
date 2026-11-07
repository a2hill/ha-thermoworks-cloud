"""Binary sensors for Thermoworks Cloud fan accessories and channel alarms."""

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo, format_mac
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from thermoworks_cloud.models import Alarm, Fan

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator
from .entity import ThermoworksChannelEntity, ThermoworksDeviceEntity
from .models import ThermoworksChannel, ThermoworksDevice


class FanConnectedSensor(ThermoworksDeviceEntity[Fan], BinarySensorEntity):
    """Implementation of a Thermoworks fan connection sensor.

    Unlike the fan sensors, this stays available while the fan is disconnected, since
    showing that is its job.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_translation_key = "fan_connected"

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> Fan | None:
        return device.fan

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

    @property
    def is_on(self) -> bool | None:
        """Return true if the fan accessory is connected."""
        return self._value.connected if self._value is not None else None

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{format_mac(self._device.get_identifier())}-fan-connected"


class AlarmBinarySensor(ThermoworksChannelEntity[Alarm], BinarySensorEntity):
    """Base class for Thermoworks channel alarm binary sensors.

    Created when the channel has the alarm, but only available while the channel has a
    valid reading. Without one, the alarm's state is an old evaluation, not a current one.
    """

    # Used in the entity id: {device identifier}_ch_{channel number}_{entity_suffix}
    entity_suffix: str

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True

    @classmethod
    def _alarm(cls, channel: ThermoworksChannel) -> Alarm | None:
        """Return the alarm this sensor shows."""
        raise NotImplementedError

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> Alarm | None:
        return cls._alarm(channel) if channel.reading is not None else None

    @classmethod
    def supported(cls, channel: ThermoworksChannel) -> bool:
        return cls._alarm(channel) is not None

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
    def extra_state_attributes(self) -> dict[str, bool | int | str | None]:
        """Return alarm metadata."""
        return {
            "enabled": self._value.enabled if self._value else None,
            "value": self._value.value if self._value else None,
            "units": self._value.units if self._value else None,
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if the alarm is active."""
        if self._value is None:
            return None
        return self._value.enabled is True and self._value.alarming is True


class HighAlarmBinarySensor(AlarmBinarySensor):
    """Implementation of a Thermoworks channel high alarm binary sensor."""

    entity_suffix = "high_alarm"

    _attr_translation_key = "high_alarm"

    @classmethod
    def _alarm(cls, channel: ThermoworksChannel) -> Alarm | None:
        """Return high alarm data."""
        return channel.alarm_high

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._device_channel.display_name()} High Alarm"

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{format_mac(self._device_serial)}-{self._device_channel.number}-high-alarm"


class LowAlarmBinarySensor(AlarmBinarySensor):
    """Implementation of a Thermoworks channel low alarm binary sensor."""

    entity_suffix = "low_alarm"

    _attr_translation_key = "low_alarm"

    @classmethod
    def _alarm(cls, channel: ThermoworksChannel) -> Alarm | None:
        """Return low alarm data."""
        return channel.alarm_low

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._device_channel.display_name()} Low Alarm"

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{format_mac(self._device_serial)}-{self._device_channel.number}-low-alarm"


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
            new_entities.append(
                FanConnectedSensor(
                    entity_id=async_generate_entity_id(
                        ENTITY_ID_FORMAT, f"{identifier}_fan_connected", hass=hass
                    ),
                    coordinator=coordinator,
                    device=device,
                )
            )

        for device_channel in device.channels.values():
            for alarm_sensor in (HighAlarmBinarySensor, LowAlarmBinarySensor):
                if not alarm_sensor.supported(device_channel):
                    continue
                new_entities.append(
                    alarm_sensor(
                        entity_id=async_generate_entity_id(
                            ENTITY_ID_FORMAT,
                            f"{identifier}_ch_{device_channel.number}_{alarm_sensor.entity_suffix}",
                            hass=hass,
                        ),
                        coordinator=coordinator,
                        device_serial=identifier,
                        device_channel=device_channel,
                    )
                )

    async_add_entities(new_entities)
