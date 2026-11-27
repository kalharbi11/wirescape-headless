# SPDX-License-Identifier: GPL-3.0-only
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

from tools.ui_cost import analyze, engine_sample, members, kiosk_sample, tree_rss


def samples(ui):
    return [
        {
            "t": float(i),
            "dropouts": 10 + i // 900,
            "engine_restarts": 0,
            "engine_running": True,
            "player_fake": False,
            "audio_state": "running",
            "patch_index": 0,
            "audio_settings": {"sampleRate": 48000, "bufferFrames": 256,
                               "deviceId": "test-output"},
            "ui_active": ui,
            "invocation": "test-invocation" if ui else None,
            "cpu_usec": i * 200000 if ui else None,
            "processes": [
                {"pid": 100, "start": 1, "rss_bytes": 100000000},
                {"pid": 101, "start": 2, "rss_bytes": 150000000},
            ] if ui else [],
        }
        for i in range(1801)
    ]


def evidence():
    common = {
        "headless_sha": "a" * 40,
        "lab_sha": "b" * 40,
        "machine": "Raspberry Pi 5",
        "date": "2026-11-27",
        "patch_sha256": "c" * 64,
        "workload": "same repeatable workload",
        "browser": "Chromium test",
        "consent": "owner audio only",
    }
    return {
        "baseline": {**common, "samples": samples(False)},
        "ui": {**common, "play_30hz_observed": True, "samples": samples(True)},
    }


