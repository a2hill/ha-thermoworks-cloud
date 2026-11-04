"""Diagnostics support for the Thermoworks Cloud integration.

Diagnostics capture the raw ThermoWorks API response, which lets maintainers support devices they
do not own. The config entry is left out, so the API key and credentials are never included.
"""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Channel ids are not personal and are needed for debugging, so "id" must not be listed here.
TO_REDACT = {"label", "locationId"}


def _redact_response(response: dict[str, Any]) -> dict[str, Any]:
    """Redact personal data, keeping the fields that show how a device is structured.

    Device identifiers become placeholders rather than being removed, so that it stays visible
    when id and serial match and when a field refers to another device, such as a gateway.
    """
    text = json.dumps(response)
    for index, device in enumerate(response.get("devices", [])):
        for identifier in (device.get("id"), device.get("serial")):
            if identifier:
                text = text.replace(json.dumps(identifier), json.dumps(f"device-{index}"))

    return async_redact_data(json.loads(text), TO_REDACT)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    diagnostics: dict[str, Any] = {
        "provider": coordinator.provider,
        "poll_interval": coordinator.poll_interval,
    }

    # Firebase providers have no API client to capture a response from
    if coordinator.client is None:
        return diagnostics

    try:
        diagnostics["devices_response"] = _redact_response(
            await coordinator.client.get_devices_raw()
        )
    except Exception as err:  # pylint: disable=broad-exception-caught
        # A failed capture is itself useful, so still return the diagnostics
        diagnostics["devices_error"] = f"{type(err).__name__}: {err}"

    return diagnostics
