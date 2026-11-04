"""Binary sensors for Thermoworks Cloud fan accessories."""

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import (
    DeviceInfo,
    async_get_device_id_by_identifier,
    format_mac,
)
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator
from .entity import ThermoworksFanEntity
from .models import (
    ChannelWithHighAlarm,
    ChannelWithLowAlarm,
    DeviceWithFan,
    ThermoworksChannel,
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
            gateway_registry_id=async_get_device_id_by_identifier(
                hass,
                (DOMAIN, format_mac(device.get_identifier())),
                config_entry_id=config_entry.entry_id,
            ),
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
                        device_identifier=device.get_identifier(),
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
                        device_identifier=device.get_identifier(),
                        device_channel=device_channel,
                    )
                )

    async_add_entities(new_entities)


class FanConnectedSensor(ThermoworksFanEntity, BinarySensorEntity):
    """Implementation of a Thermoworks fan connection sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "fan_connected"

    @property
    def is_on(self) -> bool | None:
        """Return true if the fan accessory is connected."""
        return self._device.fan.connected

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{format_mac(self._device.get_identifier())}-fan-connected"


class AlarmBinarySensor(
    CoordinatorEntity[ThermoworksCoordinator], BinarySensorEntity
):
    """Base class for Thermoworks channel alarm binary sensors."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device_identifier: str,
        device_channel: ThermoworksChannel,
    ) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._device_identifier = device_identifier
        self._device_channel = device_channel

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        device_channel = self.coordinator.get_device_channel_by_id(
            device_id=self._device_identifier, channel_id=self._device_channel.number
        )
        if not device_channel:
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device channel {self._device_channel.display_name()} "
                "is not found"
            )
        self._device_channel = device_channel
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{format_mac(self._device_identifier)}",
                )
            }
        )

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
        return f"{DOMAIN}-{format_mac(self._device_identifier)}-{self._device_channel.number}-high-alarm"


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
        return f"{DOMAIN}-{format_mac(self._device_identifier)}-{self._device_channel.number}-low-alarm"
