"""Support for Duwi Home climate devices."""
import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_ON,
    SWING_VERTICAL,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import DuwiDeviceEntity, DuwiGroupEntity
from .const import (
    DOMAIN,
    HOUSE_NO,
    MANUFACTURER,
    SIGNAL_DEVICE_GROUP_UPDATE,
    SIGNAL_DEVICE_UPDATE,
)
from .duwi_iot.duwi_manager import DuwiManager

_LOGGER = logging.getLogger(__name__)

CLIMATE_DEVICE_TYPES = ("5-001", "5-002", "5-003", "5-004", "5-005")

HVAC_MODE_TO_DUWI: dict[str, str] = {
    HVACMode.AUTO: "auto",
    HVACMode.COOL: "cold",
    HVACMode.HEAT: "hot",
    HVACMode.FAN_ONLY: "fan",
    HVACMode.DRY: "wet",
}
DUWI_TO_HVAC_MODE = {v: k for k, v in HVAC_MODE_TO_DUWI.items()}

FAN_MODE_TO_DUWI: dict[str, str] = {
    FAN_AUTO: "auto",
    FAN_LOW: "low",
    FAN_MEDIUM: "mid",
    FAN_HIGH: "high",
    "extreme_low":"extreme_low",
    "super_low": "super_low",
    "super_high": "super_high",
    "mid_low": "mid_low",
    "mid_high": "mid_high",
    "stop": "stop",
    "strong": "strong",
    "extreme_strong": "extreme_strong",
}
DUWI_TO_FAN_MODE = {v: k for k, v in FAN_MODE_TO_DUWI.items()}

SWING_MODE_TO_DUWI: dict[str, str] = {
    SWING_OFF: "stop",
    SWING_ON: "swing",
    SWING_VERTICAL: "up_down",
    SWING_HORIZONTAL: "left_right",
    SWING_BOTH: "auto",
}
DUWI_TO_SWING_MODE = {v: k for k, v in SWING_MODE_TO_DUWI.items()}

