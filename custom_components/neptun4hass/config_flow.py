"""Config flow for neptun4hass."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import callback

from .const import (
    CONF_CLOSE_ON_OFFLINE,
    CONF_LINE_IN_CONFIG,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .neptun_client import NeptunClient, NeptunConnectionError

_LOGGER = logging.getLogger(__name__)

CONFIRM_TIMEOUT_SECONDS = 15.0


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
            try:
                scan_interval = int(user_input[CONF_SCAN_INTERVAL])
            except (TypeError, ValueError):
                errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"
                scan_interval = DEFAULT_SCAN_INTERVAL

            if scan_interval < MIN_SCAN_INTERVAL:
                errors[CONF_SCAN_INTERVAL] = "scan_interval_min"

            requested_low_mask = _mask_from_user_input(user_input)
            requested_close = bool(user_input.get(CONF_CLOSE_ON_OFFLINE, False))

            if errors:
                return await self._show_form(errors)

            client, should_close = self._get_client()

            try:
                current = await client.get_system_state()
                current_mask = current.line_in_config
                desired_mask = (current_mask & ~0x0F) | (requested_low_mask & 0x0F)

                await client.set_state(
                    valve_open=current.valve_open,
                    cleaning_mode=current.cleaning_mode,
                    close_on_offline=requested_close,
                    line_in_config=desired_mask,
                )

                start = time.monotonic()
                deadline = start + CONFIRM_TIMEOUT_SECONDS
                last: Any = None
                last_err: Exception | None = None
                applied = False
                attempts = 0
                while time.monotonic() < deadline and attempts < 10:
                    attempts += 1
                    try:
                        remaining = max(0.1, deadline - time.monotonic())
                        updated = await asyncio.wait_for(
                            client.get_system_state(),
                            timeout=remaining,
                        )
                        last = updated
                        last_err = None
                    except NeptunConnectionError as err:
                        last_err = err
                        # Avoid busy-looping if the device is temporarily unavailable.
                        await asyncio.sleep(0.5)
                        continue
                    except TimeoutError as err:
                        last_err = err
                        break

                    if (
                        (updated.line_in_config & 0x0F) == (requested_low_mask & 0x0F)
                        and updated.close_on_offline == requested_close
                    ):
                        applied = True
                        break

                if not applied:
                    elapsed = time.monotonic() - start
                    if last_err is not None:
                        _LOGGER.warning(
                            "Failed to confirm applied options for '%s' (%.1fs, %d attempts): wanted line_in_config=0x%02X close_on_offline=%s; last error: %s",
                            self._config_entry.title,
                            elapsed,
                            attempts,
                            requested_low_mask & 0x0F,
                            requested_close,
                            last_err,
                        )
                    elif last is not None:
                        _LOGGER.warning(
                            "Device did not confirm applied options for '%s' (%.1fs, %d attempts): wanted line_in_config=0x%02X close_on_offline=%s; got line_in_config=0x%02X close_on_offline=%s",
                            self._config_entry.title,
                            elapsed,
                            attempts,
                            requested_low_mask & 0x0F,
                            requested_close,
                            int(last.line_in_config) & 0x0F,
                            bool(last.close_on_offline),
                        )
                    errors["base"] = "cannot_confirm"
                else:
                    new_options = dict(self._config_entry.options)
                    new_options[CONF_LINE_IN_CONFIG] = requested_low_mask & 0x0F
                    new_options[CONF_CLOSE_ON_OFFLINE] = requested_close
                    new_options[CONF_SCAN_INTERVAL] = scan_interval
                    return self.async_create_entry(title="", data=new_options)
            except NeptunConnectionError:
                prev_mask = self._config_entry.options.get(CONF_LINE_IN_CONFIG)
                prev_close = self._config_entry.options.get(CONF_CLOSE_ON_OFFLINE)
                if prev_mask == (requested_low_mask & 0x0F) and (
                    prev_close is None or prev_close == requested_close
                ):
                    new_options = dict(self._config_entry.options)
                    new_options[CONF_SCAN_INTERVAL] = scan_interval
                    return self.async_create_entry(title="", data=new_options)

                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while applying options")
                errors["base"] = "unknown"
            finally:
                if should_close:
                    await client.close()

        return await self._show_form(errors)

    async def _show_form(self, errors: dict[str, str]) -> ConfigFlowResult:
        default_mask = int(self._config_entry.options.get(CONF_LINE_IN_CONFIG, 0))
        default_close = bool(self._config_entry.options.get(CONF_CLOSE_ON_OFFLINE, False))
        default_scan = int(self._config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        if default_scan < MIN_SCAN_INTERVAL:
            default_scan = MIN_SCAN_INTERVAL

        client, should_close = self._get_client()
        try:
            device = await client.get_system_state()
            default_mask = device.line_in_config & 0x0F
            default_close = device.close_on_offline
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
                vol.Required(CONF_CLOSE_ON_OFFLINE, default=default_close): bool,
                vol.Required(CONF_SCAN_INTERVAL, default=default_scan): vol.Coerce(int),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
