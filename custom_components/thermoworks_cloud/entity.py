"""Base entities that read everything they show from a view parsed out of the coordinator data.

Every entity follows the same rules:

- On each coordinator update, the entity finds its source (a device, or one of its channels)
  and passes it to its own `parse` method. `parse` returns a view: a small frozen dataclass
  holding everything the entity shows. Entity properties read only from the view, never from
  the source, so each entity's dependencies are written down in one place.
- A view has two parts. Its `reading` groups what the entity currently reads (the value and
  anything shown about it), and is None when the source can't give a reading right now.
  The rest describes what the entity is (name, unit, ...) and is always there, because Home
  Assistant shows those even while an entity is unavailable.
- An entity is unavailable when the coordinator update failed, its source is gone from the
  API, or its view has no reading. It recovers on the next update that has one. A stale
  reading is never shown as current. When the source is gone, the last view is kept for
  the description.
- A value Home Assistant should show as unknown is part of the reading, for entities where
  that happens (e.g. a fan that doesn't report whether it's connected).
- Identity lives here. Each class declares its suffixes, and the base class builds the
  entity id and unique id from them, so the two formats can't diverge between classes.

`supported` decides whether an entity is created at setup. By default it's created when
`parse` gives a reading, but some entities override it so they're still created when the value
is missing at first (a channel with no reading yet, for example).

State is written on every update so availability changes always reach Home Assistant.
Nothing here raises: an exception from a listener would skip that entity's state write and
leave it showing its last value as available.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Self

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo, format_mac
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator, ThermoworksData
from .models import ThermoworksChannel, ThermoworksDevice


@dataclass(frozen=True)
class View[R]:
    """What an entity shows. Subclasses add the fields that describe the entity."""

    # What the entity currently reads, or None if the source can't give a reading
    reading: R | None


@dataclass(frozen=True)
class ChannelView[R](View[R]):
    """What a channel entity shows. Every channel entity is named after its channel."""

    name: str


class ThermoworksEntity[S, R](CoordinatorEntity[ThermoworksCoordinator]):
    """Parses a view from its source on every update and shows only what's in it."""

    # Set by each platform's base class, e.g. "sensor.{}"
    entity_id_format: ClassVar[str]
    # Ends the entity id: ..._{entity_suffix}
    entity_suffix: ClassVar[str]
    # Ends the unique id: ...-{unique_id_suffix}. None for entities whose unique id was
    # created without one, which can't change without orphaning existing entities.
    unique_id_suffix: ClassVar[str | None]

    _view: View[R]

    def __init__(
        self, entity_id: str, coordinator: ThermoworksCoordinator, source: S
    ) -> None:
        """Initialise the entity from the source it was discovered on."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._attr_unique_id = "-".join(
            [DOMAIN, *self._unique_id_parts(), *filter(None, [self.unique_id_suffix])]
        )
        self._source_found = True
        self._view = self.parse(source)

    @classmethod
    @abstractmethod
    def parse(cls, source: S) -> View[R]:
        """Return everything this entity shows, parsed from its source."""

    @classmethod
    def supported(cls, source: S) -> bool:
        """Return whether to create this entity for the source at setup."""
        return cls.parse(source).reading is not None

    @abstractmethod
    def _unique_id_parts(self) -> list[str]:
        """Return the parts of the unique id that identify the source."""

    @abstractmethod
    def _find_source(self, data: ThermoworksData) -> S | None:
        """Return this entity's source from the latest data, or None if it's gone."""

    @property
    def _reading(self) -> R:
        """Return the current reading.

        Only for properties Home Assistant reads while the entity is available (state and
        attributes), which is exactly when there's a reading.
        """
        assert self._view.reading is not None
        return self._view.reading

    @property
    def available(self) -> bool:
        """Return whether the latest update gave this entity a reading."""
        return super().available and self._source_found and self._view.reading is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Parse a new view from the latest data and write state either way."""
        source = self._find_source(self.coordinator.data)
        self._source_found = source is not None
        if source is not None:
            self._view = self.parse(source)
        self.async_write_ha_state()


class ThermoworksDeviceEntity[R](ThermoworksEntity[ThermoworksDevice, R]):
    """An entity whose value comes from one device."""

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device: ThermoworksDevice,
    ) -> None:
        """Initialise the entity from the device it was discovered on."""
        self._device_identifier = device.get_identifier()
        super().__init__(entity_id, coordinator, device)

    @classmethod
    def build(
        cls, hass: HomeAssistant, coordinator: ThermoworksCoordinator, device: ThermoworksDevice
    ) -> Self:
        """Create the entity with an entity id generated from its identity."""
        object_id = f"{device.get_identifier()}_{cls.entity_suffix}"
        return cls(
            async_generate_entity_id(cls.entity_id_format, object_id, hass=hass),
            coordinator,
            device,
        )

    def _unique_id_parts(self) -> list[str]:
        return [format_mac(self._device_identifier)]

    def _find_source(self, data: ThermoworksData) -> ThermoworksDevice | None:
        return data.devices.get(self._device_identifier)

    @property
    def device_info(self) -> DeviceInfo:
        """Attach the entity to its device, which `devices.py` registers with its details."""
        return DeviceInfo(identifiers={(DOMAIN, format_mac(self._device_identifier))})


class ThermoworksChannelEntity[R](ThermoworksEntity[ThermoworksChannel, R]):
    """An entity whose value comes from one channel of a device."""

    _view: ChannelView[R]

    def __init__(
        self,
        entity_id: str,
        coordinator: ThermoworksCoordinator,
        device_identifier: str,
        device_channel: ThermoworksChannel,
    ) -> None:
        """Initialise the entity from the channel it was discovered on."""
        self._device_identifier = device_identifier
        self._channel_number = device_channel.number
        super().__init__(entity_id, coordinator, device_channel)

    @classmethod
    def build(
        cls,
        hass: HomeAssistant,
        coordinator: ThermoworksCoordinator,
        device_identifier: str,
        device_channel: ThermoworksChannel,
    ) -> Self:
        """Create the entity with an entity id generated from its identity."""
        object_id = f"{device_identifier}_ch_{device_channel.number}_{cls.entity_suffix}"
        return cls(
            async_generate_entity_id(cls.entity_id_format, object_id, hass=hass),
            coordinator,
            device_identifier,
            device_channel,
        )

    def _unique_id_parts(self) -> list[str]:
        return [format_mac(self._device_identifier), self._channel_number]

    def _find_source(self, data: ThermoworksData) -> ThermoworksChannel | None:
        device = data.devices.get(self._device_identifier)
        return device.channels.get(self._channel_number) if device else None

    @property
    def device_info(self) -> DeviceInfo:
        """Attach the entity to its device, which `devices.py` registers with its details."""
        return DeviceInfo(identifiers={(DOMAIN, format_mac(self._device_identifier))})