_DEVICE_FEATURES: dict[str, dict[str, Any]] = {
    # ── 5-001 空调 默认（通用） ──
    "5-001": {
        "features": (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TARGET_HUMIDITY
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.FAN_MODE
        ),
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "swing_modes": [SWING_OFF, SWING_ON, SWING_VERTICAL, SWING_HORIZONTAL],
        "min_temp": 15, "max_temp": 35, "temp_step": 0.1,
    },
    # 5-001-002 亿林中央空调：仅冷热，3级风速，无swing
    "5-001-002": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 10, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-003 德姆瑞中央空调：冷热风湿，3级风速
    "5-001-003": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 32, "temp_step": 1,
    },
    # 5-001-004 慕驰空调：冷热风湿自动
    "5-001-004": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.AUTO, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 15, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-005 拉斐AC+二联供：冷热风湿采暖一体
    "5-001-005": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 45, "temp_step": 1,
    },
    # 5-001-006 海林空调：仅冷热风
    "5-001-006": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-007 海林空调二联供：冷热风采暖一体 + lock
    "5-001-007": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
        "has_lock_mode": True,
    },
    # 5-001-008 约克空调：冷热风采暖一体，step 0.5
    "5-001-008": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
    },
    # 5-001-009 弗雷克三合一环境面板：冷热风湿采暖一体
    "5-001-009": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 10, "max_temp": 32, "temp_step": 1,
    },
    # 5-001-010 麦克维尔空调：更多风速档位
    "5-001-010": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.AUTO, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_high", FAN_HIGH, "mid_high", FAN_MEDIUM, "mid_low", FAN_LOW, "super_low"],
        "min_temp": 5, "max_temp": 30, "temp_step": 0.5,
    },
    # 5-001-011 富士通将军空调：7级风速
    "5-001-011": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.AUTO, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_HIGH, "mid_high", FAN_MEDIUM, "mid_low", FAN_LOW, "super_low"],
        "min_temp": 10, "max_temp": 30, "temp_step": 0.5,
    },
    # 5-001-012 零狗二联供温控器青春版：冷热风湿除湿采暖一体 + humidity
    "5-001-012": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
        "has_humidity": True,
    },
    # 5-001-013 犀牛王二联供温控器：冷热风采暖一体 + humidity
    "5-001-013": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 10, "max_temp": 35, "temp_step": 0.5,
        "has_real_humidity": True,
    },
    # 5-001-014 虚拟空调：冷热风 + humidity
    "5-001-014": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
        "has_humidity": True,
    },
    # 5-001-015 迈斯线控网关：冷热风湿
    "5-001-015": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-016 新晃空调温控：更多风速档位
    "5-001-016": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH, "stop"],
        "min_temp": 5, "max_temp": 45, "temp_step": 1,
    },
    # 5-001-017 因立空调温控：冷热风湿加湿 + humidity
    "5-001-017": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 32, "temp_step": 0.5,
        "has_real_humidity": True,
    },
    # 5-001-018 迈斯集控网关
    "5-001-018": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 19, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-019 拓凡空调 + humidity
    "5-001-019": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
        "has_real_humidity": True,
    },
    # 5-001-020 海信精密空调：+humidity +set_humidity
    "5-001-020": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 32, "temp_step": 1,
        "has_humidity": True,
    },
    # 5-001-021 海尔中央空调
    "5-001-021": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-022 美的商用转接板（直流）
    "5-001-022": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH, "super_high"],
        "min_temp": 17, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-023 美的商用转接板（交流）
    "5-001-023": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 17, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-024 弗雷克三合一温控器 +humidity
    "5-001-024": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 10, "max_temp": 32, "temp_step": 1,
        "has_humidity": True,
    },
    # 5-001-025 海林空调温控
    "5-001-025": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_high"],
        "min_temp": 10, "max_temp": 32, "temp_step": 1,
    },
    # 5-001-026 视科温控
    "5-001-026": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_high"],
        "min_temp": 17, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-027 海信空调温控
    "5-001-027": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 32, "temp_step": 1,
    },
    # 5-001-028 曼瑞德温控 step 0.5
    "5-001-028": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 45, "temp_step": 0.5,
    },
    # 5-001-029 美的V8modbus直流
    "5-001-029": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH, "super_high"],
        "min_temp": 17, "max_temp": 30, "temp_step": 0.5,
    },
    # 5-001-030 美的V8modbus交流
    "5-001-030": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 17, "max_temp": 30, "temp_step": 0.5,
    },
    # 5-001-031 大金空调 step 0.1
    "5-001-031": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_high"],
        "min_temp": 16, "max_temp": 30, "temp_step": 0.1,
    },
    # 5-001-032 东芝空调 + stop
    "5-001-032": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "min_temp": 16, "max_temp": 30, "temp_step": 0.1,
    },
    # 5-001-033 中弘线控网关 step 1
    "5-001-033": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-034 中弘集控网关 step 1
    "5-001-034": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-035 广州洁控温控器：仅冷热
    "5-001-035": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 15, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-036 海信单元机
    "5-001-036": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 18, "max_temp": 32, "temp_step": 1,
    },
    # 5-001-037 美的风管机：11级风速
    "5-001-037": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "extreme_low", "super_low", FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH, "super_high", "strong", "extreme_strong"],
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-038 DAIKIN-C1线控网关：仅冷热
    "5-001-038": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 10, "max_temp": 30, "temp_step": 1,
    },
    # 5-001-039 蜻蜓：冷热风
    "5-001-039": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-040 日立空调：更多模式+7级风速
    "5-001-040": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, "mid_low", FAN_MEDIUM, FAN_HIGH, "super_high"],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
    },
    # 5-001-041 广州洁控温控器
    "5-001-041": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 15, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-042 柯耐弗直流温控器
    "5-001-042": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT,HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO,"super_low",FAN_LOW, FAN_MEDIUM, FAN_HIGH,"super_high"],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-043 吉朗空调
    "5-001-043": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT,HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO,FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 16, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-044 迪惟协议温控
    "5-001-044": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT,HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO,FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 15, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-045 亿林空调温控
    "5-001-045": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT,HVACMode.OFF],
        "fan_modes": [FAN_AUTO,FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-046 迪惟协议温控
    "5-001-046": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT,HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO,FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 15, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-047 LG中央空调
    "5-001-047": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT,HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO,FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 15, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-048 空调
    "5-001-048": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT,HVACMode.FAN_ONLY, HVACMode.DRY,HVACMode.OFF],
        "fan_modes": [FAN_AUTO,FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
    },
    # 5-001-049 海尔中央空调(直流电机)
    "5-001-049": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT,HVACMode.FAN_ONLY, HVACMode.DRY,HVACMode.OFF],
        "fan_modes": [FAN_AUTO,"super_low",FAN_LOW, "mid_low",FAN_MEDIUM, "mid_high",FAN_HIGH,"super_high"],
        "min_temp": 16, "max_temp": 35, "temp_step": 0.5,
    },
    # 5-001-050 海尔中央空调(交流电机)
    "5-001-050": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT,HVACMode.FAN_ONLY, HVACMode.DRY,HVACMode.OFF],
        "fan_modes": [FAN_AUTO,FAN_LOW, FAN_MEDIUM,FAN_HIGH],
        "min_temp": 16, "max_temp": 35, "temp_step": 0.5,
    },
    # ── 5-002 地暖 默认 ──
    "5-002": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.OFF],
        "min_temp": 10, "max_temp": 30, "temp_step": 0.1,
    },
    "5-002-001": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.OFF],
        "min_temp": 10, "max_temp": 30, "temp_step": 0.1,
    },
    "5-002-002": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 1},
    "5-002-003": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 1},
    "5-002-004": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 1},
    "5-002-005": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 10, "max_temp": 32, "temp_step": 1},
    "5-002-006": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 16, "max_temp": 45, "temp_step": 1},
    "5-002-007": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 16, "max_temp": 45, "temp_step": 1},
    "5-002-008": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 1},
    "5-002-009": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 16, "max_temp": 32, "temp_step": 1},
    "5-002-010": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 16, "max_temp": 32, "temp_step": 0.5, "has_real_humidity": True},
    "5-002-011": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 16, "max_temp": 32, "temp_step": 0.5, "has_real_humidity": True},
    "5-002-012": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 16, "max_temp": 32, "temp_step": 0.5},
    "5-002-013": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 10, "max_temp": 32, "temp_step": 1, "has_real_humidity": True},
    "5-002-014": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 17, "max_temp": 35, "temp_step": 1},
    "5-002-015": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 1},
    "5-002-016": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 1},
    "5-002-017": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 1},
    "5-002-018": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 0.5},
    "5-002-019": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 15, "max_temp": 35, "temp_step": 1},
    "5-002-020": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 45, "temp_step": 1},
    "5-002-021": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 45, "temp_step": 1},
    "5-002-022": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 1},
    "5-002-023": {"features": ClimateEntityFeature.TARGET_TEMPERATURE, "hvac_modes": [HVACMode.HEAT, HVACMode.OFF], "min_temp": 5, "max_temp": 35, "temp_step": 1},
    # ── 5-003 新风 默认 ──
    "5-003": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    "5-003-001": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_humidity": True,
    },
    "5-003-002": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
    },
    "5-003-003": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_co2": True, "has_pm25": True,
    },
    "5-003-004": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["stop", FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_co2": True, "has_pm25": True,
        "work_modes": ["auto", "manual", "timing"],
    },
    "5-003-005": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["stop", FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    "5-003-006": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "work_modes": ["heat_exchange", "common", "indoor_loop", "outdoor_loop"],
    },
    "5-003-007": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["stop", FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "work_modes": ["manual", "timing"],
    },
    "5-003-008": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    "5-003-009": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_humidity": True,
        "work_modes": ["air", "clean", "wet"],
    },
    "5-003-010": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["stop", FAN_AUTO, "super_strong", "super_high", FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_low"],
        "has_co2": True, "has_pm25": True,
    },
    "5-003-011": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_low", "stop"],
        "work_modes": ["air", "wet"],
    },
    "5-003-012": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
    },
    "5-003-013": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "work_modes": ["indoor_loop", "fresh", "fresh_wet", "wet"],
    },
    "5-003-014": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
    },
    "5-003-015": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    "5-003-016": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    "5-003-017": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
    },
    "5-003-018": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
        "has_humidity": True,
        "work_modes": ["fresh", "wet"],
    },
    "5-003-019": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
    },
    "5-003-020": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["super_low", FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_high", "extreme_strong"],
        "has_humidity": True, "has_pm25": True,
        "work_modes": ["auto", "manual", "program"],
    },
    "5-003-021": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_HIGH],
        "has_humidity": True, "has_co2": True,
        "work_modes": ["wet", "ventilate"],
    },
    "5-003-022": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_humidity": True,
        "work_modes": ["high", "mid", "low"],
    },
    "5-003-023": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "has_co2": True, "has_pm25": True,
        "work_modes": ["auto", "manual"],
        "work_mode_code": "fa_run_mode",
    },
    "5-003-024": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
    },
    "5-003-025": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
        "has_co2": True, "has_pm25": True,
        "work_modes": ["exhaust", "heat_exchange", "smart", "powerful"],
    },
    "5-003-026": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
        "min_temp": 18, "max_temp": 31, "temp_step": 1,
        "work_modes": ["auto", "exhaust", "heat_exchange", "fresh", "wet", "cold_room", "heat_room"],
    },
    "5-003-027": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["super_high", FAN_HIGH, FAN_MEDIUM, FAN_LOW],
        "work_modes": ["auto", "timing", "exhaust", "fresh", "energy_recycle", "night", "holiday"],
    },
    "5-003-028": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_low", "stop"],
        "work_modes": ["auto", "manual", "timing", "sleep"],
    },
    "5-003-029": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "has_co2": True, "has_pm25": True,
        "work_modes": ["auto", "manual", "timing", "sleep"],
    },
    "5-003-030": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "has_humidity": True, "has_pm25": True,
        "work_modes": ["indoor_loop", "fresh", "fresh_wet", "wet"],
    },
    "5-003-031": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_co2": True, "has_pm25": True,
        "work_modes": ["auto", "manual", "night", "holiday"],
    },
    "5-003-032": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
        "has_humidity": True, "has_pm25": True,
        "work_modes": ["fresh", "wet"],
    },
    "5-003-033": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_low", "stop"],
        "has_co2": True, "has_pm25": True,
        "work_modes": ["auto", "manual", "timing", "sleep"],
    },
    "5-003-034": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_humidity": True,
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
        "work_modes": ["auto", "fresh", "clean", "wet"],
    },
    "5-003-035": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    "5-003-036": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["super_high", FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_low", "stop"],
        "has_pm25": True,
        "work_modes": ["fresh", "clean", "cold_room", "sleep", "smart", "powerful"],
    },
    "5-003-037": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "work_modes": ["night", "holiday"],
    },
    "5-003-038": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_humidity": True,
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
    },
    "5-003-039": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "extreme_strong", "super_high", FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_low", "super_quiet"],
        "work_modes": ["auto", "exhaust", "heat_exchange", "indoor_loop", "fresh", "pass"],
    },
    "5-003-040": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["extreme_strong", "super_high", FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_low", "super_quiet"],
    },
    "5-003-041": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "has_co2": True, "has_pm25": True,
        "work_modes": ["auto", "manual", "timing"],
    },
    "5-003-042": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
    },
    "5-003-043": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    # 5-003-044 布雷森新风控制器
    "5-003-044": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "has_humidity": True,
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
        "work_modes": ["auto", "manual", "timing"],
    },
    # 5-003-045 科美臣新风
    "5-003-045": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
        "work_modes": ["auto", "manual", "timing"],
    },
    # 5-003-046 士诺新风
    "5-003-046": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "work_modes": ["auto", "manual", "timing"],
    },
    # 5-003-047 兰舍新风面板 L-3
    "5-003-047": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "work_modes": ["manual", "timing"],
    },
    # 5-003-048 威能新风控制器
    "5-003-048": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "work_modes": ["auto", "manual", "sleep"],
    },
    # 5-003-049 大金全热交换器
    "5-003-049": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_high"],
        "work_modes": ["auto", "heat_exchange", "common"],
    },
    # 5-003-050 东芝全热交换器
    "5-003-050": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
    },
    # 5-003-051 环都拓普新风控制器(HDK-19V)
    "5-003-051": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "work_modes": ["auto", "manual"],
    },
    # 5-003-052 环都拓普新风控制器(HDK-20A)
    "5-003-052": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "work_modes": ["auto", "manual"],
    },
    # 5-003-053 百朗新风线控器
    "5-003-053": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["super_high", FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_low", "stop"],
        "work_modes": ["fresh", "fresh_wet", "clean", "wet", "cold_room", "sleep", "smart", "powerful", "comfort", "max", "frost", "pipeline_clean"],
    },
    # 5-003-054 沃森新风控制器
    "5-003-054": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
        "work_modes": ["auto", "manual", "timing", "indoor_loop", "sleep", "pass"],
    },
    # 5-003-055 湿腾空气平衡器
    "5-003-055": {
        "features": 0,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "has_humidity": True,
    },
    # 5-003-056 绿岛风新风控制器
    "5-003-056": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
    },
    # 5-003-057 远大新风
    "5-003-057": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_low"],
    },
    # 5-003-058 西蒙新风
    "5-003-058": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_high", "super_low"],
        "has_humidity": True,
        "work_modes": ["auto", "manual", "sleep"],
    },
    # 5-003-059 博乐(面板)
    "5-003-059": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
        "work_modes": ["common", "indoor_loop", "fresh", "smart"],
    },
    # 5-003-060 日立新风
    "5-003-060": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_high", FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_low", "stop"],
        "has_humidity": True,
        "min_temp": 15, "max_temp": 35, "temp_step": 0.5,
        "work_modes": ["ventilate", "smart_auto", "eco_fresh", "indoor_loop", "normal_air", "cold_wet", "hot_humidify", "cold_hot_auto", "smart_humidify"],
    },
    # 5-003-061 嘉科尼亚新风
    "5-003-061": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_high", "super_low", "extreme_strong"],
        "has_humidity": True,
        "work_modes": ["auto", "manual", "program"],
    },
    # 5-003-062 松下新风(FV-xxZDP2C)
    "5-003-062": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "work_modes": ["auto", "heat_exchange", "indoor_loop", "disinfect"],
    },
    # 5-003-063 湿腾除湿机(EC控制板)
    "5-003-063": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "has_humidity": True,
        "work_modes": ["indoor_loop", "fresh", "fresh_wet", "wet"],
    },
    # 5-003-064 松下新风(FV-50NXC1C)
    "5-003-064": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_humidity": True,
        "work_modes": ["fresh", "fresh_wet", "wet", "disinfect"],
    },
    # 5-003-065 格恩加湿机
    "5-003-065": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_HIGH, FAN_MEDIUM, FAN_LOW, "super_high", "super_low"],
        "has_humidity": True,
        "work_modes": ["manual", "auto", "sleep", "powerful"],
    },
    # 5-003-066 造梦者新风机
    "5-003-066": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_HIGH, FAN_MEDIUM, FAN_LOW, "stop", "super_high", "super_low"],
    },
    # 5-003-067 松井吊顶除湿机
    "5-003-067": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
        "min_temp": 16, "max_temp": 36, "temp_step": 1,
        "work_modes": ["fresh", "clean", "wet", "smart"],
    },
    # 5-003-068 吉朗新风
    "5-003-068": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    # 5-003-069 迪惟新风面板
    "5-003-069": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    # 5-003-070 格兰斯柯新风
    "5-003-070": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "work_modes": ["fresh", "sleep", "pass"],
    },
    # 5-003-071 奥德森新风
    "5-003-071": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
        "work_modes": ["auto", "manual", "timing"],
    },
    # 5-003-072 德备新风
    "5-003-072": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_HIGH, FAN_MEDIUM, FAN_LOW, "stop", "super_high", "super_low", "extreme_strong"],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
        "work_modes": ["indoor_loop", "outdoor_loop", "fresh"],
    },
    # 5-003-073 迈迪龙新风控制器
    "5-003-073": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    # 5-003-074 德普莱太新风
    "5-003-074": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
    },
    # 5-003-075 恒大盛业新风
    "5-003-075": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": ["super_quiet", "super_low", FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH, "super_high", "extreme_strong", "stop"],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
    },
    # 5-003-076 新风(KNX)
    "5-003-076": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO],
        "has_humidity": True,
        "min_temp": 15, "max_temp": 35, "temp_step": 1,
        "work_modes": ["manual", "auto", "timing"],
    },
    # 5-003-077 德普莱太新风(除湿机触摸屏)
    "5-003-077": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_HIGH],
        "has_humidity": True,
    },
    # 5-003-078 三菱电机新风
    "5-003-078": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO],
    },
    # 5-003-079 KF-900D新风控制器
    "5-003-079": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "stop"],
        "work_modes": ["manual", "timing"],
    },
    # 5-003-080 德普莱太新风(普瑞DPLT-001)
    "5-003-080": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    # 5-003-081 霍尼韦尔环控一体机集控
    "5-003-081": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
        "min_temp": 16, "max_temp": 30, "temp_step": 1,
        "work_modes": ["auto", "exhaust", "wet", "cold_room", "heat_room"],
    },
    # 5-003-082 霍尼韦尔独立加湿器
    "5-003-082": {
        "features": ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO],
        "has_humidity": True,
        "work_modes": ["auto", "manual", "sleep", "powerful"],
    },
    # 5-003-083 霍尼韦尔EFD系列
    "5-003-083": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "has_humidity": True, "has_co2": True, "has_pm25": True,
        "work_modes": ["fresh"],
    },
    # ── 5-004 热泵 默认 ──
    "5-004": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 5, "max_temp": 55, "temp_step": 0.5,
    },
    "5-004-001": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 5, "max_temp": 55, "temp_step": 0.5,
    },
    "5-004-002": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 7, "max_temp": 55, "temp_step": 0.5,
    },
    "5-004-003": {
        "features": 0,
        "hvac_modes": [HVACMode.OFF],
    },
    "5-004-004": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 5, "max_temp": 55, "temp_step": 1,
    },
    "5-004-005": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 7, "max_temp": 60, "temp_step": 0.5,
    },
    "5-004-006": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 5, "max_temp": 55, "temp_step": 1,
    },
    "5-004-007": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 12, "max_temp": 50, "temp_step": 0.5,
    },
    "5-004-008": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 12, "max_temp": 55, "temp_step": 0.5,
    },
    "5-004-009": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 5, "max_temp": 55, "temp_step": 0.5,
    },
    "5-004-010": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": -15, "max_temp": 70, "temp_step": 0.5,
    },
    "5-004-011": {
        "features": 0,
        "hvac_modes": [HVACMode.OFF],
    },
    "5-004-012": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF],
        "min_temp": 18, "max_temp": 30, "temp_step": 1,
    },
    # ── 5-005 二联供 默认 ──
    "5-005": {
        "features": (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TARGET_HUMIDITY
            | ClimateEntityFeature.FAN_MODE
        ),
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
    },
    "5-005-001": {
        "features": (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TARGET_HUMIDITY
            | ClimateEntityFeature.FAN_MODE
        ),
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", "mid_low", FAN_LOW, FAN_MEDIUM, "mid_high", FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
        "has_humidity": True,
    },
    "5-005-002": {
        "features": (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TARGET_HUMIDITY
            | ClimateEntityFeature.FAN_MODE
        ),
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
        "has_humidity": True,
    },
    "5-005-003": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
    },
    "5-005-004": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "extreme_low", "super_low", FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH, "super_high", "strong", "extreme_strong", "stop"],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
    },
    "5-005-005": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 15, "max_temp": 45, "temp_step": 1,
    },
    "5-005-006": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 15, "max_temp": 45, "temp_step": 1,
    },
    "5-005-007": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 0, "max_temp": 30, "temp_step": 1,
    },
    "5-005-008": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", "mid_low", FAN_LOW, FAN_MEDIUM, "mid_high", FAN_HIGH, "super_high"],
        "min_temp": 5, "max_temp": 30, "temp_step": 0.5,
    },
    "5-005-009": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
    },
    "5-005-010": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 10, "max_temp": 35, "temp_step": 0.5,
    },
    "5-005-011": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_high"],
        "min_temp": 10, "max_temp": 35, "temp_step": 0.5,
    },
    "5-005-012": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
    },
    "5-005-013": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
        "has_real_humidity": True,
    },
    "5-005-014": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
    },
    "5-005-015": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
    },
    "5-005-016": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 15, "max_temp": 35, "temp_step": 0.5,
    },
    "5-005-017": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH, "super_high"],
        "min_temp": 16, "max_temp": 30, "temp_step": 0.5,
    },
    "5-005-018": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
    },
    "5-005-019": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "extreme_low", "super_low", FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH, "super_high", "strong", "extreme_strong"],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
    },
    "5-005-020": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH],
        "min_temp": 17, "max_temp": 32, "temp_step": 1,
        "has_humidity": True,
    },
    "5-005-021": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, FAN_MEDIUM, FAN_HIGH, "super_high"],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
        "has_real_humidity": True,
    },
    "5-005-022": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 1,
        "has_humidity": True,
    },
    "5-005-023": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, "super_low", FAN_LOW, FAN_MEDIUM, FAN_HIGH, "strong"],
        "min_temp": 18, "max_temp": 30, "temp_step": 1,
        "has_humidity": True,
    },
    "5-005-024": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, "mid_low", FAN_MEDIUM, "mid_high", FAN_HIGH],
        "min_temp": 5, "max_temp": 35, "temp_step": 0.5,
    },
}

