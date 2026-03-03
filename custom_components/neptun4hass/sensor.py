"""Sensors for neptun4hass integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    STATUS_ALARM,
    STATUS_MAIN_BATTERY,
    STATUS_SENSOR_BATTERY,
    STATUS_SENSOR_OFFLINE,
)
from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import NeptunEntity


def _decode_status(status: int) -> str:
    """Decode status bitmask to a human-readable string."""
    if status == 0:
        return "OK"
    parts: list[str] = []
    if status & STATUS_ALARM:
        parts.append("Alarm")
    if status & STATUS_MAIN_BATTERY:
        parts.append("Main battery low")
    if status & STATUS_SENSOR_BATTERY:
        parts.append("Sensor battery low")
    if status & STATUS_SENSOR_OFFLINE:
        parts.append("Sensor offline")
    return ", ".join(parts)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Neptun sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    # Water counters (always 4 lines)
    for idx in range(4):
        entities.append(NeptunWaterCounter(coordinator, idx))

    # Wireless sensor diagnostics
    for idx in range(len(coordinator.data.wireless_sensors)):
        entities.append(NeptunWirelessSignal(coordinator, idx))
        entities.append(NeptunWirelessBattery(coordinator, idx))

    # Device status
    entities.append(NeptunStatusSensor(coordinator))

    async_add_entities(entities)


class NeptunWaterCounter(NeptunEntity, SensorEntity):
    """Water meter counter sensor."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        sensor = coordinator.data.wired_sensors[index]
        super().__init__(
            coordinator,
            f"counter_{index}",
            f"{sensor.name or f'Line {index + 1}'} Counter",
        )
        self._index = index
        self._attr_entity_registry_enabled_default = sensor.line_type == "counter"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if self.coordinator.data is None:
            return False
        return (
            super().available
            and self.coordinator.data.wired_sensors[self._index].line_type == "counter"
        )

    @property
    def native_value(self) -> float | None:
        """Return counter value in cubic meters."""
        if self.coordinator.data is None:
            return None
        sensor = self.coordinator.data.wired_sensors[self._index]
        if sensor.line_type != "counter":
            return None
        step = sensor.step if sensor.step > 0 else 1
        return sensor.value / (1000.0 / step)


class NeptunWirelessSignal(NeptunEntity, SensorEntity):
    """Wireless sensor signal level."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        sensor = coordinator.data.wireless_sensors[index]
        super().__init__(
            coordinator,
            f"wireless_signal_{index}",
            f"{sensor.name or f'Wireless {index + 1}'} Signal",
        )
        self._index = index

    @property
    def native_value(self) -> int | None:
        """Return signal level."""
        if self.coordinator.data is None:
            return None
        if self._index >= len(self.coordinator.data.wireless_sensors):
            return None
        return self.coordinator.data.wireless_sensors[self._index].signal


class NeptunWirelessBattery(NeptunEntity, SensorEntity):
    """Wireless sensor battery level."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        sensor = coordinator.data.wireless_sensors[index]
        super().__init__(
            coordinator,
            f"wireless_battery_{index}",
            f"{sensor.name or f'Wireless {index + 1}'} Battery",
        )
        self._index = index

    @property
    def native_value(self) -> int | None:
        """Return battery level."""
        if self.coordinator.data is None:
            return None
        if self._index >= len(self.coordinator.data.wireless_sensors):
            return None
        return self.coordinator.data.wireless_sensors[self._index].battery


class NeptunStatusSensor(NeptunEntity, SensorEntity):
    """Device status sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(coordinator, "status", "Status")

    @property
    def native_value(self) -> str | None:
        """Return decoded status string."""
        if self.coordinator.data is None:
            return None
        return _decode_status(self.coordinator.data.status)
