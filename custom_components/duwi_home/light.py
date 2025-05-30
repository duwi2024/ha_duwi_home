import asyncio
import functools
import time
from typing import Any

from homeassistant.components.light import LightEntity, LightEntityDescription, ColorMode, ATTR_BRIGHTNESS, \
    ATTR_COLOR_TEMP, ATTR_HS_COLOR
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.helpers.event import async_call_later

from .duwi_smarthome_sdk.base.manager import Manager
from .duwi_smarthome_sdk.base.customer_device import CustomerDevice
from . import DuwiConfigEntry, debounce

from .base import DuwiEntity
from .const import DUWI_DISCOVERY_NEW, DPCode, DOMAIN, _LOGGER

LIGHTS: dict[str, tuple[LightEntityDescription, ...]] = {
    "1-001": (
        LightEntityDescription(
            key=DPCode.ON_OFF,
            name="",
        ),
    ),
    "1-004": (
        LightEntityDescription(
            key=DPCode.ON_OFF,
            name="",
        ),
    ),
    "3-001": (
        LightEntityDescription(
            key=DPCode.LIGHT,
            name="",
        ),
    ),
    "3-002": (
        LightEntityDescription(
            key=DPCode.COLOR_TEMP,
            name="",
            translation_key="color_temp",
        ),
    ),
    "3-003": (
        LightEntityDescription(
            key=DPCode.COLOR_TEMP,
            name="",
        ),
    ),
    "3-004": (
        LightEntityDescription(
            key=DPCode.RGB,
            name="",
        ),
    ),
    "3-005": (
        LightEntityDescription(
            key=DPCode.RGBW,
            name="",
        ),
    ),
    "3-006": (
        LightEntityDescription(
            key=DPCode.RGBCW,
            name="",
        ),
    ),
}
GROUP_LIGHTS: dict[str, tuple[LightEntityDescription, ...]] = {
    "Light": (
        LightEntityDescription(
            key=DPCode.LIGHT,
            name="",
        ),
    ),
    "Color": (
        LightEntityDescription(
            key=DPCode.COLOR,
            name="",
        ),
    ),
    "LightColor": (
        LightEntityDescription(
            key=DPCode.COLOR_TEMP,
            name="",
        ),
    ),
    "RGB": (
        LightEntityDescription(
            key=DPCode.RGB,
            name="",
        ),
    )
}


