"""Duwi LAN Protocol - Packet building, parsing and encryption."""
import hashlib
import json
import logging
import struct
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

from ..const import (
    LAN_PACKET_HEADER,
    LAN_PACKET_FOOTER,
    LAN_PROTOCOL_VERSION,
    LAN_MSG_TYPE_CON,
    LAN_MSG_TYPE_NON,
    LAN_CLIENT_DEVICE_ID,
)

_LOGGER = logging.getLogger(__name__)


class DuwiLanProtocol:
    """Duwi LAN protocol handler."""

    def __init__(self, house_key: str):
        """Initialize protocol handler.

        Args:
            house_key: House encryption key (hex string).
        """
        self._house_key = house_key
        self._aes_key = bytes.fromhex(house_key)
        self._aes_iv = self._compute_iv(house_key)
        self._message_id = 0

    @staticmethod
    def _compute_iv(house_key: str) -> bytes:
        """Compute AES IV from house key.

        IV = MD5(house_key as hex bytes)
        """
        key_bytes = bytes.fromhex(house_key)
        md5_hash = hashlib.md5(key_bytes).digest()
        return md5_hash

    def _get_next_message_id(self) -> int:
        """Get next message ID (2 bytes, wraps around)."""
        self._message_id = (self._message_id + 1) & 0xFFFF
        return self._message_id

    def _encrypt_payload(self, payload: dict[str, Any]) -> bytes:
        """Encrypt JSON payload using AES-128-CBC.

        Args:
            payload: JSON payload dictionary.

        Returns:
            Encrypted payload bytes.
        """
        json_str = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        json_bytes = json_str.encode('utf-8')

        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(json_bytes) + padder.finalize()

        cipher = Cipher(
            algorithms.AES(self._aes_key),
            modes.CBC(self._aes_iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded_data) + encryptor.finalize()

        return encrypted

    def _decrypt_payload(self, encrypted_data: bytes) -> dict[str, Any] | None:
        """Decrypt AES-128-CBC encrypted payload.

        Args:
            encrypted_data: Encrypted payload bytes.

        Returns:
            Decrypted JSON payload dictionary, or None on failure.
        """
        try:
            cipher = Cipher(
                algorithms.AES(self._aes_key),
                modes.CBC(self._aes_iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted_data) + decryptor.finalize()

            unpadder = padding.PKCS7(128).unpadder()
            unpadded = unpadder.update(decrypted) + unpadder.finalize()

            json_str = unpadded.decode('utf-8')
            return json.loads(json_str)
        except ValueError:
            return None
        except Exception as e:
            _LOGGER.error("Failed to decrypt payload: %s", e, exc_info=True)
            return None

    def build_packet(
        self,
        msg_type: int,
        payload: dict[str, Any] | None = None,
        device_id: bytes | None = None,
        message_id: int | None = None,
    ) -> bytes:
        """Build a complete LAN packet.

        Args:
            msg_type: Message type (CON, NON, ACK, RST).
            payload: JSON payload (optional).
            device_id: Device ID (6 bytes), defaults to client ID.
            message_id: Message ID (2 bytes), auto-generated if not provided.

        Returns:
            Complete packet bytes.
        """
        if device_id is None:
            device_id = LAN_CLIENT_DEVICE_ID

        if message_id is None:
            message_id = self._get_next_message_id()

        # Encrypt payload if present
        encrypted_payload = b""
        if payload:
            encrypted_payload = self._encrypt_payload(payload)

        # Calculate PayloadLen field size based on payload length
        payload_len = len(encrypted_payload)
        if payload_len == 0:
            plll = 0b00
            payload_len_bytes = b""
        elif payload_len <= 0xFF:
            plll = 0b01
            payload_len_bytes = struct.pack(">B", payload_len)
        elif payload_len <= 0xFFFF:
            plll = 0b10
            payload_len_bytes = struct.pack(">H", payload_len)
        else:
            plll = 0b11
            payload_len_bytes = payload_len.to_bytes(3, "big")

        # Build data header byte: Ver(2) | T(2) | Reserved(2) | PLLL(2)
        header_byte = (LAN_PROTOCOL_VERSION << 6) | (msg_type << 4) | (0b00 << 2) | plll

        # Build data section
        data_section = struct.pack(">B", header_byte)
        data_section += struct.pack(">H", message_id)
        data_section += device_id
        data_section += payload_len_bytes
        data_section += encrypted_payload

        # Build complete packet
        packet = LAN_PACKET_HEADER + data_section + LAN_PACKET_FOOTER

        return packet

    def parse_packet(self, packet: bytes) -> dict[str, Any] | None:
        """Parse a LAN packet.

        Args:
            packet: Raw packet bytes.

        Returns:
            Parsed packet dictionary, or None on failure.
            Dictionary contains: msg_type, message_id, device_id, payload
        """
        try:
            # Verify header and footer
            if len(packet) < 13:
                _LOGGER.warning("Packet too short: %d bytes", len(packet))
                return None

            if packet[:2] != LAN_PACKET_HEADER:
                _LOGGER.warning("Invalid packet header")
                return None

            if packet[-2:] != LAN_PACKET_FOOTER:
                _LOGGER.warning("Invalid packet footer")
                return None

            # Parse data section
            data_section = packet[2:-2]

            header_byte = data_section[0]
            msg_type = (header_byte >> 4) & 0x03
            plll = header_byte & 0x03

            message_id = struct.unpack(">H", data_section[1:3])[0]
            device_id = data_section[3:9]

            # Parse payload length
            offset = 9
            if plll == 0b00:
                payload_len = 0
            elif plll == 0b01:
                payload_len = data_section[offset]
                offset += 1
            elif plll == 0b10:
                payload_len = struct.unpack(">H", data_section[offset:offset+2])[0]
                offset += 2
            else:
                payload_len = int.from_bytes(data_section[offset:offset+3], "big")
                offset += 3

            # Extract and decrypt payload
            payload = None
            if payload_len > 0:
                encrypted_payload = data_section[offset:offset+payload_len]
                payload = self._decrypt_payload(encrypted_payload)
                if not payload:
                    return None

            return {
                "msg_type": msg_type,
                "message_id": message_id,
                "device_id": device_id.hex(),
                "payload": payload,
            }
        except Exception as e:
            _LOGGER.error("Failed to parse packet: %s", e, exc_info=True)
            return None

    def build_heartbeat(self) -> bytes:
        """Build heartbeat packet (CON, no payload)."""
        return self.build_packet(LAN_MSG_TYPE_CON, payload=None)

    def build_command(
        self,
        payload: dict[str, Any],
        msg_type: int = LAN_MSG_TYPE_NON,
    ) -> bytes:
        """Build device command packet from pre-built payload.

        Args:
            payload: Pre-built payload dictionary from payload builder.
            msg_type: Message type (default NON).

        Returns:
            Command packet bytes.
        """
        return self.build_packet(msg_type, payload)
