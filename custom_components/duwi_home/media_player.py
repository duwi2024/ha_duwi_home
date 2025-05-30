import math
from datetime import datetime
from typing import Any, Optional

from homeassistant.components.media_player import MediaPlayerEntityDescription, MediaPlayerEntityFeature, \
    MediaPlayerEntity, RepeatMode, MediaPlayerState, MediaType
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
import homeassistant.util.dt as dt_util

from .duwi_smarthome_sdk.base.manager import Manager
from .duwi_smarthome_sdk.base.customer_device import CustomerDevice
from . import DuwiConfigEntry

from .base import DuwiEntity
from .const import DUWI_DISCOVERY_NEW, DPCode, DOMAIN, _LOGGER

SUPPORTED_MEDIA_PLAYER_MODES = {
    DPCode.HUA_ERSI_MUSIC: (
            MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.REPEAT_SET
            | MediaPlayerEntityFeature.SEEK
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
    ),
    DPCode.XIANG_WANG_MUSIC_S7_MINI_3S: (
            MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.REPEAT_SET
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
    ),
    DPCode.XIANG_WANG_MUSIC_S8: (
            MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.REPEAT_SET
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
    ),
    DPCode.SHENG_BI_KE_MUSIC: (
            MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.REPEAT_SET
            | MediaPlayerEntityFeature.SEEK
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
    ),
    DPCode.BO_SHENG_MUSIC: (
            MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.REPEAT_SET
            | MediaPlayerEntityFeature.SEEK
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    ),
    DPCode.YOU_DA_MUSIC: (
            MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.REPEAT_SET
            | MediaPlayerEntityFeature.SEEK
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
    )
}

