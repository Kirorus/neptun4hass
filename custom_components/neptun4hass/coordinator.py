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
                        device.wired_sensors[idx].line_type = self.data.wired_sensors[idx].line_type
                if device.sensor_count > 0 and self.data is not None:
                    device.wireless_sensors = list(self.data.wireless_sensors)
                    await asyncio.sleep(0.5)
                    await self.client.get_sensor_states(device)
            return device
        except NeptunConnectionError as err:
            raise UpdateFailed(f"Error communicating with Neptun: {err}") from err
