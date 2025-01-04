# ThermoWorks Cloud for Home Assistant
ThermoWorks Cloud device integration for Home Assistant

## About
This integration allows [Home Assistant](https://www.home-assistant.io/) to pull data (temperature, battery, signal strength) from ThermoWorks Cloud connected devices.

### Supported Devices
This integration has been tested with the following devices:
* [ThermoWorks Node Wi-Fi sensor](https://www.thermoworks.com/node/)

## Installation
### HACS
If you have [HACS](https://hacs.xyz/) installed in your Home Assistant instance

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=a2hill&repository=ha-thermoworks-cloud&category=integration)

### Manual Installation
Copy the [custom_components/thermoworks_cloud](custom_components/) folder into the `config/custom_components` folder of your Home Assistant instance

## Also
To pull data, this integration uses [python-thermoworks-cloud](https://github.com/a2hill/python-thermoworks-cloud)