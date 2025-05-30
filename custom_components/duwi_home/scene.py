from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.helpers.typing import UndefinedType

from .duwi_smarthome_sdk.base.customer_scene import CustomerScene
from .duwi_smarthome_sdk.base.manager import Manager
from .duwi_smarthome_sdk.base.customer_device import CustomerDevice
from . import DuwiConfigEntry

from .base import DuwiEntity
from .const import DUWI_DISCOVERY_NEW, DPCode, DOMAIN, _LOGGER, MANUFACTURER, DUWI_SCENE_UPDATE

SWITCHES: dict[str, tuple[SwitchEntityDescription, ...]] = {
    "1-001": (
        SwitchEntityDescription(
            key=DPCode.SWITCH,
            name=None,
            translation_key="duwi_switch",
            device_class=SwitchDeviceClass.SWITCH,
        ),
    ),
}


async def async_setup_entry(
        hass: HomeAssistant, entry: DuwiConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up duwi sensors dynamically through duwi discovery."""
    hass_data = hass.data[DOMAIN].get(entry.entry_id)
    sm = hass_data.manager.scene_map

    # TODO 断网的时候状态变化做一下
    # async_add_entities(DuwiSceneEntity(hass_data.manager, scene) for scene in sm.values())
    @callback
    def async_discover_device() -> None:
        """Discover and add a discovered duwi sensor."""
        async_add_entities(DuwiSceneEntity(hass_data.manager, scene) for scene in sm.values())

    async_discover_device()

    entry.async_on_unload(
        async_dispatcher_connect(hass, DUWI_SCENE_UPDATE, async_discover_device)
    )


class DuwiSceneEntity(Scene):
    """Duwi Switch Device."""
    _should_poll = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
            self,
            scene_manager: Manager,
            scene: CustomerScene,
    ) -> None:
        """Init DuwiHaSwitch."""
        self.manager = scene_manager
        self._attr_unique_id = f"dws{scene.scene_no}"
        self.scene = scene

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.unique_id}")},
            manufacturer=MANUFACTURER,
            name=self.scene.scene_name,
            model="Duwi Scene",
            suggested_area=self.scene.floor_name + " " + self.scene.room_name
        )

    async def async_added_to_hass(self) -> None:
        """Call when entity is added to hass."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DUWI_SCENE_UPDATE}_{self.scene.scene_no}",
                self.async_write_ha_state,
            )
        )

    @property
    def available(self) -> bool:
        """Return if the scene is enabled."""
        return self.manager._is_connected or self.scene.execute_way == 1

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        await self.manager.activate_scene(self.scene)
