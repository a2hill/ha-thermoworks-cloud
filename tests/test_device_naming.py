"""Characterize names and device grouping before changing registration ownership.

These tests exercise the platform setup functions and HA's actual registries and
state machine. Cloud calls and HA platform dispatch are replaced. Names
are resolved using the integration's checked-in English translations.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, current_entry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from thermoworks_cloud import ResourceNotFoundError
from thermoworks_cloud.models import Alarm, Fan

from custom_components import thermoworks_cloud as integration
from custom_components.thermoworks_cloud import (
    binary_sensor,
    number,
    sensor,
)
from custom_components.thermoworks_cloud import (
    coordinator as coordinator_module,
)
from custom_components.thermoworks_cloud.const import DOMAIN
from custom_components.thermoworks_cloud.models import (
    ThermoworksChannel,
    ThermoworksDevice,
)

TRANSLATIONS = json.loads(
    (Path(sensor.__file__).parent / "translations/en.json").read_text()
)["entity"]


def _device(**changes) -> ThermoworksDevice:
    """Provide all optional entities so naming checks cover every platform."""
    return replace(
        ThermoworksDevice(
            serial="RFX123",
            device_id="AABBCCDDEEFF",
            label="Patio BBQ",
            device_name="RFX Gateway",
            firmware="1.2.3",
            battery=90,
            signal_strength=-50,
            last_seen=datetime(2025, 1, 1, tzinfo=UTC),
            transmit_interval_in_seconds=30,
            device_display_units="F",
            fan=Fan(connected=True, state=1, set_temp=200),
        ),
        **changes,
    )


def _channel(**changes) -> ThermoworksChannel:
    return replace(
        ThermoworksChannel(
            number="1",
            value=100,
            units="F",
            status="ok",
            label="PORK Shoulder",
            alarm_high=Alarm(enabled=True, alarming=False, value=200, units="F"),
            alarm_low=Alarm(enabled=True, alarming=False, value=50, units="F"),
        ),
        **changes,
    )


class NamingHarness:
    """Run integration setup, first refresh, and HA entity/device registration."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entries = {}
        self.platforms = []
        # Registry operations need a config-entry lookup, not a running flow manager.
        hass.config_entries = SimpleNamespace(
            async_get_entry=self.entries.get,
            async_forward_entry_setups=self.load_platforms,
        )

    async def add_account(
        self, devices, channels=(), *, entry_id="account-one", title="ThermoWorks Cloud"
    ):
        entry = ConfigEntry(
            domain=DOMAIN,
            title=title,
            entry_id=entry_id,
            data={"email": "test@example.com", "password": "test-password"},
            options={},
            version=1,
            minor_version=1,
            source="user",
            state=ConfigEntryState.SETUP_IN_PROGRESS,
            unique_id=entry_id,
            discovery_keys=MappingProxyType({}),
        )
        self.entries[entry.entry_id] = entry
        await self.setup_account(entry, devices, channels)
        return entry

    async def setup_account(self, entry, devices, channels) -> None:
        async def get_channel(*, device_serial, channel):
            for value in channels:
                if value.number == channel:
                    return value
            raise ResourceNotFoundError("No more channels")

        api = SimpleNamespace(
            get_user=AsyncMock(return_value=SimpleNamespace(account_id=entry.entry_id)),
            get_devices=AsyncMock(return_value=devices),
            get_device_channel=AsyncMock(side_effect=get_channel),
        )
        with (
            patch.object(
                coordinator_module, "async_get_clientsession", return_value=Mock()
            ),
            patch.object(
                coordinator_module,
                "AuthFactory",
                return_value=SimpleNamespace(
                    build_auth=AsyncMock(return_value=object())
                ),
            ),
            patch.object(coordinator_module, "ThermoworksCloud", return_value=api),
        ):
            token = current_entry.set(entry)
            try:
                assert await integration.async_setup_entry(self.hass, entry)
            finally:
                current_entry.reset(token)

    async def reload_account(self, entry, devices, channels=()) -> None:
        await self.unload_platforms()
        runtime = self.hass.data[DOMAIN][entry.entry_id]
        runtime.cancel_update_listener()
        await runtime.coordinator.async_shutdown()
        await self.setup_account(entry, devices, channels)

    async def load_platforms(self, entry, domains) -> None:
        assert set(domains) == {"sensor", "binary_sensor", "number"}
        # Fix platform order for naming assertions. Startup-order races are a
        # separate concern: on this baseline the battery registers the parent.
        for module in (sensor, binary_sensor, number):
            domain = module.__name__.rsplit(".", 1)[1]
            platform = EntityPlatform(
                hass=self.hass,
                logger=logging.getLogger(__name__),
                domain=domain,
                platform_name=DOMAIN,
                platform=module,
                scan_interval=timedelta(seconds=30),
                entity_namespace=None,
            )
            platform.config_entry = entry
            platform.platform_translations = {
                f"component.{DOMAIN}.entity.{domain}.{key}.name": value["name"]
                for key, value in TRANSLATIONS[domain].items()
            }
            platform.object_id_platform_translations = platform.platform_translations
            entities = []
            await module.async_setup_entry(self.hass, entry, entities.extend)
            await platform.async_add_entities(entities)
            self.platforms.append(platform)

    async def unload_platforms(self) -> None:
        for platform in self.platforms:
            await platform.async_reset()
        self.platforms.clear()
        await self.hass.async_block_till_done()

    def names(self):
        return {
            state.entity_id: state.attributes["friendly_name"]
            for state in self.hass.states.async_all()
        }

    def device(self, identifier):
        device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, identifier)}
        )
        assert device is not None
        return device


