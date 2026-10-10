"""Duwi IoT Management."""
import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import dispatcher_send

from .db.duwi_database import DuwiDatabase
from .lan.duwi_lan import DuwiLanClient
from .rps.duwi_rps import DuwiRps
from .smarthome.duwi_client import DuwiClient, UpdateTokenListener
from ..const import (
    SIGNAL_DEVICE_UPDATE,
    SIGNAL_DEVICE_GROUP_UPDATE,
    DOMAIN
)

from homeassistant.exceptions import ConfigEntryAuthFailed

_LOGGER = logging.getLogger(__name__)

ONLINE_CHECK_INTERVAL = 30
DUWI_HOST_MODEL = ["DXH","DXH-HMCUH743","DXH-Plus"]

class DuwiManager:
    """Duwi IoT Management."""

    def __init__(
        self,
        appKey: str,
        secretKey: str,
        accessToken: str,
        accessToken_expire_time: int,
        refreshToken: str,
        refreshToken_expire_time: int,
        house_no: str,
        house_lan_secret_key: str,
        hass: HomeAssistant,
        entry: ConfigEntry,
        duwi_token_refresh_listener: UpdateTokenListener | None,
    ) -> None:
        """Initialize the DuwiManage."""
        self._app_key = appKey
        self._secret_key = secretKey
        self._access_token = accessToken
        self._refresh_token = refreshToken
        self._access_token_expire_time = accessToken_expire_time
        self._refresh_token_expire_time = refreshToken_expire_time

        self._house_no = house_no
        self._house_lan_secret_key = house_lan_secret_key

        self.duwi_db: DuwiDatabase | None = None
        self.duwi_client: DuwiClient | None = None
        self.duwi_rps: DuwiRps | None = None
        self.duwi_lan: DuwiLanClient | None = None

        self._online = False
        self._online_check_task: asyncio.Task | None = None
        self._state = False

        self._hass = hass
        self._entry = entry
        self._duwi_token_refresh_listener = duwi_token_refresh_listener

        self._failover_lock = asyncio.Lock()
        self._failover_tasks: set[asyncio.Task] = set()
        self._delayed_lan_start_task: asyncio.Task | None = None

    @property
    def is_online(self) -> bool:
        """Return True if cloud connection is available."""
        return self._online

    async def start(self) -> bool:
        """Start the DuwiManage."""
        try:
            # check house_no
            if not self._house_no:
                return False

            # Close existing database connection if re-starting
            if self.duwi_db is not None:
                await self.duwi_db.close()
                self.duwi_db = None

            # Initialize database
            _LOGGER.info("DuwiManage: Initialize database")
            self.duwi_db = DuwiDatabase(self._hass.config.path("duwi_home"))
            await self.duwi_db.connect()

            # Initialize smarthome client
            _LOGGER.info("DuwiManage: Initialize smarthome client")
            self.duwi_client = DuwiClient(
                async_get_clientsession(self._hass),
                self._app_key,
                self._secret_key,
                self._duwi_token_refresh_listener,
            )
            self.duwi_client.access_token = self._access_token
            self.duwi_client.access_token_expire_time = self._access_token_expire_time
            self.duwi_client.refresh_token = self._refresh_token
            self.duwi_client.refresh_token_expire_time = self._refresh_token_expire_time

            # Check cloud service accessibility
            service_status = await self.duwi_client.check_service_status()

            if service_status == "auth_error":
                _LOGGER.error("DuwiManage: Authentication failed, please re-authenticate")
                return False

            cloud_accessible = service_status == "ok"
            if not cloud_accessible:
                _LOGGER.warning("DuwiManage: Cloud service not accessible, entering LAN mode")
                self._online = False
            else:
                _LOGGER.info("DuwiManage: Cloud service accessible")
                self._online = True

            # Initialize HA data storage
            self._hass.data[DOMAIN].setdefault(self._entry.entry_id, {})

            # Initialize RPS and Lan
            await self._init_rps()
            await self._init_lan()

            house_info = {}
            floors = []
            rooms = []
            devices = []
            device_groups = []
            scenes = []
            terminals = []
            force_sign = cloud_accessible and self._hass.state.value == CoreState.running
            if not force_sign:
                _LOGGER.info("Loading house info from database")
                house_full_info = await self.duwi_db.get_house_full_info(self._house_no)
                if house_full_info:
                    house_info["house_no"] = house_full_info["house_no"]
                    house_info["house_name"] = house_full_info["house_name"]
                    house_info["address"] = house_full_info["address"]
                    house_info["location"] = house_full_info["location"]
                    floors = house_full_info["floors"]
                    rooms = house_full_info["rooms"]
                    devices = house_full_info["devices"]
                    device_groups = house_full_info["device_groups"]
                    scenes = house_full_info["scenes"]
                    terminals = house_full_info["terminals"]

                # If the database is empty (first-time setup) and cloud is
                # accessible, fall through to the force-sync path below so
                # devices / terminals / etc. are fetched from the cloud API.
                if cloud_accessible and not devices and not terminals:
                    _LOGGER.info("Database empty, falling through to force sync")
                    force_sign = True

            if not force_sign:
                if cloud_accessible:
                    # update current date
                    if devices:
                        try:
                            api_devices = await self.duwi_client.get_house_device_list(self._house_no)
                            if api_devices:
                                device_map = {dev["deviceNo"]: dev for dev in api_devices}

                                for i, device in enumerate(devices):
                                    api_device = device_map.get(device["device_no"])
                                    if api_device:
                                        devices[i] = await self.duwi_db.insert_device(api_device)
                            else:
                                for item in devices:
                                    item["is_online"] = 0
                        except Exception as e:
                            _LOGGER.error("Failed to sync devices for house %s: %s", self._house_no, e)

                    if terminals:
                        try:
                            api_terminals = await self.duwi_client.get_house_terminal_list(self._house_no)
                            if api_terminals:
                                terminal_map = {term["terminalSequence"]: term for term in api_terminals}

                                for i, terminal in enumerate(terminals):
                                    api_terminal = terminal_map.get(terminal["terminal_sequence"])
                                    if api_terminal:
                                        terminals[i] = await self.duwi_db.insert_terminal(self._house_no,api_terminal)
                            else:
                                for item in terminals:
                                    item["is_online"] = 0
                        except Exception as e:
                            _LOGGER.error("Failed to sync terminals for house %s: %s", self._house_no, e)

                    if device_groups:
                        try:
                            api_groups = await self.duwi_client.get_house_device_group_list(self._house_no)
                            if api_groups:
                                group_map = {grp["deviceGroupNo"]: grp for grp in api_groups}

                                for i, group in enumerate(device_groups):
                                    api_group = group_map.get(group["device_group_no"])
                                    if api_group:
                                        device_groups[i] = await self.duwi_db.insert_device_group(api_group)
                        except Exception as e:
                            _LOGGER.error("Failed to sync device groups for house %s: %s", self._house_no, e)

                    if scenes:
                        try:
                            api_scenes = await self.duwi_client.get_house_scene_list(self._house_no)
                            if api_scenes:
                                scene_map = {s["sceneNo"]: s for s in api_scenes}
                                for i, scene in enumerate(scenes):
                                    api_scene = scene_map.get(scene["scene_no"])
                                    if api_scene:
                                        scenes[i] = await self.duwi_db.insert_scene(api_scene)
                        except Exception as e:
                            _LOGGER.error("Failed to sync scenes for house %s: %s", self._house_no, e)
                else:
                    for item in devices:
                        item["is_online"] = 0

                    for item in terminals:
                        item["is_online"] = 0
            else:
                _LOGGER.info("Force syncing all info for house %s", self._house_no)

                api_house_info_list = await self.duwi_client.get_house_list()

                if api_house_info_list is None:
                    _LOGGER.error("Failed to get house list")
                    return False

                # delete old data
                _LOGGER.info("Deleting all house info for house %s", self._house_no)

                await self.duwi_db.delete_all_by_house_no(self._house_no)

                house_info_temp = None
                if api_house_info_list:
                    house_info_temp = next(
                        (info for info in api_house_info_list if info.get("houseNo") == self._house_no),
                        None,
                    )
                if house_info_temp:
                    house_info = await self.duwi_db.insert_house(house_info_temp)

                    api_floors = await self.duwi_client.get_house_floor_list(self._house_no)
                    if api_floors:
                        floors = [await self.duwi_db.insert_floor(floor) for floor in api_floors]

                    api_rooms = await self.duwi_client.get_house_room_list(self._house_no)
                    if api_rooms:
                        rooms = [await self.duwi_db.insert_room(room) for room in api_rooms]

                    api_devices = await self.duwi_client.get_house_device_list(self._house_no)
                    if api_devices:
                        devices = [await self.duwi_db.insert_device(device) for device in api_devices]

                    api_device_groups = await self.duwi_client.get_house_device_group_list(self._house_no)
                    if api_device_groups:
                        device_groups = [await self.duwi_db.insert_device_group(group) for group in api_device_groups]

                    api_scenes = await self.duwi_client.get_house_scene_list(self._house_no)
                    if api_scenes:
                        scenes = [await self.duwi_db.insert_scene(scene) for scene in api_scenes]

                    api_terminals = await self.duwi_client.get_house_terminal_list(self._house_no)
                    if api_terminals:
                        terminals = [await self.duwi_db.insert_terminal(self._house_no,terminal) for terminal in api_terminals]
                else:
                    return False

            self._hass.data[DOMAIN][self._entry.entry_id]["house_info"] = house_info
            self._hass.data[DOMAIN][self._entry.entry_id]["floors"] = floors
            self._hass.data[DOMAIN][self._entry.entry_id]["rooms"] = rooms
            self._hass.data[DOMAIN][self._entry.entry_id]["devices"] = devices
            self._hass.data[DOMAIN][self._entry.entry_id]["device_groups"] = device_groups
            self._hass.data[DOMAIN][self._entry.entry_id]["scenes"] = scenes
            self._hass.data[DOMAIN][self._entry.entry_id]["terminals"] = terminals

            # update lan host list
            lan_hosts: list[str] = [
                str(terminal["terminal_sequence"])
                for terminal in terminals
                if str(terminal["product_model"]) in DUWI_HOST_MODEL
            ]
            self.duwi_lan.update_hosts_list(lan_hosts)


            # Start RPS
            await self._start_rps()

            if cloud_accessible:
                # Delayed LAN start: give RPS a chance to connect first
                self._delayed_lan_start_task = self._hass.async_create_background_task(
                    self._delayed_lan_start(), "duwi_home delayed lan start"
                )
            else:
                # Start LAN immediately when cloud is not accessible
                async with self._failover_lock:
                    await self._start_lan()

            # Check online status and start periodic check
            self._online_check_task = self._hass.async_create_background_task(self._online_check_loop(), "duwi_home online check loop")

            self._state = True

            return True

        except Exception as err:
            _LOGGER.error("Error occurred while starting DuwiManage: %s", err, exc_info=True)
            return False

    async def stop(self) -> None:
        """Stop the DuwiManage."""
        _LOGGER.debug("DuwiManage: Stop")
        try:
            # Stop online check task
            if self._online_check_task:
                self._online_check_task.cancel()
                try:
                    await self._online_check_task
                except asyncio.CancelledError:
                    pass
                self._online_check_task = None

            # Stop delayed LAN start task
            if self._delayed_lan_start_task:
                self._delayed_lan_start_task.cancel()
                try:
                    await self._delayed_lan_start_task
                except asyncio.CancelledError:
                    pass
                self._delayed_lan_start_task = None

            _LOGGER.debug("DuwiManage: Stop RPS")
            if self.duwi_rps:
                await self.duwi_rps.stop()

            _LOGGER.debug("DuwiManage: Stop LAN client")
            if self.duwi_lan:
                await self.duwi_lan.stop()

            _LOGGER.debug("DuwiManage: Stop smarthome client")
            if self.duwi_client:
                await self.duwi_client.close()

            _LOGGER.debug("DuwiManage: Stop database")
            if self.duwi_db:
                await self.duwi_db.close()

            self._state = False
        except Exception as err:
            _LOGGER.error("Error occurred while stopping DuwiManage: %s", err, exc_info=True)

    async def _check_online_status_and_service(self,connected:bool|None = None) -> None:
        """Check RPS connectivity and update online state."""
        async with self._failover_lock:
            if not self.duwi_rps:
                self._online = False
                return

            if connected is None:
                connected = self.duwi_rps.is_connected

            was_online = self._online
            self._online = connected

            if self._online and not was_online:
                _LOGGER.warning("RPS connection restored, switching to RPS mode")
                if self.duwi_lan:
                    await self.duwi_lan.stop()

                # Verify token validity, trigger reauth if both tokens have expired
                if self.duwi_client:
                    service_status = await self.duwi_client.check_service_status()
                    if service_status == "auth_error":
                        _LOGGER.error("DuwiManage: Authentication failed, please re-authenticate")
                        raise ConfigEntryAuthFailed(
                        "Token expired and could not be refreshed, please re-authenticate")

                # Refresh device status from cloud, update cache and push to HA
                await self._refresh_device_status_after_rps_online()

            elif not self._online and was_online:
                _LOGGER.warning("RPS connection lost, switching to LAN mode")

                await self._start_lan()

    async def _refresh_device_status_after_rps_online(self) -> None:
        """Refresh device real-time status from cloud and push to HA.

        The device list is taken from the database (not the cloud), so devices
        are never added or removed here. Only is_online and value (real-time
        state) are fetched from the cloud and updated in the DB cache + HA.
        """
        entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
        devices = entry_data.get("devices")
        if not devices:
            return

        _LOGGER.info("DuwiManage: Refreshing device status after RPS reconnection")

        # Fetch real-time status from cloud (single API call for efficiency),
        # but only use it to update devices that already exist in the DB.
        status_map: dict[str, dict[str, Any]] = {}
        if self.duwi_client:
            try:
                api_devices = await self.duwi_client.get_house_device_list(self._house_no)
                if api_devices:
                    status_map = {dev["deviceNo"]: dev for dev in api_devices}
            except Exception as e:
                _LOGGER.error("DuwiManage: Failed to fetch device status from cloud: %s", e, exc_info=True)

        # Update each DB device's real-time status only
        for device in devices:
            device_no = device.get("device_no")
            if not device_no:
                continue

            api_device = status_map.get(device_no)
            if api_device:
                is_online = 1 if api_device.get("isOnline") else 0
                value = api_device.get("value") or {}
                device["is_online"] = is_online
                device["value"] = value
                if self.duwi_db:
                    await self.duwi_db.update_device_status(device_no, is_online, value)
            else:
                device["is_online"] = 0

        # Refresh terminal online status (in-memory cache only)
        terminals = entry_data.get("terminals")
        if terminals and self.duwi_client:
            try:
                api_terminals = await self.duwi_client.get_house_terminal_list(self._house_no)
                if api_terminals:
                    terminal_map = {term["terminalSequence"]: term for term in api_terminals}
                    for terminal in terminals:
                        api_terminal = terminal_map.get(terminal.get("terminal_sequence"))
                        if api_terminal:
                            terminal["is_online"] = 1 if api_terminal.get("isOnline") else 0
                        else:
                            terminal["is_online"] = 0
            except Exception as e:
                _LOGGER.error("DuwiManage: Failed to refresh terminal status: %s", e, exc_info=True)

        # Push current device status to HA entities
        for device in devices:
            device_no = device.get("device_no")
            if not device_no:
                continue
            value = device.get("value") or {}
            is_online = device.get("is_online", 0)
            data: dict[str, Any] = {"deviceNo": device_no}
            data.update(value)
            data["online"] = is_online
            signal = SIGNAL_DEVICE_UPDATE.format(device_no)
            dispatcher_send(self._hass, signal, data)

        _LOGGER.info("DuwiManage: Device status refresh complete, pushed %d devices", len(devices))

    def _schedule_persist_device_value(
        self, device_no: str, properties: dict[str, Any]
    ) -> None:
        """Schedule a background DB write for device property updates."""
        if not self.duwi_db or not properties:
            return
        self._hass.async_create_background_task(
            self.duwi_db.update_device_value(device_no, properties),
            "duwi_home_persist_device_value",
        )

    def _schedule_persist_device_online(
        self, device_no: str, is_online: int
    ) -> None:
        """Schedule a background DB write for device online status."""
        if not self.duwi_db:
            return
        entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
        devices = entry_data.get("devices") or []
        device = next((d for d in devices if d.get("device_no") == device_no), None)
        value = device.get("value") if device else None
        self._hass.async_create_background_task(
            self.duwi_db.update_device_status(device_no, is_online, value),
            "duwi_home_persist_device_online",
        )

    def _schedule_persist_terminal_online(
        self, terminal_sequence: str, is_online: int
    ) -> None:
        """Schedule a background DB write for terminal online status."""
        if not self.duwi_db:
            return
        self._hass.async_create_background_task(
            self.duwi_db.update_terminal_online(terminal_sequence, is_online),
            "duwi_home_persist_terminal_online",
        )

    def _schedule_persist_device_group_value(
        self, device_group_no: str, properties: dict[str, Any]
    ) -> None:
        """Schedule a background DB write for device group property updates."""
        if not self.duwi_db or not properties:
            return
        self._hass.async_create_background_task(
            self.duwi_db.update_device_group_value(device_group_no, properties),
            "duwi_home_persist_device_group_value",
        )

    async def _online_check_loop(self) -> None:
        """Periodically check RPS connectivity as safety net."""
        while True:
            try:
                await asyncio.sleep(ONLINE_CHECK_INTERVAL)
                await self._check_online_status_and_service()
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Online check loop error: %s", err, exc_info=True)

    async def operate_device(self, device_no: str, commands: list[dict[str, Any]]) -> bool:
        """Operate device via cloud or LAN based on online status.

        Args:
            device_no: Device number.
            commands: Commands list, e.g. [{"code": "switch", "value": "on"}].

        Returns:
            True if operation successful.
        """
        if not device_no or not commands:
            return False

        if self._online:
            return await self._operate_device_via_cloud(device_no, commands)

        return await self._operate_device_via_lan(device_no, commands)

    async def _operate_device_via_cloud(self, device_no: str, commands: list[dict[str, Any]]) -> bool:
        """Operate device via smarthome cloud API."""
        return await self.duwi_client.device_batch_command_operate(
            self._house_no, device_no, commands
        )

    async def _operate_device_via_lan(self, device_no: str, commands: list[dict[str, Any]]) -> bool:
        """Operate device via LAN multicast."""
        if not self.duwi_lan:
            _LOGGER.error("LAN client not available for device %s", device_no)
            return False

        # Look up device info from database
        device_info = await self.duwi_db.get_device(device_no)
        if not device_info:
            _LOGGER.error("Device %s not found in database", device_no)
            return False

        terminal_sequence = device_info.get("terminal_sequence")
        if not terminal_sequence:
            _LOGGER.error("Device %s has no terminal_sequence for LAN control", device_no)
            return False

        route = int(device_info.get("route_num") or 1)
        device_type = device_info.get("device_type_no", "")

        # Map device type to category
        device_category = self._get_device_category(device_type)

        # Convert commands list to LAN property format
        # Cloud format: [{"code": "switch", "value": "on"}]
        # LAN format: {"switch": "on", ...}
        properties = {}
        for cmd in commands:
            code = cmd.get("code")
            value = cmd.get("value")
            if code:
                properties[code] = value

        try:
            self.duwi_lan.send_device_command(
                terminal_sequence,
                route,
                device_category,
                properties=properties,
                target_host_sequence = self._get_host_sequence(terminal_sequence)
            )
            return True
        except Exception as err:
            _LOGGER.error("LAN command failed for device %s: %s", device_no, err, exc_info=True)
            return False

    async def operate_scene(self, scene_no: str) -> bool:
        """Operate a scene.

        Args:
            scene_no (str): Scene number.

        Returns:
            bool: True if successful, False otherwise.
        """

        if scene_no is None:
            return False

        if self._online:
            return await self._operate_scene_via_cloud(scene_no)

        return await self._operate_scene_via_lan(scene_no)

    async def _operate_scene_via_cloud(self, scene_no: str) -> bool:
        """Operate scene via cloud API."""
        if not scene_no:
            return False
        return await self.duwi_client.scene_execute(self._house_no, scene_no)

    async def _operate_scene_via_lan(self, scene_no: str) -> bool:
        """Operate scene via LAN multicast."""
        if not self.duwi_lan:
            _LOGGER.error("LAN client not available for scene %s", scene_no)
            return False

        # Look up scene info from database
        scene_info = await self.duwi_db.get_scene(scene_no)
        if not scene_info:
            _LOGGER.error("Scene %s not found in database", scene_no)
            return False

        if scene_info.get("is_manual_execute",0) == 0:
            _LOGGER.error("Scene %s is not manual execute", scene_no)
            return False

        if scene_info.get("execute_way",0) == 0:
            _LOGGER.error("Scene %s execute way is not LAN", scene_no)
            return False

        try:
            self.duwi_lan.send_scene_command(scene_no)
        except Exception as err:
            _LOGGER.error("LAN command failed for scene %s: %s", scene_no, err, exc_info=True)
            return False
        return True

    async def operate_device_group(self, device_group_no: str, commands: list[dict[str, Any]],sync_host_sequences:list[str]) -> bool:
        """Operate a device group.

        Args:
            device_group_no: Device group number.
            commands: Commands list, e.g. [{"code": "switch", "value": "on"}].
            sync_host_sequences: Sync host sequences, e.g. ["123456789999"].

        Returns:
            True if successful, False otherwise.
        """
        if not device_group_no or not commands:
            return False

        if self._online:
            return await self._operate_device_group_via_cloud(device_group_no, commands)

        return await self._operate_device_group_via_lan(device_group_no, commands, sync_host_sequences)

    async def _operate_device_group_via_cloud(self, device_group_no: str, commands: list[dict[str, Any]]) -> bool:
        """Operate device group via cloud API."""
        return await self.duwi_client.device_group_batch_command_operate(
            self._house_no, device_group_no, commands
        )

    async def _operate_device_group_via_lan(self, device_group_no: str, commands: list[dict[str, Any]],sync_host_sequences:list[str]) -> bool:
        """Operate device group via LAN multicast."""
        if not self.duwi_lan or len(sync_host_sequences) == 0:
            _LOGGER.error("LAN client not available for device group %s", device_group_no)
            return False

        properties = {}
        for cmd in commands:
            code = cmd.get("code")
            value = cmd.get("value")
            if code:
                properties[code] = value

        new_commands:dict[str, Any] = {}
        new_commands["group_no"] = device_group_no
        new_commands["property"] = properties

        try:
            for item in sync_host_sequences:
                self.duwi_lan.send_device_group_command(item,new_commands)
            return True
        except Exception as err:
            _LOGGER.error("LAN command failed for device group %s: %s", device_group_no, err, exc_info=True)
            return False

    async def _init_rps(self)->None:
        """Initialize RPS client."""
        self.duwi_rps = DuwiRps(
            async_get_clientsession(self._hass),
            self._app_key,
            self._secret_key,
            self._access_token,
            self._house_no,
        )

        # Subscribe RPS listeners
        def __device_rps_update(device_no: str, data: dict[str, Any]) -> None:
            """Handle device update from RPS."""
            try:
                if not self._online:
                    return
                if not device_no:
                    return

                signal = SIGNAL_DEVICE_UPDATE.format(device_no)
                dispatcher_send(self._hass, signal, data)

                # Update in-memory cache and persist to DB
                properties = {k: v for k, v in data.items() if k != "deviceNo"}
                if properties:
                    entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
                    devices = entry_data.get("devices") or []
                    device = next((d for d in devices if d.get("device_no") == device_no), None)
                    if device:
                        value = device.get("value") or {}
                        value.update(properties)
                    self._schedule_persist_device_value(device_no, properties)
            except Exception as err:
                _LOGGER.error("Error occurred while handling RPS update: %s", err, exc_info=True)

        self.duwi_rps.add_device_listener(__device_rps_update)

        def __device_group_rps_update(device_group_no: str, data: dict[str, Any]) -> None:
            """Handle device group update from RPS."""
            try:
                if not self._online:
                    return
                if not device_group_no:
                    return
                signal = SIGNAL_DEVICE_GROUP_UPDATE.format(device_group_no)
                dispatcher_send(self._hass, signal, data)

                # Update in-memory cache and persist to DB
                properties = {k: v for k, v in data.items() if k != "deviceGroupNo"}
                if properties:
                    entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
                    device_groups = entry_data.get("device_groups") or []
                    device_group = next(
                        (d for d in device_groups if d.get("device_group_no") == device_group_no),
                        None,
                    )
                    if device_group:
                        value = device_group.get("value") or {}
                        value.update(properties)
                    self._schedule_persist_device_group_value(device_group_no, properties)
            except Exception as err:
                _LOGGER.error("Error occurred while handling RPS update: %s", err, exc_info=True)

        self.duwi_rps.add_device_group_listener(__device_group_rps_update)

        def __terminal_rps_update(terminal_no: str, online:bool) -> None:
            """Handle terminal update from RPS."""
            try:
                if not self._online:
                    return
                if not terminal_no:
                    return

                entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
                terminals = entry_data.get("terminals") or []
                terminal_data = next(
                    (item for item in terminals if item.get("terminal_sequence") == terminal_no),
                    None,
                )
                if terminal_data:
                    online_int = 1 if online else 0
                    terminal_data["is_online"] = online_int
                    self._schedule_persist_terminal_online(terminal_no, online_int)

                    if terminal_data.get("is_follow_online"):
                        devices = entry_data.get("devices") or []
                        device_datas = [
                            item for item in devices
                            if item.get("terminal_sequence") == terminal_no
                        ]
                        for item in device_datas:
                            item["is_online"] = online_int
                            signal = SIGNAL_DEVICE_UPDATE.format(item["device_no"])
                            data = {"online": online_int, "deviceNo": item["device_no"]}
                            dispatcher_send(self._hass, signal, data)
                            self._schedule_persist_device_online(item["device_no"], online_int)
            except Exception as err:
                _LOGGER.error("Error occurred while handling RPS update: %s", err, exc_info=True)

        self.duwi_rps.add_terminal_listener(__terminal_rps_update)
        def __rps_connection_changed(connected: bool) -> None:
            """Handle RPS connection state change for immediate failover."""
            try:
                task = self._hass.async_create_task(
                    self._check_online_status_and_service(connected)
                )
                self._failover_tasks.add(task)
                task.add_done_callback(self._failover_tasks.discard)
            except Exception as err:
                _LOGGER.error("Error occurred while handling RPS connection change: %s", err, exc_info=True)

        self.duwi_rps.add_connection_listener(__rps_connection_changed)
        _LOGGER.info("DuwiManage: Initialize RPS")

    async def _start_rps(self) -> None:
        # Start RPS
        if self.duwi_rps is None:
            await self._init_rps()
        await self.duwi_rps.start()
        _LOGGER.info("DuwiManage: Start RPS")

    async def _init_lan(self) -> None:
        # Initialize LAN client
        if self._house_lan_secret_key and self.duwi_lan is None:
            self.duwi_lan = DuwiLanClient(self._house_lan_secret_key, self._hass)

            # Subscribe LAN listeners
            def __device_lan_update(host_sequence: str, data: dict[str, Any]) -> None:
                """Handle device update from LAN."""

                try:
                    if self._online:
                        return

                    if not host_sequence:
                        return

                    sequence = data.get("sequence")
                    route = data.get("route")

                    if not sequence or not route:
                        _LOGGER.warning("DuwiManage: LAN update missing sequence or route")
                        return

                    device_no = sequence+"-"+str(route)

                    property_data = data.get("property") or {}
                    signal = SIGNAL_DEVICE_UPDATE.format(device_no)
                    dispatcher_send(self._hass, signal, property_data|{"deviceNo":device_no})

                    # Update in-memory cache and persist to DB
                    if property_data:
                        entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
                        devices = entry_data.get("devices") or []
                        device = next((d for d in devices if d.get("device_no") == device_no), None)
                        if device:
                            value = device.get("value") or {}
                            value.update(property_data)
                        self._schedule_persist_device_value(device_no, property_data)
                except Exception as err:
                    _LOGGER.error("DuwiManage: LAN update failed: %s", err, exc_info=True)

            self.duwi_lan.add_device_listener(__device_lan_update)

            def __terminal_lan_update(host_sequence: str, data: dict[str, Any]) -> None:
                """Handle terminal online/offline update from LAN."""

                try:
                    if self._online:
                        return

                    terminal_sequence = data.get("sequence")
                    if not terminal_sequence:
                        return

                    online_value = (data.get("property") or {}).get("online")
                    if online_value is None:
                        return
                    if isinstance(online_value, str):
                        is_online = online_value.lower()=="true"
                    else:
                        is_online = bool(online_value)

                    entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
                    terminals = entry_data.get("terminals") or []
                    terminal_data = next(
                        (item for item in terminals if item.get("terminal_sequence") == terminal_sequence),
                        None,
                    )
                    if terminal_data:
                        online_int = 1 if is_online else 0
                        terminal_data["is_online"] = online_int
                        self._schedule_persist_terminal_online(terminal_sequence, online_int)

                        if terminal_data.get("is_follow_online"):
                            devices = entry_data.get("devices") or []
                            devices_data = [
                                item for item in devices
                                if item.get("terminal_sequence") == terminal_sequence
                            ]
                            for item in devices_data:
                                item["is_online"] = online_int
                                signal = SIGNAL_DEVICE_UPDATE.format(item["device_no"])
                                update_data = {"online": online_int, "deviceNo": item["device_no"]}
                                dispatcher_send(self._hass, signal, update_data)
                                self._schedule_persist_device_online(item["device_no"], online_int)
                except Exception as err:
                    _LOGGER.error("DuwiManage: LAN terminal update failed: %s", err, exc_info=True)

            self.duwi_lan.add_terminal_listener(__terminal_lan_update)

            def __host_online_update(host_sequence: str, is_online: bool, addr_ip: str, addr_port: int):
                """LAN host online update."""
                try:
                    # Only process messages related to gateway offline status
                    if not is_online:
                        entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
                        terminals = entry_data.get("terminals") or []
                        terminals_updated = [item for item in terminals if str(item.get("host_sequence","")).upper() == host_sequence]
                        if terminals_updated:
                            for terminal_updated_item in terminals_updated:
                                terminal_updated_item["is_online"] = 0
                                self._schedule_persist_terminal_online(
                                    terminal_updated_item["terminal_sequence"], 0
                                )

                                devices = entry_data.get("devices") or []
                                devices_data = [
                                    device_item for device_item in devices
                                    if device_item.get("terminal_sequence") == terminal_updated_item["terminal_sequence"]
                                ]
                                for device_date in devices_data:
                                    device_date["is_online"] = 0
                                    signal = SIGNAL_DEVICE_UPDATE.format(device_date["device_no"])
                                    update_data = {"online": 0, "deviceNo": device_date["device_no"]}
                                    dispatcher_send(self._hass, signal, update_data)
                                    self._schedule_persist_device_online(device_date["device_no"], 0)

                except Exception as err:
                    _LOGGER.error("DuwiManage: LAN host online update failed: %s", err, exc_info=True)

            self.duwi_lan.add_host_online_listener(__host_online_update)

            def __device_group_lan_update(host_sequence: str, data: dict[str, Any]) -> None:
                """Handle device group status report from LAN (device_group_cmd_up)."""
                try:
                    if self._online:
                        return

                    group_no = data.get("group_no")
                    if not group_no:
                        return

                    property_data = data.get("property") or {}
                    signal = SIGNAL_DEVICE_GROUP_UPDATE.format(group_no)
                    dispatcher_send(self._hass, signal, property_data | {"deviceGroupNo": group_no})

                    # Update in-memory cache and persist to DB
                    if property_data:
                        entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
                        device_groups = entry_data.get("device_groups") or []
                        device_group = next(
                            (d for d in device_groups if d.get("device_group_no") == group_no),
                            None,
                        )
                        if device_group:
                            value = device_group.get("value") or {}
                            value.update(property_data)
                        self._schedule_persist_device_group_value(group_no, property_data)
                except Exception as err:
                    _LOGGER.error("DuwiManage: LAN device group update failed: %s", err, exc_info=True)

            self.duwi_lan.add_device_group_listener(__device_group_lan_update)
            _LOGGER.info("DuwiManage: Initialize LAN")

    async def _start_lan(self) -> None:
        """Start LAN client, marking devices offline when failing over from cloud.

        Must be called while holding _failover_lock to avoid concurrent
        start/stop with RPS connection callbacks.
        """
        if self.duwi_lan is None:
            await self._init_lan()
            if self.duwi_lan is None:
                _LOGGER.warning(
                    "DuwiManage: LAN client unavailable (no house LAN secret key), LAN fallback disabled"
                )
                return
        if not self.is_online:
            entry_data = self._hass.data[DOMAIN].get(self._entry.entry_id, {})
            devices = entry_data.get("devices")
            if devices:
                for item in devices:
                    item["is_online"] = 0
                    signal = SIGNAL_DEVICE_UPDATE.format(item["device_no"])
                    data = {"online": 0, "deviceNo": item["device_no"]}
                    dispatcher_send(self._hass, signal, data)

            lan_started = await self.duwi_lan.start()
            if not lan_started:
                _LOGGER.warning("DuwiManage: LAN client failed to start, LAN fallback unavailable")
            _LOGGER.info("DuwiManage: Start LAN client")

    async def _delayed_lan_start(self) -> None:
        """Start LAN client after a delay to give RPS a chance to connect."""
        try:
            await asyncio.sleep(10)
            async with self._failover_lock:
                await self._start_lan()
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _get_device_category(device_type: str) -> str:
        """Map device type number to LAN device category.
        
        Args:
            device_type: Device type number (e.g., "1-001").
            
        Returns:
            Device category string for payload builder.
        """
        # Map based on device type prefix
        # 1-xxx: Power breaker
        # 3-xxx: Light
        # 4-xxx: Curtain
        # 5-xxx: HVAC
        # 6-xxx: Sensor
        # 8-xxx: Video/Audio
        if device_type.startswith("1-"):
            return "device.power"
        elif device_type.startswith("3-"):
            return "device.light"
        elif device_type.startswith("4-"):
            return "device.curtain"
        elif device_type.startswith("5-"):
            return "device.hvac"
        elif device_type.startswith("7-"):
            return "device.sensor"
        elif device_type.startswith("8-"):
            return "device.video"
        else:
            _LOGGER.warning("Unknown device type %s, defaulting to device.power", device_type)
            return "device.power"

    def _get_host_sequence(self,terminal_sequence:str) -> str|None:
        """Obtain the gateway serial number based on the controller serial number."""
        if terminal_sequence is None or terminal_sequence == "":
            return  None

        terminals = self._hass.data[DOMAIN].get(self._entry.entry_id, {}).get("terminals")
        if terminals is None:
            return None
        return next((item.get("host_sequence") for item in terminals if item.get("terminal_sequence") == terminal_sequence), None)
