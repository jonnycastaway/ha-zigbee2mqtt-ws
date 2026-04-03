"""Switch platform for Zigbee2MQTT."""
import logging
from typing import Any, List, Optional

from homeassistant import config_entries
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_ZIGBEE2MQTT_DEVICE_MESSAGE
from .websocket_client import Zigbee2MqttWebSocket

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zigbee2MQTT switch platform."""
    websocket = hass.data[DOMAIN].ws_client
    switches = []

    @callback
    def _async_device_message(topic: str, payload: dict) -> None:
        for switch in switches:
            switch.on_message(topic, payload)

    async_dispatcher_connect(hass, SIGNAL_ZIGBEE2MQTT_DEVICE_MESSAGE, _async_device_message)

    async def _load_devices(devices: List[dict]) -> None:
        for device in devices:
            if device.get("definition"):
                exposes = device.get("definition", {}).get("exposes", [])
                for exp in exposes:
                    if exp.get("type") == "switch" and exp.get("property"):
                        switches.append(Zigbee2MqttSwitch(websocket, device, exp))
                        async_add_entities([switches[-1]])

    websocket.register_message_callback(_load_devices)


class Zigbee2MqttSwitch(SwitchEntity):
    """Representation of a Zigbee2MQTT switch."""

    def __init__(
        self, websocket: Zigbee2MqttWebSocket, device: dict, expose: dict
    ) -> None:
        """Initialize the switch."""
        self.websocket = websocket
        self._device = device
        self._expose = expose
        self._state = None
        self._available = True
        self._attr_name = expose.get("property")

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return f"{self._device.get('friendly_name')} {self._attr_name}"

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        if self._state is None:
            return False
        return self._state

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
            if self._attr_name in payload:
                value = payload[self._attr_name]
                if isinstance(value, str):
                    self._state = value == "ON"
                else:
                    self._state = bool(value)
                self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.websocket.publish(
            f"{self._device.get('friendly_name')}/set",
            {self._attr_name: self._expose.get("value_on", "ON")}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.websocket.publish(
            f"{self._device.get('friendly_name')}/set",
            {self._attr_name: self._expose.get("value_off", "OFF")}
        )
