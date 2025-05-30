"""Config flow for Duwi Smart Hub integration."""
from . import Manager
from .duwi_smarthome_sdk.api.account import AccountClient
from .duwi_smarthome_sdk.api.house import HouseInfoClient
from .duwi_smarthome_sdk.base.customer_api import CustomerApi
from .duwi_smarthome_sdk.const.const import Code
import voluptuous as vol

from homeassistant import config_entries

from .const import (
    APP_KEY,
    APP_SECRET,
    APP_VERSION,
    CLIENT_MODEL,
    CLIENT_VERSION,
    DOMAIN,
    ADDRESS,
    WS_ADDRESS,
    _LOGGER, CLIENT, PHONE, PASSWORD, ACCESS_TOKEN, HOUSE_NO, HOUSE_KEY, REFRESH_TOKEN, HOUSE_NAME, HTTP_ADDRESS,
    WEBSOCKET_ADDRESS
)


# Configuration class that handles flow initiated by the user for Duwi integration
class DuwiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Duwi."""
    
    # Use version 1 for the configuration flow
    VERSION = 1
    phone = None
    password = None
    client = None
    address = None
    ws_address = None
    app_key = None
    app_secret = None
    access_token = None
    refresh_token = None
    houses = []

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""

        # Placeholder for error messages
        errors = {}

        # Ensure DOMAIN data has been initialized in Home Assistant
        self.hass.data.setdefault(DOMAIN, {})
        placeholders = {}

        # Check if user has provided app_key and app_secret
        if user_input and user_input.get(APP_KEY) and user_input.get(APP_SECRET) and user_input.get(
                PHONE) and user_input.get(PASSWORD):
            self.client = CustomerApi(
                address=HTTP_ADDRESS,
                ws_address=WEBSOCKET_ADDRESS,
                app_key=user_input[APP_KEY],
                app_secret=user_input[APP_SECRET],
                app_version=APP_VERSION,
                client_version=CLIENT_VERSION,
                client_model=CLIENT_MODEL,
            )
            lc = AccountClient(self.client)

            # 认证开发者
            auth_data = await lc.login(user_input[PHONE], user_input[PASSWORD])
            status = auth_data.get("code")
            # 状态码异常
            if status == Code.SUCCESS.value:
                self.phone = user_input[PHONE]
                self.password = user_input[PASSWORD]
                self.access_token = auth_data.get("data", {}).get("accessToken")
                self.refresh_token = auth_data.get("data", {}).get("refreshToken")
                self.client.access_token = auth_data.get("data", {}).get("accessToken")
                self.app_key = user_input[APP_KEY]
                self.app_secret = user_input[APP_SECRET]
                hic = HouseInfoClient(self.client)
                # Fetch the house information
                house_infos_data = await hic.fetch_house_info()
                house_infos_status = house_infos_data.get("code")
                if house_infos_status != Code.SUCCESS.value:
                    errors["base"] = "fetch_house_info_error"
                    placeholders["code"] = house_infos_status
                else:
                    if len(house_infos_data.get("data", {}).get("houseInfos", [])) == 0:
                        # Handle case where no houses are found
                        errors["base"] = "no_houses_found_error"
                    self.houses = house_infos_data.get("data", {}).get("houseInfos", [])
                    return await self.async_step_select_house()
            if status == Code.SIGN_ERROR.value:
                errors["base"] = "auth_error"
                placeholders["input"] = "应用编码 或者 应用密钥错误"
                placeholders["code"] = status
            elif status == Code.LOGIN_ERROR.value:
                errors["base"] = "auth_error"
                placeholders["input"] = "账号 或者 密码错误"
                placeholders["code"] = status
            elif status != Code.SUCCESS.value:
                errors["base"] = "unknown_error"
                placeholders["code"] = status

        # Show user input form (with error messages if any)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(APP_KEY): str,
                    vol.Required(APP_SECRET): str,
                    vol.Required(PHONE): str,
                    vol.Required(PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_auth(self, user_input=None):
        """Handle the authentication step in the configuration flow."""
        errors = {}
        placeholders = {}
        if user_input and user_input.get("phone") and user_input.get("password"):
            # Access the stored app credentials from previous step
            # 创建账户客户端
            lc = AccountClient(self.client)
            # 登录
            login_data = await lc.login(user_input.get("phone"), user_input.get("password"))
            login_status = login_data.get("code")
            _LOGGER.info("login info: login_status = %s", login_status)
            # Process the login response and handle accordingly
            if login_status == Code.SUCCESS.value:
                self.phone = user_input["phone"]
                self.password = user_input["password"]
                self.access_token = login_data.get("data", {}).get("accessToken")
                self.refresh_token = login_data.get("data", {}).get("refreshToken")
                self.client.access_token = login_data.get("data", {}).get("accessToken")
                hic = HouseInfoClient(self.client)
                # Fetch the house information
                house_infos_data = await hic.fetch_house_info()
                house_infos_status = house_infos_data.get("code")
                if house_infos_status != Code.SUCCESS.value:
                    errors["base"] = "fetch_house_info_error"
                    placeholders["code"] = house_infos_status
                else:
                    self.houses = house_infos_data.get("data", {}).get("houseInfos", [])
                    return await self.async_step_select_house()
            else:
                placeholders = {}
                if login_status == Code.LOGIN_ERROR.value:
                    errors["base"] = "invalid_auth"
                    placeholders["code"] = login_status
                elif login_status == Code.SYS_ERROR.value:
                    # Handle system error login_status
                    errors["base"] = "sys_error"
                    placeholders["code"] = login_status
                elif login_status != Code.SUCCESS.value:
                    # Handle unknown error login_status
                    errors["base"] = "unknown_error"
                    placeholders["code"] = login_status
                if len(login_data.get("data", {}).get("houseInfos", [])) == 0:
                    # Handle case where no houses are found
                    errors["base"] = "no_houses_found_error"

        # Show the authentication form with constructed errors
        # return self.async_show_form(
        #     step_id="auth",
        #     data_schema=vol.Schema(
        #         {
        #             vol.Required("phone"): str,
        #             vol.Required("password"): str,
        #         }
        #     ),
        #     errors=errors,
        #     description_placeholders=placeholders,
        # )

    async def async_step_select_house(self, user_input=None):
        """Handle the selection of a house by the user."""

        # Placeholder for error messages.
        errors = {}
        # Placeholders for description placeholders.
        placeholders = {}
        # Retrieve the list of pre-existing self.houses to exclude.
        existing_house = self.hass.data[DOMAIN].get("existing_house", {})

        # Create a self.houses list excluding already existing ones.
        houses_list = {
            house["houseNo"]: house["houseName"]
            for house in self.houses
            if house["houseNo"] not in existing_house
        }

        houses_dict = {
            house["houseNo"]: {
                "house_name": house["houseName"],
                "house_key": house["lanSecretKey"],
            }
            for house in self.houses
            if house["houseNo"] not in existing_house
        }

        # If no self.houses remain, handle the error.
        if len(houses_list) == 0:
            errors["base"] = "no_houses_found_error"
        # With user's house selection, create an entry for the selected house.
        if user_input is not None:
            return self.async_create_entry(
                title=houses_dict[user_input["house_no"]].get("house_name"),
                data={
                    PHONE: self.phone,
                    PASSWORD: self.password,
                    ADDRESS: HTTP_ADDRESS,
                    ACCESS_TOKEN: self.access_token,
                    REFRESH_TOKEN: self.refresh_token,
                    WS_ADDRESS: WEBSOCKET_ADDRESS,
                    APP_KEY: self.app_key,
                    APP_SECRET: self.app_secret,
                    HOUSE_NO: user_input["house_no"],
                    HOUSE_NAME: houses_dict[user_input["house_no"]].get("house_name"),
                    HOUSE_KEY: houses_dict[user_input["house_no"]].get("house_key"),
                },
            )

        # If no house has been selected yet, show the selection form.
        return self.async_show_form(
            step_id="select_house",
            data_schema=vol.Schema(
                {
                    vol.Required("house_no"): vol.In(houses_list),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )
