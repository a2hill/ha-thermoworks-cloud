"""Shared entity behavior for ThermoWorks fan accessories."""

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator
from .models import DeviceWithFan, get_missing_attributes


class ThermoworksFanEntity(CoordinatorEntity[ThermoworksCoordinator]):
    """Common device information and updates for fan accessory entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device: DeviceWithFan,
        *,
        gateway_registry_id: str,
    ) -> None:
        """Initialise the fan entity."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._device = device
        self._gateway_registry_id = gateway_registry_id

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update the fan entity with the latest coordinator data."""
        device = self.coordinator.get_device_by_id(self._device.get_identifier())
        if not device:
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device {self._device.display_name()} is not found"
            )
        if not DeviceWithFan.is_protocol_compliant(device):
            raise UpdateFailed(
                f"Cannot update sensor {self.name}: device {self._device.display_name()} is missing required "
                f"attribute(s): {get_missing_attributes(device, DeviceWithFan)}"
            )
        self._device = device
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return fan device information."""
        # Because this sensor connects through a gateway device, we set via_device_id to the gateway's registry id.
        return DeviceInfo(
            identifiers={(DOMAIN, f"{format_mac(self._device.get_identifier())}-fan")},
            name=f"{self._device.label or self._device.display_name()} Fan",
            manufacturer="ThermoWorks",
            via_device_id=self._gateway_registry_id,
        )

