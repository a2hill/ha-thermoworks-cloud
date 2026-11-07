"""Domain types for the Thermoworks Cloud integration.

The coordinator parses each API response into these types once per update. They describe
devices and channels as the API reports them, and know nothing about Home Assistant entities.

- A device needs a serial and a channel needs a number and units. Anything without them is
  rejected here, so nothing downstream has to check for them again.
- Everything else stays optional because devices report different fields. Each entity decides
  what it needs from these types in its own `parse` method (see `entity.py`).
- A field is kept raw only if something shows it as reported, like a channel's `status`.
  Where there's a rule over a value, the rule runs on construction and only its result is
  stored: a channel keeps `reading` but not the raw value. That way there's no path around
  the rule, and it can't drift between the entities that depend on it.
"""

from collections.abc import Iterable, Mapping
from dataclasses import InitVar, dataclass, field, replace
from datetime import datetime
from typing import Optional

from homeassistant.helpers.device_registry import format_mac
from homeassistant.util import dt as dt_util
from thermoworks_cloud.models import Alarm, ChannelStatus, Device, DeviceChannel, Fan

from .exceptions import MissingRequiredAttributeError


def _as_utc(value: datetime | str | None) -> datetime | None:
    """Parse an API timestamp into an aware UTC datetime, or None if it can't be read."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        value = dt_util.parse_datetime(str(value))
        if value is None:
            return None
    return dt_util.as_utc(value)


@dataclass(frozen=True)
class ThermoworksChannel:
    """A device channel, such as a probe or humidity sensor."""

    number: str
    units: str
    # The raw measurement. It's only used to compute `reading` and isn't stored.
    value: InitVar[Optional[float]] = None
    status: Optional[str] = None
    label: Optional[str] = None
    alarm_high: Optional[Alarm] = None
    alarm_low: Optional[Alarm] = None
    id: Optional[str] = None
    enabled: Optional[bool] = None
    probe_failed: Optional[bool] = None
    alarming: Optional[bool] = None
    last_telemetry_saved: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    # The measurement, or None when the channel reports it can't be trusted
    reading: Optional[float] = field(init=False, default=None)

    def __post_init__(self, value: Optional[float]) -> None:
        """Apply the one definition of a valid reading.

        The measurement and the alarm entities all depend on this. Unknown metadata
        (None) is not treated as a failure, only an explicit one is.
        """
        valid = (
            value is not None
            and self.enabled is not False
            and self.probe_failed is not True
            and self.status != ChannelStatus.NO_PROBE
        )
        # Frozen, so set through object like dataclasses does
        object.__setattr__(self, "reading", float(value) if valid else None)

    @classmethod
    def from_api_channel(cls, channel: DeviceChannel) -> "ThermoworksChannel":
        """Parse an API channel, rejecting one that has no number or units."""
        missing = [name for name in ("number", "units") if getattr(channel, name) is None]
        if missing:
            raise MissingRequiredAttributeError(missing, cls)

        return cls(
            number=channel.number,
            value=channel.value,
            units=channel.units,
            status=channel.status,
            label=channel.label,
            alarm_high=channel.alarm_high,
            alarm_low=channel.alarm_low,
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
    registry identifier, and its entities attach to it like any other device.
    """

    # Derived from the gateway's, since the API gives the fan no identifier of its own
    registry_identifier: str
    # The gateway it's connected through
    gateway_registry_identifier: str
    name: str
    # The gateway's display units, which the set temperature is in
    display_units: Optional[str] = None
    # Shown as reported, None when the fan doesn't say
    connected: Optional[bool] = None
    state_name: Optional[str] = None
    set_temp: Optional[int] = None
    fan_channel: Optional[str] = None

    @classmethod
    def from_api_fan(cls, fan: Fan, gateway: "ThermoworksDevice") -> "ThermoworksFan":
        """Parse a fan from its gateway's API data."""
        return cls(
            registry_identifier=f"{gateway.registry_identifier}-fan",
            gateway_registry_identifier=gateway.registry_identifier,
            name=f"{gateway.label or gateway.display_name()} Fan",
            display_units=gateway.device_display_units,
            connected=fan.connected,
            state_name=fan.state_name,
            set_temp=fan.set_temp,
            fan_channel=fan.fan_channel,
        )


@dataclass(frozen=True)
class ThermoworksDevice:
    """A device on the account, with its channels keyed by channel number."""

    serial: str
    device_id: Optional[str] = None
    label: Optional[str] = None
    device_name: Optional[str] = None
    device_display_units: Optional[str] = None
    firmware: Optional[str] = None
    battery: Optional[float] = None
    battery_state: Optional[str] = None
    signal_strength: Optional[float] = None
    last_seen: Optional[datetime] = None
    transmit_interval_in_seconds: Optional[int] = None
    channels: Mapping[str, ThermoworksChannel] = field(default_factory=dict)
    fan: Optional[ThermoworksFan] = None

    @classmethod
    def from_api_device(
        cls, device: Device, channels: Iterable[ThermoworksChannel] = ()
    ) -> "ThermoworksDevice":
        """Parse an API device, its fan and its already parsed channels.

        A device with no serial is rejected.
        """
        if device.serial is None:
            raise MissingRequiredAttributeError(["serial"], cls)

        gateway = cls(
            serial=device.serial,
            device_id=device.device_id,
            label=device.label,
            device_name=device.device_name,
            device_display_units=device.device_display_units,
            firmware=device.firmware,
            battery=device.battery,
            battery_state=device.battery_state,
            # The library's Wi-Fi/gateway RSSI abstraction, so it works for every device type
            signal_strength=device.signal_strength,
            last_seen=_as_utc(device.last_seen),
            transmit_interval_in_seconds=device.transmit_interval_in_seconds,
            channels={channel.number: channel for channel in channels},
        )
        if device.fan is None:
            return gateway
        # The fan's identity and name come from its gateway, so it's parsed second
        return replace(gateway, fan=ThermoworksFan.from_api_fan(device.fan, gateway))

    def get_identifier(self) -> str:
        """Return the device identifier, preferring device_id but falling back to serial."""
        return self.device_id if self.device_id else self.serial

    @property
    def registry_identifier(self) -> str:
        """Return the identifier this device is registered under in Home Assistant."""
        return format_mac(self.get_identifier())

    def display_name(self) -> str:
        """Return the display name of the device."""
        # {user given name} ({rfx gateway, rfx meat, node, etc.} - {usually serial number})
        return f"{self.label or "unnamed device"} ({self.device_name or "unknown device"} - {self.get_identifier()})"
