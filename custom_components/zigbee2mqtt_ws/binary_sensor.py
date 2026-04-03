"""Binary sensor platform for Zigbee2MQTT."""
import logging
from typing import Any, List, Optional

from homeassistant import config_entries
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_ZIGBEE2MQTT_DEVICE_MESSAGE
from .websocket_client import Zigbee2MqttWebSocket

_LOGGER = logging.getLogger(__name__)

OCCUPANCY_DEVICE_CLASSES = ["motion", "occupancy", "presence"]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zigbee2MQTT binary sensor platform."""
    websocket = hass.data[DOMAIN].ws_client
    sensors = []

    @callback
    def _async_device_message(topic: str, payload: dict) -> None:
        for sensor in sensors:
            sensor.on_message(topic, payload)

    async_dispatcher_connect(hass, SIGNAL_ZIGBEE2MQTT_DEVICE_MESSAGE, _async_device_message)

    async def _load_devices(devices: List[dict]) -> None:
        for device in devices:
            if device.get("definition"):
                exposes = device.get("definition", {}).get("exposes", [])
                for exp in exposes:
                    if exp.get("type") == "binary":
                        sensors.append(
                            Zigbee2MqttBinarySensor(websocket, device, exp)
                        )
                        async_add_entities([sensors[-1]])

    websocket.register_message_callback(_load_devices)


class Zigbee2MqttBinarySensor(BinarySensorEntity):
    """Representation of a Zigbee2MQTT binary sensor."""

    def __init__(
        self, websocket: Zigbee2MqttWebSocket, device: dict, expose: dict
    ) -> None:
        """Initialize the binary sensor."""
        self.websocket = websocket
        self._device = device
        self._expose = expose
        self._state = None
        self._available = True
        self._attr_name = expose.get("property")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._device.get('friendly_name')} {self._attr_name}"

    @property
    def is_on(self) -> bool:
        """Return true if the sensor is on."""
        if self._state is None:
            return False
        return self._state

    @property
    def device_class(self) -> Optional[str]:
        """Return the device class."""
        device_class = self._expose.get("device_class")
        if device_class in OCCUPANCY_DEVICE_CLASSES:
            return "motion"
        return device_class

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
                    self._state = value == self._expose.get("value_on", "ON")
                else:
                    self._state = bool(value)
                self.async_write_ha_state()
