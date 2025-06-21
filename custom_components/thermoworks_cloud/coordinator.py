"""Coordinates data updates from the Thermoworks Cloud API."""

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from thermoworks_cloud import AuthFactory, ThermoworksCloud, ResourceNotFoundError

from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN
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

    auth_factory: AuthFactory
    api: ThermoworksCloud | None
    data: ThermoworksData

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""

        # Set variables from values entered in config flow setup
        self.email = config_entry.data[CONF_EMAIL]
        self.password = config_entry.data[CONF_PASSWORD]

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
        self.auth_factory = AuthFactory(client_session)
        self.api = None

    async def async_update_data(self) -> ThermoworksData:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """

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

            devices: list[ThermoworksDevice] = []
            device_channels_by_device: dict[str, list[ThermoworksChannel]] = {}

            user = await self.api.get_user()
            _LOGGER.debug("Retrieved user data: %s", user)

            if user.account_id is None:
                raise UpdateFailed("No account ID found for user")

            api_devices = await self.api.get_devices(user.account_id)
            _LOGGER.debug("Retrieved %d devices for user", len(api_devices))

            for api_device in api_devices:
                try:
                    device = ThermoworksDevice.from_api_device(api_device)
                    devices.append(device)
                    _LOGGER.debug("Retrieved device %s", device.display_name())
                except MissingRequiredAttributeError as err:
                    _LOGGER.error("Device %s: %s", api_device, err)
                    # Skip this device as it's missing critical data
                    continue

                device_channels = []
                # According to the observed behavior, channels seem to be 1 indexed
                for channel in range(1, 10):
                    try:
                        api_channel = await self.api.get_device_channel(
                            device_serial=device.serial,
                            channel=str(channel)
                        )
                        try:
                            channel_data = ThermoworksChannel.from_api_channel(
                                api_channel)
                            device_channels.append(channel_data)
                            _LOGGER.debug(
                                "Retrieved channel %s for device %s",
                                channel_data.display_name(), device.display_name())
                        except MissingRequiredAttributeError as err:
                            _LOGGER.error("Channel %s for device %s: %s",
                                          channel, device.display_name(), err)
                            # Skip this channel as it's missing critical data
                    except ResourceNotFoundError:
                        _LOGGER.debug("No more channels found for device %s after channel %s",
                                      device.display_name(), channel-1)
                        # Go until there are no more
                        break
                    except Exception as channel_err:
                        _LOGGER.error("Error fetching channel %s for device %s: %s",
                                      channel, device.display_name(), channel_err)
                        # Continue with next channel
                        continue

                device_channels_by_device[device.get_identifier()] = device_channels
                _LOGGER.debug("Found %d channels for device %s",
                              len(device_channels), device.display_name())

        except Exception as err:
            # This will show entities as unavailable by raising UpdateFailed exception
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        _LOGGER.debug(
            "Update completed: %d devices with data retrieved", len(devices))

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
