"""Base classes for every Thermoworks entity.

How an entity works:

1. `sources` picks what on a device could have the entity: the device itself, each channel,
   or its fan.
2. `parse` turns a source into a `View`, or None if the source doesn't have the entity.
   Entities are only created where it returns a view. See `View` for what goes in one.
3. The base class sets Home Assistant's `_attr_*` values from the view through `_describe`
   and `_apply`. Entities never implement Home Assistant's properties, so they don't need to
   know when it reads which one.
4. On every coordinator update, the entity finds its source again with `_select`, repeats
   steps 2 and 3, and writes its state.

An entity is unavailable when the coordinator update failed, its source is gone, `parse`
returned None, or the view has no entity state. It recovers on the next update that has one.

Nothing here may raise: an exception in a coordinator listener skips that entity's state
write and leaves its last value showing as available.

Ids are set here, never by entities (`device_key` and `ha_device_identifier` are on `Source`):

- `unique_id`, `{DOMAIN}-{ha_device_identifier}-{suffix}`: the entity registry's key.
  Changing it orphans the entity, so existing formats can't change.
- `entity_id`, `{platform}.{device_key}_{suffix}`: only suggested when the entity is created.
  Home Assistant adds `_2` if it's taken, and users can rename it.

A class whose ids were created in another format overrides `_unique_id` or
`_suggested_object_id`.
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
    """Everything an entity shows, parsed from its source by the entity's `parse` method.

    A Thermoworks device reports two kinds of data: its configuration (channel names, 
    display units, which alarms are set), which is known even when it has nothing to 
    measure, and its live readings, which come and go as probes are plugged in or fans 
    connect. This class provides a means of separating that data so an entity can be 
    displayed in HA even if its actual functionality (like measuring temperature) is 
    not available. For instance, an RFX probe that isn't in use.
    """

    # Values from the source which are used to determine the current state of the 
    # entity, and anything shown with it, like attributes or a charging icon. Examples:
    # * For a temperature sensor entity, the currently measured temperature
    # * For a binary sensor (like FanConnectedSensor), the connection state
    # This property can be `None` when the entity exists but has nothing current to
    # report (a failed probe, a disconnected fan). Doing so will make the entity
    # `unavailable` in the HA UI. If it's possible for the source to report a partial
    # state, prefer optional fields within the state type.
    entity_state: R | None
    # Values from the source that are related to the existence of the entity,
    # regardless of its current state. Examples: its name, unit or device class.
    # When class attributes like `_attr_device_class` describe the entity fully, 
    # leave `D` as its default, `None`, and pass `description=None`.
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

        While you can construct entities directly, the `build` method is provided for convenience.
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
        """Return only the sources from the device object that could have this entity type.
        
        A device might have multiple sources such as channels or accessories (like a fan) for a 
        given entity type.
        """

    @abstractmethod
    def _select(self, device: ThermoworksDevice) -> S | None:
        """Return this entity's source from the device object, or None if it's gone."""

    @classmethod
    @abstractmethod
    def parse(cls, source: S) -> View[R, D] | None:
        """Parse this entity's view of a source.

        Return None if the source doesn't have this entity, or a view with no entity state
        if it does but has no current reading.
        """

    def _suggested_object_id(self) -> str:
        """Return the object id to suggest for use in the entity id, e.g. "abc123_last_seen".

        Entity ids have always started with the device key, not the `ha_device_identifier`.
        New entities keep that pattern so they match the existing ones on a device. Changing
        it wouldn't affect existing entities, since the registry keeps their ids.
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

        Called with the description from every parsed view, even when the entity is not available
        since Home Assistant still displays descriptions for unavailable entities. Entities whose 
        description is all class attributes shouldn't override it.
        """

    @abstractmethod
    def _apply(self, entity_state: R) -> None:
        """Use the entity_state to set this entity's `_attr_*` values.

        Only called when `parse` returns a `View` containing an `entity_state`
        """

    def _on_unavailable(self) -> None:
        """Undo anything `_apply` set that Home Assistant shows while unavailable.

        Home Assistant still shows some values while an entity is unavailable, like its icon.
        If `_apply` sets one of those, override this to reset it, so it doesn't show a
        stale state. Called after every update that leaves the entity unavailable so it 
        must be safe to run more than once.
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
        """Return whether the latest update gave this entity the required state to be 
        considered 'available'."""
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
        # Without the "ch" the object id has, as channel unique ids were initially
        # created with a different scheme and changing them now would orphan existing entities.
        return f"{DOMAIN}-{self._ha_device_identifier}-{self._channel_number}-{self.suffix}"


class ThermoworksFanEntity[R, D = None](ThermoworksEntity[ThermoworksFan, R, D]):
    """An entity whose value comes from a gateway's fan accessory."""

    @classmethod
    def sources(cls, device: ThermoworksDevice) -> Iterable[ThermoworksFan]:
        return [device.fan] if device.fan is not None else []

    def _select(self, device: ThermoworksDevice) -> ThermoworksFan | None:
        return device.fan

    def _suggested_object_id(self) -> str:
        # The device key is the gateway's device key. The default unique id needs no 
        # "fan", since the fan's `ha_device_identifier` already ends in "-fan".
        return f"{self._device_key}_fan_{self.suffix}"
