"""Constants for Zigbee2MQTT WebSocket integration."""
import logging

DOMAIN = "zigbee2mqtt_ws"

LOGGER = logging.getLogger(__name__)

CONF_DISABLE_DISCOVERY = "disable_discovery"
CONF_USE_LEGACY_ENTITY_NAMING = "use_legacy_entity_naming"

DATA_DEVICE_CONFIG = "device_config"
DATA_DISCOVERY = "discovery"
DATA_ZIGBEE_GROUPS = "zigbee_groups"

DEFAULT_PORT = 8080

SIGNAL_ZIGBEE2MQTT_DEVICES = "zigbee2mqtt_devices"
SIGNAL_ZIGBEE2MQTT_GROUPS = "zigbee2mqtt_groups"
SIGNAL_ZIGBEE2MQTT_BRIDGE_INFO = "zigbee2mqtt_bridge_info"
SIGNAL_ZIGBEE2MQTT_BRIDGE_STATE = "zigbee2mqtt_bridge_state"
SIGNAL_ZIGBEE2MQTT_AVAILABILITY = "zigbee2mqtt_availability"
SIGNAL_ZIGBEE2MQTT_DEVICE_MESSAGE = "zigbee2mqtt_device_message"
