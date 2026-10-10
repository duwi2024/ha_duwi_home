"""Support for Duwi Home lights."""
import colorsys
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import DuwiDeviceEntity, DuwiGroupEntity
from .const import (
    DOMAIN,
    HOUSE_NO,
    MANUFACTURER,
    SIGNAL_DEVICE_GROUP_UPDATE,
    SIGNAL_DEVICE_UPDATE,
)
from .duwi_iot.duwi_manager import DuwiManager

_LOGGER = logging.getLogger(__name__)

LIGHT_DEVICE_TYPES = ("1-001", "1-004", "3-001", "3-002", "3-003", "3-004", "3-005", "3-006", "3-007")

LIGHT_GROUP_TYPES = {"Light", "Color", "LightColor", "RGBW", "RGB", "RGBCW"}


def _resolve_color_mode(
    supported_color_modes: set[ColorMode] | None,
    color_temp_kelvin: int | None,
    brightness: int | None,
    hs_color: tuple[float, float] | None = None,
) -> ColorMode:
    """Resolve the color mode based on current state."""
    if hs_color is not None and supported_color_modes and ColorMode.HS in supported_color_modes:
        return ColorMode.HS
    if color_temp_kelvin is not None and supported_color_modes and ColorMode.COLOR_TEMP in supported_color_modes:
        return ColorMode.COLOR_TEMP
    if brightness is not None and supported_color_modes and ColorMode.BRIGHTNESS in supported_color_modes:
        return ColorMode.BRIGHTNESS
    if supported_color_modes:
        return next(iter(supported_color_modes))
    return ColorMode.ONOFF

_DEVICE_COLOR_MODES: dict[str, set[ColorMode]] = {
    "1-001": {ColorMode.ONOFF},
    "1-004": {ColorMode.ONOFF},
    "3-001": {ColorMode.BRIGHTNESS},
    "3-002": {ColorMode.COLOR_TEMP},
    "3-003": {ColorMode.COLOR_TEMP},
    "3-004": {ColorMode.RGBW},
    "3-005": {ColorMode.RGB},
    "3-006": {ColorMode.COLOR_TEMP, ColorMode.HS},
    "3-007": {ColorMode.ONOFF},
}

_GROUP_DEVICE_COLOR_MODES: dict[str, set[ColorMode]] = {
    "Light": {ColorMode.BRIGHTNESS},
    "Color": {ColorMode.COLOR_TEMP},
    "LightColor": {ColorMode.COLOR_TEMP},
    "RGBW": {ColorMode.RGBW},
    "RGB": {ColorMode.RGB},
    "RGBCW": {ColorMode.COLOR_TEMP, ColorMode.HS}
}

_COLOR_TEMP_DEVICE_TYPES = {"3-002","3-003", "3-004","3-006"}
_COLOR_TEMP_GROUP_DEVICE_TYPES = {"LightColor", "Color", "RGBW", "RGBCW"}


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """将 duwi HSV (h:0-360, s:0-100, v:0-100) 转为 RGB (0-255)."""
    r, g, b = colorsys.hsv_to_rgb(h / 360, s / 100, v / 100)
    return (int(r * 255), int(g * 255), int(b * 255))


