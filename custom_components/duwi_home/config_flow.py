"""Config flow for Duwi Home integration."""
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig

from .const import (
    ACCESS_TOKEN,
    ACCESS_TOKEN_EXPIRE_TIME,
    APP_KEY,
    APP_SECRET,
    DOMAIN,
    HOUSE_LAN_SECRET_KEY,
    HOUSE_NAME,
    HOUSE_NO,
    PASSWORD,
    PHONE,
    REFRESH_TOKEN,
    REFRESH_TOKEN_EXPIRE_TIME,
    FIRST_INIT,
)
from .duwi_iot.const import DuwiIotError
from .duwi_iot.smarthome.duwi_client import DuwiClient, UpdateTokenListener


_LOGGER = logging.getLogger(__name__)

# This class handles the configuration flow for the Duwi Home integration
class DuwiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Duwi Home."""

    # Use version 1 for the configuration flow
    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._app_key: str | None = None
        self._app_secret: str | None = None
        self._phone: str | None = None
        self._password: str | None = None
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._access_token_expire_time: int | None = None
        self._refresh_token_expire_time: int | None = None
        self._houses: list | None = []
        self._duwi_client: DuwiClient | None = None

    # Token refresh listener for the config flow
    class TokenRefreshListener(UpdateTokenListener):
        """Token refresh listener for config flow."""

        def __init__(self, flow):
            self.flow = flow

        async def on_token_refreshed(
            self,
            access_token: str,
            refresh_token: str,
            access_token_expire_time: int,
            refresh_token_expire_time: int
        ):
            """Handle token refresh."""
            _LOGGER.info("Token refreshed during config flow")
            self.flow._access_token = access_token
            self.flow._refresh_token = refresh_token
            self.flow._access_token_expire_time = access_token_expire_time
            self.flow._refresh_token_expire_time = refresh_token_expire_time

    # This method is called when the user initiates the configuration flow
    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""

        errors = {}
        placeholders = {}

        if user_input is not None:
            # Store user input
            self._app_key = user_input[APP_KEY]
            self._app_secret = user_input[APP_SECRET]
            self._phone = user_input[PHONE]
            self._password = user_input[PASSWORD]

            try:
                # Create Duwi client
                self._duwi_client = DuwiClient(
                    session=async_get_clientsession(self.hass),
                    app_key=self._app_key,
                    app_secret=self._app_secret,
                    update_token_listener=self.TokenRefreshListener(self)
                )

                # Attempt to login
                _LOGGER.info("Attempting to login with phone:%s", self._phone)
                login_success = await self._duwi_client.login(self._phone, self._password)

                if not login_success:
                    errors["base"] = "auth_error"
                    placeholders["error_msg"] = "账号或密码错误，请检查后重试"
                    return self.async_show_form(
                        step_id="user",
                        data_schema=vol.Schema({
                            vol.Required(APP_KEY): str,
                            vol.Required(APP_SECRET): str,
                            vol.Required(PHONE): str,
                            vol.Required(PASSWORD): str
                        }),
                        errors=errors,
                        description_placeholders=placeholders
                    )

                # Get tokens from client
                self._access_token = self._duwi_client.access_token
                self._refresh_token = self._duwi_client.refresh_token
                self._access_token_expire_time = self._duwi_client.access_token_expire_time
                self._refresh_token_expire_time = self._duwi_client.refresh_token_expire_time

                _LOGGER.info("Login successful, fetching house list")

                # Get house list
                houses = await self._duwi_client.get_house_list()

                if not houses or len(houses) == 0:
                    errors["base"] = "no_houses"
                    placeholders["error_msg"] = "未找到任何房屋，请先在Duwi App中添加房屋"
                    return self.async_show_form(
                        step_id="user",
                        data_schema=vol.Schema({
                            vol.Required(APP_KEY): str,
                            vol.Required(APP_SECRET): str,
                            vol.Required(PHONE): str,
                            vol.Required(PASSWORD): str
                        }),
                        errors=errors,
                        description_placeholders=placeholders
                    )

                self._houses = houses

                # If only one house, auto-select it
                if len(houses) == 1:
                    return await self.async_step_select_house({HOUSE_NO: houses[0].get('houseNo')})

                # Multiple houses, show selection form
                return await self.async_step_select_house()

            except ConfigEntryAuthFailed as err:
                errors["base"] = "auth_error"
                placeholders["error_msg"] = str(err)
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema({
                        vol.Required(APP_KEY): str,
                        vol.Required(APP_SECRET): str,
                        vol.Required(PHONE): str,
                        vol.Required(PASSWORD): str
                    }),
                    errors=errors,
                    description_placeholders=placeholders
                )
            except DuwiIotError as err:
                _LOGGER.error("Duwi IOT error: %s", err)
                errors["base"] = "duwi_iot_error"
                placeholders["error_msg"] = f"错误代码:{err.code},错误信息: {err.message}"
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema({
                        vol.Required(APP_KEY): str,
                        vol.Required(APP_SECRET): str,
                        vol.Required(PHONE): str,
                        vol.Required(PASSWORD): str
                    }),
                    errors=errors,
                    description_placeholders=placeholders
                )
            except Exception as err:
                _LOGGER.error("Unexpected error during login: %s", err, exc_info=True)
                errors["base"] = "unknown_error"
                placeholders["error_msg"] = f"发生未知错误: {err!s}"
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema({
                        vol.Required(APP_KEY): str,
                        vol.Required(APP_SECRET): str,
                        vol.Required(PHONE): str,
                        vol.Required(PASSWORD): str
                    }),
                    errors=errors,
                    description_placeholders=placeholders
                )
            finally:
                # Clean up client
                if self._duwi_client:
                    await self._duwi_client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(APP_KEY): str,
                vol.Required(APP_SECRET): str,
                vol.Required(PHONE): str,
                vol.Required(PASSWORD): str
            }),
            errors=errors,
            description_placeholders=placeholders
        )

    # This method is called when the user needs to select a house
    async def async_step_select_house(self, user_input: dict[str, Any] | None = None):
        """Handle the step where the user selects a house."""

        errors = {}
        placeholders = {}

        # Check for existing houses to avoid duplicates
        existing_houses = []
        for entry in self._async_current_entries():
            existing_houses.append(entry.data.get(HOUSE_NO))

        # Filter out already configured houses
        available_houses = [
            house for house in self._houses
            if house.get('houseNo') not in existing_houses
        ]

        if len(available_houses) == 0:
            errors["base"] = "all_houses_configured"
            return self.async_show_form(
                step_id="select_house",
                data_schema=vol.Schema({}),
                errors=errors,
                description_placeholders=placeholders
            )

        if user_input is not None:
            selected_house_no = user_input[HOUSE_NO]

            # Find the selected house
            selected_house = None
            for house in available_houses:
                if house.get('houseNo') == selected_house_no:
                    selected_house = house
                    break

            if not selected_house:
                errors["base"] = "invalid_house"
                return self.async_show_form(
                    step_id="select_house",
                    data_schema=vol.Schema({}),
                    errors=errors,
                    description_placeholders=placeholders
                )

            # Prepare data for config entry
            data = {
                APP_KEY: self._app_key,
                APP_SECRET: self._app_secret,
                PHONE: self._phone,
                ACCESS_TOKEN: self._access_token,
                REFRESH_TOKEN: self._refresh_token,
                ACCESS_TOKEN_EXPIRE_TIME: self._access_token_expire_time,
                REFRESH_TOKEN_EXPIRE_TIME: self._refresh_token_expire_time,
                HOUSE_NO: selected_house_no,
                HOUSE_NAME: selected_house.get('houseName', 'Unknown House'),
                HOUSE_LAN_SECRET_KEY: selected_house.get('lanSecretKey', ''),
                FIRST_INIT: True,
            }

            _LOGGER.info("Creating config entry for house: %s", selected_house.get('houseName'))

            # Create the config entry with persistent data
            return self.async_create_entry(
                title=selected_house.get('houseName', 'Duwi Home'),
                data=data
            )

        # Prepare house selection schema
        house_options = {house['houseNo']: house['houseName'] for house in available_houses}

        return self.async_show_form(
            step_id="select_house",
            data_schema=vol.Schema({
                vol.Required(HOUSE_NO): vol.In(house_options)
            }),
            errors=errors,
            description_placeholders=placeholders
        )

    # This method is called when the auth is error
    async def async_step_reauth(self, user_input: dict[str, Any] | None = None):
        """Handle reauthentication when tokens have expired."""
        errors = {}
        placeholders = {}

        entry = self._get_reauth_entry()

        app_key = entry.data.get(APP_KEY)
        app_secret = entry.data.get(APP_SECRET)
        phone = entry.data.get(PHONE)

        # The reauth flow is auto-initiated by Home Assistant with the entry's
        # persisted data as ``user_input`` (see config_entries._async_init_reauth),
        # which does not contain a password since passwords are never stored.
        # Only treat ``user_input`` as a form submission when it actually
        # contains a password; otherwise just show the form.
        if user_input is not None and PASSWORD in user_input:
            password = user_input[PASSWORD]

            try:
                self._duwi_client = DuwiClient(
                    session=async_get_clientsession(self.hass),
                    app_key=app_key,
                    app_secret=app_secret,
                    update_token_listener=self.TokenRefreshListener(self),
                )

                login_success = await self._duwi_client.login(phone, password)

                if not login_success:
                    errors["base"] = "auth_error"
                    placeholders["error_msg"] = "密码错误，请检查后重试"
                    return self.async_show_form(
                        step_id="reauth",
                        data_schema=vol.Schema({
                            vol.Required(APP_KEY,default=app_key):str,
                            vol.Required(APP_SECRET,default=app_secret):str,
                            vol.Required(PHONE,default=phone):TextSelector(TextSelectorConfig(read_only=True)),
                            vol.Required(PASSWORD): str,
                        }),
                        errors=errors,
                        description_placeholders=placeholders,
                    )

                new_data = entry.data.copy()
                new_data[ACCESS_TOKEN] = self._duwi_client.access_token
                new_data[REFRESH_TOKEN] = self._duwi_client.refresh_token
                new_data[ACCESS_TOKEN_EXPIRE_TIME] = self._duwi_client.access_token_expire_time
                new_data[REFRESH_TOKEN_EXPIRE_TIME] = self._duwi_client.refresh_token_expire_time

                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

            except ConfigEntryAuthFailed as err:
                errors["base"] = "auth_error"
                placeholders["error_msg"] = str(err)
            except DuwiIotError as err:
                _LOGGER.error("Duwi IOT error: %s", err)
                errors["base"] = "duwi_iot_error"
                placeholders["error_msg"] = f"错误代码:{err.code},错误信息: {err.message}"
            except Exception as err:
                _LOGGER.error("Unexpected error during reauth: %s", err, exc_info=True)
                errors["base"] = "unknown_error"
                placeholders["error_msg"] = f"发生未知错误: {err!s}"
            finally:
                if self._duwi_client:
                    await self._duwi_client.close()

            return self.async_show_form(
                step_id="reauth",
                data_schema=vol.Schema({
                    vol.Required(APP_KEY,default=app_key):str,
                    vol.Required(APP_SECRET,default=app_secret):str,
                    vol.Required(PHONE,default=phone):TextSelector(TextSelectorConfig(read_only=True)),
                    vol.Required(PASSWORD): str,
                }),
                errors=errors,
                description_placeholders=placeholders,
            )

        return self.async_show_form(
            step_id="reauth",
            data_schema=vol.Schema({
                vol.Required(APP_KEY,default=app_key):str,
                vol.Required(APP_SECRET,default=app_secret):str,
                vol.Required(PHONE,default=phone):TextSelector(TextSelectorConfig(read_only=True)),
                vol.Required(PASSWORD): str,
            }),
            errors=errors,
            description_placeholders=placeholders,
        )
