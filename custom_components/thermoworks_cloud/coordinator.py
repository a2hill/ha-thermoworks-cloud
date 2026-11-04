"""Coordinates data updates from the Thermoworks Cloud API."""

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    InvalidApiKeyError,
    RateLimitedError,
    ThermoworksApiClient,
    ThermoworksApiError,
)
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN, MIN_SCAN_INTERVAL_SECONDS
from .exceptions import MissingRequiredAttributeError
from .models import ThermoworksDevice, ThermoworksChannel

_LOGGER: logging.Logger = logging.getLogger(__package__)


@dataclass
class ThermoworksData:
    """Class to hold data retrieved from the Thermoworks Cloud API."""

    # List of devices retreived for the user
    devices: list[ThermoworksDevice]
    # Map of DeviceChannel's indexed by device id
    device_channels: dict[str, list[ThermoworksChannel]]


class ThermoworksCoordinator(DataUpdateCoordinator[ThermoworksData]):
    """Coordinate device updates from Thermoworks Cloud."""

    api: ThermoworksApiClient
    data: ThermoworksData

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""

        api_key = config_entry.data.get(CONF_API_KEY)
        if not api_key:
            # Entries created before ThermoWorks moved to API keys hold an email and password,
            # which can no longer sign in. Ask for a key through the reauth flow.
            raise ConfigEntryAuthFailed(
                "ThermoWorks Cloud now requires an API key. Create one in the ThermoWorks "
                "Cloud web app under Account -> Integrations."
            )

        # Stay inside the API rate limits however low the option was set before.
        self.poll_interval = max(
            int(config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)),
            MIN_SCAN_INTERVAL_SECONDS,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            update_method=self.async_update_data,
            update_interval=timedelta(seconds=self.poll_interval),
        )
        self.api = ThermoworksApiClient(async_get_clientsession(hass), api_key)

    async def async_update_data(self) -> ThermoworksData:
        """Fetch every device and channel in one call to GET /v1/devices."""

        _LOGGER.debug(
            "Polling ThermoWorks Cloud API (interval: %s seconds)", self.poll_interval
        )

        try:
            api_devices = await self.api.get_devices()
        except InvalidApiKeyError as err:
            raise ConfigEntryAuthFailed(
                f"ThermoWorks Cloud rejected the API key: {err}") from err
        except RateLimitedError as err:
            raise UpdateFailed(
                f"ThermoWorks Cloud rate limit reached; retry after {err.retry_after}s") from err
        except ThermoworksApiError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        _LOGGER.debug("Retrieved %d devices", len(api_devices))

        devices: list[ThermoworksDevice] = []
        device_channels_by_device: dict[str, list[ThermoworksChannel]] = {}

        for api_device in api_devices:
            try:
                device = ThermoworksDevice.from_api_device(api_device)
            except MissingRequiredAttributeError as err:
                _LOGGER.error("Device %s: %s", api_device.device_id, err)
                continue
            devices.append(device)

            device_channels: list[ThermoworksChannel] = []
            for api_channel in api_device.channels or []:
                if api_channel.enabled is False:
                    continue
                try:
                    device_channels.append(
                        ThermoworksChannel.from_api_channel(api_channel))
                except MissingRequiredAttributeError as err:
                    _LOGGER.debug("Channel %s for device %s: %s",
                                  api_channel.number, device.display_name(), err)

            device_channels_by_device[device.get_identifier()] = device_channels
            _LOGGER.debug("Found %d channels for device %s",
                          len(device_channels), device.display_name())

        return ThermoworksData(
            devices=devices,
            device_channels=device_channels_by_device,
        )

    def get_device_by_id(self, device_id: str) -> ThermoworksDevice | None:
        """Return device by device id or serial."""
        # Called by the battery sensor to get its updated data from self.data
        for device in self.data.devices:
            if device.get_identifier() == device_id:
                return device

        return None

    def get_device_channel_by_id(
        self, device_id: str, channel_id: str
    ) -> ThermoworksChannel | None:
        """Return device channel by device id and channel id."""
        # Called by the temperature sensors to get their updated data from self.data

        for device_channel in self.data.device_channels.get(device_id, []):
            if device_channel.number == channel_id:
                return device_channel

        return None