def _rgb_to_hsv(r: int, g: int, b: int) -> dict[str, int]:
    """将 RGB (0-255) 转为 duwi HSV 格式."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return {"h": int(h * 360), "s": int(s * 100), "v": int(v * 100)}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Duwi Home light platform."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    if not data:
        return

    duwi_manager: DuwiManager | None = data.get("DuwiManager")
    if not duwi_manager:
        return

    devices: list[dict[str, Any]] = data.get("devices", [])
    device_groups: list[dict[str, Any]] = data.get("device_groups", [])

    lights: list[LightEntity] = []

    for device in devices:
        if device.get("device_type_no") not in LIGHT_DEVICE_TYPES:
            continue
        if device.get("is_use",0) == 0:
            continue
        lights.append(DuwiLight(duwi_manager, entry.data.get(HOUSE_NO), device))

    for group in device_groups:
        if group.get("device_group_type") not in LIGHT_GROUP_TYPES:
            continue
        lights.append(DuwiGroupLight(duwi_manager, entry.data.get(HOUSE_NO), group))

    if lights:
        async_add_entities(lights)
        _LOGGER.info("Added %d light entities (devices=%d, groups=%d)", len(lights), len(devices), len(device_groups))


class DuwiLight(DuwiDeviceEntity,LightEntity):
    """Representation of a Duwi Home light."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        duwi_manager: DuwiManager,
        house_no: str,
        device_data: dict[str, Any],
    ) -> None:
        """Initialize the light."""
        super().__init__(house_no, device_data)
        self._duwi_manager = duwi_manager

        self._attr_unique_id = f"duwi_light_{self._duwi_device_no}"
        self._attr_name = None

        # set supported color modes
        self._attr_supported_color_modes = _DEVICE_COLOR_MODES.get(
            self._duwi_device_type_no, {ColorMode.ONOFF}
        )

        # Color temp range (mireds) from device config
        if self._duwi_device_type_no in _COLOR_TEMP_DEVICE_TYPES:
            ct_range = self._duwi_device_value.get("color_temp_range") or {}
            kelvin_min = ct_range.get("min", 3000)
            kelvin_max = ct_range.get("max", 6000)
            self._attr_max_color_temp_kelvin = kelvin_max
            self._attr_min_color_temp_kelvin = kelvin_min

        self._update_state_from_value(self._duwi_device_value)
        self._attr_available = self._duwi_is_online

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._duwi_device_no)},
            name=self._duwi_device_name,
            manufacturer=MANUFACTURER,
            model=self._duwi_device_sub_type_no,
            serial_number=self._duwi_device_no,
        )

    def _update_state_from_value(self, value: dict[str, Any]) -> None:
        """Update brightness, color_temp, color_mode from value dict."""
        if "switch" in value and value["switch"] is not None:
            self._attr_is_on = value["switch"].lower() == "on"
        if "light" in value and value["light"] is not None:
            self._attr_brightness = self._duwi_to_ha_brightness(value["light"])
        # 3-002 设备仅支持色温调节，不支持亮度调节，固定亮度为最大值
        if self._duwi_device_type_no == "3-002":
            self._attr_brightness = 255
        if "color_temp" in value and value["color_temp"] is not None:
            self._attr_color_temp_kelvin = int(value["color_temp"])
        if "color" in value and value["color"] is not None:
            color = value["color"]
            h, s, v = color.get("h", 0), color.get("s", 0), color.get("v", 100)
            if ColorMode.RGBW in self._attr_supported_color_modes:
                r, g, b = _hsv_to_rgb(h, s, v)
                self._attr_rgbw_color = (r, g, b, 0)
            elif ColorMode.RGB in self._attr_supported_color_modes:
                self._attr_rgb_color = _hsv_to_rgb(h, s, v)
            else:
                self._attr_hs_color = (h, s)
            self._attr_brightness = self._duwi_to_ha_brightness(v)

        self._attr_color_mode = _resolve_color_mode(
            self._attr_supported_color_modes, self._attr_color_temp_kelvin, self._attr_brightness, self._attr_hs_color
        )

    @staticmethod
    def _duwi_to_ha_brightness(duwi: int) -> int:
        """Convert duwi brightness (0-100) to HA brightness (0-255)."""
        return max(0, min(255, round(int(duwi) * 255 / 100)))

    @staticmethod
    def _ha_to_duwi_brightness(ha: int) -> int:
        """Convert HA brightness (0-255) to duwi brightness (0-100)."""
        return max(0, min(100, round(int(ha) * 100 / 255)))

    def _get_device_value_color_v(self) -> int:
        """Get duwi color value."""
        color = self._duwi_device_value.get("color",{})
        return color.get("v",0)

    def _get_current_hsv(self) -> dict[str, int]:
        """Get current color as duwi HSV format."""
        if self._attr_rgbw_color is not None:
            r, g, b, _ = self._attr_rgbw_color
            return _rgb_to_hsv(r, g, b)
        if self._attr_rgb_color is not None:
            r, g, b = self._attr_rgb_color
            return _rgb_to_hsv(r, g, b)
        if self._attr_hs_color is not None:
            h, s = self._attr_hs_color
            return {"h": int(h), "s": int(s), "v": self._ha_to_duwi_brightness(self._attr_brightness or 255)}
        return {"h": 0, "s": 0, "v": self._ha_to_duwi_brightness(self._attr_brightness or 255)}


    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        signal = SIGNAL_DEVICE_UPDATE.format(self._duwi_device_no)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_update)
        )

    @callback
    def _handle_update(self, data: dict[str, Any]) -> None:
        """Handle device update from RPS or LAN."""
        if data.get("deviceNo") != self._duwi_device_no:
            return

        # Update device value
        self._update_device_value(data)

        for key, value in data.items():
            if key == "switch":
                self._attr_is_on = value.lower() == "on"
            elif key == "light":
                # 3-002 设备仅支持色温调节，不支持亮度调节，固定亮度为最大值
                if self._duwi_device_type_no == "3-002":
                    self._attr_brightness = 255
                else:
                    self._attr_brightness = self._duwi_to_ha_brightness(value)
                if ColorMode.BRIGHTNESS in self._attr_supported_color_modes:
                    self._attr_color_mode = ColorMode.BRIGHTNESS
            elif key == "color_temp":
                self._attr_color_temp_kelvin = int(value)
                if ColorMode.COLOR_TEMP in self._attr_supported_color_modes:
                    self._attr_color_mode = ColorMode.COLOR_TEMP
            elif key == "color":
                h, s, v = value.get("h", 0), value.get("s", 0), value.get("v", 100)
                if ColorMode.RGBW in self._attr_supported_color_modes:
                    r, g, b = _hsv_to_rgb(h, s, v)
                    self._attr_rgbw_color = (r, g, b, 0)
                    self._attr_color_mode = ColorMode.RGBW
                elif ColorMode.RGB in self._attr_supported_color_modes:
                    self._attr_rgb_color = _hsv_to_rgb(h, s, v)
                    self._attr_color_mode = ColorMode.RGB
                else:
                    self._attr_hs_color = (h, s)
                    self._attr_color_mode = ColorMode.HS
                self._attr_brightness = self._duwi_to_ha_brightness(v)

        if "online" in data:
            self._attr_available = bool(data["online"])
            self._update_online_status(bool(data["online"]))
        else:
            self._attr_available = True

        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        try:
            commands =[]

            if ATTR_RGBW_COLOR in kwargs:
                r, g, b, _ = kwargs[ATTR_RGBW_COLOR]
                commands.append({"code": "color", "value": _rgb_to_hsv(r, g, b)})

            if ATTR_RGB_COLOR in kwargs:
                r, g, b = kwargs[ATTR_RGB_COLOR]
                commands.append({"code": "color", "value": _rgb_to_hsv(r, g, b)})

            if ATTR_BRIGHTNESS in kwargs and ATTR_HS_COLOR not in kwargs and ATTR_RGBW_COLOR not in kwargs and ATTR_RGB_COLOR not in kwargs:
                # 3-002 设备仅支持色温调节，不支持亮度调节，忽略亮度指令
                if self._duwi_device_type_no == "3-002":
                    pass
                elif ColorMode.RGBW in self._attr_supported_color_modes or ColorMode.RGB in self._attr_supported_color_modes:
                    # RGBW/RGB 设备：亮度合并到 HSV color 命令
                    hsv = self._get_current_hsv()
                    hsv["v"] = self._ha_to_duwi_brightness(kwargs["brightness"])
                    commands.append({"code": "color", "value": hsv})
                else:
                    commands.append(
                        {
                            "code": "light",
                            "value": self._ha_to_duwi_brightness(kwargs["brightness"]),
                        }
                    )

            if ATTR_COLOR_TEMP_KELVIN in kwargs:
                commands.append(
                    {
                        "code": "color_temp",
                        "value": kwargs["color_temp_kelvin"],
                    }
                )

            if ATTR_HS_COLOR in kwargs and ATTR_BRIGHTNESS in kwargs:
                commands.append(
                    {
                        "code": "color",
                        "value": {
                            "h": int(kwargs[ATTR_HS_COLOR][0]),
                            "s": int(kwargs[ATTR_HS_COLOR][1]),
                            "v": int(self._ha_to_duwi_brightness(kwargs[ATTR_BRIGHTNESS]))
                        },
                    }
                )

            if ATTR_HS_COLOR in kwargs and ATTR_BRIGHTNESS not in kwargs:
                commands.append(
                    {
                        "code": "color",
                        "value": {
                            "h": int(kwargs[ATTR_HS_COLOR][0]),
                            "s": int(kwargs[ATTR_HS_COLOR][1]),
                            "v": int(self._get_device_value_color_v())
                        },
                    }
                )

            if len(commands) == 0:
                commands.append(
                    {
                        "code": "switch",
                        "value": "on",
                    }
                )

            await self._duwi_manager.operate_device(
                self._duwi_device_no, commands
            )
        except Exception as err:
            _LOGGER.error("Error turning on light %s: %s", self._duwi_device_no, err, exc_info=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        try:
            commands = [{"code": "switch", "value": "off"}]
            await self._duwi_manager.operate_device(
                self._duwi_device_no, commands
            )
        except Exception as err:
            _LOGGER.error("Error turning off light %s: %s", self._duwi_device_no, err, exc_info=True)

class DuwiGroupLight(DuwiGroupEntity, LightEntity):
    """Representation of a Duwi device group as a light."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        duwi_manager: DuwiManager,
        house_no: str,
        group_data: dict[str, Any],
    ) -> None:
        """Initialize the group light."""
        super().__init__(house_no, group_data)
        self._duwi_manager = duwi_manager

        self._attr_unique_id = f"duwi_group_light_{self._duwi_group_no}"
        self._attr_name = self._duwi_group_name

        # set supported color modes
        self._attr_supported_color_modes = _GROUP_DEVICE_COLOR_MODES.get(
            self._duwi_group_type, {ColorMode.ONOFF}
        )

        # Color temp range (mireds) from device config
        if self._duwi_group_type in _COLOR_TEMP_GROUP_DEVICE_TYPES:
            ct_range = self._duwi_group_value.get("color_temp_range") or {}
            kelvin_min = ct_range.get("min", 3000)
            kelvin_max = ct_range.get("max", 6000)
            self._attr_max_color_temp_kelvin = kelvin_max
            self._attr_min_color_temp_kelvin = kelvin_min

        self._attr_is_on = self._duwi_group_value.get("switch", "").lower() == "on"
        raw_light = self._duwi_group_value.get("light")
        if raw_light is not None:
            self._attr_brightness = self._duwi_to_ha_brightness(int(raw_light))
        raw_color_temp = self._duwi_group_value.get("color_temp")
        if raw_color_temp is not None:
            self._attr_color_temp_kelvin = int(raw_color_temp)
        raw_color = self._duwi_group_value.get("color")
        if raw_color is not None:
            h, s, v = raw_color.get("h", 0), raw_color.get("s", 0), raw_color.get("v", 100)
            if ColorMode.RGBW in self._attr_supported_color_modes:
                r, g, b = _hsv_to_rgb(h, s, v)
                self._attr_rgbw_color = (r, g, b, 0)
            elif ColorMode.RGB in self._attr_supported_color_modes:
                self._attr_rgb_color = _hsv_to_rgb(h, s, v)
            else:
                self._attr_hs_color = (h, s)
            self._attr_brightness = self._duwi_to_ha_brightness(v)

        self._attr_color_mode = _resolve_color_mode(
            self._attr_supported_color_modes, self._attr_color_temp_kelvin, self._attr_brightness, self._attr_hs_color
        )

        self._attr_available = self._duwi_is_online

    @staticmethod
    def _duwi_to_ha_brightness(duwi: int) -> int:
        """Convert duwi brightness (0-100) to HA brightness (0-255)."""
        return max(0, min(255, round(duwi * 255 / 100)))

    @staticmethod
    def _ha_to_duwi_brightness(ha: int) -> int:
        """Convert HA brightness (0-255) to duwi brightness (0-100)."""
        return max(0, min(100, round(ha * 100 / 255)))

    def _get_device_value_color_v(self) -> int:
        """Get duwi color value."""
        color = self._duwi_group_value.get("color",{})
        return color.get("v",0)

    def _get_current_hsv(self) -> dict[str, int]:
        """Get current color as duwi HSV format."""
        if self._attr_rgbw_color is not None:
            r, g, b, _ = self._attr_rgbw_color
            return _rgb_to_hsv(r, g, b)
        if self._attr_rgb_color is not None:
            r, g, b = self._attr_rgb_color
            return _rgb_to_hsv(r, g, b)
        if self._attr_hs_color is not None:
            h, s = self._attr_hs_color
            return {"h": int(h), "s": int(s), "v": self._ha_to_duwi_brightness(self._attr_brightness or 255)}
        return {"h": 0, "s": 0, "v": self._ha_to_duwi_brightness(self._attr_brightness or 255)}

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        signal = SIGNAL_DEVICE_GROUP_UPDATE.format(self._duwi_group_no)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_update)
        )

    @callback
    def _handle_update(self, data: dict[str, Any]) -> None:
        """Handle group update from RPS or LAN."""
        if data.get("deviceGroupNo") != self._duwi_group_no:
            return

        # Update group value
        self._update_group_value(data)

        for key, value in data.items():
            if key == "switch":
                self._attr_is_on = value.lower() == "on"
            elif key == "light":
                self._attr_brightness = self._duwi_to_ha_brightness(value)
                if ColorMode.BRIGHTNESS in self._attr_supported_color_modes:
                    self._attr_color_mode = ColorMode.BRIGHTNESS
            elif key == "color_temp":
                self._attr_color_temp_kelvin = int(value)
                if ColorMode.COLOR_TEMP in self._attr_supported_color_modes:
                    self._attr_color_mode = ColorMode.COLOR_TEMP
            elif key == "color":
                h, s, v = value.get("h", 0), value.get("s", 0), value.get("v", 100)
                if ColorMode.RGBW in self._attr_supported_color_modes:
                    r, g, b = _hsv_to_rgb(h, s, v)
                    self._attr_rgbw_color = (r, g, b, 0)
                    self._attr_color_mode = ColorMode.RGBW
                elif ColorMode.RGB in self._attr_supported_color_modes:
                    self._attr_rgb_color = _hsv_to_rgb(h, s, v)
                    self._attr_color_mode = ColorMode.RGB
                else:
                    self._attr_hs_color = (h, s)
                    self._attr_color_mode = ColorMode.HS
                self._attr_brightness = self._duwi_to_ha_brightness(v)

        if "online" in data:
            self._attr_available = bool(data["online"])
            self._update_online_status(bool(data["online"]))
        else:
            self._attr_available = True

        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        try:
            commands =[]

            if ATTR_RGBW_COLOR in kwargs:
                r, g, b, _ = kwargs[ATTR_RGBW_COLOR]
                commands.append({"code": "color", "value": _rgb_to_hsv(r, g, b)})

            if ATTR_RGB_COLOR in kwargs:
                r, g, b = kwargs[ATTR_RGB_COLOR]
                commands.append({"code": "color", "value": _rgb_to_hsv(r, g, b)})

            if ATTR_BRIGHTNESS in kwargs and ATTR_HS_COLOR not in kwargs and ATTR_RGBW_COLOR not in kwargs and ATTR_RGB_COLOR not in kwargs:
                if ColorMode.RGBW in self._attr_supported_color_modes or ColorMode.RGB in self._attr_supported_color_modes:
                    # RGBW/RGB 设备：亮度合并到 HSV color 命令
                    hsv = self._get_current_hsv()
                    hsv["v"] = self._ha_to_duwi_brightness(kwargs["brightness"])
                    commands.append({"code": "color", "value": hsv})
                else:
                    commands.append(
                        {
                            "code": "light",
                            "value": self._ha_to_duwi_brightness(kwargs["brightness"]),
                        }
                    )

            if ATTR_COLOR_TEMP_KELVIN in kwargs:
                commands.append(
                    {
                        "code": "color_temp",
                        "value": kwargs["color_temp_kelvin"],
                    }
                )

            if ATTR_HS_COLOR in kwargs and ATTR_BRIGHTNESS in kwargs:
                commands.append(
                    {
                        "code": "color",
                        "value": {
                            "h": int(kwargs[ATTR_HS_COLOR][0]),
                            "s": int(kwargs[ATTR_HS_COLOR][1]),
                            "v": int(self._ha_to_duwi_brightness(kwargs[ATTR_BRIGHTNESS]))
                        },
                    }
                )

            if ATTR_HS_COLOR in kwargs and ATTR_BRIGHTNESS not in kwargs:
                commands.append(
                    {
                        "code": "color",
                        "value": {
                            "h": int(kwargs[ATTR_HS_COLOR][0]),
                            "s": int(kwargs[ATTR_HS_COLOR][1]),
                            "v": int(self._get_device_value_color_v())
                        },
                    }
                )

            if len(commands) == 0:
                commands.append(
                    {
                        "code": "switch",
                        "value": "on",
                    }
                )

            await self._duwi_manager.operate_device_group(
                self._duwi_group_no, commands,self._duwi_sync_host_sequences
            )
        except Exception as err:
            _LOGGER.error("Error turning on light %s: %s", self._duwi_group_no, err, exc_info=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        try:
            commands = [{"code": "switch", "value": "off"}]
            await self._duwi_manager.operate_device_group(
                self._duwi_group_no, commands,self._duwi_sync_host_sequences
            )
        except Exception as err:
            _LOGGER.error("Error turning off light %s: %s", self._duwi_group_no, err, exc_info=True)
