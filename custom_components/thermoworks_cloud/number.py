"""Number entity for Thermoworks Cloud integration."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN, MIN_SCAN_INTERVAL_SECONDS
from .coordinator import ThermoworksCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number entities for the Thermoworks Cloud integration."""
    coordinator: ThermoworksCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ].coordinator

    async_add_entities([ScanIntervalNumber(coordinator, config_entry)])


class ScanIntervalNumber(CoordinatorEntity[ThermoworksCoordinator], NumberEntity):
    """Number entity to control the scan interval."""

    _attr_has_entity_name = True
    _attr_translation_key = "scan_interval"
    _attr_native_min_value = MIN_SCAN_INTERVAL_SECONDS
    _attr_native_max_value = 86400  # 24 hours in seconds
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: ThermoworksCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the scan interval number entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_scan_interval"

        # Set initial value from options (backward compatible with old config flow)
        # or use default if not set
        self._attr_native_value = config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
        )

    @property
    def device_info(self):
        """Return device info for this entity."""
        # This creates a "virtual" device for the integration itself
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": "ThermoWorks Cloud",
            "manufacturer": "ThermoWorks",
            "model": "Cloud Integration",
        }

    async def async_set_native_value(self, value: float) -> None:
        """Update the scan interval."""
        new_interval = int(value)
        _LOGGER.debug("Updating scan interval to %s seconds", new_interval)

        # Update the coordinator's poll interval immediately (no restart needed)
        self.coordinator.poll_interval = new_interval
        self.coordinator.update_interval = timedelta(seconds=new_interval)

        # Store the value in config entry options for persistence across restarts
        # This maintains backward compatibility with the old options flow system
        new_options = {**self._config_entry.options, CONF_SCAN_INTERVAL: new_interval}
        self.hass.config_entries.async_update_entry(
            self._config_entry, options=new_options
        )

        # Update the entity state
        self._attr_native_value = new_interval
        self.async_write_ha_state()

        _LOGGER.info("Scan interval updated to %s seconds", new_interval)
