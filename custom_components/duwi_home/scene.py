"""Support for Duwi Home scenes."""
import logging
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import DuwiSceneEntity
from .const import DOMAIN, HOUSE_NO
from .duwi_iot.duwi_manager import DuwiManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Duwi Home scene platform."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    if not data:
        return

    duwi_manager: DuwiManager | None = data.get("DuwiManager")
    scenes: list[dict[str, Any]] = data.get("scenes", [])
    if not duwi_manager:
        return
    if not scenes:
        return

    house_no = entry.data.get(HOUSE_NO)
    entities: list[DuwiScene] = [
        DuwiScene(duwi_manager, house_no, scene_data)
        for scene_data in scenes
        if scene_data.get("is_use") and scene_data.get("is_manual_execute")
    ]

    if entities:
        async_add_entities(entities)


class DuwiScene(DuwiSceneEntity, Scene):
    """Representation of a Duwi Home scene."""

    def __init__(
        self,
        duwi_manager: DuwiManager,
        house_no: str,
        scene_data: dict[str, Any],
    ) -> None:
        """Initialize the scene."""
        super().__init__(house_no, scene_data)
        self._duwi_manager = duwi_manager
        self._attr_unique_id = f"duwi_scene_{self._duwi_scene_no}"
        self._attr_name = self._duwi_scene_name

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        try:
            await self._duwi_manager.operate_scene(self._duwi_scene_no)
        except Exception:
            _LOGGER.exception(
                "Error activating scene %s (%s)",
                self._duwi_scene_no, self._attr_name,
            )
