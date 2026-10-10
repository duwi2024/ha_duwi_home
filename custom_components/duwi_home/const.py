"""Constants for the Duwi Iot."""

DOMAIN = "duwi_home"

# DUWI IOT
MANUFACTURER = "Duwi"

# Define constants for configuration keys
APP_KEY = "app_key"
APP_SECRET = "app_secret"
PHONE = "phone"
PASSWORD = "password"

# Additional configuration keys
ACCESS_TOKEN = "access_token"
REFRESH_TOKEN = "refresh_token"
ACCESS_TOKEN_EXPIRE_TIME = "access_token_expire_time"
REFRESH_TOKEN_EXPIRE_TIME = "refresh_token_expire_time"
HOUSE_NO = "house_no"
HOUSE_NAME = "house_name"
HOUSE_LAN_SECRET_KEY = "house_lan_secret_key"
FIRST_INIT = "first_init"

# Services
SERVICE_REFRESH_DEVICES = "refresh_devices"

# Dispatcher signals for RPS push updates
SIGNAL_DEVICE_UPDATE = f"{DOMAIN}_device_update_{{}}"
SIGNAL_DEVICE_GROUP_UPDATE = f"{DOMAIN}_device_group_update_{{}}"
