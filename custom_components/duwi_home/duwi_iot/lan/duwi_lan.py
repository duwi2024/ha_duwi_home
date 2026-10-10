"""Duwi LAN Client - UDP multicast communication."""
import asyncio
from collections.abc import Callable
import json
import logging
import socket
import time
from typing import Any

from homeassistant.components.network import async_get_source_ip
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import (
    LAN_DISCOVER_INTERVAL,
    LAN_HEARTBEAT_INTERVAL,
    LAN_HEARTBEAT_TIMEOUT,
    LAN_MSG_TYPE_ACK,
    LAN_MULTICAST_ADDR,
    LAN_MULTICAST_PORT,
)
from .duwi_lan_protocol import DuwiLanProtocol
from .lan_payload_builder import (
    DevicePayloadBuilder,
    PayloadBuilderFactory,
    SystemPayloadBuilder,
    TerminalPayloadBuilder,
)

_LOGGER = logging.getLogger(__name__)


class DuwiLanClient:
    """Duwi LAN UDP multicast client."""

    def __init__(self, house_key: str, hass: HomeAssistant):
        """Initialize LAN client.

        Args:
            house_key: House encryption key.
            hass: Home Assistant instance for source IP detection.
        """
        self._protocol = DuwiLanProtocol(house_key)
        self._hass = hass
        self._sock: socket.socket | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol_handler: _LanProtocolHandler | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._discover_task: asyncio.Task | None = None
        self._running = False

        # Mapping of host sequence -> HostInfo
        self._host_info_list: dict[str, HostInfo] = {}

        # Listeners
        self._device_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._terminal_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._system_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._host_online_listeners: list[Callable[[str, bool, str, int], None]] = []
        self._device_group_listeners: list[Callable[[str, dict[str, Any]], None]] = []

        # Register internal listeners
        self.add_system_listener(self._system_command_handle)
        self.add_host_online_listener(self._host_online_listener_handler)

    def add_device_listener(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Add device update listener."""
        self._device_listeners.append(callback)

    def add_terminal_listener(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Add terminal update listener."""
        self._terminal_listeners.append(callback)

    def add_system_listener(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Add discovery result listener."""
        self._system_listeners.append(callback)

    def add_host_online_listener(self, callback: Callable[[str, bool, str, int], None]) -> None:
        """Add host online listener."""
        self._host_online_listeners.append(callback)

    def add_device_group_listener(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Add device group update listener."""
        self._device_group_listeners.append(callback)

    async def start(self) -> bool:
        """Start LAN client.

        Returns:
            True if started successfully.
        """

        _LOGGER.info("Starting LAN client")

        if self._running:
            return True

        try:
            loop = asyncio.get_running_loop()

            # Determine which local interface to use for multicast.
            # Critical on hosts with many interfaces (WiFi, VM bridges, VPNs):
            # without IP_MULTICAST_IF the OS may send/join on the wrong one,
            # so devices never receive discovery and we never receive theirs.
            try:
                source_ip = await async_get_source_ip(self._hass)
            except HomeAssistantError:
                source_ip = None

            if not source_ip:
                _LOGGER.warning(
                    "Could not determine source IP, falling back to default interface"
                )
                source_ip = "0.0.0.0"

            # Create UDP socket
            self._sock = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            # Bind to multicast port
            self._sock.bind(("", LAN_MULTICAST_PORT))

            # Set the multicast output interface explicitly so packets egress
            # on the LAN interface that actually reaches the hardware devices.
            if source_ip != "0.0.0.0":
                self._sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(source_ip),
                )

            # Join multicast group on the chosen interface (not 0.0.0.0), so
            # the group membership is registered where other devices live.
            mreq = socket.inet_aton(LAN_MULTICAST_ADDR) + socket.inet_aton(source_ip)
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            # Set multicast TTL and enable loopback
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

            # Create asyncio transport
            self._protocol_handler = _LanProtocolHandler(
                self._protocol,
                self._device_listeners,
                self._terminal_listeners,
                self._system_listeners,
                self._host_online_listeners,
                self._device_group_listeners,
            )

            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: self._protocol_handler,
                sock=self._sock,
            )

            self._running = True

            # Start heartbeat
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Start discovery
            self._discover_task = asyncio.create_task(self._discover_hosts_loop())

            # send discovery packet
            self.discover_hosts()

            _LOGGER.info(
                "LAN client started on %s:%d via interface %s",
                LAN_MULTICAST_ADDR, LAN_MULTICAST_PORT, source_ip,
            )
            return True

        except Exception as e:
            _LOGGER.error("Failed to start LAN client: %s", e, exc_info=True)
            await self.stop()
            return False

    async def stop(self) -> None:
        """Stop LAN client."""
        if not self._running:
            return

        _LOGGER.info("Stopping LAN client")
        self._running = False

        # 1. Cancel background tasks
        tasks_to_cancel = []
        if self._heartbeat_task:
            tasks_to_cancel.append(self._heartbeat_task)
        if self._discover_task:
            tasks_to_cancel.append(self._discover_task)

        for task in tasks_to_cancel:
            task.cancel()

        # Wait for tasks to complete, ignore cancellation exceptions
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

        self._heartbeat_task = None
        self._discover_task = None

        # 2. Close Transport (this will trigger connection_lost)
        if self._transport:
            if not self._transport.is_closing():
                self._transport.close()
            self._transport = None

        # 3. Close Socket (transport.close() usually closes the associated socket)
        if self._sock:
            try:
                # Check if socket is already closed
                if self._sock.fileno() != -1:
                    self._sock.close()
            except Exception as e:
                _LOGGER.debug("Socket already closed or invalid: %s", e)
            finally:
                self._sock = None

        _LOGGER.info("LAN client stopped")

    async def _heartbeat_loop(self) -> None:
        """Send heartbeat periodically."""
        while self._running:
            try:
                await asyncio.sleep(LAN_HEARTBEAT_INTERVAL)
                if not self._running:
                    break

                packet = self._protocol.build_heartbeat()

                for host_info in self._host_info_list.values():
                    if host_info.is_online and host_info.is_search:
                        self._send_unicast_packet(packet, host_info.addr_ip,host_info.addr_port)
                        _LOGGER.debug("Sending heartbeat to %s", host_info.addr_ip)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error("LAN Heartbeat error: %s", e, exc_info=True)

    async def _discover_hosts_loop(self) -> None:
        """Discover hosts periodically."""
        while self._running:
            try:
                await asyncio.sleep(LAN_DISCOVER_INTERVAL)
                _LOGGER.debug("Discover hosts")
                if not self._running:
                    break

                # check if any hosts are offline
                for seq, host_info in self._host_info_list.items():
                    if host_info.is_online and  host_info.is_timeout(LAN_HEARTBEAT_TIMEOUT):
                        # Handler Host Online — update existing HostInfo instead of replacing
                        for callback in self._host_online_listeners:
                            try:
                                callback(host_info.sequence, False,host_info.addr_ip,host_info.addr_port)
                            except Exception as e:
                                _LOGGER.error("host online listener error: %s", e)
                        _LOGGER.debug("Host %s is offline", seq)

                # send discovery packet
                host_off_lines = [
                    seq
                    for seq, host_info in self._host_info_list.items()
                    if not host_info.is_online or not host_info.is_search
                ]

                if host_off_lines:
                    batch_size = 10
                    for i in range(0, len(host_off_lines), batch_size):
                        _LOGGER.debug("Sending discovery packet for %s", host_off_lines[i : i + batch_size])
                        self.discover_hosts(host_off_lines[i : i + batch_size])

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error("Discovery error: %s", e, exc_info=True)

    def _send_packet(self, packet: bytes) -> None:
        """Send packet to multicast group."""
        # Check if transport exists and is not closing
        _LOGGER.debug("Sending multicast packet: %s", packet.hex())
        if self._transport and not self._transport.is_closing():
            try:
                self._transport.sendto(packet, (LAN_MULTICAST_ADDR, LAN_MULTICAST_PORT))
            except OSError as e:
                if e.errno == 9:
                    _LOGGER.debug("Socket closed during send (errno 9), skipping")
                else:
                    _LOGGER.warning("Failed to send multicast packet: %s", e)
        else:
            _LOGGER.warning("Transport not available or closing, skipping multicast send")

    def _send_unicast_packet(self, packet: bytes, target_ip: str,target_port:int) -> None:
        """Send packet to a specific IP address (Unicast).

        Args:
            packet: The bytes to send.
            target_ip: Target device IP address.
        """
        _LOGGER.debug("Sending unicast packet: %s,target_ip:%s,target_port:%s",packet.hex(),target_ip,str(target_port))
        if self._transport and not self._transport.is_closing():
            try:
                # Specify the target IP and port directly, instead of using a multicast address
                self._transport.sendto(packet, (target_ip, target_port))
            except OSError as e:
                # Ignore errors caused by socket closure
                if e.errno != 9:
                    _LOGGER.error("Failed to send unicast packet to %s:%d: %s", target_ip, target_port, e)
        else:
            _LOGGER.debug("Transport not available or closing, skipping unicast send")

    # Logical instruction processing
    def _system_command_handle(self, host_sequence: str, data: dict[str, Any]) -> None:
        """Process system command."""
        _LOGGER.debug("System command: %s", data)
        if not isinstance(data, dict):
            _LOGGER.error("Invalid data type for system command")
            return

        if "terminal_search" in data:
            # send terminal_data_up
            try:
                host_info = self._host_info_list.get(host_sequence)
                if host_info:
                    self.send_terminal_data_up(host_sequence,host_info.addr_ip,host_info.addr_port)
                    host_info.update_is_search(True)
            except Exception as e:
                _LOGGER.error("Failed to send terminal data up: %s", e)

        return

    def _host_online_listener_handler(self,host_sequence:str,is_online:bool,addr_ip:str,addr_port:int) -> None:
        """Host online listener handler."""
        existing = self._host_info_list.get(host_sequence.upper())
        if existing:
            _LOGGER.debug("Host online listener handler: %s, %s, %s, %s", host_sequence,is_online,addr_ip,addr_port)
            existing.update_online(is_online)
            if addr_ip and addr_port:
                existing.update_address(addr_ip, addr_port)

    def discover_hosts(
        self, sequences: list[str] | None = None
    ) -> None:
        """Discover devices on LAN.

        Args:
            sequences: List of device sequences to discover (None for all).
        """
        try:
            builder = PayloadBuilderFactory.create_builder("system")
            if not isinstance(builder, SystemPayloadBuilder):
                _LOGGER.error("Invalid builder type for system control")
                return

            payload = builder.build_discovery(sequences)

            packet = self._protocol.build_command(payload)
            self._send_packet(packet)
            _LOGGER.debug("Discovery command sent: %s", json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            _LOGGER.error("Failed to send discovery command: %s", e, exc_info=True)

    def send_terminal_data_up(self, sequence: str, target_ip: str | None, target_port: int | None) -> None:
        """Send terminal data up."""
        try:
            builder = PayloadBuilderFactory.create_builder("system")
            if not isinstance(builder, SystemPayloadBuilder):
                _LOGGER.error("Invalid builder type for system control")
                return

            payload = builder.build_terminal_data_up(sequence)
            packet = self._protocol.build_command(payload)

            if target_ip and target_port:
                self._send_unicast_packet(packet, target_ip, target_port)
            else:
                self._send_packet(packet)
            _LOGGER.debug("Terminal data up sent: %s", json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            _LOGGER.error("Failed to send terminal data up: %s", e, exc_info=True)

    def send_device_command(
        self,
        terminal_sequence: str,
        route: int,
        device_category: str,
        properties: dict[str, Any] | None = None,
        service: dict[str, Any] | None = None,
        target_host_sequence:str|None = None
    ) -> None:
        """Control device using payload builder.

        Args:
            terminal_sequence: Target terminal sequence.
            route: Route number.
            device_category: Device category for payload builder.
            properties: Property command data.
            service: Service command data.
            target_host_sequence: target host sequence.
        """
        try:
            builder = PayloadBuilderFactory.create_builder(device_category)
            if not isinstance(builder, DevicePayloadBuilder):
                _LOGGER.error("Invalid builder type for device control")
                return

            payload = builder.build_base_payload(
                sequence=terminal_sequence,
                route=route,
                property_data=properties,
                service_data=service,
            )

            packet = self._protocol.build_command(payload)
            if target_host_sequence:
                host_info = self._host_info_list.get(target_host_sequence)
                if host_info and host_info.addr_ip and host_info.addr_port:
                    self._send_unicast_packet(packet,host_info.addr_ip,host_info.addr_port)
                else:
                    self._send_packet(packet)
            else:
                self._send_packet(packet)
            _LOGGER.debug("Device command sent: %s", json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            _LOGGER.error("Failed to send device command: %s", e, exc_info=True)

    def send_scene_command(
            self,
            scene_no:str) ->None:
        """Control device using payload builder.

        Args:
            scene_no: Target scene number
        """

        try:
            builder = TerminalPayloadBuilder()

            for item in self._host_info_list.values():
                if item.is_online:
                    payload = builder.build_scene_execute(item.sequence,scene_no)
                    packet = self._protocol.build_command(payload)
                    if item.addr_ip and  item.addr_port:
                        self._send_unicast_packet(packet,item.addr_ip,item.addr_port)
                    else:
                        self._send_packet(packet)
        except Exception as e:
            _LOGGER.error("Failed to send scene command:%s",e,exc_info=True)

    def send_device_group_command(
            self,
            host_sequence:str,
            commands: dict[str, Any]) -> None:
        """Send device group command via LAN multicast.

        Args:
            host_sequence: Host sequence number.
            commands: Command key-value pairs for the group.
        """
        try:
            builder = TerminalPayloadBuilder()
            payload = builder.build_device_group_cmd_down(host_sequence,commands)
            packet = self._protocol.build_command(payload)
            item = self._host_info_list.get(host_sequence)
            if item is not None and item.is_online and item.addr_ip and  item.addr_port:
                self._send_unicast_packet(packet,item.addr_ip,item.addr_port)
        except Exception as e:
            _LOGGER.error("Failed to send device group command:%s",e,exc_info=True)

    def update_hosts_list(self, hosts: list[str]) -> None:
        """Update hosts list.

        Args:
            hosts: List of host sequences to maintain.
        """
        try:
            # Convert to set for efficient lookup
            hosts_set = {h.upper() for h in hosts}
            current_hosts = set(self._host_info_list.keys())

            # Remove hosts that are no longer in the list
            hosts_to_remove = current_hosts - hosts_set
            for seq in hosts_to_remove:
                self._host_info_list.pop(seq.upper())

            # Add new hosts that don't exist yet
            hosts_to_add = hosts_set - current_hosts
            for seq in hosts_to_add:
                self._host_info_list[seq.upper()] = HostInfo(seq.upper())
        except Exception as e:
            _LOGGER.error("Error while updating hosts list: %s", e)

    def get_host_info_list(self) -> dict[str, HostInfo]:
        """Get host info list."""
        return self._host_info_list

class _LanProtocolHandler(asyncio.DatagramProtocol):
    """Internal asyncio UDP protocol handler."""

    def __init__(
        self,
        protocol: DuwiLanProtocol,
        device_listeners: list[Callable[[str, dict[str, Any]], None]],
        terminal_listeners: list[Callable[[str, dict[str, Any]], None]],
        system_listeners: list[Callable[[str, dict[str, Any]], None]],
        host_online_listeners: list[Callable[[str, bool, str, int], None]],
        device_group_listeners: list[Callable[[str, dict[str, Any]], None]],
    ):
        """Initialize handler."""
        self._protocol = protocol
        self._device_listeners = device_listeners
        self._terminal_listeners = terminal_listeners
        self._system_listeners = system_listeners
        self._host_online_listeners = host_online_listeners
        self._device_group_listeners = device_group_listeners
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Called when connection is made."""
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle received datagram."""
        parsed = self._protocol.parse_packet(data)
        if not parsed:
            return

        msg_type = parsed["msg_type"]
        message_id = parsed["message_id"]
        device_id = str(parsed["device_id"]).upper()
        payload = parsed["payload"]

        if device_id == "FFFFFFFFFFFF":
            _LOGGER.debug("Loopback packet from self (device_id=FFFFFFFFFFFF), skipping: %s", data.hex())
            return

        _LOGGER.debug(
            "Packet: type=%d, msg_id=%d, device=%s, payload=%s",
            msg_type, message_id, device_id, payload
        )

        # Handler Host Online — update existing HostInfo instead of replacing
        for callback in self._host_online_listeners:
            try:
                callback(device_id, True, addr[0], addr[1])
            except Exception as e:
                _LOGGER.error("host online listener error: %s", e)

        # Handle ACK (heartbeat response)
        if msg_type == LAN_MSG_TYPE_ACK:
            _LOGGER.debug("ACK received from %s,data:%s", device_id,data.hex())
            return

        # Process payload
        if not payload:
            return

        self._handle_payload(payload, device_id)

    def _handle_payload(self, payload: dict[str, Any], host_sequence: str) -> None:
        """Handle decrypted payload."""

        msg_type = str(payload.get("type"))
        data = payload.get("data", {})

        if msg_type == "sys.reply":
            _LOGGER.debug("system response from %s", host_sequence)
            for callback in self._system_listeners:
                try:
                    callback(host_sequence, data)
                except Exception as e:
                    _LOGGER.error("System listener error: %s", e)

        elif msg_type.startswith("terminal."):
            _LOGGER.debug("terminal response from %s", host_sequence)
            for callback in self._terminal_listeners:
                try:
                    callback(host_sequence, data)
                except Exception as e:
                    _LOGGER.error("Terminal listener error: %s", e)

            # Route device group status reports to device group listeners
            service_data = data.get("service", {})
            if isinstance(service_data, dict):
                group_up = service_data.get("device_group_cmd_up")
                if isinstance(group_up, dict):
                    for callback in self._device_group_listeners:
                        try:
                            callback(host_sequence, group_up)
                        except Exception as e:
                            _LOGGER.error("Device group listener error: %s", e)

        elif str(msg_type).startswith("device."):
            _LOGGER.debug("device response from %s", host_sequence)
            for callback in self._device_listeners:
                try:
                    callback(host_sequence, data)
                except Exception as e:
                    _LOGGER.error("Device listener error: %s", e)

        else:
            _LOGGER.debug("Unhandled message type: %s", msg_type)

    def error_received(self, exc: Exception) -> None:
        """Handle protocol error."""
        # Bad file descriptor (errno 9) usually occurs during shutdown, ignore it
        if isinstance(exc, OSError) and exc.errno == 9:
            _LOGGER.debug("UDP socket closed (Bad file descriptor), ignoring.")
            return

        _LOGGER.error("UDP protocol error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection lost."""
        if exc:
            _LOGGER.warning("UDP connection lost: %s", exc)
        else:
            _LOGGER.debug("UDP connection closed")

class HostInfo:
    """Host information."""
    def __init__(self, host_sequence: str,is_online: bool=False,addr_ip:str|None=None,addr_port:int|None=None) -> None:
        """Initialize host information."""
        self.sequence = host_sequence.upper()
        self.addr_ip = addr_ip
        self.addr_port = addr_port
        self.is_online = is_online
        self.is_search = False
        self.update_time = time.time()

    def update_online(self, is_online: bool) -> None:
        """Update host information -- online."""
        self.is_online = is_online
        if not self.is_online:
            self.is_search = False
        self.update_time = time.time()

    def update_address(self,addr_ip:str|None=None,addr_port:int|None=None)  ->None:
        """Update host information -- address."""
        self.addr_ip = addr_ip
        self.addr_port = addr_port

    def update_is_search(self,is_search:bool)->None:
        """Update host information -- is_search."""
        self.is_search = is_search
        self.update_time = time.time()

    def is_timeout(self, timeout: int) -> bool:
        """Check if host is timeout."""
        elapsed_time = time.time() - self.update_time
        return elapsed_time >= timeout
