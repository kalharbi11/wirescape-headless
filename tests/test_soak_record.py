# SPDX-License-Identifier: GPL-3.0-only
"""Diagnostic recorder contract without a real engine or any devices."""
import json
import os
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

from tools import soak_record as S


class SoakRecorder(unittest.TestCase):
    def test_current_process_sample(self):
        sample = S.process_sample(os.getpid())
        self.assertEqual(sample["pid"], os.getpid())
        self.assertGreater(sample["start_ticks"], 0)
        self.assertGreater(sample["rss_bytes"], 0)
        self.assertGreaterEqual(sample["cpu_seconds"], 0)

    def test_raw_status_missing_metrics_and_exclusive_output(self):
        original = S.run.EngineProcess
        forwarded = []
        def run_player(args):
            self.assertEqual(args, ["--engine", "unused", "--engine-arg=--null-audio"])
            engine = S.run.EngineProcess("unused")
            engine.proc = types.SimpleNamespace(pid=os.getpid())
            engine.on_push = forwarded.append
            engine._dispatch({"type": "hello", "session": "one"})
            engine._dispatch({"type": "status", "session": "stale", "gen": "9", "status": {}})
            engine._dispatch({"type": "status", "session": "one", "gen": "1",
                              "status": {"osc": {"dropped": 7}}})
            return 0

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "log.jsonl"
            args = ["--record", str(path), "--", "--engine", "unused", "--engine-arg=--null-audio"]
            with patch.object(S.run, "main", side_effect=run_player):
                self.assertEqual(S.main(args), 0)
                before = path.read_bytes()
                with self.assertRaises(FileExistsError):
                    S.main(args)
                self.assertEqual(path.read_bytes(), before)
            rows = [json.loads(line) for line in before.splitlines()]
        self.assertIs(S.run.EngineProcess, original)
        self.assertEqual([row["kind"] for row in rows], ["start", "hello", "status", "process", "stop"])
        self.assertEqual(len(forwarded), 1)
        self.assertEqual(rows[2]["osc"], {"dropped": 7})
        self.assertIsNone(rows[2]["audio"])
        self.assertIsNone(rows[2]["controller"])
        self.assertEqual(rows[2]["gen"], "1")
        self.assertEqual(rows[3]["engine"]["pid"], os.getpid())

    def test_failed_log_does_not_interrupt_engine_dispatch(self):
        forwarded = []
        original = S.run.EngineProcess
        class BrokenLog:
            calls = 0
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def write(self, line):
                self.calls += 1
                if self.calls >= 2:
                    raise OSError("simulated disk full")
        def run_player(args):
            engine = S.run.EngineProcess("unused")
            engine.proc = types.SimpleNamespace(pid=os.getpid())
            engine.on_push = forwarded.append
            engine._dispatch({"type": "hello", "session": "one"})
            engine._dispatch({"type": "status", "session": "one", "gen": "1", "status": {}})
            return 0
        log = BrokenLog()
        with patch.object(pathlib.Path, "open", return_value=log), \
             patch.object(S.run, "main", side_effect=run_player), \
             patch("sys.stderr") as stderr:
            self.assertNotEqual(S.main(["--record", "unused", "--", "--engine", "unused"]), 0)
            self.assertIn("recording failed", "".join(str(c) for c in stderr.write.call_args_list))
        self.assertEqual(len(forwarded), 1)
        self.assertEqual(log.calls, 2)
        self.assertIs(S.run.EngineProcess, original)
