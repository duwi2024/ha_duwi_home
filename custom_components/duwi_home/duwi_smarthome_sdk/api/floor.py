from typing import Any

from ..api.refresh_token import AuthTokenRefresherClient
from ..base.customer_api import CustomerApi
from ..const.const import _LOGGER, API_MAX_RETRY, Code


class FloorInfoClient:
    def __init__(self, client: CustomerApi):
        self._client = client

    async def fetch_floor_info(self) -> dict[str, Any] | None:

        for attempt in range(API_MAX_RETRY):
            try:
                data = await self._client.get("/floor/infos",
                                      {"houseNo": self._client.house_no})
                if data is not None:
                    if data.get("code") == Code.OPERATION_SUCCESS.value:
                        return data
                    if data.get("code") == Code.OPERATION_ACCESSTOKEN_ERROR.value:
                        authClient = AuthTokenRefresherClient(self._client)
                        refreshData = await authClient.refresh()
                        if refreshData is not None and refreshData.get("code") == Code.OPERATION_SUCCESS.value:

                            # 更新 customer_api 实体
                            await self._client.update_token(refreshData.get("data",{}).get("accessToken"),refreshData.get("data",{}).get("refreshToken"),refreshData.get("data",{}).get("accessTokenExpireTime"))

                            # 同步通知更新token
                            self._client.token_listener.update_token( is_refresh=True,
                            token_info={
                                "access_token": refreshData.get("data",{}).get("accessToken"),
                                "refresh_token": refreshData.get("data",{}).get("refreshToken")
                            })
                        else:
                            return  None
                    else:
                        _LOGGER.warning("FloorInfoClient: control failed, code: %s", data.get("code"))
            except Exception as e:
                if attempt < API_MAX_RETRY - 1:
                    _LOGGER.warning("FloorInfoClient: control failed (attempt %d), error: %s", attempt+1, str(e))
                else:
                    _LOGGER.warning("FloorInfoClient: control failed after %d attempts", API_MAX_RETRY)
                if attempt == API_MAX_RETRY - 1:
                    return None

        return None
