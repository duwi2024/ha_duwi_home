from typing import Any

from homeassistant.components.sensor import SensorEntityDescription, SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature, PERCENTAGE, ILLUMINANCE, CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER, \
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER, CONCENTRATION_PARTS_PER_MILLION, LIGHT_LUX
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .duwi_smarthome_sdk.base.manager import Manager
from .duwi_smarthome_sdk.base.customer_device import CustomerDevice
from . import DuwiConfigEntry

from .base import DuwiEntity
from .const import DUWI_DISCOVERY_NEW, DPCode, DOMAIN, _LOGGER

SENSOR_TYPE_MAP = {
    "7-001-001": ["temp"],
    "7-002-001": ["humidity"],
    "7-003-001": ["bright"],
    "7-004-001": ["hcho"],
    "7-005-001": ["pm25"],
    "7-006-001": ["co2"],
    "7-007-001": ["iqa"],
    "7-008-003": ["bright"],
    "7-009-003": ["bright"],
    "7-010-001": ["co"],
    "7-011-001": ["tvoc"],
    "7-012-001": ["temp", "humidity", "tvoc", "pm25", "hcho", "co2", "pm10"],
    "7-012-002": ["co"],
    "7-013-001": ["bright"],
    "6-001-002": ["temp", "humidity"],
    "6-002-003": ["temp", "humidity"],
}

SENSOR_TYPE_DICT = {
    "temp": {
        "unit_of_measurement": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "humidity": {
        "unit_of_measurement": PERCENTAGE,
        "device_class": SensorDeviceClass.HUMIDITY,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "bright": {
        "unit_of_measurement": LIGHT_LUX,
        "device_class": SensorDeviceClass.ILLUMINANCE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "hcho": {
        "unit_of_measurement": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "device_class": SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "pm25": {
        "unit_of_measurement": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "device_class": SensorDeviceClass.PM25,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "pm10": {
        "unit_of_measurement": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "device_class": SensorDeviceClass.PM10,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "co2": {
        "unit_of_measurement": CONCENTRATION_PARTS_PER_MILLION,
        "device_class": SensorDeviceClass.CO2,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "iqa": {
        "unit_of_measurement": CONCENTRATION_PARTS_PER_MILLION,
        "device_class": SensorDeviceClass.AQI,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "co": {
        "unit_of_measurement": CONCENTRATION_PARTS_PER_MILLION,
        "device_class": SensorDeviceClass.CO,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "tvoc": {
        "unit_of_measurement": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "device_class": SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
}
SENSORS: dict[str, tuple[SensorEntityDescription, ...]] = {
    sensor_id: tuple(
        SensorEntityDescription(
            key=getattr(DPCode, sensor_type.upper()),
            name="",
            translation_key=sensor_type,
            device_class=SENSOR_TYPE_DICT[sensor_type].get("device_class"),
            unit_of_measurement=SENSOR_TYPE_DICT[sensor_type].get("unit_of_measurement"),
            state_class=SENSOR_TYPE_DICT[sensor_type].get("state_class"),
        ) for sensor_type in sensor_types
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
        entities: list[DuwiSensorEntity] = []
        for device_id in device_ids:
            device = hass_data.manager.device_map.get(device_id)
            if not device:
                _LOGGER.warning("Device not found in device_map: %s", device_id)
                continue
            if descriptions := SENSORS.get(device.device_sub_type_no):
                if device.device_sub_type_no == "6-002-003" or device.device_sub_type_no == "6-001-002":
                    entities.extend(
                        DuwiSensorEntity(device, hass_data.manager, description)
                        for description in descriptions
                        if device.value.get("additional_property", {}).get(description.key)
                    )
                else:
                    entities.extend(
                        DuwiSensorEntity(device, hass_data.manager, description)
                        for description in descriptions
                    )

        async_add_entities(entities)

    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, DUWI_DISCOVERY_NEW, async_discover_device)
    )


class DuwiSensorEntity(DuwiEntity, SensorEntity):
    """Duwi Switch Device."""

    def __init__(
            self,
            device: CustomerDevice,
            device_manager: Manager,
            description: SensorEntityDescription,
    ) -> None:
        """Init DuwiHaSwitch."""
        super().__init__(device, device_manager)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}{description.key}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement of the sensor, if any."""
        return self.entity_description.unit_of_measurement

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self.device.value.get(self.entity_description.key + "_value")