@asynccontextmanager
async def _harness(config_dir):
    harness = NamingHarness(HomeAssistant(str(config_dir)))
    await dr.async_load(harness.hass)
    await er.async_load(harness.hass)
    try:
        yield harness
    finally:
        await harness.unload_platforms()
        for runtime in harness.hass.data.get(DOMAIN, {}).values():
            runtime.cancel_update_listener()
            await runtime.coordinator.async_shutdown()


def test_all_entity_names_ids_and_device_grouping(tmp_path) -> None:
    """Preserve visible English names, unique ids, and the three device groups."""

    async def check():
        async with _harness(tmp_path) as env:
            await env.add_account(
                [_device()],
                [
                    _channel(),
                    _channel(
                        number="2",
                        units="H",
                        label="DRY Box",
                        alarm_high=None,
                        alarm_low=None,
                    ),
                ],
            )
            assert env.names() == {
                "sensor.aabbccddeeff_battery": "Patio BBQ Battery",
                "sensor.aabbccddeeff_signal": "Patio BBQ Signal Strength",
                "sensor.aabbccddeeff_last_seen": "Patio BBQ Last Seen",
                "sensor.aabbccddeeff_transmit_interval": "Patio BBQ Transmit Interval",
                "sensor.aabbccddeeff_fan_state": "Patio BBQ Fan State",
                "sensor.aabbccddeeff_fan_set_temperature": "Patio BBQ Fan Set Temperature",
                "sensor.aabbccddeeff_ch_1_temperature": "Patio BBQ Pork shoulder (ch. 1)",
                "sensor.aabbccddeeff_ch_1_high_alarm_threshold": "Patio BBQ PORK Shoulder (Ch. 1) High Alarm Threshold",
                "sensor.aabbccddeeff_ch_1_low_alarm_threshold": "Patio BBQ PORK Shoulder (Ch. 1) Low Alarm Threshold",
                "sensor.aabbccddeeff_ch_2_humidity": "Patio BBQ Dry box (ch. 2)",
                "binary_sensor.aabbccddeeff_fan_connected": "Patio BBQ Fan Connected",
                "binary_sensor.aabbccddeeff_ch_1_high_alarm": "Patio BBQ PORK Shoulder (Ch. 1) High Alarm",
                "binary_sensor.aabbccddeeff_ch_1_low_alarm": "Patio BBQ PORK Shoulder (Ch. 1) Low Alarm",
                "number.thermoworks_cloud_scan_interval": "ThermoWorks Cloud Scan interval",
            }
            thermometer = env.device("aa:bb:cc:dd:ee:ff")
            fan = env.device("aa:bb:cc:dd:ee:ff-fan")
            account = env.device("account-one")
            assert len(dr.async_get(env.hass).devices) == 3
            assert (thermometer.name, thermometer.model, thermometer.manufacturer) == (
                "Patio BBQ",
                "RFX Gateway",
                "ThermoWorks",
            )
            assert (fan.name, fan.via_device_id) == ("Patio BBQ Fan", thermometer.id)
            assert (account.name, account.entry_type) == (
                "ThermoWorks Cloud",
                dr.DeviceEntryType.SERVICE,
            )
            registry = er.async_get(env.hass)
            expected_suffixes = {
                "sensor.aabbccddeeff_battery": "",
                "sensor.aabbccddeeff_signal": "-signal",
                "sensor.aabbccddeeff_last_seen": "-last-seen",
                "sensor.aabbccddeeff_transmit_interval": "-transmit-interval",
                "sensor.aabbccddeeff_fan_state": "-fan-state",
                "sensor.aabbccddeeff_fan_set_temperature": "-fan-set-temperature",
                "sensor.aabbccddeeff_ch_1_temperature": "-1",
                "sensor.aabbccddeeff_ch_2_humidity": "-2",
                "sensor.aabbccddeeff_ch_1_high_alarm_threshold": "-1-high-alarm-threshold",
                "sensor.aabbccddeeff_ch_1_low_alarm_threshold": "-1-low-alarm-threshold",
                "binary_sensor.aabbccddeeff_fan_connected": "-fan-connected",
                "binary_sensor.aabbccddeeff_ch_1_high_alarm": "-1-high-alarm",
                "binary_sensor.aabbccddeeff_ch_1_low_alarm": "-1-low-alarm",
            }
            for entity_id, suffix in expected_suffixes.items():
                entity = registry.async_get(entity_id)
                assert (
                    entity.unique_id == f"thermoworks_cloud-aa:bb:cc:dd:ee:ff{suffix}"
                )
                assert entity.device_id == (
                    fan.id if "_fan_" in entity_id else thermometer.id
                )
            control = registry.async_get("number.thermoworks_cloud_scan_interval")
            assert (control.unique_id, control.device_id) == (
                "account-one_scan_interval",
                account.id,
            )

    asyncio.run(check())


