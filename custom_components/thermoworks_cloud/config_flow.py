"""Config flow for Thermoworks Cloud integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from thermoworks_cloud import AuthenticationError, AuthFactory, ThermoworksCloud

from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN, MIN_SCAN_INTERVAL_SECONDS

_LOGGER: logging.Logger = logging.getLogger(__package__)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from THERMOWORKS_CLOUD_SCHEMA with values provided by the user.

    """
    client_session = async_get_clientsession(hass)
    auth_factory = AuthFactory(client_session)
    try:
        auth = await auth_factory.build_auth(
            data[CONF_EMAIL], password=data[CONF_PASSWORD]
        )
        thermoworks_cloud = ThermoworksCloud(auth)
        await thermoworks_cloud.get_user()

    except AuthenticationError as e:
        raise InvalidAuth from e
    except ConnectionError as e:
        raise CannotConnect from e

    # Return info that you want to store in the config entry.
    return {"title": "ThermoWorks Cloud", "user": auth.user_id}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ThermoWorks Cloud."""

    VERSION = 1
    _input_data: dict[str, Any]

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception as e:
                _LOGGER.exception(f"Unexpected exception: {e}")
                errors["base"] = "unknown"

            if "base" not in errors:
                # Validation was successful, so create a unique id for this instance of your integration
                # and create the config entry.
                await self.async_set_unique_id(info.get("user"))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=CONFIG_SCHEMA, errors=errors
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handles the options flow."""

    async def async_step_init(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            options = self.config_entry.options | user_input
            return self.async_create_entry(data=options)

        # It is recommended to prepopulate options fields with default values if available.
        # These will be the same default values you use on your coordinator for setting variable values
        # if the option has not been set.
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
                    ),
                ): vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL_SECONDS)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            description_placeholders={"unit": "seconds"}
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