async def async_setup_entry(
        hass: HomeAssistant, entry: DuwiConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up duwi sensors dynamically through duwi discovery."""
    hass_data = hass.data[DOMAIN].get(entry.entry_id)

    @callback
    def async_discover_device(device_ids: list[str]) -> None:
        """Discover and add a discovered duwi sensor."""
        entities: list[DuwiLightEntity] = []
        for device_id in device_ids:
            device = hass_data.manager.device_map.get(device_id)
            if not device:
                _LOGGER.warning("Device not found in device_map: %s", device_id)
                continue
            if descriptions := LIGHTS.get(device.device_type_no) or GROUP_LIGHTS.get(device.device_group_type):
                entities.extend(
                    DuwiLightEntity(device, hass_data.manager, description)
                    for description in descriptions
                )

        async_add_entities(entities)

    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, DUWI_DISCOVERY_NEW, async_discover_device)
    )


class DuwiLightEntity(DuwiEntity, LightEntity):
    """Duwi Switch Device."""

    def __init__(
            self,
            device: CustomerDevice,
            device_manager: Manager,
            description: LightEntityDescription,
    ) -> None:
        """Init DuwiHaSwitch."""
        super().__init__(device, device_manager)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}{description.key}"

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

    @property
    def supported_color_modes(self) -> set[ColorMode] | set[str] | None:
        """Flag supported color modes."""
        if self.entity_description.key == DPCode.RGB or self.entity_description.key == DPCode.RGBW:
            return {ColorMode.HS}
        elif self.entity_description.key == DPCode.COLOR_TEMP or self.entity_description.key == DPCode.COLOR:
            return {ColorMode.COLOR_TEMP}
        elif self.entity_description.key == DPCode.LIGHT:
            return {ColorMode.BRIGHTNESS}
        elif self.entity_description.key == DPCode.RGBCW:
            return {ColorMode.HS, ColorMode.COLOR_TEMP}
        elif self.entity_description.key == DPCode.ON_OFF:
            return {ColorMode.ONOFF}
        return {ColorMode.ONOFF}

    @property
    def color_mode(self) -> ColorMode | str | None:
        """Return the color mode of the light."""
        if self.entity_description.key == DPCode.RGB or self.entity_description.key == DPCode.RGBW or self.entity_description.key == DPCode.RGBCW:
            return ColorMode.HS
        elif self.entity_description.key == DPCode.COLOR_TEMP or self.entity_description.key == DPCode.COLOR:
            return ColorMode.COLOR_TEMP
        elif self.entity_description.key == DPCode.LIGHT:
            return ColorMode.BRIGHTNESS

        return ColorMode.ONOFF

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self.device.value.get("switch", "off") == "on"

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        if ColorMode.HS in self.supported_color_modes:
            return int(self.device.value.get("color", {}).get("v", 0) / 100 * 255)
        else:
            return int(self.device.value.get("light", 0) / 100 * 255)

    @property
    def color_temp(self) -> int | None:
        """Return the CT color value in mireds."""
        if ColorMode.COLOR_TEMP in self.supported_color_modes:
            ct = self.device.value.get("color_temp")
            if ct:
                return 1000000 // ct
        return None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value [float, float]."""
        if ColorMode.HS in self.supported_color_modes:
            return (
                self.device.value.get("color", {}).get("h", 0),
                self.device.value.get("color", {}).get("s", 0)
            )

    @property
    def min_mireds(self) -> int | None:
        """Return the coldest color_temp that this light supports."""
        if ColorMode.COLOR_TEMP in self.supported_color_modes:
            r = {
                "min": 3000,
                "max": 6000,
            } if not self.device.is_group else {
                "min": 2000,
                "max": 8000,
            }
            color_temp_range = self.device.value.get("color_temp_range", r)
            color_temp_max = color_temp_range.get("max")
            return 1000000 // color_temp_max

    @property
    def max_mireds(self) -> int | None:
        """Return the warmest color_temp that this light supports."""
        if ColorMode.COLOR_TEMP in self.supported_color_modes:
            r = {
                "min": 3000,
                "max": 6000,
            } if not self.device.is_group else {
                "min": 2000,
                "max": 8000,
            }
            color_temp_range = self.device.value.get("color_temp_range", r)
            color_temp_min = color_temp_range.get("min")
            return 1000000 // color_temp_min

    # @debounce(10)
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self.device.value.get("lock_s", False):
            return
        command = {}
        if ATTR_BRIGHTNESS in kwargs:
            # Set brightness from kwargs if present
            if ColorMode.HS in self.supported_color_modes:
                # If it's a color light, adjust the color brightness accordingly
                command = {
                    "color": {
                        "h": int(self.hs_color[0]),
                        "s": int(self.hs_color[1]),
                        "v": int(round(kwargs[ATTR_BRIGHTNESS] / 255 * 100)),
                    }
                }
            else:
                command = {
                    "light": int(round(kwargs[ATTR_BRIGHTNESS] / 255 * 100))
                }

        if ATTR_COLOR_TEMP in kwargs:
            command = {
                "color_temp": int(1000000 / kwargs[ATTR_COLOR_TEMP] // 100 * 100)
            }

        if ATTR_HS_COLOR in kwargs:
            command = {
                "color": {
                    "h": int(kwargs[ATTR_HS_COLOR][0]),
                    "s": int(kwargs[ATTR_HS_COLOR][1]),
                    "v": int(round(self.brightness / 255 * 100))
                }
            }
            self.device.value["color"] = command["color"]
            self.async_write_ha_state()

        if not command:
            command = {"switch": "on"}
        await self._send_command(command)
        # await self.becoming_controllable()

    # @debounce(4)
    # async def becoming_controllable(self):
    #     self.is_control = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self.device.value.get("lock_s", False):
            return
        await self._send_command({"switch": "off"})
