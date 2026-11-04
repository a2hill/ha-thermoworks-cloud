"""Verify that diagnostics capture API responses without personal data."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from thermoworks_cloud import RateLimitError

from custom_components.thermoworks_cloud.const import DOMAIN, PROVIDER_ETI, PROVIDER_THERMOWORKS
from custom_components.thermoworks_cloud.diagnostics import async_get_config_entry_diagnostics

ENTRY = SimpleNamespace(entry_id="test-entry")
SERIAL = "12:34:56:78:90:AB"
GATEWAY_SERIAL = "CD:EF:12:34:56:78"


def _diagnostics(provider: str, client) -> dict:
    """Return the diagnostics for a coordinator with the given client."""
    coordinator = SimpleNamespace(provider=provider, poll_interval=60, client=client)
    hass = SimpleNamespace(
        data={DOMAIN: {ENTRY.entry_id: SimpleNamespace(coordinator=coordinator)}}
    )
    return asyncio.run(async_get_config_entry_diagnostics(hass, ENTRY))


def _response() -> dict:
    """Return a response with one probe that refers to a gateway."""
    return {
        "generatedAt": "2026-11-04T04:43:49.806Z",
        "devices": [
            {
                "id": SERIAL,
                "serial": SERIAL,
                "label": "Smoker",
                "locationId": "test-location",
                "model": "rfx meat",
                "unknownGatewayField": GATEWAY_SERIAL,
                "channels": [{"id": "1", "number": 1, "label": "Brisket", "value": 150.5}],
            },
            {"id": GATEWAY_SERIAL, "serial": GATEWAY_SERIAL, "model": "rfx gateway", "channels": []},
        ],
    }


def test_diagnostics_redact_personal_data():
    client = SimpleNamespace(get_devices_raw=AsyncMock(return_value=_response()))

    result = _diagnostics(PROVIDER_THERMOWORKS, client)

    text = str(result)
    assert SERIAL not in text
    assert GATEWAY_SERIAL not in text
    assert "Smoker" not in text
    assert "Brisket" not in text
    assert "test-location" not in text


def test_diagnostics_keep_device_structure():
    client = SimpleNamespace(get_devices_raw=AsyncMock(return_value=_response()))

    result = _diagnostics(PROVIDER_THERMOWORKS, client)

    device, gateway = result["devices_response"]["devices"]
    assert device["id"] == device["serial"]
    assert device["unknownGatewayField"] == gateway["id"]
    assert device["model"] == "rfx meat"
    assert device["channels"][0]["id"] == "1"
    assert device["channels"][0]["value"] == 150.5


def test_diagnostics_report_a_failed_capture():
    client = SimpleNamespace(
        get_devices_raw=AsyncMock(side_effect=RateLimitError("limited", retry_after=12))
    )

    result = _diagnostics(PROVIDER_THERMOWORKS, client)

    assert result["devices_error"] == "RateLimitError: limited"
    assert result["provider"] == PROVIDER_THERMOWORKS


def test_diagnostics_without_api_client():
    result = _diagnostics(PROVIDER_ETI, None)

    assert result == {"provider": PROVIDER_ETI, "poll_interval": 60}