MEDIA_PLAY: dict[str, tuple[MediaPlayerEntityDescription, ...]] = {
    "8-001-001": (
        MediaPlayerEntityDescription(
            key=DPCode.HUA_ERSI_MUSIC,
            name="",
            translation_key=DPCode.HUA_ERSI_MUSIC,
        ),
    ),
    "8-001-002": (
        MediaPlayerEntityDescription(
            key=DPCode.XIANG_WANG_MUSIC_S7_MINI_3S,
            name="",
            translation_key=DPCode.XIANG_WANG_MUSIC_S7_MINI_3S,
        ),
    ),
    "8-001-003": (
        MediaPlayerEntityDescription(
            key=DPCode.XIANG_WANG_MUSIC_S8,
            name="",
            translation_key=DPCode.XIANG_WANG_MUSIC_S8,
        ),
    ),
    "8-001-004": (
        MediaPlayerEntityDescription(
            key=DPCode.SHENG_BI_KE_MUSIC,
            name="",
            translation_key=DPCode.SHENG_BI_KE_MUSIC,
        ),
    ),
    "8-001-005": (
        MediaPlayerEntityDescription(
            key=DPCode.BO_SHENG_MUSIC,
            name="",
            translation_key=DPCode.BO_SHENG_MUSIC,
        ),
    ),
    "8-001-007": (
        MediaPlayerEntityDescription(
            key=DPCode.YOU_DA_MUSIC,
            name="",
            translation_key=DPCode.YOU_DA_MUSIC,
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
        entities: list[DuwiMediaPlayerEntity] = []
        for device_id in device_ids:
            device = hass_data.manager.device_map.get(device_id)
            if not device:
                _LOGGER.warning("Device not found in device_map: %s", device_id)
                continue
            if not device:
                _LOGGER.warning("Device not found in device_map: %s", device_id)
                continue
            if descriptions := MEDIA_PLAY.get(device.device_sub_type_no):
                entities.extend(
                    DuwiMediaPlayerEntity(device, hass_data.manager, description)
                    for description in descriptions
                )

        async_add_entities(entities)

    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, DUWI_DISCOVERY_NEW, async_discover_device)
    )


class DuwiMediaPlayerEntity(DuwiEntity, MediaPlayerEntity):
    """Duwi Switch Device."""

    def __init__(
            self,
            device: CustomerDevice,
            device_manager: Manager,
            description: MediaPlayerEntityDescription,
    ) -> None:
        """Init DuwiHaSwitch."""
        super().__init__(device, device_manager)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}{description.key}"
        self._attr_supported_features = SUPPORTED_MEDIA_PLAYER_MODES.get(description.key)
        if description.key == DPCode.BO_SHENG_MUSIC or description.key == DPCode.XIANG_WANG_MUSIC_S8 or description.key == DPCode.YOU_DA_MUSIC:
            self._max_volume = 100
        elif description.key == DPCode.HUA_ERSI_MUSIC or description.key == DPCode.XIANG_WANG_MUSIC_S7_MINI_3S:
            self._max_volume = 15
        elif description.key == DPCode.SHENG_BI_KE_MUSIC:
            self._max_volume = 19

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media."""
        v = self.device.value
        return v.get("audio_full_info", v.get("audio_info", {})).get("pic_url", "")

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media, music track only."""
        v = self.device.value
        singer = v.get("audio_full_info", v.get("audio_info", {}), ).get("singer")
        singer_name = (
            singer[0].get("name", "")
            if isinstance(singer, list) and singer and len(singer) > 0
            else singer
        )
        return singer_name

    @property
    def media_title(self) -> str | None:
        """Title of current playing media, music track only."""
        v = self.device.value
        song_name = v.get("audio_full_info", {}).get("song_name") or v.get("audio_info", {}).get("name", "")
        return song_name

    @property
    def volume_level(self) -> float | None:
        """Image url of current playing media."""
        return self.device.value.get("volume", 0) / self._max_volume

    @property
    def is_volume_muted(self) -> bool | None:
        """Return true if volume is muted."""
        return self.device.value.get("mute", "off") == "on"

    @property
    def media_content_id(self) -> str | None:
        """Content ID of current playing media."""
        v = self.device.value
        audio_info = v.get("audio_full_info") or v.get("audio_info")
        if audio_info:
            return audio_info.get("song_id")
        return None

    @property
    def media_content_type(self) -> MediaType | str | None:
        """Content type of current playing media."""
        return MediaType.MUSIC

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        v = self.device.value
        duration = v.get("duration", v.get("audio_full_info", v.get("audio_info", {})).get("duration", "00:00"))
        minutes, seconds = map(int, duration.split(":"))
        return minutes * 60 + seconds

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        v = self.device.value
        play_progress = v.get("play_progress", "00:00")
        minutes, seconds = map(int, play_progress.split(":"))
        return minutes * 60 + seconds

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When was the position of the current playing media valid."""
        return dt_util.utcnow()

    @property
    def state(self) -> MediaPlayerState | None:
        """State of the player."""
        v = self.device.value
        return MediaPlayerState.PLAYING if v.get("play", "off") == "on" else MediaPlayerState.PAUSED

    @property
    def repeat(self) -> RepeatMode | str | None:
        """Return current repeat mode."""
        v = self.device.value
        repeat, shuffle = self.get_mode(v.get("play_mode", "list"))
        return repeat

    @property
    def shuffle(self) -> bool | None:
        """Return if shuffle is enabled."""
        v = self.device.value
        repeat, shuffle = self.get_mode(v.get("play_mode", "list"))
        return shuffle

    async def async_media_play(self) -> None:
        await self._send_command({"play": "on"})

    async def async_media_pause(self) -> None:
        await self._send_command({"play": "off"})

    async def async_media_seek(self, position: float) -> None:
        minutes, seconds = divmod(int(position), 60)
        time_str = "{:02d}:{:02d}".format(minutes, seconds)
        await self._send_command({"play_progress": time_str})

    async def async_mute_volume(self, mute: bool) -> None:
        if mute:
            await self._send_command({"mute": "on"})
        else:
            await self._send_command({"mute": "off"})

    async def async_volume_up(self) -> None:
        volume_level = min(1.0, self.volume_level + 0.1)
        volume = int(volume_level * self._max_volume)
        await self._send_command({"volume": volume})

    async def async_volume_down(self) -> None:
        volume_level = max(0.0, self.volume_level - 0.1)
        volume = int(volume_level * self._max_volume)
        await self._send_command({"volume": volume})

    async def async_set_volume_level(self, volume: float) -> None:
        await self._send_command({"volume": math.ceil(volume * self._max_volume)})

    async def async_set_shuffle(self, shuffle: bool) -> None:
        if shuffle:
            await self._send_command({"play_mode": "random"})
        else:
            await self.async_set_repeat(self.repeat)

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        if repeat == RepeatMode.ONE:
            await self._send_command({"play_mode": "single"})
        elif repeat == RepeatMode.ALL:
            await self._send_command({"play_mode": "list"})
        elif repeat == RepeatMode.OFF:
            if (self.entity_description.key == DPCode.XIANG_WANG_MUSIC_S7_MINI_3S
                    or self.entity_description.key == DPCode.XIANG_WANG_MUSIC_S8
                    or self.entity_description.key == DPCode.SHENG_BI_KE_MUSIC):
                await self._send_command({"play_mode": "all"})
            elif self.entity_description.key == DPCode.BO_SHENG_MUSIC:
                await self._send_command({"play_mode": "order"})
            else:
                await self._send_command({"play_mode": "list"})

    async def async_media_previous_track(self) -> None:
        await self._send_command({"songs_switch": "prev"})

    async def async_media_next_track(self) -> None:
        await self._send_command({"songs_switch": "next"})

    def get_mode(self, play_mode) -> Optional[tuple[RepeatMode, bool]]:
        repeat = None
        shuffle = False
        if play_mode == "list":
            repeat = RepeatMode.ALL
        elif play_mode == "single":
            repeat = RepeatMode.ONE
        elif play_mode == "random":
            repeat = RepeatMode.ALL
            shuffle = True
        elif play_mode == "order":
            repeat = RepeatMode.ALL
        elif play_mode == "all":
            repeat = RepeatMode.OFF
        return repeat, shuffle
