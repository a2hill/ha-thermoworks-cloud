"""Read-only, API-key-authenticated ThermoWorks integrations client."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import time
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from thermoworks_cloud.models import Alarm, Fan

from .const import API_BASE_URL
from .models import ThermoworksChannel, ThermoworksDevice


class ApiError(Exception):
    """The supported API could not return a usable response."""


class ApiAuthError(ApiError):
    """The API key is invalid, expired, revoked or lacks access."""


class ApiRateLimited(ApiError):
    """The API requested a pause before another request."""


class IntegrationsApi:
    """Fetch complete snapshots without consumer Firebase authentication."""

    def __init__(self, session: ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key
        self._etag: str | None = None
        self._snapshot: dict[str, Any] | None = None
        self._retry_at = 0.0

    async def get_me(self) -> dict[str, Any]:
        """Validate the key and obtain its account and polling recommendation."""
        return await self._request("me")

    async def get_devices(self) -> dict[str, Any]:
        """Retrieve all devices/channels in one conditional request."""
        return await self._request("devices")

    async def _request(self, resource: str) -> dict[str, Any]:
        if time.monotonic() < self._retry_at:
            raise ApiRateLimited("API rate limit: waiting for Retry-After")
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if resource == "devices" and self._etag:
            headers["If-None-Match"] = self._etag
        try:
            async with self._session.get(
                f"{API_BASE_URL}/{resource}",
                headers=headers,
                timeout=ClientTimeout(total=30),
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise ApiAuthError("API key rejected; update the integration's key")
                if response.status == 429:
                    retry = response.headers.get("Retry-After", "60")
                    try:
                        seconds = float(retry)
                        if not math.isfinite(seconds):
                            raise ValueError
                    except ValueError:
                        try:
                            seconds = (
                                parsedate_to_datetime(retry)
                                - datetime.now(timezone.utc)
                            ).total_seconds()
                        except (TypeError, ValueError, OverflowError):
                            seconds = 60
                    self._retry_at = time.monotonic() + max(1, seconds)
                    raise ApiRateLimited("API rate limit exceeded; honoring Retry-After")
                if response.status == 304 and resource == "devices":
                    if self._snapshot is None:
                        raise ApiError("API returned 304 without a cached snapshot")
                    return self._snapshot
                if response.status != 200:
                    raise ApiError(f"API returned HTTP {response.status}")
                payload = await response.json()
                if not isinstance(payload, dict):
                    raise ApiError("API response is not a JSON object")
                if resource == "devices":
                    if not isinstance(payload.get("devices"), list):
                        raise ApiError("API snapshot is missing its devices array")
                    # Do not cache a malformed snapshot or its ETag.
                    parse_snapshot(payload)
                    self._snapshot = payload
                    self._etag = response.headers.get("ETag")
                return payload
        except (ClientError, TimeoutError, ValueError) as err:
            # Do not include response bodies or request headers in errors.
            raise ApiError("Unable to read the ThermoWorks API response") from err


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("API timestamp must include a timezone")
    return result


def _alarm(data: dict | None, units: str | None) -> Alarm | None:
    if data is None:
        return None
    return Alarm(
        enabled=data["enabled"],
        alarming=data["alarming"],
        value=data.get("value"),
        units=units,
    )

def _fan(data: dict | None) -> Fan | None:
    if data is None:
        return None
    return Fan(
        connected=data.get("connected"),
        connection=data.get("connected"),
        fan_channel=data.get("channel"),
        set_temp=data.get("setTemp"),
        state=data.get("state"),
    )


def parse_snapshot(
    payload: dict[str, Any],
) -> tuple[list[ThermoworksDevice], dict[str, list[ThermoworksChannel]]]:
    """Map public DTOs to existing entity models, retaining stable IDs."""
    devices: list[ThermoworksDevice] = []
    channels: dict[str, list[ThermoworksChannel]] = {}
    try:
        for raw in payload["devices"]:
            device_id = raw["id"]
            if not isinstance(device_id, str) or not device_id:
                raise ValueError("Missing device ID")
            wifi = raw.get("wifiSignal")
            gateway = raw.get("gatewaySignal")
            device = ThermoworksDevice(
                device_id=device_id,
                serial=raw.get("serial") or device_id,
                label=raw.get("label"),
                device_name=raw.get("model") or raw.get("type"),
                device_display_units=raw.get("displayUnits"),
                firmware=raw.get("firmware"),
                battery=raw.get("battery"),
                battery_state=raw.get("batteryState"),
                fan=_fan(raw.get("fan")),
                wifi_strength=wifi,
                signal_strength=gateway if gateway is not None else wifi,
                last_seen=_timestamp(raw.get("lastSeen")),
                transmit_interval_in_seconds=raw.get("transmitIntervalSeconds"),
            )
            devices.append(device)
            channels[device_id] = []
            for channel in raw["channels"]:
                channel_id = channel["id"]
                if not isinstance(channel_id, str) or not channel_id:
                    raise ValueError("Missing channel ID")
                units = channel.get("units")
                # Legacy entity IDs used the channel number, not its document ID.
                number = channel.get("number")
                channels[device_id].append(
                    ThermoworksChannel(
                        number=str(number) if number is not None else channel_id,
                        value=channel.get("value"),
                        units=units,
                        status=channel.get("status"),
                        label=channel.get("label"),
                        alarm_high=_alarm(channel.get("alarmHigh"), units),
                        alarm_low=_alarm(channel.get("alarmLow"), units),
                        last_telemetry_saved=_timestamp(channel.get("lastTelemetrySaved")),
                        enabled=channel["enabled"],
                        probe_failed=channel["probeFailed"],
                    )
                )
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise ApiError("Invalid device/channel data in API snapshot") from err
    return devices, channels
