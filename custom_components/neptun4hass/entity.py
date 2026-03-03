"""Base entity for neptun4hass integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import NeptunCoordinator


class NeptunEntity(CoordinatorEntity[NeptunCoordinator]):
    """Base class for neptun4hass entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NeptunCoordinator, key: str) -> None:
        super().__init__(coordinator)
        mac = coordinator.data.mac
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=coordinator.data.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=coordinator.data.version,
        )
