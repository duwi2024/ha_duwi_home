"""Support for Duwi Smart devices."""
import asyncio
import functools
import time
from typing import Any, NamedTuple

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, __version__
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    storage,
)
from homeassistant.helpers.dispatcher import dispatcher_send

from .const import (
    _LOGGER,
    ACCESS_TOKEN,
    ADDRESS,
    APP_KEY,
    APP_SECRET,
    APP_VERSION,
    CLIENT,
    CLIENT_MODEL,
    CLIENT_VERSION,
    CONF_TOKEN_INFO,
    DOMAIN,
    DUWI_DISCOVERY_NEW,
    DUWI_HA_ACCESS_TOKEN,
    DUWI_HA_SIGNAL_UPDATE_ENTITY,
    DUWI_SCENE_UPDATE,
    HOUSE_KEY,
    HOUSE_NAME,
    HOUSE_NO,
    MANUFACTURER,
    PASSWORD,
    PHONE,
    REFRESH_TOKEN,
    SUPPORTED_PLATFORMS,
    WS_ADDRESS,
)
from .duwi_lan_sdk.service.lan_process import LanProcess
from .duwi_repository_sdk.model.device import Device
from .duwi_smarthome_sdk.base.customer_api import CustomerApi, SharingTokenListener
from .duwi_smarthome_sdk.base.customer_device import CustomerDevice
from .duwi_smarthome_sdk.base.customer_scene import CustomerScene
from .duwi_smarthome_sdk.base.manager import Manager, SharingDeviceListener

type DuwiConfigEntry = ConfigEntry[HomeAssistantDuwiData]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(domain=DOMAIN)


class HomeAssistantDuwiData(NamedTuple):
    """Duwi data stored in the Home Assistant data object."""

    manager: Manager
    listener: SharingDeviceListener


async def async_setup(hass: HomeAssistant, hass_config: dict) -> bool:
    """Set up the Duwi Smart Devices integration."""

    # Check for existing config entries for this integration
    hass.data.setdefault(DOMAIN, {})
    if not hass.config_entries.async_entries(DOMAIN):
        # No entries found, initiate the configuration flow
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={}
            )
        )

    # Setup was successful
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DuwiConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    token_listener = TokenListener(hass, entry)
    # 全局lp 只构造一个
    lp = hass.data[DOMAIN].get("lp") if hass.data[DOMAIN].get("lp") else LanProcess()
    manager: Manager = Manager(
        id=entry.entry_id,
        customer_api=CustomerApi(
            address=entry.data[ADDRESS],
            ws_address=entry.data[WS_ADDRESS],
            app_key=entry.data[APP_KEY],
            app_secret=entry.data[APP_SECRET],
            house_no=entry.data[HOUSE_NO],
            house_name=entry.data[HOUSE_NAME],
            access_token=entry.data[ACCESS_TOKEN],
            refresh_token=entry.data[REFRESH_TOKEN],
            client_version=CLIENT_VERSION,
            client_model=CLIENT_MODEL,
            app_version=__version__,
        ),
        house_key=entry.data.get(HOUSE_KEY),
        token_listener=token_listener,
        lp=lp
    )
    # 保留原先的名称
    lp.add_message_listener(manager.handle_lan_message)
    # start方法只执行一次
    if not hass.data[DOMAIN].get("lp"):
        lp.start()
        hass.data[DOMAIN]["lp"] = lp
    # Cleanup device registry
    login_status = await manager.init_manager(entry.data["phone"], entry.data["password"])
    # 登录失败报错警告
    _LOGGER.warning("login_status %s", login_status)
    if not login_status:
        raise ConfigEntryAuthFailed("用户身份认证失败,请尝试重载集成或者重新添加")

    # 抓取设备
    is_online = await manager.update_device_cache()
    listener = DeviceListener(hass, manager)
    manager.add_device_listener(listener)
    ids = []
    if hass.data[DOMAIN].get(entry.entry_id) is not None:
        old_manager = hass.data[DOMAIN].get(entry.entry_id, {}).manager
        ids = await compare_manager(old_manager, manager, None)
    else:
        devices = manager.db_repository.list_entities(Device)
        ids = await compare_manager(None, manager, devices)
    if is_online:
        await manager.save_data_to_local()
    hass.data[DOMAIN][entry.entry_id] = HomeAssistantDuwiData(manager=manager, listener=listener)
    # 清除不合适的设备
    await cleanup_device_registry(hass, ids)
    hass.data[DOMAIN].setdefault("existing_house", []).append(entry.data[HOUSE_NO])
    hass.loop.create_task(manager.is_connected())
    # 开启全局的ws监听
    if is_online:
        await hass.async_create_task(manager.ws.reconnect())
    else:
        hass.loop.create_task(manager.ws.reconnect())

    hass.loop.create_task(manager.ws.listen())
    hass.loop.create_task(manager.ws.keep_alive())

    await hass.config_entries.async_forward_entry_setups(
        entry, SUPPORTED_PLATFORMS
    )
    return True