class UICostTests(unittest.TestCase):
    def test_descendants_and_cpu_one_core(self):
        data = evidence()
        result = analyze(data)
        self.assertEqual(result["status"], "pass")
        self.assertAlmostEqual(result["mean_cpu_percent"], 20)
        self.assertEqual(result["peak_rss_bytes"], 250000000)
        self.assertEqual(result["baseline_dropouts"], 2)
        self.assertEqual(result["ui_dropouts"], 2)

    def test_cpu_and_rss_limits(self):
        data = evidence()
        for i, sample in enumerate(data["ui"]["samples"]):
            sample["cpu_usec"] = i * 250000
            sample["processes"][1]["rss_bytes"] = 250000000
        self.assertEqual(analyze(data)["status"], "pass")
        data["ui"]["samples"][-1]["cpu_usec"] += 1
        self.assertEqual(analyze(data)["status"], "fail")
        data["ui"]["samples"][-1]["cpu_usec"] -= 1
        data["ui"]["samples"][1]["processes"][1]["rss_bytes"] += 1
        self.assertEqual(analyze(data)["status"], "fail")

    def test_missing_and_incomplete_evidence(self):
        for modify in (
            lambda d: d.pop("baseline"),
            lambda d: d["ui"].update(collection_error="interrupted"),
            lambda d: d["ui"]["samples"].pop(),
            lambda d: d["ui"]["samples"].pop(5),
            lambda d: d["ui"]["samples"][5].pop("dropouts"),
            lambda d: d["ui"]["samples"][5]["processes"][1].pop("rss_bytes"),
            lambda d: d["ui"].pop("play_30hz_observed"),
            lambda d: d["ui"].update(patch_sha256="d" * 64),
            lambda d: d["ui"]["samples"][5].update(engine_restarts=1),
            lambda d: d["ui"]["samples"][5].update(dropouts=0),
            lambda d: d["ui"]["samples"][5].update(invocation="restarted"),
        ):
            with self.subTest(modify=modify):
                data = evidence()
                modify(data)
                self.assertEqual(analyze(data)["status"], "inconclusive")

    def test_pid_reuse_not_conflated_with_cpu(self):
        data = evidence()
        for sample in data["ui"]["samples"][900:]:
            sample["processes"][1]["start"] = 999
        self.assertEqual(analyze(data)["status"], "pass")
        data["ui"]["samples"][900]["processes"].append(
            {"pid": 101, "start": 2, "rss_bytes": 1})
        self.assertEqual(analyze(data)["status"], "inconclusive")

    def test_missing_baseline_and_non_equal_dropouts(self):
        data = evidence()
        data["ui"]["samples"][-1]["dropouts"] += 1
        self.assertEqual(analyze(data)["status"], "fail")
        data["baseline"]["samples"][-1]["dropouts"] = None
        self.assertEqual(analyze(data)["status"], "inconclusive")

    def test_tree_rss_includes_all_members(self):
        self.assertEqual(tree_rss(samples(True)[0]["processes"]), 250000000)
        self.assertIsNone(tree_rss([{"pid": 1, "start": 1, "rss_bytes": None}]))
        self.assertIsNone(tree_rss([]))

    def test_recursive_membership_and_recycled_pid_during_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = root / "kiosk"
            child = group / "child"
            child.mkdir(parents=True)
            (group / "cgroup.procs").write_text("100\n")
            (child / "cgroup.procs").write_text("101\n")
            (group / "cpu.stat").write_text("usage_usec 1000\n")
            self.assertEqual(members(group), {100, 101})
            props = {"ActiveState": "active", "InvocationID": "test",
                     "ControlGroup": "/kiosk", "MainPID": "100"}
            first = {"pid": 100, "start": 1, "rss_bytes": 10}
            second = {"pid": 101, "start": 2, "rss_bytes": 20}
            with patch("tools.ui_cost.CGROUP", root), \
                 patch("tools.ui_cost.unit_properties", return_value=props), \
                 patch("tools.ui_cost.process_sample",
                       side_effect=[first, second, first, second]):
                self.assertEqual(tree_rss(kiosk_sample(True)["processes"]), 30)
            with patch("tools.ui_cost.CGROUP", root), \
                 patch("tools.ui_cost.unit_properties", return_value=props), \
                 patch("tools.ui_cost.process_sample",
                       side_effect=[first, second, first, {**second, "start": 3}]):
                with self.assertRaisesRegex(ValueError, "membership changed"):
                    kiosk_sample(True)

    def test_reject_fake_missing_identity_and_unavailable_audio(self):
        # Check both windows and mid-window loss, not just the first/last sample.
        mutations = (
            ("fake", lambda s: s.update(player_fake=True)),
            ("missing player identity", lambda s: s.pop("player_fake")),
            ("null player identity", lambda s: s.update(player_fake=None)),
            ("nonboolean player identity", lambda s: s.update(player_fake=0)),
            ("missing audio state", lambda s: s.pop("audio_state")),
            ("null audio state", lambda s: s.update(audio_state=None)),
            ("no device", lambda s: s.update(audio_state="no-device")),
            ("device lost", lambda s: s.update(audio_state="device-lost")),
            ("starting", lambda s: s.update(audio_state="starting")),
            ("stalled", lambda s: s.update(audio_state="stalled")),
            ("stopped", lambda s: s.update(audio_state="stopped")),
            ("unknown", lambda s: s.update(audio_state="unknown")),
            ("missing device ID", lambda s: s["audio_settings"].pop("deviceId")),
            ("null device ID", lambda s: s["audio_settings"].update(deviceId=None)),
            ("empty device ID", lambda s: s["audio_settings"].update(deviceId="")),
            ("blank device ID", lambda s: s["audio_settings"].update(deviceId="  ")),
            ("nonstring device ID", lambda s: s["audio_settings"].update(deviceId=0)),
            ("device changed", lambda s: s["audio_settings"].update(deviceId="other-output")),
        )
        for phase in ("baseline", "ui"):
            for label, mutate in mutations:
                with self.subTest(phase=phase, mutation=label):
                    data = evidence()
                    mutate(data[phase]["samples"][900])
                    self.assertEqual(analyze(data)["status"], "inconclusive")

    def test_both_windows_unavailable_or_fake(self):
        for mutation in (
            lambda s: s.update(player_fake=True),
            lambda s: s.pop("player_fake"),
            lambda s: s.update(audio_state="no-device"),
            lambda s: s["audio_settings"].update(deviceId=None),
            lambda s: s["audio_settings"].pop("deviceId"),
        ):
            with self.subTest(mutation=mutation):
                data = evidence()
                for phase in ("baseline", "ui"):
                    for sample in data[phase]["samples"]:
                        mutation(sample)
                self.assertEqual(analyze(data)["status"], "inconclusive")

    def test_engine_sample_preserves_real_audio_and_fake_identity(self):
        state = json.loads((Path(__file__).resolve().parents[1] /
                            "api/examples/state.json").read_text())

        def read():
            with patch("tools.ui_cost.urlopen",
                       return_value=io.BytesIO(json.dumps(state).encode())) as get:
                sample = engine_sample()
                get.assert_called_once_with("http://127.0.0.1:8770/api/v1/state", timeout=2)
                return sample

        fake = read()
        self.assertIs(fake["player_fake"], True)
        self.assertEqual(fake["audio_state"], "running")
        self.assertEqual(fake["audio_settings"]["deviceId"], state["engine"]["audio"]["deviceId"])
        self.assertEqual(fake["dropouts"], 0)
        state["player"]["fake"] = False
        state["engine"]["audio"].update(state="running", deviceId="test-output")
        real = read()
        self.assertIs(real["player_fake"], False)
        self.assertEqual(real["audio_state"], "running")
        self.assertEqual(real["audio_settings"]["deviceId"], "test-output")
        state["engine"]["audio"].update(state="no-device", deviceId=None)
        null_audio = read()
        self.assertEqual(null_audio["audio_state"], "no-device")
        self.assertIsNone(null_audio["audio_settings"]["deviceId"])
        del state["player"]["fake"]
        state["engine"]["audio"] = None
        missing = read()
        self.assertIsNone(missing["player_fake"])
        self.assertIsNone(missing["audio_state"])
        self.assertIsNone(missing["audio_settings"]["deviceId"])
        self.assertIsNone(missing["dropouts"])
