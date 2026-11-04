"""Constants for the Thermoworks Cloud integration."""

DOMAIN = "thermoworks_cloud"
# NODE devices transmit every 30 minutes by default; others about once a minute.
# Five minutes keeps readings reasonably fresh well inside the free tier (4/min, 3,000/day per key).
DEFAULT_SCAN_INTERVAL_SECONDS = 300
# The API caches responses for 15 s and asks integrations not to poll faster than every 60 s.
MIN_SCAN_INTERVAL_SECONDS = 60
# An upper bound (24 hours) so the options flow and the scan interval number entity agree.
MAX_SCAN_INTERVAL_SECONDS = 86400
