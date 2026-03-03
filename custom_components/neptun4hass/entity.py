"""Base entity for neptun4hass integration."""

from __future__ import annotations

import time

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import NeptunCoordinator


class NeptunEntity(CoordinatorEntity[NeptunCoordinator]):
    """Base class for neptun4hass entities."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: NeptunCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        mac = coordinator.data.mac
        entry_name = coordinator.config_entry.title.strip()
        entity_name = name.strip()

        self._attr_unique_id = f"{mac}_{key}"
        self._attr_name = f"{entry_name} {entity_name}" if entry_name else entity_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=entry_name or coordinator.data.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=coordinator.data.version,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        Home Assistant marks CoordinatorEntity unavailable when a single update
        fails. The Neptun controller can have transient failures (single-connection
        limit), so keep entities available for a short grace period.
        """
        if self.coordinator.last_update_success:
            return True

        last_ok = getattr(self.coordinator, "_last_success_monotonic", None)
        if last_ok is None:
            return False

        interval = self.coordinator.update_interval.total_seconds() if self.coordinator.update_interval else 30.0
        grace = max(60.0, interval * 2.5)
        return (time.monotonic() - float(last_ok)) < grace
