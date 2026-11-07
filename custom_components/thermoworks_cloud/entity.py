"""Base entities that read their values from the coordinator's parsed devices.

Every entity follows the same rule for missing data:

- On each coordinator update, the entity finds its source (a device, or one of its channels)
  and passes it to its own `parse` method. `parse` returns the typed value the entity shows,
  or None when the source can't provide it.
- None, or a source the API no longer returns, makes the entity unavailable. It recovers
  on the next update that provides a value. A stale value is never shown as current.
- The last source seen is kept for names, unique ids and device info, which have to stay
  stable while the entity is unavailable.

`supported` decides whether an entity is created at setup. By default it's created when
`parse` returns a value, but some entities override it so they're still created when the
value is missing at first (a channel with no reading yet, for example).

State is written on every update so availability changes always reach Home Assistant.
Nothing here raises: an exception from a listener would skip that entity's state write and
leave it showing its last value as available.
"""

from typing import Generic, TypeVar

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ThermoworksCoordinator
from .models import ThermoworksChannel, ThermoworksDevice

T = TypeVar("T")


class ThermoworksDeviceEntity(CoordinatorEntity[ThermoworksCoordinator], Generic[T]):
    """An entity whose value comes from one device."""

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device: ThermoworksDevice,
    ) -> None:
        """Initialise the entity from the device it was discovered on."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._device = device
        self._value: T | None = self.parse(device)

    @classmethod
    def parse(cls, device: ThermoworksDevice) -> T | None:
        """Return this entity's value from the device, or None if it can't provide one."""
        raise NotImplementedError

    @classmethod
    def supported(cls, device: ThermoworksDevice) -> bool:
        """Return whether to create this entity for the device at setup."""
        return cls.parse(device) is not None

    @property
    def available(self) -> bool:
        """Return whether the latest update gave this entity a value."""
        return super().available and self._value is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Parse this entity's value from the latest data and write state either way."""
        device = self.coordinator.data.devices.get(self._device.get_identifier())
        if device is not None:
            self._device = device
        self._value = self.parse(device) if device is not None else None
        self.async_write_ha_state()


class ThermoworksChannelEntity(CoordinatorEntity[ThermoworksCoordinator], Generic[T]):
    """An entity whose value comes from one channel of a device."""

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device_serial: str,
        device_channel: ThermoworksChannel,
    ) -> None:
        """Initialise the entity from the channel it was discovered on."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._device_serial = device_serial
        self._device_channel = device_channel
        self._value: T | None = self.parse(device_channel)

    @classmethod
    def parse(cls, channel: ThermoworksChannel) -> T | None:
        """Return this entity's value from the channel, or None if it can't provide one."""
        raise NotImplementedError

    @classmethod
    def supported(cls, channel: ThermoworksChannel) -> bool:
        """Return whether to create this entity for the channel at setup."""
        return cls.parse(channel) is not None

    @property
    def available(self) -> bool:
        """Return whether the latest update gave this entity a value."""
        return super().available and self._value is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Parse this entity's value from the latest data and write state either way."""
        device = self.coordinator.data.devices.get(self._device_serial)
        channel = device.channels.get(self._device_channel.number) if device else None
        if channel is not None:
            self._device_channel = channel
        self._value = self.parse(channel) if channel is not None else None
        self.async_write_ha_state()
