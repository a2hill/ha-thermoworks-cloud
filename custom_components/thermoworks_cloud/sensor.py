"""Sensors representing a Thermoworks thermometer."""
from collections.abc import Mapping
import logging

from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import format_mac, DeviceInfo
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

from .const import DOMAIN

from .models import (
    DeviceWithBattery,
    DeviceWithWifi,
    ThermoworksChannel,
    get_missing_attributes,
)

from .coordinator import ThermoworksCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""

    coordinator: ThermoworksCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ].coordinator

    new_entities = []
    for device in coordinator.data.devices:

        # Only create battery sensor if the device has battery capability
        if DeviceWithBattery.is_protocol_compliant(device):
            new_entities.append(
                BatterySensor(
                    entity_id=async_generate_entity_id(
                        ENTITY_ID_FORMAT,
                        f"{device.device_id}_battery",
                        hass=hass,
                    ),
                    coordinator=coordinator,
                    device=device,
                )
            )
        else:
            _LOGGER.debug(
                "Not creating battery sensor for device %s, "
                "missing required attributes: %s", device.display_name(
                ), get_missing_attributes(device, DeviceWithBattery)
            )

        # Only create signal sensor if the device has WiFi capability
        if DeviceWithWifi.is_protocol_compliant(device):
            new_entities.append(
                SignalSensor(
                    entity_id=async_generate_entity_id(
                        ENTITY_ID_FORMAT,
                        f"{device.device_id}_signal",
                        hass=hass,
                    ),
                    coordinator=coordinator,
                    device=device,
                )
            )
        else:
            _LOGGER.debug(
                "Not creating wifi sensor for device %s, "
                "missing required attributes: %s", device.display_name(
                ), get_missing_attributes(device, DeviceWithWifi)
            )

        for device_channel in coordinator.data.device_channels.get(device.device_id, []):
            new_entities.append(
                TemperatureSensor(
                    entity_id=async_generate_entity_id(
                        ENTITY_ID_FORMAT,
                        f"{device.device_id}_ch_{
                            device_channel.number}_temperature",
                        hass=hass,
                    ),
                    coordinator=coordinator,
                    device_serial=device.device_id,
                    device_channel=device_channel,
                )
            )

        if len(new_entities) > 0:
            _LOGGER.debug("New entities created: %d", len(new_entities))
            async_add_entities(new_entities)
        else:
            _LOGGER.debug("No new entities created")


class BatterySensor(CoordinatorEntity[ThermoworksCoordinator], SensorEntity):
    """Implementation of a sensor."""

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
    _attr_device_class = SensorDeviceClass.BATTERY

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
    _attr_state_class = SensorStateClass.MEASUREMENT

    # Naming
    # https://developers.home-assistant.io/docs/core/entity#entity-naming
    # https://developers.home-assistant.io/docs/internationalization/core/#name-of-entities
    _attr_has_entity_name = True
    _attr_translation_key = "battery"

    # API data is in percent with no decimal place
    # https://developers.home-assistant.io/docs/core/entity/sensor#properties
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device: DeviceWithBattery,
    ) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._device = device

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        # This method is called by your DataUpdateCoordinator when a successful update runs.
        device = self.coordinator.get_device_by_id(self._device.device_id)
        if not device:
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device {self._device.display_name()} is not found")
        if not DeviceWithBattery.is_protocol_compliant(device):
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device {self._device.display_name()} is missing required "
                f"attribute(s): {get_missing_attributes(device, DeviceWithBattery)}")
        self._device = device
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Identifiers are what group entities into the same device.
        # If your device is created elsewhere, you can just specify the indentifiers parameter.
        # If your device connects via another device, add via_device parameter with the indentifiers of that device.
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{format_mac(self._device.device_id)}",
                )
            },
            name=self._device.label,
            sw_version=self._device.firmware,
            manufacturer="ThermoWorks",
            model=self._device.device_name,
            serial_number=self._device.serial,
        )

    @property
    def native_value(self) -> int | float:
        """Return the state of the entity."""
        # Using native value and native unit of measurement, allows you to change units
        # in Lovelace and HA will automatically calculate the correct value.
        return float(self._device.battery)

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.  Think carefully what you want this to be as
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{format_mac(self._device.device_id)}"


