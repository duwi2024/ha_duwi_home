from typing import Any

from homeassistant.components.cover import CoverEntityDescription, CoverEntity, CoverEntityFeature, ATTR_TILT_POSITION, \
    ATTR_POSITION
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DuwiConfigEntry
from .base import DuwiEntity
from .const import DUWI_DISCOVERY_NEW, DPCode, DOMAIN, _LOGGER
from .duwi_smarthome_sdk.base.customer_device import CustomerDevice
from .duwi_smarthome_sdk.base.manager import Manager

SUPPORTED_COVER_MODES = {
    DPCode.ROLLER: (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
    ),
    DPCode.SHUTTER: (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
            | CoverEntityFeature.OPEN_TILT
            | CoverEntityFeature.STOP_TILT
            | CoverEntityFeature.CLOSE_TILT
            | CoverEntityFeature.SET_TILT_POSITION
    ),
    DPCode.SHUTTER_2: (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
            | CoverEntityFeature.OPEN_TILT
            | CoverEntityFeature.STOP_TILT
            | CoverEntityFeature.CLOSE_TILT
            | CoverEntityFeature.SET_TILT_POSITION
    ),
}

COVERS: dict[str, tuple[CoverEntityDescription, ...]] = {
    "4-001": (
        CoverEntityDescription(
            key=DPCode.ROLLER,
            name="",
            translation_key="roller",
        ),
    ),
    "4-002": (
        CoverEntityDescription(
            key=DPCode.ROLLER,
            name="",
            translation_key="roller",
        ),
    ),
    "4-005": (
        CoverEntityDescription(
            key=DPCode.ROLLER,
            name="",
            translation_key="roller",
        ),
    ),
    "4-003": (
        CoverEntityDescription(
            key=DPCode.SHUTTER,
            name="",
            translation_key="shutter",
        ),
    ),
    "4-004": (
        CoverEntityDescription(
            key=DPCode.SHUTTER_2,
            name="",
            translation_key="shutter",
        ),
    ),
}

GROUP_COVERS: dict[str, tuple[CoverEntityDescription, ...]] = {
    "Retractable": (
        CoverEntityDescription(
            key=DPCode.ROLLER,
            name="",
            translation_key="roller",
        ),
    ),
    "Roller": (
        CoverEntityDescription(
            key=DPCode.ROLLER,
            name="",
            translation_key="roller",
        ),
    ),
    "Blind": (
        CoverEntityDescription(
            key=DPCode.SHUTTER,
            name="",
            translation_key="roller",
        ),
    ),
    "VerticalBlind": (
        CoverEntityDescription(
            key=DPCode.SHUTTER_2,
            name="",
            translation_key="roller",
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
        entities: list[DuwiCoverEntity] = []
        for device_id in device_ids:
            device = hass_data.manager.device_map.get(device_id)
            if not device:
                # _LOGGER.warning("Device not found in device_map: %s", device_id)
                continue
            if descriptions := COVERS.get(device.device_type_no) or GROUP_COVERS.get(device.device_group_type):
                entities.extend(
                    DuwiCoverEntity(device, hass_data.manager, description)
                    for description in descriptions
                )

        async_add_entities(entities)

    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, DUWI_DISCOVERY_NEW, async_discover_device)
    )


class DuwiCoverEntity(DuwiEntity, CoverEntity):
    """Duwi Switch Device."""

    def __init__(
            self,
            device: CustomerDevice,
            device_manager: Manager,
            description: CoverEntityDescription,
    ) -> None:
        """Init DuwiHaSwitch."""
        super().__init__(device, device_manager)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}{description.key}"
        self._attr_supported_features = SUPPORTED_COVER_MODES.get(description.key)
        tilt_position = self.device.value.get("angle_degree", 0) or self.device.value.get("light_angle", 0)
        self._is_tilt_over_90 = tilt_position > 90

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of the roller."""
        return self.device.value.get("control_percent", 0)

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the current tilt position of the roller."""
        tilt_position = self.device.value.get("angle_degree", 0) or self.device.value.get("light_angle", 0)
        if tilt_position == 90:
            self._is_tilt_over_90 = not self._is_tilt_over_90
        if self._is_tilt_over_90 == 90:
            tilt_position = 180 - tilt_position
        tilt_position = 180 - tilt_position if tilt_position > 90 else tilt_position
        return int(tilt_position / 90 * 100)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        return self.current_cover_position == 0

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the roller."""
        await self._send_command({"control": "close"})

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Close the roller."""
        t = 180 if self._is_tilt_over_90 else 0
        cmd = ""
        if self.entity_description.key == DPCode.SHUTTER:
            cmd = "angle_degree"
        elif self.entity_description.key == DPCode.SHUTTER_2:
            cmd = "light_angle"
        await self._send_command({cmd: t})

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the roller."""
        await self._send_command({"control": "open"})

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Open the roller."""
        cmd = ""
        if self.entity_description.key == DPCode.SHUTTER:
            cmd = "angle_degree"
        elif self.entity_description.key == DPCode.SHUTTER_2:
            cmd = "light_angle"
        await self._send_command({cmd: 90})
        self._is_tilt_over_90 = not self._is_tilt_over_90

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the roller to a specific position."""
        position = kwargs[ATTR_POSITION]
        await self._send_command({"control_percent": position})

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Move the roller to a specific position."""
        tilt_position = kwargs[ATTR_TILT_POSITION]
        t = tilt_position / 100 * 90
        if self._is_tilt_over_90:
            t = 180 - t
        cmd = ""
        if self.entity_description.key == DPCode.SHUTTER:
            cmd = "angle_degree"
        elif self.entity_description.key == DPCode.SHUTTER_2:
            cmd = "light_angle"
        await self._send_command(
            {cmd: int(t)})

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the roller."""
        await self._send_command({"control": "stop"})

    # async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
    #     """Stop the roller."""
    #     await self._send_command({"control": "stop"})
