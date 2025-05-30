from types import SimpleNamespace
from typing import Any


class CustomerScene(SimpleNamespace):
    def __init__(self, scene_dict: dict[str, Any], _Logger=None, **kwargs: Any):
        super().__init__(**kwargs)
        self.scene_no = scene_dict.get("sceneNo", "")
        self.scene_name = scene_dict.get("sceneName", "")
        self.room_no = scene_dict.get("roomNo", "")
        self.room_name = scene_dict.get("roomName", "")
        self.floor_no = scene_dict.get("floorNo", "")
        self.floor_name = scene_dict.get("floorName", "")
        self.house_no = scene_dict.get("houseNo", "")
        self.execute_way = scene_dict.get("executeWay", 0)
        self.sync_host_sequences = scene_dict.get("syncHostSequences", [])


