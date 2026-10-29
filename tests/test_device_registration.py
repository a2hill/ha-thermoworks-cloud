"""Observable results of registering ThermoWorks devices with Home Assistant."""

from dataclasses import replace
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from thermoworks_cloud.models import Fan

from custom_components.thermoworks_cloud.device import async_register_devices
from custom_components.thermoworks_cloud.models import ThermoworksDevice


class TestDeviceRegistration(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.hass = HomeAssistant(directory)
        self.entry = SimpleNamespace(
            entry_id="account-one",
            title="ThermoWorks Cloud",
            domain="thermoworks_cloud",
            disabled_by=None,
        )
        self.hass.config_entries = SimpleNamespace(
            async_get_entry=lambda entry_id: self.entry
        )
        await dr.async_load(self.hass)
        self.registry = dr.async_get(self.hass)

    async def test_registration_names_devices_and_links_fan_before_entities_exist(self):
        # Setup
        device = ThermoworksDevice(
            serial="RFX123", label="Patio BBQ", battery=90, fan=Fan(connected=True)
        )

        # Act
        async_register_devices(self.hass, self.entry, [device])

        # Assert
        parent = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "RFX123")}
        )
        fan = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "RFX123-fan")}
        )
        account = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "account-one")}
        )
        self.assertEqual(parent.name, "Patio BBQ")
        self.assertEqual(fan.name, "Patio BBQ Fan")
        self.assertEqual(fan.via_device_id, parent.id)
        self.assertEqual(account.name, "ThermoWorks Cloud")
        self.assertEqual(account.entry_type, dr.DeviceEntryType.SERVICE)

    async def test_refresh_changes_cloud_names_without_replacing_devices_or_user_names(
        self,
    ):
        # Setup
        device = ThermoworksDevice(
            serial="RFX123",
            label="Patio BBQ",
            battery=90,
            firmware="1.0",
            fan=Fan(connected=True),
        )
        async_register_devices(self.hass, self.entry, [device])
        parent = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "RFX123")}
        )
        fan = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "RFX123-fan")}
        )
        self.registry.async_update_device(parent.id, name_by_user="My Grill")

        # Act
        async_register_devices(
            self.hass, self.entry, [replace(device, label="Smoker", firmware="2.0")]
        )

        # Assert
        updated_parent = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "RFX123")}
        )
        updated_fan = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "RFX123-fan")}
        )
        self.assertEqual(updated_parent.id, parent.id)
        self.assertEqual(updated_parent.name, "Smoker")
        self.assertEqual(updated_parent.sw_version, "2.0")
        self.assertEqual(updated_parent.name_by_user, "My Grill")
        self.assertEqual(updated_fan.id, fan.id)
        self.assertEqual(updated_fan.name, "Smoker Fan")

    async def test_registration_preserves_names_for_devices_with_missing_metadata(self):
        # Setup
        no_battery_device = ThermoworksDevice(serial="NO_BATTERY", label="Freezer")
        missing_label_device = ThermoworksDevice(
            serial="MISSING_LABEL", label=None, battery=90
        )
        empty_label_device = ThermoworksDevice(
            serial="EMPTY_LABEL", label="", battery=90
        )
        devices = [no_battery_device, missing_label_device, empty_label_device]

        # Act
        async_register_devices(self.hass, self.entry, devices)
        async_register_devices(self.hass, self.entry, devices)

        # Assert
        no_battery_parent = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "NO_BATTERY")}
        )
        missing_label_parent = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "MISSING_LABEL")}
        )
        empty_label_parent = self.registry.async_get_device(
            identifiers={("thermoworks_cloud", "EMPTY_LABEL")}
        )
        self.assertIsNone(no_battery_parent.name)
        self.assertEqual(missing_label_parent.name, "ThermoWorks Cloud")
        self.assertEqual(empty_label_parent.name, "ThermoWorks Cloud")
