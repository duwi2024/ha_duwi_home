"""Support for Duwi devices."""
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

class DuwiDeviceEntity:
    """Base class for device entities."""
    def __init__(self, house_no: str, device_data: dict[str, Any]):
        self._duwi_house_no = house_no
        self._duwi_device_no = device_data.get("device_no")
        self._duwi_device_name = device_data.get("device_name", "")
        self._duwi_room_no = device_data.get("room_no", "")
        self._duwi_terminal_sequence = device_data.get("terminal_sequence", "")
        self._duwi_terminal_name = device_data.get("terminal_name", "")
        self._duwi_route_num = device_data.get("route_num", 1)
        self._duwi_is_use = bool(device_data.get("is_use", 0))
        self._duwi_is_online = bool(device_data.get("is_online", 0))
        self._duwi_device_type_no = device_data.get("device_type_no", "")
        self._duwi_device_sub_type_no = device_data.get("device_sub_type_no", "")
        self._duwi_device_value: dict[str, Any] = device_data.get("value", {}) or {}

    def _update_online_status(self, is_online: bool) -> None:
        """Update online status."""
        self._duwi_is_online = is_online

    def _update_device_value(self, device_values: dict[str, Any]) -> None:
        """Update device value."""
        for key, value in device_values.items():
            if key == "deviceNo":
                continue
            self._duwi_device_value[key] = value


class DuwiSceneEntity:
    """Base class for scene entities."""
    def __init__(self, house_no: str, scene_data: dict[str, Any]):
        self._duwi_house_no = house_no
        self._duwi_scene_no = scene_data.get("scene_no")
        self._duwi_scene_name = scene_data.get("scene_name", "")
        self._duwi_is_use = bool(scene_data.get("is_use", 0))
        self._duwi_scene_execute_way = scene_data.get("execute_way", "")


class DuwiGroupEntity:
    """Base class for device group entities."""

    def __init__(self, house_no: str, group_data: dict[str, Any]) -> None:
        self._duwi_house_no = house_no
        self._duwi_group_no = group_data.get("device_group_no", "")
        self._duwi_group_name = group_data.get("device_group_name", "")
        self._duwi_group_type = group_data.get("device_group_type", "")
        raw_value = group_data.get("value")
        self._duwi_group_value: dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}
        self._duwi_execute_way = group_data.get("execute_way", 0)
        self._duwi_room_no = group_data.get("room_no", "")
        self._duwi_sync_host_sequences = group_data.get("sync_host_sequences") or []
        self._duwi_is_online = bool(self._duwi_group_value.get("is_online", 0))

    def _update_group_value(self, group_value: dict[str, Any]) -> None:
        """Update the group's current value from a real-time update."""
        for key, value in group_value.items():
            if key == "deviceGroupNo":
                continue
            self._duwi_group_value[key] = value
    def _update_online_status(self, is_online: bool) -> None:
        """Update online status."""
        self._duwi_is_online = is_online

