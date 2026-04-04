"""Coordinator for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import asyncio
import logging
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
    """Manages connection to Z2M and dispatches updates to entities."""

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
        # list of device definitions from bridge/devices
        self.devices: list[dict[str, Any]] = []
        # friendly_name -> device definition
        self.device_map: dict[str, dict[str, Any]] = {}

        self._connect_task: asyncio.Task | None = None
        self._platforms_loaded = asyncio.Event()

    async def async_start(self) -> None:
        """Start the WebSocket connection."""
        self.client.add_listener(self._on_message)
        self._connect_task = self.hass.async_create_task(
            self.client.connect(), eager_start=False
        )
        # Give the client a moment to connect and receive initial bridge/devices
        await asyncio.sleep(0)

    async def async_stop(self) -> None:
        """Stop the connection."""
        if self._connect_task:
            self._connect_task.cancel()
        await self.client.disconnect()

    @callback
    def _on_message(self, topic: str, payload: Any) -> None:
        """Dispatch incoming Z2M WebSocket messages."""
        base = self.client.base_topic

        if topic == f"{base}/bridge/devices":
            self._handle_devices(payload)
        elif topic == f"{base}/bridge/state":
            self._handle_bridge_state(payload)
        elif topic.endswith("/availability"):
            # e.g. zigbee2mqtt/my_bulb/availability
            friendly_name = topic[len(base) + 1 : -len("/availability")]
            self._handle_availability(friendly_name, payload)
        elif topic.startswith(f"{base}/") and not topic.startswith(f"{base}/bridge/"):
            # Device state message: zigbee2mqtt/<friendly_name>
            friendly_name = topic[len(base) + 1 :]
            self._handle_device_state(friendly_name, payload)

    def _handle_devices(self, devices: list[dict]) -> None:
        """Process bridge/devices message – builds device registry entries."""
        if not isinstance(devices, list):
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

            # Register device in HA device registry
            model = None
            manufacturer = None
            definition = device.get("definition")
            if definition:
                model = definition.get("model")
                manufacturer = definition.get("vendor")

            dev_reg.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, ieee)},
                name=friendly_name,
                model=model,
                manufacturer=manufacturer,
                sw_version=None,
            )

        _LOGGER.debug("Z2M: registered %d devices", len(devices))
        async_dispatcher_send(self.hass, SIGNAL_DEVICES_UPDATED, devices)

    def _handle_bridge_state(self, payload: Any) -> None:
        """Handle bridge online/offline state."""
        if isinstance(payload, dict):
            state = payload.get("state", "")
        else:
            state = str(payload)
        _LOGGER.info("Z2M bridge state: %s", state)

    def _handle_availability(self, friendly_name: str, payload: Any) -> None:
        """Handle device availability messages."""
        if isinstance(payload, dict):
            state = payload.get("state", "offline")
        else:
            state = str(payload)
        self.device_availability[friendly_name] = state
        async_dispatcher_send(
            self.hass, f"{SIGNAL_DEVICE_AVAILABILITY}_{friendly_name}", state
        )

    def _handle_device_state(self, friendly_name: str, payload: Any) -> None:
        """Handle incoming device state messages."""
        if not isinstance(payload, dict):
            return

        current = self.device_states.setdefault(friendly_name, {})
        current.update(payload)

        async_dispatcher_send(
            self.hass, f"{SIGNAL_DEVICE_STATE_UPDATED}_{friendly_name}", current
        )

    def get_device_state(self, friendly_name: str) -> dict[str, Any]:
        return self.device_states.get(friendly_name, {})

    def get_device_availability(self, friendly_name: str) -> str:
        return self.device_availability.get(friendly_name, "online")

    def get_device_definition(self, friendly_name: str) -> dict | None:
        return self.device_map.get(friendly_name, {}).get("definition")
