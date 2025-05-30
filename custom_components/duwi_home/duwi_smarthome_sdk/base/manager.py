from abc import ABCMeta
import asyncio
from datetime import datetime
import json
import subprocess
import time
from typing import Any

import aiohttp

from ...duwi_lan_sdk.service.lan_process import LanProcess
from ...duwi_repository_sdk.model.device import Device
from ...duwi_repository_sdk.model.device_value import DeviceValue
from ...duwi_repository_sdk.model.floor import Floor
from ...duwi_repository_sdk.model.house import House
from ...duwi_repository_sdk.model.room import Room
from ...duwi_repository_sdk.model.sence import Scene
from ...duwi_repository_sdk.model.terminal import Terminal
from ...duwi_repository_sdk.repo.base_repo import Repository
from ...duwi_repository_sdk.repo.device_repo import DeviceRepository
from ...duwi_repository_sdk.repo.device_value_repo import DeviceValueRepository
from ..api.account import AccountClient
from ..api.control import ControlClient
from ..api.discover import DiscoverClient
from ..api.floor import FloorInfoClient
from ..api.group import GroupClient
from ..api.house import HouseInfoClient
from ..api.refresh_token import AuthTokenRefresherClient
from ..api.room import RoomInfoClient
from ..api.scene_op import SceneOpClient
from ..api.scenes import SceneInfoClient
from ..api.terminal import TerminalClient
from ..api.ws import DeviceSynchronizationWS
from ..base.customer_api import CustomerApi, SharingTokenListener
from ..base.customer_device import CustomerDevice
from ..const.const import _LOGGER, DEVICE_TYPE_MAP, GROUP_TYPE, HAVC_TYPE_MAP, Code
from ..model.device_control import ControlDevice
from .customer_scene import CustomerScene


class SharingDeviceListener(metaclass=ABCMeta):
    """Sharing device listener."""

    @classmethod
    def update_device(cls, device: CustomerDevice):
        """Update device info.

        Args:
            device(CustomerDevice): updated device info

        """

    @classmethod
    def add_device(cls, device: CustomerDevice):
        """Device Added.

        Args:
            device(CustomerDevice): Device added

        """

    @classmethod
    def remove_device(cls, device_no: str):
        """Device removed.

        Args:
            device_no(str): device's id which removed

        """

    @classmethod
    def token_listener(cls, device_id: str):
        """Device removed.

        Args:
            device_id(str): device's id which removed

        """

    @classmethod
    def update_scene(cls, scene: CustomerScene):
        """Update device info.

        Args:
            scene(CustomerDevice): updated device info

        """


