"""Support for Duwi Home covers."""
import logging
from typing import Any

from homeassistant.components.cover import CoverDeviceClass, CoverEntity
from homeassistant.components.cover.const import CoverEntityFeature
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

COVER_DEVICE_TYPES = ("4-001", "4-002", "4-003", "4-004", "4-005")

# Retractable(开合帘), Roller(卷帘), Blind(百叶帘), VerticalBlind(竖百叶帘)
COVER_GROUP_TYPES = {"Retractable", "Roller", "Blind", "VerticalBlind"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Duwi Home cover platform."""
    data = hass.data[DOMAIN].get(entry.entry_id,{})
    if not data:
        return

    duwi_manager: DuwiManager = data.get("DuwiManager")
    if not duwi_manager:
        _LOGGER.error("DuwiManager not found in hass.data")
        return

    devices = data.get("devices", [])
    device_groups = data.get("device_groups", [])

    if not devices and not device_groups:
        _LOGGER.info("No devices or groups found for house %s", entry.data.get(HOUSE_NO))
        return

    covers: list[CoverEntity] = []
    for device in devices:
        if device.get("device_type_no") not in COVER_DEVICE_TYPES:
            continue
        if device.get("is_use",0) == 0:
            continue
        covers.append(DuwiCover(duwi_manager, entry.data.get(HOUSE_NO), device))

    for group in device_groups:
        if group.get("device_group_type") not in COVER_GROUP_TYPES:
            continue
        covers.append(DuwiGroupCover(duwi_manager, entry.data.get(HOUSE_NO), group))

    if covers:
        async_add_entities(covers)
        _LOGGER.info("Added %d cover entities (devices=%d, groups=%d)", len(covers), len(devices), len(device_groups))

class DuwiCover(DuwiDeviceEntity, CoverEntity):
    """Representation of a Duwi Home cover."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, duwi_manager: DuwiManager, house_no: str, device_data: dict[str, Any]) -> None:
        """Initialize the cover."""
        super().__init__(house_no, device_data)
        self._duwi_manager = duwi_manager
        self._attr_unique_id = f"duwi_cover_{self._duwi_device_no}"
        self._attr_name = None

        self._set_device_features()
        self._attr_device_class = self._get_device_class()

        # Initial state
        control = self._duwi_device_value.get("control", "stop")
        if control == "open":
            self._attr_is_opening = True
        elif control == "close":
            self._attr_is_closing = True
        elif control == "stop":
            self._attr_is_closing = False
            self._attr_is_opening = False
        self._attr_current_cover_position = int(self._duwi_device_value.get("control_percent",0))
        self._attr_is_closed = self._attr_current_cover_position == 0
        if "light_angle" in self._duwi_device_value and self._duwi_device_type_no == "4-004":
            self._attr_current_cover_tilt_position = int((int(self._duwi_device_value.get("light_angle",0))/180)*100)
        elif "angle_degree" in self._duwi_device_value and self._duwi_device_type_no == "4-003":
            self._attr_current_cover_tilt_position = int((int(self._duwi_device_value.get("angle_degree",0))/360)*100)
        self._attr_available = self._duwi_is_online

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._duwi_device_no)},
            name=self._duwi_device_name,
            manufacturer=MANUFACTURER,
            model=self._duwi_device_sub_type_no,
            serial_number=self._duwi_device_no,
        )

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

        _LOGGER.debug("Received update for device %s: %s", self._duwi_device_no, data)
        # RPS msg example: {"deviceNo": "11800000002-1", "switch": "on", "light": 50}
        if data.get("deviceNo") != self._duwi_device_no:
            return

        # Update device value
        self._update_device_value(data)

        for key, value in data.items():
            if key == "open":
                self._attr_is_opening = True
                self._attr_is_closing = False
            elif key == "close":
                self._attr_is_closing = True
                self._attr_is_opening = False
            elif key == "stop":
                self._attr_is_closing = False
                self._attr_is_opening = False
            elif key == "control_percent":
                self._attr_current_cover_position = int(value)
                self._attr_is_closed = self._attr_current_cover_position == 0
            elif key == "angle_degree":
                self._attr_current_cover_tilt_position = int(int(value)/360*100)
            elif key == "light_angle":
                self._attr_current_cover_tilt_position = int(int(value)/180*100)

        if "online" in data:
            self._attr_available = bool(data["online"])
            self._update_online_status(bool(data["online"]))
        else:
            self._attr_available = True

        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        try:
            commands = [{"code":"control", "value": "open"}]
            await self._duwi_manager.operate_device(
                self._duwi_device_no, commands
            )
        except Exception as err:
            _LOGGER.error("Error open cover %s: %s", self._duwi_device_no, err, exc_info=True)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        try:
            commands = [{"code":"control", "value": "close"}]
            await self._duwi_manager.operate_device(
                self._duwi_device_no, commands
            )
        except Exception as err:
            _LOGGER.error("Error close cover %s: %s", self._duwi_device_no, err, exc_info=True)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        try:
            commands = [{"code":"control", "value": "stop"}]
            await self._duwi_manager.operate_device(
                self._duwi_device_no, commands
            )
        except Exception as err:
            _LOGGER.error("Error stop cover %s: %s", self._duwi_device_no, err, exc_info=True)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set cover position."""
        try:
            commands = [{"code":"control_percent", "value": kwargs["position"]}]
            await self._duwi_manager.operate_device(
                self._duwi_device_no, commands
            )
        except Exception as err:
            _LOGGER.error("Error set cover position %s: %s", self._duwi_device_no, err, exc_info=True)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Set cover tilt position."""
        try:
            value = int(kwargs["tilt_position"])
            commands = []
            if self._duwi_device_type_no == "4-004":
                value = int(value/100*180)
                commands = [{"code":"light_angle", "value":value}]
            else:
                value = int(value/100*360)
                commands = [{"code":"angle_degree", "value":value}]
            await self._duwi_manager.operate_device(
                self._duwi_device_no, commands
            )
        except Exception as err:
            _LOGGER.error("Error set cover tilt position %s: %s", self._duwi_device_no, err, exc_info=True)

    def _set_device_features(self) -> None:
        """Set supported features based on device type."""
        if self._duwi_device_type_no in ("4-003", "4-004"):
            self._attr_supported_features = (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
                | CoverEntityFeature.SET_POSITION
                | CoverEntityFeature.SET_TILT_POSITION
            )
        else:
            self._attr_supported_features = (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
                | CoverEntityFeature.SET_POSITION
            )

    def _get_device_class(self) -> str | None:
        """Get the device class for a device."""
        if self._duwi_device_type_no == "4-001":
            return CoverDeviceClass.CURTAIN
        if self._duwi_device_type_no == "4-002":
            return CoverDeviceClass.SHADE
        if self._duwi_device_type_no == "4-003":
            return CoverDeviceClass.BLIND
        if self._duwi_device_type_no == "4-004":
            return CoverDeviceClass.BLIND
        if self._duwi_device_type_no == "4-005":
            return CoverDeviceClass.WINDOW
        return None

