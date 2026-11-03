"""Constants for the Thermoworks Cloud integration."""

from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_API_KEY

DOMAIN = "thermoworks_cloud"
# Setting to 30 minutes to be nice to their servers
DEFAULT_SCAN_INTERVAL_SECONDS = 1800
# Just an arbitrary value
MIN_SCAN_INTERVAL_SECONDS = 5
# Also arbitrary: an upper bound (24 hours) so the options flow and the scan
# interval number entity agree on a maximum.
MAX_SCAN_INTERVAL_SECONDS = 86400

CONF_CLOUD_PROVIDER = "cloud_provider"
CONF_ACCOUNT_ID = "account_id"
CONF_RECOMMENDED_POLL_SECONDS = "recommended_poll_seconds"
API_MIN_SCAN_INTERVAL_SECONDS = 60
API_BASE_URL = "https://cloud.thermoworks.com/api/v1"


def minimum_scan_interval(data: Mapping[str, Any]) -> int:
    """Return the polling floor for this entry's authentication method."""
    if CONF_API_KEY in data:
        return max(
            API_MIN_SCAN_INTERVAL_SECONDS,
            data.get(CONF_RECOMMENDED_POLL_SECONDS, API_MIN_SCAN_INTERVAL_SECONDS),
        )
    return MIN_SCAN_INTERVAL_SECONDS

PROVIDER_THERMOWORKS = "thermoworks"
PROVIDER_ETI = "eti"

CLOUD_PROVIDERS = {
    PROVIDER_THERMOWORKS: {
        "name": "ThermoWorks Cloud",
        "api_key": None,  # Use library defaults
        "app_id": None,
        "referer": None,
    },
    PROVIDER_ETI: {
        "name": "ETI Cloud",
        "api_key": "AIzaSyBD4snlT2LllO4k0NywX5qYjJ7M7WfU4_I",
        "app_id": "1:701566661301:web:7a9bc711c05985ead144fc",
        "referer": "https://cloud.etiltd.com/",
    },
}
