"""Quick test script for NeptunClient against a real device or mock server.

Usage:
    python test_client.py [host] [port]

Default: 127.0.0.1:6350 (mock server)
"""

import asyncio
import importlib.util
import os
import sys
import types

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_components", "neptun4hass")


def _load_module(name: str, filename: str):
    """Load a module from file and register it in sys.modules."""
    full_name = f"custom_components.neptun4hass.{name}"
    spec = importlib.util.spec_from_file_location(full_name, os.path.join(BASE, filename))
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "custom_components.neptun4hass"
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Set up fake package hierarchy
sys.modules["custom_components"] = types.ModuleType("custom_components")
sys.modules["custom_components"].__path__ = [os.path.join(BASE, "..")]
pkg = types.ModuleType("custom_components.neptun4hass")
pkg.__path__ = [BASE]
pkg.__package__ = "custom_components.neptun4hass"
sys.modules["custom_components.neptun4hass"] = pkg

_load_module("const", "const.py")
client_mod = _load_module("neptun_client", "neptun_client.py")

NeptunClient = client_mod.NeptunClient


async def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 6350

    print(f"Connecting to {host}:{port}...")
    client = NeptunClient(host, port)

    try:
        print("\n=== Full state ===")
        device = await client.get_full_state()

        print(f"  Name:      {device.name}")
        print(f"  MAC:       {device.mac}")
        print(f"  Type:      {device.device_type}")
        print(f"  Version:   {device.version}")
        print(f"  Valve:     {'OPEN' if device.valve_open else 'CLOSED'}")
        print(f"  Cleaning:  {'ON' if device.cleaning_mode else 'OFF'}")
        print(f"  Status:    0x{device.status:02X}")
        print(f"  Sensors:   {device.sensor_count} wireless")

        print("\n--- Wired lines ---")
        for i, ws in enumerate(device.wired_sensors):
            print(f"  [{i}] {ws.name:20s} type={ws.line_type:8s} state={ws.state} value={ws.value} step={ws.step}")

        print("\n--- Wireless sensors ---")
        for i, ws in enumerate(device.wireless_sensors):
            print(f"  [{i}] {ws.name:20s} signal={ws.signal}% battery={ws.battery}% line={ws.line} state={ws.state}")

        # Test valve control
        print("\n=== Opening valve ===")
        await client.set_state(
            valve_open=True,
            cleaning_mode=device.cleaning_mode,
            close_on_offline=device.close_on_offline,
            line_in_config=device.line_in_config,
        )
        await asyncio.sleep(1)
        device2 = await client.get_system_state()
        print(f"  Valve after open: {'OPEN' if device2.valve_open else 'CLOSED'}")

        await asyncio.sleep(1)
        print("\n=== Closing valve ===")
        await client.set_state(
            valve_open=False,
            cleaning_mode=device.cleaning_mode,
            close_on_offline=device.close_on_offline,
            line_in_config=device.line_in_config,
        )
        await asyncio.sleep(1)
        device3 = await client.get_system_state()
        print(f"  Valve after close: {'OPEN' if device3.valve_open else 'CLOSED'}")

        print("\nAll tests passed!")

    except Exception as e:
        print(f"\nERROR: {e}")
        raise
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
