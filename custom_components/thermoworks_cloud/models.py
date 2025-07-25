"""Models for Thermoworks Cloud integration."""

from dataclasses import dataclass
from types import NoneType
from typing import Any, Optional, Protocol, Type, TypeGuard, Union, get_args, get_origin, get_type_hints
from thermoworks_cloud.models import Device, DeviceChannel

from .exceptions import MissingRequiredAttributeError


def is_optional_type(tp: Any) -> bool:
    """Returns True if the type is Optional[...]"""
    origin = get_origin(tp)
    args = get_args(tp)
    return origin is Union and NoneType in args


def has_required_attributes(obj: Any, protocol_cls: Type) -> bool:
    hints = get_type_hints(protocol_cls, include_extras=True)
    for attr, typ in hints.items():
        if not is_optional_type(typ):
            if not hasattr(obj, attr):
                return False
            if getattr(obj, attr) is None:
                return False
    return True


def get_missing_attributes(obj: Any, protocol_cls: Type) -> list[str]:
    hints = get_type_hints(protocol_cls, include_extras=True)
    missing_attributes = []
    for attr, typ in hints.items():
        if not is_optional_type(typ):
            if not hasattr(obj, attr):
                missing_attributes.append(attr)
            elif getattr(obj, attr) is None:
                missing_attributes.append(attr)
    return missing_attributes


@dataclass(frozen=True)
class BaseDevice(Protocol):
    serial: str
    device_id: Optional[str] = None
    label: Optional[str] = None
    device_name: Optional[str] = None
    firmware: Optional[str] = None
    battery: Optional[float] = None
    battery_state: Optional[str] = None
    wifi_strength: Optional[float] = None


@dataclass(frozen=True)
class ThermoworksDevice(BaseDevice):
    """Represents a Thermoworks device with required attributes for this integration."""

    @classmethod
    def is_thermoworks_device(cls, obj: Any) -> TypeGuard["ThermoworksDevice"]:
        """Return True if the object is a ThermoworksDevice."""
        return has_required_attributes(obj, ThermoworksDevice)

    @classmethod
    def from_api_device(cls, device: Device) -> "ThermoworksDevice":
        """Create a ThermoworksDevice from the API device object."""
        if not ThermoworksDevice.is_thermoworks_device(device):
            raise MissingRequiredAttributeError(
                get_missing_attributes(device, ThermoworksDevice), ThermoworksDevice)

        return cls(
            device_id=getattr(device, 'device_id', None),
            label=device.label,
            device_name=device.device_name,
            firmware=device.firmware,
            serial=device.serial,
            battery=device.battery,
            wifi_strength=device.wifi_strength
        )

    def get_identifier(self) -> str:
        """Return the device identifier, preferring device_id but falling back to serial."""
        return self.device_id if self.device_id else self.serial

    def display_name(self) -> str:
        """Return the display name of the device."""
        # {user given name} ({rfx gateway, rfx meat, node, etc.} - {usually serial number})
        return f"{self.label or "unnamed device"} ({self.device_name or "unknown device"} - {self.get_identifier()})"


class DeviceWithBattery(ThermoworksDevice):
    """Protocol for devices with battery information."""
    battery: float

    @classmethod
    def is_protocol_compliant(cls, obj: Any) -> TypeGuard["DeviceWithBattery"]:
        """Return True if the object implements DeviceWithBattery protocol."""
        return has_required_attributes(obj, DeviceWithBattery)


class DeviceWithWifi(ThermoworksDevice):
    """Protocol for devices with WiFi capability."""
    wifi_strength: float

    @classmethod
    def is_protocol_compliant(cls, obj: Any) -> TypeGuard["DeviceWithWifi"]:
        """Return True if the object implements DeviceWithWifi protocol."""
        return has_required_attributes(obj, DeviceWithWifi)


@dataclass
class ThermoworksChannel:
    """Represents a Thermoworks device channel with required properties for this integration."""

    number: str
    value: float
    units: str
    status: Optional[str]
    label: Optional[str]

    @classmethod
    def is_thermoworks_channel(cls, obj: Any) -> TypeGuard["ThermoworksChannel"]:
        """Return True if the device is a ThermoworksChannel."""
        return has_required_attributes(obj, ThermoworksChannel)

    @classmethod
    def from_api_channel(cls, channel: DeviceChannel) -> "ThermoworksChannel":
        """Create a ThermoworksChannel from the API channel object."""
        if not ThermoworksChannel.is_thermoworks_channel(channel):
            raise MissingRequiredAttributeError(
                get_missing_attributes(channel, ThermoworksChannel), ThermoworksChannel)

        # All required attributes exist, create the object
        return cls(
            number=channel.number,
            value=channel.value,
            units=channel.units,
            status=channel.status,
            label=channel.label
        )

    def display_name(self) -> str:
        """Return the display name of the channel."""
        # {user given name} (Ch. {channel number})
        return f"{self.label or "unnamed channel"} (Ch. {self.number})"
