import asyncio
import json
import time
import traceback
from typing import Callable

import websockets

from ..base.customer_api import CustomerApi
from ..const.const import _LOGGER, Code
from ..api.refresh_token import AuthTokenRefresherClient
from ..util.sign import md5_encrypt, sha256_base64


class DeviceSynchronizationWS:
    def __init__(self, client: CustomerApi):
        self.is_connected = False
        self._client = client
        self._is_over = False
        self._connection = None
        self.message_listeners = set()

    async def connect(self):
        _LOGGER.info('connect ws server...')
        self._connection = await websockets.connect(
            self._client.ws_address,
            ping_interval=20,  # Disable automatic pings
            ping_timeout=120,  # Disable automatic ping timeout
        )

    async def send(self, message):
        if self._connection:
            await self._connection.send(message)

    async def disconnect(self):
        if self._connection:
            _LOGGER.info('disconnect ws server...')
            self._is_over = True
            self.is_connected = False
            await self._connection.close()

    async def reconnect(self):
        if self._is_over:
            return
        self.is_connected = False
        _LOGGER.info('Reconnecting WS server...')
        backoff_time = 1  # 设定初始等待时间
        max_backoff_time = 60  # 最大等待时间
        while not self._is_over:
            try:
                await self.connect()
                await self.link()
                await self.bind()
                self.is_connected = True
                _LOGGER.info('Reconnected successfully.')
                break  # 成功后退出循环
            except Exception as e:
                _LOGGER.error(f'Failed to reconnect: {e}, will retry in {backoff_time}s...')
                await asyncio.sleep(backoff_time)
                backoff_time = min(backoff_time * 2, max_backoff_time)  # 指数退避

    async def listen(self):
        while not self._is_over:
            try:
                await self.process_messages()
            except websockets.exceptions.ConnectionClosed:
                _LOGGER.info('listen ws connection closed...')
                await asyncio.sleep(10)
            except Exception as e:
                await asyncio.sleep(10)
                # _LOGGER.error(f'An error occurred during listen: {e}')

    async def link(self):
        _LOGGER.info('link...')
        timestamp = str(int(time.time() * 1000))
        client_id = md5_encrypt(timestamp)

        data = {
            "clientID": client_id,
            "appKey": self._client.app_key,
            "time": str(timestamp),
            "sign": sha256_base64(client_id, self._client.app_key, timestamp, self._client.app_secret),
        }
        json_string = json.dumps(data)
        await self.send(
            'LINK|' + json_string
        )

    async def bind(self):
        _LOGGER.info('bind...')
        data = {
            "accessToken": self._client.access_token,
            "houseNo": self._client.house_no,
        }
        json_string = json.dumps(data)
        await self.send(
            'BIND|' + json_string
        )

    async def keep_alive(self):
        while not self._is_over:
            try:
                _LOGGER.info("keep alive...")
                await asyncio.sleep(20)
                await self.send('KEEPALIVE')
            except websockets.exceptions.ConnectionClosedError:
                _LOGGER.info('keep_alive ws,connection closed, trying to reconnect...')
                await self.reconnect()
            except Exception as e:
                _LOGGER.error(f'An error occurred during keep_alive: {e}')

    async def process_messages(self):
        async for message in self._connection:
            try:
                if message == "KEEPALIVE":
                    continue
                message = str.replace(message, "&excision&", "")
                try:
                    message_data = json.loads(message)
                except json.JSONDecodeError:
                    _LOGGER.error("Failed to parse JSON message: %s", message)
                    return
                namespace = message_data.get("namespace")
                if namespace == "Duwi.RPS.Link":
                    if message_data.get("result", {}).get("code") != "success":
                        _LOGGER.error(f"error message detail: \n{message}")
                        self._is_over = True
                        return
                for listener in self.message_listeners:
                    listener(message)

            except Exception as e:
                _LOGGER.error(f"error message detail: \n{traceback.format_exc()}")

    async def add_message_listener(self, listener: Callable[[str], None]):
        """Add ws message listener."""
        self.message_listeners.add(listener)

    async def remove_message_listener(self, listener: Callable[[str], None]):
        """Remove ws message listener."""
        self.message_listeners.discard(listener)
