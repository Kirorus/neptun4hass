"""The neptun4hass integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .options_sync import async_update_options_mismatch_notification
from .registry import async_sync_wired_line_entities


async def _async_update_listener(hass: HomeAssistant, entry: NeptunConfigEntry) -> None:
    """Handle options updates."""
    mac = entry.unique_id
    coordinator = entry.runtime_data
    if mac and coordinator and coordinator.data is not None:
        low_mask = int(entry.options.get("line_in_config", coordinator.data.line_in_config)) & 0x0F
        changed = await async_sync_wired_line_entities(hass, entry, mac, low_mask)
        if changed:
            await hass.config_entries.async_reload(entry.entry_id)
            return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: NeptunConfigEntry) -> bool:
    """Set up neptun4hass from a config entry."""
    coordinator = NeptunCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    domain_data = hass.data.setdefault(DOMAIN, {})
    logged: set[str] = domain_data.setdefault("mismatch_logged", set())
    if coordinator.data is not None:
        await async_update_options_mismatch_notification(
            hass,
            entry,
            coordinator.data,
            log_mismatch=entry.entry_id not in logged,
        )
        logged.add(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Ensure entity registry matches current device config even if it was
    # changed externally (or integration behavior changed between versions).
    mac = entry.unique_id
    if mac and coordinator.data is not None:
        low_mask = coordinator.data.line_in_config & 0x0F
        if await async_sync_wired_line_entities(hass, entry, mac, low_mask):
            hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
            return True
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NeptunConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
