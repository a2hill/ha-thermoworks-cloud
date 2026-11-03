"""Config flow for Thermoworks Cloud integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from thermoworks_cloud import AuthenticationError, AuthFactory, ThermoworksCloud

from .api import ApiAuthError, ApiError, ApiRateLimited, IntegrationsApi
from .const import (
    API_MIN_SCAN_INTERVAL_SECONDS,
    CLOUD_PROVIDERS,
    CONF_CLOUD_PROVIDER,
    CONF_ACCOUNT_ID,
    CONF_RECOMMENDED_POLL_SECONDS,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    PROVIDER_ETI,
    PROVIDER_THERMOWORKS,
    minimum_scan_interval,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

PROVIDER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLOUD_PROVIDER, default=PROVIDER_THERMOWORKS): vol.In(
            {
                PROVIDER_THERMOWORKS: "ThermoWorks Cloud (US)",
                PROVIDER_ETI: "ETI Cloud (UK/International)",
            }
        ),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

API_KEY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def _build_auth_factory(
    hass: HomeAssistant, provider: str
) -> AuthFactory:
    """Build an AuthFactory for the given cloud provider."""
    client_session = async_get_clientsession(hass)
    provider_config = CLOUD_PROVIDERS[provider]
    return AuthFactory(
        client_session,
        api_key=provider_config["api_key"],
        app_id=provider_config["app_id"],
        referer=provider_config["referer"],
    )


async def validate_input(
    hass: HomeAssistant, data: dict[str, Any], provider: str
) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    if provider == PROVIDER_THERMOWORKS:
        api = IntegrationsApi(async_get_clientsession(hass), data[CONF_API_KEY])
        try:
            me = await api.get_me()
        except ApiAuthError as err:
            raise InvalidAuth from err
        except ApiRateLimited:
            raise
        except ApiError as err:
            raise CannotConnect from err
        account_id = me.get("accountId")
        recommendation = me.get("recommendedPollSeconds")
        if (
            not isinstance(account_id, str)
            or not account_id
            or type(recommendation) is not int
            or recommendation < 1
            or recommendation > MAX_SCAN_INTERVAL_SECONDS
        ):
            raise CannotConnect("API returned invalid account or polling information")
        return {
            "title": CLOUD_PROVIDERS[provider]["name"],
            "user": f"{provider}:{account_id}",
            CONF_ACCOUNT_ID: account_id,
            CONF_RECOMMENDED_POLL_SECONDS: max(
                API_MIN_SCAN_INTERVAL_SECONDS, recommendation
            ),
        }
    auth_factory = _build_auth_factory(hass, provider)
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

    provider_name = CLOUD_PROVIDERS[provider]["name"]
    return {"title": provider_name, "user": auth.user_id}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ThermoWorks Cloud."""

    VERSION = 1
    _input_data: dict[str, Any]
    _provider: str = PROVIDER_THERMOWORKS
    _reauth_entry: config_entries.ConfigEntry | None = None

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
        """Handle the cloud provider selection step."""
        if user_input is not None:
            self._provider = user_input[CONF_CLOUD_PROVIDER]
            if self._provider == PROVIDER_THERMOWORKS:
                return await self.async_step_api_key()
            return await self.async_step_credentials()

        return self.async_show_form(
            step_id="user", data_schema=PROVIDER_SCHEMA
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the credentials step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input, self._provider)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception as e:
                _LOGGER.exception(f"Unexpected exception: {e}")
                errors["base"] = "unknown"

            if "base" not in errors:
                if self._reauth_entry is not None:
                    if info["user"] != self._reauth_entry.unique_id:
                        return self.async_abort(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        self._reauth_entry,
                        data={**user_input, CONF_CLOUD_PROVIDER: self._provider},
                    )
                await self.async_set_unique_id(info.get("user"))
                self._abort_if_unique_id_configured()
                entry_data = {
                    **user_input,
                    CONF_CLOUD_PROVIDER: self._provider,
                }
                return self.async_create_entry(title=info["title"], data=entry_data)

        return self.async_show_form(
            step_id="credentials", data_schema=CONFIG_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Replace credentials without replacing the entry or its entity IDs."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_entry_missing")
        self._provider = entry_data.get(CONF_CLOUD_PROVIDER, PROVIDER_THERMOWORKS)
        if self._provider == PROVIDER_THERMOWORKS:
            return await self.async_step_api_key()
        return await self.async_step_credentials()

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure the supported ThermoWorks API."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {CONF_API_KEY: user_input[CONF_API_KEY].strip()}
            try:
                info = await validate_input(self.hass, user_input, PROVIDER_THERMOWORKS)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except ApiRateLimited:
                errors["base"] = "rate_limited"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                account_id = info[CONF_ACCOUNT_ID]
                if self._reauth_entry is not None:
                    entry = self._reauth_entry
                    if (
                        entry.data.get(CONF_ACCOUNT_ID) is not None
                        and entry.data[CONF_ACCOUNT_ID] != account_id
                    ):
                        return self.async_abort(reason="wrong_account")
                for configured in self._async_current_entries():
                    if (
                        configured is not self._reauth_entry
                        and configured.data.get(CONF_CLOUD_PROVIDER, PROVIDER_THERMOWORKS)
                        == PROVIDER_THERMOWORKS
                        and configured.data.get(CONF_ACCOUNT_ID) == account_id
                    ):
                        return self.async_abort(reason="already_configured")
                data = {
                    **user_input,
                    CONF_CLOUD_PROVIDER: PROVIDER_THERMOWORKS,
                    CONF_ACCOUNT_ID: account_id,
                    CONF_RECOMMENDED_POLL_SECONDS: info[CONF_RECOMMENDED_POLL_SECONDS],
                }
                if self._reauth_entry is not None:
                    # Replace data, removing the old password; keep the entry/unique ID.
                    return self.async_update_reload_and_abort(
                        self._reauth_entry, data=data
                    )
                await self.async_set_unique_id(info["user"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=data)
        return self.async_show_form(
            step_id="api_key", data_schema=API_KEY_SCHEMA, errors=errors
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
                        min=minimum_scan_interval(
                            getattr(self.config_entry, "data", {})
                        ),
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
