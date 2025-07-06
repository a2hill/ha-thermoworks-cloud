# ThermoWorks Cloud for Home Assistant
![GitHub branch check runs](https://img.shields.io/github/check-runs/a2hill/ha-thermoworks-cloud/main)
[![License](https://img.shields.io/github/license/a2hill/ha-thermoworks-cloud)](https://raw.githubusercontent.com/a2hill/ha-thermoworks-cloud/refs/heads/main/LICENSE)

## About
This integration allows [Home Assistant](https://www.home-assistant.io/) to pull data (temperature, battery, signal strength) from ThermoWorks Cloud connected devices.

### Supported Devices
See [Discussions - Device Interoperability](https://github.com/a2hill/ha-thermoworks-cloud/discussions/6)

## Installation
### HACS
If you have [HACS](https://hacs.xyz/) installed in your Home Assistant instance

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=a2hill&repository=ha-thermoworks-cloud&category=integration)

### Manual Installation
Copy the [custom_components/thermoworks_cloud](custom_components/) folder into the `config/custom_components` folder of your Home Assistant instance

## Usage
1. With this custom component installed into your HA instance, you will now see the ThermoWorks Cloud integration available as an integration that can be added (settings > Devices & services > Add Integration)
1. After adding the integration, be sure to set the scan interval which will tell HA how often to request new data from ThermoWorks  
    * The default is 1,800 second (30 minutes), however this may be too slow for real-time applications like grilling with RFX

## Also
To pull data, this integration uses [python-thermoworks-cloud](https://github.com/a2hill/python-thermoworks-cloud)