"""Common configuration for ThermoWorks entities backed by the coordinator."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator


class ThermoworksEntity(CoordinatorEntity[ThermoworksCoordinator]):
    """An entity associated with a device and the shared data coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        *,
        identifier: str,
    ) -> None:
        """Connect the coordinator and store the device association chosen by setup."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._device_identifier = identifier
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, identifier)})
