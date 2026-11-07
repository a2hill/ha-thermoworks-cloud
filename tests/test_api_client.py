"""Test the integration end to end, from the ThermoWorks HTTP API to Home Assistant states."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from typing import Any

import pytest

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.thermoworks_cloud.const import (
    CONF_API_KEY,
    CONF_CLOUD_PROVIDER,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    PROVIDER_ETI,
    PROVIDER_THERMOWORKS,
)
from tests.api_test_object import (
    GET_DEVICES_RESPONSE,
    GET_DEVICES_NO_PROBE_RESPONSE,
    GET_DEVICES_FAILED_PROBE_RESPONSE,
    GET_DEVICES_NULL_READING_RESPONSE,
    GET_DEVICES_NULL_UNITS_RESPONSE,
    GET_DEVICES_CHARGING_RESPONSE,
    GET_DEVICES_NULL_BATTERY_RESPONSE,
    GET_DEVICES_NO_DEVICES_RESPONSE,
    GET_DEVICES_FAN_RESPONSE,
    GET_DEVICES_FAN_NO_STATE_RESPONSE,
    GET_DEVICES_FAN_NO_CONNECTION_RESPONSE,
    GET_DEVICES_UNLABELED_FAN_RESPONSE,
    GET_DEVICES_UPDATED_DETAILS_RESPONSE,
    GET_DEVICES_NO_CHANNELS_RESPONSE,
    GET_DEVICES_DISABLED_CHANNEL_RESPONSE,
    GET_DEVICES_UNKNOWN_CHANNEL_METADATA_RESPONSE,
    GET_DEVICES_DISTINCT_CHANNEL_ID_RESPONSE,
    GET_DEVICES_LOW_ALARM_RESPONSE,
    TEST_ACCOUNT_ID,
    TEST_API_KEY,
    TEST_ETAG,
    TEST_SERIAL,
    ApiTestObject,
)

TEMPERATURE_ENTITY = "sensor.12_34_56_78_90_ab_ch_1_temperature"
HIGH_THRESHOLD_ENTITY = "sensor.12_34_56_78_90_ab_ch_1_high_alarm_threshold"
HIGH_ALARM_ENTITY = "binary_sensor.12_34_56_78_90_ab_ch_1_high_alarm"
LOW_ALARM_ENTITY = "binary_sensor.12_34_56_78_90_ab_ch_1_low_alarm"
BATTERY_ENTITY = "sensor.12_34_56_78_90_ab_battery"
SIGNAL_ENTITY = "sensor.12_34_56_78_90_ab_signal"
DEVICE_ENTITIES = (
    BATTERY_ENTITY,
    SIGNAL_ENTITY,
    "sensor.12_34_56_78_90_ab_last_seen",
    "sensor.12_34_56_78_90_ab_transmit_interval",
)


def _api_key_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add a config entry that uses an API key."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{PROVIDER_THERMOWORKS}:{TEST_ACCOUNT_ID}",
        data={CONF_API_KEY: TEST_API_KEY, CONF_CLOUD_PROVIDER: PROVIDER_THERMOWORKS},
    )
    entry.add_to_hass(hass)
    return entry


def _password_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add a config entry as it was saved before API keys, without a provider."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="firebase-user-id",
        data={CONF_EMAIL: "test@example.com", CONF_PASSWORD: "test_password"},
    )
    entry.add_to_hass(hass)
    return entry


async def _set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up a config entry and wait for it to settle."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass: HomeAssistant, seconds: int = DEFAULT_SCAN_INTERVAL_SECONDS) -> None:
    """Advance time far enough for the integration to poll again."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds + 1))
    await hass.async_block_till_done(wait_background_tasks=True)


def _reauth_flows(hass: HomeAssistant) -> list:
    """Return the reauthentication prompts shown to the user."""
    return [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == "reauth"
    ]


