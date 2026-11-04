"""Test that diagnostics capture API responses without personal data."""

from copy import deepcopy

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermoworks_cloud.const import (
    CONF_API_KEY,
    CONF_CLOUD_PROVIDER,
    DOMAIN,
    PROVIDER_THERMOWORKS,
)
from custom_components.thermoworks_cloud.diagnostics import async_get_config_entry_diagnostics
from tests.api_test_object import (
    GET_DEVICES_RESPONSE,
    TEST_API_KEY,
    TEST_SERIAL,
    ApiTestObject,
)

TEST_GATEWAY_SERIAL = "CD:EF:12:34:56:78"


async def _set_up(hass: HomeAssistant) -> MockConfigEntry:
    """Set up a config entry that uses an API key."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: TEST_API_KEY, CONF_CLOUD_PROVIDER: PROVIDER_THERMOWORKS},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_diagnostics_remove_personal_data(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that serials, labels and the API key are not in the downloaded file."""

    # Setup
    entry = await _set_up(hass)
    response = deepcopy(GET_DEVICES_RESPONSE)
    response["devices"][0]["unknownGatewayField"] = TEST_GATEWAY_SERIAL
    response["devices"].append(
        {"id": TEST_GATEWAY_SERIAL, "serial": TEST_GATEWAY_SERIAL, "channels": []}
    )
    api_test_object.respond_to_devices(body=response)

    # Act
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    # Assert
    text = str(diagnostics)
    assert TEST_SERIAL not in text
    assert TEST_GATEWAY_SERIAL not in text
    assert response["devices"][0]["label"] not in text
    assert response["devices"][0]["channels"][0]["label"] not in text
    assert TEST_API_KEY not in text


async def test_diagnostics_keep_what_is_needed_to_support_a_device(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that the raw shape survives redaction, including links between devices."""

    # Setup
    entry = await _set_up(hass)
    response = deepcopy(GET_DEVICES_RESPONSE)
    response["devices"][0]["unknownGatewayField"] = TEST_GATEWAY_SERIAL
    response["devices"].append(
        {"id": TEST_GATEWAY_SERIAL, "serial": TEST_GATEWAY_SERIAL, "channels": []}
    )
    api_test_object.respond_to_devices(body=response)

    # Act
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    # Assert
    device, gateway = diagnostics["devices_response"]["devices"]
    expected = response["devices"][0]
    assert device["id"] == device["serial"]
    assert device["unknownGatewayField"] == gateway["id"]
    assert device["model"] == expected["model"]
    assert device["channels"][0]["id"] == expected["channels"][0]["id"]
    assert device["channels"][0]["value"] == expected["channels"][0]["value"]


async def test_diagnostics_report_a_failed_capture(
    hass: HomeAssistant, api_test_object: ApiTestObject
) -> None:
    """Test that the file can still be downloaded when the capture is rate limited."""

    # Setup
    entry = await _set_up(hass)
    api_test_object.respond_to_devices(status=429, headers={"Retry-After": "12"})

    # Act
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    # Assert
    assert "devices_response" not in diagnostics
    assert "RateLimitError" in diagnostics["devices_error"]
