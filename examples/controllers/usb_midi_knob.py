# SPDX-License-Identifier: MIT
"""CircuitPython native USB MIDI ADC example; --print-config opens no device."""
import json
import sys

CHANNEL = 1
CC = 74


def cc_message(channel, controller, value):
    if not 1 <= channel <= 16 or not 0 <= controller <= 127 or not 0 <= value <= 127:
        raise ValueError("MIDI channel 1..16 and data 0..127 required")
    return bytes((0xb0 | (channel - 1), controller, value))


def main():
    if "--print-config" in getattr(sys, "argv", []):
        print(json.dumps({"channel": CHANNEL, "cc": CC, "range": [0, 127]}))
        return
    import analogio
    import board
    import time
    import usb_midi

    if input("Owner consent to send USB MIDI? Type SEND: ") != "SEND":
        return
    pin = getattr(board, input("Analog pin name (e.g. A0): "))
    adc = analogio.AnalogIn(pin)
    port = next((p for p in usb_midi.ports if isinstance(p, usb_midi.PortOut)), None)
    if port is None:
        adc.deinit()
        raise RuntimeError("USB MIDI output port not enabled")
    try:
        last = None
        while True:
            value = adc.value * 127 // 65535
            if last is None or abs(value - last) >= 1:
                port.write(cc_message(CHANNEL, CC, value))
                last = value
            time.sleep(.05)
    finally:
        adc.deinit()


if __name__ == "__main__":
    main()
