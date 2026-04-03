import asyncio
import json
import logging
from typing import Any, Callable, Optional
import aiohttp
import aiohttp.web
import async_timeout
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DISABLE_DISCOVERY,
    CONF_USE_LEGACY_ENTITY_NAMING,
    DATA_DEVICE_CONFIG,
    DATA_DISCOVERY,
    DATA_ZIGBEE_GROUPS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

class Zigbee2MqttWebSocket:
    def __init__(self, hass: HomeAssistant, host: str, port: int, token: Optional[str] = None):
        self.hass = hass
        self.host = host
        self.port = port
        self.token = token
        self.ws_client: Optional[aiohttp.ClientWebSocketResponse] = None
        self._ws_loop_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._shutdown = False
        self.devices = {}
        self.groups = {}
        self.bridge_info = {}
        self._message_callbacks = []

    @property
    def url(self) -> str:
        base = f"http://{self.host}:{self.port}"
        if self.token:
            return f"{base}/api?token={self.token}"
        return f"{base}/api"

    async def _send_json(self, message: dict) -> None:
        if self.ws_client and not self.ws_client.closed:
            await self.ws_client.send_json(message)

    async def _ping(self) -> None:
        while not self._shutdown:
            await asyncio.sleep(30)
            if self.ws_client and not self.ws_client.closed:
                try:
                    await self.ws_client.ping()
                except Exception:
                    pass

    async def _ws_loop(self) -> None:
        session = aiohttp.ClientSession()
        try:
            while not self._shutdown:
                try:
                    async with session.ws_connect(
                        self.url,
                        autoclose=False,
                        autoping=False,
                        heartbeat=30,
                    ) as ws:
                        self.ws_client = ws
                        _LOGGER.info("Connected to Zigbee2MQTT WebSocket")

                        async for msg in ws:
                            if self._shutdown:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                    self._handle_message(data)
                                except json.JSONDecodeError:
                                    _LOGGER.warning("Received non-JSON message: %s", msg.data)
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                _LOGGER.error("WebSocket error: %s", ws.exception())
                                break
                        await asyncio.sleep(1)
                except aiohttp.ClientError as e:
                    _LOGGER.warning("WebSocket connection error: %s", e)
                except Exception as e:
                    _LOGGER.error("Unexpected error in WebSocket loop: %s", e)
                await asyncio.sleep(1)
        finally:
            await session.close()

    def _handle_message(self, data: dict) -> None:
        topic = data.get("topic", "")
        payload = data.get("payload", {})

        # Handle different message types
        if topic == "bridge/info":
            self.bridge_info = payload
            async_dispatcher_send(self.hass, f"{DOMAIN}_bridge_info", payload)
        elif topic == "bridge/state":
            async_dispatcher_send(self.hass, f"{DOMAIN}_bridge_state", payload)
        elif topic == "bridge/devices":
            self.devices = {dev.get("friendly_name"): dev for dev in payload}
            async_dispatcher_send(self.hass, f"{DOMAIN}_devices", payload)
        elif topic == "bridge/groups":
            self.groups = {group.get("id"): group for group in payload}
            async_dispatcher_send(self.hass, f"{DOMAIN}_groups", payload)
        elif topic.endswith("/availability"):
            device_id = topic.replace("/availability", "")
            async_dispatcher_send(self.hass, f"{DOMAIN}_availability", {"device": device_id, "payload": payload})
        else:
            # Device state updates
            async_dispatcher_send(self.hass, f"{DOMAIN}_device_message", {"topic": topic, "payload": payload})

        for callback in self._message_callbacks:
            callback(topic, payload)

    async def publish(self, topic: str, payload: dict) -> None:
        message = json.dumps({"topic": topic, "payload": payload})
        await self._send_json({"type": "publish", "topic": topic, "payload": payload})

    async def request_device_list(self) -> None:
        await self._send_json({"type": "get", "topic": "bridge/devices"})
        await self._send_json({"type": "get", "topic": "bridge/groups"})
        await self._send_json({"type": "get", "topic": "bridge/info"})

    async def start(self) -> None:
        self._ws_loop_task = asyncio.create_task(self._ws_loop())
        self._ping_task = asyncio.create_task(self._ping())

    async def stop(self) -> None:
        self._shutdown = True
        if self._ws_loop_task:
            self._ws_loop_task.cancel()
            try:
                await self._ws_loop_task
            except asyncio.CancelledError:
                pass
        if self._ping_task:
            self._ping_task.cancel()
        if self.ws_client and not self.ws_client.closed:
            await self.ws_client.close()

    def register_message_callback(self, callback: Callable[[str, dict], None]) -> None:
        self._message_callbacks.append(callback)