class DuwiGroupCover(DuwiGroupEntity, CoverEntity):
    """Representation of a Duwi device group as a cover."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, duwi_manager: DuwiManager, house_no: str, group_data: dict[str, Any]) -> None:
        """Initialize the cover."""
        super().__init__(house_no, group_data)
        self._duwi_manager = duwi_manager
        self._attr_unique_id = f"duwi_group_cover_{self._duwi_group_no}"
        self._attr_name = self._duwi_group_name

        self._set_group_features()
        self._attr_device_class = self._get_group_class()

        # Initial state
        control= self._duwi_group_value.get("control","stop")
        if control == "open":
            self._attr_is_opening = True
        elif control == "close":
            self._attr_is_closing = True
        elif control == "stop":
            self._attr_is_closing = False
            self._attr_is_opening = False
        self._attr_current_cover_position = int(self._duwi_group_value.get("control_percent",0))
        self._attr_is_closed = self._attr_current_cover_position == 0
        if "light_angle" in self._duwi_group_value and self._duwi_group_type == "VerticalBlind":
            self._attr_current_cover_tilt_position = int((int(self._duwi_group_value.get("light_angle",0))/180)*100)
        elif "angle_degree" in self._duwi_group_value and self._duwi_group_type == "Blind":
            self._attr_current_cover_tilt_position = int((int(self._duwi_group_value.get("angle_degree",0))/360)*100)
        self._attr_available = self._duwi_is_online

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

        _LOGGER.debug("Received update for group %s: %s", self._duwi_group_no, data)
        # RPS msg example: {"deviceNo": "11800000002-1", "switch": "on", "light": 50}
        if data.get("deviceGroupNo") != self._duwi_group_no:
            return

        # Update group value
        self._update_group_value(data)

        for key, value in data.items():
            if key == "open":
                self._attr_is_opening = True
                self._attr_is_closing = False
            elif key == "close":
                self._attr_is_closing = True
                self._attr_is_opening = False
            elif key == "stop":
                self._attr_is_closing = False
                self._attr_is_opening = False
            elif key == "control_percent":
                self._attr_current_cover_position = int(value)
                self._attr_is_closed = self._attr_current_cover_position == 0
            elif key == "angle_degree":
                self._attr_current_cover_tilt_position = int(int(value)/360*100)
            elif key == "light_angle":
                self._attr_current_cover_tilt_position = int(int(value)/180*100)

        if "online" in data:
            self._attr_available = bool(data["online"])
            self._update_online_status(bool(data["online"]))
        else:
            self._attr_available = True

        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        try:
            commands = [{"code":"control", "value": "open"}]
            await self._duwi_manager.operate_device_group(
                self._duwi_group_no, commands,self._duwi_sync_host_sequences
            )
        except Exception as err:
            _LOGGER.error("Error open cover %s: %s", self._duwi_group_no, err, exc_info=True)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        try:
            commands = [{"code":"control", "value": "close"}]
            await self._duwi_manager.operate_device_group(
                self._duwi_group_no, commands,self._duwi_sync_host_sequences
            )
        except Exception as err:
            _LOGGER.error("Error close cover %s: %s", self._duwi_group_no, err, exc_info=True)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        try:
            commands = [{"code":"control", "value": "stop"}]
            await self._duwi_manager.operate_device_group(
                self._duwi_group_no, commands,self._duwi_sync_host_sequences
            )
        except Exception as err:
            _LOGGER.error("Error stop cover %s: %s", self._duwi_group_no, err, exc_info=True)
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set cover position."""
        try:
            commands = [{"code":"control_percent", "value": kwargs["position"]}]
            await self._duwi_manager.operate_device_group(
                self._duwi_group_no, commands, self._duwi_sync_host_sequences
            )
        except Exception as err:
            _LOGGER.error("Error set cover position %s: %s", self._duwi_group_no, err, exc_info=True)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Set cover tilt position."""
        try:
            value = int(kwargs["tilt_position"])
            commands = []
            if self._duwi_group_type == "VerticalBlind":
                value = int(value/100*180)
                commands = [{"code":"light_angle", "value":value}]
            else:
                value = int(value/100*360)
                commands = [{"code":"angle_degree", "value":value}]
            await self._duwi_manager.operate_device_group(
                self._duwi_group_no, commands, self._duwi_sync_host_sequences
            )
        except Exception as err:
            _LOGGER.error("Error set cover tilt position %s: %s", self._duwi_group_no, err, exc_info=True)

    def _set_group_features(self) -> None:
        """Set supported features based on group type."""
        if self._duwi_group_type in ("Blind", "VerticalBlind"):
            self._attr_supported_features = (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
                | CoverEntityFeature.SET_POSITION
                | CoverEntityFeature.SET_TILT_POSITION
            )
        else:
            self._attr_supported_features = (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
                | CoverEntityFeature.SET_POSITION
            )

    def _get_group_class(self) -> str | None:
        """Get the group class for a device."""
        if self._duwi_group_type == "Retractable":
            return CoverDeviceClass.CURTAIN
        if self._duwi_group_type == "Roller":
            return CoverDeviceClass.SHADE
        if self._duwi_group_type == "Blind":
            return CoverDeviceClass.BLIND
        if self._duwi_group_type == "VerticalBlind":
            return CoverDeviceClass.BLIND
        return None