class TemperatureSensor(CoordinatorEntity[ThermoworksCoordinator], SensorEntity):
    """Implementation of a thermoworks temperature sensor."""

    _device_channel: ThermoworksChannel

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
    _attr_state_class = SensorStateClass.MEASUREMENT

    # Naming
    # https://developers.home-assistant.io/docs/core/entity#entity-naming
    # https://developers.home-assistant.io/docs/internationalization/core/#name-of-entities
    _attr_has_entity_name = True
    _attr_translation_key = "temperature"

    # API data is given at higher precision, but that isn't needed
    # https://developers.home-assistant.io/docs/core/entity/sensor#properties
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device_serial: str,
        device_channel: ThermoworksChannel,
    ) -> None:
        """Initialize the sensor."""

        super().__init__(coordinator)
        self.entity_id = entity_id
        self._device_channel = device_channel
        self._device_serial = device_serial

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        # This method is called by your DataUpdateCoordinator when a successful update runs.
        device_channel = self.coordinator.get_device_channel_by_id(
            device_id=self._device_serial, channel_id=self._device_channel.number
        )
        if not device_channel:
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device channel {self._device_channel.display_name()} "
                "is not found")
        self._device_channel = device_channel
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Identifiers are what group entities into the same device.
        # If your device is created elsewhere, you can just specify the indentifiers parameter.
        # If your device connects via another device, add via_device parameter with the indentifiers of that device.
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{format_mac(self._device_serial)}",
                )
            }
        )

    @property
    def translation_placeholders(self) -> Mapping[str, str]:
        """Placeholder values for string internationalization."""
        return {"channel_name": self._device_channel.display_name()}

    @property
    def native_value(self) -> int | float:
        """Return the state of the entity."""
        # Using native value and native unit of measurement, allows you to change units
        # in Lovelace and HA will automatically calculate the correct value.
        return float(self._device_channel.value)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of temperature."""
        if self._device_channel.units is None:
            return None
        if self._device_channel.units == "F":
            return UnitOfTemperature.FAHRENHEIT
        if self._device_channel.units == "C":
            return UnitOfTemperature.CELSIUS

        raise ValueError(
            f"Unable to determine unit of measurement from unit string '{
                self._device_channel.units}'"
        )

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.  Think carefully what you want this to be as
        # changing it later will cause HA to create new entities.
        return (
            f"{DOMAIN}-{format_mac(self._device_serial)
                        }-{self._device_channel.number}"
        )


class SignalSensor(CoordinatorEntity[ThermoworksCoordinator], SensorEntity):
    """Implementation of a sensor."""

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH

    # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
    _attr_state_class = SensorStateClass.MEASUREMENT

    # Naming
    # https://developers.home-assistant.io/docs/core/entity#entity-naming
    # https://developers.home-assistant.io/docs/internationalization/core/#name-of-entities
    _attr_has_entity_name = True
    _attr_translation_key = "signal"

    # API data is in negative decibels with no decimal place
    # https://developers.home-assistant.io/docs/core/entity/sensor#properties
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device: DeviceWithWifi,
    ) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._device = device

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        # This method is called by your DataUpdateCoordinator when a successful update runs.
        device = self.coordinator.get_device_by_id(self._device.device_id)
        if not device:
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device {self._device.display_name()} is not found")
        if not DeviceWithWifi.is_protocol_compliant(device):
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device {self._device.display_name()} is missing required "
                f"attribute(s): {get_missing_attributes(device, DeviceWithWifi)}")
        self._device = device
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Identifiers are what group entities into the same device.
        # If your device is created elsewhere, you can just specify the indentifiers parameter.
        # If your device connects via another device, add via_device parameter with the indentifiers of that device.
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{format_mac(self._device.device_id)}",
                )
            }
        )

    @property
    def native_value(self) -> int | float:
        """Return the state of the entity."""
        # Using native value and native unit of measurement, allows you to change units
        # in Lovelace and HA will automatically calculate the correct value.
        return float(self._device.wifi_strength)

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.  Think carefully what you want this to be as
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{format_mac(self._device.device_id)}-signal"
