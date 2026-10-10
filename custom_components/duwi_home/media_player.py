"""Support for Duwi Home media players."""
import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .base import DuwiDeviceEntity
from .const import DOMAIN, HOUSE_NO, MANUFACTURER, SIGNAL_DEVICE_UPDATE
from .duwi_iot.duwi_manager import DuwiManager

_LOGGER = logging.getLogger(__name__)

MEDIA_PLAYER_DEVICE_TYPES = ("8-001",)

_SUBTYPE_CONFIG: dict[str, dict[str, Any]] = {
    "8-001-001": {
        "name": "华尔思背景音乐",
        "max_volume": 15,
        "has_switch": False,
        "has_progress": True,
        "has_duration": False,
        "has_source": False,
        "has_media_info": False,
        "play_modes": ["random", "list", "single"],
    },
    "8-001-002": {
        "name": "向往背景音乐S7/mini3S",
        "max_volume": 15,
        "has_switch": False,
        "has_progress": False,
        "has_duration": False,
        "has_source": False,
        "has_media_info": False,
        "play_modes": ["random", "list", "single", "all"],
    },
    "8-001-003": {
        "name": "向往背景音乐S8",
        "max_volume": 100,
        "has_switch": False,
        "has_progress": False,
        "has_duration": False,
        "has_source": False,
        "has_media_info": False,
        "play_modes": ["random", "list", "single", "all"],
    },
    "8-001-004": {
        "name": "声必可背景音乐",
        "max_volume": 19,
        "has_switch": False,
        "has_progress": False,
        "has_duration": False,
        "has_source": True,
        "has_media_info": False,
        "play_modes": ["random", "list", "single", "all"],
        "source_list": ["云音乐", "U盘", "TF卡", "蓝牙", "AUX外接1"],
        "source_map": {"云音乐": "cloud", "U盘": "udisk", "TF卡": "tfcard", "蓝牙": "bluetooth", "AUX外接1": "aux1"},
    },
    "8-001-005": {
        "name": "泊声背景音乐",
        "max_volume": 100,
        "has_switch": True,
        "has_progress": True,
        "has_duration": True,
        "has_source": True,
        "has_media_info": True,
        "play_modes": ["random", "list", "single", "order"],
        "source_list": ["云音乐", "本地音乐", "AUX外接1", "AUX外接2"],
        "source_map": {"云音乐": "cloud", "本地音乐": "local", "AUX外接1": "aux1", "AUX外接2": "aux2"},
    },
    "8-001-006": {
        "name": "Sonos背景音乐",
        "max_volume": 100,
        "has_switch": False,
        "has_progress": True,
        "has_duration": False,
        "has_source": False,
        "has_media_info": True,
        "play_modes": ["random", "single", "list", "crossfade"],
    },
    "8-001-007": {
        "name": "悠达背景音乐",
        "max_volume": 100,
        "has_switch": True,
        "has_progress": True,
        "has_duration": True,
        "has_source": True,
        "has_media_info": True,
        "play_modes": ["random", "list", "single"],
        "source_list": ["云音乐", "本地音乐", "AUX外接1", "AUX外接2"],
        "source_map": {"云音乐": "cloud", "本地音乐": "local", "AUX外接1": "aux1", "AUX外接2": "aux2"},
    },
}

_DUWI_PLAY_MODE_TO_REPEAT: dict[str, tuple[RepeatMode | None, bool | None]] = {
    "random": (RepeatMode.OFF, True),
    "single": (RepeatMode.ONE, False),
    "list": (RepeatMode.ALL, False),
    "all": (RepeatMode.ALL, False),
    "order": (RepeatMode.OFF, False),
    "crossfade": (None, None),
}


def _duwi_play_mode_for(
    play_modes: list[str], repeat: RepeatMode, shuffle: bool, honor: str
) -> str | None:
    """Pick a duwi play_mode matching the requested repeat/shuffle.

    The duwi play_mode is a single combined field, so repeat and shuffle cannot
    be controlled independently. ``honor`` ("repeat" or "shuffle") decides which
    dimension is satisfied first; the other is used as a fallback. Returns None
    when no suitable mode is available for the device.
    """
    if honor == "shuffle":
        if shuffle and "random" in play_modes:
            return "random"
        if not shuffle:
            if repeat == RepeatMode.ONE and "single" in play_modes:
                return "single"
            if repeat == RepeatMode.ALL:
                if "list" in play_modes:
                    return "list"
                if "all" in play_modes:
                    return "all"
            if "order" in play_modes:
                return "order"
        return None
    # honor repeat
    if repeat == RepeatMode.ONE and "single" in play_modes:
        return "single"
    if repeat == RepeatMode.ALL:
        if "list" in play_modes:
            return "list"
        if "all" in play_modes:
            return "all"
    # repeat OFF or unmappable: fall back to the shuffle dimension
    if shuffle and "random" in play_modes:
        return "random"
    if not shuffle and "order" in play_modes:
        return "order"
    return None


