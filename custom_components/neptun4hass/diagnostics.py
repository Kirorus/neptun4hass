"""Diagnostics support for neptun4hass."""

from __future__ import annotations

from dataclasses import asdict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import NeptunCoordinator


TO_REDACT = {
    "host",
    "ip",
    "mac",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict:
    """Return diagnostics for a config entry."""
    coordinator: NeptunCoordinator | None = getattr(entry, "runtime_data", None)
    device_data = None
    coordinator_data = None

    if coordinator is not None:
        coordinator_data = {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
            "update_interval": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
            "names_cached": coordinator._names_cached,
            "fast_cycles_since_full": coordinator._fast_cycles_since_full,
            "last_wired_mask": coordinator._last_wired_mask,
            "last_denied_requests": coordinator.last_denied_requests,
            "last_denied_at": coordinator.last_denied_at,
        }
        if coordinator.data is not None:
            device_data = asdict(coordinator.data)

    diag = {
        "entry": {
            "domain": DOMAIN,
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
            "unique_id": entry.unique_id,
        },
        "coordinator": coordinator_data,
        "device_data": device_data,
    }

    return async_redact_data(diag, TO_REDACT)
