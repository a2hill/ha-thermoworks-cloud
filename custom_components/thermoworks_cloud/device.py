"""Device descriptions and registration for ThermoWorks Cloud."""

from collections.abc import Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import (
    DeviceEntryType,
    DeviceInfo,
    format_mac,
)

from .const import DOMAIN
from .models import DeviceWithBattery, DeviceWithFan, ThermoworksDevice


def device_reference(device_identifier: str) -> DeviceInfo:
    """Identify an existing thermometer device without supplying metadata."""
    return DeviceInfo(identifiers={(DOMAIN, format_mac(device_identifier))})


def entity_device_info(info: DeviceInfo) -> DeviceInfo:
    """Associate an entity with a centrally managed device without repeating metadata."""
    return DeviceInfo(identifiers=info["identifiers"])


def thermometer_device_info(device: ThermoworksDevice) -> DeviceInfo:
    """Describe a thermometer using the metadata previously supplied by battery entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, format_mac(device.get_identifier()))},
        name=device.label,
        sw_version=device.firmware,
        manufacturer="ThermoWorks",
        model=device.device_name,
        serial_number=device.serial,
    )


def fan_device_info(device: DeviceWithFan) -> DeviceInfo:
    """Describe the separate fan accessory and its connection to the thermometer."""
    identifier = format_mac(device.get_identifier())
    return DeviceInfo(
        identifiers={(DOMAIN, f"{identifier}-fan")},
        name=f"{device.label or device.display_name()} Fan",
        manufacturer="ThermoWorks",
        via_device=(DOMAIN, identifier),
    )


def account_device_info(config_entry: ConfigEntry) -> DeviceInfo:
    """Describe the account-wide service device used by the scan interval control."""
    return DeviceInfo(
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=config_entry.title,
        entry_type=DeviceEntryType.SERVICE,
    )


@callback
def async_register_devices(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    devices: Iterable[ThermoworksDevice],
) -> None:
    """Create or update device metadata before entities consume refreshed data."""
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, **account_device_info(config_entry)
    )
    for device in devices:
        # Only battery entities supplied thermometer metadata before this
        # refactor. Keep identifier-only registration for the other devices.
        info = (
            thermometer_device_info(device)
            if DeviceWithBattery.is_protocol_compliant(device)
            else device_reference(device.get_identifier())
        )
        if "name" in info and not info["name"]:
            # Match HA's initial fallback without clearing it on later refreshes.
            info["name"] = config_entry.title
        # Missing optional cloud metadata should not erase known registry values.
        registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            **{key: value for key, value in info.items() if value is not None},
        )
        if DeviceWithFan.is_protocol_compliant(device):
            registry.async_get_or_create(
                config_entry_id=config_entry.entry_id, **fan_device_info(device)
            )