def _time_to_seconds(time_str: str) -> int | None:
    """Convert HH:MM:SS / MM:SS string to seconds."""
    try:
        parts = time_str.split(":")
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return seconds
    except (ValueError, AttributeError):
        return None


def _singer_to_str(singer: Any) -> str | None:
    """Normalize singer to a string.

    audio_info pushes singer as a plain string; audio_full_info pushes it as
    a JsonArray of {"id", "mid", "name"} objects.
    """
    if not singer:
        return None
    if isinstance(singer, str):
        return singer
    if isinstance(singer, list):
        names = [s.get("name") for s in singer if isinstance(s, dict) and s.get("name")]
        return ", ".join(names) if names else None
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Duwi Home media player platform."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    if not data:
        return

    duwi_manager: DuwiManager | None = data.get("DuwiManager")
    devices: list[dict[str, Any]] = data.get("devices", [])
    if not duwi_manager or not devices:
        return

    entities: list[DuwiMediaPlayer] = [
        DuwiMediaPlayer(duwi_manager, entry.data.get(HOUSE_NO), device)
        for device in devices if _is_media_player_device(device)
    ]

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d media player entities", len(entities))


class DuwiMediaPlayer(DuwiDeviceEntity, MediaPlayerEntity):
    """Representation of a Duwi Home background music player."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        duwi_manager: DuwiManager,
        house_no: str,
        device_data: dict[str, Any],
    ) -> None:
        """Initialize the media player."""
        super().__init__(house_no, device_data)
        self._duwi_manager = duwi_manager
        self._config = _SUBTYPE_CONFIG.get(
            self._duwi_device_sub_type_no, _SUBTYPE_CONFIG["8-001-001"]
        )

        self._attr_unique_id = f"duwi_media_{self._duwi_device_no}"
        self._attr_name = None
        self._attr_available = self._duwi_is_online

        self._attr_supported_features = self._compute_features()
        self._attr_source_list = self._config.get("source_list")
        self._attr_volume_step = 1.0 / self._config["max_volume"]

        self._update_state_from_value(self._duwi_device_value)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._duwi_device_no)},
            name=self._duwi_device_name,
            manufacturer=MANUFACTURER,
            model=self._duwi_device_sub_type_no,
            serial_number=self._duwi_device_no,
        )

    def _compute_features(self) -> MediaPlayerEntityFeature:
        """Compute supported features based on subtype config."""
        features = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
        )
        if self._config.get("has_switch"):
            features |= MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
        if self._config.get("has_source"):
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        if self._config.get("play_modes"):
            features |= MediaPlayerEntityFeature.REPEAT_SET | MediaPlayerEntityFeature.SHUFFLE_SET
        if self._config.get("has_progress"):
            features |= MediaPlayerEntityFeature.SEEK
        return features

    def _update_state_from_value(self, value: dict[str, Any]) -> None:
        """Update all state attributes from device value dict."""
        if self._config.get("has_switch") and value.get("switch") == "off":
            self._attr_state = MediaPlayerState.OFF
        elif value.get("play") == "on":
            self._attr_state = MediaPlayerState.PLAYING
        elif value.get("play") == "off":
            self._attr_state = MediaPlayerState.PAUSED
        else:
            self._attr_state = MediaPlayerState.IDLE

        duwi_volume = value.get("volume")
        max_vol = self._config["max_volume"]
        if duwi_volume is not None and max_vol > 0:
            self._attr_volume_level = min(1.0, max(0.0, int(duwi_volume) / max_vol))

        if "mute" in value:
            self._attr_is_volume_muted = value["mute"] == "on"

        if value.get("play_progress"):
            seconds = _time_to_seconds(value["play_progress"])
            if seconds is not None:
                self._attr_media_position = seconds
                self._attr_media_position_updated_at = dt_util.now()

        if value.get("duration"):
            seconds = _time_to_seconds(value["duration"])
            if seconds is not None:
                self._attr_media_duration = seconds

        if "play_mode" in value:
            play_mode = value["play_mode"]
            repeat, shuffle = _DUWI_PLAY_MODE_TO_REPEAT.get(play_mode, (None, None))
            if repeat is not None:
                self._attr_repeat = repeat
            if shuffle is not None:
                self._attr_shuffle = shuffle

        if self._config.get("has_source") and "audio_source" in value:
            source = value["audio_source"]
            rev_map = {
                v: k for k, v in self._config.get("source_map", {}).items()
            }
            self._attr_source = rev_map.get(source, source)

        if self._config.get("has_media_info"):
            audio_info = value.get("audio_info") or value.get("audio_full_info")
            if isinstance(audio_info, dict):
                self._attr_media_title = audio_info.get("name") or audio_info.get("song_name")
                self._attr_media_artist = _singer_to_str(audio_info.get("singer"))
                self._attr_media_album_name = audio_info.get("album_name")
                pic_url = audio_info.get("pic_url")
                self._attr_media_image_url = pic_url
                dur_str = audio_info.get("duration")
                if dur_str:
                    seconds = _time_to_seconds(str(dur_str))
                    if seconds is not None:
                        self._attr_media_duration = seconds

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
        self._update_state_from_value(self._duwi_device_value)

        if "online" in data:
            self._attr_available = bool(data["online"])
            self._update_online_status(bool(data["online"]))
        else:
            self._attr_available = True

        self.async_write_ha_state()

    async def _send_cmd(self, code: str, value: Any | None = None) -> None:
        """Send a single command to the device."""
        await self._duwi_manager.operate_device(
            self._duwi_device_no, [{"code": code, "value": value}]
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the media player on."""
        if self._config.get("has_switch"):
            await self._send_cmd("switch", "on")
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the media player off."""
        if self._config.get("has_switch"):
            await self._send_cmd("switch", "off")
        self._attr_state = MediaPlayerState.OFF
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        """Send play command."""
        await self._send_cmd("play", "on")
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Send pause command."""
        await self._send_cmd("play", "off")
        self._attr_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_play_pause(self) -> None:
        """Toggle play/pause."""
        await self._send_cmd("play_exchange")
        if self._attr_state == MediaPlayerState.PLAYING:
            self._attr_state = MediaPlayerState.PAUSED
        else:
            self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        await self._send_cmd("songs_switch", "next")

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        await self._send_cmd("songs_switch", "prev")

    async def async_media_seek(self, position: int) -> None:
        """Seek to a position (seconds) by sending play_progress as MM:SS."""
        if not self._config.get("has_progress"):
            return
        minutes, seconds = divmod(max(0, int(position)), 60)
        await self._send_cmd("play_progress", f"{minutes:02d}:{seconds:02d}")
        self._attr_media_position = max(0, int(position))
        self._attr_media_position_updated_at = dt_util.now()
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        max_vol = self._config["max_volume"]
        duwi_vol = max(0, min(max_vol, round(volume * max_vol)))
        await self._send_cmd("volume", duwi_vol)
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._send_cmd("mute", "on" if mute else "off")
        self._attr_is_volume_muted = mute
        self.async_write_ha_state()

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set repeat mode, mapped to a duwi play_mode."""
        play_modes = self._config.get("play_modes") or []
        mode = _duwi_play_mode_for(
            play_modes, repeat, bool(self._attr_shuffle), honor="repeat"
        )
        if mode:
            await self._send_cmd("play_mode", mode)
            new_repeat, new_shuffle = _DUWI_PLAY_MODE_TO_REPEAT.get(mode, (None, None))
            if new_repeat is not None:
                self._attr_repeat = new_repeat
            if new_shuffle is not None:
                self._attr_shuffle = new_shuffle
        self.async_write_ha_state()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Set shuffle, mapped to a duwi play_mode."""
        play_modes = self._config.get("play_modes") or []
        mode = _duwi_play_mode_for(
            play_modes, self._attr_repeat or RepeatMode.OFF, shuffle, honor="shuffle"
        )
        if mode:
            await self._send_cmd("play_mode", mode)
            new_repeat, new_shuffle = _DUWI_PLAY_MODE_TO_REPEAT.get(mode, (None, None))
            if new_repeat is not None:
                self._attr_repeat = new_repeat
            if new_shuffle is not None:
                self._attr_shuffle = new_shuffle
        self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        source_map = self._config.get("source_map", {})
        duwi_source = source_map.get(source, source)
        await self._send_cmd("audio_source", duwi_source)
        self._attr_source = source
        self.async_write_ha_state()


def _is_media_player_device(device: dict[str, Any]) -> bool:
    """Check if a device is a media player type."""
    if device.get("device_type_no") in MEDIA_PLAYER_DEVICE_TYPES:
        if device.get("is_use", 0) == 1:
            return True
    return False
