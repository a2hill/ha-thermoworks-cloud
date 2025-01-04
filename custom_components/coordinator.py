"""Coordinates data updates from the Thermoworks Cloud API."""

from dataclasses import dataclass
import logging
from typing import Any, TypedDict

from homeassistant.components.sensor import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from thermoworks_cloud import AuthFactory, ThermoworksCloud
from thermoworks_cloud.models import Device, DeviceChannel

from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class ThermoworksData(TypedDict):
    """Class to hold data retrieved from the Thermoworks Cloud API."""

    # List of devices retreived for the user
    devices: list[Device]
    # Map of DeviceChannel's indexed by device id
    device_channels: dict[str, list[DeviceChannel]]


class ThermoworksCoordinator(DataUpdateCoordinator):
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

    async def async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """

        try:
            if self.api is None:
                # Do not need to worry about invalid credentials here as they have been
                # validated during the config_flow
                auth = await self.auth_factory.build_auth(
                    self.email, password=self.password
                )
                self.api = ThermoworksCloud(auth)

            devices: list[Device] = []
            device_channels_by_device: dict[str, list[DeviceChannel]] = {}

            user = await self.api.get_user()
            device_serials = [
                device_order_item.device_id
                for device_order_item in user.device_order[user.account_id]
            ]

            for device_serial in device_serials:
                device = await self.api.get_device(device_serial)
                devices.append(device)

                device_channels = []
                # According to reverse engineering, channels seem to be 1 indexed
                for channel in range(1, 10):
                    try:
                        device_channels.append(
                            await self.api.get_device_channel(
                                device_serial=device_serial, channel=str(channel)
                            )
                        )
                    except RuntimeError:
                        break

                device_channels_by_device[device_serial] = device_channels

        except Exception as err:
            # This will show entities as unavailable by raising UpdateFailed exception
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        # What is returned here is stored in self.data by the DataUpdateCoordinator
        return {
            "devices": devices,
            "device_channels": device_channels_by_device,
        }

    def get_device_by_id(self, device_id: str) -> Device | None:
        """Return device by device id."""
        # Called by the battery sensor to get its updated data from self.data
        for device in self.data["devices"]:
            if device.device_id == device_id:
                return device

        return None

    def get_device_channel_by_id(
        self, device_id: str, channel_id: str
    ) -> DeviceChannel | None:
        """Return device channel by device id and channel id."""
        # Called by the temperature sensors to get their updated data from self.data

        for device_channel in self.data["device_channels"][device_id]:
            if device_channel.number == channel_id:
                return device_channel

        return None
