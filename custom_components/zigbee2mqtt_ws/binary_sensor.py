"""Binary sensor platform for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HOST, CONF_PORT, DATA_COORDINATOR, DOMAIN
from .coordinator import SIGNAL_CONNECTION_STATE, SIGNAL_DEVICES_UPDATED, Z2MCoordinator
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

    # Link diagnostics - independent of any device
    async_add_entities([Z2MConnectionSensor(coordinator, entry)])

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


class Z2MConnectionSensor(BinarySensorEntity):
    """Connectivity of the WebSocket link to Zigbee2MQTT.

    Purely diagnostic: it never touches the availability of other entities.
    Zigbee2MQTT already publishes per-device availability, and flipping every
    entity to unavailable on a transport hiccup has side effects (alarm panels
    treat unavailable sensors as triggered).
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Z2MCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_connection_{entry.entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"bridge_{entry.entry_id}")},
            name="Zigbee2MQTT (WebSocket)",
            manufacturer="Zigbee2MQTT",
            model="WebSocket API",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=(
                f"http://{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}"
            ),
        )

    @property
    def available(self) -> bool:
        # Must stay available, otherwise a dead link could not be reported
        return True

    @property
    def is_on(self) -> bool:
        return self._coordinator.connection_ok

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CONNECTION_STATE,
                self._on_connection_update,
            )
        )

    @callback
    def _on_connection_update(self, ok: bool) -> None:
        self.async_write_ha_state()


class Z2MBinarySensor(Z2MEntity, BinarySensorEntity):
    """A Zigbee2MQTT binary sensor."""

    def __init__(self, coordinator: Z2MCoordinator, device: dict, expose: dict) -> None:
        super().__init__(coordinator, device, feature=expose)
        prop = expose.get("property", "")
        self._prop = prop
        self._attr_device_class = BINARY_MAP.get(prop)
        # Z2M: contact=false means open (free), contact=true means closed (contact)
        # HA DOOR: True=closed, False=open - INVERT needed
        self._invert = prop == "contact"

    @property
    def is_on(self) -> bool | None:
        val = self._get_state_value(self._prop)
        if val is None:
            return None
        # Parse the value
        if isinstance(val, bool):
            raw_on = val
        elif isinstance(val, str):
            raw_on = val.lower() == "true"
        elif isinstance(val, (int, float)):
            raw_on = bool(val)
        else:
            return None
        
        # Invert for contact (Z2M: true=closed, HA: true=open)
        if self._invert:
            return not raw_on
        return raw_on
