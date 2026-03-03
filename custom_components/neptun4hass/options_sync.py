"""Sync and mismatch reporting for integration options."""

from __future__ import annotations

import logging

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant

from .const import CONF_CLOSE_ON_OFFLINE, CONF_LINE_IN_CONFIG, DOMAIN
from .neptun_client import DeviceData

_LOGGER = logging.getLogger(__name__)


def _bool_to_on_off(value: bool) -> str:
    return "ON" if value else "OFF"


async def async_update_options_mismatch_notification(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: DeviceData,
    *,
    log_mismatch: bool = True,
) -> None:
    """Report mismatch between stored options and device state.

    Only reports for options that are explicitly set in entry.options.
    """
    # device values
    dev_mask = device.line_in_config & 0x0F
    dev_close = bool(device.close_on_offline)

    # option values (if present)
    opt_mask = entry.options.get(CONF_LINE_IN_CONFIG)
    opt_close = entry.options.get(CONF_CLOSE_ON_OFFLINE)

    mismatches: list[str] = []
    if opt_mask is not None and int(opt_mask) != dev_mask:
        mismatches.append(
            f"{CONF_LINE_IN_CONFIG}: options=0x{int(opt_mask):02X} device=0x{dev_mask:02X}"
        )
    if opt_close is not None and bool(opt_close) != dev_close:
        mismatches.append(
            f"{CONF_CLOSE_ON_OFFLINE}: options={_bool_to_on_off(bool(opt_close))} device={_bool_to_on_off(dev_close)}"
        )

    notification_id = f"{DOMAIN}_{entry.entry_id}_options_mismatch"
    if not mismatches:
        persistent_notification.async_dismiss(hass, notification_id)
        return

    scan = entry.options.get(CONF_SCAN_INTERVAL)
    scan_text = f"{scan}s" if scan is not None else "(default)"

    msg = (
        f"Device settings differ from saved integration options for '{entry.title}'.\n\n"
        f"- "
        + "\n- ".join(mismatches)
        + "\n\n"
        f"Polling interval (local): {scan_text}\n\n"
        "To align the device with Home Assistant, open the integration options and click Save. "
        "To align Home Assistant with the device, update the options to match current device values."
    )

    if log_mismatch:
        _LOGGER.warning(
            "Options mismatch for entry '%s': %s",
            entry.title,
            "; ".join(mismatches),
        )

    persistent_notification.async_create(
        hass,
        msg,
        title="neptun4hass: Options mismatch",
        notification_id=notification_id,
    )
