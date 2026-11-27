# SPDX-License-Identifier: GPL-3.0-only
"""Prepare a separate source bundle with a deterministic first-tone gate probe."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from player.install import _fsync_tree
from player.state import atomic_write_json, atomic_write_bytes, fsync_dir

SOURCE = ROOT / "examples/bundle"
PATCH = "patches/smoke-first-tone.json"
SCRIPT = "scripts/smoke_gate.py"
PORT_IN, PORT_OUT = 9002, 9003


def make(dest: Path, port_in=PORT_IN, port_out=PORT_OUT):
    dest = dest.resolve()
    if dest.exists() or SOURCE == dest or SOURCE in dest.parents:
        raise ValueError("choose a new source-bundle directory outside examples/bundle")
    if not (1024 <= port_in <= 65535 and 1024 <= port_out <= 65535):
        raise ValueError("invalid UDP port")
    if port_in == port_out or {port_in, port_out} & {9000, 9100}:
        raise ValueError("choose distinct ports outside existing bundle routes")
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        stage = Path(tmp) / "bundle"
        shutil.copytree(SOURCE, stage)
        cfg = json.loads((stage / "player.json").read_text())
        patch = json.loads((stage / cfg["setlist"][0]["patch"]).read_text())
        patch["name"] = "First tone (smoke gate)"
        patch["description"] = "A quiet held tone and loopback gate witness; no keyboard required."
        patch.pop("ui", None)
        patch["modules"] = [m for m in patch["modules"] if m["id"] != 1]
        next(m for m in patch["modules"] if m["id"] == 4)["parameters"]["gain"] = .05
        patch["modules"] += [
            {"id": 101, "module": "osc.in", "config": {"port": port_in, "lan": False,
                "rows": [{"pattern": "/ws/smoke_gate", "argument": 0, "kind": "gate",
                          "input_min": 0, "input_max": 1, "output_min": 0, "output_max": 1,
                          "smoothing_ms": 0, "timeout_ms": 2000, "stale": "zero"}] +
                         [{"enabled": False} for _ in range(7)]}},
            {"id": 102, "module": "osc.out", "config": {"port": port_out, "rate_hz": 100,
                "rows": [{"address": "/ws/smoke_echo", "kind": "gate"}] +
                         [{"enabled": False} for _ in range(7)]}}]
        patch["connections"] = [c for c in patch["connections"] if c["from"]["module"] != 1]
        for module, port in ((3, "gate"), (102, "row1")):
            patch["connections"].append({"kind": "signal", "from": {"module": 101, "port": "row1"},
                                        "to": {"module": module, "port": port}})
        cfg["title"] = "Hardware smoke set"
        cfg["setlist"][0].update(patch=PATCH, title="First tone (smoke gate)",
                                 scripts=[{"file": SCRIPT, "port": port_in}])
        atomic_write_json(stage / PATCH, patch)
        atomic_write_json(stage / "player.json", cfg)
        script = f"""# SPDX-License-Identifier: GPL-3.0-only
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ws

gate = ws.gate("Smoke gate", address="/ws/smoke_gate")
ws.start(name="smoke_gate", port={port_in})
while True:
    gate.on()
    ws.sleep(.1)
"""
        atomic_write_bytes(stage / SCRIPT, script.encode())
        _fsync_tree(stage)
        if dest.exists():
            raise ValueError("destination already exists")
        os.rename(stage, dest)
        fsync_dir(dest.parent)


def listen():
    """Explicit owner-only loopback receiver; does not touch audio or MIDI."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", PORT_OUT))
        print(f"listening on localhost:{PORT_OUT}; Ctrl-C to stop", flush=True)
        try:
            while True:
                packet, _ = rx.recvfrom(2048)
                if packet.startswith(b"/ws/smoke_echo\0") and len(packet) >= 20:
                    print(f"graph gate: {struct.unpack('>f', packet[-4:])[0]:g}", flush=True)
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("make").add_argument("directory", type=Path)
    sub.add_parser("listen")
    args = parser.parse_args()
    if args.command == "make":
        make(args.directory)
        print("prepared:", args.directory)
    else:
        listen()


if __name__ == "__main__":
    main()
