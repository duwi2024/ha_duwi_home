from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntityDescription, BinarySensorEntity, \
    BinarySensorDeviceClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .duwi_smarthome_sdk.base.manager import Manager
from .duwi_smarthome_sdk.base.customer_device import CustomerDevice
from . import DuwiConfigEntry

from .base import DuwiEntity
from .const import DUWI_DISCOVERY_NEW, DPCode, DOMAIN, _LOGGER

SENSOR_TYPE_MAP = {
    "7-008-001": (DPCode.HUMAN, BinarySensorDeviceClass.PRESENCE),
    "7-008-002": (DPCode.HUMAN, BinarySensorDeviceClass.PRESENCE),
    "7-008-003": (DPCode.HUMAN, BinarySensorDeviceClass.PRESENCE),
    "7-009-001": (DPCode.HUMAN, BinarySensorDeviceClass.MOTION),
    "7-009-002": (DPCode.MOVING, BinarySensorDeviceClass.MOVING),
    "7-009-003": (DPCode.HUMAN, BinarySensorDeviceClass.PRESENCE),
    "7-009-004": (DPCode.HUMAN, BinarySensorDeviceClass.PRESENCE),
    "7-009-005": (DPCode.DOOR, BinarySensorDeviceClass.DOOR),
    "7-009-006": (DPCode.MOISTURE, BinarySensorDeviceClass.MOISTURE),
    "7-009-007": (DPCode.GAS, BinarySensorDeviceClass.GAS),
    "7-009-008": (DPCode.SMOKE, BinarySensorDeviceClass.SMOKE),
    "7-009-009": (DPCode.HUMAN, BinarySensorDeviceClass.PRESENCE),
    "7-009-010": (DPCode.HUMAN, BinarySensorDeviceClass.PRESENCE),
    "7-013-001": (DPCode.HUMAN, BinarySensorDeviceClass.PRESENCE),
    "6-001-002": (DPCode.SMOKE, BinarySensorDeviceClass.MOTION),
    "6-002-003": (DPCode.SMOKE, BinarySensorDeviceClass.MOTION),
}

BINARY_SENSORS: dict[str, tuple[BinarySensorEntityDescription, ...]] = {
    sensor_id: (
        BinarySensorEntityDescription(
            key=sensor_types[0],
            name="",
            translation_key=sensor_id,
            device_class=sensor_types[1],
        ),
    )
    for sensor_id, sensor_types in SENSOR_TYPE_MAP.items()
}


async def async_setup_entry(
        hass: HomeAssistant, entry: DuwiConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up duwi sensors dynamically through duwi discovery."""
    hass_data = hass.data[DOMAIN].get(entry.entry_id)
    @callback
    def async_discover_device(device_ids: list[str]) -> None:
        """Discover and add a discovered duwi sensor."""
        entities: list[DuwiBinarySensorEntity] = []
        for device_id in device_ids:
            device = hass_data.manager.device_map.get(device_id)
            if not device:
                # _LOGGER.warning("Device not found in device_map: %s", device_id)
                continue
            if descriptions := BINARY_SENSORS.get(device.device_sub_type_no):
                entities.extend(
                    DuwiBinarySensorEntity(device, hass_data.manager, description)
                    for description in descriptions
                )
        async_add_entities(entities)

    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, DUWI_DISCOVERY_NEW, async_discover_device)
    )


class DuwiBinarySensorEntity(DuwiEntity, BinarySensorEntity):
    """Duwi Switch Device."""

    def __init__(
            self,
            device: CustomerDevice,
            device_manager: Manager,
            description: BinarySensorEntityDescription,
    ) -> None:
        """Init DuwiHaSwitch."""
        super().__init__(device, device_manager)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the state of the sensor."""
        v = self.device.value
        return (v.get("human_state", v.get("trigger_state", False))
                or v.get("additional_property", {}).get(DPCode.TRIGGER, False))
