"""Climate platform for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SIGNAL_DEVICES_UPDATED, Z2MCoordinator
from .entity import Z2MEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

Z2M_HVAC_MAP: dict[str, HVACMode] = {
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "auto": HVACMode.AUTO,
    "off": HVACMode.OFF,
    "fan_only": HVACMode.FAN_ONLY,
    "dry": HVACMode.DRY,
    "heat_cool": HVACMode.HEAT_COOL,
}
HVAC_REVERSE: dict[HVACMode, str] = {v: k for k, v in Z2M_HVAC_MAP.items()}


def _has_climate(definition: dict | None) -> bool:
    if not definition:
        return False
    return any(e.get("type") == "climate" for e in definition.get("exposes", []))


def _get_climate_expose(definition: dict | None) -> dict | None:
    if not definition:
        return None
    return next(
        (e for e in definition.get("exposes", []) if e.get("type") == "climate"), None
    )


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
            if _has_climate(device.get("definition")):
                known.add(ieee)
                new_entities.append(Z2MClimate(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    async_dispatcher_connect(hass, SIGNAL_DEVICES_UPDATED, _add_devices)
    if coordinator.devices:
        _add_devices(coordinator.devices)


class Z2MClimate(Z2MEntity, ClimateEntity):
    """A Zigbee2MQTT climate (thermostat) entity."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: Z2MCoordinator, device: dict) -> None:
        super().__init__(coordinator, device, feature={"property": "climate", "label": "Climate"})

        expose = _get_climate_expose(device.get("definition")) or {}
        features_list = expose.get("features", [])
        feature_props = {f.get("property"): f for f in features_list}

        # Build supported features – TURN_ON/TURN_OFF required since HA 2025.x
        supported = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF

        if "occupied_heating_setpoint" in feature_props or "current_heating_setpoint" in feature_props:
            supported |= ClimateEntityFeature.TARGET_TEMPERATURE

        if "system_mode" in feature_props:
            modes_raw: list[str] = feature_props["system_mode"].get("values", [])
            self._attr_hvac_modes = [Z2M_HVAC_MAP.get(m, HVACMode.AUTO) for m in modes_raw]
            # Ensure OFF is always present
            if HVACMode.OFF not in self._attr_hvac_modes:
                self._attr_hvac_modes.append(HVACMode.OFF)
        else:
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

        if "fan_mode" in feature_props:
            supported |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes = feature_props["fan_mode"].get("values", [])

        if "preset" in feature_props:
            supported |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = feature_props["preset"].get("values", [])

        self._attr_supported_features = supported

        # Setpoint property name
        self._setpoint_prop = (
            "occupied_heating_setpoint"
            if "occupied_heating_setpoint" in feature_props
            else "current_heating_setpoint"
        )

        sp_feat = feature_props.get(self._setpoint_prop, {})
        self._attr_min_temp = sp_feat.get("value_min", 5)
        self._attr_max_temp = sp_feat.get("value_max", 35)
        self._attr_target_temperature_step = sp_feat.get("value_step", 0.5)

    @property
    def current_temperature(self) -> float | None:
        val = self._get_state_value("local_temperature")
        return float(val) if val is not None else None

    @property
    def target_temperature(self) -> float | None:
        val = self._get_state_value(self._setpoint_prop)
        return float(val) if val is not None else None

    @property
    def hvac_mode(self) -> HVACMode:
        mode = self._get_state_value("system_mode")
        return Z2M_HVAC_MAP.get(str(mode).lower(), HVACMode.OFF) if mode else HVACMode.OFF

    @property
    def fan_mode(self) -> str | None:
        return self._get_state_value("fan_mode")

    @property
    def preset_mode(self) -> str | None:
        return self._get_state_value("preset")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self._publish_set({self._setpoint_prop: temp})

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        z2m_mode = HVAC_REVERSE.get(hvac_mode, str(hvac_mode))
        await self._publish_set({"system_mode": z2m_mode})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._publish_set({"fan_mode": fan_mode})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._publish_set({"preset": preset_mode})

    async def async_turn_on(self) -> None:
        """Turn on – set HVAC mode to first non-off mode."""
        for mode in self._attr_hvac_modes:
            if mode != HVACMode.OFF:
                await self.async_set_hvac_mode(mode)
                return

    async def async_turn_off(self) -> None:
        """Turn off – set system_mode to off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
