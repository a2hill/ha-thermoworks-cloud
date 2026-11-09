"""Domain types for the Thermoworks Cloud integration.

The coordinator parses each API response into these types once per update. They describe
devices, their channels and fan accessories as this integration understands them, and know
nothing about Home Assistant entities.

- A device needs a serial and a channel needs a number and units. Anything without them is
  rejected here, so nothing downstream has to check for them again.
- Everything else stays optional because devices report different fields. Each entity decides
  what it needs from these types in its own `parse` method (see `entity.py`).
- The library stays flexible about what the API might send. This integration doesn't: values
  it handles from a known set, like units and fan states, become its own enums here, and
  anything else becomes None.
- A field is kept raw only if something shows it as reported, like a channel's `status`.
  Where there's a rule over a value, the rule runs here and only its result is stored: a
  channel keeps `reading` but not the raw value. That way there's no path around the rule,
  and it can't drift between the entities that depend on it.
- Every type that has entities carries the `device_key` of the device it's on, which
  is how its entities find it again, and the `ha_device_identifier` of the Home Assistant
  device they attach to. Both are derived once here.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
import logging

from homeassistant.helpers.device_registry import format_mac
from homeassistant.util import dt as dt_util
from thermoworks_cloud.models import (
    Alarm,
    ChannelStatus,
    Device,
    DeviceChannel,
    Fan,
    FanState,
)

from .exceptions import MissingRequiredAttributeError

_LOGGER: logging.Logger = logging.getLogger(__package__)


class Unit(StrEnum):
    """Units the API reports that this integration handles, by their API value."""

    FAHRENHEIT = "F"
    CELSIUS = "C"
    HUMIDITY = "H"

    @classmethod
    def parse(cls, value: str | None) -> "Unit | None":
        """Return the unit for an API value, or None if this integration doesn't handle it."""
        try:
            return cls(value) if value is not None else None
        except ValueError:
            _LOGGER.debug("Unsupported unit %r", value)
            return None


class FanActivity(StrEnum):
    """What a fan accessory is doing. The values are the states Home Assistant shows."""

    PAUSED = "Paused"
    BLOWING = "Blowing"
    PULSING = "Pulsing"

    @classmethod
    def parse(cls, state: int | None) -> "FanActivity | None":
        """Return the activity for an API fan state, or None if it isn't one we know."""
        activities = {
            FanState.PAUSED: cls.PAUSED,
            FanState.BLOWING: cls.BLOWING,
            FanState.PULSING: cls.PULSING,
        }
        activity = activities.get(state) if state is not None else None
        if state is not None and activity is None:
            _LOGGER.debug("Unsupported fan state %r", state)
        return activity


def _as_utc(value: datetime | str | None) -> datetime | None:
    """Parse an API timestamp into an aware UTC datetime, or None if it can't be read."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        value = dt_util.parse_datetime(str(value))
        if value is None:
            return None
    return dt_util.as_utc(value)


def _valid_reading(channel: DeviceChannel) -> float | None:
    """Apply the one definition of a valid reading.

    The measurement and the alarm entities all depend on this. Unknown metadata (None) is
    not treated as a failure, only an explicit one is.
    """
    if (
        channel.value is None
        or channel.enabled is False
        or channel.probe_failed is True
        or channel.status == ChannelStatus.NO_PROBE
    ):
        return None
    return float(channel.value)


@dataclass(frozen=True)
class ThermoworksAlarm:
    """A channel's high or low alarm."""

    enabled: bool | None
    alarming: bool | None
    value: float | None
    units: Unit | None

    @classmethod
    def from_api_alarm(cls, alarm: Alarm | None) -> "ThermoworksAlarm | None":
        """Parse an API alarm, if the channel has one."""
        if alarm is None:
            return None
        return cls(
            enabled=alarm.enabled,
            alarming=alarm.alarming,
            value=alarm.value,
            units=Unit.parse(alarm.units),
        )


@dataclass(frozen=True)
class ThermoworksChannel:
    """A device channel, such as a probe or humidity sensor."""

    # Its device's
    device_key: str
    # Its device's, since channel entities attach to the device
    ha_device_identifier: str
    number: str
    # None when the API reports a unit this integration doesn't handle
    units: Unit | None
    # The measurement, or None when the channel reports it can't be trusted
    reading: float | None
    status: str | None = None
    label: str | None = None
    alarm_high: ThermoworksAlarm | None = None
    alarm_low: ThermoworksAlarm | None = None
    id: str | None = None
    enabled: bool | None = None
    probe_failed: bool | None = None
    alarming: bool | None = None
    last_telemetry_saved: datetime | None = None
    last_seen: datetime | None = None

    @classmethod
    def from_api_channel(
        cls, channel: DeviceChannel, device: "ThermoworksDevice"
    ) -> "ThermoworksChannel":
        """Parse an API channel of this device.

        A channel with no number or units is rejected.
        """
        missing = [name for name in ("number", "units") if getattr(channel, name) is None]
        if missing:
            raise MissingRequiredAttributeError(missing, cls)

        return cls(
            device_key=device.device_key,
            ha_device_identifier=device.ha_device_identifier,
            number=channel.number,
            units=Unit.parse(channel.units),
            reading=_valid_reading(channel),
            status=channel.status,
            label=channel.label,
            alarm_high=ThermoworksAlarm.from_api_alarm(channel.alarm_high),
            alarm_low=ThermoworksAlarm.from_api_alarm(channel.alarm_low),
            id=channel.id,
            enabled=channel.enabled,
            probe_failed=channel.probe_failed,
            alarming=channel.alarming,
            last_telemetry_saved=channel.last_telemetry_saved,
            last_seen=channel.last_seen,
        )

    def display_name(self) -> str:
        """Return the display name of the channel."""
        # {user given name} (Ch. {channel number})
        return f"{self.label or "unnamed channel"} (Ch. {self.number})"


