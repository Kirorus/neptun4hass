"""Mock Neptun ProW+ WiFi TCP server for testing.

Response formats match the real device protocol as parsed in neptun2mqtt/neptun.py.

Key format differences:
- SYSTEM_STATE (0x52): header(6) + TLV tags + CRC(2)
- COUNTER_NAME (0x63): header(4) + tag_size(2) + null-terminated strings + CRC(2)
- COUNTER_STATE (0x43): header(4) + tag_size(2) + 5-byte records + CRC(2)
- SENSOR_NAME (0x4E):  header(4) + tag_size(2) + null-terminated strings + CRC(2)
- SENSOR_STATE (0x53): header(4) + tag_size(2) + 4-byte records + CRC(2)

Note: For non-SYSTEM_STATE responses, the parser in neptun.py reads
packet_type at offset [3] and then tag_size at offsets [4..5],
so the response header is actually the same 6-byte format but
with body = tag_size(2) + actual_data.
"""

import socket
import struct
import sys

HOST = "127.0.0.1"
PORT = 6350

# Mutable device state
valve = 0x00
dry = 0x00
cl_valve = 0x00
line_in_config = 0x03


def crc16(data: bytes | bytearray) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= (b & 0xFF) << 8
        crc &= 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return bytes([(crc >> 8) & 0xFF, crc & 0xFF])


def make_packet(packet_type: int, body: bytes) -> bytes:
    """Build response: [0x02, 0x54, 0x41, type, size_hi, size_lo, body, crc_hi, crc_lo]."""
    size = len(body)
    header = bytes([0x02, 0x54, 0x41, packet_type, (size >> 8) & 0xFF, size & 0xFF])
    packet = header + body
    return packet + crc16(packet)


def build_system_state_body() -> bytes:
    """Build SYSTEM_STATE TLV body (parsed at offset 6, tag-by-tag)."""
    body = bytearray()

    # Tag 0x49: type(2) + version(3) = "N3" + "2.2.0"
    info = bytes([ord("N"), ord("3"), ord("2"), ord("2"), ord("0")])
    body += bytes([0x49, 0x00, len(info)]) + info

    # Tag 0x4E: device name
    name = b"TestNeptun"
    body += bytes([0x4E, 0x00, len(name)]) + name

    # Tag 0x4D: MAC address
    mac = b"AA:BB:CC:DD:EE:FF"
    body += bytes([0x4D, 0x00, len(mac)]) + mac

    # Tag 0x41: access flag
    body += bytes([0x41, 0x00, 0x01, 0x01])

    # Tag 0x53: main state — 7 bytes:
    # valve_open, sensor_count, relay_count, flag_dry, flag_cl_valve, line_in_config, status
    body += bytes([
        0x53,
        0x00,
        0x07,
        valve,
        0x02,
        0x01,
        dry,
        cl_valve,
        line_in_config,
        0x00,
    ])

    # Tag 0x73: wired line states — 4 bytes (0=dry, 1=wet)
    body += bytes([0x73, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00])

    return bytes(body)


def build_counter_names_body() -> bytes:
    """Build COUNTER_NAME body (parsed at offset 4: tag_size(2) + strings).

    neptun.py:593-616: offset=4, read tag_size, then split by \\x00.
    The response packet_type byte is at offset [3].
    So the 6-byte header has: [0x02, 0x54, 0x41, 0x63, size_hi, size_lo]
    Then at offset 4 from response start = size_hi, size_lo — which IS the body size.

    Wait — let me re-read neptun.py parsing:
    offset = 4
    tag_size = data[offset] * 0x100 + data[offset + 1]
    offset += 2  # now offset = 6
    str_data = data[offset:]  # everything after (minus CRC which was already stripped)

    So the body of the packet (after the 6-byte header) must start with
    the tag_size repeated, then the actual data. BUT the header already has
    the size at bytes [4..5]. Let me check if the parser reads the BODY size
    or the HEADER size...

    In neptun.py:497-505, CRC is stripped: data_len = len(data) - 2; del data[data_len:]
    So after stripping CRC, data looks like:
    [0x02, 0x54, 0x41, packet_type, body_len_hi, body_len_lo, ...body...]

    For COUNTER_NAME: offset=4, reads data[4]*0x100+data[5] as tag_size.
    These are the body_len bytes from the header! So tag_size = body_len.
    Then offset=6, reads data[6:] as the string data.

    So body is just the null-terminated strings directly, and the header's
    size field tells the parser how big the data is. Perfect — simple.
    """
    names = b"Kitchen\x00Bathroom\x00Counter 1\x00Counter 2\x00"
    return names


