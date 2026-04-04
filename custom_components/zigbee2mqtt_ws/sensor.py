"""Sensor platform for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SIGNAL_DEVICES_UPDATED, Z2MCoordinator
from .entity import Z2MEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Map Z2M property name -> (device_class, unit, state_class)
SENSOR_MAP: dict[str, tuple] = {
    "temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT),
    "humidity": (SensorDeviceClass.HUMIDITY, PERCENTAGE, SensorStateClass.MEASUREMENT),
    "pressure": (SensorDeviceClass.PRESSURE, UnitOfPressure.HPA, SensorStateClass.MEASUREMENT),
    "battery": (SensorDeviceClass.BATTERY, PERCENTAGE, SensorStateClass.MEASUREMENT),
    "linkquality": (None, "lqi", SensorStateClass.MEASUREMENT),
    "power": (SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT),
    "energy": (SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, SensorStateClass.TOTAL_INCREASING),
    "voltage": (SensorDeviceClass.VOLTAGE, "V", SensorStateClass.MEASUREMENT),
    "current": (SensorDeviceClass.CURRENT, "A", SensorStateClass.MEASUREMENT),
    "illuminance": (SensorDeviceClass.ILLUMINANCE, "lx", SensorStateClass.MEASUREMENT),
    "illuminance_lux": (SensorDeviceClass.ILLUMINANCE, "lx", SensorStateClass.MEASUREMENT),
    "co2": (SensorDeviceClass.CO2, "ppm", SensorStateClass.MEASUREMENT),
    "voc": (SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS, "µg/m³", SensorStateClass.MEASUREMENT),
    "pm25": (SensorDeviceClass.PM25, "µg/m³", SensorStateClass.MEASUREMENT),
    "pm10": (SensorDeviceClass.PM10, "µg/m³", SensorStateClass.MEASUREMENT),
    "action": (None, None, None),
    "angle": (None, "°", SensorStateClass.MEASUREMENT),
}

BINARY_PROPS = {"occupancy", "contact", "water_leak", "smoke", "gas", "tamper", "vibration", "motion"}

# Properties that are enum/text - need state_class=None (not MEASUREMENT)
NON_NUMERIC_PROPS = {
    "indicator_mode",
    "power_outage_memory", 
    "child_lock",
    "mode",
    "color",
    "update",
    "alarm",
    "action",
    "temperature_display_mode",
    "switch_type",
    "power_on_behavior",
    "effect",
}


def _get_sensor_exposes(definition: dict | None) -> list[dict]:
    if not definition:
        return []
    result = []
    for expose in definition.get("exposes", []):
        t = expose.get("type")
        prop = expose.get("property", "")
        if prop in BINARY_PROPS:
            continue
        if t in ("numeric", "enum", "text") and prop and expose.get("access", 1) & 1:
            result.append(expose)
        if t in ("composite", "climate"):
            for feat in expose.get("features", []):
                ft = feat.get("type")
                fp = feat.get("property", "")
                if fp in BINARY_PROPS:
                    continue
                if ft in ("numeric", "enum") and fp and feat.get("access", 1) & 1:
                    result.append(feat)
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
            for expose in _get_sensor_exposes(device.get("definition")):
                prop = expose.get("property", "")
                uid = f"{ieee}_{prop}"
                if uid in known:
                    continue
                known.add(uid)
                new_entities.append(Z2MSensor(coordinator, device, expose))
        if new_entities:
            async_add_entities(new_entities)

    async_dispatcher_connect(hass, SIGNAL_DEVICES_UPDATED, _add_devices)
    if coordinator.devices:
        _add_devices(coordinator.devices)


class Z2MSensor(Z2MEntity, SensorEntity):
    """A Zigbee2MQTT sensor entity."""

    def __init__(self, coordinator: Z2MCoordinator, device: dict, expose: dict) -> None:
        super().__init__(coordinator, device, feature=expose)
        prop = expose.get("property", "")
        meta = SENSOR_MAP.get(prop, (None, expose.get("unit"), SensorStateClass.MEASUREMENT))
        self._attr_device_class = meta[0]
        self._attr_native_unit_of_measurement = expose.get("unit") or meta[1]
        # Enum/text properties should NOT have state_class (causes error in HA 2026+)
        if prop in NON_NUMERIC_PROPS:
            self._attr_state_class = None
        else:
            self._attr_state_class = meta[2]
        self._prop = prop

    @property
    def native_value(self):
        val = self._get_state_value(self._prop)
        # For properties with state_class (numeric sensors), convert to number
        if self._attr_state_class is not None and val is not None:
            try:
                return float(val) if "." in str(val) else int(val)
            except (ValueError, TypeError):
                _LOGGER.warning("Sensor %s: cannot convert '%s' to numeric", self.unique_id, val)
                return None
        return val