@pytest.mark.parametrize(
    "device_id, identifier, entity_prefix",
    [
        (None, "RFX123", "rfx123"),
        ("AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff", "aabbccddeeff"),
        ("device-123", "device-123", "device_123"),
    ],
)
def test_device_id_precedence_and_serial_fallback(
    tmp_path, device_id, identifier, entity_prefix
) -> None:
    """Formatting and ID precedence must not create replacement devices/entities."""

    async def check():
        async with _harness(tmp_path) as env:
            await env.add_account([_device(device_id=device_id)], [_channel()])
            thermometer = env.device(identifier)
            fan = env.device(f"{identifier}-fan")
            assert thermometer.serial_number == "RFX123"
            assert fan.via_device_id == thermometer.id
            assert (
                er.async_get(env.hass)
                .async_get(f"sensor.{entity_prefix}_battery")
                .unique_id
                == f"thermoworks_cloud-{identifier}"
            )
            assert (
                env.names()[f"sensor.{entity_prefix}_ch_1_temperature"]
                == "Patio BBQ Pork shoulder (ch. 1)"
            )

    asyncio.run(check())


@pytest.mark.parametrize("label", [None, ""])
@pytest.mark.parametrize(
    "device_name, model_name",
    [("RFX Gateway", "RFX Gateway"), (None, "unknown device")],
)
def test_unlabelled_device_and_fan_names(
    tmp_path, label, device_name, model_name
) -> None:
    """HA's account-title fallback and our fan display-name fallback differ."""

    async def check():
        async with _harness(tmp_path) as env:
            await env.add_account([_device(label=label, device_name=device_name)])
            assert env.device("aa:bb:cc:dd:ee:ff").name == "ThermoWorks Cloud"
            fan_name = f"unnamed device ({model_name} - AABBCCDDEEFF) Fan"
            assert env.device("aa:bb:cc:dd:ee:ff-fan").name == fan_name
            assert (
                env.names()["sensor.aabbccddeeff_battery"]
                == "ThermoWorks Cloud Battery"
            )
            assert env.names()["sensor.aabbccddeeff_fan_state"] == f"{fan_name} State"

    asyncio.run(check())


@pytest.mark.parametrize(
    "label, reading_name, alarm_name",
    [
        (None, "Unnamed channel (ch. 1)", "unnamed channel (Ch. 1)"),
        ("", "Unnamed channel (ch. 1)", "unnamed channel (Ch. 1)"),
        ("PORK Shoulder", "Pork shoulder (ch. 1)", "PORK Shoulder (Ch. 1)"),
    ],
)
def test_channel_name_fallbacks_and_capitalization(
    tmp_path, label, reading_name, alarm_name
) -> None:
    """Reading names use capitalize(); alarms preserve the original label case."""

    async def check():
        async with _harness(tmp_path) as env:
            await env.add_account([_device()], [_channel(label=label)])
            names = env.names()
            assert (
                names["sensor.aabbccddeeff_ch_1_temperature"]
                == f"Patio BBQ {reading_name}"
            )
            assert (
                names["sensor.aabbccddeeff_ch_1_high_alarm_threshold"]
                == f"Patio BBQ {alarm_name} High Alarm Threshold"
            )
            assert (
                names["sensor.aabbccddeeff_ch_1_low_alarm_threshold"]
                == f"Patio BBQ {alarm_name} Low Alarm Threshold"
            )
            assert (
                names["binary_sensor.aabbccddeeff_ch_1_high_alarm"]
                == f"Patio BBQ {alarm_name} High Alarm"
            )
            assert (
                names["binary_sensor.aabbccddeeff_ch_1_low_alarm"]
                == f"Patio BBQ {alarm_name} Low Alarm"
            )

    asyncio.run(check())


