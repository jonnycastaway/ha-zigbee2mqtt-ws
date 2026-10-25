"""Base entity for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.event import async_call_later

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
        self._pending_write: Callable[[], None] | None = None

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
        self.async_on_remove(self._cancel_pending_write)

    @callback
    def _cancel_pending_write(self) -> None:
        if self._pending_write is not None:
            self._pending_write()
            self._pending_write = None

    @callback
    def _on_state_update(self, state: dict) -> None:
        """Write the new state, throttled but never losing the last update."""
        now = time.monotonic()
        if now - self._last_state_update < _STATE_UPDATE_THROTTLE:
            # Burst of messages: do not drop this update, write it once the
            # throttle window has passed. Dropping it left the entity stuck on
            # the previous value until the next message arrived.
            if self._pending_write is None:
                self._pending_write = async_call_later(
                    self.hass, _STATE_UPDATE_THROTTLE, self._delayed_state_update
                )
            return

        self._flush_state()

    @callback
    def _delayed_state_update(self, _now: Any) -> None:
        self._pending_write = None
        self._flush_state()

    @callback
    def _flush_state(self) -> None:
        self._last_state_update = time.monotonic()
        self.async_write_ha_state()

    @callback
    def _on_availability_update(self, availability: str) -> None:
        self.async_write_ha_state()

    async def _publish_set(self, payload: dict) -> None:
        """Publish /set command to device via WebSocket.

        Uses an optimistic update - the values we send are applied to the local
        state right away so the UI does not lag behind until Z2M answers.
        The confirmation from Z2M is always merged afterwards.
        """
        friendly_name = self._friendly_name
        coordinator = self._coordinator

        optimistic: dict[str, Any] = {}
        if "state" in payload:
            # Raw value, not just ON/OFF: covers use OPEN/CLOSE/STOP and locks
            # use LOCK/UNLOCK - mapping those to OFF broke their state.
            optimistic["state"] = str(payload["state"]).upper()
        for key in ("brightness", "color_temp", "color"):
            if key in payload:
                optimistic[key] = payload[key]

        if optimistic:
            coordinator.device_states.setdefault(friendly_name, {}).update(optimistic)
            self.async_write_ha_state()

        await coordinator.client.set_state(friendly_name, payload)
