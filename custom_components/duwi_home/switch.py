from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)

from .duwi_smarthome_sdk.base.manager import Manager
from .duwi_smarthome_sdk.base.customer_device import CustomerDevice
from . import DuwiConfigEntry

from .base import DuwiEntity
from .const import DUWI_DISCOVERY_NEW, DPCode, DOMAIN, _LOGGER

SWITCHES: dict[str, tuple[SwitchEntityDescription, ...]] = {
    "1-002": (
        SwitchEntityDescription(
            key=DPCode.SWITCH,
            name=None,
            translation_key="duwi_switch",
            device_class=SwitchDeviceClass.SWITCH,
        ),
    ),
    "1-003": (
        SwitchEntityDescription(
            key=DPCode.SWITCH,
            name=None,
            translation_key="duwi_switch",
            device_class=SwitchDeviceClass.SWITCH,
        ),
    ),
    "1-005": (
        SwitchEntityDescription(
            key=DPCode.SWITCH,
            name=None,
            translation_key="duwi_switch",
            device_class=SwitchDeviceClass.SWITCH,
        ),
    ),
    "1-006": (
        SwitchEntityDescription(
            key=DPCode.SWITCH,
            name=None,
            translation_key="duwi_switch",
            device_class=SwitchDeviceClass.SWITCH,
        ),
    ),
    "107-001": (
        SwitchEntityDescription(
            key=DPCode.SWITCH,
            name=None,
            translation_key="duwi_switch",
            device_class=SwitchDeviceClass.SWITCH,
        ),
    ),
    "107-002": (
        SwitchEntityDescription(
            key=DPCode.SWITCH,
            name=None,
            translation_key="duwi_switch",
            device_class=SwitchDeviceClass.SWITCH,
        ),
    ),
    "107-003": (
        SwitchEntityDescription(
            key=DPCode.SWITCH,
            name=None,
            translation_key="duwi_switch",
            device_class=SwitchDeviceClass.SWITCH,
        ),
    ),
}

GROUP_SWITCHES: dict[str, tuple[SwitchEntityDescription, ...]] = {
    "Breaker": (
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

    @callback
    def async_discover_device(device_ids: list[str]) -> None:
        """Discover and add a discovered duwi sensor."""
        entities: list[DuwiSwitchEntity] = []
        for device_id in device_ids:
            device = hass_data.manager.device_map.get(device_id)
            if not device:
                _LOGGER.warning("Device not found in device_map: %s", device_id)
                continue
            if descriptions := SWITCHES.get(device.device_type_no) or GROUP_SWITCHES.get(device.device_group_type):
                entities.extend(
                    DuwiSwitchEntity(device, hass_data.manager, description)
                    for description in descriptions
                )

        async_add_entities(entities)

    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, DUWI_DISCOVERY_NEW, async_discover_device)
    )


class DuwiSwitchEntity(DuwiEntity, SwitchEntity):
    """Duwi Switch Device."""

    def __init__(
            self,
            device: CustomerDevice,
            device_manager: Manager,
            description: SwitchEntityDescription,
    ) -> None:
        """Init DuwiHaSwitch."""
        super().__init__(device, device_manager)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}{description.key}"

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self.device.value.get(self.entity_description.key, "off") == "on"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the switch."""
        v = self.device.value
        attrs = {}
        if v.get("oap_s") is not None:
            attrs["过载保护状态"] = "过载" if v.get("oap_s", False) else "正常"
        if v.get("ovp_s") is not None:
            attrs["过压保护状态"] = "未启用" if not v.get("ouvp_use") else ("过压" if v.get("ovp_s", False) else "正常")
        if v.get("uvp_s") is not None:
            attrs["欠压保护状态"] = "未启用" if not v.get("ouvp_use") else ("欠压" if v.get("uvp_s", False) else "正常")
        if v.get("ohp_s") is not None:
            attrs["过热保护状态"] = "过热" if v.get("ohp_s", False) else "正常"
        if v.get("lock_s") is not None:
            attrs["锁定状态"] = "锁定" if v.get("lock_s", False) else "正常"
        if v.get("elec_use") is not None:
            attrs["用电量"] = f"{v.get('electricity', 0)} kWh"
        if v.get("current_use") is not None:
            attrs["电流"] = f"{v.get('current', 0)} A"
        if v.get("voltage_use") is not None:
            attrs["电压"] = f"{v.get('voltage', 0)} V"
        if v.get("activepower") is not None:
            attrs["功率"] = f"{v.get('activepower', 0)} w"
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self.device.value.get("lock_s", False):
            return
        await self._send_command({self.entity_description.key: "on"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self.device.value.get("lock_s", False):
            return
        await self._send_command({self.entity_description.key: "off"})
