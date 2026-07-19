"""Tests for ThermoWorks integration models."""

from types import SimpleNamespace

from thermoworks_cloud.models import Fan

from custom_components.thermoworks_cloud.models import (
    DeviceWithFan,
    DeviceWithSignalStrength,
    ThermoworksDevice,
)


def test_signal_strength_capability_uses_normalized_property() -> None:
    """Devices with non-Wi-Fi signal strength expose a signal sensor."""
    device = ThermoworksDevice(serial="RFX123", signal_strength=-67)

    assert DeviceWithSignalStrength.is_protocol_compliant(device)


def test_from_api_device_preserves_normalized_signal_strength() -> None:
    """The integration copies the library's Wi-Fi/gateway RSSI abstraction."""
    api_device = SimpleNamespace(
        device_id=None,
        label="RFX Meat",
        device_name="RFX Meat",
        firmware="1.2.3",
        serial="RFX123",
        battery=82,
        wifi_strength=None,
        signal_strength=-67,
        last_seen=None,
        transmit_interval_in_seconds=None,
    )

    device = ThermoworksDevice.from_api_device(api_device)

    assert device.signal_strength == -67
    assert device.wifi_strength is None
    assert DeviceWithSignalStrength.is_protocol_compliant(device)


def test_fan_capability_uses_fan_property() -> None:
    """Devices with fan accessory data expose fan accessory entities."""
    fan = Fan(connected=True, fan_channel="1", set_temp=150, state=1)
    device = ThermoworksDevice(serial="RFX123", fan=fan)

    assert DeviceWithFan.is_protocol_compliant(device)


def test_from_api_device_preserves_fan() -> None:
    """The integration copies the library's fan accessory data."""
    fan = Fan(connected=True, fan_channel="1", set_temp=150, state=1)
    api_device = SimpleNamespace(
        device_id=None,
        label="RFX Gateway",
        device_name="RFX Gateway",
        device_display_units="F",
        firmware="1.2.3",
        serial="RFX123",
        battery=82,
        wifi_strength=None,
        signal_strength=-67,
        fan=fan,
        last_seen=None,
        transmit_interval_in_seconds=None,
    )

    device = ThermoworksDevice.from_api_device(api_device)

    assert device.fan == fan
    assert device.fan.state_name == "Blowing"
    assert device.device_display_units == "F"
    assert DeviceWithFan.is_protocol_compliant(device)