async def test_sensors_report_values_from_the_api(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that a reading from the API reaches a Home Assistant sensor."""

    # Setup
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = _api_key_entry(hass)
    channel = GET_DEVICES_RESPONSE["devices"][0]["channels"][0]

    # Act
    await _set_up(hass, entry)

    # Assert
    assert entry.state is ConfigEntryState.LOADED
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert float(state.state) == channel["value"]


async def test_devices_keep_their_firebase_identity(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that a device matches the registry entry created through Firebase."""

    # Setup
    entry = _api_key_entry(hass)
    registry = dr.async_get(hass)

    # Act
    await _set_up(hass, entry)

    # Assert
    device = registry.async_get_device_by_identifier(
        (DOMAIN, dr.format_mac(TEST_SERIAL)), config_entry_id=entry.entry_id
    )
    assert device is not None
    assert device.model == GET_DEVICES_RESPONSE["devices"][0]["model"]


async def test_one_request_is_made_per_poll(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that reading every device and channel costs one request of the rate limit."""

    # Setup
    entry = _api_key_entry(hass)

    # Act
    await _set_up(hass, entry)

    # Assert
    assert len(api_test_object.devices_requests) == 1


async def test_unchanged_devices_keep_their_values(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that a 304 response to the previous ETag leaves sensors as they were."""

    # Setup
    entry = _api_key_entry(hass)
    api_test_object.respond_to_devices(
        body=GET_DEVICES_RESPONSE, headers={"ETag": TEST_ETAG}
    )
    await _set_up(hass, entry)
    before = hass.states.get(TEMPERATURE_ENTITY)
    assert before is not None
    api_test_object.respond_to_devices(status=304)

    # Act
    await _poll(hass)

    # Assert
    assert api_test_object.devices_requests[-1].headers["If-None-Match"] == TEST_ETAG
    after = hass.states.get(TEMPERATURE_ENTITY)
    assert after is not None
    assert after.state == before.state
    assert after.attributes["last_telemetry_saved"] == before.attributes["last_telemetry_saved"]


async def test_rate_limit_makes_sensors_unavailable(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that a 429 response is shown as unavailable and does not ask for a new key."""

    # Setup
    entry = _api_key_entry(hass)
    await _set_up(hass, entry)
    api_test_object.respond_to_devices(status=429, headers={"Retry-After": "120"})

    # Act
    await _poll(hass)

    # Assert
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert state.state == "unavailable"
    assert not _reauth_flows(hass)


async def test_rate_limit_delays_the_next_poll(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that the integration waits for as long as a 429 response asks."""

    # Setup
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{PROVIDER_THERMOWORKS}:{TEST_ACCOUNT_ID}",
        data={CONF_API_KEY: TEST_API_KEY, CONF_CLOUD_PROVIDER: PROVIDER_THERMOWORKS},
        options={CONF_SCAN_INTERVAL: 60},
    )
    entry.add_to_hass(hass)
    await _set_up(hass, entry)
    api_test_object.respond_to_devices(status=429, headers={"Retry-After": "600"})
    await _poll(hass, 60)
    requests_when_limited = len(api_test_object.devices_requests)

    # Act
    await _poll(hass, 120)

    # Assert
    assert len(api_test_object.devices_requests) == requests_when_limited


async def test_rejected_key_asks_for_a_new_key(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that a key revoked while running prompts the user instead of failing silently."""

    # Setup
    entry = _api_key_entry(hass)
    await _set_up(hass, entry)
    api_test_object.respond_to_devices(status=401, body={"error": {"code": "invalid_api_key"}})

    # Act
    await _poll(hass)

    # Assert
    assert len(_reauth_flows(hass)) == 1


async def test_new_key_restores_a_running_entry(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that entering a new key for a revoked one reloads the entry and uses the new key."""

    # Setup
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{PROVIDER_THERMOWORKS}:{TEST_ACCOUNT_ID}",
        data={CONF_API_KEY: "twk_revoked", CONF_CLOUD_PROVIDER: PROVIDER_THERMOWORKS},
    )
    entry.add_to_hass(hass)
    await _set_up(hass, entry)
    api_test_object.respond_to_devices(status=401, body={"error": {"code": "invalid_api_key"}})
    await _poll(hass)
    api_test_object.respond_to_devices(body=GET_DEVICES_RESPONSE)
    flow = _reauth_flows(hass)[0]

    # Act
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_API_KEY: TEST_API_KEY}
    )
    await hass.async_block_till_done()

    # Assert
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED
    last_request = api_test_object.devices_requests[-1]
    assert last_request.headers["Authorization"] == f"Bearer {TEST_API_KEY}"
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert state.state != "unavailable"