async def compare_manager(old_manager: Manager | None, new_manager: Manager, devices: list[Device] | None) -> list:
    ids = []
    if not old_manager:
        # _LOGGER.debug("old_manager is None")
        for d in devices:
            d2 = new_manager.device_map.get(d.device_no)
            if not d2:
                # _LOGGER.debug("device not in new manager %s", d.device_no)
                continue
            # 如果区域不一样的,以云端新的区域为主,设备类型也是,如果类型不一样就返回设备的id
            if d.room_no != d2.room_no or d.device_sub_type_no != d2.device_sub_type_no:
                ids.append(d.device_no)
        return ids
    # 如果区域不一样的,以云端新的区域为主,设备类型也是,如果类型不一样就返回设备的id
    for dev_id in old_manager.device_map:
        d1 = old_manager.device_map.get(dev_id)
        d2 = new_manager.device_map.get(dev_id)
        if not d2:
            # _LOGGER.debug("device not in new manager %s", dev_id)
            continue
        if d1.room_no != d2.room_no or d1.device_sub_type_no != d2.device_sub_type_no:
            ids.append(dev_id)
    return ids


async def cleanup_device_registry(hass: HomeAssistant, device_ids: list) -> None:
    """Remove deleted device registry entry if there are no remaining entities."""
    # _LOGGER.debug("device_ids %s", device_ids)
    device_registry = dr.async_get(hass)
    for dev_id, device_entry in list(device_registry.devices.items()):
        for item in device_entry.identifiers:
            if item[0] == DOMAIN:
                # 准备移除duwi的设备
                read_to_remove = True
                for v in hass.data[DOMAIN].values():
                    if hasattr(v, 'manager'):
                        # 如果设备编号是在这个
                        if item[1] in v.manager.device_map:
                            read_to_remove = False
                            break
                # _LOGGER.debug("read_to_remove %s", read_to_remove)
                # _LOGGER.debug("dev_id in device_ids %s", item[1] in device_ids)

                if read_to_remove or item[1] in device_ids:
                    device_name = device_entry.name
                    device_registry.async_remove_device(dev_id)


async def async_unload_entry(hass: HomeAssistant, entry: DuwiConfigEntry) -> bool:
    """Unloading the Duwi platforms."""
    # Attempt to unload all platforms associated with the entry.
    await hass.data[DOMAIN][entry.entry_id].manager.unload()
    house_no = entry.data.get(HOUSE_NO)
    if house_no in hass.data[DOMAIN].get("existing_house"):
        hass.data[DOMAIN]["existing_house"].remove(house_no)

    if lp := hass.data[DOMAIN].get("lp"):
        _LOGGER.info("clear_hosts from async_unload_entry")
        lp.clear_hosts(entry.entry_id)

    return await hass.config_entries.async_unload_platforms(
        entry, SUPPORTED_PLATFORMS
    )


async def async_remove_entry(hass: HomeAssistant, entry: DuwiConfigEntry) -> bool:
    """Remove a config entry.

    This will revoke the credentials from Duwi.
    """
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await cleanup_device_registry(hass, manager.device_map.keys())
    await manager.unload(True)
    hass.data[DOMAIN].pop(entry.entry_id)

    house_no_list: [] = hass.data[DOMAIN].get("existing_house")
    if lp := hass.data[DOMAIN].get("lp"):
        _LOGGER.info("clear_hosts from async_remove_entry")
        lp.clear_hosts(entry.entry_id)
        if len(house_no_list) == 0:
            # last entry removed
            _LOGGER.info("last entry removed from async_remove_entry")
            lp.stop()
            hass.data[DOMAIN].pop("lp")

    return await hass.config_entries.async_unload_platforms(
        entry, SUPPORTED_PLATFORMS
    )


