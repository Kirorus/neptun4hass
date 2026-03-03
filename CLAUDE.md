# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this

`neptun4hass` — custom Home Assistant integration for the **Neptun ProW+ WiFi** leak protection system by SST. Local TCP protocol, no cloud.

## Architecture

```
neptun_client.py  →  coordinator.py  →  entity.py  →  binary_sensor.py / sensor.py / switch.py
   (TCP protocol)     (polling 30s)      (base)        (HA platforms)
```

- **neptun_client.py** — async TCP client: CRC16/CCITT, TLV packets, all protocol logic. Each request = new TCP connection (open → send → recv → close).
- **coordinator.py** — `DataUpdateCoordinator`. First poll: full chain (5 requests). Subsequent: system_state + counter_values only (names cached).
- **config_flow.py** — UI setup: IP → validate connection → MAC as unique_id.
- **entity.py** — base `CoordinatorEntity` with `DeviceInfo`.
- **Platforms**: `binary_sensor` (wired/wireless leak + alarm), `sensor` (counters m³, signal, battery, status), `switch` (valve, cleaning mode).

## Testing

```bash
python3 test_server.py          # mock Neptun device on :6350
python3 test_client.py [host] [port]  # default: 127.0.0.1:6350
```

Deploy to HA: copy `custom_components/neptun4hass/` → `config/custom_components/`, restart, add via UI.

## Protocol (verified on real hardware)

- **Port 6350**, binary TCP, CRC-16/CCITT (poly 0x1021, init 0xFFFF)
- Request: `[0x02, 0x54, 0x51, type, size_hi, size_lo, ...body, crc_hi, crc_lo]`
- SYSTEM_STATE (0x52) body: TLV tags. Others: header size = data size, body starts at offset 6.
- **SET_SYSTEM_STATE (0x57) is fire-and-forget** — no response from device. Use `_send_only()`.
- **REQUEST_DELAY = 0.5s** between connections — device drops fast reconnects.
- READ_TIMEOUT = 10s. Polling interval >= 5s (30s default).
- Names encoded CP1251, cached after first fetch.
- SET requires ALL fields (valve, dry, close_on_offline, line_in_config), not just changed ones.

## Reference sources

Protocol reverse-engineered from `neptun2mqtt/neptun.py` (sibling dir `../neptun2mqtt/`). Bug in reference line 628 (counter parsing) — fixed here.