def test_device_without_battery_does_not_acquire_its_cloud_label(tmp_path) -> None:
    """Pin the current limitation: identifier-only entities don't supply a name."""

    async def check():
        async with _harness(tmp_path) as env:
            await env.add_account([_device(battery=None, fan=None)], [_channel()])
            assert env.device("aa:bb:cc:dd:ee:ff").name is None
            assert env.names()["sensor.aabbccddeeff_signal"] == "Signal Strength"
            assert (
                env.names()["sensor.aabbccddeeff_ch_1_temperature"]
                == "Pork shoulder (ch. 1)"
            )

    asyncio.run(check())


def test_reload_updates_cloud_names_without_replacing_entities(tmp_path) -> None:
    """A changed cloud label affects display names while IDs stay stable."""

    async def check():
        async with _harness(tmp_path) as env:
            entry = await env.add_account([_device()], [_channel()])
            original_entities = {
                item.entity_id: (item.unique_id, item.device_id)
                for item in er.async_get(env.hass).entities.values()
            }
            await env.reload_account(
                entry, [_device(label="Smoker")], [_channel(label="BRISKET")]
            )
            assert env.names()["sensor.aabbccddeeff_battery"] == "Smoker Battery"
            assert env.names()["sensor.aabbccddeeff_fan_state"] == "Smoker Fan State"
            assert (
                env.names()["sensor.aabbccddeeff_ch_1_temperature"]
                == "Smoker Brisket (ch. 1)"
            )
            assert {
                item.entity_id: (item.unique_id, item.device_id)
                for item in er.async_get(env.hass).entities.values()
            } == original_entities

    asyncio.run(check())


def test_user_device_entity_names_and_entity_ids_survive_reload(tmp_path) -> None:
    """Cloud metadata and suggested IDs must not overwrite user customizations."""

    async def check():
        async with _harness(tmp_path) as env:
            entry = await env.add_account([_device()], [_channel()])
            registry = er.async_get(env.hass)
            dr.async_get(env.hass).async_update_device(
                env.device("aa:bb:cc:dd:ee:ff").id, name_by_user="My Grill"
            )
            registry.async_update_entity(
                "sensor.aabbccddeeff_ch_1_temperature",
                name="Meat Probe",
                new_entity_id="sensor.meat_probe",
            )
            await env.hass.async_block_till_done()
            assert env.names()["sensor.aabbccddeeff_battery"] == "My Grill Battery"
            assert env.names()["sensor.meat_probe"] == "Meat Probe"
            await env.reload_account(
                entry, [_device(label="Changed in cloud")], [_channel()]
            )
            assert env.names()["sensor.aabbccddeeff_battery"] == "My Grill Battery"
            assert env.names()["sensor.meat_probe"] == "Meat Probe"
            assert "sensor.aabbccddeeff_ch_1_temperature" not in env.names()

    asyncio.run(check())


@pytest.mark.parametrize(
    "second_title, second_id",
    [
        ("ThermoWorks Cloud", "thermoworks_cloud_scan_interval_2"),
        ("ETI Cloud", "eti_cloud_scan_interval"),
    ],
)
def test_scan_interval_account_names_and_collisions(
    tmp_path, second_title, second_id
) -> None:
    """Each account has its own named service device, even with identical titles."""

    async def check():
        async with _harness(tmp_path) as env:
            await env.add_account([])
            await env.add_account([], entry_id="account-two", title=second_title)
            assert env.names() == {
                "number.thermoworks_cloud_scan_interval": "ThermoWorks Cloud Scan interval",
                f"number.{second_id}": f"{second_title} Scan interval",
            }
            control = er.async_get(env.hass).async_get(f"number.{second_id}")
            assert control.unique_id == "account-two_scan_interval"
            assert control.device_id == env.device("account-two").id

    asyncio.run(check())
