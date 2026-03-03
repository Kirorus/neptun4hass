"""DataUpdateCoordinator for neptun4hass."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DOMAIN
from .neptun_client import DeviceData, NeptunClient, NeptunConnectionError
from .registry import async_sync_wired_line_entities

_LOGGER = logging.getLogger(__name__)

NeptunConfigEntry = ConfigEntry["NeptunCoordinator"]


class NeptunCoordinator(DataUpdateCoordinator[DeviceData]):
    """Coordinator that polls a Neptun ProW+ device."""

    config_entry: NeptunConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NeptunConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data[CONF_HOST]}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            config_entry=entry,
        )
        self.client = NeptunClient(
            host=entry.data[CONF_HOST],
            port=entry.data.get("port", DEFAULT_PORT),
        )
        self._names_cached = False
        self._last_wired_mask: int | None = None
        self._sync_task: asyncio.Task | None = None

    def _schedule_registry_sync(self, low_mask: int, mac: str) -> None:
        """Sync entity registry and reload entry if needed."""
        if self._sync_task is not None and not self._sync_task.done():
            return

        async def _run() -> None:
            if await async_sync_wired_line_entities(
                self.hass,
                self.config_entry,
                mac,
                low_mask,
            ):
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

        self._sync_task = self.hass.async_create_task(_run())

    async def _async_update_data(self) -> DeviceData:
        """Fetch data from device."""
        try:
            if not self._names_cached:
                device = await self.client.get_full_state()
                self._names_cached = True
            else:
                device = await self.client.get_system_state()
                await asyncio.sleep(0.5)
                await self.client.get_counter_values(device)
                # Preserve cached names from previous full state
                if self.data is not None:
                    for idx in range(4):
                        device.wired_sensors[idx].name = self.data.wired_sensors[idx].name
                        device.wired_sensors[idx].line_type = (
                            "counter" if device.line_in_config & (1 << idx) else "sensor"
                        )
                if device.sensor_count > 0 and self.data is not None:
                    device.wireless_sensors = list(self.data.wireless_sensors)
                    await asyncio.sleep(0.5)
                    await self.client.get_sensor_states(device)
            low_mask = device.line_in_config & 0x0F
            if self._last_wired_mask is None:
                self._last_wired_mask = low_mask
            elif low_mask != self._last_wired_mask:
                self._last_wired_mask = low_mask
                mac = self.config_entry.unique_id or device.mac
                if mac:
                    self._schedule_registry_sync(low_mask, mac)

            return device
        except NeptunConnectionError as err:
            raise UpdateFailed(f"Error communicating with Neptun: {err}") from err
