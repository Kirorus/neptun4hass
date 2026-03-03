"""Helpers for Home Assistant entity registry sync."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler


def _can_change_disabled_by(disabled_by: RegistryEntryDisabler | None) -> bool:
    """Return True if integration can change the disabled state."""
    return disabled_by is None or disabled_by == RegistryEntryDisabler.INTEGRATION


async def async_sync_wired_line_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    mac: str,
    low_mask: int,
) -> bool:
    """Enable/disable wired line entities to match current device config.

    We keep both entities for each wired line:
    - leak binary_sensor: unique_id = "{mac}_wired_sensor_{idx}"
    - counter sensor: unique_id = "{mac}_counter_{idx}"

    Only one of them is enabled by the integration at a time.
    Returns True if registry was modified.
    """
    low_mask &= 0x0F
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    by_unique_id = {e.unique_id: e for e in entries}

    changed = False
    for idx in range(4):
        is_counter = bool(low_mask & (1 << idx))

        counter_uid = f"{mac}_counter_{idx}"
        leak_uid = f"{mac}_wired_sensor_{idx}"

        counter_entry = by_unique_id.get(counter_uid)
        leak_entry = by_unique_id.get(leak_uid)

        want_counter_disabled_by = None if is_counter else RegistryEntryDisabler.INTEGRATION
        want_leak_disabled_by = RegistryEntryDisabler.INTEGRATION if is_counter else None

        if counter_entry is not None and _can_change_disabled_by(counter_entry.disabled_by):
            if counter_entry.disabled_by != want_counter_disabled_by:
                registry.async_update_entity(
                    counter_entry.entity_id,
                    disabled_by=want_counter_disabled_by,
                )
                changed = True

        if leak_entry is not None and _can_change_disabled_by(leak_entry.disabled_by):
            if leak_entry.disabled_by != want_leak_disabled_by:
                registry.async_update_entity(
                    leak_entry.entity_id,
                    disabled_by=want_leak_disabled_by,
                )
                changed = True

    return changed
