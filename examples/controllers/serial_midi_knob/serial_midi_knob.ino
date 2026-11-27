// SPDX-License-Identifier: MIT
// Owner-flashed only. Requires a proper MIDI OUT electrical interface on UART TX.
// Never connect TTL UART directly to a DIN MIDI input.
const int knobPin = A0;
const byte controller = 74;
int previous = -1;
void setup() {
  Serial.begin(31250);
}
void loop() {
  int value = analogRead(knobPin) * 127L / 1023;
  if (value != previous) {
    Serial.write((byte)0xB0);  // channel 1
    Serial.write(controller);
    Serial.write((byte)value);
    previous = value;
  }
  delay(50);
}
