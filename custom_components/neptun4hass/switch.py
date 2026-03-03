"""Switches for neptun4hass integration."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import REQUEST_DELAY
from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import NeptunEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Neptun switches."""
    coordinator = entry.runtime_data
    async_add_entities([
        NeptunValveSwitch(coordinator),
        NeptunCleaningSwitch(coordinator),
    ])


class NeptunValveSwitch(NeptunEntity, SwitchEntity):
    """Valve switch (open/close)."""

    _attr_icon = "mdi:valve"

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(coordinator, "valve", "Valve")

    @property
    def is_on(self) -> bool | None:
        """Return true if valve is open."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.valve_open

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Open the valve."""
        data = self.coordinator.data
        await self.coordinator.client.set_state(
            valve_open=True,
            cleaning_mode=data.cleaning_mode,
            close_on_offline=data.close_on_offline,
            line_in_config=data.line_in_config,
        )
        await asyncio.sleep(REQUEST_DELAY)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Close the valve."""
        data = self.coordinator.data
        await self.coordinator.client.set_state(
            valve_open=False,
            cleaning_mode=data.cleaning_mode,
            close_on_offline=data.close_on_offline,
            line_in_config=data.line_in_config,
        )
        await asyncio.sleep(REQUEST_DELAY)
        await self.coordinator.async_request_refresh()


class NeptunCleaningSwitch(NeptunEntity, SwitchEntity):
    """Cleaning/dry mode switch."""

    _attr_icon = "mdi:spray-bottle"

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(coordinator, "cleaning_mode", "Cleaning mode")

    @property
    def is_on(self) -> bool | None:
        """Return true if cleaning mode is active."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.cleaning_mode

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable cleaning mode."""
        data = self.coordinator.data
        await self.coordinator.client.set_state(
            valve_open=data.valve_open,
            cleaning_mode=True,
            close_on_offline=data.close_on_offline,
            line_in_config=data.line_in_config,
        )
        await asyncio.sleep(REQUEST_DELAY)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable cleaning mode."""
        data = self.coordinator.data
        await self.coordinator.client.set_state(
            valve_open=data.valve_open,
            cleaning_mode=False,
            close_on_offline=data.close_on_offline,
            line_in_config=data.line_in_config,
        )
        await asyncio.sleep(REQUEST_DELAY)
        await self.coordinator.async_request_refresh()
