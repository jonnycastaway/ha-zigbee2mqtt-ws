"""Zigbee2MQTT WebSocket integration for Home Assistant."""
from __future__ import annotations

import asyncio
import importlib
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AUTH_TOKEN,
    CONF_BASE_TOPIC,
    CONF_USE_SSL,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DEFAULT_BASE_TOPIC,
    DOMAIN,
)
from .coordinator import Z2MCoordinator
from .websocket_client import Z2MWebSocketClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.COVER,
    Platform.LOCK,
    Platform.CLIMATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Zigbee2MQTT WS from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    use_ssl = entry.data.get(CONF_USE_SSL, False)
    auth_token = entry.data.get(CONF_AUTH_TOKEN)
    base_topic = entry.data.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC)

    client = Z2MWebSocketClient(
        host=host,
        port=port,
        use_ssl=use_ssl,
        auth_token=auth_token,
        base_topic=base_topic,
    )

    coordinator = Z2MCoordinator(hass, client, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_COORDINATOR: coordinator,
    }

    await coordinator.async_start()

    # Pre-import platform modules in the executor thread pool to avoid
    # blocking the async event loop (required since HA 2024.x).
    await asyncio.gather(
        *[
            hass.async_add_executor_job(
                importlib.import_module,
                f"custom_components.{DOMAIN}.{p}",
            )
            for p in ("light", "switch", "sensor", "binary_sensor", "cover", "lock", "climate")
        ]
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator: Z2MCoordinator = data[DATA_COORDINATOR]
        await coordinator.async_stop()
    return unload_ok
