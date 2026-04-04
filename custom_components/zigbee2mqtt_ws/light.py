"""Light platform for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ATTR_TRANSITION,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SIGNAL_DEVICES_UPDATED, Z2MCoordinator
from .entity import Z2MEntity

_LOGGER = logging.getLogger(__name__)

# Required for HA 2025.4+ – 0 = no limit, coordinator handles all updates
PARALLEL_UPDATES = 0


def _is_light(definition: dict | None) -> bool:
    if not definition:
        return False
    for expose in definition.get("exposes", []):
        if expose.get("type") == "light":
            return True
    return False


def _get_light_features(definition: dict | None) -> list[dict]:
    if not definition:
        return []
    for expose in definition.get("exposes", []):
        if expose.get("type") == "light":
            return expose.get("features", [])
    return []


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
            definition = device.get("definition")
            if _is_light(definition):
                known.add(ieee)
                new_entities.append(Z2MLight(coordinator, device))
        if new_entities:
            _LOGGER.info("Adding %d new light entities", len(new_entities))
            async_add_entities(new_entities)

    async_dispatcher_connect(hass, SIGNAL_DEVICES_UPDATED, _add_devices)
    if coordinator.devices:
        _add_devices(coordinator.devices)


class Z2MLight(Z2MEntity, LightEntity):
    """Representation of a Zigbee2MQTT light."""

    def __init__(self, coordinator: Z2MCoordinator, device: dict) -> None:
        super().__init__(coordinator, device, feature=None)
        self._attr_name = None

        features = _get_light_features(device.get("definition"))
        feature_props = {f.get("property") for f in features}

        # Determine supported color modes (HA 2022.5+ Kelvin API)
        supported_color_modes: set[ColorMode] = set()
        if "color_xy" in feature_props or "color" in feature_props:
            supported_color_modes.add(ColorMode.XY)
        if "color_hs" in feature_props:
            supported_color_modes.add(ColorMode.HS)
        if "color_temp" in feature_props:
            supported_color_modes.add(ColorMode.COLOR_TEMP)
        if "brightness" in feature_props and not supported_color_modes:
            supported_color_modes.add(ColorMode.BRIGHTNESS)
        if not supported_color_modes:
            supported_color_modes.add(ColorMode.ONOFF)

        self._attr_supported_color_modes = supported_color_modes
        # color_mode must always be set – HA 2026.3 removed the legacy fallback
        self._attr_color_mode = next(iter(supported_color_modes))

        # Color temp range in mireds; convert to Kelvin for HA 2022.9+ API
        for feat in features:
            if feat.get("property") == "color_temp":
                vmin = feat.get("value_min")
                vmax = feat.get("value_max")
                if vmin and vmax:
                    # Z2M exposes mireds; HA wants Kelvin (higher mired = lower Kelvin)
                    self._attr_min_color_temp_kelvin = round(1_000_000 / vmax)
                    self._attr_max_color_temp_kelvin = round(1_000_000 / vmin)

        # Transition support
        self._attr_supported_features = (
            LightEntityFeature.TRANSITION
            if any(f.get("property") == "transition" for f in features)
            else LightEntityFeature(0)
        )

    @property
    def is_on(self) -> bool | None:
        state = self._get_state_value("state")
        if state is None:
            return None
        return str(state).upper() == "ON"

    @property
    def brightness(self) -> int | None:
        val = self._get_state_value("brightness")
        return int(val) if val is not None else None

    @property
    def color_mode(self) -> ColorMode:
        """Return current color mode based on last received state."""
        if self._get_state_value("color") is not None:
            color = self._get_state_value("color")
            if isinstance(color, dict):
                if "hue" in color:
                    return ColorMode.HS
                if "x" in color:
                    return ColorMode.XY
        if self._get_state_value("color_temp") is not None:
            if ColorMode.COLOR_TEMP in self._attr_supported_color_modes:
                return ColorMode.COLOR_TEMP
        return self._attr_color_mode

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return color temp in Kelvin (Z2M reports mireds)."""
        val = self._get_state_value("color_temp")
        if val is None:
            return None
        try:
            return round(1_000_000 / int(val))
        except (ZeroDivisionError, ValueError, TypeError):
            return None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        color = self._get_state_value("color")
        if isinstance(color, dict) and "hue" in color and "saturation" in color:
            return (float(color["hue"]), float(color["saturation"]))
        return None

    @property
    def xy_color(self) -> tuple[float, float] | None:
        color = self._get_state_value("color")
        if isinstance(color, dict) and "x" in color and "y" in color:
            return (float(color["x"]), float(color["y"]))
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        payload: dict[str, Any] = {"state": "ON"}
        if ATTR_BRIGHTNESS in kwargs:
            payload["brightness"] = kwargs[ATTR_BRIGHTNESS]
        # HA passes color_temp_kelvin; convert back to mireds for Z2M
        if "color_temp_kelvin" in kwargs:
            kelvin = kwargs["color_temp_kelvin"]
            payload["color_temp"] = round(1_000_000 / kelvin)
        if ATTR_XY_COLOR in kwargs:
            x, y = kwargs[ATTR_XY_COLOR]
            payload["color"] = {"x": x, "y": y}
        if ATTR_HS_COLOR in kwargs:
            h, s = kwargs[ATTR_HS_COLOR]
            payload["color"] = {"hue": h, "saturation": s}
        if ATTR_TRANSITION in kwargs:
            payload["transition"] = kwargs[ATTR_TRANSITION]
        await self._publish_set(payload)

    async def async_turn_off(self, **kwargs: Any) -> None:
        payload: dict[str, Any] = {"state": "OFF"}
        if ATTR_TRANSITION in kwargs:
            payload["transition"] = kwargs[ATTR_TRANSITION]
        await self._publish_set(payload)
