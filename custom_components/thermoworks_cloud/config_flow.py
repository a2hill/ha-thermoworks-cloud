"""Config flow for Thermoworks Cloud integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    ApiKeyInfo,
    CannotConnectError,
    InvalidApiKeyError,
    RateLimitedError,
    ThermoworksApiClient,
)
from .const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

API_KEY_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})

API_KEY_HELP = {
    "integrations_url": "https://cloud.thermoworks.com/",
    "docs_url": "https://cloud.thermoworks.com/api/docs/",
}


async def validate_api_key(hass: HomeAssistant, api_key: str) -> ApiKeyInfo:
    """Check the key against GET /v1/me and GET /v1/devices."""
    client = ThermoworksApiClient(async_get_clientsession(hass), api_key)
    try:
        info = await client.get_me()
        await client.get_devices()
    except InvalidApiKeyError as err:
        raise InvalidAuth from err
    except RateLimitedError as err:
        raise RateLimited from err
    except CannotConnectError as err:
        raise CannotConnect from err
    return info


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ThermoWorks Cloud."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    async def _async_check_key(self, api_key: str) -> tuple[ApiKeyInfo | None, dict[str, str]]:
        errors: dict[str, str] = {}
        try:
            return await validate_api_key(self.hass, api_key.strip()), errors
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_api_key"
        except RateLimited:
            errors["base"] = "rate_limited"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception validating ThermoWorks API key")
            errors["base"] = "unknown"
        return None, errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for a ThermoWorks Cloud API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._async_check_key(user_input[CONF_API_KEY])
            if info is not None:
                await self.async_set_unique_id(info.account_id or info.key_id)
                self._abort_if_unique_id_configured()
                title = "ThermoWorks Cloud"
                if info.key_name:
                    title = f"ThermoWorks Cloud ({info.key_name})"
                return self.async_create_entry(
                    title=title,
                    data={CONF_API_KEY: user_input[CONF_API_KEY].strip()},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=API_KEY_SCHEMA,
            errors=errors,
            description_placeholders=API_KEY_HELP,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Start reauth: an old email/password entry, or a key that was revoked or expired."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for a new API key and keep the existing entry, devices and entities."""
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._async_check_key(user_input[CONF_API_KEY])
            if info is not None:
                # Replace the data outright so the old email and password are discarded.
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data={CONF_API_KEY: user_input[CONF_API_KEY].strip()},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=API_KEY_SCHEMA,
            errors=errors,
            description_placeholders=API_KEY_HELP,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handles the options flow."""

    async def async_step_init(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            options = self.config_entry.options | user_input
            return self.async_create_entry(data=options)

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Clamp(
                        min=MIN_SCAN_INTERVAL_SECONDS,
                        max=MAX_SCAN_INTERVAL_SECONDS,
                    ),
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class RateLimited(HomeAssistantError):
    """Error to indicate the API key is rate limited."""
