"""Coordinates data updates from the Thermoworks Cloud API."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from thermoworks_cloud import (
    AuthFactory,
    ApiAuthenticationError,
    RateLimitError,
    ThermoworksCloud,
    ThermoworksClient,
    ResourceNotFoundError,
)
from thermoworks_cloud.models import Device, DeviceChannel

from .const import (
    CLOUD_PROVIDERS,
    CONF_API_KEY,
    CONF_CLOUD_PROVIDER,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    PROVIDER_THERMOWORKS,
)
from .exceptions import MissingRequiredAttributeError
from .models import ThermoworksChannel, ThermoworksDevice

_LOGGER: logging.Logger = logging.getLogger(__package__)


@dataclass
class ThermoworksData:
    """Devices parsed from the latest API response."""

    # Keyed by device identifier (see ThermoworksDevice.get_identifier), so entities can
    # look up their device directly. Each device holds its own channels and fan.
    devices: dict[str, ThermoworksDevice] = field(default_factory=dict)


def _api_device_name(api_device: Device) -> str:
    """Return a readable name for a device that hasn't been parsed yet, for logging.

    Mirrors ThermoworksDevice.display_name(), but nothing is required yet, so every
    field has a fallback.
    """
    device_type = api_device.device_name or api_device.type or "unknown device"
    return f"{api_device.label or "unnamed device"} ({device_type} - {api_device.serial or "no serial"})"


def _parse_device(
    api_device: Device, api_channels: Iterable[DeviceChannel]
) -> ThermoworksDevice | None:
    """Parse a device and its channels, or return None if the device can't be used.

    A channel that can't be parsed is logged and left out, without dropping the device.
    """
    channels = []
    for api_channel in api_channels:
        try:
            channels.append(ThermoworksChannel.from_api_channel(api_channel))
        except MissingRequiredAttributeError as err:
            _LOGGER.error("Skipping channel %s (Ch. %s) for device %s, missing: %s",
                          api_channel.label or "unnamed channel", api_channel.number,
                          _api_device_name(api_device),
                          ", ".join(err.missing_attributes))
    try:
        return ThermoworksDevice.from_api_device(api_device, channels)
    except MissingRequiredAttributeError as err:
        _LOGGER.error("Skipping device %s, missing: %s",
                      _api_device_name(api_device), ", ".join(err.missing_attributes))
        return None


class ThermoworksCoordinator(DataUpdateCoordinator[ThermoworksData]):
    """Coordinate device updates from Thermoworks Cloud."""

    auth_factory: AuthFactory
    api: ThermoworksCloud | None
    data: ThermoworksData

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""

        # Set variables from values entered in config flow setup
        self.email = config_entry.data.get(CONF_EMAIL)
        self.password = config_entry.data.get(CONF_PASSWORD)
        self.provider = config_entry.data.get(CONF_CLOUD_PROVIDER, PROVIDER_THERMOWORKS)

        # set variables from options.  You need a default here incase options have not been set
        self.poll_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
        )

        # Initialise DataUpdateCoordinator
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            # Method to call on every update interval.
            update_method=self.async_update_data,
            # Polling interval. Will only be polled if there are subscribers.
            # Using config option here but you can just use a value.
            update_interval=timedelta(seconds=self.poll_interval),
        )
        client_session = async_get_clientsession(hass)
        self.client: ThermoworksClient | None = None
        if self.provider == PROVIDER_THERMOWORKS and config_entry.data.get(CONF_API_KEY):
            self.client = ThermoworksClient(
                client_session, config_entry.data[CONF_API_KEY],
                base_url=CLOUD_PROVIDERS[self.provider]["base_url"],
            )
            self.auth_factory = None
        else:
            provider_config = CLOUD_PROVIDERS[self.provider]
            self.auth_factory = AuthFactory(
                client_session,
                api_key=provider_config["api_key"],
                app_id=provider_config["app_id"],
                referer=provider_config["referer"],
            )
        self.api = None

    async def async_update_data(self) -> ThermoworksData:
        """Fetch data from the API and parse it into devices keyed by identifier.

        Parsing happens once here, so entities only read typed data (see models.py).
        """

        _LOGGER.debug(
            "Polling ThermoWorks Cloud API (interval: %s seconds)", self.poll_interval
        )
        if self.provider == PROVIDER_THERMOWORKS and self.client is None:
            raise ConfigEntryAuthFailed(
                "ThermoWorks now requires an integrations API key"
            )
        if self.client is not None:
            return await self._async_update_api_data()

        try:
            if self.api is None:
                # Do not need to worry about invalid credentials here as they have been
                # validated during the config_flow
                _LOGGER.debug(
                    "Initializing Thermoworks Cloud API connection for %s", self.email)
                auth = await self.auth_factory.build_auth(
                    self.email, password=self.password
                )
                self.api = ThermoworksCloud(auth)
                _LOGGER.debug(
                    "Successfully authenticated with Thermoworks Cloud API")

            data = ThermoworksData()

            user = await self.api.get_user()
            _LOGGER.debug("Retrieved user data: %s", user)

            if user.account_id is None:
                raise UpdateFailed("No account ID found for user")

            api_devices = await self.api.get_devices(user.account_id)
            _LOGGER.debug("Retrieved %d devices for user", len(api_devices))

            for api_device in api_devices:
                if api_device.serial is None:
                    _LOGGER.error("Skipping device %s, missing: serial",
                                  _api_device_name(api_device))
                    # Channels are fetched by serial, so there's nothing more to read
                    continue

                api_channels = []
                # According to the observed behavior, channels seem to be 1 indexed
                for channel in range(1, 10):
                    try:
                        api_channels.append(await self.api.get_device_channel(
                            device_serial=api_device.serial,
                            channel=str(channel)
                        ))
                    except ResourceNotFoundError:
                        _LOGGER.debug("No more channels found for device %s after channel %s",
                                      _api_device_name(api_device), channel-1)
                        # Go until there are no more
                        break
                    except Exception as channel_err:
                        _LOGGER.error("Error fetching channel %s for device %s: %s",
                                      channel, _api_device_name(api_device), channel_err)
                        # Continue with next channel
                        continue

                device = _parse_device(api_device, api_channels)
                if device is not None:
                    data.devices[device.get_identifier()] = device
                    _LOGGER.debug("Found %d channels for device %s",
                                  len(device.channels), device.display_name())

        except Exception as err:
            # This will show entities as unavailable by raising UpdateFailed exception
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        _LOGGER.debug(
            "Update completed: %d devices with data retrieved", len(data.devices))

        return data

    async def _async_update_api_data(self) -> ThermoworksData:
        """Fetch all devices and their channels in a single ThermoWorks API request."""
        assert self.client is not None
        try:
            api_devices = await self.client.get_devices()
        except ApiAuthenticationError as err:
            raise ConfigEntryAuthFailed("ThermoWorks API key was rejected") from err
        except RateLimitError as err:
            raise UpdateFailed(
                f"Error communicating with API: {err}", retry_after=err.retry_after
            ) from err
        except Exception as err:
            # This will show entities as unavailable by raising UpdateFailed exception
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        data = ThermoworksData()
        for api_device in api_devices:
            device = _parse_device(api_device, api_device.channels or [])
            if device is not None:
                data.devices[device.get_identifier()] = device

        _LOGGER.debug("Update completed: %d devices with data retrieved", len(data.devices))
        return data
