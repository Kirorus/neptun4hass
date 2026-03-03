"""Config flow for neptun4hass."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback

from .const import DEFAULT_PORT, DOMAIN
from .neptun_client import NeptunClient, NeptunConnectionError

_LOGGER = logging.getLogger(__name__)


CONF_LINE_IN_CONFIG = "line_in_config"
CONF_LINE_1_COUNTER = "line_1_counter"
CONF_LINE_2_COUNTER = "line_2_counter"
CONF_LINE_3_COUNTER = "line_3_counter"
CONF_LINE_4_COUNTER = "line_4_counter"

_LINE_COUNTER_KEYS: list[str] = [
    CONF_LINE_1_COUNTER,
    CONF_LINE_2_COUNTER,
    CONF_LINE_3_COUNTER,
    CONF_LINE_4_COUNTER,
]

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_NAME): str,
    }
)


class Neptun4hassConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for neptun4hass."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return Neptun4hassOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_required"
                return self.async_show_form(
                    step_id="user",
                    data_schema=STEP_USER_DATA_SCHEMA,
                    errors=errors,
                )

            client = NeptunClient(host, DEFAULT_PORT)

            try:
                device = await client.test_connection()
            except NeptunConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                mac = device.mac
                if not mac:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(mac)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_HOST: host,
                            CONF_NAME: name,
                            "port": DEFAULT_PORT,
                        },
                    )
            finally:
                await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


def _mask_from_user_input(user_input: dict[str, Any]) -> int:
    """Build a 4-bit line_in_config mask from options form input."""
    mask = 0
    for idx, key in enumerate(_LINE_COUNTER_KEYS):
        if user_input.get(key):
            mask |= 1 << idx
    return mask


def _defaults_from_mask(mask: int) -> dict[str, bool]:
    """Get checkbox defaults from a line_in_config mask."""
    defaults: dict[str, bool] = {}
    for idx, key in enumerate(_LINE_COUNTER_KEYS):
        defaults[key] = bool(mask & (1 << idx))
    return defaults


class Neptun4hassOptionsFlow(OptionsFlow):
    """Handle neptun4hass options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    def _get_client(self) -> tuple[NeptunClient, bool]:
        """Get a client instance.

        Prefer the runtime coordinator client (shared lock) when available.
        Returns (client, should_close).
        """
        runtime_data = getattr(self._config_entry, "runtime_data", None)
        shared = getattr(runtime_data, "client", None)
        if isinstance(shared, NeptunClient):
            return shared, False

        host = self._config_entry.data[CONF_HOST]
        port = self._config_entry.data.get("port", DEFAULT_PORT)
        return NeptunClient(host, port), True

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            requested_low_mask = _mask_from_user_input(user_input)
            client, should_close = self._get_client()

            try:
                current = await client.get_system_state()
                current_mask = current.line_in_config
                desired_mask = (current_mask & ~0x0F) | (requested_low_mask & 0x0F)

                await client.set_state(
                    valve_open=current.valve_open,
                    cleaning_mode=current.cleaning_mode,
                    close_on_offline=current.close_on_offline,
                    line_in_config=desired_mask,
                )

                applied = False
                for _ in range(3):
                    updated = await client.get_system_state()
                    if (updated.line_in_config & 0x0F) == (requested_low_mask & 0x0F):
                        applied = True
                        break

                if not applied:
                    errors["base"] = "cannot_apply"
                else:
                    return self.async_create_entry(
                        title="",
                        data={CONF_LINE_IN_CONFIG: requested_low_mask & 0x0F},
                    )
            except NeptunConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while applying options")
                errors["base"] = "unknown"
            finally:
                if should_close:
                    await client.close()

        default_mask = int(self._config_entry.options.get(CONF_LINE_IN_CONFIG, 0))
        client, should_close = self._get_client()
        try:
            device = await client.get_system_state()
            default_mask = device.line_in_config & 0x0F
        except NeptunConnectionError:
            if not errors:
                errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while loading options")
            if not errors:
                errors["base"] = "unknown"
        finally:
            if should_close:
                await client.close()

        defaults = _defaults_from_mask(default_mask)
        schema = vol.Schema(
            {
                vol.Required(CONF_LINE_1_COUNTER, default=defaults[CONF_LINE_1_COUNTER]): bool,
                vol.Required(CONF_LINE_2_COUNTER, default=defaults[CONF_LINE_2_COUNTER]): bool,
                vol.Required(CONF_LINE_3_COUNTER, default=defaults[CONF_LINE_3_COUNTER]): bool,
                vol.Required(CONF_LINE_4_COUNTER, default=defaults[CONF_LINE_4_COUNTER]): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
