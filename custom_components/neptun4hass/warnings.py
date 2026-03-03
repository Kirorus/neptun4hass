"""Persistent notifications for device warnings."""

from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_update_limited_access_notification(
    hass: HomeAssistant,
    entry: ConfigEntry,
    denied_requests: list[str],
    *,
    access_flag: bool | None = None,
) -> None:
    """Create or dismiss a limited-access notification."""
    notification_id = f"{DOMAIN}_{entry.entry_id}_limited_access"
    if not denied_requests:
        persistent_notification.async_dismiss(hass, notification_id)
        return

    denied = ", ".join(sorted(set(denied_requests)))
    access_txt = "unknown"
    if access_flag is not None:
        access_txt = "true" if access_flag else "false"

    msg = (
        f"The Neptun device for '{entry.title}' denied access to some data requests ({denied}).\n\n"
        f"Device access flag: {access_txt}.\n\n"
        "This can limit counters and sensor names/values. "
        "If you have the Neptun mobile app open, close it (the controller allows only one TCP session). "
        "Also verify that local access is enabled on the controller."
    )

    persistent_notification.async_create(
        hass,
        msg,
        title="neptun4hass: Limited device access",
        notification_id=notification_id,
    )
