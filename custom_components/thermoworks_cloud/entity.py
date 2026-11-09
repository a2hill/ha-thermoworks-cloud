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
- Identity lives here. Entities are built from their source alone, and their ids are set
  in `build` and `__init__`, never by entities themselves.

Identifiers, Home Assistant's first and then ours:

- `unique_id`: the key Home Assistant's entity registry stores an entity under. Never shown.
  Changing it orphans the entity, so existing formats can't change.
- `entity_id`: what users see and can rename, e.g. `sensor.abc123_last_seen`. We only
  suggest it, when the entity is created.
- object id: Home Assistant's name for the part of the `entity_id` after the platform. We
  suggest one, and Home Assistant adds `_2` etc. if it's taken.
- device identifiers: `DeviceInfo(identifiers={(DOMAIN, x)})`, how a device is found in
  Home Assistant's device registry.
- `device_key`: the device's `device_id`, or its serial, and its key in
  `ThermoworksData.devices`. Every source carries its device's, so its entities can find it.
  Object ids start with it.
- `ha_device_identifier`: the `x` above, for the device a source's entities attach to,
  registered in `__init__.py`. Unique ids start with it.

The default ids are `{device_key}_{suffix}` and `{DOMAIN}-{ha_device_identifier}-{suffix}`.
A class whose ids were created in another format overrides `_suggested_object_id` or
`_unique_id` to return it.

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
    """A parsed type that has entities: it knows its device and the device they attach to."""

    @property
    def device_key(self) -> str:
        """Return the key in `ThermoworksData.devices` of the device it's on."""
        ...

    @property
    def ha_device_identifier(self) -> str:
        """Return the device registry identifier of the device its entities attach to."""
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

    _view: View[R]

    def __init__(self, coordinator: ThermoworksCoordinator, source: S) -> None:
        """Initialise the entity from a source that has this entity.

        Create entities with `build`, which only creates one where it applies.
        """
        super().__init__(coordinator)
        self._device_key = source.device_key
        self._ha_device_identifier = source.ha_device_identifier
        self._attr_unique_id = self._unique_id()
        view = self.parse(source)
        if view is None:
            raise ValueError(f"{type(self).__name__} doesn't apply to {source}")
        self._view = view
        self._has_new_view = True

    @classmethod
    def build(
        cls, hass: HomeAssistant, coordinator: ThermoworksCoordinator, source: S
    ) -> Self | None:
        """Create the entity for a source, or None if it doesn't apply."""
        if cls.parse(source) is None:
            return None
        entity = cls(coordinator, source)
        entity.entity_id = async_generate_entity_id(
            cls.entity_id_format, entity._suggested_object_id(), hass=hass
        )
        return entity

    @classmethod
    @abstractmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[S]:
        """Return the sources on the device that could have this entity.
        
        A device might have multiple sources such as channels or accessories (like a fan) for a 
        given entity type.
        """

    @abstractmethod
    def _select(self, device: ThermoworksDevice) -> S | None:
        """Return this entity's source from its device, or None if it's gone."""

    @classmethod
    @abstractmethod
    def parse(cls, source: S) -> View[R] | None:
        """Return the view for this entity, or None if the source doesn't apply to this 
        entity type."""

    def _suggested_object_id(self) -> str:
        """Return the object id to suggest for the entity id, e.g. "abc123_last_seen".

        Entity ids were previously based off of the device key rather than the
        `ha_device_identifier`. Continue to use the device key for new entities to avoid
        orphaning existing ones.
        """
        return f"{self._device_key}_{self.suffix}"

    def _unique_id(self) -> str:
        """Return the unique id. Overrides return a format existing entities already have."""
        return f"{DOMAIN}-{self._ha_device_identifier}-{self.suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        """Attach the entity to its source's device, which `__init__.py` registers."""
        return DeviceInfo(identifiers={(DOMAIN, self._ha_device_identifier)})

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
        device = data.devices.get(self._device_key)
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

    def __init__(self, coordinator: ThermoworksCoordinator, source: ThermoworksChannel) -> None:
        """Initialise the entity, remembering which channel it reads."""
        self._channel_number = source.number
        super().__init__(coordinator, source)

    @classmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[ThermoworksChannel]:
        return device.channels.values()

    def _select(self, device: ThermoworksDevice) -> ThermoworksChannel | None:
        return device.channels.get(self._channel_number)

    def _suggested_object_id(self) -> str:
        return f"{self._device_key}_ch_{self._channel_number}_{self.suffix}"

    def _unique_id(self) -> str:
        # Without the "ch" the object id has, as channel unique ids were created
        return f"{DOMAIN}-{self._ha_device_identifier}-{self._channel_number}-{self.suffix}"


class ThermoworksFanEntity[R](ThermoworksEntity[ThermoworksFan, R]):
    """An entity whose value comes from a gateway's fan accessory."""

    @classmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[ThermoworksFan]:
        return [device.fan] if device.fan is not None else []

    def _select(self, device: ThermoworksDevice) -> ThermoworksFan | None:
        return device.fan

    def _suggested_object_id(self) -> str:
        # The device key is the gateway's. The default unique id needs no "fan", since the
        # fan's `ha_device_identifier` already ends in "-fan".
        return f"{self._device_key}_fan_{self.suffix}"
