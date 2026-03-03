"""Constants for the neptun4hass integration."""

DOMAIN = "neptun4hass"

# Options keys
CONF_LINE_IN_CONFIG = "line_in_config"
CONF_CLOSE_ON_OFFLINE = "close_on_offline"

DEFAULT_PORT = 6350
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 5
SOCKET_BUFSIZE = 1024
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
REQUEST_DELAY = 0.5

# Packet types
PACKET_SYSTEM_STATE = 0x52
PACKET_COUNTER_NAME = 0x63
PACKET_COUNTER_STATE = 0x43
PACKET_SENSOR_NAME = 0x4E
PACKET_SENSOR_STATE = 0x53
PACKET_BACK_STATE = 0x42
PACKET_SET_SYSTEM_STATE = 0x57

# Packet header
PACKET_HEADER = bytearray([0x02, 0x54, 0x51])

# Response tags in SYSTEM_STATE
TAG_DEVICE_INFO = 73   # 0x49 — type + version
TAG_NAME = 78          # 0x4E — device name
TAG_MAC = 77           # 0x4D — MAC address
TAG_ACCESS = 65        # 0x41 — access flag
TAG_STATE = 83         # 0x53 — main state
TAG_WIRED_LINES = 115  # 0x73 — wired line states

# Status bitmask
STATUS_NORMAL = 0x00
STATUS_ALARM = 0x01
STATUS_MAIN_BATTERY = 0x02
STATUS_SENSOR_BATTERY = 0x04
STATUS_SENSOR_OFFLINE = 0x08

MANUFACTURER = "Neptun/SST"
MODEL = "ProW+ WiFi"

PLATFORMS: list[str] = ["binary_sensor", "sensor", "switch"]
