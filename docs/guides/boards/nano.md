<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Arduino Nano family: MIDI

**Applies to:** Player v1; hardware mappings and PC require H-14/controllerStream.
**You need:** exact Nano variant, Arduino IDE, potentiometer, data cable, appropriate MIDI OUT
electrical interface and receiver/interface for a UART-only board.
**Time:** 20–30 minutes.

## 1. Identify the board and wire

Classic ATmega328P Nano has a USB serial bridge, not native USB MIDI. Nano-family boards
differ in voltage, pinout, ADC resolution and native USB/Wi-Fi. Check the exact board schematic.
With power disconnected, connect pot ends to the supported ADC reference supply and GND and
the wiper to A0. Do not exceed the pin's specified voltage.
For classic Nano, use a proper MIDI OUT current-loop interface on TX and a MIDI receiver/USB
MIDI interface; never wire TTL directly to DIN MIDI or to a different voltage domain.

**Check:** wiring and board voltage match the exact hardware; receiver is suitable for MIDI.

## 2. Flash the classic UART example

Open examples/controllers/serial_midi_knob/serial_midi_knob.ino in Arduino IDE; select the
exact classic Nano board, processor and upload port, then Verify and Upload. Disconnect the
MIDI interface if it interferes with uploading. Sketch sends MIDI at 31250 baud on UART,
not a USB-MIDI device. Do not use the serial monitor on that UART during transmission.

**Check:** IDE reports compile/upload success; a suitable connected MIDI receiver reports
channel 1 CC 74 in 0..127. Arduino compilation and hardware operation have not been measured in H0.

## 3. Native USB variants

For a Nano variant with supported CircuitPython native USB MIDI, inspect the device-free example:

```sh
python -I examples/controllers/usb_midi_knob.py --print-config
```

Use the board-specific CircuitPython build, enable MIDI if disabled, copy code.py as in pico.md
step 2, and choose the documented analog pin alias. A USB UART bridge cannot be converted to
class-compliant MIDI by copying this file.

**Check:** the board enumerates as MIDI, or use the UART path instead. For network-capable
variants with supported MicroPython, follow the Wi-Fi example in pico-2-w.md using the
correct board pinout, not its pin numbers.

## 4. Receive in Wirescape

Follow ../OSC_MIDI_SETUP.md step 4: owner consent, select the actual MIDI interface, enable it,
then use in-patch CC to CV or H-14 Player mappings.

```sh
curl -fsS -N 'http://127.0.0.1:8770/api/v1/events?controller=1'
```

**Check:** H-14 controller stream shows the intended interface and channel; before H-14 check
in-patch MIDI or record mapping blocked.

## If it fails

| Symptom | Cause | Fix |
|---|---|---|
| USB serial only | classic USB bridge | use proper MIDI OUT/interface, not raw serial |
| Upload fails | processor/bootloader selection or TX interference | select exact board, disconnect MIDI interface temporarily |
| MIDI data wrong | wrong baud/interface/voltage | use 31250 and compliant MIDI electrical interface |
| Range wrong | ADC resolution differs | use correct variant and scale |
| No mapping | capability missing or pickup | verify H-14 and mapped control |
