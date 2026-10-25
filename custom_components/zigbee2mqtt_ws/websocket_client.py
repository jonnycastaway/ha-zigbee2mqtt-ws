"""Zigbee2MQTT WebSocket client."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 5  # seconds between reconnect attempts

# Commands that cannot be sent because the WebSocket is down are queued and
# replayed after the next successful connect. Entries older than
# COMMAND_QUEUE_TTL seconds are dropped - a light that gets switched 5 minutes
# late is worse than a command that never arrives.
COMMAND_QUEUE_MAX = 50
COMMAND_QUEUE_TTL = 30


class Z2MWebSocketClient:
    """Client for the Zigbee2MQTT WebSocket API.

    Z2M exposes its frontend via WebSocket at ws://<host>:<port>/api.
    Every message is a JSON object:
        {"topic": "<mqtt-topic>", "payload": <value>}
    where <value> is already the parsed JSON payload (dict, list, str, …).

    On connect Z2M immediately pushes:
        bridge/state, bridge/info, bridge/devices, bridge/groups, bridge/extensions
    and then streams live device-state / availability messages.
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
        self._connected = False

        # (timestamp, topic, payload) - written while disconnected, flushed on connect
        self._queue: deque[tuple[float, str, Any]] = deque(maxlen=COMMAND_QUEUE_MAX)
        self._last_message: float | None = None

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def base_topic(self) -> str:
        return self._base_topic

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_message_age(self) -> float | None:
        """Seconds since the last message arrived, None if nothing arrived yet."""
        if self._last_message is None:
            return None
        return time.monotonic() - self._last_message

    @property
    def queued_commands(self) -> int:
        return len(self._queue)

    def add_listener(self, callback: Callable[[str, Any], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, Any], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    async def connect(self) -> None:
        """Connect and keep reconnecting until async_stop() is called."""
        self._running = True
        self._session = aiohttp.ClientSession()
        try:
            await self._reconnect_loop()
        finally:
            if self._session and not self._session.closed:
                await self._session.close()

    async def _reconnect_loop(self) -> None:
        while self._running:
            try:
                await self._do_connect()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                _LOGGER.warning(
                    "Z2M WebSocket disconnected (%s). Reconnecting in %ds …",
                    exc,
                    RECONNECT_DELAY,
                )
                self._notify(f"{self._base_topic}/bridge/state", {"state": "offline"})
                if self._running:
                    await asyncio.sleep(RECONNECT_DELAY)

    async def _do_connect(self) -> None:
        scheme = "wss" if self._use_ssl else "ws"
        url = f"{scheme}://{self._host}:{self._port}/api"
        
        # Build URL with query params (Z2M uses token as query param, not header)
        params = {}
        if self._auth_token:
            params["token"] = self._auth_token

        headers: dict[str, str] = {}

        _LOGGER.info("Z2M: connecting to %s", url)
        async with self._session.ws_connect(
            url,
            headers=headers,
            heartbeat=30,
            ssl=False,
            params=params if params else None,
        ) as ws:
            self._ws = ws
            self._connected = True
            _LOGGER.info("Z2M: WebSocket connected")
            await self._flush_queue()

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_raw(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await self._handle_raw(msg.data.decode("utf-8", errors="replace"))
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("Z2M WebSocket error: %s", ws.exception())
                    break
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    _LOGGER.debug("Z2M WebSocket closed (type=%s)", msg.type)
                    break

    async def _handle_raw(self, raw: str) -> None:
        self._last_message = time.monotonic()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.warning("Z2M: invalid JSON: %.200s", raw)
            return

        topic = data.get("topic", "")
        payload = data.get("payload")

        # Z2M sends topics WITHOUT base_topic prefix (e.g., "bridge/devices", not "zigbee2mqtt/bridge/devices")
        # But it sends device states with friendly_name only: "friendly_name", not "zigbee2mqtt/friendly_name"
        
        # Normalize payload if it's a JSON string
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                pass  # keep as plain string

        _LOGGER.debug("Z2M ← topic=%s  payload=%s", topic, str(payload)[:200])
        self._notify(topic, payload)

    def _notify(self, topic: str, payload: Any) -> None:
        for listener in list(self._listeners):
            try:
                listener(topic, payload)
            except Exception:
                _LOGGER.exception("Z2M: error in message listener")

    # ── Write ───────────────────────────────────────────────────────────────

    async def publish(self, topic: str, payload: Any) -> None:
        """Send a message to Z2M via WebSocket, queueing it if the link is down.

        Silently dropping a command while the WebSocket is reconnecting means a
        light simply does not switch and nobody notices - the command is queued
        instead and replayed after the next successful connect.
        """
        if not self._ws or self._ws.closed or not self._connected:
            self._enqueue(topic, payload)
            return

        await self._send(topic, payload)

    async def _send(self, topic: str, payload: Any) -> None:
        """Send a message, queueing it if the write fails."""
        # Build message in Z2M format: {"topic": "friendly_name/set", "payload": {...}}
        # Note: Z2M expects topics WITHOUT base_topic prefix
        message = json.dumps({"topic": topic, "payload": payload})
        _LOGGER.debug("Z2M → sending: topic=%s  payload=%s", topic, str(payload)[:200])
        try:
            await self._ws.send_str(message)
        except Exception as err:  # noqa: BLE001 - connection died mid-write
            _LOGGER.warning(
                "Z2M: send failed (%s), queueing command for topic=%s", err, topic
            )
            self._enqueue(topic, payload)

    def _enqueue(self, topic: str, payload: Any) -> None:
        if len(self._queue) == self._queue.maxlen:
            dropped = self._queue[0]
            _LOGGER.error(
                "Z2M: command queue full (%d), dropping oldest command for topic=%s",
                self._queue.maxlen,
                dropped[1],
            )
        if self._queue:
            _LOGGER.debug(
                "Z2M: queued command for topic=%s (%d in queue)",
                topic,
                len(self._queue) + 1,
            )
        else:
            _LOGGER.warning(
                "Z2M: connection down – queueing commands, first for topic=%s", topic
            )
        self._queue.append((time.monotonic(), topic, payload))

    async def _flush_queue(self) -> None:
        """Replay queued commands after a reconnect, dropping expired ones."""
        if not self._queue:
            return

        now = time.monotonic()
        pending = list(self._queue)
        self._queue.clear()

        fresh = [entry for entry in pending if now - entry[0] <= COMMAND_QUEUE_TTL]
        expired = len(pending) - len(fresh)
        if expired:
            _LOGGER.error(
                "Z2M: %d queued command(s) expired after %ds and were dropped",
                expired,
                COMMAND_QUEUE_TTL,
            )
        for _ts, topic, payload in fresh:
            await self._send(topic, payload)
        if fresh:
            _LOGGER.info("Z2M: replayed %d queued command(s)", len(fresh))

    async def set_state(self, friendly_name: str, payload: dict) -> None:
        # Z2M expects: friendly_name/set (NOT base_topic/friendly_name/set)
        await self.publish(f"{friendly_name}/set", payload)

    async def get_state(self, friendly_name: str, payload: dict) -> None:
        # Z2M expects: friendly_name/get (NOT base_topic/friendly_name/get)
        await self.publish(f"{friendly_name}/get", payload)

    async def bridge_request(self, endpoint: str, payload: Any) -> None:
        # Z2M expects: bridge/request/endpoint (NOT base_topic/bridge/request/endpoint)
        await self.publish(f"bridge/request/{endpoint}", payload)

    async def disconnect(self) -> None:
        """Disconnect gracefully."""
        self._running = False
        self._connected = False
        self._queue.clear()
        if self._ws and not self._ws.closed:
            await self._ws.close()
