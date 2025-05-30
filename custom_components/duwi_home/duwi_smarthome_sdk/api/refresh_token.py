from typing import Any

from ..api.account import AccountClient
from ..base.customer_api import CustomerApi
from ..const.const import _LOGGER, API_MAX_RETRY, Code


class AuthTokenRefresherClient:
    def __init__(self, client: CustomerApi):
        self._client = client

    async def refresh(self) -> dict[str, Any] | None:

        try:
            data = await self._client.put("/account/token", {"refreshToken": self._client.refresh_token})
            if data is not None:
                if data.get("code") == Code.OPERATION_SUCCESS.value:
                    return data
                if data.get("code") == Code.OPERATION_REFRESHTOKEN_ERROR.value:
                    authClient = AccountClient(self._client)
                    refreshData = await authClient.login(self._client.phone, self._client.password)
                    if refreshData is not None and refreshData.get("code") == Code.OPERATION_SUCCESS.value:
                        return  refreshData
                    if refreshData is not None and refreshData.get("code") == Code.ACCOUNT_LOGIN_ERROR.value:
                        await self._client.token_listener.error_notification()
                        return None
                else:
                    _LOGGER.warning("AuthTokenRefresherClient: control failed, code: %s", data.get("code"))
        except Exception as e:
                _LOGGER.warning("AuthTokenRefresherClient: control failed (attempt %d), error: %s", str(e))
                return None

        return None