async def test_same_key_recovers_a_running_entry(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test re-entering a key after a temporary rejection.

    The saved data does not change, so the update listener does not reload the entry, and polling
    has stopped since the key was rejected. The flow has to reload it, without the call that Home
    Assistant no longer allows from 2026.12.
    """

    # Setup
    entry = _api_key_entry(hass)
    await _set_up(hass, entry)
    api_test_object.respond_to_devices(status=401, body={"error": {"code": "invalid_api_key"}})
    await _poll(hass)
    api_test_object.respond_to_devices(body=GET_DEVICES_RESPONSE)
    flow = _reauth_flows(hass)[0]

    # Act
    with patch("homeassistant.config_entries.report_usage") as report_usage:
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_API_KEY: TEST_API_KEY}
        )
        await hass.async_block_till_done()

    # Assert
    report_usage.assert_not_called()
    assert result["reason"] == "reauth_successful"
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert state.state != "unavailable"


async def test_existing_password_user_is_asked_for_a_key(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that upgrading prompts anyone set up with a ThermoWorks password for a key."""

    # Setup
    entry = _password_entry(hass)

    # Act
    await _set_up(hass, entry)

    # Assert
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = _reauth_flows(hass)
    assert len(flows) == 1
    assert flows[0]["step_id"] == "api_key"


async def test_existing_password_user_recovers_with_a_key(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that entering a key restores sensors and removes the saved password."""

    # Setup
    entry = _password_entry(hass)
    await _set_up(hass, entry)
    flow = _reauth_flows(hass)[0]

    # Act
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_API_KEY: TEST_API_KEY}
    )
    await hass.async_block_till_done()

    # Assert
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == "firebase-user-id"
    assert CONF_PASSWORD not in entry.data
    assert hass.states.get(TEMPERATURE_ENTITY) is not None


async def test_removing_an_entry_ends_its_prompt(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that a prompt for a key can't outlive the entry it belongs to."""

    # Setup
    entry = _password_entry(hass)
    await _set_up(hass, entry)
    assert len(_reauth_flows(hass)) == 1

    # Act
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    # Assert
    assert not _reauth_flows(hass)


async def test_eti_entry_is_not_asked_for_a_key(
    hass: HomeAssistant, api_test_object: ApiTestObject, aioclient_mock
) -> None:
    """Test that ETI accounts, which have no API yet, keep retrying with their password."""

    # Setup
    aioclient_mock.get("https://firebase.googleapis.com/", status=500)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="firebase-user-id",
        data={
            CONF_EMAIL: "test@example.com",
            CONF_PASSWORD: "test_password",
            CONF_CLOUD_PROVIDER: PROVIDER_ETI,
        },
    )
    entry.add_to_hass(hass)

    # Act
    await _set_up(hass, entry)

    # Assert
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not _reauth_flows(hass)


async def _start_setup(hass: HomeAssistant) -> str:
    """Start setting up ThermoWorks Cloud in the UI, returning the flow at the API key step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CLOUD_PROVIDER: PROVIDER_THERMOWORKS}
    )
    assert result["step_id"] == "api_key"
    return result["flow_id"]


async def test_setup_with_a_key_creates_an_entry(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that a valid key creates a config entry for its account."""

    # Setup
    flow_id = await _start_setup(hass)

    # Act
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_API_KEY: TEST_API_KEY})
    await hass.async_block_till_done()

    # Assert
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_KEY] == TEST_API_KEY
    assert result["result"].unique_id == f"{PROVIDER_THERMOWORKS}:{TEST_ACCOUNT_ID}"


