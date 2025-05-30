from abc import ABCMeta
from typing import Any


class LanMessage:
    def __init__(self, device_no: str, message: dict[str, Any]):
        self.device_no = device_no
        self.message = message


class LanMessageListener(metaclass=ABCMeta):
    """Sharing device listener."""

    @classmethod
    def handle_message(cls, message: LanMessage):
        """Handle status.

        Args:
            handle_message(LanMessage): handle message
        """
        pass
