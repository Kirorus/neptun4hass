"""Async TCP client for Neptun ProW+ WiFi."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .const import (
    CONNECT_TIMEOUT,
    DEFAULT_PORT,
    PACKET_BACK_STATE,
    PACKET_COUNTER_NAME,
    PACKET_COUNTER_STATE,
    PACKET_ERROR,
    PACKET_HEADER,
    PACKET_SENSOR_NAME,
    PACKET_SENSOR_STATE,
    PACKET_SET_SYSTEM_STATE,
    PACKET_SYSTEM_STATE,
    READ_TIMEOUT,
    REQUEST_DELAY,
    SOCKET_BUFSIZE,
    TAG_ACCESS,
    TAG_DEVICE_INFO,
    TAG_MAC,
    TAG_NAME,
    TAG_STATE,
    TAG_WIRED_LINES,
)

_LOGGER = logging.getLogger(__name__)


def _crc16(data: bytearray | bytes, data_len: int = 0) -> tuple[int, int]:
    """CRC-16/CCITT (poly=0x1021, init=0xFFFF)."""
    polynom = 0x1021
    crc = 0xFFFF
    length = data_len if data_len > 0 else len(data)

    for j in range(length):
        b = data[j] & 0xFF
        crc ^= b << 8
        crc &= 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ polynom
            else:
                crc = crc << 1
            crc &= 0xFFFF

    return ((crc >> 8) & 0xFF, crc & 0xFF)


def _crc16_check(data: bytearray | bytes) -> bool:
    """Verify CRC16 of a packet."""
    i = len(data)
    crc_hi, crc_lo = _crc16(data, i - 2)
    return data[i - 2] == crc_hi and data[i - 1] == crc_lo


def _crc16_append(data: bytearray) -> bytearray:
    """Append CRC16 to a packet."""
    crc_hi, crc_lo = _crc16(data)
    return data + bytearray([crc_hi, crc_lo])


def _build_request(packet_type: int, body: bytearray | None = None) -> bytearray:
    """Build a request packet with header, type, size, body, and CRC."""
    if body is None:
        body = bytearray()
    size = len(body)
    packet = bytearray(PACKET_HEADER)
    packet.append(packet_type)
    packet.append((size >> 8) & 0xFF)
    packet.append(size & 0xFF)
    packet.extend(body)
    return _crc16_append(packet)


@dataclass
class WiredSensor:
    """Wired sensor/counter line."""

    name: str = ""
    line_type: str = "sensor"  # "sensor" or "counter"
    state: int = 0
    value: int = 0
    step: int = 0


@dataclass
class WirelessSensor:
    """Wireless sensor."""

    name: str = ""
    signal: int = 0
    battery: int = 0
    line: int = 0
    state: int = 0


@dataclass
class DeviceData:
    """Full device state."""

    device_type: str = ""
    version: str = ""
    name: str = ""
    mac: str = ""
    access: bool = False
    valve_open: bool = False
    sensor_count: int = 0
    relay_count: int = 0
    cleaning_mode: bool = False
    close_on_offline: bool = False
    line_in_config: int = 0
    status: int = 0
    wired_sensors: list[WiredSensor] = field(default_factory=lambda: [WiredSensor() for _ in range(4)])
    wireless_sensors: list[WirelessSensor] = field(default_factory=list)


class NeptunConnectionError(Exception):
    """Connection error."""


class NeptunProtocolError(Exception):
    """Protocol error."""


class NeptunAccessDenied(NeptunProtocolError):
    """Device denied access to requested data."""


def _packet_type(response: bytearray) -> int:
    if len(response) < 4:
        raise NeptunConnectionError("Response too short")
    return response[3]


class NeptunClient:
    """Async TCP client for Neptun ProW+ WiFi."""

    def __init__(self, host: str, port: int = DEFAULT_PORT) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._last_disconnect: float | None = None

    @property
    def host(self) -> str:
        return self._host

    async def _connect(self) -> None:
        """Establish TCP connection."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=CONNECT_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise NeptunConnectionError(
                f"Cannot connect to {self._host}:{self._port}"
            ) from err

    async def _ensure_request_delay(self) -> None:
        """Ensure a minimum delay between consecutive connections."""
        if self._last_disconnect is None:
            return
        elapsed = asyncio.get_running_loop().time() - self._last_disconnect
        if elapsed < REQUEST_DELAY:
            await asyncio.sleep(REQUEST_DELAY - elapsed)

    async def _disconnect(self) -> None:
        """Close TCP connection."""
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            finally:
                self._writer = None
                self._reader = None

    async def _send_and_receive(self, request: bytearray) -> bytearray:
        """Send request and read response."""
        async with self._lock:
            last_err: Exception | None = None
            for attempt in range(2):
                await self._ensure_request_delay()
                await self._connect()
                try:
                    self._writer.write(request)
                    await self._writer.drain()

                    data = await asyncio.wait_for(
                        self._reader.read(SOCKET_BUFSIZE),
                        timeout=READ_TIMEOUT,
                    )
                    if not data:
                        raise NeptunConnectionError("Empty response")

                    data = bytearray(data)
                    if len(data) < 4:
                        raise NeptunConnectionError("Response too short")

                    if not _crc16_check(data):
                        raise NeptunConnectionError("CRC check failed")

                    return data
                except NeptunConnectionError as err:
                    last_err = err
                    if attempt == 0 and str(err) in {"Empty response", "Response too short"}:
                        _LOGGER.debug("Retrying request after %s", err)
                        continue
                    raise
                finally:
                    await self._disconnect()
                    self._last_disconnect = asyncio.get_running_loop().time()

            # Should not happen, but keep mypy happy.
            raise NeptunConnectionError(str(last_err) if last_err else "Unknown error")

    async def _send_only(self, request: bytearray) -> None:
        """Send request without waiting for response (fire-and-forget)."""
        async with self._lock:
            await self._ensure_request_delay()
            await self._connect()
            try:
                self._writer.write(request)
                await self._writer.drain()
            finally:
                await self._disconnect()
                self._last_disconnect = asyncio.get_running_loop().time()

    def _parse_system_state(self, data: bytearray, device: DeviceData) -> None:
        """Parse SYSTEM_STATE response with TLV tags."""
        data_len = len(data) - 2  # exclude CRC
        offset = 6  # skip header

        while offset < data_len:
            if offset + 3 > data_len:
                break
            tag = data[offset]
            offset += 1
            tag_size = (data[offset] << 8) | data[offset + 1]
            offset += 2
            tag_start = offset

            if tag == TAG_DEVICE_INFO and tag_size >= 5:
                device.device_type = chr(data[tag_start]) + chr(data[tag_start + 1])
                device.version = (
                    chr(data[tag_start + 2]) + "."
                    + chr(data[tag_start + 3]) + "."
                    + chr(data[tag_start + 4])
                )
            elif tag == TAG_NAME:
                device.name = data[tag_start : tag_start + tag_size].decode("ascii", errors="replace")
            elif tag == TAG_MAC:
                device.mac = data[tag_start : tag_start + tag_size].decode("ascii", errors="replace")
            elif tag == TAG_ACCESS:
                device.access = tag_size > 0 and data[tag_start] > 0
            elif tag == TAG_STATE and tag_size >= 7:
                pos = tag_start
                device.valve_open = data[pos] == 1
                pos += 1
                device.sensor_count = data[pos]
                pos += 1
                device.relay_count = data[pos]
                pos += 1
                device.cleaning_mode = data[pos] == 1
                pos += 1
                device.close_on_offline = data[pos] == 1
                pos += 1
                device.line_in_config = data[pos]
                pos += 1
                device.status = data[pos]
            elif tag == TAG_WIRED_LINES and tag_size >= 4:
                for idx in range(min(4, tag_size)):
                    device.wired_sensors[idx].state = data[tag_start + idx]

            offset = tag_start + tag_size

    def _parse_counter_names(self, data: bytearray, device: DeviceData) -> None:
        """Parse COUNTER_NAME response."""
        offset = 4
        if offset + 2 > len(data) - 2:
            return
        # tag_size at offset 4-5
        offset += 2
        str_data = data[offset : len(data) - 2]
        names = str_data.split(b"\x00")
        if names and names[-1] == b"":
            names.pop(-1)

        mask = 1
        for idx, name_bytes in enumerate(names):
            if idx >= 4:
                break
            device.wired_sensors[idx].name = name_bytes.decode("cp1251", errors="replace")
            if device.line_in_config & mask:
                device.wired_sensors[idx].line_type = "counter"
            else:
                device.wired_sensors[idx].line_type = "sensor"
            mask <<= 1

    def _parse_counter_values(self, data: bytearray, device: DeviceData) -> None:
        """Parse COUNTER_STATE response."""
        data_len = len(data) - 2
        offset = 4
        if offset + 2 > data_len:
            return
        offset += 2  # skip tag_size

        idx = 0
        while offset + 5 <= data_len and idx < 4:
            # Fix the bug from reference: use correct offsets
            value = (
                (data[offset] << 24)
                | (data[offset + 1] << 16)
                | (data[offset + 2] << 8)
                | data[offset + 3]
            )
            device.wired_sensors[idx].value = value
            device.wired_sensors[idx].step = data[offset + 4]
            offset += 5
            idx += 1

    def _parse_sensor_names(self, data: bytearray, device: DeviceData) -> None:
        """Parse SENSOR_NAME response (wireless sensor names)."""
        offset = 4
        if offset + 2 > len(data) - 2:
            return
        offset += 2
        str_data = data[offset : len(data) - 2]
        names = str_data.split(b"\x00")
        if names and names[-1] == b"":
            names.pop(-1)

        device.wireless_sensors = []
        for name_bytes in names:
            sensor = WirelessSensor()
            sensor.name = name_bytes.decode("cp1251", errors="replace")
            device.wireless_sensors.append(sensor)

    def _parse_sensor_states(self, data: bytearray, device: DeviceData) -> None:
        """Parse SENSOR_STATE response (wireless sensor states)."""
        data_len = len(data) - 2
        offset = 4
        if offset + 2 > data_len:
            return
        offset += 2

        idx = 0
        while offset + 4 <= data_len and idx < len(device.wireless_sensors):
            device.wireless_sensors[idx].signal = data[offset]
            device.wireless_sensors[idx].line = data[offset + 1]
            device.wireless_sensors[idx].battery = data[offset + 2]
            device.wireless_sensors[idx].state = data[offset + 3]
            offset += 4
            idx += 1

    async def get_system_state(self) -> DeviceData:
        """Get system state (single request, returns device info + wired states)."""
        request = _build_request(PACKET_SYSTEM_STATE)
        response = await self._send_and_receive(request)
        ptype = _packet_type(response)
        if ptype == PACKET_ERROR:
            raise NeptunAccessDenied("SYSTEM_STATE")
        if ptype != PACKET_SYSTEM_STATE:
            raise NeptunProtocolError(f"Unexpected response type 0x{ptype:02X} for SYSTEM_STATE")
        device = DeviceData()
        self._parse_system_state(response, device)
        return device

    async def get_counter_names(self, device: DeviceData) -> None:
        """Get wired line names and update device in-place."""
        request = _build_request(PACKET_COUNTER_NAME)
        response = await self._send_and_receive(request)
        ptype = _packet_type(response)
        if ptype == PACKET_ERROR:
            raise NeptunAccessDenied("COUNTER_NAME")
        if ptype != PACKET_COUNTER_NAME:
            raise NeptunProtocolError(f"Unexpected response type 0x{ptype:02X} for COUNTER_NAME")
        self._parse_counter_names(response, device)

    async def get_counter_values(self, device: DeviceData) -> None:
        """Get counter values and update device in-place."""
        request = _build_request(PACKET_COUNTER_STATE)
        response = await self._send_and_receive(request)
        ptype = _packet_type(response)
        if ptype == PACKET_ERROR:
            raise NeptunAccessDenied("COUNTER_STATE")
        if ptype != PACKET_COUNTER_STATE:
            raise NeptunProtocolError(f"Unexpected response type 0x{ptype:02X} for COUNTER_STATE")
        self._parse_counter_values(response, device)

    async def get_sensor_names(self, device: DeviceData) -> None:
        """Get wireless sensor names and update device in-place."""
        request = _build_request(PACKET_SENSOR_NAME)
        response = await self._send_and_receive(request)
        ptype = _packet_type(response)
        if ptype == PACKET_ERROR:
            raise NeptunAccessDenied("SENSOR_NAME")
        if ptype != PACKET_SENSOR_NAME:
            raise NeptunProtocolError(f"Unexpected response type 0x{ptype:02X} for SENSOR_NAME")
        self._parse_sensor_names(response, device)

    async def get_sensor_states(self, device: DeviceData) -> None:
        """Get wireless sensor states and update device in-place."""
        request = _build_request(PACKET_SENSOR_STATE)
        response = await self._send_and_receive(request)
        ptype = _packet_type(response)
        if ptype == PACKET_ERROR:
            raise NeptunAccessDenied("SENSOR_STATE")
        if ptype != PACKET_SENSOR_STATE:
            raise NeptunProtocolError(f"Unexpected response type 0x{ptype:02X} for SENSOR_STATE")
        self._parse_sensor_states(response, device)

    async def get_full_state(self) -> DeviceData:
        """Perform full polling chain: system_state -> names -> values -> states.

        A short delay between requests is needed because the device drops
        connections that arrive too quickly after the previous one closes.
        """
        device = await self.get_system_state()
        await asyncio.sleep(REQUEST_DELAY)
        await self.get_counter_names(device)
        await asyncio.sleep(REQUEST_DELAY)
        await self.get_counter_values(device)
        if device.sensor_count > 0:
            await asyncio.sleep(REQUEST_DELAY)
            await self.get_sensor_names(device)
            await asyncio.sleep(REQUEST_DELAY)
            await self.get_sensor_states(device)
        return device

    async def set_state(
        self,
        valve_open: bool,
        cleaning_mode: bool,
        close_on_offline: bool,
        line_in_config: int,
    ) -> None:
        """Send SET_SYSTEM_STATE command."""
        body = bytearray([
            0x53,  # tag 'S'
            0x00, 0x04,  # tag length = 4
            0x01 if valve_open else 0x00,
            0x01 if cleaning_mode else 0x00,
            0x01 if close_on_offline else 0x00,
            line_in_config & 0xFF,
        ])
        request = _build_request(PACKET_SET_SYSTEM_STATE, body)
        await self._send_only(request)

    async def test_connection(self) -> DeviceData:
        """Test connection by getting system state. Raises on failure."""
        return await self.get_system_state()

    async def close(self) -> None:
        """Close any open connection."""
        await self._disconnect()