_VALUE_FIELDS: dict[str, dict[str, str]] = {
    "5-001": {"set_temp": "ac_set_temp", "real_temp": "ac_real_temp", "set_humidity": "ac_set_humidity", "real_humidity": "ac_real_humidity", "mode": "ac_mode", "fan": "ac_wind_speed", "swing": "ac_wind_direction"},
    "5-002": {"set_temp": "fh_set_temp", "real_temp": "fh_real_temp", "real_humidity": "fh_real_humidity"},
    "5-003": {"set_temp": "fa_set_temp", "real_temp": "fa_real_temp", "set_humidity": "fa_set_humidity", "real_humidity": "fa_real_humidity", "fan": "fa_wind_speed"},
    "5-004": {"set_temp": "hp_set_temp", "real_temp": "hp_real_temp", "mode": "hp_mode"},
    "5-005": {"set_temp": "tc_set_temp", "real_temp": "tc_real_temp", "set_humidity": "tc_set_humidity", "real_humidity": "tc_real_humidity", "mode": "tc_mode", "fan": "tc_wind_speed"},
}

_GROUP_FEATURES: dict[str, dict[str, Any]] = {
    "AC": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 45, "temp_step": 1,
    },
    "FH": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE,
        "hvac_modes": [HVACMode.HEAT, HVACMode.OFF],
        "min_temp": 5, "max_temp": 45, "temp_step": 1,
    },
    "FA": {
        "features": ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    },
    "CS": {
        "features": ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        "hvac_modes": [HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.OFF],
        "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
        "min_temp": 5, "max_temp": 45, "temp_step": 1,
    },
}

