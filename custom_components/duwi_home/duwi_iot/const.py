"""Constants for the Duwi Home integration."""

# Define constants for smarhome
from enum import Enum

APP_VERSION = "1.0.0"
CLIENT_VERSION = "1.0.0"
CLIENT_MODEL = "duwi_ha"
HTTP_ADDRESS = "https://openapi.duwi.com.cn/homeApi/v1/"
WEBSOCKET_ADDRESS = "wss://openws.duwi.com.cn:32013"
DUWI_DATABASE_NAME = "duwi_data.db"

# LAN Protocol Constants
LAN_MULTICAST_ADDR = "239.0.0.188"
LAN_MULTICAST_PORT = 54283
LAN_HEARTBEAT_INTERVAL = 20
LAN_HEARTBEAT_TIMEOUT = 120
LAN_DISCOVER_INTERVAL = 60
LAN_PROTOCOL_VERSION = 0b00
LAN_CLIENT_DEVICE_ID = b"\xFF\xFF\xFF\xFF\xFF\xFF"

# LAN Message Types
LAN_MSG_TYPE_CON = 0b00
LAN_MSG_TYPE_NON = 0b01
LAN_MSG_TYPE_ACK = 0b10
LAN_MSG_TYPE_RST = 0b11

# LAN Packet Markers
LAN_PACKET_HEADER = b"\xFA\xAF"
LAN_PACKET_FOOTER = b"\xFB\xBF"


class ResultCode(Enum):
    """Duwi IoT result codes."""
    # 系统业务返回码
    SUCCESS = "10000"  # 操作成功
    FAILED = "100014"  # 操作失败
    INVALID_PARAMS = "10004"  # 请求参数不正确
    ACCESS_TOKEN_ERROR = "10005"  # accessToken异常或过期
    REFRESH_TOKEN_ERROR = "10006"  # refreshToken异常或过期
    ACCOUNT_PASSWORD_ERROR = "11000"  # 账户名或者密码错误
    ACCOUNT_UNAUTHORIZED = "11004"  # 账户未授权
    BACKEND_SERVICE_ERROR = "19998"  # 后台服务错误
    SYSTEM_ERROR = "19999"  # 系统错误

    # 网关返回码
    APP_KEY_ERROR = "99001"  # appKey异常
    SIGNATURE_ERROR = "99002"  # 签名错误
    TIMESTAMP_TIMEOUT = "99003"  # 时间戳请求超时
    RATE_LIMIT_SECOND = "99004"  # 系统频率限制
    RATE_LIMIT_MINUTE = "99005"  # 系统分钟频率限制
    RATE_LIMIT_HOUR = "99006"  # 系统小时频率限制
    GATEWAY_SYSTEM_ERROR = "99999"  # 网关系统错误

class DuwiIotError(Exception):
    """Duwi IoT exception class."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Duwi IoT API Error {code}: {message}")
