"""Switch platform for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SIGNAL_DEVICES_UPDATED, Z2MCoordinator
from .entity import Z2MEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _get_switch_exposes(definition: dict | None) -> list[dict]:
    if not definition:
        return []
    result = []
    for expose in definition.get("exposes", []):
        if expose.get("type") == "switch":
            for feat in expose.get("features", []):
                if feat.get("property") == "state" and feat.get("access", 0) & 2:
                    result.append(expose)
                    break
        elif (
            expose.get("type") == "binary"
            and expose.get("property") == "state"
            and expose.get("access", 0) & 2
        ):
            result.append(expose)
    return result


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
            if not ieee:
                continue
            definition = device.get("definition")
            exposes = _get_switch_exposes(definition)
            for expose in exposes:
                uid = f"{ieee}_switch"
                if uid in known:
                    continue
                known.add(uid)
                new_entities.append(Z2MSwitch(coordinator, device, expose))
        if new_entities:
            async_add_entities(new_entities)

    async_dispatcher_connect(hass, SIGNAL_DEVICES_UPDATED, _add_devices)
    if coordinator.devices:
        _add_devices(coordinator.devices)


class Z2MSwitch(Z2MEntity, SwitchEntity):
    """A Zigbee2MQTT switch entity."""

    def __init__(self, coordinator: Z2MCoordinator, device: dict, expose: dict) -> None:
        super().__init__(coordinator, device, feature={"property": "state", "label": "Switch"})
        self._expose = expose
        self._attr_name = None

    @property
    def is_on(self) -> bool | None:
        state = self._get_state_value("state")
        if state is None:
            return None
        return str(state).upper() == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._publish_set({"state": "ON"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._publish_set({"state": "OFF"})
