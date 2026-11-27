# SPDX-License-Identifier: GPL-3.0-only
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

from tools.ui_cost import analyze, members, kiosk_sample, tree_rss


def samples(ui):
    return [
        {
            "t": float(i),
            "dropouts": 10 + i // 900,
            "engine_restarts": 0,
            "engine_running": True,
            "patch_index": 0,
            "audio_settings": {"sampleRate": 48000, "bufferFrames": 256},
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
