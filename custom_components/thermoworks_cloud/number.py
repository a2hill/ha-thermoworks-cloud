"""Number platform for the ThermoWorks Cloud integration.

This platform exposes a single entity, :class:`ScanIntervalNumber`, which controls
the polling interval for the **entire** config entry -- every device and channel
is fetched by one shared :class:`~.coordinator.ThermoworksCoordinator`, so this
value applies to every device on the account, not per-device.

Setting the value rewrites the ``CONF_SCAN_INTERVAL`` config entry option. The
integration's own update listener (``__init__._async_update_listener``) reacts to
that options change by reloading the config entry, which rebuilds the coordinator
with the new ``update_interval`` and performs an immediate refresh. That reload is
what actually applies the change -- this entity never touches the coordinator
directly.

Because the setting belongs to the config entry as a whole rather than to any
thermometer, the entity is attached to a ``DeviceEntryType.SERVICE`` device that
represents the config entry itself (identified by ``entry_id``, no manufacturer /
model). That keeps it off the individual device pages while still giving Home
Assistant a device name to compose the entity name from and a card to group any
future account-wide entities under.

Exposing the interval as a ``number`` entity (in addition to the options flow)
lets automations retune it on the fly: poll every few seconds while a cook is
running, then fall back to a long interval once the gateway goes idle. The
options-flow field and this entity are two views of the same
``options[CONF_SCAN_INTERVAL]`` value and cannot drift.
"""

from __future__ import annotations

import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the scan interval number entity for a config entry."""
    async_add_entities([ScanIntervalNumber(config_entry)])


class ScanIntervalNumber(NumberEntity):
    """Controls the polling interval for the whole ThermoWorks Cloud config entry.

    The config entry option ``CONF_SCAN_INTERVAL`` is the single source of truth:
    :attr:`native_value` reads it back and :meth:`async_set_native_value` writes
    it. Writing the option triggers an integration reload (see the module
    docstring), which is what propagates the new interval to the coordinator, so
    this class does not hold or update any interval state of its own.

    The interval governs every device and channel at once, so the entity is put
    on a service device that stands for the config entry itself rather than on
    any individual thermometer.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "scan_interval"
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = MIN_SCAN_INTERVAL_SECONDS
    _attr_native_max_value = MAX_SCAN_INTERVAL_SECONDS
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise the entity for the given config entry."""
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_scan_interval"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=config_entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int:
        """Return the current scan interval in seconds from the options store."""
        return self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
        )

    async def async_set_native_value(self, value: float) -> None:
        """Persist a new scan interval on the config entry.

        Only the options store is updated here. The integration's update listener
        reacts to the options change by reloading the entry, which rebuilds the
        coordinator with the new ``update_interval`` and performs an immediate
        refresh -- so there is no need to update the coordinator from here.
        """
        new_interval = round(value)
        # Compare with native_value, not the raw option, so that setting the
        # default on an entry whose option was never saved is also a no-op.
        if new_interval == self.native_value:
            return

        _LOGGER.debug("Setting scan interval to %s seconds", new_interval)
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options={
                **self._config_entry.options,
                CONF_SCAN_INTERVAL: new_interval,
            },
        )
