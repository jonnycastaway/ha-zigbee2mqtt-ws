"""Constants for Zigbee2MQTT WebSocket integration."""

DOMAIN = "zigbee2mqtt_ws"

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USE_SSL = "use_ssl"
CONF_AUTH_TOKEN = "auth_token"
CONF_BASE_TOPIC = "base_topic"

DEFAULT_PORT = 8080
DEFAULT_BASE_TOPIC = "zigbee2mqtt"

# Data keys stored in hass.data[DOMAIN]
DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"

# Z2M expose feature types
FEATURE_BINARY = "binary"
FEATURE_NUMERIC = "numeric"
FEATURE_ENUM = "enum"
FEATURE_TEXT = "text"
FEATURE_COMPOSITE = "composite"
FEATURE_LIST = "list"
FEATURE_COVER = "cover"

# Expose property names
PROP_STATE = "state"
PROP_BRIGHTNESS = "brightness"
PROP_COLOR_TEMP = "color_temp"
PROP_COLOR = "color"
PROP_COLOR_XY = "color_xy"
PROP_COLOR_HS = "color_hs"
PROP_OCCUPANCY = "occupancy"
PROP_CONTACT = "contact"
PROP_TEMPERATURE = "temperature"
PROP_HUMIDITY = "humidity"
PROP_PRESSURE = "pressure"
PROP_BATTERY = "battery"
PROP_LINKQUALITY = "linkquality"
PROP_POSITION = "position"
PROP_TILT = "tilt"
PROP_ACTION = "action"
PROP_LOCK = "lock"
PROP_CHILD_LOCK = "child_lock"
