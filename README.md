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

## ThermoWorks API key requirements

ThermoWorks Cloud requires a **user-created integration API key** with
`read:devices` access. Your ThermoWorks password and the web application's
Firebase API key cannot be used in its place.

To create a key, you need:

* A ThermoWorks Cloud account with the devices you want to monitor.
* The **Account Admin** or **API Admin** role on that account.
* A plan with integrations API access enabled so the **Integrations** tab is
  available in the web app.

### Create an API key

1. Sign in to [ThermoWorks Cloud](https://cloud.thermoworks.com/).
2. Open your account settings and select **Integrations**. Make sure you are
   viewing your own account, not another account shared with you.
3. In **API keys**, select **Create API key**.
4. Enter a recognizable name, such as `Home Assistant`.
5. Choose an expiration. If you choose an expiration date, plan to replace the
   key in Home Assistant before it expires.
6. Select the devices Home Assistant should access. Leave the selection empty
   to allow all devices on the account, including devices added later.
7. Select **Create key** and copy the **complete key** from the one-time secret
   dialog. The key is shown only once; the prefix in the key list is not enough.

Keys provide read-only device access; they cannot change device settings.
Treat the complete key like a password: do not put it in screenshots, logs,
GitHub issues, or committed configuration. Use a separate key for Home Assistant
so it can be revoked independently.

If the **Integrations** tab is missing, verify your account, role, and plan with
your account administrator or ThermoWorks support. If you lose the complete key,
create a replacement and revoke the lost key; it cannot be displayed again.

### Add the key to Home Assistant

1. Install this integration and restart Home Assistant.
2. Open **Settings > Devices & services > Add integration > ThermoWorks Cloud**.
3. Select **ThermoWorks Cloud (US)**.
4. Paste the complete API key into **API key** and submit.
5. Use **Configure** to adjust the [scan interval](#controlling-the-scan-interval)
   if needed. The default is 1,800 seconds; API-key entries enforce a minimum of
   60 seconds or the API's longer recommendation.

(#migrating-an-existing-thermoworks-entry).
For a revoked, expired, or otherwise rejected key, Home Assistant requests
reauthentication. Create a replacement key for the same account and enter it
there. The integration connects to `https://cloud.thermoworks.com/api/v1`;
you do not need to configure a server URL.

## Usage
1. With this custom component installed into your HA instance, you will now see the ThermoWorks Cloud integration available as an integration that can be added (settings > Devices & services > Add Integration)
1. Select the cloud provider. ThermoWorks Cloud uses a `read:devices` API key created in the account's **Integrations** tab, not an email/password login. ETI Cloud continues to use email/password.
1. After adding the integration, you will be required to set the [scan interval](#controlling-the-scan-interval) which will tell HA how often to request new data from ThermoWorks. This can be changed later.  
    * The default is 1,800 seconds (30 minutes), however this may be too slow for real-time applications like grilling with RFX

### Migrating an existing ThermoWorks entry

After updating and restarting Home Assistant, existing password-based ThermoWorks
entries request reauthentication. Enter an API key for the **same account**.
The existing config entry and its unique ID are retained, and the saved password
is removed. Device/channel entity unique-ID formats are unchanged; new channel 0
entities can now be discovered too. Do not delete and recreate the integration.
Once the account is linked, replacement keys must belong to that same account.
Legacy entries do not contain an account ID, so the first key's account cannot be
checked against the old login.

The API retrieves all devices and channels in one request. It supports readings,
alarm thresholds/states, battery, signal strength, last contact and transmit
interval where reported. Fan telemetry supports the existing connected, state,
and set-temperature entities, including the controlling channel. Device display
units and battery charging state are preserved. Fan data is read-only.
These additional fields require the corresponding API backend update; an older
API response without fan data will not create fan entities.

| Integration model field | API field |
|---|---|
| `serial` | `serial` (falls back to `id` when absent) |
| `device_id` | `id` (existing serial-based identifiers retained on migration) |
| `label` | `label` |
| `device_name` | `model`, falling back to `type` |
| `device_display_units` | `displayUnits` |
| `firmware` | `firmware` |
| `battery` | `battery` |
| `battery_state` | `batteryState` |
| `wifi_strength` | `wifiSignal` |
| `signal_strength` | `gatewaySignal`, falling back to `wifiSignal` |
| `fan` | `fan.connected`, `fan.channel`, `fan.setTemp`, `fan.state` |
| `last_seen` | `lastSeen` |
| `transmit_interval_in_seconds` | `transmitIntervalSeconds` |

The integration uses the production API at
`https://cloud.thermoworks.com/api/v1`. No consumer App Check bypass or Firebase
password login is used for ThermoWorks.

### Reading timestamps and freshness

Reading sensors expose `lastTelemetrySaved` as an attribute, not a separate
timestamp sensor. As before, there is **no age-based freshness cutoff**: an old
reading stays available while API polling succeeds. Disabled channels and failed
probes are unavailable; missing readings are unknown. Missing devices/channels
must not continue to appear available.

The sample timestamp does not backdate Home Assistant history or prevent HA from
recording values on startup or producing statistics from held readings.

### Controlling the Scan Interval
It may be desirable to change the scan interval based on the activity that the devices is being used for. There are two ways to change it:

1. **Manually**: Settings > Devices & services > ThermoWorks Cloud > **Configure**, then set **Scan interval (seconds)**.
1. **Programatically**: the integration creates a `number` entity named **Scan interval**, you can control this entity from automations and scripts (see [example](#example-poll-faster-during-a-cook)).

#### Tips
* Polling more often than your device sends readings to the cloud won't give you fresher data. If your device has a **Transmit Interval** sensor, it gives a rough idea of how often the device sends readings.
* Short intervals mean more requests to ThermoWorks Cloud. Consider using a fast interval only while you actually need it.
* ThermoWorks API-key entries enforce at least 60 seconds between scheduled polls (or a longer API recommendation). Existing shorter options are clamped at runtime. HTTP 429 responses honor `Retry-After`, including across subsequent refreshes. Invalid, revoked or expired keys trigger reauthentication; transient failures make entities unavailable without deleting the entry.
*  Scan interval is a configuration entity, so Home Assistant does not add it to auto-generated dashboards. You can still add it to a dashboard card yourself.

#### Example: poll faster during a cook
This automation polls every 60 seconds while an `input_boolean.cook_mode` helper is on and goes back to every 30 minutes when it is turned off. You can use any trigger that suits your setup instead of the helper, such as a probe temperature, a device's **Last Seen** time, or whether your gateway is on the network.

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
      value: "{{ 60 if is_state('input_boolean.cook_mode', 'on') else 1800 }}"
mode: restart
```
## Also
For ETI Cloud, this integration uses [python-thermoworks-cloud](https://github.com/a2hill/python-thermoworks-cloud). ThermoWorks Cloud uses its supported integrations REST API.
