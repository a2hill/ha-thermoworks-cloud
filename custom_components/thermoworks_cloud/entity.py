"""Base entities that read everything they show from a view parsed out of the coordinator data.

Every entity follows the same rules:

- Each entity has a source: a parsed device, one of its channels, or its fan accessory. On each
  coordinator update it looks up its device and picks its source from it, then passes the
  source to its own `parse` method. `parse` returns a view: a small frozen dataclass holding
  everything the entity shows. Entity properties read only from the view, never from the
  source, so each entity's dependencies are written down in one place.
- `parse` returns None when the source doesn't have this entity at all (a device with no
  battery, a channel with no high alarm). Entities are only created where `parse` returns a
  view, and an existing entity whose source stops having it becomes unavailable.
- A view has two parts. Its `entity_state` is each entity's own type holding what it
  currently reads (the value and anything shown about it, like Home Assistant's state and
  attributes), and is None when the source can't give one right now. The rest describes
  what the entity is (name, unit, ...) and is always there, because Home Assistant shows
  those even while an entity is unavailable.
- An entity is unavailable when the coordinator update failed, its source is gone from the
  API, `parse` returned None, or its view has no entity state. It recovers on the next
  update that has one. A stale entity state is never shown as current. Without a new view,
  the last one is kept for the description.
- A value Home Assistant should show as unknown is part of the entity state, for entities
  where that happens (e.g. a fan that doesn't report whether it's connected).
- Identity lives here. Every source carries the `registry_identifier` of the device its
  entities attach to (the `Source` protocol), registered in `__init__.py`. The entity id and
  unique id are both built in `build` and `__init__` from the same parts: the device, any
  parts each base class adds (like the channel number), and the class's suffix. Entities
  never build identifiers themselves.

State is written on every update so availability changes always reach Home Assistant.
Nothing here raises: an exception from a listener would skip that entity's state write and
leave it showing its last value as available.
"""

from abc import abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar, Protocol, Self

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ThermoworksCoordinator, ThermoworksData
from .models import ThermoworksChannel, ThermoworksDevice, ThermoworksFan


class Source(Protocol):
    """A parsed type that has entities: it knows which registered device they attach to."""

    @property
    def registry_identifier(self) -> str:
        """Return the identifier of the Home Assistant device its entities attach to."""
        ...


@dataclass(frozen=True)
class View[R]:
    """What an entity shows. Subclasses add the fields that describe the entity."""

    # What the entity currently reads, or None if the source can't give it right now
    entity_state: R | None


@dataclass(frozen=True)
class ChannelView[R](View[R]):
    """What a channel entity shows. Every channel entity is named after its channel."""

    name: str