async def test_setup_with_a_rejected_key_shows_an_error(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that a key the API rejects is reported on the form."""

    # Setup
    flow_id = await _start_setup(hass)

    # Act
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_API_KEY: "twk_wrong"})

    # Assert
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_setup_when_the_service_fails_shows_an_error(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that a service failure is not reported as a bad key."""

    # Setup
    flow_id = await _start_setup(hass)
    api_test_object.me_status = 500

    # Act
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_API_KEY: TEST_API_KEY})

    # Assert
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reading_exposes_source_metadata(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Keep the source measurement timestamp distinguishable from HA's poll time."""

    # Setup
    entry = _api_key_entry(hass)
    expected = GET_DEVICES_RESPONSE["devices"][0]["channels"][0]

    # Act
    await _set_up(hass, entry)

    # Assert
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert state.attributes["channel_id"] == expected["id"]
    assert state.attributes["enabled"] == expected["enabled"]
    assert state.attributes["probe_failed"] == expected["probeFailed"]
    assert state.attributes["alarming"] == expected["alarming"]
    assert state.attributes["status"] == expected["status"]
    assert dt_util.parse_datetime(state.attributes["last_telemetry_saved"]) == (
        dt_util.parse_datetime(expected["lastTelemetrySaved"])
    )
    assert dt_util.parse_datetime(state.attributes["last_seen"]) == (
        dt_util.parse_datetime(expected["lastSeen"])
    )


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(GET_DEVICES_NO_PROBE_RESPONSE, id="no-probe"),
        pytest.param(GET_DEVICES_FAILED_PROBE_RESPONSE, id="probe-failed"),
        pytest.param(GET_DEVICES_NULL_READING_RESPONSE, id="null-reading"),
        pytest.param(GET_DEVICES_DISABLED_CHANNEL_RESPONSE, id="disabled"),
    ],
)
async def test_failed_channel_becomes_unavailable_and_recovers(
    hass: HomeAssistant, api_test_object: ApiTestObject, response: dict[str, Any]
) -> None:
    """Explicit channel failures hide readings and active alarms without deleting entities."""

    # Setup
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = _api_key_entry(hass)
    await _set_up(hass, entry)
    registry = er.async_get(hass)
    before = registry.async_get(TEMPERATURE_ENTITY)
    assert before is not None
    unique_id = before.unique_id
    api_test_object.respond_to_devices(body=response)

    # Act
    await _poll(hass)

    # Assert
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert state.state == "unavailable"
    alarm = hass.states.get(HIGH_ALARM_ENTITY)
    assert alarm is not None
    assert alarm.state == "unavailable"
    threshold = hass.states.get(HIGH_THRESHOLD_ENTITY)
    assert threshold is not None
    assert float(threshold.state) == response["devices"][0]["channels"][0]["alarmHigh"]["value"]

    # Recover using the same entities and identifiers.
    api_test_object.respond_to_devices(body=GET_DEVICES_RESPONSE)
    await _poll(hass, DEFAULT_SCAN_INTERVAL_SECONDS * 2)
    recovered = hass.states.get(TEMPERATURE_ENTITY)
    assert recovered is not None
    assert float(recovered.state) == GET_DEVICES_RESPONSE["devices"][0]["channels"][0]["value"]
    after = registry.async_get(TEMPERATURE_ENTITY)
    assert after is not None
    assert after.unique_id == unique_id


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(GET_DEVICES_NULL_UNITS_RESPONSE, id="null-units"),
        pytest.param(GET_DEVICES_NO_CHANNELS_RESPONSE, id="channel-removed"),
    ],
)
async def test_missing_channel_becomes_unavailable_and_recovers(
    hass: HomeAssistant,
    api_test_object: ApiTestObject,
    caplog: pytest.LogCaptureFixture,
    response: dict[str, Any],
) -> None:
    """A channel the integration cannot read must not keep showing its last data."""

    # Setup
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = _api_key_entry(hass)
    await _set_up(hass, entry)
    api_test_object.respond_to_devices(body=response)

    # Act
    await _poll(hass)

    # Assert
    for entity_id in (TEMPERATURE_ENTITY, HIGH_ALARM_ENTITY, HIGH_THRESHOLD_ENTITY):
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "unavailable"
    assert "Unexpected error updating listener" not in caplog.text

    # Recover using the same entities.
    api_test_object.respond_to_devices(body=GET_DEVICES_RESPONSE)
    await _poll(hass, DEFAULT_SCAN_INTERVAL_SECONDS * 2)
    recovered = hass.states.get(TEMPERATURE_ENTITY)
    assert recovered is not None
    assert float(recovered.state) == GET_DEVICES_RESPONSE["devices"][0]["channels"][0]["value"]


