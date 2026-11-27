# SPDX-License-Identifier: GPL-3.0-only
"""H-3: the Player core with the fake engine (lab proposals/0025 §2.2–§2.4).

Restart backoff, the hang kill, the start sequence, the arbiter, the Program Change debounce,
state files and atomic saves (PG5 and PG6 in unit form), and the stdio engine adapter.
"""
import asyncio
import json
import os
import pathlib
import random
import signal
import subprocess
import sys
import tempfile
import unittest

from player import bundle as B, core as C, state as S
from player.core import CommandError, PlayerCore
from player.engine_proc import EngineProcess
from player.fake_engine import FakeEngine
from tests.helpers import ROOT, TempBundle

STDIO_ENGINE = ROOT / "tests" / "stdio_engine.py"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class CoreBase(unittest.IsolatedAsyncioTestCase):
    """A core over the example bundle; `self.fakes` holds every fake engine session."""

    engine_cls = FakeEngine
    player_json = None

    async def asyncSetUp(self):
        self.tb = TempBundle(self.player_json)
        self.bundle = B.load(self.tb.root)
        self.fakes = []
        self.delays = []
        self.state_dir = tempfile.TemporaryDirectory()
        self.store = S.StateStore(pathlib.Path(self.state_dir.name))
        self.core = self.make_core()

    def factory(self):
        f = self.engine_cls(status_hz=50)
        self.fakes.append(f)
        return f

    def make_core(self, **kw):
        core = PlayerCore({self.bundle.name: self.bundle}, self.factory, fake=True, store=self.store, **kw)
        real = core._schedule_restart

        def record(delay):
            self.delays.append(delay)
            real(0.0)  # run restarts at once; the delay itself is what is tested

        core._schedule_restart = record
        return core

    async def asyncTearDown(self):
        await self.core.close()
        self.tb.cleanup()
        self.state_dir.cleanup()

    @property
    def fake(self):
        return self.fakes[-1]

    async def until(self, pred, timeout=3.0):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            if pred():
                return
            await asyncio.sleep(0.01)
        self.fail("condition not reached")

    async def crash_and_wait(self):
        n = len(self.fakes)
        self.fake.crash()
        await self.until(lambda: len(self.fakes) == n + 1 and self.core.engine_info["state"] == "running"
                         and self.fake.graph is not None)

    def loads(self, fake=None):
        return [c for c in (fake or self.fake).commands if c["type"] == "loadGraph"]


# =========================================================================== supervision


