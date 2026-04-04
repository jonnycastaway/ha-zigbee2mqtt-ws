"""Coordinator for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN
from .websocket_client import Z2MWebSocketClient

_LOGGER = logging.getLogger(__name__)

SIGNAL_DEVICE_STATE_UPDATED = f"{DOMAIN}_device_state"
SIGNAL_DEVICE_AVAILABILITY = f"{DOMAIN}_availability"
SIGNAL_DEVICES_UPDATED = f"{DOMAIN}_devices"


class Z2MCoordinator:
    """Manages connection to Z2M and dispatches updates to entities.

    Flow:
      1. async_start() registers the message listener and queues the connect task.
      2. __init__.py calls async_forward_entry_setups() → platforms register their
         SIGNAL_DEVICES_UPDATED listeners via async_dispatcher_connect().
      3. Once the WS connects, Z2M pushes bridge/devices; _handle_devices() fires
         the dispatcher so all platform listeners are already subscribed.
      4. If bridge/devices arrived before platforms finished loading (unlikely but
         possible), platforms call coordinator.devices in their setup and get the
         cached list directly.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: Z2MWebSocketClient,
        entry: ConfigEntry,
    ) -> None:
        self.hass = hass
        self.client = client
        self.entry = entry

        # friendly_name -> current state dict
        self.device_states: dict[str, dict[str, Any]] = {}
        # friendly_name -> availability ("online"/"offline")
        self.device_availability: dict[str, str] = {}
        # list of device definitions from bridge/devices (cached)
        self.devices: list[dict[str, Any]] = []
        # friendly_name -> full device dict
        self.device_map: dict[str, dict[str, Any]] = {}
        
        # Track pending state changes with timestamp
        # friendly_name -> (expected_state, timestamp)
        self._pending_state: dict[str, tuple[str, float]] = {}

        self._connect_task: asyncio.Task | None = None

    async def async_start(self) -> None:
        """Register listener and kick off the WebSocket connection task."""
        self.client.add_listener(self._on_message)
        # Schedule the long-running connect loop as a background task.
        # Do NOT use eager_start – it was removed in HA 2025.x.
        self._connect_task = self.hass.async_create_background_task(
            self.client.connect(),
            name=f"z2m_ws_{self.entry.entry_id}",
        )

    async def async_stop(self) -> None:
        """Stop the connection and cancel the background task."""
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            try:
                await self._connect_task
            except asyncio.CancelledError:
                pass
        await self.client.disconnect()

    @callback
    def _on_message(self, topic: str, payload: Any) -> None:
        """Dispatch incoming Z2M WebSocket messages (runs in the event loop)."""
        # Topics come WITHOUT base_topic prefix from Z2M WebSocket API
        # Examples: "bridge/devices", "bridge/state", "bridge/info", "friendly_name/availability"
        
        _LOGGER.debug("Z2M raw topic: %s, payload type: %s", topic, type(payload).__name__)

        if topic == "bridge/devices":
            self._handle_devices(payload)

        elif topic == "bridge/state":
            self._handle_bridge_state(payload)

        elif topic == "bridge/info":
            _LOGGER.info("Z2M bridge info: version=%s", payload.get("version", "unknown"))

        elif topic.endswith("/availability"):
            # friendly_name/availability
            friendly_name = topic[: -len("/availability")]
            self._handle_availability(friendly_name, payload)

        elif not topic.startswith("bridge/"):
            # Device state: "friendly_name" (not prefixed!)
            friendly_name = topic
            # Ignore sub-topics like .../set, .../get
            if "/" not in friendly_name or all(
                not friendly_name.endswith(s) for s in ("/set", "/get")
            ):
                self._handle_device_state(friendly_name, payload)

    def _handle_devices(self, devices: Any) -> None:
        """Process bridge/devices – build device registry + dispatch to platforms."""
        # Z2M sends the payload already parsed as a list when coming via WS.
        # Guard against unexpected formats.
        if not isinstance(devices, list):
            _LOGGER.warning("Z2M bridge/devices: expected list, got %s – ignoring", type(devices))
            return

        self.devices = devices
        self.device_map = {}

        dev_reg = dr.async_get(self.hass)

        for device in devices:
            ieee = device.get("ieee_address")
            friendly_name = device.get("friendly_name")
            if not ieee or not friendly_name:
                continue

            self.device_map[friendly_name] = device

            definition = device.get("definition") or {}
            dev_reg.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, ieee)},
                name=friendly_name,
                model=definition.get("model"),
                manufacturer=definition.get("vendor"),
            )

        _LOGGER.info("Z2M: received %d device(s) from bridge", len(devices))
        _LOGGER.debug("Z2M devices payload sample: %s", str(devices[0])[:500] if devices else "empty")
        async_dispatcher_send(self.hass, SIGNAL_DEVICES_UPDATED, devices)

    def _handle_bridge_state(self, payload: Any) -> None:
        if isinstance(payload, dict):
            state = payload.get("state", "")
        else:
            state = str(payload)
        _LOGGER.info("Z2M bridge state: %s", state)

    def _handle_availability(self, friendly_name: str, payload: Any) -> None:
        if isinstance(payload, dict):
            state = payload.get("state", "offline")
        else:
            state = str(payload)
        self.device_availability[friendly_name] = state
        async_dispatcher_send(
            self.hass,
            f"{SIGNAL_DEVICE_AVAILABILITY}_{friendly_name}",
            state,
        )

    def _handle_device_state(self, friendly_name: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        
        # Check if this is a state change we initiated (within 2 seconds)
        pending = self._pending_state.get(friendly_name)
        now = time.monotonic()
        
        if pending is not None:
            expected_state, timestamp = pending
            # Clear if older than 2 seconds
            if now - timestamp > 2.0:
                _LOGGER.debug("Pending state for %s expired", friendly_name)
                self._pending_state.pop(friendly_name, None)
                pending = None
            elif "state" in payload:
                received = str(payload["state"]).upper()
                _LOGGER.info("Z2M state for %s: got=%s expected=%s", friendly_name, received, expected_state)
                if received == expected_state:
                    _LOGGER.info("Ignoring echo for %s: %s", friendly_name, received)
                    current = self.device_states.setdefault(friendly_name, {})
                    current.update(payload)
                    self._pending_state.pop(friendly_name, None)
                    return
                else:
                    _LOGGER.info("State mismatch for %s: expected=%s got=%s - processing normally", 
                                 friendly_name, expected_state, received)
                    self._pending_state.pop(friendly_name, None)
        
        current = self.device_states.setdefault(friendly_name, {})
        current.update(payload)
        async_dispatcher_send(
            self.hass,
            f"{SIGNAL_DEVICE_STATE_UPDATED}_{friendly_name}",
            current,
        )

    # ── Accessors used by entity classes ──────────────────────────────────────

    def get_device_state(self, friendly_name: str) -> dict[str, Any]:
        return self.device_states.get(friendly_name, {})

    def get_device_availability(self, friendly_name: str) -> str:
        return self.device_availability.get(friendly_name, "online")

    def get_device_definition(self, friendly_name: str) -> dict | None:
        return self.device_map.get(friendly_name, {}).get("definition")
