# SPDX-License-Identifier: MIT
"""A108 example: one OSC trigger per script button press (requires Player v1.1)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ws

trigger = ws.trig("Press")
press = ws.button("Press")
ws.start(name="button_counter", port=9000)
handled = 0
while True:
    current = press.press_count
    while handled < current:
        trigger.send()
        handled += 1
    ws.sleep(.02)