class Supervisor(CoreBase):
    async def test_backoff_doubles_to_cap_and_never_gives_up(self):
        await self.core.start()
        for _ in range(10):
            await self.crash_and_wait()
        self.assertEqual(self.delays, [0.25, 0.5, 1, 2, 4, 8, 16, 30, 30, 30])
        self.assertEqual(self.core.engine_info["restarts"], 10)
        self.assertEqual(self.core.engine_info["lastExit"]["signal"], "SIGSEGV")
        self.assertEqual(self.core.engine_info["lastExit"]["code"], 139)

    async def test_backoff_resets_after_30s_healthy(self):
        clock = Clock()
        await self.core.close()
        self.core = self.make_core(clock=clock)
        await self.core.start()
        for _ in range(3):
            await self.crash_and_wait()
        self.assertEqual(self.delays, [0.25, 0.5, 1])
        clock.t += 29
        await asyncio.sleep(0.1)  # status pushes arrive while healthy, but not 30 s yet
        await self.crash_and_wait()
        self.assertEqual(self.delays[-1], 2)
        clock.t += 31
        await asyncio.sleep(0.1)
        await self.crash_and_wait()
        self.assertEqual(self.delays[-1], 0.25)

    async def test_hello_timeout_counts_as_crash(self):
        class Silent(FakeEngine):
            async def start(self):
                await asyncio.sleep(3600)

        made = []

        def factory():
            e = (Silent if not made else FakeEngine)(status_hz=50)
            made.append(e)
            self.fakes.append(e)
            return e

        old = C.HELLO_TIMEOUT
        C.HELLO_TIMEOUT = 0.1
        try:
            await self.core.close()
            self.core = PlayerCore({self.bundle.name: self.bundle}, factory, fake=True,
                                   initial=S.state_doc(self.bundle.name, 2, {}))
            await self.core.start()
            await self.until(lambda: self.core.engine_info["state"] == "running"
                             and self.core.current["index"] == 2 and self.fake.graph is not None, 2.0)
            self.assertEqual(len(self.loads()), 1)
        finally:
            C.HELLO_TIMEOUT = old
        self.assertEqual(self.core.engine_info["restarts"], 1)
        self.assertEqual(self.core.engine_info["lastExit"]["signal"], "start-failed")

    async def test_hang_is_killed_once_within_1_5_s(self):
        kills = []

        class SlowDeath(FakeEngine):
            async def kill(self):
                kills.append(1)
                if len(kills) == 1:
                    asyncio.get_running_loop().call_later(0.4, lambda: self._exit(None, "SIGKILL"))

        self.engine_cls = SlowDeath
        await self.core.close()
        self.core = self.make_core()
        await self.core.start()
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        self.fake.stall()
        await self.until(lambda: self.core.engine_info["restarts"] == 1)
        self.assertLess(loop.time() - t0, 1.5 + 0.5)  # 1 s gap + watchdog tick + the slow exit
        self.assertEqual(len(kills), 1)
        await self.until(lambda: self.core.engine_info["state"] == "running")

    async def test_start_sequence_hello_controller_stream_then_composed_load(self):
        class WithStream(FakeEngine):
            async def start(self):
                h = await super().start()
                h["capabilities"].append("controllerStream")
                return h

            def _handle(self, msg):
                if msg.get("type") == "controllerStream":
                    return {"kinds": msg["kinds"], "oscUnmatched": False}
                return super()._handle(msg)

        self.engine_cls = WithStream
        await self.core.close()
        self.core = self.make_core()
        await self.core.start()
        await self.core.command({"type": "set", "target": {"param": {"module": 2, "param": "frequency"}}, "value": 333})
        await self.crash_and_wait()
        types = [c["type"] for c in self.fake.commands]
        self.assertEqual(types[:2], ["controllerStream", "loadGraph"])
        self.assertEqual(B.find_module(self.fake.commands[1]["patch"], 2)["parameters"]["frequency"], 333)

    async def test_stop_closes_engine_and_marks_stopped(self):
        await self.core.start()
        await self.core.close()
        self.assertEqual(self.core.engine_info["state"], "stopped")
        self.assertEqual(self.core.engine_info["lastExit"]["code"], 0)
        self.assertEqual(self.delays, [])


# =========================================================================== arbiter