_GROUP_VALUE_FIELDS: dict[str, dict[str, str]] = {
    "AC": {"set_temp": "ac_set_temp", "mode": "ac_mode", "fan": "ac_wind_speed"},
    "FH": {"set_temp": "fh_set_temp"},
    "FA": {"fan": "fa_wind_speed"},
    "CS": {"set_temp": "tc_set_temp", "mode": "tc_mode", "fan": "tc_wind_speed"},
}

CLIMATE_GROUP_TYPES = ("AC", "FH", "FA", "CS")
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Duwi Home climate platform."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    if not data:
        return

    duwi_manager: DuwiManager = data.get("DuwiManager")
    devices = data.get("devices", [])
    device_groups = data.get("device_groups", [])

    if not duwi_manager:
        _LOGGER.error("DuwiManager not found in hass.data")
        return

    climates: list[ClimateEntity] = []
    for device in devices:
        if device.get("device_type_no") not in CLIMATE_DEVICE_TYPES:
            continue
        if device.get("is_use",0) == 0:
            continue
        climates.append(DuwiClimate(duwi_manager, entry.data.get(HOUSE_NO), device))

    for group in device_groups:
        if group.get("device_group_type") not in CLIMATE_GROUP_TYPES:
            continue
        climates.append(DuwiGroupClimate(duwi_manager, entry.data.get(HOUSE_NO), group))

    if climates:
        async_add_entities(climates)
        _LOGGER.info("Added %d climate entities (devices=%d, groups=%d)", len(climates), len(devices), len(device_groups))


