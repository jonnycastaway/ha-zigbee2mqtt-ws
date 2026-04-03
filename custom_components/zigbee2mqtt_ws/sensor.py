"""Sensor platform for Zigbee2MQTT."""
import logging
from typing import Any, Callable, Dict, List, Optional

from homeassistant import config_entries
from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_HUMIDITY,
    DEVICE_CLASS_ILLUMINANCE,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_TEMPERATURE,
    DEVICE_CLASS_VOLTAGE,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    DATA_DEVICE_CONFIG,
    DATA_DISCOVERY,
    DOMAIN,
    SIGNAL_ZIGBEE2MQTT_AVAILABILITY,
    SIGNAL_ZIGBEE2MQTT_BRIDGE_INFO,
    SIGNAL_ZIGBEE2MQTT_BRIDGE_STATE,
    SIGNAL_ZIGBEE2MQTT_DEVICE_MESSAGE,
    SIGNAL_ZIGBEE2MQTT_DEVICES,
    SIGNAL_ZIGBEE2MQTT_GROUPS,
)
from .websocket_client import Zigbee2MqttWebSocket

_LOGGER = logging.getLogger(__name__)


DEVICE_CLASS_MAPPING = {
    "battery": DEVICE_CLASS_BATTERY,
    "humidity": DEVICE_CLASS_HUMIDITY,
    "illuminance": DEVICE_CLASS_ILLUMINANCE,
    "temperature": DEVICE_CLASS_TEMPERATURE,
    "power": DEVICE_CLASS_POWER,
    "voltage": DEVICE_CLASS_VOLTAGE,
}

STATE_CLASS_MAPPING = {
    "battery": SensorStateClass.MEASUREMENT,
    "humidity": SensorStateClass.MEASUREMENT,
    "temperature": SensorStateClass.MEASUREMENT,
    "power": SensorStateClass.MEASUREMENT,
    "voltage": SensorStateClass.MEASUREMENT,
}

UNIT_MAPPING = {
    "battery": PERCENTAGE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zigbee2MQTT sensor platform."""

    @callback
    def _async_device_message(topic: str, payload: dict) -> None:
        pass

    async_dispatcher_connect(hass, SIGNAL_ZIGBEE2MQTT_DEVICE_MESSAGE, _async_device_message)


class Zigbee2MqttSensor(SensorEntity):
    """Representation of a Zigbee2MQTT sensor."""

    def __init__(
        self,
        websocket: Zigbee2MqttWebSocket,
        device: dict,
        attribute: str,
        name: str,
        unit: Optional[str] = None,
    ) -> None:
        """Initialize the sensor."""
        self.websocket = websocket
        self._device = device
        self._attribute = attribute
        self._name = name
        self._unit = unit
        self._state = None
        self._available = True

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self._name

    @property
    def state(self) -> Any:
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self) -> Optional[str]:
        """Return the unit of measurement."""
        return self._unit

    @property
    def device_class(self) -> Optional[str]:
        """Return the device class."""
        return DEVICE_CLASS_MAPPING.get(self._attribute)

    @property
    def state_class(self) -> Optional[str]:
        """Return the state class."""
        return STATE_CLASS_MAPPING.get(self._attribute)

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

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        pass
