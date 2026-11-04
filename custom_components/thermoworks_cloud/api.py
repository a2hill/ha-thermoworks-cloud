"""Client for the ThermoWorks Cloud Integrations API.

ThermoWorks enabled Firebase App Check on their cloud in November 2026, which ended the
email/password sign-in this integration used. They now publish a read-only REST API for home
automation that takes a per-user API key, created in the ThermoWorks Cloud web app under
Account -> Integrations.

Docs: https://cloud.thermoworks.com/api/docs/
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Optional

import aiohttp

API_BASE_URL = "https://cloud.thermoworks.com/api"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class ThermoworksApiError(Exception):
    """Base error for the ThermoWorks Integrations API."""


class InvalidApiKeyError(ThermoworksApiError):
    """The API key is missing, invalid, revoked or expired."""


class RateLimitedError(ThermoworksApiError):
    """The API key has exceeded its rate limit."""

    def __init__(self, message: str, retry_after: int | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class CannotConnectError(ThermoworksApiError):
    """The API could not be reached."""


# --- Data models --------------------------------------------------------------------------
# Attribute names match the old thermoworks_cloud library models, so the entity code and the
# entity unique_ids built from them stay the same.


@dataclass
class Alarm:
    """A channel alarm."""

    enabled: Optional[bool] = None
    alarming: Optional[bool] = None
    value: Optional[float] = None
    units: Optional[str] = None


@dataclass
class Fan:
    """A fan accessory. The Integrations API does not expose fans yet."""

    STATE_NAMES: ClassVar[dict[int, str]] = {0: "Paused", 1: "Blowing", 2: "Pulsing"}

    connected: Optional[bool] = None
    connection: Optional[bool] = None
    fan_channel: Optional[str] = None
    set_temp: Optional[int] = None
    state: Optional[int] = None

    @property
    def state_name(self) -> Optional[str]:
        """Return the ThermoWorks app name for the current fan state."""
        if self.state is None:
            return None
        return self.STATE_NAMES.get(self.state)


@dataclass
class DeviceChannel:
    """A device channel with its latest reading."""

    number: Optional[str] = None
    id: Optional[str] = None
    value: Optional[float] = None
    units: Optional[str] = None
    status: Optional[str] = None
    type: Optional[str] = None
    label: Optional[str] = None
    enabled: Optional[bool] = None
    probe_failed: Optional[bool] = None
    alarming: Optional[bool] = None
    alarm_high: Optional[Alarm] = None
    alarm_low: Optional[Alarm] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    last_telemetry_saved: Optional[datetime] = None
    last_seen: Optional[datetime] = None


@dataclass
class Device:
    """A device and its channels."""

    device_id: Optional[str] = None
    serial: Optional[str] = None
    label: Optional[str] = None
    device_name: Optional[str] = None
    type: Optional[str] = None
    firmware: Optional[str] = None
    location_id: Optional[str] = None
    battery: Optional[float] = None
    battery_state: Optional[str] = None
    wifi_strength: Optional[float] = None
    gateway_rssi: Optional[float] = None
    device_display_units: Optional[str] = None
    fan: Optional[Fan] = None
    last_seen: Optional[datetime] = None
    next_expected_connection: Optional[datetime] = None
    transmit_interval_in_seconds: Optional[int] = None
    channels: Optional[list[DeviceChannel]] = None

    @property
    def signal_strength(self) -> Optional[float]:
        """Gateway signal for RFX devices, otherwise Wi-Fi signal (same rule as the old library)."""
        return self.gateway_rssi if self.gateway_rssi is not None else self.wifi_strength


@dataclass
class ApiKeyInfo:
    """What GET /v1/me says about the key."""

    account_id: Optional[str]
    key_id: Optional[str]
    key_name: Optional[str]
    device_ids: Optional[list[str]]
    api_tier: Optional[str]
    per_minute: Optional[int]
    per_day: Optional[int]
    recommended_poll_seconds: Optional[int]


# --- Parsing ------------------------------------------------------------------------------


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_alarm(data: Any, units: Optional[str]) -> Optional[Alarm]:
    if not isinstance(data, dict):
        return None
    return Alarm(
        enabled=data.get("enabled"),
        alarming=data.get("alarming"),
        value=data.get("value"),
        units=units,
    )


def parse_channel(data: dict) -> DeviceChannel:
    """Build a DeviceChannel from an API channel object."""
    units = data.get("units")
    number = data.get("number")
    # The old Firestore data keyed channels by a 1-based number held as a string; unique_ids
    # are built from it, so keep it a string. Fall back to the channel id if number is absent.
    number_str = str(number) if number is not None else data.get("id")
    value = data.get("value")
    return DeviceChannel(
        number=number_str,
        id=data.get("id"),
        value=float(value) if isinstance(value, (int, float)) else None,
        units=units,
        status=data.get("status"),
        type=data.get("type"),
        label=data.get("label"),
        enabled=data.get("enabled"),
        probe_failed=data.get("probeFailed"),
        alarming=data.get("alarming"),
        alarm_high=_parse_alarm(data.get("alarmHigh"), units),
        alarm_low=_parse_alarm(data.get("alarmLow"), units),
        minimum=data.get("minimum"),
        maximum=data.get("maximum"),
        last_telemetry_saved=_parse_datetime(data.get("lastTelemetrySaved")),
        last_seen=_parse_datetime(data.get("lastSeen")),
    )


def parse_device(data: dict) -> Device:
    """Build a Device from an API device object."""
    interval = data.get("transmitIntervalSeconds")
    return Device(
        device_id=data.get("id"),
        serial=data.get("serial") or data.get("id"),
        label=data.get("label"),
        device_name=data.get("model") or data.get("type"),
        type=data.get("type"),
        firmware=data.get("firmware"),
        location_id=data.get("locationId"),
        battery=data.get("battery"),
        battery_state=data.get("batteryState"),
        device_display_units=data.get("displayUnits"),
        wifi_strength=data.get("wifiSignal"),
        gateway_rssi=data.get("gatewaySignal"),
        last_seen=_parse_datetime(data.get("lastSeen")),
        next_expected_connection=_parse_datetime(data.get("nextExpectedConnection")),
        transmit_interval_in_seconds=int(interval) if isinstance(interval, (int, float)) else None,
        channels=[parse_channel(c) for c in data.get("channels") or [] if isinstance(c, dict)],
    )


# --- Client -------------------------------------------------------------------------------


class ThermoworksApiClient:
    """Read-only client for https://cloud.thermoworks.com/api/v1."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key.strip()
        self._devices_etag: str | None = None
        self._devices_cache: list[Device] | None = None

    async def _get(self, path: str, etag: str | None = None) -> tuple[int, dict | None, str | None]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        if etag:
            headers["If-None-Match"] = etag
        try:
            async with self._session.get(
                f"{API_BASE_URL}{path}", headers=headers, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status == 304:
                    return 304, None, etag
                body: dict | None = None
                try:
                    body = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    body = None
                message = _error_message(body) or f"HTTP {resp.status}"
                if resp.status == 401:
                    raise InvalidApiKeyError(message)
                if resp.status == 403:
                    # insufficient_scope: a valid key that cannot read this resource
                    raise InvalidApiKeyError(message)
                if resp.status == 429:
                    retry = resp.headers.get("Retry-After")
                    raise RateLimitedError(message, int(retry) if retry and retry.isdigit() else None)
                if resp.status >= 400:
                    raise ThermoworksApiError(f"{path}: {message}")
                return resp.status, body, resp.headers.get("ETag")
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as err:
            raise CannotConnectError(str(err) or type(err).__name__) from err

    async def get_me(self) -> ApiKeyInfo:
        """Describe the key, plan tier and rate limits."""
        _, body, _ = await self._get("/v1/me")
        body = body or {}
        key = body.get("apiKey") or {}
        plan = body.get("plan") or {}
        rate = body.get("rateLimit") or {}
        return ApiKeyInfo(
            account_id=body.get("accountId"),
            key_id=key.get("id"),
            key_name=key.get("name"),
            device_ids=key.get("deviceIds"),
            api_tier=plan.get("apiTier"),
            per_minute=rate.get("perMinute"),
            per_day=rate.get("perDay"),
            recommended_poll_seconds=body.get("recommendedPollSeconds"),
        )

    async def get_devices(self) -> list[Device]:
        """Return every device the key can see, with all channels, in one request."""
        status, body, etag = await self._get("/v1/devices", self._devices_etag)
        if status == 304 and self._devices_cache is not None:
            return self._devices_cache
        devices = [
            parse_device(d) for d in (body or {}).get("devices") or [] if isinstance(d, dict)
        ]
        self._devices_etag = etag
        self._devices_cache = devices
        return devices


def _error_message(body: Any) -> str | None:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        err = body["error"]
        code = err.get("code")
        msg = err.get("message")
        return f"{code}: {msg}" if code and msg else (msg or code)
    return None
