"""Duwi IoT smarthome client module"""
from abc import ABCMeta, abstractmethod
import datetime
import hashlib
import json
import logging
import time
from typing import Any

import aiohttp

from ..const import (
    APP_VERSION,
    CLIENT_MODEL,
    CLIENT_VERSION,
    HTTP_ADDRESS,
    DuwiIotError,
    ResultCode,
)

_LOGGER = logging.getLogger(__name__)


class UpdateTokenListener(metaclass=ABCMeta):
    """Token refresh listener interface."""

    @abstractmethod
    async def on_token_refreshed(self, access_token: str, refresh_token: str, access_token_expire_time: int, refresh_token_expire_time: int):
        """Called when token is refreshed.
        
        Args:
            access_token: New access token.
            refresh_token: New refresh token.
            access_token_expire_time: Access token expiration time (milliseconds timestamp).
            refresh_token_expire_time: Refresh token expiration time (milliseconds timestamp).
        """

class DuwiClient:
    """Duwi IoT smarthome client."""

    def __init__(self, session: aiohttp.ClientSession, app_key: str, app_secret: str, update_token_listener: UpdateTokenListener|None):
        """Initialize Duwi client."""
        self.appKey = app_key
        self.appSecret = app_secret
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.access_token_expire_time: int | None = None
        self.refresh_token_expire_time: int | None = None
        self.update_token_listener: UpdateTokenListener | None = update_token_listener
        self.request_session = session

    def _get_timestamp(self):
        """Get current timestamp (milliseconds).
        
        Returns:
            Current timestamp (milliseconds).
        """
        return int(time.time() * 1000)

    def _generate_sign(self, method: str, params: dict[str, Any] | None, body: dict[str, Any] | None, timestamp: int) -> str:
        """Generate signature.
        
        Args:
            params: Request parameters.
            method: Request method.
            body: Request body (used for POST/PUT/DELETE).
            
        Returns:
            MD5 signature (lowercase).
        """

        param_str = ""

        if method == "GET":
            if params:
                # GET request: Sort parameters alphabetically and concatenate
                filtered_params = {k: v for k, v in params.items() if v not in ['', None]}
                sorted_keys = sorted(filtered_params.keys())
                param_str = "&".join([f"{k}={filtered_params[k]}" for k in sorted_keys])
        else:
            # POST/PUT/DELETE: Use request body JSON string
            param_str =  json.dumps(body, separators=(',', ':'),ensure_ascii=False) if body else "{}"

        # Signature algorithm: MD5(string_to_sign + secret + time)
        sign_str = f"{param_str}{self.appSecret}{timestamp}"
        return hashlib.md5(sign_str.encode('utf-8')).hexdigest().lower()

    def _get_headers(self, method: str, params: dict[str, Any]|None, body: dict[str, Any]|None) -> dict[str, Any]:
        """Get request headers.
        
        Args:
            method: Request method.
            body: Request body (used for POST/PUT/DELETE).
            
        Returns:
            Headers dictionary.
        """
        timestamp = self._get_timestamp()
        sign = self._generate_sign(method, params, body,timestamp)

        headers = {
            "appkey": self.appKey,
            "time": str(timestamp),
            "sign": sign,
            "appVersion": APP_VERSION,
            "clientVersion": CLIENT_VERSION,
            "clientModel": CLIENT_MODEL,
            "Content-Type": "application/json"
        }

        if self.access_token:
            headers["accessToken"] = self.access_token

        return headers

    async def _check_token_is_valid(self) -> bool:
        """Check if access_token is valid.

        Returns:
            True if access_token is valid and not expired, False otherwise.
        """
        is_token_valid = False

        if  self.access_token is None or self.refresh_token is None or self.access_token_expire_time is None or self.refresh_token_expire_time is None:
            return is_token_valid

        if self.access_token and self.access_token_expire_time:
            if self._get_timestamp() < self.access_token_expire_time:
                is_token_valid = True

        if is_token_valid:
            return True

        if not self.refresh_token:
            return False

        try:
            return await self.refresh_auth_token()
        except Exception as e:
            _LOGGER.error("Failed to check access_token: %s", e)
            return False

    async def _request(self, method: str, endpoint: str, params: dict | None = None,
                 json_data: dict | None = None) -> dict[str, Any]|None:
        """Send HTTP request.
        
        Args:
            method: Request method.
            endpoint: API endpoint.
            params: URL parameters.
            json_data: JSON request body.
            
        Returns:
            API response data.
        """
        try:
            headers = self._get_headers(method,params,json_data)

            async with self.request_session.request(url=f"{HTTP_ADDRESS}{endpoint}", method=method, headers=headers, params=params,json=json_data) as response:
                result = await response.json()
                if isinstance(result, dict):
                    return result
                return {"code": ResultCode.BACKEND_SERVICE_ERROR.value, "message": "API response format error"}
        except Exception as e:
            _LOGGER.error("HTTP request failed: %s", e)
            return {"code": ResultCode.BACKEND_SERVICE_ERROR.value, "message": "HTTP request failed"}

    async def _get(self, endpoint: str, params: dict | None = None) -> dict[str, Any]|None:
        """Send GET request.
        
        Args:
            endpoint: API endpoint.
            params: URL parameters.
            
        Returns:
            API response data.
        """
        return await self._request("GET", endpoint, params)

    async def _post(self, endpoint: str, json_data: dict | None = None) -> dict[str, Any]|None:
        """Send POST request.
        
        Args:
            endpoint: API endpoint.
            json_data: JSON request body.
            
        Returns:
            API response data.
        """
        return await self._request("POST", endpoint, json_data=json_data)

    async def _put(self, endpoint: str, json_data: dict | None = None) -> dict[str, Any]|None:
        """Send PUT request.
        
        Args:
            endpoint: API endpoint.
            json_data: JSON request body.
            
        Returns:
            API response data.
        """
        return await self._request("PUT", endpoint, json_data=json_data)

    async def _delete(self, endpoint: str, json_data: dict | None = None) -> dict[str, Any]|None:
        """Send DELETE request.
        
        Args:
            endpoint: API endpoint.
            json_data: JSON request body.
            
        Returns:
            API response data.
        """
        return await self._request("DELETE", endpoint, json_data=json_data)

    def _parse_time_to_ms(self,time_str: str) ->int:
        """Parse time string to milliseconds."""
        if not time_str:
            return 0
        try:
            dt_object = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return int(dt_object.timestamp() * 1000)
        except ValueError as e:
            _LOGGER.error("Time format error: %s", e)
            return 0

    # ==================== Functional APIs ====================

    async def close(self):
        """Close HTTP session."""
        pass

    async def check_service_status(self) -> str:
        """Check cloud service accessibility and authentication status.

        Returns:
            "ok" if service is accessible and authentication is valid.
            "network_error" if the cloud service is not reachable.
            "auth_error" if the service is reachable but authentication failed.
        """
        try:
            if not await self._check_token_is_valid():
                if self.refresh_token_expire_time is not None and self._get_timestamp() >= self.refresh_token_expire_time:
                    return "auth_error"
                if self.refresh_token is None or self.access_token is None:
                    return "auth_error"
                return "network_error"

            result = await self._get("house/infos")

            if not result:
                return "network_error"

            code = result.get("code")

            if code == ResultCode.SUCCESS.value:
                return "ok"

            if code in (
                ResultCode.ACCESS_TOKEN_ERROR.value,
                ResultCode.ACCOUNT_UNAUTHORIZED.value,
                ResultCode.REFRESH_TOKEN_ERROR.value,
                ResultCode.APP_KEY_ERROR.value,
            ):
                return "auth_error"

            return "network_error"

        except DuwiIotError:
            return "auth_error"
        except Exception:
            return "network_error"

    # ==================== Account Authorization APIs ====================

    async def refresh_auth_token(self) -> bool:
        """Refresh token."""
        _LOGGER.info("Refreshing access_token...")
        if not self.refresh_token or not self.refresh_token_expire_time:
            return False

        if self._get_timestamp() >= self.refresh_token_expire_time:
            return False

        try:
            json_data = {
                "refreshToken": self.refresh_token
            }

            result = await self._put("account/token", json_data)

            if not result:
                _LOGGER.error("Failed to refresh token: API response is empty")
                return False

            if result.get("code") in [ResultCode.ACCOUNT_UNAUTHORIZED.value,ResultCode.REFRESH_TOKEN_ERROR.value,ResultCode.APP_KEY_ERROR.value]:
                _LOGGER.error("Failed to refresh token: %s (Error code: %s)", result.get('message'), result.get('code'))

                # reset auth info
                self.access_token = None
                self.refresh_token = None
                self.access_token_expire_time = None
                self.refresh_token_expire_time = None

                if self.update_token_listener:
                    try:
                        await self.update_token_listener.on_token_refreshed(
                            self.access_token,
                            self.refresh_token,
                            self.access_token_expire_time,
                            self.refresh_token_expire_time
                        )
                    except Exception as e:
                        _LOGGER.error("Failed to refresh token: %s", e, exc_info=True)

                raise DuwiIotError(result.get("code"), result.get("message"))  # noqa: TRY301

            if result.get("code") != ResultCode.SUCCESS.value:
                error_msg = result.get("message", "Unknown error")
                _LOGGER.error("Failed to refresh token: %s (Error code: %s)", error_msg, result.get("code"))
                return False

            data = result.get("data")

            if not isinstance(data, dict):
                _LOGGER.error("Failed to refresh token: API response format error")
                return False

            new_access_token = data.get("accessToken")
            new_refresh_token = data.get("refreshToken")
            new_access_token_expire_time = self._parse_time_to_ms(data.get("accessTokenExpireTime"))
            new_refresh_token_expire_time = self._parse_time_to_ms(data.get("refreshTokenExpireTime"))

            if new_access_token is None or new_refresh_token is None or new_access_token_expire_time == 0 or new_refresh_token_expire_time == 0:
                _LOGGER.error("Failed to refresh token: API returned empty values or error format")
                return False

            self.access_token = new_access_token
            self.refresh_token = new_refresh_token
            self.access_token_expire_time = new_access_token_expire_time
            self.refresh_token_expire_time = new_refresh_token_expire_time

            if self.update_token_listener:
                try:
                    await self.update_token_listener.on_token_refreshed(
                        self.access_token,
                        self.refresh_token,
                        self.access_token_expire_time,
                        self.refresh_token_expire_time
                    )
                except Exception as e:
                    _LOGGER.error("Failed to refresh token: %s", e, exc_info=True)

            return True

        except Exception as e:
            _LOGGER.error("Failed to refresh token: %s", e, exc_info=True)
            return False

    async def login(self, phone: str, password: str) -> bool:
        """Login to get tokens.
        
        Args:
            phone: Phone number.
            password: Password.
            
        Returns:
            True if login successful, False otherwise.
        """
        try:
            json_data = {
                "phone": phone,
                "password": password
            }

            result = await self._post("account/login", json_data)

            if not result:
                _LOGGER.error("Login failed: API response is empty")
                return False

            if result.get("code") != ResultCode.SUCCESS.value:
                error_msg = result.get("message", "Unknown error")
                _LOGGER.error("Login failed: %s (Error code: %s)", error_msg, result.get("code"))
                return False

            data = result.get("data")

            if not isinstance(data, dict):
                _LOGGER.error("Login failed: API response format error")
                return False

            self.access_token = data.get("accessToken")
            self.refresh_token = data.get("refreshToken")
            self.access_token_expire_time = self._parse_time_to_ms(data.get("accessTokenExpireTime"))
            self.refresh_token_expire_time = self._parse_time_to_ms(data.get("refreshTokenExpireTime"))

            if self.update_token_listener:
                try:
                    await self.update_token_listener.on_token_refreshed(
                        self.access_token,
                        self.refresh_token,
                        self.access_token_expire_time,
                        self.refresh_token_expire_time
                    )
                except Exception as e:
                    _LOGGER.error("Login failed: %s", e, exc_info=True)

            return True

        except Exception as e:
            _LOGGER.error("Login failed: %s", e, exc_info=True)
            return False

    # ==================== House Basic Information APIs ====================

    async def get_house_list(self) -> list[dict[str, Any]]|None:
        """Get house list.
        
        Returns:
            House list, returns None on failure.
            House list example: [{
                "houseNo": "3f21841b-58e4-46cd-994f-a7ca4f614147",
                "houseName": "Test House",
                "createTime": "2021-02-27 15:23:12",
                "seq": 1
            }, ...]
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get house list")
                return None

            result = await self._get("house/infos")

            if not result:
                _LOGGER.error("Failed to get house list: API response is empty")
                return None

            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get house list: %s (Error code: %s)", result.get('message', 'Unknown error'), result.get('code'))
                return None

            data = result.get("data")

            if data is None:
                _LOGGER.warning("Failed to get house list: API response data is empty")
                return None

            houseInfos = data.get("houseInfos",[])
            if not isinstance(houseInfos, list):
                _LOGGER.warning("Failed to get  house list: API response format error")
                return None

            return houseInfos

        except Exception as e:
            _LOGGER.error("Failed to get house list: %s", e, exc_info=True)
            return None

    async def get_house_floor_and_room_list(self, house_no: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]|None:
        """Get house floors and rooms list.
        
        Args:
            house_no: House number.
            
        Returns:
            Tuple (floors list, rooms list), returns None on failure.
            Floors list example: [{
                "houseNo": "3f21841b-58e4-46cd-994f-a7ca4f614147",
                "floorNo": "7e99d414-2b5f-4d3a-900a-3c6e22d54694",
                "floorName": "Test Floor",
                "seq": 1,
                "createTime": "2021-02-27 15:23:12"
            }, ...]
            Rooms list example: [{
                "roomNo": "24d84173-eb50-4966-944f-fd618b012803",
                "roomName": "Test Room",
                "houseNo": "3f21841b-58e4-46cd-994f-a7ca4f614147",
                "floorNo": "7e99d414-2b5f-4d3a-900a-3c6e22d54694",
                "createTime": "2021-03-04 11:01:22",
                "seq": 1,
                "roomImage": "Image URL"
            }, ...]
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get floors and rooms information")
                return None

            # Call floors and rooms API
            result = await self._get("floor/floorsAndRooms", {"houseNo": house_no})

            if not result:
                _LOGGER.error("Failed to get floors and rooms information: API returned empty response")
                return None

            # Check response status code
            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get floors and rooms information: %s (Error code: %s)", result.get('message', 'Unknown error'), result.get('code'))
                return None

            # Parse returned data
            data = result.get("data")
            if data is None:
                _LOGGER.warning("Failed to get floors and rooms information: API response data is empty")
                return None

            # Extract floors list
            floors = data.get("floors", [])
            if not isinstance(floors, list):
                _LOGGER.warning("Floors data format error, expected array")
                floors = []

            # Extract rooms list
            rooms = data.get("rooms", [])
            if not isinstance(rooms, list):
                _LOGGER.warning("Rooms data format error, expected array")
                rooms = []

            # Extract default room information (optional)
            default_room = data.get("defaultRoom")
            if default_room and isinstance(default_room, dict):
                _LOGGER.debug("Got default room information: %s", default_room)

            return floors, rooms

        except Exception as e:
            _LOGGER.error("Exception getting floors and rooms list: %s", e, exc_info=True)
            return None

    async def get_house_room_list(self, house_no: str) -> list[dict[str, Any]]|None:
        """Get rooms information for a house.
        
        Args:
            house_no: House number.
            
        Returns:
            Rooms list, returns None on failure.
            Rooms list example: [{
                "roomNo": "24d84173-eb50-4966-944f-fd618b012803",
                "roomName": "Test Room",
                "houseNo": "3f21841b-58e4-46cd-994f-a7ca4f614147",
                "floorNo": "7e99d414-2b5f-4d3a-900a-3c6e22d54694",
                "createTime": "2021-03-04 11:01:22",
                "seq": 1,
                "roomImage": "Image URL"
            }, ...]
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get rooms information")
                return None

            # Call rooms information API
            result = await self._get("room/infos", {"houseNo": house_no})

            if not result:
                _LOGGER.error("Failed to get rooms information: API returned empty response")
                return None

            # Check response status code
            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get rooms information: %s (Error code: %s)", result.get('message', 'Unknown error'), result.get('code'))
                return None

            # Parse returned data
            data = result.get("data")
            if data is None:
                _LOGGER.warning("Failed to get rooms information: API response data is empty")
                return None

            # Extract rooms list
            rooms = data.get("rooms", [])
            if not isinstance(rooms, list):
                _LOGGER.warning("Rooms data format error, expected array")
                rooms = []

            return rooms

        except Exception as e:
            _LOGGER.error("Exception getting rooms list: %s", e, exc_info=True)
            return None

    async def get_house_floor_list(self, house_no: str) -> list[dict[str, Any]]|None:
        """Get floors information for a house.
        
        Args:
            house_no: House number.
            
        Returns:
            Floors list, returns None on failure.
            Floors list example: [{
                "houseNo": "3f21841b-58e4-46cd-994f-a7ca4f614147",
                "floorNo": "7e99d414-2b5f-4d3a-900a-3c6e22d54694",
                "floorName": "Test Floor",
                "seq": 1,
                "createTime": "2021-02-27 15:23:12"
            }, ...]
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get floors information")
                return None

            # Call floors and rooms API, then extract floors information
            result = await self._get("floor/infos", {"houseNo": house_no})

            if not result:
                _LOGGER.error("Failed to get floors information: API returned empty response")
                return None

            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get floors information: %s (Error code: %s)", result.get('message', 'Unknown error'), result.get('code'))
                return None

            data = result.get("data")
            if data is None:
                _LOGGER.warning("Failed to get floors information: API response data is empty")
                return None

            # Extract floors list
            floors = data.get("floors", [])
            if not isinstance(floors, list):
                _LOGGER.warning("Floors data format error, expected array")
                floors = []

            return floors

        except Exception as e:
            _LOGGER.error("Exception getting floors list: %s", e, exc_info=True)
            return None

    def find_floor_by_no(self, floors: list[dict[str, Any]], floor_no: str) -> dict[str, Any]|None:
        """Find floor by floor number.
        
        Args:
            floors: Floors list.
            floor_no: Floor number.
            
        Returns:
            Floor information, returns None if not found.
        """
        for floor in floors:
            if floor.get("floorNo") == floor_no:
                return floor
        return None

    def find_room_by_no(self, rooms: list[dict[str, Any]], room_no: str) -> dict[str, Any]|None:
        """Find room by room number.
        
        Args:
            rooms: Rooms list.
            room_no: Room number.
            
        Returns:
            Room information, returns None if not found.
        """
        for room in rooms:
            if room.get("roomNo") == room_no:
                return room
        return None

    def get_rooms_by_floor(self, rooms: list[dict[str, Any]], floor_no: str) -> list[dict[str, Any]]:
        """Get all rooms under a specific floor.
        
        Args:
            rooms: Rooms list.
            floor_no: Floor number.
            
        Returns:
            Rooms list under the floor.
        """
        return [room for room in rooms if room.get("floorNo") == floor_no]

    # ==================== Device APIs ====================

    async def get_device_info(self, device_no: str) -> dict[str, Any]|None:
        """Get single device information.
        
        Args:
            device_no: Device number.
            
        Returns:
            Device information dictionary, returns None on failure.
            Device information contains: deviceNo, deviceName, roomNo, routeNum, isUse, isOnline,
                                         isFavorite, deviceTypeNo, deviceSubTypeNo, icon, value, etc.
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get device information")
                return None

            # Call device information API
            result = await self._get("device/info", {"deviceNo": device_no})

            if not result:
                _LOGGER.error("Failed to get device information: API returned empty response (Device number: %s)", device_no)
                return None

            # Check response status code
            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get device information: %s (Error code: %s, Device number: %s)", result.get('message', 'Unknown error'), result.get('code'), device_no)
                return None

            # Parse returned data
            device_info = result.get("data")
            if device_info is None:
                _LOGGER.warning("Failed to get device information: API response data is empty (Device number: %s)", device_no)
                return None

            return device_info

        except Exception as e:
            _LOGGER.error("Exception getting device information: %s (Device number: %s)", e, device_no, exc_info=True)
            return None

    async def get_house_device_list(self, house_no: str) -> list[dict[str, Any]]|None:
        """Get devices information for a house.
        
        Args:
            house_no: House number.
            
        Returns:
            Devices list, returns None on failure.
            Each device contains: deviceNo, deviceName, terminalSequence, routeNum, deviceTypeNo,
                                  deviceSubTypeNo, houseNo, roomNo, isUse, isOnline, value, icon, etc.
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get device list")
                return None

            # Call house device information API
            result = await self._get("device/infos", {"houseNo": house_no})

            if not result:
                _LOGGER.error("Failed to get device list: API returned empty response (House number: %s)", house_no)
                return None

            # Check response status code
            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get device list: %s (Error code: %s, House number: %s)", result.get('message', 'Unknown error'), result.get('code'), house_no)
                return None

            # Parse returned data
            data = result.get("data")
            if data is None:
                _LOGGER.warning("Failed to get device list: Data empty error (House number: %s)", house_no)
                return None

            # Extract devices list
            devices = data.get("devices", [])
            if not isinstance(devices, list):
                _LOGGER.warning("Device data format error, expected array (House number: %s)", house_no)
                devices = []

            return devices

        except Exception as e:
            _LOGGER.error("Exception getting device list: %s (House number: %s)", e, house_no, exc_info=True)
            return None

    async def device_batch_command_operate(self, house_no: str, device_no: str, commands: list[dict[str, Any]]) -> bool:
        """Batch operate device.
        
        Args:
            house_no: House number.
            device_no: Device number.
            commands: Commands list.
            
        Returns:
            True if operation successful, False otherwise.
        """

        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot batch operate device")
                return False

            # Build request parameters
            params = {
                "houseNo": house_no,
                "deviceNo": device_no,
                "commands": commands
            }

            # Call batch operate device API
            result = await self._post("device/batchCommandOperate", params)

            if not result:
                _LOGGER.error(
                    "Failed to batch operate device: API returned empty response (House number: %s, Device number: %s, Commands: %s)",
                    house_no,
                    device_no,
                    commands,
                )
                return False

            # Check response status code
            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning(
                    "Failed to batch operate device: %s (Error code: %s, House number: %s, Device number: %s, Commands: %s)",
                    result.get("message", "Unknown error"),
                    result.get("code"),
                    house_no,
                    device_no,
                    commands,
                )
                return False

            return True

        except Exception as e:
            _LOGGER.error(
                "Exception batch operating device: %s (House number: %s, Device number: %s, Commands: %s)",
                e,
                house_no,
                device_no,
                commands,
                exc_info=True,
            )
            return False

    def find_device_by_no(self, devices: list[dict[str, Any]], device_no: str) -> dict[str, Any]|None:
        """Find device by device number.
        
        Args:
            devices: Devices list.
            device_no: Device number.
            
        Returns:
            Device information, returns None if not found.
        """
        for device in devices:
            if device.get("deviceNo") == device_no:
                return device
        return None

    def find_devices_by_room(self, devices: list[dict[str, Any]], room_no: str) -> list[dict[str, Any]]:
        """Get all devices under a specific room.
        
        Args:
            devices: Devices list.
            room_no: Room number.
            
        Returns:
            Devices list under the room.
        """
        return [device for device in devices if device.get("roomNo") == room_no]

    def find_online_devices(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Get all online devices.
        
        Args:
            devices: Devices list.
            
        Returns:
            Online devices list.
        """
        return [device for device in devices if device.get("isOnline", False)]

    # ==================== Device Group APIs ====================

    async def get_house_device_group_list(self, house_no: str) -> list[dict[str, Any]]|None:
        """Get device groups list for a house.
        
        Args:
            house_no: House number.
            
        Returns:
            Device groups list, returns None on failure.
            Each group contains: deviceGroupNo, deviceGroupName, houseNo, roomNo, icon,
                                 isFavorite, createTime, updateTime, executeWay, deviceGroupType, seq, etc.
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get device group list")
                return None

            # Call device group information API
            result = await self._get("deviceGroup/infos", {"houseNo": house_no})

            if not result:
                _LOGGER.error("Failed to get device group list: API returned empty response (House number: %s)", house_no)
                return None

            # Check response status code
            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get device group list: %s (Error code: %s, House number: %s)", result.get('message', 'Unknown error'), result.get('code'), house_no)
                return None

            # Parse returned data
            data = result.get("data")
            if data is None:
                _LOGGER.warning("Device group data format error, expected object (House number: %s)", house_no)  # noqa: G004
                return None

            # Extract device groups list
            device_groups = data.get("deviceGroups", [])
            if not isinstance(device_groups, list):
                _LOGGER.warning("Device group data format error, expected array (House number: %s)", house_no)
                device_groups = []


            return device_groups

        except Exception as e:
            _LOGGER.error("Exception getting device group list: %s (House number: %s)", e, house_no, exc_info=True)
            return None

    async def device_group_batch_command_operate(self, house_no: str, device_group_no: str, commands: list[dict[str, Any]]) -> bool:
        """Batch operate device group.
        
        Args:
            house_no: House number.
            device_group_no: Device group number.
            commands: Commands list.
            
        Returns:
            True if operation successful, False otherwise.
        """

        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot batch operate device group")
                return False

            # Build request parameters
            params = {
                "houseNo": house_no,
                "deviceGroupNo": device_group_no,
                "commands": commands
            }

            result = await self._post("deviceGroup/batchCommandOperate", params)

            if not result:
                _LOGGER.error(
                    "Failed to batch operate device group: API returned empty response (House number: %s, Device group number: %s, Commands: %s)",
                    house_no,
                    device_group_no,
                    commands,
                )
                return False

            # Check response status code
            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning(
                    "Failed to batch operate device group: %s (Error code: %s, House number: %s, Device group number: %s, Commands: %s)",
                    result.get("message", "Unknown error"),
                    result.get("code"),
                    house_no,
                    device_group_no,
                    commands,
                )
                return False

            return True

        except Exception as e:
            _LOGGER.error(
                "Exception batch operating device group: %s (House number: %s, Device group number: %s, Commands: %s)",
                e,
                house_no,
                device_group_no,
                commands,
                exc_info=True,
            )
            return False

    def find_device_group_by_no(self, device_groups: list[dict[str, Any]], group_no: str) -> dict[str, Any]|None:
        """Find device group by group number.
        
        Args:
            device_groups: Device groups list.
            group_no: Group number.
            
        Returns:
            Device group information, returns None if not found.
        """
        for group in device_groups:
            if group.get("deviceGroupNo") == group_no:
                return group
        return None

    def find_device_groups_by_room(self, device_groups: list[dict[str, Any]], room_no: str) -> list[dict[str, Any]]:
        """Get all device groups under a specific room.
        
        Args:
            device_groups: Device groups list.
            room_no: Room number.
            
        Returns:
            Device groups list under the room.
        """
        return [group for group in device_groups if group.get("roomNo") == room_no]


    # ==================== Scene APIs ====================

    async def get_house_scene_list(self, house_no: str) -> list[dict[str, Any]]|None:
        """Get scenes list for a house.
        
        Args:
            house_no: House number.
            
        Returns:
            Scenes list, returns None on failure.
            Each scene contains: sceneNo, sceneName, houseNo, roomNo, icon, isManualExecute,
                                 isFavorite, favoriteTime, seq, createTime, isUse, timeZone, updateTime, excuteWay, etc.
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get scene list")
                return None

            # Call scene information API
            result = await self._get("scene/infos", {"houseNo": house_no})

            if not result:
                _LOGGER.error("Failed to get scene list: API returned empty response (House number: %s)", house_no)
                return None

            # Check response status code
            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get scene list: %s (Error code: %s, House number: %s)", result.get('message', 'Unknown error'), result.get('code'), house_no)
                return None

            # Parse returned data
            data = result.get("data")
            if data is None:
                _LOGGER.warning("Scene data format error, expected object (House number: %s)", house_no)
                return None

            # Extract scenes list
            scenes = data.get("scenes", [])
            if not isinstance(scenes, list):
                _LOGGER.warning("Scene data format error, expected array (House number: %s)", house_no)
                scenes = []

            return scenes

        except Exception as e:
            _LOGGER.error("Exception getting scene list: %s (House number: %s)", e, house_no, exc_info=True)
            return None

    async def scene_execute(self, house_no: str, scene_no: str) -> bool:
        """Execute scene.
        
        Args:
            house_no: House number.
            scene_no: Scene number.
            
        Returns:
            True if execution successful, False otherwise.
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot execute scene")
                return False

            # Build request parameters
            params = {
                "houseNo": house_no,
                "sceneNo": scene_no
            }

            # Call execute scene API
            result = await self._post("scene/execute", params)

            if not result:
                _LOGGER.error("Failed to execute scene: API returned empty response (House number: %s, Scene number: %s)", house_no, scene_no)
                return False

            # Check response status code
            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to execute scene: %s (Error code: %s, House number: %s, Scene number: %s)", result.get('message', 'Unknown error'), result.get('code'), house_no, scene_no)
                return False

            return True

        except Exception as e:
            _LOGGER.error("Exception executing scene: %s (House number: %s, Scene number: %s)", e, house_no, scene_no, exc_info=True)
            return False

    def find_scene_by_no(self, scenes: list[dict[str, Any]], scene_no: str) -> dict[str, Any]|None:
        """Find scene by scene number.
        
        Args:
            scenes: Scenes list.
            scene_no: Scene number.
            
        Returns:
            Scene information, returns None if not found.
        """
        for scene in scenes:
            if scene.get("sceneNo") == scene_no:
                return scene
        return None

    def find_scenes_by_room(self, scenes: list[dict[str, Any]], room_no: str) -> list[dict[str, Any]]:
        """Get all scenes under a specific room.
        
        Args:
            scenes: Scenes list.
            room_no: Room number.
            
        Returns:
            Scenes list under the room.
        """
        return [scene for scene in scenes if scene.get("roomNo") == room_no]

    def find_manual_execute_scenes(self, scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Get all manually executable scenes.
        
        Args:
            scenes: Scenes list.
            
        Returns:
            Manually executable scenes list.
        """
        return [scene for scene in scenes if scene.get("isManualExecute", False)]

    # ==================== Controller (Terminal) APIs ====================

    async def get_house_terminal_list(self, house_no: str) -> list[dict[str, Any]]|None:
        """Get controller (terminal) list for a house.
        
        Args:
            house_no: House number.
            
        Returns:
            Terminals list, returns None on failure.
            Each terminal contains: terminalName, terminalSequence, shortCode, productModel,
                                     seq, isGateWay, productLogo, hostSequence, createTime,
                                     productShowModel, isFollowOnline, isOnline, etc.
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get terminal list")
                return None

            result = await self._get("terminal/infos", {"houseNo": house_no})

            if not result:
                _LOGGER.error("Failed to get terminal list: API returned empty response (House number: %s)", house_no)
                return None

            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get terminal list: %s (Error code: %s, House number: %s)", result.get('message', 'Unknown error'), result.get('code'), house_no)
                return None

            data = result.get("data")
            if data is None:
                _LOGGER.warning("Failed to get terminal list: API response data is empty (House number: %s)", house_no)
                return None

            terminals = data.get("terminals", [])
            if not isinstance(terminals, list):
                _LOGGER.warning("Terminal data format error, expected array (House number: %s)", house_no)
                terminals = []

            return terminals

        except Exception as e:
            _LOGGER.error("Exception getting terminal list: %s (House number: %s)", e, house_no, exc_info=True)
            return None

    async def get_terminal_info(self, terminal_sequence: str) -> dict[str, Any]|None:
        """Get single controller (terminal) information.
        
        Args:
            terminal_sequence: Terminal sequence number.
            
        Returns:
            Terminal information dictionary, returns None on failure.
            Terminal information contains: terminalName, terminalSequence, shortCode, productModel,
                                            productLogo, manufacturerLogo, mac, currentVersion, seq,
                                            isAutoUpdate, connectWay, wifi, hasUpdate, brandNo,
                                            brandName, seriesNo, seriesName, modelNo, modelName,
                                            protocolName, hostSequence, upgradeVersion,
                                            upgradeVersionType, versionType, productShowModel, etc.
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get terminal information")
                return None

            result = await self._get("terminal/info", {"terminalSequence": terminal_sequence})

            if not result:
                _LOGGER.error("Failed to get terminal information: API returned empty response (Terminal sequence: %s)", terminal_sequence)
                return None

            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get terminal information: %s (Error code: %s, Terminal sequence: %s)", result.get('message', 'Unknown error'), result.get('code'), terminal_sequence)
                return None

            terminal_info = result.get("data")
            if terminal_info is None:
                _LOGGER.warning("Failed to get terminal information: API response data is empty (Terminal sequence: %s)", terminal_sequence)
                return None

            return terminal_info

        except Exception as e:
            _LOGGER.error("Exception getting terminal information: %s (Terminal sequence: %s)", e, terminal_sequence, exc_info=True)
            return None

    async def get_terminal_device_list(self, terminal_sequence: str) -> list[dict[str, Any]]|None:
        """Get devices list under a specific controller (terminal).
        
        Args:
            terminal_sequence: Terminal sequence number.
            
        Returns:
            Devices list under the terminal, returns None on failure.
            Each device contains: deviceNo, deviceName, roomNo, routeNum, isUse, isOnline,
                                   isFavorite, favoriteTime, createTime, deviceTypeNo,
                                   deviceSubTypeNo, value, keyBindingQuantity,
                                   keyMappingQuantity, icon, etc.
        """
        try:
            if not await self._check_token_is_valid():
                _LOGGER.warning("Invalid token, cannot get terminal device list")
                return None

            result = await self._get("device/detailInfos", {"terminalSequence": terminal_sequence})

            if not result:
                _LOGGER.error("Failed to get terminal device list: API returned empty response (Terminal sequence: %s)", terminal_sequence)
                return None

            if result.get("code") != ResultCode.SUCCESS.value:
                if result.get("code") == ResultCode.ACCESS_TOKEN_ERROR.value:
                    await self.refresh_auth_token()
                _LOGGER.warning("Failed to get terminal device list: %s (Error code: %s, Terminal sequence: %s)", result.get('message', 'Unknown error'), result.get('code'), terminal_sequence)
                return None

            data = result.get("data")
            if data is None:
                _LOGGER.warning("Failed to get terminal device list: API response data is empty (Terminal sequence: %s)", terminal_sequence)
                return None

            devices = data.get("devices", [])
            if not isinstance(devices, list):
                _LOGGER.warning("Terminal device data format error, expected array (Terminal sequence: %s)", terminal_sequence)
                devices = []

            return devices

        except Exception as e:
            _LOGGER.error("Exception getting terminal device list: %s (Terminal sequence: %s)", e, terminal_sequence, exc_info=True)
            return None

    def find_terminal_by_sequence(self, terminals: list[dict[str, Any]], terminal_sequence: str) -> dict[str, Any]|None:
        """Find terminal by terminal sequence number.
        
        Args:
            terminals: Terminals list.
            terminal_sequence: Terminal sequence number.
            
        Returns:
            Terminal information, returns None if not found.
        """
        for terminal in terminals:
            if terminal.get("terminalSequence") == terminal_sequence:
                return terminal
        return None

    def find_terminals_by_host(self, terminals: list[dict[str, Any]], host_sequence: str) -> list[dict[str, Any]]:
        """Get all terminals under a specific host.
        
        Args:
            terminals: Terminals list.
            host_sequence: Host sequence number.
            
        Returns:
            Terminals list under the host.
        """
        return [terminal for terminal in terminals if terminal.get("hostSequence") == host_sequence]

    def find_gateway_terminals(self, terminals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Get all gateway terminals.
        
        Args:
            terminals: Terminals list.
            
        Returns:
            Gateway terminals list.
        """
        return [terminal for terminal in terminals if terminal.get("isGateWay") == 1]

    def find_online_terminals(self, terminals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Get all online terminals.
        
        Args:
            terminals: Terminals list.
            
        Returns:
            Online terminals list.
        """
        return [terminal for terminal in terminals if terminal.get("isOnline", False)]
