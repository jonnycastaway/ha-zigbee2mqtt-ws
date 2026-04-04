"""Config flow for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_AUTH_TOKEN,
    CONF_BASE_TOPIC,
    CONF_USE_SSL,
    DEFAULT_BASE_TOPIC,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _test_connection(
    host: str,
    port: int,
    use_ssl: bool,
    auth_token: str | None,
) -> str | None:
    """Try to connect to Z2M WebSocket. Returns error key or None on success."""
    scheme = "wss" if use_ssl else "ws"
    url = f"{scheme}://{host}:{port}/api"
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, headers=headers, ssl=False, timeout=aiohttp.ClientTimeout(total=10)) as ws:
                # Wait for the first message (Z2M sends bridge/devices on connect)
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=8)
                    if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                        return None  # success
                    return "cannot_connect"
                except asyncio.TimeoutError:
                    # Connection worked but no message – still OK
                    return None
    except aiohttp.ClientConnectorError:
        return "cannot_connect"
    except Exception as exc:
        _LOGGER.debug("Z2M connection test failed: %s", exc)
        return "cannot_connect"


class Zigbee2MQTTWSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Zigbee2MQTT WebSocket."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            use_ssl = user_input[CONF_USE_SSL]
            auth_token = user_input.get(CONF_AUTH_TOKEN) or None
            base_topic = user_input.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC)

            error = await _test_connection(host, port, use_ssl, auth_token)
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Zigbee2MQTT @ {host}:{port}",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_USE_SSL: use_ssl,
                        CONF_AUTH_TOKEN: auth_token,
                        CONF_BASE_TOPIC: base_topic,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="homeassistant.local"): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_USE_SSL, default=False): bool,
                vol.Optional(CONF_AUTH_TOKEN, default=""): str,
                vol.Optional(CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
