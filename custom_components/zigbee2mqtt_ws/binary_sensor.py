"""Binary sensor platform for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SIGNAL_DEVICES_UPDATED, Z2MCoordinator
from .entity import Z2MEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

BINARY_MAP: dict[str, BinarySensorDeviceClass | None] = {
    "occupancy": BinarySensorDeviceClass.OCCUPANCY,
    "contact": BinarySensorDeviceClass.DOOR,
    "water_leak": BinarySensorDeviceClass.MOISTURE,
    "smoke": BinarySensorDeviceClass.SMOKE,
    "gas": BinarySensorDeviceClass.GAS,
    "tamper": BinarySensorDeviceClass.TAMPER,
    "vibration": BinarySensorDeviceClass.VIBRATION,
    "motion": BinarySensorDeviceClass.MOTION,
    "presence": BinarySensorDeviceClass.PRESENCE,
    "battery_low": BinarySensorDeviceClass.BATTERY,
    "update_available": BinarySensorDeviceClass.UPDATE,
}


def _get_binary_exposes(definition: dict | None) -> list[dict]:
    if not definition:
        return []
    return [
        e for e in definition.get("exposes", [])
        if e.get("property", "") in BINARY_MAP and e.get("type") == "binary"
    ]


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
            for expose in _get_binary_exposes(device.get("definition")):
                prop = expose.get("property", "")
                uid = f"{ieee}_{prop}"
                if uid in known:
                    continue
                known.add(uid)
                new_entities.append(Z2MBinarySensor(coordinator, device, expose))
        if new_entities:
            async_add_entities(new_entities)

    async_dispatcher_connect(hass, SIGNAL_DEVICES_UPDATED, _add_devices)
    if coordinator.devices:
        _add_devices(coordinator.devices)


class Z2MBinarySensor(Z2MEntity, BinarySensorEntity):
    """A Zigbee2MQTT binary sensor."""

    def __init__(self, coordinator: Z2MCoordinator, device: dict, expose: dict) -> None:
        super().__init__(coordinator, device, feature=expose)
        prop = expose.get("property", "")
        self._prop = prop
        self._attr_device_class = BINARY_MAP.get(prop)
        # contact=True means closed in Z2M → HA door sensor True=open → invert
        self._invert = prop == "contact"
        self._value_on = expose.get("value_on", True)

    @property
    def is_on(self) -> bool | None:
        val = self._get_state_value(self._prop)
        if val is None:
            return None
        is_on = val == self._value_on or val is True or str(val).lower() == "true"
        return (not is_on) if self._invert else is_on
