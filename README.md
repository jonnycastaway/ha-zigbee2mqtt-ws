# Zigbee2MQTT (WebSocket) for Home Assistant

**English** · [Deutsch](README.de.md)

This integration brings your Zigbee2MQTT devices into Home Assistant through the
**WebSocket interface** of Zigbee2MQTT — as an alternative to the usual route via MQTT.

In short: Zigbee2MQTT manages your Zigbee devices (lights, plugs, sensors …), this
integration is the line in between and turns them into Home Assistant entities.

---

## Installation

1. **HACS → Integrations → ⋮ → Custom repositories**
2. Add the URL `https://github.com/jonnycastaway/ha-zigbee2mqtt-ws`
   Category: **Integration**
3. Find the integration, install it and restart Home Assistant.
4. **Settings → Devices & Services → Add integration → “Zigbee2MQTT (WebSocket)”**

### Setup fields

| Field | Meaning |
|---|---|
| **Host** | IP address or hostname of the machine running Zigbee2MQTT |
| **Port** | Default `8080` (the Zigbee2MQTT web interface) |
| **SSL** | Only enable if Zigbee2MQTT is served over HTTPS |
| **Auth token** | Only needed if `frontend: auth_token` is set in your Zigbee2MQTT configuration |
| **Base topic** | Default `zigbee2mqtt`, only change it if your setup differs |

Afterwards your Zigbee devices show up as regular Home Assistant devices — lights,
switches, sensors, covers, locks and climate devices, depending on what each device
supports.

---

## Connection sensor (since 1.3.6)

There is an additional device **“Zigbee2MQTT (WebSocket)”** with a diagnostic entity:

```
binary_sensor.zigbee2mqtt_websocket_connection
```

* **on** = the connection is up, data is arriving.
* **off** = no data for about 2.5 minutes.

When the connection is really gone, a **persistent notification** appears in Home
Assistant as well, and it disappears automatically once the link is back.

You can use this entity for your own automation (e.g. “notify me when the connection has
been down for a while”) — so you decide what happens.

> **Important:** On a disconnect, **no** other entities are marked as *unavailable*.
> This is intentional: Zigbee2MQTT itself reports when individual devices cannot be
> reached. If the integration locked *every* entity on each short network hiccup, that
> would have real side effects — an alarm panel, for example, treats “unavailable”
> sensors as triggered when that is enabled per sensor. A brief hiccup would then set
> off the siren.

---

## What happens on a disconnect?

* **Commands are not lost.** If you switch a light in Home Assistant while the connection
  is down, the command is stored and replayed after the reconnect — for up to **30
  seconds**. Anything older is dropped, because switching a light a minute later is worse
  than not switching it at all.
* **The state stays as it was** until data arrives again. The last known state is more
  honest than an invented one.
* **Automatic reconnect:** the integration retries every 5 seconds.

---

## Changelog

### 1.3.6 — commands are no longer lost, connection sensor

**Fixed / new:**

* **Commands were silently dropped.** Previously, commands issued during a connection
  outage were only written to the log and then forgotten. In the app it looked as if it
  had worked — but the light stayed off. Those commands are now stored and replayed after
  the reconnect (up to 30 seconds old).
* **New connection sensor + notification.** You can now see in Home Assistant whether the
  link to Zigbee2MQTT is up (see above). Before, an outage was only noticeable because
  nothing reacted anymore.

**Background:** so that a quiet Zigbee network (nothing happening for minutes at night) is
not mistaken for an outage, the integration briefly asks Zigbee2MQTT “are you still
there?” every 30 seconds while the link is silent. Only if that is not answered either, and
no data arrived for 2.5 minutes in total, is the connection considered down.

### 1.3.5 — stale states fixed

**Fixed:**

* **Lights sometimes showed a wrong state.** Example: you set a lamp to 100 % brightness,
  Zigbee2MQTT reports 100 % as well — but Home Assistant kept showing the old 25 %. The
  correct value was already known internally, it just never reached the dashboard.
  Only a restart or a reconnect repaired the display.
  Cause: the integration treated the confirmation from Zigbee2MQTT as a “stale message”
  and threw it away whenever Home Assistant had just sent a command itself. That no
  longer happens.
* **Rapid changes were swallowed.** When several messages arrived in quick succession
  (e.g. brightness + colour at once), the last one could be lost. It is now written
  afterwards.
* **Covers and locks** could briefly show a wrong state (e.g. “open” instead of “closed”),
  because every state other than “on” was translated to “off”. Fixed.
* **Availability** of devices (“offline”/“online”) is now correctly passed on to the
  dashboard.

### Older versions

Up to and including **1.3.4** there were no changelogs. Summary: build-up of the
integration, support for lights, switches, sensors, binary sensors, covers, locks and
climate devices, improvements for Home Assistant versions from 2025 on.

---

## Known limitations

* The integration uses the WebSocket interface of the Zigbee2MQTT web UI. It does not work
  if the web frontend is disabled in Zigbee2MQTT.
* Using MQTT discovery in parallel creates duplicate devices. Please use only one of the
  two approaches.
* After a HACS update, reload the integration once
  (Settings → Devices & Services → Zigbee2MQTT (WebSocket) → ⋮ → Reload) so new entities
  appear.
