# SPDX-License-Identifier: GPL-3.0-only
"""H-16: correlation, units, tails, provenance and honest missing evidence."""
import unittest
from tools.knob_latency import Collector, summarize, validate_provenance


class KnobLatencyTests(unittest.TestCase):
    def setUp(self):
        self.c = Collector(start_ns=1_000_000_000, duration_s=1, expected=3)

    def event(self, controller=1, t=1_100_000, value=64):
        return dict(kind="cc", deviceId="scripted", channel=1,
                    controller=controller, value=value, t=t)

    def observe(self, event, session="s1"):
        self.c.observe({"type": "controller", "session": session, "gen": "4",
                        "events": [event]})
        return self.c.row_for(event)

    def ack(self, row, re="p1", ns=1_105_000_000, ok=True, session="s1"):
        row["requests"].append({"command": {"type": "setParam", "moduleId": 2,
                                           "paramId": "frequency", "value": 64},
                                "reply": {"re": re, "ok": ok, "session": session},
                                "receipt_ns": ns})

    def test_units_percentiles_and_source_deficit(self):
        a, b = self.observe(self.event()), self.observe(self.event(2))
        self.ack(a, "p1", 1_101_000_000)
        self.ack(b, "p2", 1_112_000_000)
        s = summarize(self.c.rows, expected=3)
        self.assertEqual(s["paired"], 2)
        self.assertEqual(s["source_deficit"], 1)
        self.assertEqual(s["p50_ms"], 1.0)
        self.assertEqual(s["p99_ms"], 12.0)
        self.assertEqual(s["max_ms"], 12.0)

    def test_same_cc_value_and_timestamp_are_not_identity(self):
        a, b = self.event(), self.event()
        row_a, row_b = self.observe(a), self.observe(b)
        self.assertIsNot(row_a, row_b)
        self.ack(row_b)
        s = summarize(self.c.rows, expected=2)
        self.assertEqual(s["paired"], 1)
        self.assertEqual(s["unmatched"], 1)

    def test_reject_duplicate_reply_cross_session_negative_and_refusal(self):
        rows = [self.observe(self.event(i)) for i in range(5)]
        self.ack(rows[0], "p1")
        self.ack(rows[1], "p1")
        self.ack(rows[2], "p2", session="other")
        self.ack(rows[3], "p3", ns=1_099_999_999)
        self.ack(rows[4], "p4", ok=False)
        s = summarize(self.c.rows, expected=5)
        self.assertEqual(s["paired"], 0)
        self.assertEqual(s["invalid"], 5)
        self.assertIsNone(s["p99_ms"])

    def test_no_pair_for_fanout_or_non_parameter_request(self):
        a, b = self.observe(self.event()), self.observe(self.event(2))
        self.ack(a, "p1")
        self.ack(a, "p2")
        self.ack(b, "p3")
        b["requests"][0]["command"]["type"] = "setModAmount"
        s = summarize(self.c.rows, expected=2)
        self.assertEqual(s["invalid"], 2)
        self.assertEqual(s["paired"], 0)

    def test_window_and_missing_timestamp(self):
        self.assertIsNone(self.observe(self.event(t=999_999)))
        self.assertIsNone(self.observe(self.event(t=2_000_000)))
        row = self.observe(self.event(t=None))
        self.assertIsNotNone(row)
        self.ack(row)
        self.assertEqual(summarize(self.c.rows, expected=1)["invalid"], 1)

    def test_explicit_drop_counters(self):
        self.c.observe({"type": "status", "session": "s1",
                        "controller": {"events": 10, "dropped": {"fifo": 0, "latest": 2, "oversize": 0}}})
        self.c.player_dropped = 3
        self.assertEqual(self.c.engine_status["s1"]["dropped"]["latest"], 2)
        self.assertEqual(self.c.player_dropped, 3)

    def test_provenance_refuses_missing_invalid_clock(self):
        valid = dict(headless_sha="a"*40, lab_sha="b"*40, binary_sha256="c"*64,
                     platform="Linux", clock="CLOCK_MONOTONIC", ingress_unit="us", receipt_unit="ns")
        validate_provenance(valid)
        for key, value in (("headless_sha", "abc"), ("lab_sha", None),
                           ("clock", "wall"), ("platform", "Darwin"), ("receipt_unit", "ms")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_provenance({**valid, key: value})


if __name__ == "__main__":
    unittest.main()
