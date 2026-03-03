"""Binary sensors for neptun4hass integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import STATUS_ALARM
from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import NeptunEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Neptun binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []

    # Alarm sensor
    entities.append(NeptunAlarmSensor(coordinator))

    # Wired sensors (always 4 lines)
    for idx in range(4):
        entities.append(NeptunWiredSensor(coordinator, idx))

    # Wireless sensors
    for idx in range(len(coordinator.data.wireless_sensors)):
        entities.append(NeptunWirelessSensor(coordinator, idx))

    async_add_entities(entities)


class NeptunAlarmSensor(NeptunEntity, BinarySensorEntity):
    """Alarm binary sensor (any leak detected)."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_translation_key = "alarm"

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(coordinator, "alarm")
        self._attr_name = "Alarm"

    @property
    def is_on(self) -> bool | None:
        """Return true if alarm is active."""
        if self.coordinator.data is None:
            return None
        return bool(self.coordinator.data.status & STATUS_ALARM)


class NeptunWiredSensor(NeptunEntity, BinarySensorEntity):
    """Wired leak sensor."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        super().__init__(coordinator, f"wired_sensor_{index}")
        self._index = index
        sensor = coordinator.data.wired_sensors[index]
        self._attr_name = sensor.name or f"Wired sensor {index + 1}"

    @property
    def is_on(self) -> bool | None:
        """Return true if leak detected."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.wired_sensors[self._index].state != 0


class NeptunWirelessSensor(NeptunEntity, BinarySensorEntity):
    """Wireless leak sensor."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        super().__init__(coordinator, f"wireless_sensor_{index}")
        self._index = index
        sensor = coordinator.data.wireless_sensors[index]
        self._attr_name = sensor.name or f"Wireless sensor {index + 1}"

    @property
    def is_on(self) -> bool | None:
        """Return true if leak detected."""
        if self.coordinator.data is None:
            return None
        if self._index >= len(self.coordinator.data.wireless_sensors):
            return None
        return self.coordinator.data.wireless_sensors[self._index].state != 0
