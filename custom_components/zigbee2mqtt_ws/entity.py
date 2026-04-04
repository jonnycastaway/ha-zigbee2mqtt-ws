"""Base entity for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .coordinator import (
    SIGNAL_DEVICE_AVAILABILITY,
    SIGNAL_DEVICE_STATE_UPDATED,
    Z2MCoordinator,
)

_LOGGER = logging.getLogger(__name__)

_STATE_UPDATE_THROTTLE = 0.1


class Z2MEntity(Entity):
    """Base entity for all Zigbee2MQTT WebSocket entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Z2MCoordinator,
        device: dict,
        feature: dict | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._device = device
        self._feature = feature or {}
        
        # Track last update time to throttle
        self._last_state_update: float = 0

        ieee = device.get("ieee_address", "unknown")
        self._friendly_name: str = device.get("friendly_name", ieee)
        prop = feature.get("property", "") if feature else ""

        self._attr_unique_id = f"{DOMAIN}_{ieee}_{prop or 'main'}"
        self._attr_name = feature.get("label", prop) if feature else None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ieee)},
            name=self._friendly_name,
            manufacturer=device.get("definition", {}).get("vendor"),
            model=device.get("definition", {}).get("model"),
        )

    @property
    def available(self) -> bool:
        avail = self._coordinator.get_device_availability(self._friendly_name)
        return avail != "offline"

    def _get_state_value(self, key: str) -> Any:
        return self._coordinator.get_device_state(self._friendly_name).get(key)

    async def async_added_to_hass(self) -> None:
        """Subscribe to state and availability updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_DEVICE_STATE_UPDATED}_{self._friendly_name}",
                self._on_state_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_DEVICE_AVAILABILITY}_{self._friendly_name}",
                self._on_availability_update,
            )
        )

    @callback
    def _on_state_update(self, state: dict) -> None:
        # Throttle state updates to prevent dispatcher flooding
        now = time.monotonic()
        if now - self._last_state_update < _STATE_UPDATE_THROTTLE:
            return
        self._last_state_update = now
        self.async_write_ha_state()

    @callback
    def _on_availability_update(self, availability: str) -> None:
        pass  # Suppress frequent logging - availability changes are handled via async_write_ha_state()

    async def _publish_set(self, payload: dict) -> None:
        """Publish /set command to device via WebSocket.
        
        Tracks pending state to ignore echo from Z2M after our own commands.
        """
        friendly_name = self._friendly_name
        coordinator = self._coordinator
        
        # Track pending state change
        if "state" in payload:
            coordinator._pending_state[friendly_name] = "ON" if payload["state"] == "ON" else "OFF"
        
        await coordinator.client.set_state(friendly_name, payload)