@dataclass(frozen=True)
class ThermoworksFan:
    """A fan accessory, such as a Billows, connected to a gateway.

    The API reports the fan as a field on its gateway, and it's kept on the gateway here
    too, like channels. It's still its own device in Home Assistant, so it has its own
    `ha_device_identifier`, and its entities attach to it like any other device.
    """

    # The gateway's
    device_key: str
    # The identifier used to register it to HA, derived from the gateway's id since the API
    # does not give it an identifier of its own
    ha_device_identifier: str
    # The gateway's `ha_device_identifier`, the device it connects through
    gateway_ha_device_identifier: str
    name: str
    # The gateway's display units which determine the units for the fan
    display_units: Unit | None = None
    # Shown as reported, None when the fan doesn't say
    connected: bool | None = None
    activity: FanActivity | None = None
    set_temp: int | None = None
    fan_channel: str | None = None

    @classmethod
    def from_api_fan(cls, fan: Fan, gateway: "ThermoworksDevice") -> "ThermoworksFan":
        """Parse a fan from its gateway's API data."""
        return cls(
            device_key=gateway.device_key,
            ha_device_identifier=f"{gateway.ha_device_identifier}-fan",
            gateway_ha_device_identifier=gateway.ha_device_identifier,
            name=f"{gateway.label or gateway.display_name()} Fan",
            display_units=gateway.device_display_units,
            connected=fan.connected,
            activity=FanActivity.parse(fan.state),
            set_temp=fan.set_temp,
            fan_channel=fan.fan_channel,
        )


@dataclass(frozen=True)
class ThermoworksDevice:
    """A device on the account, with its channels keyed by channel number."""

    serial: str
    device_id: str | None = None
    label: str | None = None
    device_name: str | None = None
    device_display_units: Unit | None = None
    firmware: str | None = None
    battery: float | None = None
    battery_state: str | None = None
    signal_strength: float | None = None
    last_seen: datetime | None = None
    transmit_interval_in_seconds: int | None = None
    channels: Mapping[str, ThermoworksChannel] = field(default_factory=dict)
    fan: ThermoworksFan | None = None

    @classmethod
    def from_api_device(
        cls, device: Device, api_channels: Iterable[DeviceChannel] = ()
    ) -> "ThermoworksDevice":
        """Parse an API device, its channels and its fan.

        A device with no serial is rejected. A channel that can't be parsed is logged and
        left out, without dropping the device.
        """
        if device.serial is None:
            raise MissingRequiredAttributeError(["serial"], cls)

        gateway = cls(
            serial=device.serial,
            device_id=device.device_id,
            label=device.label,
            device_name=device.device_name,
            device_display_units=Unit.parse(device.device_display_units),
            firmware=device.firmware,
            battery=device.battery,
            battery_state=device.battery_state,
            # The library's Wi-Fi/gateway RSSI abstraction, so it works for every device type
            signal_strength=device.signal_strength,
            last_seen=_as_utc(device.last_seen),
            transmit_interval_in_seconds=device.transmit_interval_in_seconds,
        )

        # Channels and the fan take their identity from the device, so they're parsed after it
        channels: dict[str, ThermoworksChannel] = {}
        for api_channel in api_channels:
            try:
                channel = ThermoworksChannel.from_api_channel(api_channel, gateway)
            except MissingRequiredAttributeError as err:
                _LOGGER.error("Skipping channel %s (Ch. %s) for device %s, missing: %s",
                              api_channel.label or "unnamed channel", api_channel.number,
                              gateway.display_name(), ", ".join(err.missing_attributes))
                continue
            channels[channel.number] = channel

        fan = ThermoworksFan.from_api_fan(device.fan, gateway) if device.fan else None
        return replace(gateway, channels=channels, fan=fan)

    @property
    def device_key(self) -> str:
        """Return the key for this device in our data, preferring device_id but falling back to serial."""
        return self.device_id if self.device_id else self.serial

    @property
    def ha_device_identifier(self) -> str:
        """Return the identifier this device is registered under in Home Assistant."""
        return format_mac(self.device_key)

    def display_name(self) -> str:
        """Return the display name of the device."""
        # {user given name} ({rfx gateway, rfx meat, node, etc.} - {usually serial number})
        return f"{self.label or "unnamed device"} ({self.device_name or "unknown device"} - {self.device_key})"
