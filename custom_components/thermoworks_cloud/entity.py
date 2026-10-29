"""Common configuration for ThermoWorks entities backed by the coordinator."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ThermoworksCoordinator


class ThermoworksEntity(CoordinatorEntity[ThermoworksCoordinator]):
    """An entity associated with a device and the shared data coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        *,
        device_info: DeviceInfo,
    ) -> None:
        """Connect the entity to its coordinator and supplied device reference."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._attr_device_info = device_info
