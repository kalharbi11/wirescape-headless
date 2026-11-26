# SPDX-License-Identifier: GPL-3.0-only
"""Shared test helpers: temporary bundles built from the example patches."""
import json
import pathlib
import shutil
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "bundle"


def mapped_patch() -> dict:
    """A synthetic patch with a Macro, a CC to CV and an OSC In driving parameters.

    `essentials.macro` is not in the catalogue at LAB_PIN (wirescape-test MOD-5); the bundle
    check reads patches as documents, so this is valid test material for resolution rules.
    """
    return {
        "format": "wirescape.native.patch", "version": 2,
        "modules": [
            {"id": 1, "module": "essentials.macro", "parameters": {"knob1": 0.5}},
            {"id": 2, "module": "midi.cc_to_cv", "config": {"rows": [{"channel": 1, "controller": 20}]}},
            {"id": 3, "module": "osc.in", "config": {"port": 9100, "rows": [{"pattern": "/ws/kick", "kind": "trigger"}]}},
            {"id": 4, "module": "essentials.vcf", "parameters": {"cutoff": 800, "resonance": 0.2}},
            {"id": 5, "module": "essentials.lfo", "parameters": {"rate": 1}},
            {"id": 6, "module": "essentials.output"},
        ],
        "connections": [
            {"kind": "modulation", "from": {"module": 1, "port": "knob1"}, "to": {"module": 4, "port": "cutoff"}, "amount": 1},
            {"kind": "modulation", "from": {"module": 2, "port": "cc1"}, "to": {"module": 4, "port": "resonance"}, "amount": 0.5},
            {"kind": "modulation", "from": {"module": 5, "port": "control"}, "to": {"module": 4, "port": "cutoff"}, "amount": 0.3},
        ],
    }


class TempBundle:
    """Copy of examples/bundle in a temp folder; `player` replaces player.json."""

    def __init__(self, player: dict | None = None, extra_patches: dict[str, dict] | None = None,
                 keep_player_json: bool = True):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "set"
        shutil.copytree(EXAMPLE, self.root)
        for name, doc in (extra_patches or {}).items():
            (self.root / "patches" / name).write_text(json.dumps(doc))
        if player is not None:
            (self.root / "player.json").write_text(json.dumps(player))
        elif not keep_player_json:
            (self.root / "player.json").unlink()

    def cleanup(self):
        self._tmp.cleanup()


def player(setlist=None, **top) -> dict:
    doc = {"format": "wirescape.player", "version": 1,
           "setlist": setlist if setlist is not None else [{"patch": "patches/basics-01-first-tone.json"}]}
    doc.update(top)
    return doc