class DeviceListener(SharingDeviceListener):
    """Device Update Listener."""

    def __init__(
            self,
            hass: HomeAssistant,
            manager: Manager,
    ) -> None:
        """Init DeviceListener."""
        self.hass = hass
        self.manager = manager

    def update_scene(self, scene: CustomerScene):
        dispatcher_send(self.hass, f"{DUWI_SCENE_UPDATE}_{scene.scene_no}")

    def update_device(self, device: CustomerDevice) -> None:
        """Update device status."""
        dispatcher_send(self.hass, f"{DUWI_HA_SIGNAL_UPDATE_ENTITY}_{device.device_no}")

    def add_device(self, device: CustomerDevice) -> None:
        """Add device added listener."""
        # Ensure the device isn't present stale
        self.async_remove_device(device.device_no)

        dispatcher_send(self.hass, DUWI_DISCOVERY_NEW, [device.device_no])

    def remove_device(self, device_no: str) -> None:
        """Add device removed listener."""
        self.hass.add_job(self.async_remove_device, device_no)

    def token_listener(self, token_info: dict[str, Any]) -> None:
        """Add token listener."""

    @callback
    def async_remove_device(self, device_no: str) -> None:
        """Remove device from Home Assistant."""
        device_registry = dr.async_get(self.hass)
        _LOGGER.info("remove device_no %s", device_no)
        device_entry = device_registry.async_get_device(
            identifiers={(DOMAIN, device_no)}
        )
        if device_entry is not None:
            device_registry.async_remove_device(device_entry.id)


class TokenListener(SharingTokenListener):
    """Token listener for upstream token updates."""

    def __init__(
            self,
            hass: HomeAssistant,
            entry: DuwiConfigEntry,
    ) -> None:
        """Init TokenListener."""
        self.hass = hass
        self.entry = entry

    def update_token(self, is_refresh: bool, token_info: dict[str, Any] = None) -> None:
        """Update token info in config entry."""
        _LOGGER.info("Update token: %s %s", is_refresh, token_info)
        if is_refresh:
            data = {
                PHONE: self.entry.data[PHONE],
                PASSWORD: self.entry.data[PASSWORD],
                HOUSE_KEY: self.entry.data[HOUSE_KEY],
                ADDRESS: self.entry.data[ADDRESS],
                WS_ADDRESS: self.entry.data[WS_ADDRESS],
                APP_KEY: self.entry.data[APP_KEY],
                APP_SECRET: self.entry.data[APP_SECRET],
                HOUSE_NO: self.entry.data[HOUSE_NO],
                HOUSE_NAME: self.entry.data[HOUSE_NAME],
                ACCESS_TOKEN: token_info[ACCESS_TOKEN],
                REFRESH_TOKEN: token_info[REFRESH_TOKEN],
            }
        else:
            raise ConfigEntryAuthFailed("刷新token失败,请尝试重载集成或者重新添加")

        @callback
        def async_update_entry() -> None:
            """Update config entry."""
            self.hass.config_entries.async_update_entry(self.entry, data=data)

        self.hass.add_job(async_update_entry)

    async def error_notification(self):  # noqa: D102
        await self.hass.config_entries.async_reload(self.entry.entry_id)

        await self.hass.components.persistent_notification.async_create(
                "账户或密码错误，导致授权失败,请尝试检查并重新加载集成!",
                title="Duwi(BETA)集成故障"
            )

def debounce(wait):
    def decorator(fn):
        last_call = 0
        call_pending = None

        @functools.wraps(fn)
        async def debounced(*args, **kwargs):
            nonlocal last_call, call_pending

            now = time.time()
            if now - last_call < wait:
                if call_pending:
                    call_pending.cancel()
                call_pending = asyncio.create_task(asyncio.sleep(wait - (now - last_call)))
                await call_pending

            last_call = time.time()
            return await fn(*args, **kwargs)

        return debounced

    return decorator
