"""Test the integration end to end, from the ThermoWorks HTTP API to Home Assistant states."""

from datetime import timedelta

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
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
    TEST_ACCOUNT_ID,
    TEST_API_KEY,
    TEST_ETAG,
    TEST_SERIAL,
    ApiTestObject,
)

TEMPERATURE_ENTITY = "sensor.12_34_56_78_90_ab_ch_1_temperature"


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
