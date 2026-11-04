"""Configures pytest for the tests that run against a real Home Assistant."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.thermoworks_cloud.const import CLOUD_PROVIDERS, PROVIDER_THERMOWORKS
from tests.api_test_object import ApiTestObject


@pytest.fixture(name="api_test_object")
async def fixture_api_test_object(
    enable_custom_integrations: Any, socket_enabled: Any
) -> AsyncIterator[ApiTestObject]:
    """Point the integration at a local server standing in for the ThermoWorks API."""
    api_test_object = ApiTestObject()
    await api_test_object.server.start_server()
    provider = {**CLOUD_PROVIDERS[PROVIDER_THERMOWORKS], "base_url": api_test_object.base_url}
    with patch.dict(CLOUD_PROVIDERS, {PROVIDER_THERMOWORKS: provider}):
        yield api_test_object
    await api_test_object.server.close()
