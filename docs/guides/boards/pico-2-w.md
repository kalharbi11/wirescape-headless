<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Raspberry Pi Pico 2 W: Wi-Fi OSC or USB MIDI

**Applies to:** Player v1; in-patch OSC at LAB_PIN, controllerStream H-14, control port later.
**You need:** Pico 2 W, USB data cable, supported MicroPython or CircuitPython firmware, 10 kΩ pot,
trusted Wi-Fi for OSC.
**Time:** 20–30 minutes.

## 1. Wire and select firmware

Disconnect USB. Pot ends to 3V3 OUT/GND, wiper to GP26; no 5 V on ADC. For OSC install
MicroPython for Pico 2 W using BOOTSEL and the official UF2. For USB MIDI use supported
CircuitPython instead; do not copy MicroPython network code into CircuitPython.

**Check:** serial REPL is available; firmware matches the exact board.

## 2. Wi-Fi OSC

Inspect the example locally:

```sh
python -I examples/controllers/wifi_osc_knob.py --print-config
```

Using a MicroPython serial IDE, copy examples/controllers/wifi_osc_knob.py to the board;
run it interactively (do not install as an unattended boot script). At the prompts enter GPIO 26,
your trusted Wi-Fi details and the engine host's LAN IPv4 address, then SEND for owner consent.
Credentials are not saved by the example. Configure a matching OSC In row /ws/knob/1, port
9000, argument 0, range 0..1 and CV; enable route LAN and owner engine consent as in ../OSC_MIDI_SETUP.md.

**Check:** declaration reports port 9000 and range 0..1. Turn the knob; the engine's row receives
advance and the corresponding patch output changes. No Player control-port claim before P1-e2.

## 3. USB MIDI alternative

```sh
python -I examples/controllers/usb_midi_knob.py --print-config
```

With CircuitPython and USB MIDI enabled, follow pico.md step 2, using the appropriate ADC
alias for GP26. Select the device per ../OSC_MIDI_SETUP.md step 4.

**Check:** CC 74 on channel 1 appears in the intended in-patch MIDI row, or controller stream
after H-14. USB MIDI requires no LAN consent.

## If it fails

| Symptom | Cause | Fix |
|---|---|---|
| Wi-Fi won't connect | credentials/unsupported band | check trusted 2.4 GHz network |
| UDP not received | incorrect destination or route LAN consent | check host, port and both consent conditions |
| ADC error | pin alias/firmware mismatch | verify exact board pinout |
| No USB MIDI | incompatible firmware or disabled port | use supported CircuitPython and enable USB MIDI |
