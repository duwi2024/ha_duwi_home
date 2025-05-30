from typing import Any, Union

from homeassistant.components.climate import ClimateEntityDescription, ClimateEntity, HVACMode, ClimateEntityFeature, \
    HVACAction
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .duwi_smarthome_sdk.base.manager import Manager
from .duwi_smarthome_sdk.base.customer_device import CustomerDevice
from . import DuwiConfigEntry

from .base import DuwiEntity
from .const import DUWI_DISCOVERY_NEW, DPCode, DOMAIN, _LOGGER

SUPPORT_FLAGS = ClimateEntityFeature(0)

CLIMATE: dict[str, tuple[ClimateEntityDescription, ...]] = {
    "ac": (
        ClimateEntityDescription(
            key=DPCode.AC,
            name="",
            translation_key="duwi_climate",
        ),
    ),
    "fa": (
        ClimateEntityDescription(
            key=DPCode.FA,
            name="",
            translation_key="duwi_climate",
        ),
    ),
    "fh": (
        ClimateEntityDescription(
            key=DPCode.FH,
            name="",
            translation_key="duwi_climate",
        ),
    ),
    "hp": (
        ClimateEntityDescription(
            key=DPCode.HP,
            name="",
            translation_key="duwi_climate",
        ),
    ),
    "tc": (
        ClimateEntityDescription(
            key=DPCode.TC,
            name="",
            translation_key="duwi_climate",
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
        entities: list[DuwiClimateEntity] = []
        for device_id in device_ids:
            device = hass_data.manager.device_map.get(device_id)
            if not device:
                # _LOGGER.warning("Device not found in device_map: %s", device_id)
                continue
            if descriptions := CLIMATE.get(device.value.get("havc", {}).get("type")):
                entities.extend(
                    DuwiClimateEntity(device, hass_data.manager, description)
                    for description in descriptions
                )

        async_add_entities(entities)

    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, DUWI_DISCOVERY_NEW, async_discover_device)
    )


class DuwiClimateEntity(DuwiEntity, ClimateEntity):
    """Duwi Switch Device."""
    HVAC_MODE_TO_STR = {
        HVACMode.AUTO: "auto",
        HVACMode.COOL: "cold",
        HVACMode.HEAT: "hot",
        HVACMode.DRY: "wet",
        HVACMode.FAN_ONLY: "fan",
        HVACMode.OFF: "off",
    }

    DEFAULT_HVAC_MODE = {
        DPCode.FA: HVACMode.FAN_ONLY,
        DPCode.HP: HVACMode.HEAT,
        DPCode.FH: HVACMode.HEAT,
    }

    STR_TO_HVAC_MODE = {v: k for k, v in HVAC_MODE_TO_STR.items()}

    def __init__(
            self,
            device: CustomerDevice,
            device_manager: Manager,
            description: ClimateEntityDescription,
    ) -> None:
        """Init DuwiHaSwitch."""
        super().__init__(device, device_manager)
        self.entity_description = description
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_unique_id = f"{super().unique_id}{description.key}"
        havc = self.device.value.get("havc", {})
        self._attr_supported_features = (
                SUPPORT_FLAGS
                | ClimateEntityFeature.TURN_OFF
                | ClimateEntityFeature.TURN_ON
                | (ClimateEntityFeature.TARGET_TEMPERATURE if havc.get(description.key + "_set_temp_range") else 0)
                | (ClimateEntityFeature.TARGET_HUMIDITY if havc.get(description.key + "_set_humidity_range") else 0)
                | (ClimateEntityFeature.PRESET_MODE if self.preset_modes else 0)
                | (ClimateEntityFeature.FAN_MODE if self.fan_modes else 0)
        )

    @property
    def available(self) -> bool:
        """Return if the device is available."""
        v = self.device.value
        for key, value in v.items():
            if key.endswith("_fault_s") and value is True:
                return False
        return self.device.value.get("online", False)

    @property
    def target_temperature_step(self) -> float | None:
        """Return the unit of measurement."""
        havc = self.device.value.get("havc", {})
        return havc.get(self.entity_description.key + "_temp_step")

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        v = self.device.value
        return v.get(self.entity_description.key + "_lock_mode") or v.get(
            self.entity_description.key + "_work_mode")

    @property
    def preset_modes(self) -> list[str] | None:
        """Return the list of available preset modes."""
        havc = self.device.value.get("havc", {})
        return havc.get(self.entity_description.key + "_lock_mode") or havc.get(
            self.entity_description.key + "_work_mode")

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        v = self.device.value
        mode = v.get(self.entity_description.key + "_mode")
        t = v.get(self.entity_description.key + "_set_temp")
        if not mode:
            return t
        temp = v.get(self.entity_description.key + "_" + mode + "_set_temp")
        if not temp:
            temp = v.get(self.entity_description.key + "_set_temp")
        return temp

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.device.value.get(self.entity_description.key + "_real_temp")

    @property
    def target_humidity(self) -> float | None:
        """Return the humidity we try to reach."""
        # return 0.4
        return self.device.value.get(self.entity_description.key + "_set_humidity")

    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        return self.device.value.get(self.entity_description.key + "_real_humidity")

    @property
    def fan_modes(self) -> list[str] | None:
        """Return the list of available fan modes."""
        return self.device.value.get("havc", {}).get(self.entity_description.key + "_wind_speed")

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode."""
        return self.device.value.get(self.entity_description.key + "_wind_speed")

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current operation mode."""
        v = self.device.value
        if v.get(self.entity_description.key + "_switch") == "off":
            return HVACMode.OFF
        mode = self.convert_mode(v.get(self.entity_description.key + "_mode"))
        return mode if mode else self.default_mode()

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available operation modes."""
        mode_key = self.entity_description.key + "_mode"
        raw_modes = self.device.value.get("havc", {}).get(mode_key, [])

        if not raw_modes:
            if self.entity_description.key == DPCode.FA:
                raw_modes.append("fan")
            if self.entity_description.key == DPCode.HP or self.entity_description.key == DPCode.FH:
                raw_modes.append("hot")

        mode = [mode for raw_mode in raw_modes if (mode := self.convert_mode(raw_mode))]
        mode.append(HVACMode.OFF)
        return mode

    @property
    def max_humidity(self) -> float:
        """Return the maximum humidity value."""
        return self.device.value.get("havc", {}).get(self.entity_description.key + "_set_humidity_range", [40, 75])[1]

    @property
    def min_humidity(self) -> float:
        """Return the minimum humidity value."""
        return self.device.value.get("havc", {}).get(self.entity_description.key + "_set_humidity_range", [40, 75])[0]

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature value."""
        v = self.device.value
        h = self.device.value.get("havc", {})
        mode = v.get(self.entity_description.key + "_mode")
        r = 0
        if mode:
            r = h.get(self.entity_description.key + "_set_" + mode + "_temp_range")
            r = r[1] if r else 0
        if not r:
            r = h.get(self.entity_description.key + "_set_temp_range", [5, 45])[1]
        return r

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature value."""
        v = self.device.value
        h = self.device.value.get("havc", {})
        mode = v.get(self.entity_description.key + "_mode")
        r = 0
        if mode:
            r = h.get(self.entity_description.key + "_set_" + mode + "_temp_range")
            r = r[0] if r else 0
        if not r:
            r = h.get(self.entity_description.key + "_set_temp_range", [5, 45])[0]
        return r

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        await self._send_command({self.entity_description.key + "_set_humidity": humidity})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        await self._send_command({self.entity_description.key + "_wind_speed": fan_mode})

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target operation mode."""
        if hvac_mode == HVACMode.OFF:
            await self._send_command({self.entity_description.key + "_switch": "off"})
        else:
            await self._send_command({
                self.entity_description.key + "_mode": self.convert_mode(hvac_mode),
                self.entity_description.key + "_switch": "on",
            })

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if self.entity_description.key == DPCode.FA:
            await self._send_command({self.entity_description.key + "_work_mode": preset_mode})
        else:
            await self._send_command({self.entity_description.key + "_lock_mode": preset_mode})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        target_temp = kwargs.get(ATTR_TEMPERATURE)
        v = self.device.value
        mode = v.get(self.entity_description.key + "_mode")
        t = v.get(self.entity_description.key + "_set_temp")
        if not mode:
            await self._send_command({self.entity_description.key + "_set_temp": target_temp})
            return
        temp = v.get(self.entity_description.key + "_" + mode + "_set_temp")
        # 区分不同模式下面的温度调整指令
        if not temp:
            await self._send_command({self.entity_description.key + "_set_temp": target_temp})
        else:
            await self._send_command({self.entity_description.key + "_" + mode + "_set_temp": target_temp})

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        await self._send_command({self.entity_description.key + "_set_humidity": humidity})

    def convert_mode(self, mode: Union[str, HVACMode]) -> HVACMode | str | None:
        """Convert between string and HVACMode."""
        return self.STR_TO_HVAC_MODE.get(mode) or self.HVAC_MODE_TO_STR.get(mode)

    def default_mode(self) -> HVACMode | str | None:
        """Convert between string and HVACMode."""
        return self.DEFAULT_HVAC_MODE.get(self.entity_description.key)
