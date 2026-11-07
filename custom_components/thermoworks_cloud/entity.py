"""Base entity for values read from a ThermoWorks device."""

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ThermoworksCoordinator
from .models import ThermoworksDevice


class ThermoworksDeviceEntity(CoordinatorEntity[ThermoworksCoordinator]):
    """An entity whose value comes from one device in each coordinator update.

    Each subclass sets `_capability` to the device protocol it reads from, such as
    `DeviceWithBattery`. On every update the device is looked up again by identifier:

    - If it's present and still meets the capability, it replaces the stored device.
    - If it's missing, or lost the field this entity reads, the entity is unavailable.
      The last good device is kept only for the name, unique id and device info, and
      its old value is never shown. The entity recovers when the device comes back.

    State is always written so availability changes reach Home Assistant. This never
    raises: the coordinator logs a listener's exception and moves on, but the entity
    would skip its state write and keep showing its last value as available.
    """

    _capability: type[ThermoworksDevice]

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device: ThermoworksDevice,
    ) -> None:
        """Initialise the entity with the device it was discovered from."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._device = device

    def _current_device(self) -> ThermoworksDevice | None:
        """Return the device from the latest update if this entity can read it."""
        device = self.coordinator.get_device_by_id(self._device.get_identifier())
        if device is None or not self._capability.is_protocol_compliant(device):
            return None
        return device

    @property
    def available(self) -> bool:
        """Do not present the last known value of a device the API no longer provides."""
        return super().available and self._current_device() is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Keep the latest readable device and write state either way."""
        device = self._current_device()
        if device is not None:
            self._device = device
        self.async_write_ha_state()
