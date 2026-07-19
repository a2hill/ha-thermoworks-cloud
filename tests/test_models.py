"""Tests for ThermoWorks integration models."""

from types import SimpleNamespace

from custom_components.thermoworks_cloud.models import (
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