class Arbiter(CoreBase):
    def gate_loads(self, fake, refuse_index_patch=None):
        gate = asyncio.Event()
        real = fake.request

        async def slow(msg):
            if msg["type"] == "loadGraph":
                await gate.wait()
                if refuse_index_patch and msg["patch"] is not None and self._is(msg["patch"], refuse_index_patch):
                    return {"v": 0, "session": fake.session, "re": msg.get("id"), "ok": False, "gen": "1",
                            "code": "limit", "message": "Graph capacity exceeded"}
            return await real(msg)

        fake.request = slow
        return gate

    def _is(self, doc, patch_rel):
        disk = json.loads((self.tb.root / patch_rel).read_text())
        return [m["module"] for m in doc["modules"]] == [m["module"] for m in disk["modules"]]

    async def test_pending_is_drained_after_a_refused_load(self):
        await self.core.start()
        gate = self.gate_loads(self.fake, refuse_index_patch=self.bundle.entries[1].patch)
        first = asyncio.create_task(self.core.select(1))
        await asyncio.sleep(0.02)
        self.assertTrue((await self.core.select(3))["queued"])
        gate.set()
        await first  # the refusal of 1 is superseded by the pending 3
        self.assertEqual(self.core.current["index"], 3)
        self.assertIsNone(self.core.current["error"])

    async def test_refusal_error_stays_until_next_success(self):
        await self.core.start()
        gate = self.gate_loads(self.fake, refuse_index_patch=self.bundle.entries[2].patch)
        gate.set()
        with self.assertRaises(CommandError):
            await self.core.select(2)
        self.assertEqual(self.core.current["index"], 0)
        self.assertIn("limit", self.core.current["error"])
        await self.core.select(1)
        self.assertIsNone(self.core.current["error"])

    async def test_ack_equal_to_current_needs_no_extra_load(self):
        await self.core.start()
        gate = self.gate_loads(self.fake)
        first = asyncio.create_task(self.core.select(2))
        await asyncio.sleep(0.02)
        await self.core.select(2)
        gate.set()
        await first
        self.assertEqual(len(self.loads()), 2)  # boot + 2, the pending 2 equals the current entry


class ProgramChange(CoreBase):
    async def test_burst_of_20_pcs_in_100ms_gives_at_most_2_loads_and_ends_on_the_last(self):
        await self.core.start()
        before = len(self.loads())
        targets = [random.Random(7).randrange(6) for _ in range(19)] + [4]
        for n in targets:
            self.core.program_change(n)
            await asyncio.sleep(0.005)
        await self.until(lambda: self.core.current["index"] == 4 and not self.core.current["switching"]
                         and self.core._debounce is None)
        await asyncio.sleep(0.3)
        self.assertLessEqual(len(self.loads()) - before, 2)
        self.assertEqual(self.core.current["index"], 4)

    async def test_debounce_window_follows_player_json(self):
        self.tb.cleanup()
        self.tb = TempBundle()
        cfg = json.loads((self.tb.root / "player.json").read_text())
        cfg["programChange"] = {"enabled": True, "debounceMs": 0}
        (self.tb.root / "player.json").write_text(json.dumps(cfg))
        self.bundle = B.load(self.tb.root)
        await self.core.close()
        self.core = self.make_core()
        self.assertEqual(self.core.debounce_ms(), 0)
        await self.core.start()
        self.core.program_change(self._program_of(2))
        await self.until(lambda: self.core.current["index"] == 2)

    def _program_of(self, index):
        inv = {v: k for k, v in self.bundle.program_map().items()}
        return inv[index]

    async def test_pc_with_no_entry_is_ignored_and_counted(self):
        await self.core.start()
        self.core.program_change(127)
        await asyncio.sleep(0.25)
        self.assertEqual(self.core.current["index"], 0)
        self.assertTrue(any("127" in w and "Program Change" in w for w in self.core.state_doc()["warnings"]))

    async def test_debounced_step_counts_from_the_debounced_target(self):
        await self.core.start()
        for _ in range(3):
            self.core.debounced_step(1)
        await self.until(lambda: self.core.current["index"] == 3 and self.core._debounce is None)

    async def test_ui_select_skips_the_debounce(self):
        await self.core.start()
        await self.core.command({"type": "select", "index": 5})
        self.assertEqual(self.core.current["index"], 5)


# =========================================================================== state files


