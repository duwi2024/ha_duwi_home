from abc import ABCMeta, abstractmethod
import asyncio
import json
import time
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from ..const.const import _LOGGER, Code
from ..util.sign import md5_encrypt


class SharingTokenListener(metaclass=ABCMeta):
    @abstractmethod
    def update_token(self, is_refresh: bool, token_info: dict[str, Any] = None):
        """Update token.
        """

    @abstractmethod
    async def error_notification(self):
        """Error notification.
        """

class CustomerApi:
    def __init__(
            self,
            address: str,
            ws_address: str,
            app_key: str,
            app_secret: str,
            app_version: str,
            client_version: str,
            client_model: str,
            house_no: str = "",
            house_name: str = "",
            listener: SharingTokenListener = None,
            access_token: str = "",
            refresh_token: str = "",
            phone:str="",
            pasword:str ="",
    ):
        # self.token_info = token_info
        self.address = address
        self.ws_address = ws_address
        self.house_no = house_no
        self.house_name = house_name
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.app_version = app_version
        self.client_version = client_version
        self.client_model = client_model
        self.token_listener = listener
        self.timeout = ClientTimeout(total=15)
        self.access_token_expire_time = None
        self.phone = phone
        self.password = pasword
    def __generate_headers(self, method: str, body: dict[str, Any] | str) -> dict[str, str]:
        if body is None:
            body = {}

        if method == "GET":
            sorted_params = sorted(body.items())  # 按字母顺序排序
            body_string = "&".join(f"{k}={v}" for k, v in sorted_params)  # 拼接成字符串
            body_string = body_string.replace(" ", "").replace("\t", "").replace("\n", "").replace("\r", "")
        else:
            body_string = json.dumps(body, separators=(',', ':'))

        timestamp = int(time.time() * 1000)
        sign = md5_encrypt(body_string + self.app_secret + str(timestamp))
        headers = {
            'Content-Type': 'application/json',
            'accessToken': self.access_token,
            'appkey': self.app_key,
            'time': str(timestamp),
            'sign': sign,
            'appVersion': self.app_version,
            'clientVersion': self.client_version,
            'clientModel': self.client_model,
        }
        return headers

    async def __request(
            self,
            method: str,
            path: str,
            params: dict[str, Any] | None = None,
            body: dict[str, Any] = None,
    ) -> dict[str, Any] | None:
        headers = self.__generate_headers(method, params if method == "GET" else body)
        session = aiohttp.ClientSession(timeout=self.timeout)
        try:
            async with session.request(method=method, url=self.address + path, headers=headers, params=params,
                                       json=body) as response:
                response_data = await response.json()
                if isinstance(response_data, dict):
                    return response_data
                _LOGGER.error("Unexpected response format: not a dictionary")
                return {"code": Code.SYS_ERROR.value}
        except aiohttp.ClientError as e:
            _LOGGER.error("Connection error: %s", e)
            return {"code": Code.NETWORK_CONFIGURATION_NOT_SUPPORTED.value}
        except TimeoutError as e:
            _LOGGER.error("Request timeout: %s", e)
            return {"code": Code.OPERATION_TIMEOUT.value}
        except asyncio.exceptions.CancelledError:
            _LOGGER.error("Request canceled")
            return {"code": Code.OPERATION_TIMEOUT.value}
        finally:
            await session.close()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.__request("GET", path, params, None)

    async def post(self, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[
        str, Any]:
        return await self.__request("POST", path, params, body)

    async def put(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.__request("PUT", path, None, body)

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.__request("DELETE", path, params, None)

    async def update_token(self,accessToken:str,refreshToken:str,accessTokenExpireTime:str) ->None:
        self.access_token = accessToken
        self.refresh_token = refreshToken
        self.access_token_expire_time = accessTokenExpireTime



