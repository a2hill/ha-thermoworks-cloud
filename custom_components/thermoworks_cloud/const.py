"""Constants for the Thermoworks Cloud integration."""

DOMAIN = "thermoworks_cloud"
# Setting to 30 minutes to be nice to their servers
DEFAULT_SCAN_INTERVAL_SECONDS = 1800
# The ThermoWorks API caches responses for 15 seconds, so polling faster can't return new data.
# This also matches its free plan's limit of 4 requests per minute. Most devices report far less
# often, and the free plan's daily limit is only sustainable at around 30 seconds.
MIN_SCAN_INTERVAL_SECONDS = 15
# Also arbitrary: an upper bound (24 hours) so the options flow and the scan
# interval number entity agree on a maximum.
MAX_SCAN_INTERVAL_SECONDS = 86400

CONF_CLOUD_PROVIDER = "cloud_provider"
CONF_API_KEY = "api_key"

PROVIDER_THERMOWORKS = "thermoworks"
PROVIDER_ETI = "eti"

CLOUD_PROVIDERS = {
    PROVIDER_THERMOWORKS: {
        "name": "ThermoWorks Cloud",
        "base_url": "https://cloud.thermoworks.com/api",
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
