"""Lock platform for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SIGNAL_DEVICES_UPDATED, Z2MCoordinator
from .entity import Z2MEntity

_LOGGER = logging.getLogger(__name__)


def _has_lock(definition: dict | None) -> bool:
    if not definition:
        return False
    for expose in definition.get("exposes", []):
        if expose.get("type") == "lock":
            return True
    return False


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Z2MCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    known: set[str] = set()

    @callback
    def _add_devices(devices: list[dict]) -> None:
        new_entities = []
        for device in devices:
            ieee = device.get("ieee_address")
            if not ieee or ieee in known:
                continue
            if _has_lock(device.get("definition")):
                known.add(ieee)
                new_entities.append(Z2MLock(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    async_dispatcher_connect(hass, SIGNAL_DEVICES_UPDATED, _add_devices)
    if coordinator.devices:
        _add_devices(coordinator.devices)


class Z2MLock(Z2MEntity, LockEntity):
    """A Zigbee2MQTT lock entity."""

    _attr_name = None

    def __init__(self, coordinator: Z2MCoordinator, device: dict) -> None:
        super().__init__(coordinator, device, feature={"property": "state", "label": "Lock"})

    @property
    def is_locked(self) -> bool | None:
        state = self._get_state_value("state")
        if state is None:
            return None
        return str(state).upper() == "LOCK"

    async def async_lock(self, **kwargs: Any) -> None:
        await self._publish_set({"state": "LOCK"})

    async def async_unlock(self, **kwargs: Any) -> None:
        await self._publish_set({"state": "UNLOCK"})
