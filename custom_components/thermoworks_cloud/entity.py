"""Base entities that read everything they show from a view parsed out of the coordinator data.

Every entity follows the same rules:

- Each entity has a source: a parsed device, one of its channels, or its fan accessory. On each
  coordinator update it looks up its device and picks its source from it, then passes the
  source to its own `parse` method. `parse` returns a view: a small frozen dataclass holding
  everything the entity shows, so each entity's dependencies are written down in one place.
- Entities don't implement Home Assistant's properties. They set its `_attr_*` values from
  the view in `_describe` and `_apply`, which the base class calls at the right times. So an
  entity doesn't need to know when Home Assistant reads which property.
- `parse` returns None when the source doesn't have this entity at all (a device with no
  battery, a channel with no high alarm). Entities are only created where `parse` returns a
  view, and an existing entity whose source stops having it becomes unavailable.
- A view has two parts, each its own type parameter of the entity. Its `entity_state` (`R`)
  holds what the entity currently reads (the value and anything shown about it, like Home
  Assistant's state and attributes), and is None when the source can't give one right now.
  Its `description` (`D`) is what the entity is (name, unit, ...) and is always there,
  because Home Assistant shows those even while an entity is unavailable. `_describe` gets
  every new description, and `_apply` gets only an entity state that's there, so it never
  has to check for None. Since the entity names both types, `parse` can't return a view
  that doesn't match what `_describe` and `_apply` take.
- An entity is unavailable when the coordinator update failed, its source is gone from the
  API, `parse` returned None, or its view has no entity state. It recovers on the next
  update that has one. A stale entity state is never shown as current: anything `_apply`
  sets that Home Assistant shows while unavailable (like an icon) is undone in
  `_on_unavailable`. Without a new view, the last description is kept.
- A value Home Assistant should show as unknown is part of the entity state, for entities
  where that happens (e.g. a fan that doesn't report whether it's connected).
- Identity lives here. Entities are built from their source alone, and their ids are set
  in `__init__`, never by entities themselves.

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
    """Properties which link an entity to its underlying data source (generally a device)"""

    @property
    def device_key(self) -> str:
        """The key to the entry in `ThermoworksData.devices` which contains the data 
        for this entity."""
        ...

    @property
    def ha_device_identifier(self) -> str:
        """The key for this entity's device in the HA device registry."""
        ...


@dataclass(frozen=True)
class View[R, D]:
    """Contains the data that an entity parses from its source. Should contain only the 
    data that the entity needs to update its state."""

    # Contains the state required for an entity to be 'available' in HA terms. Will be None 
    # if the source is unavailable and can't give it right now
    entity_state: R | None
    # What the entity is (name, unit, ...). None for entities described by class attributes alone.
    description: D


@dataclass(frozen=True)
class ChannelDescription:
    """The description every channel entity has."""

    # Every channel entity is named after its channel.
    name: str


