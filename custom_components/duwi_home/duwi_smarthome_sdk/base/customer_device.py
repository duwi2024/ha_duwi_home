from types import SimpleNamespace
from typing import Any
from ..const.const import _LOGGER


class CustomerDevice(SimpleNamespace):
    device_no: str
    device_name: str
    device_type: str
    terminal_sequence: str
    route_num: int
    device_type_no: str
    device_sub_type_no: str
    house_no: str
    room_no: str
    is_online: bool
    create_time: str
    seq: int
    is_favorite: int
    favorite_time: str
    terminal_name: str
    host: str
    is_gesture_password: bool
    icon: str
    main_device_no: str
    is_virtual_device: bool
    value: dict[str, Any]
    room_name: str
    floor_name: str
    is_group: bool = False
    is_follow_online: bool
    hosts: list[str] = []

    def __init__(self, device_dict: dict[str, Any], _Logger=None, **kwargs: Any):
        super().__init__(**kwargs)
        self.device_no = device_dict.get("deviceNo", device_dict.get("deviceGroupNo", ""))
        self.device_name = device_dict.get("deviceName", device_dict.get("deviceGroupName", ""))
        self.device_type = device_dict.get("deviceType", "")
        self.terminal_sequence = device_dict.get("terminalSequence", "")
        self.host = device_dict.get("host", "")
        self.route_num = device_dict.get("routeNum", 0)
        self.device_type_no = device_dict.get("deviceTypeNo", "")
        self.device_sub_type_no = device_dict.get("deviceSubTypeNo", "")
        self.house_no = device_dict.get("houseNo", "")
        self.room_no = device_dict.get("roomNo", "")
        self.floor_no = device_dict.get("floorNo", "")
        self.room_name = device_dict.get("roomName", "")
        self.floor_name = device_dict.get("floorName", "")
        self.is_online = device_dict.get("isOnline", False)
        self.is_group = device_dict.get("isGroup", False)
        self.hosts = device_dict.get("syncHostSequences", []) if self.is_group else []
        if not self.hosts:
            self.hosts = device_dict.get("hosts", [])
        self.is_follow_online = device_dict.get("isFollowOnline", False)

        self.create_time = device_dict.get("createTime", "")
        self.seq = device_dict.get("seq", 0)
        self.is_favorite = device_dict.get("isFavorite", 0)
        self.favorite_time = device_dict.get("favoriteTime", "")
        self.terminal_name = device_dict.get("terminalName", "")
        self.is_gesture_password = device_dict.get("isGesturePassword", False)
        self.icon = device_dict.get("icon", "")
        self.main_device_no = device_dict.get("mainDeviceNo", "")
        self.is_virtual_device = device_dict.get("isVirtualDevice", False)
        self.device_group_type = device_dict.get("deviceGroupType", "")
        self.execute_way = device_dict.get("executeWay", "")
        self.value = device_dict.get("value", {})
        if not self.is_group:
            self.value["online"] = self.is_online

    def update_from(self, other):
        if isinstance(other, CustomerDevice):
            self.device_no = other.device_no if other.device_no else self.device_no
            self.device_name = other.device_name if other.device_name else self.device_name
            self.device_type = other.device_type if other.device_type else self.device_type
            self.terminal_sequence = other.terminal_sequence if other.terminal_sequence else self.terminal_sequence
            self.host = other.host if other.host else self.host
            self.route_num = other.route_num if other.route_num else self.route_num
            self.device_type_no = other.device_type_no if other.device_type_no else self.device_type_no
            self.device_sub_type_no = other.device_sub_type_no if other.device_sub_type_no else self.device_sub_type_no
            self.house_no = other.house_no if other.house_no else self.house_no
            self.room_no = other.room_no if other.room_no else self.room_no
            self.floor_no = other.floor_no if other.floor_no else self.floor_no
            self.room_name = other.room_name if other.room_name else self.room_name
            self.floor_name = other.floor_name if other.floor_name else self.floor_name
            self.is_online = other.is_online if other.is_online else self.is_online
            self.is_group = other.is_group if other.is_group else self.is_group
            self.create_time = other.create_time if other.create_time else self.create_time
            self.seq = other.seq if other.seq else self.seq
            self.is_favorite = other.is_favorite if other.is_favorite else self.is_favorite
            self.favorite_time = other.favorite_time if other.favorite_time else self.favorite_time
            self.terminal_name = other.terminal_name if other.terminal_name else self.terminal_name
            self.is_gesture_password = other.is_gesture_password if other.is_gesture_password else self.is_gesture_password
            self.icon = other.icon if other.icon else self.icon
            self.main_device_no = other.main_device_no if other.main_device_no else self.main_device_no
            self.is_virtual_device = other.is_virtual_device if other.is_virtual_device else self.is_virtual_device
            self.device_group_type = other.device_group_type if other.device_group_type else self.device_group_type
            self.execute_way = other.execute_way if other.execute_way else self.execute_way
            self.value = other.value.copy()

    def __eq__(self, other):
        """If devices are the same one."""
        return self.device_no == other.device_no
