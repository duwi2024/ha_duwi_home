"""Duwi RPS (Real-time Push Service) WebSocket Client."""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

import aiohttp

from ..const import CLIENT_MODEL, WEBSOCKET_ADDRESS

_LOGGER = logging.getLogger(__name__)

KEEPALIVE_INTERVAL = 20
SEPARATOR = "&excision&"


class DuwiRps:
    """WebSocket client for Duwi RPS."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        app_key: str,
        app_secret: str,
        access_token: str,
        house_no: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._app_key = app_key
        self._app_secret = app_secret
        self._access_token = access_token
        self._house_no = house_no
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None

        # listeners
        self._device_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._device_group_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._terminal_listeners: list[Callable[[str, bool], None]] = []

        self._buffer = ""
        self._connected = False
        self._connection_listeners: list[Callable[[bool], None]] = []

    @property
    def is_connected(self) -> bool:
        """Return True if WebSocket is connected."""
        return self._connected

    def add_connection_listener(
        self,
        callback: Callable[[bool], None],
    ) -> None:
        """Add a listener for connection state changes."""
        self._connection_listeners.append(callback)

    def _notify_connection_state(self, connected: bool) -> None:
        """Notify listeners of connection state change."""
        for callback in self._connection_listeners:
            try:
                callback(connected)
            except Exception as err:
                _LOGGER.error("Connection listener error: %s", err)

    def add_device_listener(
        self,
        callback: Callable[[str, dict[str, Any]], None],
    ) -> None:
        """Add a listener for device updates."""
        self._device_listeners.append(callback)

    def add_device_group_listener(
        self,
        callback: Callable[[str, dict[str, Any]], None],
    ) -> None:
        """Add a listener for device group updates."""
        self._device_group_listeners.append(callback)

    def add_terminal_listener(
        self,
        callback: Callable[[str, bool], None],
    ) -> None:
        """Add a listener for terminal updates."""
        self._terminal_listeners.append(callback)

    async def start(self) -> None:
        """Start the WebSocket connection."""
        _LOGGER.debug("Starting rps service.")
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        _LOGGER.info("Stopping rps service.")

        # 1. Cancel background tasks first
        tasks_to_cancel = []
        if self._keepalive_task:
            tasks_to_cancel.append(self._keepalive_task)
        if self._task:
            tasks_to_cancel.append(self._task)

        for task in tasks_to_cancel:
            task.cancel()

        # Wait for tasks to complete, ignore all exceptions
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

        self._keepalive_task = None
        self._task = None

        # 2. Close WebSocket (context manager in _run will also handle this)
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception as err:
                _LOGGER.debug("WebSocket already closed or closing: %s", err)
            finally:
                self._ws = None

        # 3. Update connection state
        was_connected = self._connected
        self._connected = False
        if was_connected:
            self._notify_connection_state(False)

    async def _run(self) -> None:
        """Main connection loop with auto-reconnect."""
        while True:
            _LOGGER.debug("Connecting to Duwi RPS: %s", WEBSOCKET_ADDRESS)
            try:
                async with self._session.ws_connect(
                    WEBSOCKET_ADDRESS, heartbeat=KEEPALIVE_INTERVAL
                ) as ws:
                    self._ws = ws
                    _LOGGER.info("Connected to Duwi RPS")

                    if not await self._handshake(ws):
                        _LOGGER.error("Handshake failed, reconnecting in 10s...")
                        await asyncio.sleep(10)
                        continue

                    if not await self._bind(ws):
                        _LOGGER.error("Bind failed, reconnecting in 10s...")
                        await asyncio.sleep(10)
                        continue

                    self._connected = True
                    self._notify_connection_state(True)

                    self._keepalive_task = asyncio.create_task(self._keepalive_loop(ws))

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle_data(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            self._handle_data(msg.data.decode("utf-8"))
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            _LOGGER.error("WebSocket error: %s", ws.exception())
                            break
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                            break

            except asyncio.CancelledError:
                _LOGGER.debug("RPS WebSocket cancelled")
                break
            except aiohttp.ServerDisconnectedError:
                _LOGGER.warning("RPS server disconnected, reconnecting in 10s...")
            except aiohttp.ClientConnectionError as err:
                _LOGGER.error("RPS connection error: %s, reconnecting in 10s...", err)
            except Exception as err:
                _LOGGER.error("RPS unexpected error: %s, reconnecting in 10s...", err)
            finally:
                was_connected = self._connected
                self._connected = False
                if was_connected:
                    self._notify_connection_state(False)
                if self._keepalive_task:
                    self._keepalive_task.cancel()
                    try:
                        await self._keepalive_task
                    except asyncio.CancelledError:
                        pass
                    self._keepalive_task = None
                self._ws = None

            await asyncio.sleep(10)

    async def _handshake(self, ws: aiohttp.ClientWebSocketResponse) -> bool:
        """Perform handshake (LINK)."""
        client_id = CLIENT_MODEL+"_"+str(uuid.uuid4())
        timestamp = int(time.time() * 1000)

        msg_to_sign = f"{client_id}{self._app_key}{timestamp}"
        signature = self._generate_signature(msg_to_sign, self._app_secret)

        data = {
            "clientID": client_id,
            "appKey": self._app_key,
            "time": str(timestamp),
            "sign": signature,
        }

        await ws.send_str(f"LINK|{json.dumps(data)}")

        msg = await ws.receive()
        if msg.type != aiohttp.WSMsgType.TEXT:
            _LOGGER.error("Handshake(LINK): unexpected message type %s", msg.type)
            return False

        response = msg.data
        self._handle_data(response)

        try:
            parts = response.split(SEPARATOR)
            for part in parts:
                if not part:
                    continue
                payload = json.loads(part)
                if payload.get("namespace") == "Duwi.RPS.Link":
                    if payload.get("result", {}).get("code") == "success":
                        _LOGGER.info("RPS handshake (LINK) successful")
                        return True
            return False
        except Exception as err:
            _LOGGER.error("Failed to parse handshake (LINK) response: %s", err)
            return False

    async def _bind(self, ws: aiohttp.ClientWebSocketResponse) -> bool:
        """Send bind request (BIND)."""
        data = {
            "accessToken": self._access_token,
            "houseNo": self._house_no,
        }

        await ws.send_str(f"BIND|{json.dumps(data)}")

        msg = await ws.receive()
        if msg.type != aiohttp.WSMsgType.TEXT:
            _LOGGER.error("Bind (BIND): unexpected message type %s", msg.type)
            return False

        response = msg.data
        self._handle_data(response)

        try:
            parts = response.split(SEPARATOR)
            for part in parts:
                if not part:
                    continue
                payload = json.loads(part)
                if payload.get("namespace") == "Duwi.RPS.Bind":
                    if payload.get("result", {}).get("code") == "success":
                        _LOGGER.info("RPS bind (BIND) successful")
                        return True
            return False
        except Exception as err:
            _LOGGER.error("Failed to parse bind (BIND) response: %s", err)
            return False

    def _generate_signature(self, content: str, key: str) -> str:
        """Generate HMAC-SHA256 signature."""
        hmac_obj = hmac.new(
            key.encode("utf-8"), content.encode("utf-8"), hashlib.sha256
        )
        return base64.b64encode(hmac_obj.digest()).decode("utf-8")

    async def _keepalive_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Send keepalive every 20s."""
        while True:
            try:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if ws.closed:
                    break
                await ws.send_str("KEEPALIVE")
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Keepalive error: %s", err)
                break

    def _handle_data(self, data: str) -> None:
        """Handle raw incoming data, buffer and split by separator."""
        _LOGGER.debug("Raw data: %s", data)
        if not data:
            return

        if data == "KEEPALIVE":
            _LOGGER.debug("KEEPALIVE received")
            return

        self._dispatch(data)

    def _dispatch(self, raw: str) -> None:
        """Parse JSON and dispatch to listeners."""
        try:
            payload = json.loads(raw.removesuffix("&excision&"))
        except json.JSONDecodeError:
            _LOGGER.warning("Failed to decode JSON: %s", raw)
            return

        namespace = payload.get("namespace")
        result = payload.get("result", {})

        if not isinstance(result, dict):
            _LOGGER.warning("Invalid result format in payload: %s", type(result))
            return

        msg = result.get("msg")

        if namespace == "Duwi.RPS.DeviceValue" and isinstance(msg, dict):
            device_no = msg.get("deviceNo")
            _LOGGER.debug("Device update: %s -> %s", device_no, msg)
            for callback in self._device_listeners:
                try:
                    callback(device_no, msg)
                except Exception as err:
                    _LOGGER.error("Listener error: %s", err)
        elif namespace == "Duwi.RPS.DeviceGroupValue" and isinstance(msg, dict):
            device_group_no = msg.get("deviceGroupNo")
            _LOGGER.debug("Device group update: %s -> %s", device_group_no, msg)
            for callback in self._device_group_listeners:
                try:
                    callback(device_group_no, msg)
                except Exception as err:
                    _LOGGER.error("Listener error: %s", err)
        elif namespace == "Duwi.RPS.TerminalOnline" and isinstance(msg, dict):
            sequence = msg.get("sequence")
            online = msg.get("online")
            _LOGGER.info("Terminal online status: %s -> %s", sequence, online)
            for callback in self._terminal_listeners:
                try:
                    callback(sequence, online)
                except Exception as err:
                    _LOGGER.error("Listener error: %s", err)
        elif namespace in ("Duwi.RPS.Link", "Duwi.RPS.Bind"):
            pass
        else:
            _LOGGER.warning("Unhandled namespace: %s, message: %s", namespace, msg)