class ThermoworksEntity[S: Source, R, D = None](CoordinatorEntity[ThermoworksCoordinator]):
    """Base class for all entities of Thermoworks devices. Parses a view from its source on 
    every update."""

    # Set by each platform's base class, e.g. "sensor.{}"
    entity_id_format: ClassVar[str]
    # Appended to both ids of the entity. The entity id is generated as a slug, so "last-seen" becomes "last_seen".
    suffix: ClassVar[str]

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ThermoworksCoordinator,
        source: S,
        view: View[R, D],
    ) -> None:
        """Initialise the entity from a source and the view parsed from it.

        Taking the view means an entity can't be created for a source it doesn't apply to,
        so the constructor always succeeds. `build` parses the view for you.
        """
        super().__init__(coordinator)
        self._device_key = source.device_key
        self._ha_device_identifier = source.ha_device_identifier
        self._attr_unique_id = self._unique_id()
        self.entity_id = async_generate_entity_id(
            self.entity_id_format, self._suggested_object_id(), hass=hass
        )
        self._update_from(view)

    @classmethod
    def build(
        cls, hass: HomeAssistant, coordinator: ThermoworksCoordinator, source: S
    ) -> Self | None:
        """Create the entity for a source, or None if it doesn't apply."""
        view = cls.parse(source)
        if view is None:
            return None
        return cls(hass, coordinator, source, view)

    @classmethod
    @abstractmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[S]:
        """Return the sources on the device that could have this entity type.
        
        A device might have multiple sources such as channels or accessories (like a fan) for a 
        given entity type.
        """

    @abstractmethod
    def _select(self, device: ThermoworksDevice) -> S | None:
        """Return this entity's source from its device, or None if it's gone."""

    @classmethod
    @abstractmethod
    def parse(cls, source: S) -> View[R, D] | None:
        """Parse this entities view of a source, or None if the source doesn't apply to this 
        entity type."""

    def _suggested_object_id(self) -> str:
        """Return the object id to suggest for use in the the entity id, e.g. "abc123_last_seen".

        Entity ids were previously based off of the device key rather than the
        `ha_device_identifier`. Continue to use the device key for new entities to avoid
        orphaning existing ones.
        """
        return f"{self._device_key}_{self.suffix}"

    def _unique_id(self) -> str:
        """Return the unique id of the entity."""
        return f"{DOMAIN}-{self._ha_device_identifier}-{self.suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        """Information used by HA to link an entity to a device."""
        return DeviceInfo(identifiers={(DOMAIN, self._ha_device_identifier)})

    def _describe(self, description: D) -> None:
        """Set the `_attr_*` values that describe the entity (name, unit, ...).

        Called with every new view, even one with no entity state, since Home Assistant
        shows these while the entity is unavailable too. Entities whose description is all
        class attributes don't override it.
        """

    @abstractmethod
    def _apply(self, entity_state: R) -> None:
        """Set the `_attr_*` values Home Assistant shows as the state, from an entity state.

        Only called when there is one, so it's never None here. When the entity becomes
        unavailable these values are left as they were, since Home Assistant doesn't show
        the state or attributes then. Anything it does show is undone in `_on_unavailable`.
        """

    def _on_unavailable(self) -> None:
        """Undo anything `_apply` set that Home Assistant shows while unavailable.

        Home Assistant still shows some values while an entity is unavailable, like its icon.
        If `_apply` sets one of those, override this to reset it, so it doesn't show a
        stale state. Called after every update that leaves the entity unavailable, for any
        reason, so it must be safe to run more than once.
        """

    def _update_from(self, view: View[R, D] | None) -> None:
        """Apply a new view, or mark the entity unavailable if there isn't one.

        Without a view the last description is kept, since there's nothing newer.
        """
        self._has_entity_state = view is not None and view.entity_state is not None
        if view is not None:
            self._describe(view.description)
            if view.entity_state is not None:
                self._apply(view.entity_state)
        # Checked here rather than above, as a failed coordinator update also makes it unavailable
        if not self.available:
            self._on_unavailable()

    @property
    def available(self) -> bool:
        """Return whether the latest update gave this entity an entity state."""
        # CoordinatorEntity's `available` ignores `_attr_available`, so this keeps its own flag
        return super().available and self._has_entity_state

    @callback
    def _handle_coordinator_update(self) -> None:
        """Parse a new view from the latest data and write state either way."""
        data: ThermoworksData = self.coordinator.data
        device = data.devices.get(self._device_key)
        source = self._select(device) if device is not None else None
        self._update_from(self.parse(source) if source is not None else None)
        self.async_write_ha_state()


class ThermoworksDeviceEntity[R, D = None](ThermoworksEntity[ThermoworksDevice, R, D]):
    """An entity whose value comes from the device itself."""

    @classmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[ThermoworksDevice]:
        return [device]

    def _select(self, device: ThermoworksDevice) -> ThermoworksDevice | None:
        return device


class ThermoworksChannelEntity[R, D: ChannelDescription = ChannelDescription](
    ThermoworksEntity[ThermoworksChannel, R, D]
):
    """An entity whose value comes from one channel of a device."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ThermoworksCoordinator,
        source: ThermoworksChannel,
        view: View[R, D],
    ) -> None:
        """Initialise the entity, remembering which channel it reads."""
        # Before super().__init__, which builds the ids from it
        self._channel_number = source.number
        super().__init__(hass, coordinator, source, view)

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


class ThermoworksFanEntity[R, D = None](ThermoworksEntity[ThermoworksFan, R, D]):
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
