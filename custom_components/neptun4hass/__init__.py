"""The neptun4hass integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import NeptunConfigEntry, NeptunCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: NeptunConfigEntry) -> bool:
    """Set up neptun4hass from a config entry."""
    coordinator = NeptunCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NeptunConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
