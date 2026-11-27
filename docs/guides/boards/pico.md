<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Raspberry Pi Pico: USB MIDI

**Applies to:** Player v1; Player CC mapping requires H-14/controllerStream.
**You need:** Pico (non-Wi-Fi), USB data cable, supported CircuitPython UF2, 10 kΩ pot, jumper wires.
**Time:** 15–25 minutes.

## 1. Wire and install firmware

Disconnect USB while wiring. Connect pot ends to 3V3 OUT and GND, wiper to GP26 (ADC0).
Never connect 5 V to an ADC input. Hold BOOTSEL while plugging USB; install CircuitPython for
your exact board from circuitpython.org. Use a data cable.

**Check:** CIRCUITPY appears and the serial REPL is available.

## 2. Copy the example

From the headless checkout, first inspect the device-free declaration:

```sh
python -I examples/controllers/usb_midi_knob.py --print-config
```

Copy examples/controllers/usb_midi_knob.py to CIRCUITPY as code.py using your file manager.
If MIDI is disabled in your CircuitPython build, enable usb_midi in boot.py using its documented
boot-time API and reset. At the serial prompt type SEND only if you intend to send MIDI, then
A0 (or the board's documented GP26 alias).

**Check:** declaration shows channel 1, CC 74; firmware opens a USB MIDI output and sends
0..127 as the knob moves.

## 3. Connect to Wirescape

Follow ../OSC_MIDI_SETUP.md step 4 (owner MIDI consent only). Select the reported MIDI device
and map CC 74 channel 1 to a patch MIDI CC to CV or a Player control after H-14.

```sh
curl -fsS -N 'http://127.0.0.1:8770/api/v1/events?controller=1'
```

**Check:** after H-14 raw CC events and the intended mapped value change. Before H-14 use an
in-patch MIDI CC to CV witness, or mark Player mapping blocked.

## If it fails

| Symptom | Cause | Fix |
|---|---|---|
| No USB MIDI device | charge-only cable or MIDI disabled | data cable; verify boot.py USB configuration |
| No knob movement | wrong ADC alias/wiring | check 3V3/GND, wiper and board pinout |
| CC visible, target static | channel, pickup or missing capability | check mapping and H-14 |
| Need Wi-Fi OSC | this board lacks Wi-Fi | use USB MIDI or a network-capable board |
