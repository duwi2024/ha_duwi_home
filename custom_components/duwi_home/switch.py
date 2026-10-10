"""Support for Duwi Home switches."""
import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
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

SWITCH_DEVICE_TYPES = ("1-002", "1-003", "1-005", "1-006", "3-008", "3-009")

SWITCH_GROUP_TYPES = {"Breaker"}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Duwi Home switch platform."""
    data = hass.data[DOMAIN].get(entry.entry_id,{})
    if not data:
        return

    duwi_manager: DuwiManager = data.get("DuwiManager")

    if not duwi_manager:
        _LOGGER.error("DuwiManager not found in hass.data")
        return

    devices = data.get("devices", [])
    device_groups = data.get("device_groups", [])

    switches:list[SwitchEntity] = []
    for device in devices:
        if device.get("device_type_no") not in SWITCH_DEVICE_TYPES:
            continue
        if device.get("is_use",0) == 0:
            continue
        switches.append(DuwiSwitch(duwi_manager, entry.data.get(HOUSE_NO), device))

    for group in device_groups:
        if group.get("device_group_type") not in SWITCH_GROUP_TYPES:
            continue
        switches.append(DuwiGroupSwitch(duwi_manager, entry.data.get(HOUSE_NO), group))

    if switches:
        async_add_entities(switches)
        _LOGGER.info("Added %d switch entities (devices=%d, groups=%d)", len(switches), len(devices), len(device_groups))

class DuwiSwitch(DuwiDeviceEntity,SwitchEntity):
    """Representation of a Duwi Home switch."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, duwi_manager: DuwiManager, house_no: str, device_data: dict[str, Any]) -> None:
        """Initialize the switch."""
        super().__init__(house_no, device_data)
        self._duwi_manager = duwi_manager
        self._attr_unique_id = f"duwi_switch_{self._duwi_device_no}"
        self._attr_name = None

        # set device class
        self._attr_device_class = self._get_device_class()

        # Initial state
        self._attr_is_on = self._duwi_device_value.get("switch","off") == "on"
        self._attr_available = self._duwi_is_online
        self._lock_status: bool = bool(self._duwi_device_value.get("lock_s", False))

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._duwi_device_no)},
            name=self._duwi_device_name,
            manufacturer=MANUFACTURER,
            model=self._duwi_device_sub_type_no,
            serial_number=self._duwi_device_no,
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return additional state attributes."""
        return {"锁定状态": "锁定" if self._lock_status else "正常"}

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
            if key == "switch":
                self._attr_is_on = value.lower() == "on"
            elif key == "lock_s":
                self._lock_status = bool(value)

        if "online" in data:
            self._attr_available = bool(data["online"])
            self._update_online_status(bool(data["online"]))
        else:
            self._attr_available = True

        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        try:
            commands = [{"code":"switch", "value": "on"}]
            await self._duwi_manager.operate_device(
                self._duwi_device_no, commands
            )
        except Exception as err:
            _LOGGER.error("Error turning on switch %s: %s", self._duwi_device_no, err, exc_info=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        try:
            commands = [{"code":"switch", "value": "off"}]
            await self._duwi_manager.operate_device(
                self._duwi_device_no, commands
            )
        except Exception as err:
            _LOGGER.error("Error turning off switch %s: %s", self._duwi_device_no, err, exc_info=True)

    def _get_device_class(self) -> str | None:
        """Get the device class for a device."""
        if self._duwi_device_type_no == "1-002":
            return SwitchDeviceClass.OUTLET
        if self._duwi_device_type_no == "1-003":
            return SwitchDeviceClass.SWITCH
        if self._duwi_device_type_no == "1-005":
            return SwitchDeviceClass.OUTLET
        if self._duwi_device_type_no == "1-006":
            return SwitchDeviceClass.SWITCH
        if self._duwi_device_type_no == "3-008":
            return SwitchDeviceClass.OUTLET
        if self._duwi_device_type_no == "3-009":
            return SwitchDeviceClass.SWITCH
        return None

class DuwiGroupSwitch(DuwiGroupEntity, SwitchEntity):
    """Representation of a Duwi device group as a switch."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        duwi_manager: DuwiManager,
        house_no: str,
        group_data: dict[str, Any],
    ) -> None:
        """Initialize the group switch."""
        super().__init__(house_no, group_data)
        self._duwi_manager = duwi_manager
        self._attr_unique_id = f"duwi_group_switch_{self._duwi_group_no}"
        self._attr_name = self._duwi_group_name

        self._attr_is_on = self._duwi_group_value.get("switch", "").lower() == "on"
        self._attr_available = self._duwi_is_online
        self._lock_status: bool = bool(self._duwi_group_value.get("lock_s", False))

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return additional state attributes."""
        return {"锁定状态": "锁定" if self._lock_status else "正常"}

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        signal = SIGNAL_DEVICE_GROUP_UPDATE.format(self._duwi_group_no)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_update)
        )

    @callback
    def _handle_update(self, data: dict[str, Any]) -> None:
        """Handle group update from RPS."""
        _LOGGER.debug("Received update for group %s: %s", self._duwi_group_no, data)
        # msg example: {"deviceGroupNo": "11800000", "switch": "on", "light": 50}
        if data.get("deviceGroupNo") != self._duwi_group_no:
            return

        # Update device value
        self._update_group_value(data)

        for key, value in data.items():
            if key == "switch":
                self._attr_is_on = value.lower() == "on"
            elif key == "lock_s":
                self._lock_status = bool(value)

        if "online" in data:
            self._attr_available = bool(data["online"])
            self._update_online_status(bool(data["online"]))
        else:
            self._attr_available = True

        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the group switch on."""
        try:
            await self._duwi_manager.operate_device_group(
                self._duwi_group_no, [{"code": "switch", "value": "on"}], self._duwi_sync_host_sequences
            )
        except Exception as err:
            _LOGGER.error("Error turning on group switch %s: %s", self._duwi_group_no, err, exc_info=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the group switch off."""
        try:
            await self._duwi_manager.operate_device_group(
                self._duwi_group_no, [{"code": "switch", "value": "off"}], self._duwi_sync_host_sequences
            )
        except Exception as err:
            _LOGGER.error("Error turning off group switch %s: %s", self._duwi_group_no, err, exc_info=True)
