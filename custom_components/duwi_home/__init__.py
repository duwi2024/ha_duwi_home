"""Duwi Home Integration."""
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    floor_registry as fr,
)

from .const import (
    ACCESS_TOKEN,
    ACCESS_TOKEN_EXPIRE_TIME,
    APP_KEY,
    APP_SECRET,
    DOMAIN,
    FIRST_INIT,
    HOUSE_LAN_SECRET_KEY,
    HOUSE_NAME,
    HOUSE_NO,
    REFRESH_TOKEN,
    REFRESH_TOKEN_EXPIRE_TIME,
    SERVICE_REFRESH_DEVICES,
)
from .duwi_iot.db.duwi_database import DuwiDatabase
from .duwi_iot.duwi_manager import DuwiManager
from .duwi_iot.smarthome.duwi_client import UpdateTokenListener

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["switch", "sensor", "binary_sensor", "light", "cover", "climate", "media_player", "scene"]

class DuwiTokenRefreshListener(UpdateTokenListener):
    """Listener for Duwi token refresh events."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the listener."""
        self._hass = hass
        self._entry = entry

    async def on_token_refreshed(self, access_token: str, refresh_token: str, access_token_expire_time: int, refresh_token_expire_time: int):
        """Handle token refresh event."""
        _LOGGER.info("Token refreshed for house: %s", self._entry.data.get(HOUSE_NAME))

        new_data = self._entry.data.copy()
        new_data[ACCESS_TOKEN] = access_token
        new_data[REFRESH_TOKEN] = refresh_token
        new_data[ACCESS_TOKEN_EXPIRE_TIME] = access_token_expire_time
        new_data[REFRESH_TOKEN_EXPIRE_TIME] = refresh_token_expire_time

        await self._hass.config_entries.async_update_entry(self._entry, data=new_data)

async def async_sync_floors_and_rooms_to_ha(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Sync duwi floors and rooms to HA floor and area registries."""
    data = hass.data[DOMAIN][entry.entry_id]
    floors = data.get("floors", [])
    rooms = data.get("rooms", [])
    devices = data.get("devices", [])

    floor_reg = fr.async_get(hass)
    area_reg = ar.async_get(hass)
    dev_reg = dr.async_get(hass)

    floor_no_to_floor_id: dict[str, str] = {}

    for floor in floors:
        floor_no = floor.get("floor_no")
        floor_name = floor.get("floor_name")
        if not floor_no or not floor_name:
            continue

        alias = f"{DOMAIN}:{floor_no}"
        ha_floor = None

        for f in floor_reg.async_list_floors():
            if alias in f.aliases:
                ha_floor = f
                break

        if not ha_floor:
            existing = floor_reg.async_get_floor_by_name(floor_name)
            if existing:
                ha_floor = floor_reg.async_update(
                    existing.floor_id, aliases=existing.aliases | {alias}
                )
            else:
                ha_floor = floor_reg.async_create(floor_name, aliases={alias})

        if ha_floor:
            floor_no_to_floor_id[floor_no] = ha_floor.floor_id

    room_no_to_area_id: dict[str, str] = {}

    for room in rooms:
        room_no = room.get("room_no")
        room_name = room.get("room_name")
        room_floor_no = room.get("floor_no")
        if not room_no or not room_name:
            continue

        floor_id = floor_no_to_floor_id.get(room_floor_no)
        alias = f"{DOMAIN}:{room_no}"
        ha_area = None

        for a in area_reg.async_list_areas():
            if alias in a.aliases:
                ha_area = a
                break

        if not ha_area:
            existing = area_reg.async_get_area_by_name(room_name)
            if existing:
                ha_area = area_reg.async_update(
                    existing.id, aliases=existing.aliases | {alias}
                )
            else:
                ha_area = area_reg.async_create(
                    room_name, aliases={alias}, floor_id=floor_id
                )

        if ha_area:
            room_no_to_area_id[room_no] = ha_area.id

    for device in devices:
        device_no = device.get("device_no")
        room_no = device.get("room_no")
        if not device_no or not room_no:
            continue

        area_id = room_no_to_area_id.get(room_no)
        if not area_id:
            continue

        ha_device = dev_reg.async_get_device({(DOMAIN, device_no)})
        if ha_device:
            dev_reg.async_update_device(ha_device.id, area_id=area_id)

async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up Duwi Home integration."""
    hass.data.setdefault(DOMAIN, {})

    async def async_refresh_devices_service(call: ServiceCall) -> None:
        """Handle the refresh devices service call."""
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id in hass.data[DOMAIN]:
                data = hass.data[DOMAIN][entry.entry_id]
                duwi_manager: DuwiManager | None = data.get("DuwiManager")
                if duwi_manager:
                    _LOGGER.info("Manually refreshing devices for %s", entry.data.get(HOUSE_NAME))
                    await duwi_manager.start()
                    await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(DOMAIN, SERVICE_REFRESH_DEVICES, async_refresh_devices_service)

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Duwi Home from a config entry."""

    # Initialize DuwiManager
    duwi_manager = DuwiManager(
        entry.data.get(APP_KEY),
        entry.data.get(APP_SECRET),
        entry.data.get(ACCESS_TOKEN),
        entry.data.get(ACCESS_TOKEN_EXPIRE_TIME),
        entry.data.get(REFRESH_TOKEN),
        entry.data.get(REFRESH_TOKEN_EXPIRE_TIME),
        entry.data.get(HOUSE_NO),
        entry.data.get(HOUSE_LAN_SECRET_KEY),
        hass,
        entry,
        DuwiTokenRefreshListener(hass, entry),
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "DuwiManager": duwi_manager,
    }

    start_success = await duwi_manager.start()
    if not start_success:
        _LOGGER.error("Failed to start DuwiManager")
        raise ConfigEntryAuthFailed(
            "Token expired and could not be refreshed, please re-authenticate"
        )

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if hass.state.value == CoreState.running or entry.data.get(FIRST_INIT, False):
        _LOGGER.debug("sync floors and rooms to HA")
        await async_sync_floors_and_rooms_to_ha(hass, entry)
        if entry.data.get(FIRST_INIT, False):
            # 持久化清除 FIRST_INIT 标记
            new_data = entry.data.copy()
            new_data[FIRST_INIT] = False
            hass.config_entries.async_update_entry(entry, data=new_data)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if entry.entry_id not in hass.data[DOMAIN]:
        return True

    data = hass.data[DOMAIN][entry.entry_id]

    # Stop DuwiManager
    duwi_manager = data.get("DuwiManager")
    if duwi_manager:
        await duwi_manager.stop()

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Duwi Home unloaded for house: %s", entry.data.get(HOUSE_NAME))

    return unload_ok

async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove a config entry."""
    house_name = entry.data.get(HOUSE_NAME)
    house_no = entry.data.get(HOUSE_NO)

    _LOGGER.info("Duwi Home removed for house: %s", house_name)

    # Delete all data from SQLite database for this house
    if house_no:
        db_path = hass.config.path("duwi_home")
        db = DuwiDatabase(db_path)
        try:
            await db.connect()
            deleted_count = await db.delete_all_by_house_no(house_no)
            _LOGGER.info(
                "Deleted %d rows from database for house: %s",
                deleted_count,
                house_name,
            )
        except Exception:
            _LOGGER.exception(
                "Failed to delete database data for house: %s", house_name
            )
        finally:
            await db.close()

    return True
