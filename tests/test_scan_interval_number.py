"""Tests for the ThermoWorks Cloud scan interval number entity."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.components.number import NumberDeviceClass
from homeassistant.const import CONF_SCAN_INTERVAL, EntityCategory, UnitOfTime
from homeassistant.helpers.device_registry import DeviceEntryType

from custom_components.thermoworks_cloud.const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
)
from custom_components.thermoworks_cloud.config_flow import OptionsFlowHandler
from custom_components.thermoworks_cloud.number import ScanIntervalNumber


def _build_entity(options: dict | None = None):
    """Return ``(entity, updates)`` with fake hass / config entry wiring.

    ``updates`` collects the options dicts handed to ``async_update_entry`` so a
    test can assert exactly what would be persisted to the config entry.
    """
    updates: list[dict] = []
    config_entry = SimpleNamespace(
        entry_id="entry123",
        title="ThermoWorks Cloud",
        options=dict(options or {}),
    )

    def async_update_entry(entry, *, options):
        updates.append(options)
        entry.options = options

    entity = ScanIntervalNumber(config_entry)
    entity.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=async_update_entry)
    )
    return entity, updates


def test_static_attributes() -> None:
    """Entity advertises bounds, unit, config category and a stable unique id."""
    entity, _ = _build_entity()

    assert entity.native_min_value == MIN_SCAN_INTERVAL_SECONDS
    assert entity.native_max_value == MAX_SCAN_INTERVAL_SECONDS
    assert entity.native_unit_of_measurement == UnitOfTime.SECONDS
    assert entity.device_class == NumberDeviceClass.DURATION
    assert entity.entity_category == EntityCategory.CONFIG
    assert entity.unique_id == "entry123_scan_interval"


def test_bound_to_config_entry_service_device() -> None:
    """The entity hangs off a service device that stands for the config entry,
    not off any individual thermometer (no manufacturer / model)."""
    entity, _ = _build_entity()

    device_info = entity.device_info
    assert device_info["identifiers"] == {(DOMAIN, "entry123")}
    assert device_info["entry_type"] == DeviceEntryType.SERVICE
    assert device_info["name"] == "ThermoWorks Cloud"
    assert "manufacturer" not in device_info
    assert "model" not in device_info


def test_native_value_defaults_when_option_unset() -> None:
    """With no stored option the entity reports the package default."""
    entity, _ = _build_entity()
    assert entity.native_value == DEFAULT_SCAN_INTERVAL_SECONDS


def test_native_value_reads_from_options_store() -> None:
    """The options store is the source of truth for the current value."""
    entity, _ = _build_entity({CONF_SCAN_INTERVAL: 45})
    assert entity.native_value == 45


def test_set_value_persists_to_options_and_reads_back() -> None:
    """Setting the value writes CONF_SCAN_INTERVAL and is then reflected."""
    entity, updates = _build_entity({CONF_SCAN_INTERVAL: 1800})

    asyncio.run(entity.async_set_native_value(5))

    assert updates == [{CONF_SCAN_INTERVAL: 5}]
    assert entity.native_value == 5


def test_set_value_coerces_to_int() -> None:
    """The number platform hands us a float; we persist whole seconds."""
    entity, updates = _build_entity()

    asyncio.run(entity.async_set_native_value(12.0))

    assert updates == [{CONF_SCAN_INTERVAL: 12}]
    assert isinstance(updates[0][CONF_SCAN_INTERVAL], int)


def test_set_value_rounds_rather_than_truncates() -> None:
    """A fractional value rounds to the nearest second instead of truncating."""
    entity, updates = _build_entity()

    asyncio.run(entity.async_set_native_value(5.9))

    assert updates == [{CONF_SCAN_INTERVAL: 6}]


def test_set_value_no_op_when_unchanged() -> None:
    """Re-setting the current value does not rewrite options (avoids a reload)."""
    entity, updates = _build_entity({CONF_SCAN_INTERVAL: 30})

    asyncio.run(entity.async_set_native_value(30))

    assert updates == []


def test_set_value_no_op_when_option_unset_and_value_is_default() -> None:
    """With no stored option the entity shows the default; setting the default
    must not write options (and so must not reload the entry)."""
    entity, updates = _build_entity()

    asyncio.run(entity.async_set_native_value(DEFAULT_SCAN_INTERVAL_SECONDS))

    assert updates == []


def test_set_value_preserves_other_options() -> None:
    """Unrelated options are carried through unchanged."""
    entity, updates = _build_entity({CONF_SCAN_INTERVAL: 1800, "other": "keep"})

    asyncio.run(entity.async_set_native_value(60))

    assert updates == [{CONF_SCAN_INTERVAL: 60, "other": "keep"}]


def _options_schema(options: dict):
    """Return the voluptuous schema the options flow shows for ``options``."""
    flow = OptionsFlowHandler()
    captured = {}

    def async_show_form(*, step_id, data_schema):
        captured["schema"] = data_schema

    with (
        patch.object(
            OptionsFlowHandler,
            "config_entry",
            SimpleNamespace(options=dict(options)),
        ),
        patch.object(flow, "async_show_form", async_show_form),
    ):
        asyncio.run(flow.async_step_init())
    return captured["schema"]


def test_options_flow_clamps_to_shared_bounds() -> None:
    """The options-flow field enforces the same bounds as the entity."""
    schema = _options_schema({})

    too_high = schema({CONF_SCAN_INTERVAL: MAX_SCAN_INTERVAL_SECONDS + 1})
    too_low = schema({CONF_SCAN_INTERVAL: MIN_SCAN_INTERVAL_SECONDS - 1})

    assert too_high[CONF_SCAN_INTERVAL] == MAX_SCAN_INTERVAL_SECONDS
    assert too_low[CONF_SCAN_INTERVAL] == MIN_SCAN_INTERVAL_SECONDS
