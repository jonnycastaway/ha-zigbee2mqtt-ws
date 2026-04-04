"""Zigbee2MQTT WebSocket client."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Z2M WebSocket message types (mirror of MQTT topics)
MSG_BRIDGE_DEVICES = "zigbee2mqtt/bridge/devices"
MSG_BRIDGE_INFO = "zigbee2mqtt/bridge/info"
MSG_BRIDGE_STATE = "zigbee2mqtt/bridge/state"
MSG_BRIDGE_GROUPS = "zigbee2mqtt/bridge/groups"
MSG_AVAILABILITY_SUFFIX = "/availability"
MSG_SET_SUFFIX = "/set"
MSG_GET_SUFFIX = "/get"


class Z2MWebSocketClient:
    """Client for the Zigbee2MQTT WebSocket API.

    Z2M exposes its frontend via WebSocket at ws://<host>:<port>/api.
    Each message is a JSON object with 'topic' and 'payload' keys,
    mirroring the MQTT topic/payload structure exactly.
    """

    def __init__(
        self,
        host: str,
        port: int,
        use_ssl: bool = False,
        auth_token: str | None = None,
        base_topic: str = "zigbee2mqtt",
    ) -> None:
        self._host = host
        self._port = port
        self._use_ssl = use_ssl
        self._auth_token = auth_token
        self._base_topic = base_topic

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._listeners: list[Callable[[str, Any], None]] = []
        self._running = False
        self._reconnect_task: asyncio.Task | None = None
        self._connected = False

    @property
    def base_topic(self) -> str:
        return self._base_topic

    @property
    def connected(self) -> bool:
        return self._connected

    def _build_url(self) -> str:
        scheme = "wss" if self._use_ssl else "ws"
        return f"{scheme}://{self._host}:{self._port}/api"

    def add_listener(self, callback: Callable[[str, Any], None]) -> None:
        """Add a message listener. callback(topic, payload)."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, Any], None]) -> None:
        self._listeners.discard(callback) if hasattr(self._listeners, "discard") else None
        if callback in self._listeners:
            self._listeners.remove(callback)

    async def connect(self) -> None:
        """Connect to Z2M WebSocket and start the receive loop."""
        self._running = True
        self._session = aiohttp.ClientSession()
        await self._connect_loop()

    async def _connect_loop(self) -> None:
        while self._running:
            try:
                await self._do_connect()
            except Exception as exc:
                _LOGGER.warning("Z2M WebSocket disconnected: %s – reconnecting in 5s", exc)
                self._connected = False
                self._notify(f"{self._base_topic}/bridge/state", {"state": "offline"})
                if self._running:
                    await asyncio.sleep(5)

    async def _do_connect(self) -> None:
        url = self._build_url()
        headers = {}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        _LOGGER.debug("Connecting to Z2M WebSocket: %s", url)
        async with self._session.ws_connect(
            url,
            headers=headers,
            heartbeat=30,
            ssl=False,
        ) as ws:
            self._ws = ws
            self._connected = True
            _LOGGER.info("Connected to Zigbee2MQTT WebSocket at %s", url)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", ws.exception())
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    break

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            _LOGGER.warning("Z2M: invalid JSON received: %s", raw[:200])
            return

        topic = data.get("topic", "")
        payload = data.get("payload")

        # payload can be a JSON string or already a dict
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                pass  # keep as string for simple values like "online"/"offline"

        _LOGGER.debug("Z2M message: topic=%s payload=%s", topic, payload)
        self._notify(topic, payload)

    def _notify(self, topic: str, payload: Any) -> None:
        for listener in list(self._listeners):
            try:
                listener(topic, payload)
            except Exception:
                _LOGGER.exception("Error in Z2M listener")

    async def publish(self, topic: str, payload: Any) -> None:
        """Send a message to Z2M via WebSocket."""
        if not self._ws or self._ws.closed:
            _LOGGER.error("Z2M: cannot publish, not connected")
            return
        message = json.dumps({"topic": topic, "payload": payload})
        await self._ws.send_str(message)

    async def set_state(self, friendly_name: str, payload: dict) -> None:
        """Set state on a device: zigbee2mqtt/<name>/set."""
        topic = f"{self._base_topic}/{friendly_name}/set"
        await self.publish(topic, payload)

    async def get_state(self, friendly_name: str, payload: dict) -> None:
        """Read state from a device: zigbee2mqtt/<name>/get."""
        topic = f"{self._base_topic}/{friendly_name}/get"
        await self.publish(topic, payload)

    async def bridge_request(self, endpoint: str, payload: Any) -> None:
        """Send a bridge request: zigbee2mqtt/bridge/request/<endpoint>."""
        topic = f"{self._base_topic}/bridge/request/{endpoint}"
        await self.publish(topic, payload)

    async def disconnect(self) -> None:
        """Disconnect from Z2M WebSocket."""
        self._running = False
        self._connected = False
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()