async def test_channel_last_seen_is_not_recorded(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Keep the measurement timestamp in history without storing every device contact."""

    # Setup
    entry = _api_key_entry(hass)

    # Act
    await _set_up(hass, entry)

    # Assert
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert state.attributes["last_seen"] is not None
    assert state.state_info is not None
    unrecorded = state.state_info["unrecorded_attributes"]
    assert "last_seen" in unrecorded
    assert "last_telemetry_saved" not in unrecorded


async def test_initial_null_reading_still_creates_entities(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """A null reading must not prevent discovery or recovery of a known channel."""

    # Setup
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = _api_key_entry(hass)
    api_test_object.respond_to_devices(body=GET_DEVICES_NULL_READING_RESPONSE)

    # Act
    await _set_up(hass, entry)

    # Assert
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert state.state == "unavailable"
    threshold = hass.states.get(HIGH_THRESHOLD_ENTITY)
    assert threshold is not None
    assert float(threshold.state) == (
        GET_DEVICES_NULL_READING_RESPONSE["devices"][0]["channels"][0]["alarmHigh"]["value"]
    )


async def test_low_alarm_is_a_valid_reading(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """An out-of-range measurement is distinct from an unavailable measurement."""

    # Setup
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = _api_key_entry(hass)
    api_test_object.respond_to_devices(body=GET_DEVICES_LOW_ALARM_RESPONSE)
    expected = GET_DEVICES_LOW_ALARM_RESPONSE["devices"][0]["channels"][0]

    # Act
    await _set_up(hass, entry)

    # Assert
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert float(state.state) == expected["value"]
    alarm = hass.states.get(LOW_ALARM_ENTITY)
    assert alarm is not None
    assert alarm.state == "on"


async def test_unknown_metadata_does_not_mark_a_channel_failed(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Missing metadata is unknown rather than an explicit probe failure."""

    # Setup
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = _api_key_entry(hass)
    api_test_object.respond_to_devices(body=GET_DEVICES_UNKNOWN_CHANNEL_METADATA_RESPONSE)

    # Act
    await _set_up(hass, entry)

    # Assert
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert float(state.state) == (
        GET_DEVICES_UNKNOWN_CHANNEL_METADATA_RESPONSE["devices"][0]["channels"][0]["value"]
    )
    assert state.attributes["enabled"] is None
    assert state.attributes["probe_failed"] is None
    assert state.attributes["last_telemetry_saved"] is None


async def test_channel_api_id_does_not_replace_entity_identity(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Expose the API id while retaining channel-number-based entity identifiers."""

    # Setup
    entry = _api_key_entry(hass)
    await _set_up(hass, entry)
    registry = er.async_get(hass)
    before = registry.async_get(TEMPERATURE_ENTITY)
    assert before is not None
    unique_id = before.unique_id
    api_test_object.respond_to_devices(body=GET_DEVICES_DISTINCT_CHANNEL_ID_RESPONSE)

    # Act
    await _poll(hass)

    # Assert
    state = hass.states.get(TEMPERATURE_ENTITY)
    assert state is not None
    assert state.attributes["channel_id"] == (
        GET_DEVICES_DISTINCT_CHANNEL_ID_RESPONSE["devices"][0]["channels"][0]["id"]
    )
    after = registry.async_get(TEMPERATURE_ENTITY)
    assert after is not None
    assert after.unique_id == unique_id


async def test_charging_battery_uses_the_charging_icon(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """The battery state from the API reaches the battery sensor's icon."""

    # Setup
    entry = _api_key_entry(hass)
    api_test_object.respond_to_devices(body=GET_DEVICES_CHARGING_RESPONSE)

    # Act
    await _set_up(hass, entry)

    # Assert
    state = hass.states.get(BATTERY_ENTITY)
    assert state is not None
    assert state.attributes.get("icon") == "mdi:battery-charging-100"


async def test_lost_device_field_only_affects_its_entity(
    hass: HomeAssistant,
    api_test_object: ApiTestObject,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A device losing one value makes that entity unavailable without stalling the rest."""

    # Setup
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = _api_key_entry(hass)
    await _set_up(hass, entry)
    api_test_object.respond_to_devices(body=GET_DEVICES_NULL_BATTERY_RESPONSE)

    # Act
    await _poll(hass)

    # Assert
    battery = hass.states.get(BATTERY_ENTITY)
    assert battery is not None
    assert battery.state == "unavailable"
    # Entities updated after the battery sensor still get the new data
    signal = hass.states.get(SIGNAL_ENTITY)
    assert signal is not None
    assert float(signal.state) == -70
    temperature = hass.states.get(TEMPERATURE_ENTITY)
    assert temperature is not None
    assert float(temperature.state) == 5.0
    assert "Unexpected error updating listener" not in caplog.text

    # Recover using the same entity.
    api_test_object.respond_to_devices(body=GET_DEVICES_RESPONSE)
    await _poll(hass, DEFAULT_SCAN_INTERVAL_SECONDS * 2)
    recovered = hass.states.get(BATTERY_ENTITY)
    assert recovered is not None
    assert float(recovered.state) == GET_DEVICES_RESPONSE["devices"][0]["battery"]


async def test_missing_device_becomes_unavailable_and_recovers(
    hass: HomeAssistant,
    api_test_object: ApiTestObject,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A device the API stops returning must not keep showing its last values."""

    # Setup
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = _api_key_entry(hass)
    await _set_up(hass, entry)
    api_test_object.respond_to_devices(body=GET_DEVICES_NO_DEVICES_RESPONSE)

    # Act
    await _poll(hass)

    # Assert
    for entity_id in (*DEVICE_ENTITIES, TEMPERATURE_ENTITY):
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "unavailable", entity_id
    assert "Unexpected error updating listener" not in caplog.text

    # Recover using the same entities.
    api_test_object.respond_to_devices(body=GET_DEVICES_RESPONSE)
    await _poll(hass, DEFAULT_SCAN_INTERVAL_SECONDS * 2)
    for entity_id in DEVICE_ENTITIES:
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state != "unavailable", entity_id


def _registered_device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str):
    """Return the device registry entry for an identifier."""
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, identifier), config_entry_id=entry.entry_id
    )
    assert device is not None
    return device


