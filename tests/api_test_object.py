"""Provides a local stand-in for the ThermoWorks API."""

from copy import deepcopy
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer
from thermoworks_cloud.models import ChannelStatus

TEST_API_KEY = "twk_test_key_id_test_secret"
TEST_ACCOUNT_ID = "test-account-id"
TEST_SERIAL = "12:34:56:78:90:AB"
TEST_ETAG = 'W/"test-etag"'

GET_ME_RESPONSE: dict[str, Any] = {
    "accountId": TEST_ACCOUNT_ID,
    "rateLimit": {"perMinute": 4, "perDay": 3000},
    "recommendedPollSeconds": 60,
}

# Actual response value structure, with the serial and labels replaced
GET_DEVICES_RESPONSE: dict[str, Any] = {
    "generatedAt": "2026-11-04T04:43:49.806Z",
    "devices": [
        {
            "id": TEST_SERIAL,
            "serial": TEST_SERIAL,
            "label": "Kitchen",
            "model": "node",
            "displayUnits": "F",
            "type": "datalogger",
            "firmware": "2.1.8-30",
            "locationId": None,
            "battery": 100,
            "batteryState": "discharging",
            "fan": None,
            "wifiSignal": -59,
            "gatewaySignal": None,
            "lastSeen": "2026-11-04T03:54:28.717Z",
            "nextExpectedConnection": None,
            "transmitIntervalSeconds": 3600,
            "channels": [
                {
                    "id": "1",
                    "number": 1,
                    "label": "Freezer",
                    "type": "Pro-Series",
                    "enabled": True,
                    "value": -10.3,
                    "units": "F",
                    "status": "NORMAL",
                    "probeFailed": False,
                    "alarming": False,
                    "alarmHigh": {"enabled": True, "value": 20, "alarming": False},
                    "alarmLow": {"enabled": True, "value": -12, "alarming": False},
                    "minimum": -13,
                    "maximum": 69.5,
                    "lastTelemetrySaved": "2026-11-04T03:55:17.000Z",
                    "lastSeen": "2026-11-04T03:54:28.717Z",
                }
            ],
        }
    ],
}


# Derived examples for channel-health behavior; not additional live captures.
# NO PROBE values come from the excerpt in issue #46, with representative surrounding data.
GET_DEVICES_NO_PROBE_RESPONSE = deepcopy(GET_DEVICES_RESPONSE)
GET_DEVICES_NO_PROBE_RESPONSE["devices"][0]["channels"][0].update({
    "status": ChannelStatus.NO_PROBE.value,
    "value": 76.8,
    "lastTelemetrySaved": "2026-09-09T12:49:36.000Z",
})
GET_DEVICES_FAILED_PROBE_RESPONSE = deepcopy(GET_DEVICES_RESPONSE)
GET_DEVICES_FAILED_PROBE_RESPONSE["devices"][0]["channels"][0]["probeFailed"] = True
GET_DEVICES_NULL_READING_RESPONSE = deepcopy(GET_DEVICES_RESPONSE)
GET_DEVICES_NULL_READING_RESPONSE["devices"][0]["channels"][0]["value"] = None
GET_DEVICES_NULL_UNITS_RESPONSE = deepcopy(GET_DEVICES_RESPONSE)
GET_DEVICES_NULL_UNITS_RESPONSE["devices"][0]["channels"][0].update({
    "status": ChannelStatus.NO_PROBE.value,
    "units": None,
})
GET_DEVICES_NO_CHANNELS_RESPONSE = deepcopy(GET_DEVICES_RESPONSE)
GET_DEVICES_NO_CHANNELS_RESPONSE["devices"][0]["channels"] = []
GET_DEVICES_DISABLED_CHANNEL_RESPONSE = deepcopy(GET_DEVICES_RESPONSE)
GET_DEVICES_DISABLED_CHANNEL_RESPONSE["devices"][0]["channels"][0]["enabled"] = False
GET_DEVICES_UNKNOWN_CHANNEL_METADATA_RESPONSE = deepcopy(GET_DEVICES_RESPONSE)
for _field in ("enabled", "probeFailed", "alarming", "lastTelemetrySaved", "lastSeen"):
    del GET_DEVICES_UNKNOWN_CHANNEL_METADATA_RESPONSE["devices"][0]["channels"][0][_field]
GET_DEVICES_DISTINCT_CHANNEL_ID_RESPONSE = deepcopy(GET_DEVICES_RESPONSE)
GET_DEVICES_DISTINCT_CHANNEL_ID_RESPONSE["devices"][0]["channels"][0]["id"] = "opaque-channel-id"
GET_DEVICES_LOW_ALARM_RESPONSE = deepcopy(GET_DEVICES_RESPONSE)
GET_DEVICES_LOW_ALARM_RESPONSE["devices"][0]["channels"][0].update({
    "status": ChannelStatus.LOW.value,
    "value": -13,
    "alarming": True,
})
GET_DEVICES_LOW_ALARM_RESPONSE["devices"][0]["channels"][0]["alarmLow"]["alarming"] = True


class ApiTestObject:
    """A real HTTP server that answers like the ThermoWorks API."""

    def __init__(self) -> None:
        """Create the server, which responds successfully until told otherwise."""
        app = web.Application()
        app.router.add_get("/api/v1/me", self._get_me)
        app.router.add_get("/api/v1/devices", self._get_devices)
        self.server = TestServer(app)
        self.devices_requests: list[web.Request] = []
        self.me_status = 200
        self.devices_status = 200
        self.devices_headers: dict[str, str] = {}
        self.devices_body: dict[str, Any] | None = GET_DEVICES_RESPONSE

    @property
    def base_url(self) -> str:
        """Return the root URL of the API."""
        return str(self.server.make_url("/api"))

    def respond_to_devices(
        self,
        status: int = 200,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Set the response to future requests for devices."""
        self.devices_status = status
        self.devices_body = body
        self.devices_headers = headers or {}

    async def _get_me(self, request: web.Request) -> web.Response:
        if self.me_status != 200:
            return web.json_response({"error": {"code": "test"}}, status=self.me_status)
        if request.headers.get("Authorization") != f"Bearer {TEST_API_KEY}":
            return web.json_response({"error": {"code": "invalid_api_key"}}, status=401)
        return web.json_response(GET_ME_RESPONSE)

    async def _get_devices(self, request: web.Request) -> web.Response:
        self.devices_requests.append(request)
        if self.devices_body is None:
            return web.Response(status=self.devices_status, headers=self.devices_headers)
        return web.json_response(
            self.devices_body, status=self.devices_status, headers=self.devices_headers
        )
