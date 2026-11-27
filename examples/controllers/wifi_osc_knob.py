# SPDX-License-Identifier: MIT
"""MicroPython Wi-Fi ADC to OSC; import or --print-config is device-free."""
import json
import struct
import sys

ADDRESS = "/ws/knob/1"
PORT = 9000


def pad(data):
    return data + b"\0" * (4 - len(data) % 4)


def osc_float(address, value):
    return pad(address.encode()) + pad(b",f") + struct.pack(">f", float(value))


def main():
    if "--print-config" in getattr(sys, "argv", []):
        print(json.dumps({"address": ADDRESS, "port": PORT, "range": [0, 1], "transport": "udp"}))
        return
    import time
    import network
    import socket
    from machine import ADC, Pin

    pin = int(input("ADC GPIO number: "))
    ssid = input("Trusted local Wi-Fi SSID: ")
    password = input("Wi-Fi password (serial input, not saved): ")
    host = input("Receiver LAN IPv4 address: ")
    if input("Owner consent to send UDP on LAN? Type SEND: ") != "SEND":
        return
    adc = ADC(Pin(pin))
    if hasattr(adc, "atten") and hasattr(ADC, "ATTN_11DB"):
        adc.atten(ADC.ATTN_11DB)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    sock = None
    try:
        wlan.connect(ssid, password)
        for _ in range(30):
            if wlan.isconnected():
                break
            time.sleep(1)
        if not wlan.isconnected():
            raise RuntimeError("Wi-Fi connection failed")
        destination = socket.getaddrinfo(host, PORT)[0][-1]
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        last = None
        while True:
            value = adc.read_u16() / 65535
            if last is None or abs(value - last) >= .01:
                sock.sendto(osc_float(ADDRESS, value), destination)
                last = value
            time.sleep_ms(50)
    finally:
        if sock:
            sock.close()
        wlan.disconnect()
        wlan.active(False)


if __name__ == "__main__":
    main()