async def test_devices_are_registered_with_their_details(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Every device is registered with its details from the API."""

    # Setup
    entry = _api_key_entry(hass)
    api_device = GET_DEVICES_RESPONSE["devices"][0]

    # Act
    await _set_up(hass, entry)

    # Assert
    device = _registered_device(hass, entry, dr.format_mac(TEST_SERIAL))
    assert device.name == api_device["label"]
    assert device.manufacturer == "ThermoWorks"
    assert device.model == api_device["model"]
    assert device.sw_version == api_device["firmware"]
    assert device.serial_number == api_device["serial"]


async def test_device_without_battery_is_still_named(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """A device's details don't depend on which entities it has."""

    # Setup
    entry = _api_key_entry(hass)
    api_test_object.respond_to_devices(body=GET_DEVICES_NULL_BATTERY_RESPONSE)

    # Act
    await _set_up(hass, entry)

    # Assert
    assert hass.states.get(BATTERY_ENTITY) is None
    device = _registered_device(hass, entry, dr.format_mac(TEST_SERIAL))
    assert device.name == GET_DEVICES_RESPONSE["devices"][0]["label"]


async def test_device_details_update_after_a_refresh(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """A rename or firmware update shows up without a reload, keeping the user's own name."""

    # Setup
    entry = _api_key_entry(hass)
    await _set_up(hass, entry)
    registry = dr.async_get(hass)
    device = _registered_device(hass, entry, dr.format_mac(TEST_SERIAL))
    registry.async_update_device(device.id, name_by_user="My freezer")
    api_test_object.respond_to_devices(body=GET_DEVICES_UPDATED_DETAILS_RESPONSE)

    # Act
    await _poll(hass)

    # Assert
    updated = _registered_device(hass, entry, dr.format_mac(TEST_SERIAL))
    assert updated.name == "Pantry"
    assert updated.sw_version == "2.2.0"
    assert updated.name_by_user == "My freezer"


@pytest.mark.parametrize(
    ("response", "fan_name"),
    [
        pytest.param(GET_DEVICES_FAN_RESPONSE, "Kitchen Fan", id="labeled"),
        pytest.param(
            GET_DEVICES_UNLABELED_FAN_RESPONSE,
            f"unnamed device (node - {TEST_SERIAL}) Fan",
            id="unlabeled",
        ),
    ],
)
async def test_fan_is_registered_under_its_gateway(
    hass: HomeAssistant,
    api_test_object: ApiTestObject,
    response: dict[str, Any],
    fan_name: str,
) -> None:
    """The fan accessory is its own device, named after and connected through its gateway."""

    # Setup
    entry = _api_key_entry(hass)
    api_test_object.respond_to_devices(body=response)

    # Act
    await _set_up(hass, entry)

    # Assert
    gateway = _registered_device(hass, entry, dr.format_mac(TEST_SERIAL))
    fan = _registered_device(hass, entry, f"{dr.format_mac(TEST_SERIAL)}-fan")
    assert fan.name == fan_name
    assert fan.via_device_id == gateway.id
    fan_state = hass.states.get("sensor.12_34_56_78_90_ab_fan_state")
    assert fan_state is not None
    assert fan_state.state == "Blowing"


async def test_last_seen_is_reported_in_utc(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """The API's last seen timestamp reaches the sensor as an aware UTC time."""

    # Setup
    entry = _api_key_entry(hass)

    # Act
    await _set_up(hass, entry)

    # Assert
    state = hass.states.get("sensor.12_34_56_78_90_ab_last_seen")
    assert state is not None
    # Home Assistant shows timestamps to the second
    assert dt_util.parse_datetime(state.state) == datetime(
        2026, 11, 4, 3, 54, 28, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        pytest.param(
            GET_DEVICES_FAN_NO_STATE_RESPONSE,
            {"binary_sensor.12_34_56_78_90_ab_fan_connected": "on",
             "sensor.12_34_56_78_90_ab_fan_state": "unknown"},
            id="no-fan-state",
        ),
        pytest.param(
            GET_DEVICES_FAN_NO_CONNECTION_RESPONSE,
            {"binary_sensor.12_34_56_78_90_ab_fan_connected": "unknown",
             # Not known to be connected, so its values aren't shown as current
             "sensor.12_34_56_78_90_ab_fan_state": "unavailable"},
            id="no-fan-connection",
        ),
    ],
)
async def test_unreported_fan_values_are_unknown(
    hass: HomeAssistant,
    api_test_object: ApiTestObject,
    response: dict[str, Any],
    expected: dict[str, str],
) -> None:
    """A value the fan doesn't report is unknown, not unavailable."""

    # Setup
    entry = _api_key_entry(hass)
    api_test_object.respond_to_devices(body=response)

    # Act
    await _set_up(hass, entry)

    # Assert
    for entity_id, value in expected.items():
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state == value, entity_id

