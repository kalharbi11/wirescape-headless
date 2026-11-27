# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"


def load(name):
    spec = importlib.util.spec_from_file_location(name, EX / "controllers" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ControllerExamples(unittest.TestCase):
    def test_osc_float_message(self):
        mod = load("wifi_osc_knob")
        packet = mod.osc_float("/ws/knob/1", 0.5)
        self.assertEqual(packet, b"/ws/knob/1\0\0,f\0\0" + struct.pack(">f", .5))

    def test_usb_midi_message(self):
        mod = load("usb_midi_knob")
        self.assertEqual(mod.cc_message(1, 74, 64), bytes((0xb0, 74, 64)))
        self.assertEqual(mod.cc_message(16, 0, 127), bytes((0xbf, 0, 127)))
        for args in ((0, 74, 64), (1, 128, 64), (1, 74, -1)):
            with self.assertRaises(ValueError):
                mod.cc_message(*args)

    def test_print_config_without_hardware(self):
        for file in (EX / "controllers/wifi_osc_knob.py", EX / "controllers/usb_midi_knob.py",
                     EX / "scripts/button_counter.py"):
            with self.subTest(file=file):
                result = subprocess.run([sys.executable, "-I", str(file), "--print-config"],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                doc = json.loads(result.stdout)
                self.assertIsInstance(doc, dict)
                if file.name == "button_counter.py":
                    self.assertEqual(doc["controls"][0]["type"], "button")
                    self.assertEqual(doc["oscIn"][0]["rows"][0]["pattern"], "/ws/press")
