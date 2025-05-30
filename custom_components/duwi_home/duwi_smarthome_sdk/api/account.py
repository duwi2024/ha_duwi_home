from typing import Any

from ..base.customer_api import CustomerApi
from ..const.const import _LOGGER, API_MAX_RETRY, Code


class AccountClient:
    def __init__(self, client: CustomerApi):
        self._client = client

    async def login(self, phone: str, password: str) -> dict[str, Any] | None:
        for attempt in range(API_MAX_RETRY):
            try:
                body = {
                    "phone": phone,
                    "password": password,
                }
                data = await self._client.post("/account/login", None, body)
                if data is not None and data.get("code") != Code.OPERATION_SUCCESS.value:
                    _LOGGER.warning("AccountClient: control failed, code: %s", data.get("code"))
                    return data
                if data is not None and data.get("code") != Code.ACCOUNT_LOGIN_ERROR.value:
                    return data
            except Exception as e:
                if attempt < API_MAX_RETRY - 1:
                    _LOGGER.warning("AccountClient: control failed (attempt %d), error: %s", attempt+1, str(e))
                else:
                    _LOGGER.warning("AccountClient: control failed after %d attempts", API_MAX_RETRY)
                if attempt == API_MAX_RETRY - 1:
                    return None
        return None

