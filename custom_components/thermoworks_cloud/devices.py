"""Registers each ThermoWorks device, and its fan accessory, in Home Assistant's device registry.

Devices are registered here explicitly rather than through entities' `device_info`, so that:

- every device gets its details (name, model, firmware), whichever entities it has
- the details stay current: this runs after every successful refresh, so a firmware update
  or a rename in the ThermoWorks app shows up without a reload

Entities attach to these devices by identifier only. A name the user sets in Home Assistant
is stored separately (`name_by_user`), so updating `name` here never overwrites it.
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
    """Create or update the registry entry for every device in the latest data."""
    # A failed refresh keeps the previous data, which was already registered
    if not coordinator.last_update_success:
        return

    registry = dr.async_get(hass)
    for device in coordinator.data.devices.values():
        identifier = dr.format_mac(device.get_identifier())
        # Creates the device the first time, then only writes when a detail changed
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, identifier)},
            name=device.label,
            manufacturer=MANUFACTURER,
            model=device.device_name,
            sw_version=device.firmware,
            serial_number=device.serial,
        )
        if device.fan is not None:
            # The fan accessory is its own device, connected through the gateway
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"{identifier}-fan")},
                name=f"{device.label or device.display_name()} Fan",
                manufacturer=MANUFACTURER,
                via_device=(DOMAIN, identifier),
            )
