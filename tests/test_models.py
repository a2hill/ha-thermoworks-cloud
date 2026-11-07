"""Tests for ThermoWorks integration models."""

from datetime import datetime, timezone

import pytest
from thermoworks_cloud.models import Alarm, Device, DeviceChannel, Fan

from custom_components.thermoworks_cloud.exceptions import MissingRequiredAttributeError
from custom_components.thermoworks_cloud.models import (
    ThermoworksChannel,
    ThermoworksDevice,
)


def test_from_api_device_preserves_normalized_signal_strength() -> None:
    """The integration copies the library's Wi-Fi/gateway RSSI abstraction."""
    api_device = Device(serial="RFX123", gateway_rssi=-67)

    device = ThermoworksDevice.from_api_device(api_device)

    assert device.signal_strength == -67


def test_from_api_device_preserves_fan() -> None:
    """The integration copies the library's fan accessory data."""
    fan = Fan(connected=True, fan_channel="1", set_temp=150, state=1)
    api_device = Device(serial="RFX123", device_display_units="F", fan=fan)

    device = ThermoworksDevice.from_api_device(api_device)

    assert device.fan == fan
    assert device.connected_fan == fan
    assert device.device_display_units == "F"


def test_disconnected_fan_is_not_a_connected_fan() -> None:
    """A disconnected fan's last values aren't presented as current."""
    device = ThermoworksDevice(serial="RFX123", fan=Fan(connected=False, state=1))

    assert device.connected_fan is None


def test_from_api_device_keys_channels_by_number() -> None:
    """Channels are looked up by number, so entities don't search for them."""
    channel = ThermoworksChannel(number="2", units="F", value=100)

    device = ThermoworksDevice.from_api_device(Device(serial="RFX123"), [channel])

    assert device.channels == {"2": channel}


def test_from_api_device_parses_last_seen_as_utc() -> None:
    """Timestamps are parsed once, at the boundary."""
    device = ThermoworksDevice.from_api_device(
        Device(serial="RFX123", last_seen="2026-01-02T03:04:05Z")
    )

    assert device.last_seen == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_device_without_serial_is_rejected() -> None:
    """A device with no serial can't be identified, so it isn't parsed."""
    with pytest.raises(MissingRequiredAttributeError):
        ThermoworksDevice.from_api_device(Device(label="No serial"))


def test_from_api_channel_preserves_alarms() -> None:
    """The integration copies channel alarm data from the library."""
    high_alarm = Alarm(enabled=True, alarming=False, value=175, units="F")
    low_alarm = Alarm(enabled=True, alarming=True, value=125, units="F")
    api_channel = DeviceChannel(
        number="1",
        value=150,
        units="F",
        status="ok",
        label="Air",
        alarm_high=high_alarm,
        alarm_low=low_alarm,
    )

    channel = ThermoworksChannel.from_api_channel(api_channel)

    assert channel.alarm_high == high_alarm
    assert channel.alarm_low == low_alarm


@pytest.mark.parametrize("missing", ["number", "units"])
def test_channel_without_number_or_units_is_rejected(missing: str) -> None:
    """A channel that can't be identified or interpreted isn't parsed."""
    api_channel = DeviceChannel(**{"number": "1", "units": "F", "value": 150, missing: None})

    with pytest.raises(MissingRequiredAttributeError):
        ThermoworksChannel.from_api_channel(api_channel)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"value": None}, id="no-value"),
        pytest.param({"enabled": False}, id="disabled"),
        pytest.param({"probe_failed": True}, id="probe-failed"),
        pytest.param({"status": "NO PROBE"}, id="no-probe"),
    ],
)
def test_channel_reading_rejects_explicit_failures(overrides: dict) -> None:
    """A channel that reports a failure has no reading."""
    channel = ThermoworksChannel(number="1", units="F", **{"value": 150, **overrides})

    assert channel.reading is None


def test_channel_reading_accepts_unknown_metadata() -> None:
    """Missing metadata isn't treated as a failure."""
    channel = ThermoworksChannel(number="1", units="F", value=150)

    assert channel.reading == 150.0
