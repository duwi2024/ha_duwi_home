"""Support for Duwi Home binary sensors."""
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import DuwiDeviceEntity
from .const import DOMAIN, HOUSE_NO, MANUFACTURER, SIGNAL_DEVICE_UPDATE
from .duwi_iot.duwi_manager import DuwiManager

_LOGGER = logging.getLogger(__name__)

BINARY_SENSOR_DEFS: dict[str, tuple[BinarySensorDeviceClass | None, str]] = {
    "oap_s": (BinarySensorDeviceClass.PROBLEM, "过流保护"),
    "ovp_s": (BinarySensorDeviceClass.PROBLEM, "过压保护"),
    "uvp_s": (BinarySensorDeviceClass.PROBLEM, "欠压保护"),
    "ohp_s": (BinarySensorDeviceClass.PROBLEM, "过热保护"),
    "lock_s": (BinarySensorDeviceClass.PROBLEM, "锁定状态"),
    "human_state": (BinarySensorDeviceClass.OCCUPANCY, "人体感应"),
}

_TRIGGER_DEFS: dict[str, tuple[BinarySensorDeviceClass | None, str]] = {
    "7-009-002": (BinarySensorDeviceClass.OCCUPANCY, "光栅人体感应"),
    "7-009-003": (BinarySensorDeviceClass.OCCUPANCY, "红外人体感应"),
    "7-009-004": (BinarySensorDeviceClass.OCCUPANCY, "人体感应器"),
    "7-009-005": (BinarySensorDeviceClass.DOOR, "门磁"),
    "7-009-006": (BinarySensorDeviceClass.MOISTURE, "水浸"),
    "7-009-007": (BinarySensorDeviceClass.SMOKE, "烟雾报警"),
    "7-009-008": (BinarySensorDeviceClass.GAS, "可燃气体报警"),
    "7-009-009": (BinarySensorDeviceClass.OCCUPANCY, "存在感应"),
    "7-009-010": (BinarySensorDeviceClass.OCCUPANCY, "人体感应"),
    "7-009-011": (BinarySensorDeviceClass.OCCUPANCY, "人体感应"),
}

BINARY_SENSOR_DEVICE_TYPES: dict[str, list[str]] = {
    "1-001": ["oap_s", "ovp_s", "uvp_s", "ohp_s", "lock_s"],
    "1-002": ["oap_s", "ovp_s", "uvp_s", "ohp_s", "lock_s"],
    "1-003": ["oap_s", "ovp_s", "uvp_s", "ohp_s", "lock_s"],
    "7-008": ["human_state"],
    "7-009": ["trigger_state"],
    "7-013": ["human_state"],
    "7-016": ["trigger_state"],
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Duwi Home binary sensor platform."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    if not data:
        return

    duwi_manager: DuwiManager | None = data.get("DuwiManager")
    devices: list[dict[str, Any]] = data.get("devices", [])
    if not duwi_manager or not devices:
        return

    entities: list[DuwiBinarySensor] = []
    for device in devices:
        if device.get("is_use", 0) != 1:
            continue
        device_type = device.get("device_type_no", "")
        device_sub_type = device.get("device_sub_type_no", "")
        value: dict[str, Any] = device.get("value", {}) or {}

        binary_keys = BINARY_SENSOR_DEVICE_TYPES.get(device_sub_type) or BINARY_SENSOR_DEVICE_TYPES.get(device_type)
        if binary_keys is None:
            continue

        for value_key in binary_keys:
            if value_key not in value:
                continue

            if value_key == "trigger_state":
                device_class, name = _TRIGGER_DEFS.get(
                    device_sub_type, (None, "触发状态")
                )
            else:
                device_class, name = BINARY_SENSOR_DEFS[value_key]

            entities.append(
                DuwiBinarySensor(
                    duwi_manager, entry.data.get(HOUSE_NO), device,
                    value_key, device_class, name,
                )
            )

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d binary sensor entities", len(entities))


class DuwiBinarySensor(DuwiDeviceEntity, BinarySensorEntity):
    """Representation of a Duwi Home binary sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        duwi_manager: DuwiManager,
        house_no: str,
        device_data: dict[str, Any],
        value_key: str,
        device_class: BinarySensorDeviceClass | None,
        name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(house_no, device_data)
        self._duwi_manager = duwi_manager
        self._value_key = value_key

        self._attr_unique_id = f"duwi_binary_{self._duwi_device_no}_{value_key}"
        self._attr_name = name
        self._attr_device_class = device_class

        self._attr_is_on = bool(self._duwi_device_value.get(value_key, False))
        self._attr_available = self._duwi_is_online

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._duwi_device_no)},
            name=self._duwi_device_name,
            manufacturer=MANUFACTURER,
            model=self._duwi_device_sub_type_no,
            serial_number=self._duwi_device_no,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return self._attr_is_on

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

        self._update_device_value(data)

        if self._value_key in data:
            self._attr_is_on = bool(data[self._value_key])

        if "online" in data:
            self._attr_available = bool(data["online"])
        else:
            self._attr_available = True

        self.async_write_ha_state()
