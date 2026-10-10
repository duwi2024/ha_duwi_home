"""LAN Payload Builder - Modular command generation for Duwi devices."""
import uuid
from typing import Any


class LanPayloadBuilder:
    """Base payload builder for LAN protocol commands."""

    VERSION = "1.0"

    def __init__(self, cmd_type: str):
        """Initialize payload builder.

        Args:
            cmd_type: Command type identifier (e.g., "device.power", "sys.op").
        """
        self._cmd_type = cmd_type

    def _generate_trace_id(self) -> str:
        """Generate unique trace ID."""
        return str(uuid.uuid4()).replace("-", "")

    def build_base_payload(
        self,
        sequence: str | None = None,
        route: int | None = None,
        property_data: dict[str, Any] | None = None,
        service_data: dict[str, Any] | None = None,
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build base payload structure.

        Args:
            sequence: Controller sequence number (optional for system commands).
            route: Route number (optional for system commands).
            property_data: Property command data.
            service_data: Service command data.
            event_data: Event command data.

        Returns:
            Complete payload dictionary.
        """
        payload = {
            "traceId": self._generate_trace_id(),
            "version": self.VERSION,
            "type": self._cmd_type,
        }

        data = {}

        if sequence is not None:
            data["sequence"] = sequence
        if route is not None:
            data["route"] = route
        if property_data:
            data["property"] = property_data
        if service_data:
            data["service"] = service_data
        if event_data:
            data["event"] = event_data

        payload["data"] = data
        return payload


class SystemPayloadBuilder(LanPayloadBuilder):
    """System command payload builder."""

    def __init__(self):
        """Initialize system payload builder."""
        super().__init__("sys.op")

    def build_discovery(
        self, sequences: list[str] | None = None
    ) -> dict[str, Any]:
        """Build device discovery payload.

        Args:
            sequences: List of device sequences to discover (None for all).

        Returns:
            Discovery payload dictionary.
        """
        terminal_search = {}
        if sequences:
            terminal_search["sequence"] = sequences[:10]

        return self.build_base_payload() | {"data": {"terminal_search": terminal_search}}

    def build_terminal_data_up(self,sequence: str) -> dict[str, Any]:
        """Build terminal data up payload.

        Args:
            sequence: Device sequence.

        Returns:
            Terminal data up payload dictionary.
        """
        return self.build_base_payload() | {"data": {"terminal_data_up": {"sequence":sequence}}}

class TerminalPayloadBuilder(LanPayloadBuilder):
    """Terminal command payload builder."""

    def __init__(self):
        """Initialize terminal payload builder."""
        super().__init__("terminal.op")

    def build_device_group_cmd_down(self, sequence: str, data: dict[str, Any]) -> dict[str, Any]:
        """Build terminal data down payload.

        Args:
            sequence: Device sequence.
            data: Terminal data.

        Returns:
            Terminal data down payload dictionary.
        """

        return self.build_base_payload(
            sequence=sequence,
            service_data={"device_group_cmd_down": data}
        )

    def build_scene_execute(self,sequence: str, scene_no: str) -> dict[str, Any]:
        """Build scene execute payload.

        Args:
            scene_no: Scene number.

        Returns:
            Scene execute payload dictionary.
        """
        return self.build_base_payload(
            sequence=sequence,
            service_data={"scene_execute": {"scene_no": scene_no}}
        )

class DevicePayloadBuilder(LanPayloadBuilder):
    """Device command payload builder."""

    def build_property_command(
        self,
        sequence: str,
        route: int,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Build property command payload.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            properties: Property key-value pairs.

        Returns:
            Property command payload dictionary.
        """
        return self.build_base_payload(
            sequence=sequence,
            route=route,
            property_data=properties,
        )

    def build_service_command(
        self,
        sequence: str,
        route: int,
        service: dict[str, Any],
    ) -> dict[str, Any]:
        """Build service command payload.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            service: Service command dictionary.

        Returns:
            Service command payload dictionary.
        """
        return self.build_base_payload(
            sequence=sequence,
            route=route,
            service_data=service,
        )


class PowerDeviceBuilder(DevicePayloadBuilder):
    """Power breaker device payload builder."""

    def __init__(self):
        """Initialize power device builder."""
        super().__init__("device.power")

    def build_switch_command(
        self, sequence: str, route: int, state: str
    ) -> dict[str, Any]:
        """Build switch command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            state: Switch state ("on" or "off").

        Returns:
            Switch command payload.
        """
        return self.build_property_command(
            sequence, route, {"switch": state}
        )


class LightDeviceBuilder(DevicePayloadBuilder):
    """Light device payload builder."""

    def __init__(self):
        """Initialize light device builder."""
        super().__init__("device.light")

    def build_switch_command(
        self, sequence: str, route: int, state: str
    ) -> dict[str, Any]:
        """Build switch command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            state: Switch state ("on" or "off").

        Returns:
            Switch command payload.
        """
        return self.build_property_command(
            sequence, route, {"switch": state}
        )

    def build_brightness_command(
        self, sequence: str, route: int, brightness: int
    ) -> dict[str, Any]:
        """Build brightness command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            brightness: Brightness value (0-100).

        Returns:
            Brightness command payload.
        """
        return self.build_property_command(
            sequence, route, {"light": brightness}
        )

    def build_color_temp_command(
        self, sequence: str, route: int, color_temp: int
    ) -> dict[str, Any]:
        """Build color temperature command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            color_temp: Color temperature value.

        Returns:
            Color temperature command payload.
        """
        return self.build_property_command(
            sequence, route, {"color_temp": color_temp}
        )


class CurtainDeviceBuilder(DevicePayloadBuilder):
    """Curtain device payload builder."""

    def __init__(self):
        """Initialize curtain device builder."""
        super().__init__("device.curtain")

    def build_control_command(
        self, sequence: str, route: int, action: str
    ) -> dict[str, Any]:
        """Build curtain control command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            action: Action ("open", "close", "stop").

        Returns:
            Control command payload.
        """
        return self.build_service_command(
            sequence, route, {"control": action}
        )

    def build_position_command(
        self, sequence: str, route: int, position: int
    ) -> dict[str, Any]:
        """Build curtain position command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            position: Position value (0-100).

        Returns:
            Position command payload.
        """
        return self.build_property_command(
            sequence, route, {"control": position}
        )


class HVACDeviceBuilder(DevicePayloadBuilder):
    """HVAC (Heating, Ventilation, Air Conditioning) device payload builder."""

    def __init__(self):
        """Initialize HVAC device builder."""
        super().__init__("device.hvac")

    def build_switch_command(
        self, sequence: str, route: int, state: str
    ) -> dict[str, Any]:
        """Build switch command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            state: Switch state ("on" or "off").

        Returns:
            Switch command payload.
        """
        return self.build_property_command(
            sequence, route, {"switch": state}
        )

    def build_ac_mode_command(
        self, sequence: str, route: int, mode: str
    ) -> dict[str, Any]:
        """Build AC mode command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            mode: AC mode ("auto", "cold", "hot", "fan", "wet", "air", "heat", "mix").

        Returns:
            AC mode command payload.
        """
        return self.build_property_command(
            sequence, route, {"ac_mode": mode}
        )

    def build_ac_temp_command(
        self, sequence: str, route: int, temp: float
    ) -> dict[str, Any]:
        """Build AC temperature command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            temp: Temperature value (10-30°C).

        Returns:
            AC temperature command payload.
        """
        return self.build_property_command(
            sequence, route, {"ac_set_temp": temp}
        )

    def build_ac_wind_speed_command(
        self, sequence: str, route: int, speed: str
    ) -> dict[str, Any]:
        """Build AC wind speed command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            speed: Wind speed ("auto", "super_strong", "super_high", "high",
                               "mid_high", "mid", "low", "mid_low", "super_low", "super_quiet").

        Returns:
            AC wind speed command payload.
        """
        return self.build_property_command(
            sequence, route, {"ac_wind_speed": speed}
        )

    def build_ac_wind_direction_command(
        self, sequence: str, route: int, direction: str
    ) -> dict[str, Any]:
        """Build AC wind direction command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            direction: Wind direction ("auto", "stop", "swing", "up_down", "left_right").

        Returns:
            AC wind direction command payload.
        """
        return self.build_property_command(
            sequence, route, {"ac_wind_direction": direction}
        )


class SensorDeviceBuilder(DevicePayloadBuilder):
    """Sensor device payload builder."""

    def __init__(self):
        """Initialize sensor device builder."""
        super().__init__("device.security_sensor")

    def build_query_all_command(
        self, sequence: str, route: int
    ) -> dict[str, Any]:
        """Build query all sensor data command.

        Args:
            sequence: Controller sequence number.
            route: Route number.

        Returns:
            Query command payload.
        """
        return self.build_service_command(
            sequence, route, {"query_info": {}}
        )


class VideoDeviceBuilder(DevicePayloadBuilder):
    """Video/Audio device payload builder."""

    def __init__(self):
        """Initialize video device builder."""
        super().__init__("device.video")

    def build_switch_command(
        self, sequence: str, route: int, state: str
    ) -> dict[str, Any]:
        """Build switch command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            state: Switch state ("on" or "off").

        Returns:
            Switch command payload.
        """
        return self.build_property_command(
            sequence, route, {"switch": state}
        )

    def build_play_command(
        self, sequence: str, route: int, state: str
    ) -> dict[str, Any]:
        """Build play/pause command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            state: Play state ("on" for play, "off" for pause).

        Returns:
            Play command payload.
        """
        return self.build_property_command(
            sequence, route, {"play": state}
        )

    def build_volume_command(
        self, sequence: str, route: int, volume: int
    ) -> dict[str, Any]:
        """Build volume command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            volume: Volume value (0-100).

        Returns:
            Volume command payload.
        """
        return self.build_property_command(
            sequence, route, {"volume": volume}
        )

    def build_mute_command(
        self, sequence: str, route: int, state: str
    ) -> dict[str, Any]:
        """Build mute command.

        Args:
            sequence: Controller sequence number.
            route: Route number.
            state: Mute state ("on" or "off").

        Returns:
            Mute command payload.
        """
        return self.build_property_command(
            sequence, route, {"mute": state}
        )


class PayloadBuilderFactory:
    """Factory for creating device-specific payload builders."""

    _builders = {
        "device.power": PowerDeviceBuilder,
        "device.light": LightDeviceBuilder,
        "device.curtain": CurtainDeviceBuilder,
        "device.hvac": HVACDeviceBuilder,
        "device.sensor": SensorDeviceBuilder,
        "device.video": VideoDeviceBuilder,
        "terminal":TerminalPayloadBuilder,
        "system": SystemPayloadBuilder,
    }

    @classmethod
    def create_builder(cls, device_category: str) -> LanPayloadBuilder:
        """Create payload builder for device category.

        Args:
            device_category: Device category ("device.power", "device.light", "device.curtain", "device.hvac",
                           "device.sensor", "device.video","terminal","system").

        Returns:
            Device-specific payload builder instance.

        Raises:
            ValueError: If device category is not supported.
        """
        builder_class = cls._builders.get(device_category.lower())
        if not builder_class:
            raise ValueError(f"Unsupported device category: {device_category}")
        return builder_class()

    @classmethod
    def register_builder(
        cls, category: str, builder_class: type[LanPayloadBuilder]
    ) -> None:
        """Register custom payload builder.

        Args:
            category: Device category name.
            builder_class: Builder class to register.
        """
        cls._builders[category.lower()] = builder_class