def _get_device_config(device_type_no: str, device_sub_type_no: str) -> dict[str, Any]:
    """Get device config by sub_type first, fallback to main type."""
    if device_sub_type_no and device_sub_type_no in _DEVICE_FEATURES:
        return _DEVICE_FEATURES[device_sub_type_no]
    return _DEVICE_FEATURES.get(device_type_no, {})

def _get_group_config(group_type: str) -> dict[str, Any]:
    """Get group config by type."""
    if group_type and group_type in _GROUP_FEATURES:
        return _GROUP_FEATURES[group_type]
    return {}


class DuwiClimate(DuwiDeviceEntity, ClimateEntity):
    """Representation of a Duwi Home climate device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, duwi_manager: DuwiManager, house_no: str, device_data: dict[str, Any]
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(house_no, device_data)
        self._duwi_manager = duwi_manager

        self._attr_unique_id = f"duwi_climate_{self._duwi_device_no}"
        self._attr_name = None
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_fan_mode = FAN_AUTO
        self._attr_swing_mode = SWING_OFF

        self._set_device_features()
        self._update_state_from_value(self._duwi_device_value)

        switch_val = self._duwi_device_value.get(self._switch_code, "off")
        self._apply_switch_state(switch_val)

        self._attr_available = self._duwi_is_online

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._duwi_device_no)},
            name=self._duwi_device_name,
            manufacturer=MANUFACTURER,
            model=self._duwi_device_sub_type_no,
            serial_number=self._duwi_device_no,
        )

    def _set_device_features(self) -> None:
        """Set supported features based on device subtype."""
        cfg = _get_device_config(self._duwi_device_type_no, self._duwi_device_sub_type_no)
        self._attr_supported_features = (
            cfg.get("features", 0)
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        self._attr_hvac_modes = cfg.get("hvac_modes", [HVACMode.OFF])
        if fan_modes := cfg.get("fan_modes"):
            self._attr_fan_modes = fan_modes
        if swing_modes := cfg.get("swing_modes"):
            self._attr_swing_modes = swing_modes
        if (work_modes := cfg.get("work_modes")):
            self._attr_preset_modes = work_modes
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
        if (v := cfg.get("min_temp")) is not None:
            self._attr_min_temp = v
        if (v := cfg.get("max_temp")) is not None:
            self._attr_max_temp = v
        if (v := cfg.get("temp_step")) is not None:
            self._attr_target_temperature_step = v

    def _update_state_from_value(self, value: dict[str, Any]) -> None:
        """Update temperature, humidity, mode, fan, swing from value dict."""
        fields = _VALUE_FIELDS.get(self._duwi_device_type_no, {})

        if (v := value.get(fields.get("set_temp", "_"))) is not None:
            self._attr_target_temperature = float(v)
        if (v := value.get(fields.get("real_temp", "_"))) is not None:
            self._attr_current_temperature = float(v)
        if (v := value.get(fields.get("set_humidity", "_"))) is not None:
            self._attr_target_humidity = float(v)
        if (v := value.get(fields.get("real_humidity", "_"))) is not None:
            self._attr_current_humidity = float(v)

        raw_mode = value.get(fields.get("mode", "_"))
        if raw_mode:
            mode = DUWI_TO_HVAC_MODE.get(raw_mode)
            if mode:
                self._attr_hvac_mode = mode

        raw_fan = value.get(fields.get("fan", "_"))
        if raw_fan is not None:
            self._attr_fan_mode = DUWI_TO_FAN_MODE.get(raw_fan)
        raw_swing = value.get(fields.get("swing", "_"))
        if raw_swing is not None:
            self._attr_swing_mode = DUWI_TO_SWING_MODE.get(raw_swing)

        cfg = _get_device_config(self._duwi_device_type_no, self._duwi_device_sub_type_no)
        work_code = cfg.get("work_mode_code", "fa_work_mode")
        if (raw_work := value.get(work_code)) is not None:
            presets = self._attr_preset_modes
            self._attr_preset_mode = raw_work if presets and raw_work in presets else None

    def _apply_switch_state(self, switch_val: str) -> None:
        """Apply switch on/off state to hvac_mode."""
        if switch_val == "off":
            self._attr_hvac_mode = HVACMode.OFF
        elif self._attr_hvac_mode == HVACMode.OFF:
            default = self._default_on_hvac_mode()
            if default:
                self._attr_hvac_mode = default

    def _default_on_hvac_mode(self) -> HVACMode | None:
        """Return the default HVAC mode when switch turns on."""
        hvac_modes = self._attr_hvac_modes
        if not hvac_modes:
            return None
        return next((m for m in (HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.DRY) if m in hvac_modes), hvac_modes[0])

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation ie. heat, cool mode."""
        return self._attr_hvac_mode

    def _cmd(self, suffix: str, value: Any) -> dict[str, Any]:
        """Build a prefixed command dict for the current device type."""
        prefix = self._cmd_prefix
        return {"code": f"{prefix}{suffix}", "value": value}

    def _cmd_raw(self, code: str, value: Any) -> dict[str, Any]:
        """Build a command dict with exact code (no prefix added)."""
        return {"code": code, "value": value}

    @property
    def _cmd_prefix(self) -> str:
        """Return command code prefix based on device type."""
        prefixes = {
            "5-001": "ac_",
            "5-002": "fh_",
            "5-003": "fa_",
            "5-004": "hp_",
            "5-005": "tc_",
        }
        return prefixes.get(self._duwi_device_type_no, "ac_")

    @property
    def _switch_code(self) -> str:
        """Return the switch command code for the current device type."""
        switch_codes = {
            "5-001": "ac_switch",
            "5-002": "fh_switch",
            "5-003": "fa_switch",
            "5-004": "hp_switch",
            "5-005": "tc_switch",
        }
        return switch_codes.get(self._duwi_device_type_no, "switch")

    async def _send_commands(self, commands: list[dict[str, Any]]) -> None:
        """Send commands to device."""
        await self._duwi_manager.operate_device(self._duwi_device_no, commands)

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

        if (switch_val := self._duwi_device_value.get(self._switch_code)) is not None:
            self._apply_switch_state(switch_val)

        if "online" in data:
            self._attr_available = bool(data["online"])
            self._update_online_status(bool(data["online"]))
        else:
            self._attr_available = True
            self._update_online_status(True)

        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        try:
            commands: list[dict[str, Any]] = []
            if hvac_mode == HVACMode.OFF:
                commands.append(self._cmd_raw(self._switch_code, "off"))
            else:
                commands.append(self._cmd_raw(self._switch_code, "on"))
                fields = _VALUE_FIELDS.get(self._duwi_device_type_no, {})
                if "mode" in fields:
                    duwi_mode = HVAC_MODE_TO_DUWI.get(hvac_mode)
                    if duwi_mode:
                        commands.append(self._cmd("mode", duwi_mode))
            await self._send_commands(commands)
        except Exception as err:
            _LOGGER.error(
                "Error setting hvac mode for %s: %s", self._duwi_device_no, err, exc_info=True
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        try:
            await self._send_commands([self._cmd("set_temp", str(temperature))])
        except Exception as err:
            _LOGGER.error(
                "Error setting temperature for %s: %s", self._duwi_device_no, err, exc_info=True
            )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode."""
        duwi_speed = FAN_MODE_TO_DUWI.get(fan_mode)
        if not duwi_speed:
            return
        try:
            await self._send_commands([self._cmd("wind_speed", duwi_speed)])
        except Exception as err:
            _LOGGER.error(
                "Error setting fan mode for %s: %s", self._duwi_device_no, err, exc_info=True
            )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set swing mode."""
        duwi_direction = SWING_MODE_TO_DUWI.get(swing_mode)
        if not duwi_direction:
            return
        try:
            await self._send_commands([self._cmd("wind_direction", duwi_direction)])
        except Exception as err:
            _LOGGER.error(
                "Error setting swing mode for %s: %s", self._duwi_device_no, err, exc_info=True
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset/work mode (fa_work_mode / fa_run_mode)."""
        if not self._attr_preset_modes:
            return
        cfg = _get_device_config(self._duwi_device_type_no, self._duwi_device_sub_type_no)
        work_code = cfg.get("work_mode_code", "fa_work_mode")
        try:
            await self._send_commands([self._cmd_raw(work_code, preset_mode)])
        except Exception as err:
            _LOGGER.error(
                "Error setting preset mode for %s: %s", self._duwi_device_no, err, exc_info=True
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the climate device on."""
        try:
            commands = [self._cmd_raw(self._switch_code, "on")]
            await self._send_commands(commands)
        except Exception as err:
            _LOGGER.error(
                "Error turning on climate %s: %s", self._duwi_device_no, err, exc_info=True
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the climate device off."""
        try:
            commands = [self._cmd_raw(self._switch_code, "off")]
            await self._send_commands(commands)
        except Exception as err:
            _LOGGER.error(
                "Error turning off climate %s: %s", self._duwi_device_no, err, exc_info=True
            )

    async def async_set_humidity(self, humidity: int) -> None:
        """Set target humidity."""
        try:
            await self._send_commands([self._cmd("set_humidity", str(humidity))])
        except Exception as err:
            _LOGGER.error(
                "Error setting humidity for %s: %s", self._duwi_device_no, err, exc_info=True
            )


class DuwiGroupClimate(DuwiGroupEntity, ClimateEntity):
    """Representation of a Duwi group as a climate device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, duwi_manager: DuwiManager, house_no: str, group_data: dict[str, Any]
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(house_no, group_data)
        self._duwi_manager = duwi_manager

        self._attr_unique_id = f"duwi_group_climate_{self._duwi_group_no}"
        self._attr_name = self._duwi_group_name
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_fan_mode = FAN_AUTO
        self._attr_swing_mode = SWING_OFF

        self._set_device_features()
        self._update_state_from_value(self._duwi_group_value)

        switch_val = self._duwi_group_value.get(self._switch_code, "off")
        self._apply_switch_state(switch_val)

        self._attr_available = self._duwi_is_online

    def _set_device_features(self) -> None:
        """Set supported features based on device subtype."""
        cfg = _get_group_config(self._duwi_group_type)
        self._attr_supported_features = (
            cfg.get("features", 0)
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        self._attr_hvac_modes = cfg.get("hvac_modes", [HVACMode.OFF])
        if fan_modes := cfg.get("fan_modes"):
            self._attr_fan_modes = fan_modes
        if swing_modes := cfg.get("swing_modes"):
            self._attr_swing_modes = swing_modes
        if (work_modes := cfg.get("work_modes")):
            self._attr_preset_modes = work_modes
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
        if (v := cfg.get("min_temp")) is not None:
            self._attr_min_temp = v
        if (v := cfg.get("max_temp")) is not None:
            self._attr_max_temp = v
        if (v := cfg.get("temp_step")) is not None:
            self._attr_target_temperature_step = v

    def _update_state_from_value(self, value: dict[str, Any]) -> None:
        """Update temperature, humidity, mode, fan, swing from value dict."""
        fields = _GROUP_VALUE_FIELDS.get(self._duwi_group_type, {})

        if (v := value.get(fields.get("set_temp", "_"))) is not None:
            self._attr_target_temperature = float(v)
        if (v := value.get(fields.get("real_temp", "_"))) is not None:
            self._attr_current_temperature = float(v)
        if (v := value.get(fields.get("set_humidity", "_"))) is not None:
            self._attr_target_humidity = float(v)
        if (v := value.get(fields.get("real_humidity", "_"))) is not None:
            self._attr_current_humidity = float(v)

        raw_mode = value.get(fields.get("mode", "_"))
        if raw_mode:
            mode = DUWI_TO_HVAC_MODE.get(raw_mode)
            if mode:
                self._attr_hvac_mode = mode

        raw_fan = value.get(fields.get("fan", "_"))
        if raw_fan is not None:
            self._attr_fan_mode = DUWI_TO_FAN_MODE.get(raw_fan)
        raw_swing = value.get(fields.get("swing", "_"))
        if raw_swing is not None:
            self._attr_swing_mode = DUWI_TO_SWING_MODE.get(raw_swing)

    def _apply_switch_state(self, switch_val: str) -> None:
        """Apply switch on/off state to hvac_mode."""
        if switch_val == "off":
            self._attr_hvac_mode = HVACMode.OFF
        elif self._attr_hvac_mode == HVACMode.OFF:
            default = self._default_on_hvac_mode()
            if default:
                self._attr_hvac_mode = default

    def _default_on_hvac_mode(self) -> HVACMode | None:
        """Return the default HVAC mode when switch turns on."""
        hvac_modes = self._attr_hvac_modes
        if not hvac_modes:
            return None
        return next((m for m in (HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.DRY) if m in hvac_modes), hvac_modes[0])

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation ie. heat, cool mode."""
        return self._attr_hvac_mode

    def _cmd(self, suffix: str, value: Any) -> dict[str, Any]:
        """Build a prefixed command dict for the current group type."""
        prefix = self._cmd_prefix
        return {"code": f"{prefix}{suffix}", "value": value}

    def _cmd_raw(self, code: str, value: Any) -> dict[str, Any]:
        """Build a command dict with exact code (no prefix added)."""
        return {"code": code, "value": value}

    @property
    def _cmd_prefix(self) -> str:
        """Return command code prefix based on group type."""
        prefixes = {
            "AC": "ac_",
            "FH": "fh_",
            "FA": "fa_",
            "CS": "tc_",
        }
        return prefixes.get(self._duwi_group_type, "ac_")

    @property
    def _switch_code(self) -> str:
        """Return the switch command code for the current group type."""
        switch_codes = {
            "AC": "ac_switch",
            "FH": "fh_switch",
            "FA": "fa_switch",
            "CS": "tc_switch",
        }
        return switch_codes.get(self._duwi_group_type, "switch")

    async def _send_commands(self, commands: list[dict[str, Any]]) -> None:
        """Send commands to device."""
        await self._duwi_manager.operate_device_group(self._duwi_group_no, commands,self._duwi_sync_host_sequences)

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        signal = SIGNAL_DEVICE_GROUP_UPDATE.format(self._duwi_group_no)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_update)
        )

    @callback
    def _handle_update(self, data: dict[str, Any]) -> None:
        """Handle device update from RPS or LAN."""
        if data.get("deviceGroupNo") != self._duwi_group_no:
            return

        self._update_group_value(data)
        self._update_state_from_value(self._duwi_group_value)

        if (switch_val := self._duwi_group_value.get(self._switch_code)) is not None:
            self._apply_switch_state(switch_val)

        if "online" in data:
            self._attr_available = bool(data["online"])
            self._update_online_status(bool(data["online"]))
        else:
            self._attr_available = True
            self._update_online_status(True)

        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        try:
            commands: list[dict[str, Any]] = []
            if hvac_mode == HVACMode.OFF:
                commands.append(self._cmd_raw(self._switch_code, "off"))
            else:
                commands.append(self._cmd_raw(self._switch_code, "on"))
                fields = _GROUP_VALUE_FIELDS.get(self._duwi_group_type, {})
                if "mode" in fields:
                    duwi_mode = HVAC_MODE_TO_DUWI.get(hvac_mode)
                    if duwi_mode:
                        commands.append(self._cmd("mode", duwi_mode))
            await self._send_commands(commands)
        except Exception as err:
            _LOGGER.error(
                "Error setting hvac mode for %s: %s", self._duwi_group_no, err, exc_info=True
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        try:
            await self._send_commands([self._cmd("set_temp", str(temperature))])
        except Exception as err:
            _LOGGER.error(
                "Error setting temperature for %s: %s", self._duwi_group_no, err, exc_info=True
            )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode."""
        duwi_speed = FAN_MODE_TO_DUWI.get(fan_mode)
        if not duwi_speed:
            return
        try:
            await self._send_commands([self._cmd("wind_speed", duwi_speed)])
        except Exception as err:
            _LOGGER.error(
                "Error setting fan mode for %s: %s", self._duwi_group_no, err, exc_info=True
            )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set swing mode."""
        duwi_direction = SWING_MODE_TO_DUWI.get(swing_mode)
        if not duwi_direction:
            return
        try:
            await self._send_commands([self._cmd("wind_direction", duwi_direction)])
        except Exception as err:
            _LOGGER.error(
                "Error setting swing mode for %s: %s", self._duwi_group_no, err, exc_info=True
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the climate device on."""
        try:
            commands = [self._cmd_raw(self._switch_code, "on")]
            await self._send_commands(commands)
        except Exception as err:
            _LOGGER.error(
                "Error turning on climate %s: %s", self._duwi_group_no, err, exc_info=True
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the climate device off."""
        try:
            commands = [self._cmd_raw(self._switch_code, "off")]
            await self._send_commands(commands)
        except Exception as err:
            _LOGGER.error(
                "Error turning off climate %s: %s", self._duwi_group_no, err, exc_info=True
            )

    async def async_set_humidity(self, humidity: int) -> None:
        """Set target humidity."""
        try:
            await self._send_commands([self._cmd("set_humidity", str(humidity))])
        except Exception as err:
            _LOGGER.error(
                "Error setting humidity for %s: %s", self._duwi_group_no, err, exc_info=True
            )
