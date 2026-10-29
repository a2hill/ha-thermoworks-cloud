"""Binary sensor entities for ThermoWorks Cloud."""

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN
from .device import get_identifier_for_device
from .entity import ThermoworksEntity
from .coordinator import ThermoworksCoordinator
from .models import (
    ChannelWithHighAlarm,
    ChannelWithLowAlarm,
    DeviceWithFan,
    ThermoworksChannel,
    ThermoworksDevice,
    get_missing_attributes,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add binary sensors for passed config_entry in HA."""
    coordinator: ThermoworksCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ].coordinator

    new_entities = [
        FanConnectedSensor(
            entity_id=async_generate_entity_id(
                ENTITY_ID_FORMAT,
                f"{device.get_identifier()}_fan_connected",
                hass=hass,
            ),
            coordinator=coordinator,
            device=device,
        )
        for device in coordinator.data.devices
        if DeviceWithFan.is_protocol_compliant(device)
    ]

    for device in coordinator.data.devices:
        for device_channel in coordinator.data.device_channels.get(
            device.get_identifier(), []
        ):
            if ChannelWithHighAlarm.is_protocol_compliant(device_channel):
                new_entities.append(
                    HighAlarmBinarySensor(
                        entity_id=async_generate_entity_id(
                            ENTITY_ID_FORMAT,
                            f"{device.get_identifier()}_ch_{device_channel.number}_high_alarm",
                            hass=hass,
                        ),
                        coordinator=coordinator,
                        device=device,
                        device_channel=device_channel,
                    )
                )

            if ChannelWithLowAlarm.is_protocol_compliant(device_channel):
                new_entities.append(
                    LowAlarmBinarySensor(
                        entity_id=async_generate_entity_id(
                            ENTITY_ID_FORMAT,
                            f"{device.get_identifier()}_ch_{device_channel.number}_low_alarm",
                            hass=hass,
                        ),
                        coordinator=coordinator,
                        device=device,
                        device_channel=device_channel,
                    )
                )

    async_add_entities(new_entities)


class FanConnectedSensor(ThermoworksEntity, BinarySensorEntity):
    """Implementation of a Thermoworks fan connection sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "fan_connected"

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device: DeviceWithFan,
    ) -> None:
        """Initialise sensor."""
        super().__init__(
            entity_id,
            coordinator,
            identifier=f"{get_identifier_for_device(device)}-fan",
        )
        self._device = device

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        device = self.coordinator.get_device_by_id(self._device.get_identifier())
        if not device:
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device {self._device.display_name()} is not found"
            )
        if not DeviceWithFan.is_protocol_compliant(device):
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device {self._device.display_name()} is missing required "
                f"attribute(s): {get_missing_attributes(device, DeviceWithFan)}"
            )
        self._device = device
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return true if the fan accessory is connected."""
        return self._device.fan.connected

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{get_identifier_for_device(self._device)}-fan-connected"


class AlarmBinarySensor(ThermoworksEntity, BinarySensorEntity):
    """Base class for Thermoworks channel alarm binary sensors."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device: ThermoworksDevice,
        device_channel: ThermoworksChannel,
    ) -> None:
        """Initialise sensor."""
        super().__init__(
            entity_id,
            coordinator,
            identifier=get_identifier_for_device(device),
        )
        self._device = device
        self._device_channel = device_channel

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        device_channel = self.coordinator.get_device_channel_by_id(
            device_id=self._device.get_identifier(), channel_id=self._device_channel.number
        )
        if not device_channel:
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device channel {self._device_channel.display_name()} "
                "is not found"
            )
        self._device_channel = device_channel
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, bool | int | str | None]:
        """Return alarm metadata."""
        return {
            "enabled": self._alarm.enabled if self._alarm else None,
            "value": self._alarm.value if self._alarm else None,
            "units": self._alarm.units if self._alarm else None,
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if the alarm is active."""
        if self._alarm is None:
            return None
        return self._alarm.enabled is True and self._alarm.alarming is True


class HighAlarmBinarySensor(AlarmBinarySensor):
    """Implementation of a Thermoworks channel high alarm binary sensor."""

    _attr_translation_key = "high_alarm"

    @property
    def _alarm(self):
        """Return high alarm data."""
        return self._device_channel.alarm_high

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._device_channel.display_name()} High Alarm"

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{get_identifier_for_device(self._device)}-{self._device_channel.number}-high-alarm"


class LowAlarmBinarySensor(AlarmBinarySensor):
    """Implementation of a Thermoworks channel low alarm binary sensor."""

    _attr_translation_key = "low_alarm"

    @property
    def _alarm(self):
        """Return low alarm data."""
        return self._device_channel.alarm_low

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._device_channel.display_name()} Low Alarm"

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{get_identifier_for_device(self._device)}-{self._device_channel.number}-low-alarm"
