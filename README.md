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
1. After adding the integration, you will be required to set the [scan interval](#controlling-the-scan-interval) which will tell HA how often to request new data from ThermoWorks. This can be changed later.  
    * The default is 1,800 seconds (30 minutes), however this may be too slow for real-time applications like grilling with RFX

### Controlling the Scan Interval
It may be desirable to change the scan interval based on the activity that the devices is being used for. There are two ways to change it:

1. **Manually**: Settings > Devices & services > ThermoWorks Cloud > **Configure**, then set **Scan interval (seconds)**.
1. **Programatically**: the integration creates a `number` entity named **Scan interval**, you can control this entity from automations and scripts (see [example](#example-poll-faster-during-a-cook)).

#### Tips
* Polling more often than your device sends readings to the cloud won't give you fresher data. If your device has a **Transmit Interval** sensor, it gives a rough idea of how often the device sends readings.
* Short intervals mean more requests to ThermoWorks Cloud. Consider using a fast interval only while you actually need it.
*  Scan interval is a configuration entity, so Home Assistant does not add it to auto-generated dashboards. You can still add it to a dashboard card yourself.

#### Example: poll faster during a cook
This automation polls every 15 seconds while an `input_boolean.cook_mode` helper is on and goes back to every 30 minutes when it is turned off. You can use any trigger that suits your setup instead of the helper, such as a probe temperature, a device's **Last Seen** time, or whether your gateway is on the network.

```yaml
alias: ThermoWorks - fast polling during a cook
triggers:
  - trigger: state
    entity_id: input_boolean.cook_mode
actions:
  - action: number.set_value
    target:
      entity_id: number.thermoworks_cloud_scan_interval
    data:
      value: "{{ 15 if is_state('input_boolean.cook_mode', 'on') else 1800 }}"
mode: restart
```
## Also
To pull data, this integration uses [python-thermoworks-cloud](https://github.com/a2hill/python-thermoworks-cloud)
