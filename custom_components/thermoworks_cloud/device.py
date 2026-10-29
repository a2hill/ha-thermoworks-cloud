"""Device identity, metadata, and registration for ThermoWorks Cloud.

Metadata describes devices registered centrally. Entities use the same device
identifiers to associate themselves with those registry records.
"""

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
from .models import DeviceWithFan, ThermoworksDevice


def device_identifier(identifier: str, *, fan: bool = False) -> str:
    """Format the cloud identifier, adding the accessory suffix for a fan device."""
    identifier = format_mac(identifier)
    return f"{identifier}-fan" if fan else identifier


def device_metadata(device: ThermoworksDevice) -> DeviceInfo:
    """Describe a ThermoWorks device using its identity and cloud metadata."""
    return DeviceInfo(
        identifiers={(DOMAIN, device_identifier(device.get_identifier()))},
        name=device.label,
        sw_version=device.firmware,
        manufacturer="ThermoWorks",
        model=device.device_name,
        serial_number=device.serial,
    )


def fan_metadata(device: DeviceWithFan) -> DeviceInfo:
    """Describe the separate fan accessory and its connection to the parent device."""
    return DeviceInfo(
        identifiers={(DOMAIN, device_identifier(device.get_identifier(), fan=True))},
        name=f"{device.label or device.display_name()} Fan",
        manufacturer="ThermoWorks",
        via_device=(DOMAIN, device_identifier(device.get_identifier())),
    )


def account_metadata(config_entry: ConfigEntry) -> DeviceInfo:
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
        config_entry_id=config_entry.entry_id, **account_metadata(config_entry)
    )
    for device in devices:
        info = device_metadata(device)
        if not info["name"]:
            # Use the account name when the cloud supplies no label.
            info["name"] = config_entry.title
        # Missing optional cloud metadata should not erase known registry values.
        registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            **{key: value for key, value in info.items() if value is not None},
        )
        if DeviceWithFan.is_protocol_compliant(device):
            registry.async_get_or_create(
                config_entry_id=config_entry.entry_id, **fan_metadata(device)
            )
