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

# Truly numeric sensors with state_class MEASUREMENT
NUMERIC_SENSOR_PROPS = {
    "temperature",
    "humidity", 
    "pressure",
    "battery",
    "power",
    "energy",
    "voltage",
    "current",
    "illuminance",
    "illuminance_lux",
    "co2",
    "voc",
    "pm25",
    "pm10",
    "angle",
    "device_temperature",
    "local_temperature",
    "linkquality",
}

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
    "angle": (None, "°", SensorStateClass.MEASUREMENT),
    "device_temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT),
    "local_temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT),
}

BINARY_PROPS = {"occupancy", "contact", "water_leak", "smoke", "gas", "tamper", "vibration", "motion"}

# Properties that are enum/text - NO state_class (causes errors in HA 2026+)
NON_NUMERIC_PROPS = {
    # Generic
    "action",
    "color",
    "mode",
    "update",
    "linkquality",  # Has its own state_class handling in SENSOR_MAP
    # Enum properties from devices
    "indicator_mode",
    "power_outage_memory", 
    "child_lock",
    "temperature_display_mode",
    "switch_type",
    "power_on_behavior",
    "effect",
    "state",
    "alert",
    "alarm",
    "alarm_temperature",
    "alarm_battery",
    "available",
    "battery_low",
    "battery_warning",
    "calibration",
    "cardinality",
    "command",
    "consumer_connected",
    "consumer_overload",
    "cover_position",
    "cover_tilt_position",
    "dead",
    "detected",
    "direction",
    "do_not_disturb",
    "driver_installed",
    "eco_mode",
    "enrolled",
    "error",
    "fan_mode",
    "fast_pro响",
    "heating_running_state",
    "humidity_alarm",
    "last_seen",
    "load_status",
    "operating_mode",
    "opple_mode",
    "pin_code",
    "preheat_status",
    "programming_operation_mode",
    "proxy",
    "push",
    "reset_pin_code",
    "running_state",
    "sensitivity",
    "sensor_mode",
    "sensor_type",
    "silence",
    "smoke_alarm",
    "sound",
    "steam",
    "supply",
    "support",
    "tampered",
    "test",
    "thermostat",
    "valve_alarm",
    "valve_state",
    "water_alarm",
    "window_detection",
}


def _get_sensor_exposes(definition: dict | None) -> list[dict]:
    """Get sensor exposes based on expose type."""
    if not definition:
        return []
    result = []
    for expose in definition.get("exposes", []):
        t = expose.get("type")
        prop = expose.get("property", "")
        
        # Binary types go to binary_sensor platform
        if t == "binary":
            continue
        
        # Only numeric type gets state_class MEASUREMENT
        # enum and text types are strings (no state_class)
        if t in ("numeric", "enum", "text") and prop and expose.get("access", 1) & 1:
            result.append(expose)
        
        # Handle composite/climate features
        if t in ("composite", "climate"):
            for feat in expose.get("features", []):
                ft = feat.get("type")
                fp = feat.get("property", "")
                if ft == "binary":
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
        
        # Only truly numeric properties get state_class
        if prop in NUMERIC_SENSOR_PROPS:
            meta = SENSOR_MAP.get(prop, (None, expose.get("unit"), SensorStateClass.MEASUREMENT))
            self._attr_device_class = meta[0]
            self._attr_native_unit_of_measurement = expose.get("unit") or meta[1]
            self._attr_state_class = meta[2]
        else:
            # Enum/text properties - no state_class
            self._attr_device_class = None
            self._attr_native_unit_of_measurement = expose.get("unit")
            self._attr_state_class = None
        
        self._prop = prop

    @property
    def native_value(self):
        val = self._get_state_value(self._prop)
        
        # Handle None/missing values
        if val is None:
            return None
        
        # For numeric properties, convert to number
        if self._prop in NUMERIC_SENSOR_PROPS and self._attr_state_class is not None:
            try:
                # Try int first, then float
                if isinstance(val, (int, float)):
                    return val
                val_str = str(val)
                if "." in val_str:
                    return float(val_str)
                return int(val_str)
            except (ValueError, TypeError):
                _LOGGER.debug("Sensor %s: cannot convert '%s' to numeric", self.unique_id, val)
                return None
        
        # Return value as-is for non-numeric (enum/text) properties
        return val
