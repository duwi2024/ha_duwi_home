"""Support for Duwi Home sensors."""
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfDensity,
    UnitOfLength,
    UnitOfRatio,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import DuwiDeviceEntity
from .const import DOMAIN, HOUSE_NO, MANUFACTURER, SIGNAL_DEVICE_UPDATE
from .duwi_iot.duwi_manager import DuwiManager

_LOGGER = logging.getLogger(__name__)

SENSOR_DEFS: dict[str, tuple[SensorDeviceClass | None, SensorStateClass | None, str, str]] = {
    "voltage": (SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "V", "电压"),
    "current": (SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT, "A", "电流"),
    "activepower": (SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "W", "有功功率"),
    "electricity": (SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "kWh", "电量"),
    "ac_real_temp": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS, "温度"),
    "ac_real_humidity": (SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT, PERCENTAGE, "湿度"),
    "fh_real_temp": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS, "温度"),
    "fh_real_humidity": (SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT, PERCENTAGE, "湿度"),
    "fa_real_humidity": (SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT, PERCENTAGE, "湿度"),
    "fa_real_temp": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS, "温度"),
    "tc_real_temp": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS, "温度"),
    "tc_real_humidity": (SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT, PERCENTAGE, "湿度"),
    "temp_value": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS, "温度"),
    "humidity_value": (SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT, PERCENTAGE, "湿度"),
    "bright_value": (SensorDeviceClass.ILLUMINANCE, SensorStateClass.MEASUREMENT, LIGHT_LUX, "光照度"),
    "hcho_value": (None, SensorStateClass.MEASUREMENT, UnitOfDensity.MILLIGRAMS_PER_CUBIC_METER, "甲醛"),
    "pm25_value": (SensorDeviceClass.PM25, SensorStateClass.MEASUREMENT, UnitOfDensity.MICROGRAMS_PER_CUBIC_METER, "PM2.5"),
    "co2_value": (SensorDeviceClass.CO2, SensorStateClass.MEASUREMENT, UnitOfRatio.PARTS_PER_MILLION, "二氧化碳"),
    "iaq_value": (SensorDeviceClass.AQI, SensorStateClass.MEASUREMENT, None, "空气质量IAQ"),
    "co_value": (SensorDeviceClass.CO, SensorStateClass.MEASUREMENT, UnitOfRatio.PARTS_PER_MILLION, "一氧化碳"),
    "tvoc_value": (SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS, SensorStateClass.MEASUREMENT, UnitOfDensity.MILLIGRAMS_PER_CUBIC_METER, "TVOC"),
    "pm10_value": (SensorDeviceClass.PM10, SensorStateClass.MEASUREMENT, UnitOfDensity.MICROGRAMS_PER_CUBIC_METER, "PM10"),
    "distance": (SensorDeviceClass.DISTANCE, SensorStateClass.MEASUREMENT, UnitOfLength.METERS, "距离"),
}

SENSOR_DEVICE_TYPES: dict[str, list[str]] = {
    "1-001": ["voltage", "current", "activepower", "electricity"],
    "1-002": ["voltage", "current", "activepower", "electricity"],
    "1-003": ["voltage", "current", "activepower", "electricity"],
    "7-001": ["temp_value"],
    "7-002": ["humidity_value"],
    "7-003": ["bright_value"],
    "7-004": ["hcho_value"],
    "7-005": ["pm25_value"],
    "7-006": ["co2_value"],
    "7-007": ["iaq_value"],
    "7-008-003": ["bright_value"],
    "7-008-004": ["bright_value"],
    "7-008-005": ["bright_value", "distance"],
    "7-008-006": ["bright_value"],
    "7-009-003": ["bright_value"],
    "7-009-011": ["bright_value"],
    "7-010": ["co_value"],
    "7-011": ["tvoc_value"],
    "7-012-001": ["temp_value", "humidity_value", "tvoc_value", "pm25_value", "hcho_value", "co2_value", "pm10_value"],
    "7-012-002": ["co_value"],
    "7-013-001": ["bright_value"],
    "7-013-002": ["bright_value"],
    "7-013-003": ["bright_value"],
    "7-013-004": ["bright_value"],
    "7-013-005": ["bright_value"],
    "7-016-001": ["temp_value", "humidity_value"],
    "5-001": ["ac_real_temp"],
    "5-002": ["fh_real_humidity", "fh_real_temp"],
    "5-003": ["fa_real_humidity", "fa_real_temp"],
    "5-005": ["tc_real_temp", "tc_real_humidity"],
    "5-003-002":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-003":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-004":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-010":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-020":{"fa_real_humidity", "fa_real_temp","pm25_value"},
    "5-003-021":{"fa_real_humidity", "fa_real_temp","co2_value"},
    "5-003-023":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-025":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-029":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-030":{"fa_real_humidity", "fa_real_temp","pm25_value"},
    "5-003-031":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-032":{"fa_real_humidity", "fa_real_temp","pm25_value"},
    "5-003-033":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-036":{"fa_real_humidity", "fa_real_temp","pm25_value"},
    "5-003-041":{"fa_real_humidity", "fa_real_temp","pm25_value"},
    "5-003-045":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-054":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-059":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-067":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-071":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-072":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-075":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-081":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
    "5-003-083":{"fa_real_humidity", "fa_real_temp","co2_value","pm25_value"},
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Duwi Home sensor platform."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    if not data:
        return

    duwi_manager: DuwiManager | None = data.get("DuwiManager")
    devices: list[dict[str, Any]] = data.get("devices", [])
    if not duwi_manager or not devices:
        return

    entities: list[DuwiSensor] = []
    for device in devices:
        if device.get("is_use", 0) != 1:
            continue
        value: dict[str, Any] = device.get("value", {}) or {}
        device_type = device.get("device_type_no", "")
        device_sub_type = device.get("device_sub_type_no", "")
        sensor_keys = SENSOR_DEVICE_TYPES.get(device_sub_type) or SENSOR_DEVICE_TYPES.get(device_type)
        if sensor_keys is None:
            continue

        for value_key in sensor_keys:
            if value_key in value:
                device_class, state_class, unit, name = SENSOR_DEFS[value_key]
                entities.append(
                    DuwiSensor(duwi_manager, entry.data.get(HOUSE_NO), device, value_key, device_class, state_class, unit, name)
                )

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d sensor entities", len(entities))


class DuwiSensor(DuwiDeviceEntity, SensorEntity):
    """Representation of a Duwi Home sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        duwi_manager: DuwiManager,
        house_no: str,
        device_data: dict[str, Any],
        value_key: str,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
        unit: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(house_no, device_data)
        self._duwi_manager = duwi_manager
        self._value_key = value_key

        self._attr_unique_id = f"duwi_sensor_{self._duwi_device_no}_{value_key}"
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit

        self._attr_native_value = self._duwi_device_value.get(value_key)
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
        if data.get("deviceNo") != self._duwi_device_no:
            return

        self._update_device_value(data)

        if self._value_key in data:
            self._attr_native_value = data[self._value_key]

        if "online" in data:
            self._attr_available = bool(data["online"])
        else:
            self._attr_available = True

        self.async_write_ha_state()
