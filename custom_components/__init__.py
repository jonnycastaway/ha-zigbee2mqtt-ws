"""Zigbee2MQTT WebSocket integration for Home Assistant."""
import asyncio
import logging
from typing import Optional

import aiohttp
import async_timeout
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN
from .websocket_client import Zigbee2MqttWebSocket

_LOGGER = logging.getLogger(__name__)

class Zigbee2MqttData:
    def __init__(self) -> None:
        self.ws_client: Optional[Zigbee2MqttWebSocket] = None
        self.devices = {}
        self.groups = {}

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True

async def async_setup_entry(hass: HomeAssistant, config_entry: config_entries.ConfigEntry) -> bool:
    host = config_entry.data[CONF_HOST]
    port = config_entry.data[CONF_PORT]
    token = config_entry.data.get("token")

    websocket = Zigbee2MqttWebSocket(hass, host, port, token)

    try:
        async with async_timeout.timeout(10):
            await websocket.start()
    except aiohttp.ClientError as err:
        raise ConfigEntryNotReady(f"Failed to connect to Zigbee2MQTT: {err}") from err

    hass.data[DOMAIN] = Zigbee2MqttData()
    hass.data[DOMAIN].ws_client = websocket

    await websocket.request_device_list()

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, "sensor")
    )
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, "light")
    )
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, "switch")
    )
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, "binary_sensor")
    )

    async def on_hass_stop(event):
        await websocket.stop()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: config_entries.ConfigEntry) -> bool:
    websocket = hass.data[DOMAIN].ws_client
    if websocket:
        await websocket.stop()

    await hass.config_entries.async_forward_entry_unload(config_entry, "sensor")
    await hass.config_entries.async_forward_entry_unload(config_entry, "light")
    await hass.config_entries.async_forward_entry_unload(config_entry, "switch")
    await hass.config_entries.async_forward_entry_unload(config_entry, "binary_sensor")

    return True