class AtomicWrites(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_atomic_write_replaces_and_leaves_no_temp(self):
        p = self.dir / "a.json"
        S.atomic_write_json(p, {"x": 1})
        S.atomic_write_json(p, {"x": 2})
        self.assertEqual(json.loads(p.read_text()), {"x": 2})
        self.assertEqual(sorted(x.name for x in self.dir.iterdir()), ["a.json"])

    def test_failed_write_keeps_the_old_file(self):
        p = self.dir / "a.json"
        S.atomic_write_json(p, {"x": 1})
        with self.assertRaises(TypeError):
            S.atomic_write_json(p, {"x": object()})
        self.assertEqual(json.loads(p.read_text()), {"x": 1})
        self.assertEqual(sorted(x.name for x in self.dir.iterdir()), ["a.json"])

    def test_load_falls_back_to_good_then_none(self):
        st = S.StateStore(self.dir)
        self.assertIsNone(st.load())
        doc = S.state_doc("set", 2, {2: {"param:1:x": 0.5}})
        st.save_good(doc)
        (self.dir / "state.json").write_text("{not json")
        self.assertEqual(st.load(), doc)
        (self.dir / "state.good.json").write_text('{"format":"other"}')
        self.assertIsNone(st.load())

    def test_wrong_format_or_version_is_unreadable(self):
        st = S.StateStore(self.dir)
        S.atomic_write_json(self.dir / "state.json", {**S.state_doc("b", 0, {}), "version": 2})
        self.assertIsNone(st.load())

    def test_pg6_unit_kill_9_during_saves_never_corrupts(self):
        """PG6 in unit form: SIGKILL a saver process mid-write; state.json always parses."""
        script = ("import sys,pathlib; sys.path.insert(0, sys.argv[2]);\n"
                  "from player import state as S\n"
                  "st=S.StateStore(pathlib.Path(sys.argv[1])); i=0\n"
                  "big={str(k): {f'param:{k}:p{j}': j*0.5 for j in range(200)} for k in range(20)}\n"
                  "while True:\n i+=1; st.save(S.state_doc('set', i % 7, big))\n")
        rnd = random.Random(1)
        S.StateStore(self.dir).save(S.state_doc("set", 0, {}))
        for _ in range(40):
            p = subprocess.Popen([sys.executable, "-I", "-c", script, str(self.dir), str(ROOT)])
            try:
                p.wait(rnd.uniform(0.05, 0.2))
                self.fail(f"saver exited early with {p.returncode}")
            except subprocess.TimeoutExpired:
                os.kill(p.pid, signal.SIGKILL)
                p.wait()
            doc = json.loads((self.dir / "state.json").read_text())
            self.assertEqual(doc["format"], "wirescape.player.state")


class Saves(CoreBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._old = C.SAVE_DELAY
        C.SAVE_DELAY = 0.1

    async def asyncTearDown(self):
        C.SAVE_DELAY = self._old
        await super().asyncTearDown()

    def saved(self):
        return json.loads((pathlib.Path(self.state_dir.name) / "state.json").read_text())

    async def test_good_copy_after_boot_and_save_on_switch(self):
        await self.core.start()
        good = json.loads((pathlib.Path(self.state_dir.name) / "state.good.json").read_text())
        self.assertEqual((good["bundle"], good["index"]), (self.bundle.name, 0))
        await self.core.select(3)
        self.assertEqual(self.saved()["index"], 3)

    async def test_values_save_after_the_quiet_delay(self):
        await self.core.start()
        await self.core.select(4)
        key = "param:2:frequency"
        for v in (100, 200, 300):
            await self.core.command({"type": "set", "target": {"param": {"module": 2, "param": "frequency"}}, "value": v})
            await asyncio.sleep(0.03)
        self.assertNotIn(key, self.saved()["values"].get("4", {}))  # still inside the quiet window
        await asyncio.sleep(0.2)
        self.assertEqual(self.saved()["values"]["4"][key], 300)

    async def test_close_saves(self):
        await self.core.start()
        await self.core.command({"type": "set", "target": {"param": {"module": 2, "param": "frequency"}}, "value": 210})
        await self.core.close()
        self.assertEqual(self.saved()["values"]["0"]["param:2:frequency"], 210)

    async def test_pg5_unit_boot_restores_bundle_index_and_values(self):
        await self.core.start()
        await self.core.select(5)
        await self.core.command({"type": "set", "control": "cutoff", "value": 2222})
        await self.core.close()
        self.core = self.make_core(initial=self.store.load())
        await self.core.start()
        self.assertEqual(self.core.current["index"], 5)
        self.assertEqual(B.find_module(self.loads()[0]["patch"], 2)["parameters"]["cutoff"], 2222)

    async def test_pg5_unit_corrupt_state_falls_back_to_good(self):
        await self.core.start()
        await self.core.select(2)
        await self.core.close()  # good copy is from boot (index 0); state.json has index 2
        (pathlib.Path(self.state_dir.name) / "state.json").write_text("garbage")
        self.assertEqual(self.store.load()["index"], 0)


# =========================================================================== stdio adapter


class StdioAdapter(unittest.IsolatedAsyncioTestCase):
    def proc(self, *extra):
        return EngineProcess(sys.executable, ["-I", str(STDIO_ENGINE), *extra])

    async def test_hello_request_and_clean_stop(self):
        e = self.proc()
        exits = []
        e.on_exit = lambda code, sig: exits.append((code, sig))
        hello = await e.start()
        self.assertEqual(hello["type"], "hello")
        patch = json.loads((ROOT / "examples/bundle/patches/basics-01-first-tone.json").read_text())
        r = await e.request({"type": "loadGraph", "patch": patch})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["gen"], "1")
        r = await e.request({"type": "nope"})
        self.assertEqual(r["code"], "invalid")
        await e.stop()
        self.assertEqual(exits, [(0, None)])

    async def test_kill_reports_sigkill_and_fails_pending(self):
        e = self.proc("--exit-on", "never")
        exits = []
        e.on_exit = lambda code, sig: exits.append((code, sig))
        await e.start()
        await e.kill()
        await asyncio.sleep(0.05)
        self.assertEqual(exits, [(None, "SIGKILL")])
        with self.assertRaises(ConnectionError):
            await e.request({"type": "panic"})

    async def test_exit_mid_request_fails_the_request(self):
        e = self.proc("--exit-on", "panic")
        exits = []
        e.on_exit = lambda code, sig: exits.append((code, sig))
        await e.start()
        with self.assertRaises(ConnectionError):
            await e.request({"type": "panic"})
        await asyncio.sleep(0.05)
        self.assertEqual(exits, [(3, None)])

    async def test_status_pushes_and_stderr_prefix(self):
        e = self.proc("--stderr-line", "hello from engine")
        pushes = []
        e.on_push = pushes.append
        with self.assertLogs("player.engine", "INFO") as logs:
            await e.start()
            await asyncio.sleep(0.2)
        self.assertTrue(any(p["type"] == "status" for p in pushes))
        self.assertIn("engine: hello from engine", "\n".join(logs.output))
        await e.stop()

    async def test_no_hello_raises(self):
        e = self.proc("--no-hello")
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(e.start(), 0.5)
        await e.kill()
        self.assertIsNotNone(e.proc.returncode)
        self.assertTrue(all(t.done() for t in e._tasks))

    async def test_core_restarts_a_killed_process_and_reloads(self):
        tb = TempBundle()
        b = B.load(tb.root)
        procs = []

        def factory():
            p = self.proc()
            procs.append(p)
            return p

        core = PlayerCore({b.name: b}, factory)
        try:
            await core.start()
            self.assertEqual(core.current["index"], 0)
            os.kill(procs[0].pid, signal.SIGKILL)
            loop = asyncio.get_running_loop()
            end = loop.time() + 4
            while loop.time() < end and not (len(procs) == 2 and core.engine_info["state"] == "running"
                                             and core.current["index"] == 0):
                await asyncio.sleep(0.02)
            self.assertEqual(core.engine_info["restarts"], 1)
            self.assertEqual(core.engine_info["lastExit"]["signal"], "SIGKILL")
        finally:
            await core.close()
            tb.cleanup()


if __name__ == "__main__":
    unittest.main()
