"""Registers each ThermoWorks device, and each fan accessory, in Home Assistant's device registry.

Devices are registered here explicitly rather than through entities' `device_info`, so that:

- every device gets its details (name, model, firmware), whichever entities it has
- the details stay current: this runs after every successful refresh, so a firmware update
  or a rename in the ThermoWorks app shows up without a reload

Each device is registered under its parsed model's `registry_identifier`, and entities attach
by that same identifier (see `entity.py`), so neither side builds identifiers itself. A name
the user sets in Home Assistant is stored separately (`name_by_user`), so updating `name`
here never overwrites it.
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator

MANUFACTURER = "ThermoWorks"


@callback
def async_register_devices(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: ThermoworksCoordinator
) -> None:
    """Create or update the registry entry for every device and fan in the latest data."""
    # A failed refresh keeps the previous data, which was already registered
    if not coordinator.last_update_success:
        return

    registry = dr.async_get(hass)
    # async_get_or_create creates a device the first time, then only writes when a detail changed
    for device in coordinator.data.devices.values():
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, device.registry_identifier)},
            name=device.label,
            manufacturer=MANUFACTURER,
            model=device.device_name,
            sw_version=device.firmware,
            serial_number=device.serial,
        )
    # After the gateways, which fans are connected through
    for fan in coordinator.data.fans.values():
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, fan.registry_identifier)},
            name=fan.name,
            manufacturer=MANUFACTURER,
            via_device=(DOMAIN, fan.gateway_registry_identifier),
        )