class Manager:
    def __init__(
            self,
            id: str,
            house_key: str,
            customer_api: CustomerApi = None,
            token_listener: SharingTokenListener = None,
            lp: LanProcess = None
    ) -> None:
        self._is_over = False
        self._is_init = True
        self._is_connected = True
        self._id = id
        self._customer_api = customer_api
        self.house_key = house_key
        self.device_map: dict[str, CustomerDevice] = {}
        self.scene_map: dict[str, CustomerScene] = {}
        self.host_list: list[str] = []
        # 初始化db
        self.db_repository = Repository(self._id)
        self.device_repository = DeviceRepository(self.db_repository)
        self.device_value_repository = DeviceValueRepository(self.db_repository)
        # 初始化account_api
        self._account_repository = AccountClient(self._customer_api)
        # 初始化ws
        self.ws = DeviceSynchronizationWS(client=self._customer_api)
        # 初始化home_api
        self._home_repository = HouseInfoClient(client=self._customer_api)
        # 初始化control_api
        self._control_repository = ControlClient(client=self._customer_api)
        # 初始化terminal_api
        self._terminal_repository = TerminalClient(client=self._customer_api)
        # 初始化discover_api
        self._discover_repository = DiscoverClient(client=self._customer_api)
        # 初始化floor_info_api
        self._floor_info_repository = FloorInfoClient(client=self._customer_api)
        # 初始化room_api
        self._room_repository = RoomInfoClient(client=self._customer_api)
        # 初始化group_api
        self._group_repository = GroupClient(client=self._customer_api)
        # 初始化场景scene_api
        self._scene_repository = SceneInfoClient(client=self._customer_api)
        # 控制场景
        self.scene_op_repository = SceneOpClient(client=self._customer_api)
        # 初始化refresh_token_update
        self._refresh_token_repository = AuthTokenRefresherClient(client=self._customer_api)
        self._token_listener = token_listener
        self._device_listeners = set()
        # 局域网相关初始化
        self._lan_process = lp
        # 局域网指令解析相关类型
        self._valid_terminal_types = {"terminal.host", "terminal.slave"}
        self._valid_device_types = {"device.power", "device.light", "device.curtain", "device.hvac",
                                    "device.security_sensor", "device.video"}

    async def init_manager(self, phone: str, password: str) -> bool:
        # 获取access_token
        data = await self._account_repository.login(phone, password)
        status = data.get("code")
        if status != Code.SUCCESS.value:
            if status == Code.NETWORK_CONFIGURATION_NOT_SUPPORTED.value or status == Code.OPERATION_TIMEOUT.value:
                self._is_connected = False
                return True
            _LOGGER.error("login error: %s", status)
            return False

        self._customer_api.access_token = data.get("data", {}).get("accessToken")
        self._customer_api.refresh_token = data.get("data", {}).get("refreshToken")
        self._customer_api.access_token_expire_time = data.get("data", {}).get("accessTokenExpireTime")
        self._customer_api.phone = phone
        self._customer_api.password = password


        self._customer_api.token_listener = self._token_listener
        _LOGGER.info("duwi manager init success")
        return True

    async def update_device_cache(self) -> bool:
        await self.ws.add_message_listener(self.on_ws_message)
        self.db_repository.init_db()
        if not self._is_connected:
            _LOGGER.error("duwi manager not connected !!")
            self.__read_data_to_devices()
            return False
        floor_data, room_data, terminal_data, terminal_cloud_dict = await self.init_from_cloud_data()
        if not floor_data or not room_data or not terminal_data or not terminal_cloud_dict:
            return False

        # 同步局域网主机
        host_sequence_list = []
        for key, value in terminal_cloud_dict.items():
            if (value.get("host") not in host_sequence_list and
                    (value.get("productModel") == 'DXH' or value.get("productModel") == "DXH-HMCUH743")):
                host_sequence_list.append(value.get("host"))

        self.host_list = host_sequence_list
        self._lan_process.sync_hosts(self._id, [], self.house_key)

        return True

    async def init_from_cloud_data(self):
        global floors_dict, rooms_floors_dict, rooms_dict, terminal_dict
        # 初始化 terminal_dict 为空字典
        terminal_dict = {}
        # 修改本地群组和设备的状态
        device_data = await self._discover_repository.discover()
        group_data = await self._group_repository.discover_groups()
        floor_data = await self._floor_info_repository.fetch_floor_info()
        room_data = await self._room_repository.fetch_room_info()
        terminal_data = await self._terminal_repository.fetch_terminal_info()
        scene_data = await self._scene_repository.fetch_scene_info()

        # 房间和楼层映射
        if floor_data.get("code") == Code.SUCCESS.value and room_data.get("code") == Code.SUCCESS.value:
            floors_dict = (
                {floor.get("floorNo"): floor.get("floorName") for floor in
                 floor_data.get("data", {}).get("floors", [])} if floor_data.get("data") else {}
            )
            rooms_floors_dict = (
                {room.get("roomNo"): room.get("floorNo") for room in
                 room_data.get("data", {}).get("rooms", [])} if room_data.get("data") else {}
            )
            rooms_dict = {room["roomNo"]: room["roomName"] for room in
                          room_data.get("data", {}).get("rooms", [])} if room_data.get("data") else {}
        else:
            _LOGGER.error("discover floor or room error")
            return floor_data, room_data, terminal_data, terminal_dict

        # 主机和从机映射 从机是否跟随上线
        if terminal_data.get("code") == Code.SUCCESS.value:
            terminal_dict = {terminal.get("terminalSequence"): {
                "host": terminal.get("hostSequence"),
                "isFollowOnline": terminal.get("isFollowOnline"),
                "productModel": terminal.get("productModel")
            } for terminal in
                terminal_data.get("data", {}).get("terminals", [])} if terminal_data.get("data") else {}
        else:
            _LOGGER.error("discover terminal error")
            return floor_data, room_data, terminal_data, terminal_dict

        # 跟新全局的设备或者群组属性
        if device_data is not None and device_data.get("code") == Code.SUCCESS.value:
            for device in device_data.get("data", {}).get("devices"):
                if device.get("isUse") == 0:
                    continue
                device["deviceType"] = DEVICE_TYPE_MAP.get(device.get("deviceSubTypeNo"))
                self.device_map[device.get("deviceNo")] = CustomerDevice(device)
        else:
            _LOGGER.error("discover device error")
            return floor_data, room_data, terminal_data, terminal_dict

        if group_data is not None and group_data.get("code") == Code.SUCCESS.value:
            for group in group_data.get("data", {}).get("deviceGroups"):
                group["isGroup"] = True
                group["deviceType"] = GROUP_TYPE.get(group.get("deviceGroupType"))
                self.device_map[group.get("deviceGroupNo")] = CustomerDevice(group)
        else:
            _LOGGER.error("discover group error")
            return floor_data, room_data, terminal_data, terminal_dict
        if scene_data is not None and scene_data.get("code") == Code.SUCCESS.value:
            for scene in scene_data.get("data", {}).get("scenes"):
                if not scene.get("isUse") or not scene.get("isManualExecute"):
                    continue
                self.scene_map[scene.get("sceneNo")] = CustomerScene(scene)
        else:
            _LOGGER.error("discover scene error")
            return floor_data, room_data, terminal_data, terminal_dict

        # 遍历设备设置设备的房间名和楼层名字
        for device in self.device_map.values():
            if device.room_no in rooms_floors_dict:
                device.room_name = rooms_dict.get(device.room_no)
                device.floor_no = rooms_floors_dict.get(device.room_no)
            if device.floor_no in floors_dict:
                device.floor_name = floors_dict.get(device.floor_no)
            if device.terminal_sequence in terminal_dict:
                device.hosts.append(terminal_dict.get(device.terminal_sequence).get("host"))
                device.is_follow_online = terminal_dict.get(device.terminal_sequence).get("isFollowOnline")
            if havc_data := HAVC_TYPE_MAP.get(device.device_sub_type_no):
                device.value["havc"] = havc_data

        # 遍历场景设置设备的房间名和楼层名字
        for scene in self.scene_map.values():
            if scene.room_no in rooms_floors_dict:
                scene.room_name = rooms_dict.get(scene.room_no)
                scene.floor_no = rooms_floors_dict.get(scene.room_no)
            if scene.floor_no in floors_dict:
                scene.floor_name = floors_dict.get(scene.floor_no)

        # self.save_data_to_local(
        #                         floor_data.get("data").get("floors"),
        #                         room_data.get("data").get("rooms"),
        #                         terminal_data.get("data").get("terminals"),
        #                         )
        return floor_data, room_data, terminal_data, terminal_dict

    def __read_data_to_devices(self):
        devices = self.db_repository.list_entities(Device)
        device_values = self.db_repository.list_entities(DeviceValue)
        houses = self.db_repository.list_entities(House)
        floors = self.db_repository.list_entities(Floor)
        rooms = self.db_repository.list_entities(Room)
        terminals = self.db_repository.list_entities(Terminal)
        scenes = self.db_repository.list_entities(Scene)
        # 局域网状态下的主机列表
        host_sequence_list = []
        for t in terminals:
            if (t.host_sequence not in host_sequence_list and
                    (t.product_model == 'DXH' or t.product_model == "DXH-HMCUH743")):
                host_sequence_list.append(t.host_sequence)
        self.host_list = host_sequence_list
        self._lan_process.sync_hosts(self._id, host_sequence_list, self.house_key)
        for s in scenes:
            scene = CustomerScene(s.to_dict())
            for f in floors:
                if f.floor_no == scene.floor_no:
                    scene.floor_name = f.floor_name
            for r in rooms:
                if r.room_no == scene.room_no:
                    scene.room_name = r.room_name
            self.scene_map[s.scene_no] = scene

        for d in devices:
            device_no = d.device_no
            customer_device = CustomerDevice(d.to_dict())
            for dv in device_values:
                if dv.device_no == device_no:
                    customer_device.value[dv.code] = dv.value
            for h in houses:
                if h.house_no == customer_device.house_no:
                    customer_device.house_name = h.house_name
            for f in floors:
                if f.floor_no == customer_device.floor_no:
                    customer_device.floor_name = f.floor_name
            for r in rooms:
                if r.room_no == customer_device.room_no:
                    customer_device.room_name = r.room_name
            for t in terminals:
                if t.terminal_sequence == customer_device.terminal_sequence:
                    customer_device.hosts.append(t.host_sequence)
            self.device_map[customer_device.device_no] = customer_device

    async def save_data_to_local(self,
                                 # floors: list[dict],
                                 # rooms: list[dict],
                                 # terminals: list[dict],
                                 ):
        """Save data to local file"""
        global floors, rooms, terminals
        devices = list(self.device_map.values())
        houses = {
            "houseNo": self._customer_api.house_no,
            "houseName": self._customer_api.house_name,
            "lanSecretKey": self.house_key
        }
        floors_data = await self._floor_info_repository.fetch_floor_info()
        rooms_data = await self._room_repository.fetch_room_info()
        terminal_data = await self._terminal_repository.fetch_terminal_info()
        if floors_data is None or rooms_data is None or terminal_data is None:
            _LOGGER.error("Failed to fetch floor info")
            return
        self.db_repository.clear_all_table()
        self.db_repository.init_db()
        floors = floors_data.get("data").get("floors")
        rooms = rooms_data.get("data").get("rooms")
        terminals = terminal_data.get("data").get("terminals")
        device_datas: list[Device] = []
        device_value_datas: list[DeviceValue] = []
        house_datas: list[House] = []
        floor_datas: list[Floor] = []
        room_datas: list[Room] = []
        terminal_datas: list[Terminal] = []
        scene_datas: list[Scene] = []
        for d in devices:
            device_data = Device(
                device_no=d.device_no,
                device_name=d.device_name,
                device_type=d.device_type,
                terminal_sequence=d.terminal_sequence,
                route_num=d.route_num,
                device_type_no=d.device_type_no,
                device_sub_type_no=d.device_sub_type_no,
                house_no=d.house_no,
                floor_no=d.floor_no,
                room_no=d.room_no,
                create_time=d.create_time,
                device_group_type=d.device_group_type,
                seq=d.seq,
                is_follow_online=d.is_follow_online,
                is_favorite=d.is_favorite,
                favorite_time=d.favorite_time,
                hosts=d.hosts,
                is_group=d.is_group
            )
            device_datas.append(device_data)

            for v in d.value:
                device_value_data = DeviceValue(
                    device_no=d.device_no,
                    code=v,
                    value=d.value.get(v) if v != "online" else False
                )
                device_value_datas.append(device_value_data)

        house_data = House(
            house_no=houses.get("houseNo"),
            house_name=houses.get("houseName"),
            lan_secret_key=houses.get("lanSecretKey")
        )
        house_datas.append(house_data)

        for f in floors:
            floor_data = Floor(
                floor_no=f.get("floorNo"),
                floor_name=f.get("floorName")
            )
            floor_datas.append(floor_data)
        for r in rooms:
            room_data = Room(
                room_no=r.get("roomNo"),
                room_name=r.get("roomName")
            )
            room_datas.append(room_data)
        for t in terminals:
            terminal_data = Terminal(
                terminal_sequence=t.get("terminalSequence"),
                host_sequence=t.get("hostSequence"),
                product_model=t.get("productModel")
            )
            terminal_datas.append(terminal_data)
        for s in self.scene_map.values():
            scene_data = Scene(
                scene_no=s.scene_no,
                scene_name=s.scene_name,
                room_no=s.room_no,
                floor_no=s.floor_no,
                house_no=s.house_no,
                execute_way=s.execute_way,
                sync_host_sequences=s.sync_host_sequences
            )
            scene_datas.append(scene_data)
        self.db_repository.add_entities(device_datas)
        self.db_repository.add_entities(device_value_datas)
        self.db_repository.add_entities(house_datas)
        self.db_repository.add_entities(floor_datas)
        self.db_repository.add_entities(room_datas)
        self.db_repository.add_entities(terminal_datas)
        self.db_repository.add_entities(scene_datas)
        # _LOGGER.debug("save data to local file success")

    def on_ws_message(self, msg: str):
        msg_dict = json.loads(msg)
        namespace = msg_dict.get("namespace")
        if namespace not in [
            "Duwi.RPS.DeviceValue",
            "Duwi.RPS.TerminalOnline",
            "Duwi.RPS.DeviceGroupValue",
        ]:
            _LOGGER.info(f"not support namespace: {msg_dict.get('namespace')}")
            return
        code_data = msg_dict.get("result", {}).get("msg")
        # _LOGGER.debug("ws返回来的设备 namespace = %s msg_dict = %s", namespace, code_data)
        device_id = code_data.get("deviceNo") or code_data.get("deviceGroupNo")
        # 修改本地的状态变化
        self._on_device_report(namespace, device_id, code_data)

    def _on_device_report(self, namespace: str, device_id: str, status: dict[str, Any]):
        # 设备状态
        if namespace == "Duwi.RPS.DeviceValue" or namespace == "Duwi.RPS.DeviceGroupValue":
            device = self.device_map.get(device_id, None)
            if not device:
                _LOGGER.warn(f"device {device_id} not found")
                return
            device_values = []
            for v in status:
                dv = DeviceValue(
                    device_no=device_id,
                    code=v,
                    value=status.get(v)
                )
                device_values.append(dv)
            self.device_value_repository.update_device_values(device_values)
            self.__update_device(device, status)
            if "device_use" in status:
                self.__change_device(device, status["device_use"])

        # 设备联网状态
        elif namespace == "Duwi.RPS.TerminalOnline":
            sequence = status.get("sequence")
            online = status.get("online")
            for d in self.device_map:
                device = self.device_map[d]
                # 判断上线还是下线
                if online:
                    if device.is_follow_online and device.terminal_sequence == sequence:
                        self.device_map[d].value["online"] = online
                        # 下发通知
                        for listener in self._device_listeners:
                            listener.update_device(device)
                # 主机离线之后 如设备要去离线 + 跨主机群组不离线
                elif device.terminal_sequence == sequence or (sequence in device.hosts and len(device.hosts) == 1):
                    self.device_map[d].value["online"] = online
                    # 下发通知
                    for listener in self._device_listeners:
                        listener.update_device(device)

    def __change_device(self, device: CustomerDevice, device_use: bool = False):
        # 下发通知
        for listener in self._device_listeners:
            if device_use:
                _LOGGER.info(f"设备 {device.device_no} 已被使用")
                listener.add_device(device)
                #     添加本地数据
                device = self.device_map.get(device.device_no, None)
                device_value_datas = []
                device_data = Device(
                    device_no=device.device_no,
                    device_name=device.device_name,
                    device_type=device.device_type,
                    terminal_sequence=device.terminal_sequence,
                    route_num=device.route_num,
                    device_type_no=device.device_type_no,
                    device_sub_type_no=device.device_sub_type_no,
                    house_no=device.house_no,
                    floor_no=device.floor_no,
                    room_no=device.room_no,
                    create_time=device.create_time,
                    seq=device.seq,
                    is_follow_online=device.is_follow_online,
                    is_favorite=device.is_favorite,
                    favorite_time=device.favorite_time,
                    device_group_type=device.device_group_type
                )
                for v in device.value:
                    device_value_data = DeviceValue(
                        device_no=device.device_no,
                        code=v,
                        value=device.value.get(v)
                    )
                    device_value_datas.append(device_value_data)
                # _LOGGER.debug("添加持久化的本地设备数据 = %s", device_data)
                self.device_repository.add_device(device_data, device_value_datas)
            else:
                _LOGGER.info(f"设备 {device.device_no} 已被停用")
                listener.remove_device(device.device_no)
                #     移除本地数据
                self.device_repository.remove_one_device(device.device_no)

    def __update_device(self, device: CustomerDevice, status: dict[str, Any]):
        # 改变全局的设备的状态
        for k in status:
            device.value[k] = status[k]
        # 下发通知
        for listener in self._device_listeners:
            listener.update_device(device)

    def add_device_listener(self, listener: SharingDeviceListener):
        """Add device listener."""
        self._device_listeners.add(listener)

    def remove_device_listener(self, listener: SharingDeviceListener):
        """Remove device listener."""
        self._device_listeners.remove(listener)

    async def activate_scene(self, scene: CustomerScene):
        if scene.execute_way == 0 or self._is_connected:
            await self.scene_op_repository.control(scene.scene_no)
        elif scene.execute_way == 1:
            for host_sequence in scene.sync_host_sequences:
                self._lan_process.activate_scene(host_sequence, scene.scene_no)

    async def send_commands(
            self, device_no: str, is_group: bool, commands: dict[str, Any]
    ):
        cd = ControlDevice(
            device_no=device_no,
            house_no=self._customer_api.house_no,
            is_group=is_group
        )
        for k in commands:
            cd.add_param_info(k, commands[k])

        # 这里进行局域网和云平台的判断
        # 获取设备所属主机，如果所属多个主机，1个不在线就走云端
        device = self.device_map.get(device_no, None)
        if not device:
            _LOGGER.warn(f"device {device_no} not found")
            return
        # _LOGGER.debug(" -- 所有的在线的 device.hosts -- %s ", self._lan_process.get_online_hosts(self._id))
        # _LOGGER.debug("当前设备的主机 %s", device.hosts)
        host_sequences = device.hosts
        is_host_lan_online = False
        for host_sequence in host_sequences:
            if self._lan_process.check_is_online(host_sequence):
                is_host_lan_online = True
                break
            is_host_lan_online = False
        # _LOGGER.debug("self._is_connected %s", self._is_connected)
        if self._is_connected:
            # 走云端的逻辑
            _LOGGER.info("go cloud")
            expire_time_str = self._customer_api.access_token_expire_time
            if expire_time_str:
                expire_time_dt = datetime.fromisoformat(expire_time_str)
                expire_time_ts = expire_time_dt.timestamp()
                if expire_time_ts < time.time() + 2 * 24 * 60 * 60:
                    refresh_token_data = await self._refresh_token_repository.refresh()
                    auth_data = refresh_token_data.get("data", {})
                    self._token_listener.update_token(
                        is_refresh=refresh_token_data.get("code ") == Code.SUCCESS.value,
                        token_info={
                            "access_token": auth_data.get("accessToken"),
                            "refresh_token": auth_data.get("refreshToken")
                        })
                    self._customer_api.access_token_expire_time = auth_data.get("accessTokenExpire")
                    self._customer_api.access_token = auth_data.get("accessToken")
                    self._customer_api.refresh_token = auth_data.get("refreshToken")
            data = await self._control_repository.control(is_group, cd)
            if data is not None:
                if data.get("code") != Code.SUCCESS.value:
                    _LOGGER.error("send_commands error = %s message %s", data.get("code"), data.get("message"))
                else:
                    _LOGGER.info("send_commands success = %s message %s", data.get("code"), data.get("message"))
            else:
                _LOGGER.error("send_commands error,data is None")
        elif is_host_lan_online:
            _LOGGER.info("go local")
            # _LOGGER.debug(f"device {device_no} lan operation")
            for host_sequence in host_sequences:
                self._lan_process.device_operate(host_sequence, device.device_type_no, device.device_no,
                                                 device.terminal_sequence, device.route_num, device.is_group,
                                                 device.is_virtual_device, commands)

    async def unload(self, clear_local: bool = False):
        self._is_over = True
        await self.ws.remove_message_listener(self.on_ws_message)
        await self.ws.disconnect()
        if clear_local:
            self.device_map.clear()
            self.db_repository.clear_all_table()

    async def ping(self, host):
        """执行 ping 命令并返回是否成功"""
        try:
            result = await asyncio.create_subprocess_exec(
                'ping', '-c', '1', host,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            # _LOGGER.debug("result.returncode = %s host = %s", result.returncode, host)
            return result.returncode == 0
        except Exception as e:
            _LOGGER.error(f"Ping {host} 时发生异常: {e}")
            return False

    async def is_connected(self):
        dns_servers = ['www.baidu.com', 'www.duwi.com.cn']  # 使用一些国内的 DNS 服务器
        fail_count = 0
        while not self._is_over:
            try:
                async with aiohttp.ClientSession() as session:
                    for dns in dns_servers:
                        # async with session.get(url, timeout=25) as response:
                        if await self.ping(dns):
                            # if response.status == 200:
                            # _LOGGER.info(f"连接网络测试成功 %s", dns)
                            last = self._is_connected
                            fail_count = 0
                            self._is_connected = True
                            self._is_init = False
                            if last != self._is_connected:
                                _LOGGER.info("关闭局域网查询")
                                await self.enter_cloud_mode()
                            await asyncio.sleep(20)
                        else:
                            # _LOGGER.error(f"状态码异常--- status")
                            if not self.ws.is_connected:
                                _LOGGER.warning("ws连接状态也异常 fail_count ++")
                                fail_count += 1
                                if fail_count >= 5:
                                    raise aiohttp.ClientError
                            await asyncio.sleep(5)
            except (TimeoutError, aiohttp.ClientError) as e:
                if self.ws.is_connected:
                    fail_count = 0
                    _LOGGER.info("ping 失败了 但是ws依旧连接成功 跳过切换模式")
                    continue
                _LOGGER.error("连接网络测试失败 %s", e)
                last = self._is_connected
                self._is_connected = False
                if last != self._is_connected or self._is_init:
                    _LOGGER.info("开启局域网查询")
                    await self.enter_lan_mode()
                    self._lan_process.sync_hosts(self._id, self.host_list, self.house_key)
                    self._is_init = False
                await asyncio.sleep(10)

    async def enter_cloud_mode(self):
        _LOGGER.info("enter_cloud_mode")
        self._lan_process.clear_hosts(self._id)
        await self.ws.reconnect()
        # 这边要等云端数据更新到最新版本的联网状态,不然拉取的数据就是假数据
        for i in range(3):
            await asyncio.sleep(20)
            device_data = await self._discover_repository.discover()
            group_data = await self._group_repository.discover_groups()
            updated_device_nos = set()
            if group_data is not None and group_data.get("code") == Code.SUCCESS.value:
                for group in group_data.get("data", {}).get("deviceGroups"):
                    group["isGroup"] = True
                    group["deviceType"] = GROUP_TYPE.get(group.get("deviceGroupType"))
                    d = CustomerDevice(group)
                    if old := self.device_map[group.get("deviceGroupNo")]:
                        # 更新原先的设备
                        old.update_from(d)
                        updated_device_nos.add(group.get("deviceGroupNo"))
                    else:
                        # 添加云端存在的设备
                        for listener in self._device_listeners:
                            listener.add_device(d)

            if device_data.get("code") != Code.SUCCESS.value:
                _LOGGER.error("discover error = %s message %s", device_data.get("code"), device_data.get("message"))
                return
            for device in device_data.get("data", {}).get("devices"):
                if device.get("isUse") == 0:
                    continue
                device["deviceType"] = DEVICE_TYPE_MAP.get(device.get("deviceSubTypeNo"))
                if havc_data := HAVC_TYPE_MAP.get(device.get("deviceSubTypeNo")):
                    # device["value"]["havc"] = havc_data
                    device["value"].setdefault("havc", havc_data)
                d = CustomerDevice(device)
                if old := self.device_map.get(device.get("deviceNo")):
                    # 更新原先的设备
                    old.update_from(d)
                    updated_device_nos.add(device.get("deviceNo"))
                else:
                    # 添加云端存在的设备(本地没有但是云端有的设备)
                    for listener in self._device_listeners:
                        listener.add_device(d)

            # 下发更新通知
            for d in self.device_map.values():
                for listener in self._device_listeners:
                    # 云端和本地都有的设备需要通知更新
                    listener.update_device(d)
            # 筛选出没有被更新过的设备(云端没拉取到但是本地有的设备需要移除)
            non_updated_device_nos = {device_no for device_no in self.device_map if device_no not in updated_device_nos}
            for d in non_updated_device_nos:
                for listener in self._device_listeners:
                    listener.remove_device(d)
            for s in self.scene_map.values():
                for listener in self._device_listeners:
                    listener.update_scene(s)

    async def enter_lan_mode(self):
        _LOGGER.warn("enter_lan_mode----------")
        # self.ws.is_connected = False
        # 获取所有的主机
        for d in self.device_map.values():
            d.value["online"] = False

            # 下发设备状态变化通知
            for listener in self._device_listeners:
                listener.update_device(d)
        # 场景改变
        for s in self.scene_map.values():
            for listener in self._device_listeners:
                listener.update_scene(s)

    def handle_lan_message(self, message: dict[str, any]):
        # _LOGGER.debug(f"------Manager接收到局域网的消息 {message}")
        # _LOGGER.debug("self.is_connected %s", self._is_connected)
        if self._is_connected:
            return
        # 解析局域网指令
        msg_type = message["type"]
        msg_data = message["data"]

        if msg_type in self._valid_terminal_types:
            self._resolve_terminal_lan_message(msg_data)
        elif msg_type in self._valid_device_types:
            self._resolve_device_lan_message(msg_data)

    def _resolve_terminal_lan_message(self, command: dict[str, any]):
        command_keys = list(command.keys())
        device_no = ""
        sequence = ""
        if "sequence" in command:
            sequence = command["sequence"]
        status = {}
        # 处理控制器指令
        if "property" in command_keys:
            # 属性
            cmd_property = command["property"]
            if "online" in cmd_property.keys():
                online = cmd_property["online"]
                # _LOGGER.debug("sequence %s ----- online %s", sequence, online)
                for d in self.device_map:
                    device = self.device_map[d]
                    online_host = self._lan_process.get_online_hosts(self._id)
                    # 判断上线还是下线
                    if online:
                        # 设备在线
                        if not device.is_group and device.is_follow_online and device.terminal_sequence == sequence:
                            device.value["online"] = True
                            # 下发通知
                            for listener in self._device_listeners:
                                listener.update_device(device)
                        # 群组在线
                        if device.is_group:
                            for t in device.hosts:
                                if t in online_host:
                                    device.value["online"] = True
                                    # 下发通知
                                    for listener in self._device_listeners:
                                        listener.update_device(device)
                    else:
                        # 离线的情况
                        # 设备离线
                        if not device.is_group and (device.terminal_sequence == sequence or sequence in device.hosts):
                            self.device_map[d].value["online"] = False
                            # 下发通知
                            for listener in self._device_listeners:
                                listener.update_device(device)
                        # 群组离线
                        if device.is_group:
                            group_online = any(t in online_host for t in device.hosts)
                            if not group_online:
                                self.device_map[d].value["online"] = False
                                # 下发通知
                                for listener in self._device_listeners:
                                    listener.update_device(device)

        elif "service" in command_keys:
            # 服务
            cmd_service = command["service"]
            if "device_group_cmd_up" in cmd_service.keys():
                cmd_up = cmd_service["device_group_cmd_up"]
                if cmd_up is not None:
                    device_no = cmd_up["group_no"]
                    status = cmd_up["property"]

        # 处理设备指令,因为群组作为设备处理
        if device_no == "" or len(status) == 0:
            # _LOGGER.debug("len(status) %s", len(status))
            return
        device = self.device_map.get(device_no, None)
        if not device:
            _LOGGER.warning(f"device {device_no} not found")
            return
        self.__update_device(device, status)
        # _LOGGER.debug(f"------向HA发送局域网的消息 _resolve_terminal_lan_message {device_no} {status}")

    def _resolve_device_lan_message(self, command: dict[str, any]):
        command_keys = list(command.keys())
        device_no = ""
        sequence = ""
        if "sequence" in command:
            sequence = command["sequence"]
        status = {}
        # 处理控制器指令
        if "property" in command_keys:
            # 属性
            cmd_property = command["property"]
            route = ""
            if 'route' in command:
                route = command["route"]
            if route == "":
                device_no = sequence
            else:
                # 这里需要进行虚拟设备的判断
                device_no = sequence + "-" + str(route)
            status = cmd_property

        # 处理设备指令
        if device_no == "" or len(status) == 0:
            return
        device = self.device_map.get(device_no, None)
        if not device:
            _LOGGER.warning(f"device {device_no} not found")
            return
        self.__update_device(device, status)
        # _LOGGER.debug(f"------向HA发送局域网的消息 _resolve_device_lan_message {device_no} {status}")