def build_counter_values_body() -> bytes:
    """Build COUNTER_STATE body (parsed at offset 4: tag_size(2), then 5-byte records).

    Same logic: offset=4 reads header size bytes, offset=6 starts records.
    Each record: 4 bytes value (big-endian) + 1 byte step.
    """
    body = bytearray()
    # 4 wired lines: (value, step)
    counters = [
        (12345, 10),    # Kitchen: 12345 * 10/1000 = 123.45 m³
        (67890, 10),    # Bathroom: 678.90 m³
        (0, 1),         # Counter 1: 0
        (0, 1),         # Counter 2: 0
    ]
    for val, step in counters:
        body += struct.pack(">I", val) + bytes([step])
    return bytes(body)


def build_sensor_names_body() -> bytes:
    """Build SENSOR_NAME body (parsed at offset 4: tag_size(2), then null-terminated strings).

    Wireless sensor names. Index starts at 4 in the device model.
    """
    names = b"WL Hallway\x00WL Bathroom\x00"
    return names


def build_sensor_states_body() -> bytes:
    """Build SENSOR_STATE body (parsed at offset 4: tag_size(2), then 4-byte records).

    Each record: signal(1), line(1), battery(1), state(1).
    Index starts at 4 in the device model.
    """
    body = bytearray()
    sensors = [
        (85, 1, 95, 0),   # WL Hallway: signal=85%, line=1, battery=95%, state=dry
        (62, 2, 78, 0),   # WL Bathroom: signal=62%, line=2, battery=78%, state=dry
    ]
    for sig, line, bat, state in sensors:
        body += bytes([sig, line, bat, state])
    return bytes(body)


def handle_request(data: bytes) -> bytes | None:
    global valve, dry, cl_valve, line_in_config

    if len(data) < 8:
        return None

    packet_type = data[3]

    if packet_type == 0x52:  # SYSTEM_STATE
        print(
            f"  -> SYSTEM_STATE (valve={valve}, dry={dry}, cl_valve={cl_valve}, line_in_config=0x{line_in_config:02X})"
        )
        return make_packet(0x52, build_system_state_body())

    if packet_type == 0x63:  # COUNTER_NAME
        print("  -> COUNTER_NAME")
        return make_packet(0x63, build_counter_names_body())

    if packet_type == 0x43:  # COUNTER_STATE
        print("  -> COUNTER_STATE")
        return make_packet(0x43, build_counter_values_body())

    if packet_type == 0x4E:  # SENSOR_NAME
        print("  -> SENSOR_NAME")
        return make_packet(0x4E, build_sensor_names_body())

    if packet_type == 0x53:  # SENSOR_STATE
        print("  -> SENSOR_STATE")
        return make_packet(0x53, build_sensor_states_body())

    if packet_type == 0x57:  # SET_SYSTEM_STATE
        if len(data) >= 13:
            valve = data[9]
            dry = data[10]
            cl_valve = data[11]
            line_in_config = data[12]
            print(
                f"  -> SET_STATE: valve={valve}, dry={dry}, cl_valve={cl_valve}, line_in_config=0x{line_in_config:02X}"
            )
        return make_packet(0x00, b"")

    print(f"  -> UNKNOWN type 0x{packet_type:02X}")
    return None


def main():
    host = HOST
    port = PORT
    if len(sys.argv) > 1:
        host = sys.argv[1]
    if len(sys.argv) > 2:
        port = int(sys.argv[2])

    print(f"Neptun ProW+ mock server on {host}:{port}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen()
        print("Listening...")

        while True:
            conn, addr = s.accept()
            with conn:
                print(f"Connected: {addr}")
                try:
                    while True:
                        data = conn.recv(1024)
                        if not data:
                            break
                        print(f"  Recv {len(data)}B: {data.hex()}")
                        response = handle_request(data)
                        if response:
                            try:
                                conn.sendall(response)
                                print(f"  Sent {len(response)}B: {response.hex()}")
                            except (BrokenPipeError, ConnectionResetError):
                                print("  Client closed before response sent")
                                break
                except ConnectionResetError:
                    pass
                print(f"Disconnected: {addr}")


if __name__ == "__main__":
    main()