class ThermoworksEntity[S: Source, R](CoordinatorEntity[ThermoworksCoordinator]):
    """Parses a view from its source on every update and shows only what's in it."""

    # Set by each platform's base class, e.g. "sensor.{}"
    entity_id_format: ClassVar[str]
    # Ends both ids. The entity id is generated as a slug, so "last-seen" becomes "last_seen".
    suffix: ClassVar[str]
    # False only for entities whose unique id was created without the suffix, which can't
    # change without orphaning existing entities
    unique_id_has_suffix: ClassVar[bool] = True

    _view: View[R]

    def __init__(
        self, coordinator: ThermoworksCoordinator, device: ThermoworksDevice, source: S
    ) -> None:
        """Initialise the entity from a device and the source on it that has this entity.

        Create entities with `build`, which only creates one where it applies.
        """
        super().__init__(coordinator)
        self._device_identifier = device.get_identifier()
        self._registry_identifier = source.registry_identifier
        self._attr_unique_id = "-".join(
            [
                DOMAIN,
                self._registry_identifier,
                *self._unique_id_parts(),
                *([self.suffix] if self.unique_id_has_suffix else []),
            ]
        )
        view = self.parse(source)
        if view is None:
            raise ValueError(f"{type(self).__name__} doesn't apply to {source}")
        self._view = view
        self._has_new_view = True

    @classmethod
    def build(
        cls,
        hass: HomeAssistant,
        coordinator: ThermoworksCoordinator,
        device: ThermoworksDevice,
        source: S,
    ) -> Self | None:
        """Create the entity for a source on the device, or None if it doesn't apply."""
        if cls.parse(source) is None:
            return None
        entity = cls(coordinator, device, source)
        # The device identifier rather than the registry identifier, to keep the entity ids
        # new entities have always been given
        object_id = "_".join(
            [entity._device_identifier, *entity._entity_id_parts(), cls.suffix]
        )
        entity.entity_id = async_generate_entity_id(cls.entity_id_format, object_id, hass=hass)
        return entity

    @classmethod
    @abstractmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[S]:
        """Return the sources on the device that could have this entity."""

    @abstractmethod
    def _select(self, device: ThermoworksDevice) -> S | None:
        """Return this entity's source from its device, or None if it's gone."""

    @classmethod
    @abstractmethod
    def parse(cls, source: S) -> View[R] | None:
        """Return everything this entity shows, or None if the source doesn't have it."""

    def _entity_id_parts(self) -> list[str]:
        """Return parts of the entity id between the device identifier and the suffix."""
        return []

    def _unique_id_parts(self) -> list[str]:
        """Return parts of the unique id between the registry identifier and the suffix."""
        return []

    @property
    def device_info(self) -> DeviceInfo:
        """Attach the entity to its source's device, which `__init__.py` registers."""
        return DeviceInfo(identifiers={(DOMAIN, self._registry_identifier)})

    @property
    def _entity_state(self) -> R:
        """Return the current entity state.

        Only for properties Home Assistant reads while the entity is available (state and
        attributes), which is exactly when there's an entity state.
        """
        assert self._view.entity_state is not None
        return self._view.entity_state

    @property
    def available(self) -> bool:
        """Return whether the latest update gave this entity an entity state."""
        return (
            super().available
            and self._has_new_view
            and self._view.entity_state is not None
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Parse a new view from the latest data and write state either way."""
        data: ThermoworksData = self.coordinator.data
        device = data.devices.get(self._device_identifier)
        source = self._select(device) if device is not None else None
        view = self.parse(source) if source is not None else None
        self._has_new_view = view is not None
        if view is not None:
            self._view = view
        self.async_write_ha_state()


class ThermoworksDeviceEntity[R](ThermoworksEntity[ThermoworksDevice, R]):
    """An entity whose value comes from the device itself."""

    @classmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[ThermoworksDevice]:
        return [device]

    def _select(self, device: ThermoworksDevice) -> ThermoworksDevice | None:
        return device


class ThermoworksChannelEntity[R](ThermoworksEntity[ThermoworksChannel, R]):
    """An entity whose value comes from one channel of a device."""

    _view: ChannelView[R]

    def __init__(
        self,
        coordinator: ThermoworksCoordinator,
        device: ThermoworksDevice,
        source: ThermoworksChannel,
    ) -> None:
        """Initialise the entity, remembering which channel it reads."""
        self._channel_number = source.number
        super().__init__(coordinator, device, source)

    @classmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[ThermoworksChannel]:
        return device.channels.values()

    def _select(self, device: ThermoworksDevice) -> ThermoworksChannel | None:
        return device.channels.get(self._channel_number)

    def _entity_id_parts(self) -> list[str]:
        return ["ch", self._channel_number]

    def _unique_id_parts(self) -> list[str]:
        return [self._channel_number]


class ThermoworksFanEntity[R](ThermoworksEntity[ThermoworksFan, R]):
    """An entity whose value comes from a gateway's fan accessory."""

    @classmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[ThermoworksFan]:
        return [device.fan] if device.fan is not None else []

    def _select(self, device: ThermoworksDevice) -> ThermoworksFan | None:
        return device.fan

    def _entity_id_parts(self) -> list[str]:
        # The fan's registry identifier already ends in "-fan", so the unique id needs no part
        return ["fan"]
