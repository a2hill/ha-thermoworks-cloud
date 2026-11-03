"""API key setup, reauthentication and ETI compatibility tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_API_KEY, CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL

from custom_components.thermoworks_cloud.api import ApiAuthError, ApiError, ApiRateLimited
from custom_components.thermoworks_cloud.config_flow import (
    CannotConnect,
    ConfigFlow,
    InvalidAuth,
    OptionsFlowHandler,
    validate_input,
)
from custom_components.thermoworks_cloud.const import (
    CONF_ACCOUNT_ID,
    CONF_CLOUD_PROVIDER,
    CONF_RECOMMENDED_POLL_SECONDS,
)

MODULE = "custom_components.thermoworks_cloud.config_flow"
INFO = {
    "title": "ThermoWorks Cloud",
    "user": "thermoworks:account123",
    CONF_ACCOUNT_ID: "account123",
    CONF_RECOMMENDED_POLL_SECONDS: 60,
}


def flow_with_mocks():
    flow = ConfigFlow()
    flow.hass = MagicMock()
    flow.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
    flow.async_abort = MagicMock(side_effect=lambda **kwargs: kwargs)
    flow.async_create_entry = MagicMock(side_effect=lambda **kwargs: kwargs)
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow._async_current_entries = MagicMock(return_value=[])
    return flow


def test_provider_selection_routes_thermoworks_to_key_and_eti_to_password():
    for provider, step in [("thermoworks", "api_key"), ("eti", "credentials")]:
        flow = flow_with_mocks()
        result = asyncio.run(flow.async_step_user({CONF_CLOUD_PROVIDER: provider}))
        assert result["step_id"] == step


def test_key_validation_uses_me_not_firebase():
    with (
        patch(f"{MODULE}.async_get_clientsession"),
        patch(f"{MODULE}._build_auth_factory") as legacy,
        patch(f"{MODULE}.IntegrationsApi") as api,
    ):
        api.return_value.get_me = AsyncMock(
            return_value={"accountId": "account123", "recommendedPollSeconds": 60}
        )
        result = asyncio.run(
            validate_input(MagicMock(), {CONF_API_KEY: "test-key"}, "thermoworks")
        )
        assert result == INFO
        legacy.assert_not_called()
        api.return_value.get_me.assert_awaited_once()


@pytest.mark.parametrize("error,expected", [
    (ApiAuthError("revoked"), InvalidAuth),
    (ApiRateLimited("retry"), ApiRateLimited),
    (ApiError("bad response"), CannotConnect),
])
def test_validation_error_classification(error, expected):
    with (
        patch(f"{MODULE}.async_get_clientsession"),
        patch(f"{MODULE}.IntegrationsApi") as api,
    ):
        api.return_value.get_me = AsyncMock(side_effect=error)
        with pytest.raises(expected):
            asyncio.run(
                validate_input(MagicMock(), {CONF_API_KEY: "test-key"}, "thermoworks")
            )


def test_new_entry_stores_account_and_recommendation_without_password():
    flow = flow_with_mocks()
    with patch(f"{MODULE}.validate_input", AsyncMock(return_value=INFO)):
        result = asyncio.run(flow.async_step_api_key({CONF_API_KEY: " test-key "}))
    assert result["data"] == {
        CONF_API_KEY: "test-key",
        CONF_CLOUD_PROVIDER: "thermoworks",
        CONF_ACCOUNT_ID: "account123",
        CONF_RECOMMENDED_POLL_SECONDS: 60,
    }
    flow.async_set_unique_id.assert_awaited_once_with("thermoworks:account123")


@pytest.mark.parametrize("error,code", [
    (InvalidAuth(), "invalid_auth"),
    (CannotConnect(), "cannot_connect"),
    (ApiRateLimited(), "rate_limited"),
])
def test_key_form_reports_actionable_errors(error, code):
    flow = flow_with_mocks()
    with patch(f"{MODULE}.validate_input", AsyncMock(side_effect=error)):
        result = asyncio.run(flow.async_step_api_key({CONF_API_KEY: "test-key"}))
    assert result["errors"] == {"base": code}


def test_legacy_reauth_replaces_password_without_changing_entry_or_unique_id():
    flow = flow_with_mocks()
    entry = SimpleNamespace(
        entry_id="original-entry",
        unique_id="original-firebase-uid",
        data={CONF_EMAIL: "test@example.invalid", CONF_PASSWORD: "old-password"},
    )
    flow.context = {"entry_id": entry.entry_id}
    flow.hass.config_entries.async_get_entry.return_value = entry
    with patch(f"{MODULE}.validate_input", AsyncMock(return_value=INFO)):
        result = asyncio.run(flow.async_step_reauth(entry.data))
        assert result["step_id"] == "api_key"
        # Use the actual HA helper, mocking only its final UI abort.
        result = asyncio.run(flow.async_step_api_key({CONF_API_KEY: "new-key"}))
    assert result["reason"] == "reauth_successful"
    update = flow.hass.config_entries.async_update_entry.call_args.kwargs
    assert update["entry"] is entry
    assert CONF_PASSWORD not in update["data"]
    assert CONF_EMAIL not in update["data"]
    assert update["data"][CONF_API_KEY] == "new-key"
    # HA's UNDEFINED sentinel leaves the original unique ID unchanged.
    from homeassistant.config_entries import UNDEFINED
    assert update["unique_id"] is UNDEFINED
    flow.hass.config_entries.async_schedule_reload.assert_called_once_with("original-entry")
    flow.async_set_unique_id.assert_not_called()


def test_reauth_rejects_different_account():
    flow = flow_with_mocks()
    flow._reauth_entry = SimpleNamespace(data={CONF_ACCOUNT_ID: "different"})
    with patch(f"{MODULE}.validate_input", AsyncMock(return_value=INFO)):
        result = asyncio.run(flow.async_step_api_key({CONF_API_KEY: "test-key"}))
    assert result["reason"] == "wrong_account"
    flow.hass.config_entries.async_update_entry.assert_not_called()


def test_duplicate_account_rejected_even_with_different_key():
    flow = flow_with_mocks()
    flow._async_current_entries.return_value = [
        SimpleNamespace(data={CONF_ACCOUNT_ID: "account123"})
    ]
    with patch(f"{MODULE}.validate_input", AsyncMock(return_value=INFO)):
        result = asyncio.run(flow.async_step_api_key({CONF_API_KEY: "another-key"}))
    assert result["reason"] == "already_configured"


def test_eti_validation_keeps_legacy_login():
    auth = SimpleNamespace(user_id="eti-user")
    with (
        patch(f"{MODULE}._build_auth_factory") as factory,
        patch(f"{MODULE}.ThermoworksCloud") as cloud,
        patch(f"{MODULE}.IntegrationsApi") as supported_api,
    ):
        factory.return_value.build_auth = AsyncMock(return_value=auth)
        cloud.return_value.get_user = AsyncMock()
        result = asyncio.run(validate_input(
            MagicMock(),
            {CONF_EMAIL: "test@example.invalid", CONF_PASSWORD: "test-password"},
            "eti",
        ))
        assert result["user"] == "eti-user"
        supported_api.assert_not_called()


def test_options_flow_enforces_key_polling_floor():
    flow = OptionsFlowHandler()
    with (
        patch.object(OptionsFlowHandler, "config_entry", SimpleNamespace(
            data={CONF_API_KEY: "test-key", CONF_RECOMMENDED_POLL_SECONDS: 90},
            options={},
        )),
        patch.object(flow, "async_show_form", side_effect=lambda **kwargs: kwargs),
    ):
        result = asyncio.run(flow.async_step_init())
    assert result["data_schema"]({CONF_SCAN_INTERVAL: 5})[CONF_SCAN_INTERVAL] == 90
