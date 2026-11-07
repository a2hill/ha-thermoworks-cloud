"""Domain types for the Thermoworks Cloud integration.

The coordinator parses each API response into these types once per update. They describe
devices and channels as the API reports them, and know nothing about Home Assistant entities.

- A device needs a serial and a channel needs a number and units. Anything without them is
  rejected here, so nothing downstream has to check for them again.
- Everything else stays optional because devices report different fields. Each entity decides
  what it needs from these types in its own `parse` method (see `entity.py`).
- Values more than one entity depends on, such as whether a channel has a valid reading, are
  defined once here as cached properties so the rule can't drift between entities. A new
  object is built on every update, so a cached value never outlives the data it came from.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from typing import Optional

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
    value: Optional[float] = None
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

    @classmethod
    def from_api_channel(cls, channel: DeviceChannel) -> "ThermoworksChannel":
        """Parse an API channel, rejecting one that has no number or units."""
        missing = [name for name in ("number", "units") if getattr(channel, name) is None]
        if missing:
            raise MissingRequiredAttributeError(missing, cls)

        return cls(
            number=channel.number,
            units=channel.units,
            value=channel.value,
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

    @cached_property
    def reading(self) -> float | None:
        """Return the measurement, or None when the channel reports it can't be trusted.

        This is the one definition of a valid reading. The measurement and the alarm
        entities all use it. Unknown metadata (None) is not treated as a failure, only an
        explicit one is.
        """
        if (
            self.value is None
            or self.enabled is False
            or self.probe_failed is True
            or self.status == ChannelStatus.NO_PROBE
        ):
            return None
        return float(self.value)

    def display_name(self) -> str:
        """Return the display name of the channel."""
        # {user given name} (Ch. {channel number})
        return f"{self.label or "unnamed channel"} (Ch. {self.number})"


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
    fan: Optional[Fan] = None
    last_seen: Optional[datetime] = None
    transmit_interval_in_seconds: Optional[int] = None
    channels: Mapping[str, ThermoworksChannel] = field(default_factory=dict)

    @classmethod
    def from_api_device(
        cls, device: Device, channels: Iterable[ThermoworksChannel] = ()
    ) -> "ThermoworksDevice":
        """Parse an API device and its already parsed channels, rejecting one with no serial."""
        if device.serial is None:
            raise MissingRequiredAttributeError(["serial"], cls)

        return cls(
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
            fan=device.fan,
            last_seen=_as_utc(device.last_seen),
            transmit_interval_in_seconds=device.transmit_interval_in_seconds,
            channels={channel.number: channel for channel in channels},
        )

    @cached_property
    def connected_fan(self) -> Fan | None:
        """Return the fan accessory only while it's connected.

        A disconnected fan still reports its last state and set temperature, which
        shouldn't be shown as current.
        """
        if self.fan is None or self.fan.connected is not True:
            return None
        return self.fan

    def get_identifier(self) -> str:
        """Return the device identifier, preferring device_id but falling back to serial."""
        return self.device_id if self.device_id else self.serial

    def display_name(self) -> str:
        """Return the display name of the device."""
        # {user given name} ({rfx gateway, rfx meat, node, etc.} - {usually serial number})
        return f"{self.label or "unnamed device"} ({self.device_name or "unknown device"} - {self.get_identifier()})"
