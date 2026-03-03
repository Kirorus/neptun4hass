"""DataUpdateCoordinator for neptun4hass."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_FULL_REFRESH_CYCLES,
    DEFAULT_FULL_REFRESH_CYCLES,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .neptun_client import (
    DeviceData,
    NeptunAccessDenied,
    NeptunClient,
    NeptunConnectionError,
    NeptunProtocolError,
)
from .registry import async_sync_wired_line_entities
from .warnings import async_update_limited_access_notification

_LOGGER = logging.getLogger(__name__)

NeptunConfigEntry = ConfigEntry["NeptunCoordinator"]


class NeptunCoordinator(DataUpdateCoordinator[DeviceData]):
    """Coordinator that polls a Neptun ProW+ device."""

    config_entry: NeptunConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NeptunConfigEntry) -> None:
        scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        if scan_interval < MIN_SCAN_INTERVAL:
            scan_interval = MIN_SCAN_INTERVAL
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data[CONF_HOST]}",
            update_interval=timedelta(seconds=scan_interval),
            config_entry=entry,
        )
        self.client = NeptunClient(
            host=entry.data[CONF_HOST],
            port=entry.data.get("port", DEFAULT_PORT),
        )
        self._names_cached = False
        self._fast_cycles_since_full = 0
        self._last_wired_mask: int | None = None
        self._sync_task: asyncio.Task | None = None
        self._limited_access_logged = False

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
            denied: list[str] = []
            refresh_every = int(
                self.config_entry.options.get(
                    CONF_FULL_REFRESH_CYCLES,
                    DEFAULT_FULL_REFRESH_CYCLES,
                )
            )
            if refresh_every < 1:
                refresh_every = 1

            need_full = (
                not self._names_cached
                or refresh_every == 1
                or self._fast_cycles_since_full >= (refresh_every - 1)
            )

            if need_full:
                device = await self.client.get_system_state()

                # Try to pull names/values/states, but do not fail the update if
                # the device denies access.
                try:
                    await asyncio.sleep(0.5)
                    await self.client.get_counter_names(device)
                except NeptunAccessDenied:
                    denied.append("COUNTER_NAME")
                except NeptunProtocolError as err:
                    _LOGGER.debug("Protocol error in COUNTER_NAME: %s", err)

                try:
                    await asyncio.sleep(0.5)
                    await self.client.get_counter_values(device)
                except NeptunAccessDenied:
                    denied.append("COUNTER_STATE")
                except NeptunProtocolError as err:
                    _LOGGER.debug("Protocol error in COUNTER_STATE: %s", err)

                if device.sensor_count > 0:
                    try:
                        await asyncio.sleep(0.5)
                        await self.client.get_sensor_names(device)
                    except NeptunAccessDenied:
                        denied.append("SENSOR_NAME")
                    except NeptunProtocolError as err:
                        _LOGGER.debug("Protocol error in SENSOR_NAME: %s", err)

                    try:
                        await asyncio.sleep(0.5)
                        await self.client.get_sensor_states(device)
                    except NeptunAccessDenied:
                        denied.append("SENSOR_STATE")
                    except NeptunProtocolError as err:
                        _LOGGER.debug("Protocol error in SENSOR_STATE: %s", err)

                # If we couldn't fetch names/states, keep cached values where possible.
                if self.data is not None:
                    for idx in range(4):
                        if "COUNTER_NAME" in denied:
                            device.wired_sensors[idx].name = self.data.wired_sensors[idx].name
                        device.wired_sensors[idx].line_type = (
                            "counter" if device.line_in_config & (1 << idx) else "sensor"
                        )
                        if "COUNTER_STATE" in denied:
                            device.wired_sensors[idx].value = self.data.wired_sensors[idx].value
                            device.wired_sensors[idx].step = self.data.wired_sensors[idx].step
                    if device.sensor_count > 0 and device.wireless_sensors == []:
                        device.wireless_sensors = list(self.data.wireless_sensors)

                self._names_cached = True
                self._fast_cycles_since_full = 0
            else:
                device = await self.client.get_system_state()

                # If wireless sensor count changed (e.g. a new sensor was added),
                # run a full refresh to re-sync sensor names and list.
                if self.data is not None:
                    prev_count = len(self.data.wireless_sensors)
                    if device.sensor_count != prev_count:
                        device = await self.client.get_system_state()
                        self._names_cached = False
                        self._fast_cycles_since_full = refresh_every  # force full next
                    else:
                        await asyncio.sleep(0.5)
                        try:
                            await self.client.get_counter_values(device)
                        except NeptunAccessDenied:
                            denied.append("COUNTER_STATE")
                        except NeptunProtocolError as err:
                            _LOGGER.debug("Protocol error in COUNTER_STATE: %s", err)
                        # Preserve cached names from previous full state
                        for idx in range(4):
                            device.wired_sensors[idx].name = self.data.wired_sensors[idx].name
                            device.wired_sensors[idx].line_type = (
                                "counter" if device.line_in_config & (1 << idx) else "sensor"
                            )
                            if "COUNTER_STATE" in denied:
                                device.wired_sensors[idx].value = self.data.wired_sensors[idx].value
                                device.wired_sensors[idx].step = self.data.wired_sensors[idx].step
                        if device.sensor_count > 0:
                            device.wireless_sensors = list(self.data.wireless_sensors)
                            await asyncio.sleep(0.5)
                            try:
                                await self.client.get_sensor_states(device)
                            except NeptunAccessDenied:
                                denied.append("SENSOR_STATE")
                            except NeptunProtocolError as err:
                                _LOGGER.debug("Protocol error in SENSOR_STATE: %s", err)
                        self._fast_cycles_since_full += 1
                else:
                    # No previous cache, do a full refresh next.
                    device = await self.client.get_system_state()
                    self._names_cached = False
                    self._fast_cycles_since_full = refresh_every

            await async_update_limited_access_notification(
                self.hass,
                self.config_entry,
                denied,
                access_flag=device.access,
            )

            if denied and not self._limited_access_logged:
                _LOGGER.warning(
                    "Device denied access for '%s' (%s). access flag=%s",
                    self.config_entry.title,
                    ", ".join(sorted(set(denied))),
                    device.access,
                )
                self._limited_access_logged = True
            elif not denied and self._limited_access_logged:
                self._limited_access_logged = False
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
