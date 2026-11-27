<!-- SPDX-License-Identifier: GPL-3.0-only -->
# ESP32 family: Wi-Fi OSC and optional native USB MIDI

**Applies to:** Player v1, OSC In at LAB_PIN; controllerStream H-14; control port P1-e2 later.
**You need:** ESP32 variant supported by MicroPython, USB data/serial link, pot, trusted Wi-Fi;
native USB MIDI only on a variant and firmware with USB device support.
**Time:** 20–30 minutes.

## 1. Wire and prepare firmware

Use the exact board schematic. With power disconnected, connect the pot to 3.3 V and GND
and its wiper to a documented ADC-capable GPIO (prefer ADC1 on classic ESP32 when Wi-Fi is
active). Never apply 5 V to an ADC pin. Avoid boot/flash pins; ESP32, S2 and S3 pin maps differ.
Install MicroPython for your exact board and connect the serial REPL.

**Check:** REPL responds; chosen ADC pin is not reserved and supports the selected voltage range.

## 2. Configure the Wi-Fi OSC sender

```sh
python -I examples/controllers/wifi_osc_knob.py --print-config
```

Copy the example to the board and run interactively via the serial IDE. Enter the chosen GPIO,
trusted Wi-Fi details, engine LAN IPv4 address and SEND only with owner consent. It uses read_u16
and selects attenuation when supported; measure usable travel and adjust calibration in the source
if needed. Use /ws/knob/1 port 9000, arg 0, input 0..1 and CV in OSC In; see ../OSC_MIDI_SETUP.md
for route LAN and engine consent.

**Check:** the device-free declaration prints the expected address/port. On the owner-run test,
the row receives advance and the patch follows the knob, without exposing the Player API.

## 3. USB MIDI alternative

Classic ESP32 with a USB-to-UART bridge is not class-compliant USB MIDI. Only use the USB MIDI
example on an ESP32 variant with native USB and a CircuitPython build exposing usb_midi.

```sh
python -I examples/controllers/usb_midi_knob.py --print-config
```

Use the documented analog pin alias for your variant and the procedure in pico.md step 2.
Select and enable MIDI as in ../OSC_MIDI_SETUP.md; no LAN necessary.

**Check:** the device enumerates as MIDI and sends channel 1 CC 74; if unsupported, use OSC
rather than treating USB serial as MIDI.

## If it fails

| Symptom | Cause | Fix |
|---|---|---|
| ADC stops with Wi-Fi | ADC2 shared on some variants | choose a documented ADC1 pin |
| ADC clips early | attenuation/board voltage | verify datasheet and calibrate; never exceed pin limit |
| Wi-Fi fails | network band/credentials | verify 2.4 GHz trusted network |
| No OSC | address, port or LAN consent | compare route and example, verify receive count |
| No MIDI port | UART bridge, not native USB | use OSC or a supported native USB board |
