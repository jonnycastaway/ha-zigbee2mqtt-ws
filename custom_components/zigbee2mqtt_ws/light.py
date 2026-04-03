"""Light platform for Zigbee2MQTT."""
import logging
from typing import Any, Callable, Dict, List, Optional

from homeassistant import config_entries
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ATTR_XY_COLOR,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR_TEMP,
    SUPPORT_EFFECT,
    SUPPORT_RGB_COLOR,
    SUPPORT_XY_COLOR,
    LightEntity,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import (
    color_hs_to_RGB,
    color_RGB_to_hs,
    color_RGB_to_xy,
    color_xy_to_RGB,
)

from .const import DOMAIN, SIGNAL_ZIGBEE2MQTT_DEVICE_MESSAGE
from .websocket_client import Zigbee2MqttWebSocket

_LOGGER = logging.getLogger(__name__)

DEFAULT_EFFECTS = [
    "blink",
    "breathe",
    "okay",
    "channel_change",
    "finish_effect",
    "stop_effect",
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zigbee2MQTT light platform."""
    websocket = hass.data[DOMAIN].ws_client
    lights = []

    @callback
    def _async_device_message(topic: str, payload: dict) -> None:
        for light in lights:
            light.on_message(topic, payload)

    async_dispatcher_connect(hass, SIGNAL_ZIGBEE2MQTT_DEVICE_MESSAGE, _async_device_message)

    async def _load_devices(devices: List[dict]) -> None:
        for device in devices:
            if device.get("definition"):
                exposes = device.get("definition", {}).get("exposes", [])
                has_light = any(
                    exp.get("type") in ["light", "color_light", "dimmer"]
                    for exp in exposes
                )
                if has_light:
                    lights.append(Zigbee2MqttLight(websocket, device))
                    async_add_entities([lights[-1]])

    websocket.register_message_callback(_load_devices)


class Zigbee2MqttLight(LightEntity):
    """Representation of a Zigbee2MQTT light."""

    def __init__(self, websocket: Zigbee2MqttWebSocket, device: dict) -> None:
        """Initialize the light."""
        self.websocket = websocket
        self._device = device
        self._state = {}
        self._available = True

    @property
    def name(self) -> str:
        """Return the name of the light."""
        return self._device.get("friendly_name")

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._state.get("state") == "ON"

    @property
    def brightness(self) -> Optional[int]:
        """Return the brightness of this light between 0..255."""
        return self._state.get("brightness")

    @property
    def color_temp(self) -> Optional[int]:
        """Return the color temperature in mireds."""
        return self._state.get("color_temp")

    @property
    def rgb_color(self) -> Optional[tuple]:
        """Return the rgb color."""
        color = self._state.get("color")
        if color and color.get("x") and color.get("y"):
            return color_xy_to_RGB(color["x"], color["y"])
        return None

    @property
    def xy_color(self) -> Optional[tuple]:
        """Return the xy color."""
        color = self._state.get("color")
        if color:
            return (color.get("x"), color.get("y"))
        return None

    @property
    def effect(self) -> Optional[str]:
        """Return the current effect."""
        return self._state.get("effect")

    @property
    def supported_features(self) -> int:
        """Return supported features."""
        features = 0
        if "brightness" in self._state:
            features |= SUPPORT_BRIGHTNESS
        if "color_temp" in self._state:
            features |= SUPPORT_COLOR_TEMP
        if self.xy_color:
            features |= SUPPORT_XY_COLOR
        if self.rgb_color:
            features |= SUPPORT_RGB_COLOR
        if "effect" in self._state:
            features |= SUPPORT_EFFECT
        return features

    @property
    def available(self) -> bool:
        """Return if the device is available."""
        return self._available

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device.get("ieee_address"))},
            "name": self._device.get("friendly_name"),
            "manufacturer": self._device.get("definition", {}).get("vendor"),
            "model": self._device.get("definition", {}).get("model"),
        }

    @callback
    def on_message(self, topic: str, payload: dict) -> None:
        """Handle incoming messages."""
        device_id = self._device.get("friendly_name")
        if topic == device_id or topic.startswith(f"{device_id}/"):
            self._state.update(payload)
            if "state" in payload:
                self._available = True
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        payload = {"state": "ON"}

        if ATTR_BRIGHTNESS in kwargs:
            payload["brightness"] = int(kwargs[ATTR_BRIGHTNESS])

        if ATTR_COLOR_TEMP in kwargs:
            payload["color_temp"] = kwargs[ATTR_COLOR_TEMP]

        if ATTR_RGB_COLOR in kwargs:
            x, y = color_RGB_to_xy(kwargs[ATTR_RGB_COLOR])
            payload["color"] = {"x": x, "y": y}

        if ATTR_XY_COLOR in kwargs:
            payload["color"] = {"x": kwargs[ATTR_XY_COLOR][0], "y": kwargs[ATTR_XY_COLOR][1]}

        if ATTR_EFFECT in kwargs:
            payload["effect"] = kwargs[ATTR_EFFECT]

        await self.websocket.publish(f"{self._device.get('friendly_name')}/set", payload)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self.websocket.publish(
            f"{self._device.get('friendly_name')}/set", {"state": "OFF"}
        )
