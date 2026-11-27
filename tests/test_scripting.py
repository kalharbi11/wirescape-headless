# SPDX-License-Identifier: GPL-3.0-only
"""H-10: the script runner and helper (lab proposals/0025 §4.3, §4.5).

Devices off: scripts send UDP to a listener this test binds on 127.0.0.1.
"""
import asyncio
import json
import pathlib
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "scripting"))
import wsrun  # noqa: E402

WS = ROOT / "scripting" / "ws.py"
GEN = ROOT / "examples" / "scripts" / "generative_ws.py"
HEADER = "import os, sys\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nimport ws\n"


def parse_osc(data: bytes) -> tuple[str, list[float]]:
    end = data.index(b"\0")
    addr = data[:end].decode()
    i = (end + 4) & ~3
    tend = data.index(b"\0", i)
    tags = data[i + 1:tend].decode()
    j = (tend + 4) & ~3
    vals = [struct.unpack(">f", data[j + 4 * k:j + 4 * k + 4])[0] for k in range(len(tags))]
    return addr, vals


class Listener:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]
        self.got: list[tuple[float, str, list[float]]] = []

    def drain(self):
        while True:
            try:
                data = self.sock.recv(4096)
            except BlockingIOError:
                return self.got
            a, v = parse_osc(data)
            self.got.append((time.monotonic(), a, v))

    def close(self):
        self.sock.close()


class ScriptDir:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "scripts"
        self.root.mkdir()
        shutil.copy(WS, self.root / "ws.py")

    def write(self, name: str, body: str) -> pathlib.Path:
        p = self.root / name
        p.write_text(HEADER + textwrap.dedent(body))
        return p

    def cleanup(self):
        self.tmp.cleanup()


# =========================================================================== helper


class PrintConfig(unittest.TestCase):
    def test_generative_ws_declares_the_same_addresses(self):
        d = wsrun.print_config(GEN)
        self.assertEqual((d["format"], d["version"], d["name"], d["port"]), ("wirescape.script", 1, "generative_ws", 9000))
        addrs = set(wsrun.gate_addresses(d))
        self.assertEqual(addrs, {f"/ws/gate/{i}" for i in (1, 2, 3, 4)})
        patterns = [r["pattern"] for c in d["oscIn"] for r in c["rows"]]
        self.assertEqual(sorted(patterns), sorted(["/ws/pitch/*", "/ws/gate/*", "/ws/vel/*", "/ws/trig/*",
                                                   "/ws/cv/1", "/ws/cv/2", "/ws/cv/3", "/ws/cv/4"]))
        self.assertEqual(d["controls"], [{"id": "density", "type": "knob", "label": "Density", "min": 0, "max": 1,
                                          "default": 0.85}])

    def test_rows_follow_the_kind_rules(self):
        d = wsrun.print_config(GEN)
        rows = {r["label"]: r for c in d["oscIn"] for r in c["rows"]}
        self.assertEqual((rows["Voice pitch"]["input_max"], rows["Voice pitch"]["output_min"],
                          rows["Voice pitch"]["output_max"]), (127, -5, 5.583333))
        self.assertEqual((rows["Voice gate"]["timeout_ms"], rows["Voice gate"]["stale"]), (2000, "zero"))
        self.assertEqual((rows["Voice vel"]["input_max"], rows["Voice vel"]["output_max"]), (1, 1))
        self.assertEqual(rows["CV 1"]["smoothing_ms"], 5)
        self.assertEqual((rows["Drums"]["kind"], rows["Drums"]["smoothing_ms"]), ("trigger", 0))

    def test_committed_row_file_matches_the_declaration(self):
        d = wsrun.print_config(GEN)
        committed = json.loads((ROOT / "examples" / "osc_in_script_rows.json").read_text())
        self.assertEqual(committed["rows"], d["oscIn"][0]["rows"])

    def test_helper_copies_are_identical(self):
        for p in (ROOT / "examples/scripts/ws.py", ROOT / "examples/bundle/scripts/ws.py"):
            self.assertEqual(p.read_bytes(), WS.read_bytes(), p)
        self.assertEqual((ROOT / "examples/bundle/scripts/generative_ws.py").read_bytes(), GEN.read_bytes())
        self.assertIn("SPDX-License-Identifier: MIT", WS.read_text().splitlines()[0])

    def test_print_config_opens_no_socket_and_runs_no_body(self):
        sd = ScriptDir()
        try:
            p = sd.write("s.py", """
                import socket
                def refuse(*a, **k): raise SystemExit(7)
                socket.socket = refuse
                ws.gate("G")
                ws.start()
                raise SystemExit(9)
            """)
            self.assertEqual(wsrun.print_config(p)["outputs"][0]["address"], "/ws/g")
        finally:
            sd.cleanup()

    def test_more_than_8_rows_split_into_configs(self):
        sd = ScriptDir()
        try:
            p = sd.write("many.py", "\n".join(f"ws.cv('C{i}')" for i in range(11)) + "\nws.start(port=9005)\n")
            d = wsrun.print_config(p)
            self.assertEqual([len(c["rows"]) for c in d["oscIn"]], [8, 3])
            self.assertEqual([c["port"] for c in d["oscIn"]], [9005, 9005])
            self.assertEqual(d["oscIn"][1]["rows"][0]["label"], "C8")
        finally:
            sd.cleanup()

    def test_print_config_timeout_and_errors(self):
        sd = ScriptDir()
        try:
            slow = sd.write("slow.py", "import time\ntime.sleep(10)\n")
            with self.assertRaises(wsrun.ScriptError):
                wsrun.print_config(slow, timeout=0.5)
            bad = sd.write("bad.py", "raise RuntimeError('x')\n")
            with self.assertRaises(wsrun.ScriptError):
                wsrun.print_config(bad)
        finally:
            sd.cleanup()

    def test_all_control_types_declare(self):
        sd = ScriptDir()
        try:
            p = sd.write("c.py", """
                ws.knob("K", 0, 2, 1); ws.slider("S"); ws.toggle("T", True); ws.button("B")
                ws.dropdown("D", ["a", "b"]); ws.number("N", 0, 10, 3, step=1); ws.text("X", "hi")
                ws.notes("G", steps=8); ws.label("Hello")
                ws.start()
            """)
            types = [c["type"] for c in wsrun.print_config(p)["controls"]]
            self.assertEqual(types, ["knob", "slider", "toggle", "button", "dropdown", "number", "text", "notes", "label"])
        finally:
            sd.cleanup()


class BundleCheckWithScripts(unittest.TestCase):
    def test_check_scripts_reads_the_declaration_from_a_relative_path(self):
        r = subprocess.run([sys.executable, "-m", "player", "check", "examples/bundle", "--scripts", "--json"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        codes = [f["code"] for f in json.loads(r.stdout)["findings"]]
        # scene-03 runs generative_ws.py but has no OSC In rows: one warning per declared address
        self.assertEqual(codes.count("script-row-missing"), 8)


class PathRule(unittest.TestCase):
    def test_only_files_inside_the_root(self):
        sd = ScriptDir()
        try:
            sd.write("ok.py", "ws.start()\n")
            self.assertTrue(wsrun.resolve_script(sd.root, "ok.py").is_file())
            for rel in ("../ok.py", "/etc/passwd", "ws.txt", "missing.py"):
                with self.assertRaises(wsrun.ScriptError, msg=rel):
                    wsrun.resolve_script(sd.root, rel)
        finally:
            sd.cleanup()


# =========================================================================== runner


class RunnerBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sd = ScriptDir()
        self.udp = Listener()
        self.scripts = []

    async def asyncTearDown(self):
        for s in self.scripts:
            await s.stop()
        self.udp.close()
        self.sd.cleanup()

    def script(self, body: str, **kw) -> "wsrun.Script":
        p = self.sd.write("s.py", body)
        self.logs = []
        s = wsrun.Script(p, self.udp.port, on_log=self.logs.append, **kw)
        self.scripts.append(s)
        return s

    async def until(self, pred, timeout=5.0):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            self.udp.drain()
            if pred():
                return
            await asyncio.sleep(0.02)
        self.fail("condition not reached")

    def values(self, addr):
        return [v for _, a, v in self.udp.drain() if a == addr]


class Runner(RunnerBase):
    async def test_stop_sends_zero_to_every_declared_gate(self):
        s = self.script("""
            g = ws.gate("G"); v = ws.voice("Lead", voices=2)
            ws.start()
            g.on(); v.on(1, 60); v.on(2, 64)
            while True: ws.sleep(0.05)
        """)
        await s.start()
        await self.until(lambda: self.values("/ws/g") and s.declaration)
        await s.stop()
        await asyncio.sleep(0.1)
        for a in ("/ws/g", "/ws/lead_gate/1", "/ws/lead_gate/2"):
            self.assertEqual(self.values(a)[-1], [0.0], a)
        self.assertEqual(s.state, "stopped")

    async def test_a_script_that_ignores_stop_is_killed_and_gates_still_zero(self):
        s = self.script("""
            import signal, time
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            g = ws.gate("G"); ws.start(); g.on()
            while True: time.sleep(1)
        """)
        await s.start()
        await self.until(lambda: self.values("/ws/g") == [[1.0]] or len(self.values("/ws/g")) > 0)
        t0 = time.monotonic()
        await s.stop()
        took = time.monotonic() - t0
        self.assertGreater(took, wsrun.STOP_WAIT + wsrun.TERM_WAIT - 0.2)
        self.assertLess(took, wsrun.STOP_WAIT + wsrun.TERM_WAIT + 1.5)
        self.assertLess(s.last_exit, 0)  # killed
        await asyncio.sleep(0.1)
        self.assertEqual(self.values("/ws/g")[-1], [0.0])

    async def test_crash_restarts_with_backoff_and_zeros_gates(self):
        s = self.script("""
            g = ws.gate("G"); ws.start(); g.on()
            raise SystemExit(1)
        """)
        await s.start()
        await self.until(lambda: s.restarts >= 3, 4.0)
        self.assertEqual(s.delays[:3], [0.25, 0.5, 1.0])
        got = [v for _, a, v in self.udp.got if a == "/ws/g"]
        self.assertIn([0.0], got)
        self.assertEqual(s.last_exit, 1)

    async def test_backoff_resets_after_30s_up(self):
        clock = [0.0]
        s = self.script("""
            ws.start()
            ws.sleep(0.4)
            raise SystemExit(1)
        """, clock=lambda: clock[0])
        await s.start()
        await self.until(lambda: s.restarts >= 2 and s.state == "running", 4.0)
        self.assertEqual(s.delays, [0.25, 0.5])
        clock[0] += 31  # the current run "lasts" 31 s before it crashes
        await self.until(lambda: s.restarts >= 3, 3.0)
        self.assertEqual(s.delays, [0.25, 0.5, 0.25])

    async def test_flood_cap_1000_per_second_and_drops_reported(self):
        s = self.script("""
            c = ws.cv("C"); ws.start()
            for i in range(5000): c.send(0.5)
            while True: ws.sleep(0.1)
        """)
        await s.start()
        await self.until(lambda: s.drops > 0, 4.0)
        sent = self.values("/ws/c")
        self.assertLessEqual(len(sent), 1000 + 50)
        self.assertGreaterEqual(s.drops, 3900)

    async def test_held_gate_is_resent_every_500ms(self):
        s = self.script("""
            g = ws.gate("G"); ws.start(); g.on()
            ws.sleep(1.7)
            g.off()
            while True: ws.sleep(0.1)
        """)
        await s.start()
        await self.until(lambda: [0.0] in self.values_seen("/ws/g"), 4.0)
        ones = [t for t, a, v in self.udp.got if a == "/ws/g" and v == [1.0]]
        self.assertGreaterEqual(len(ones), 4)  # the on, then about every 500 ms for 1.7 s
        gaps = [b - a for a, b in zip(ones, ones[1:])]
        self.assertTrue(all(0.35 < g < 0.75 for g in gaps), gaps)

    def values_seen(self, addr):
        self.udp.drain()
        return [v for _, a, v in self.udp.got if a == addr]

    async def test_natural_exit_with_idle_runner_stdin(self):
        """A script exiting while the runner keeps stdin open must not abort on a buffered I/O lock."""
        p = self.sd.write("exit.py", """
            ws.start()
            ws.sleep(0.1)
            raise SystemExit(7)
        """)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-u", str(p), "--ws-runner",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"WS_OSC_HOST": "127.0.0.1", "WS_OSC_PORT": str(self.udp.port)})
        try:
            # Do not use communicate(): it closes stdin and masks the shutdown race.
            await asyncio.wait_for(proc.wait(), 3.0)
            err = await proc.stderr.read()
            self.assertEqual(proc.returncode, 7, err.decode(errors="replace"))
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            proc.stdin.close()

    async def test_controls_reach_the_script_and_are_resent_after_restart(self):
        s = self.script("""
            k = ws.knob("Density", 0, 1, 0.5)
            ws.start()
            last = None
            for _ in range(40):
                if k.value != last:
                    print("density", k.value, flush=True); last = k.value
                ws.sleep(0.05)
            raise SystemExit(1)
        """)
        await s.start()
        await self.until(lambda: "density 0.5" in self.logs)
        await s.control("density", 0.7)
        await self.until(lambda: "density 0.7" in self.logs)
        self.logs.clear()
        try:
            await self.until(lambda: s.restarts >= 1 and "density 0.7" in self.logs, 6.0)
        except AssertionError:
            self.fail(f"control replay failed: state={s.state}, restarts={s.restarts}, "
                      f"exit={s.last_exit}, values={s.values}, logs={self.logs!r}, "
                      f"task={s._task!r}")

    async def test_environment_and_working_directory(self):
        s = self.script("""
            import os
            print("cwd", os.path.basename(os.getcwd()), flush=True)
            print("env", os.environ["WS_OSC_HOST"], os.environ["WS_OSC_PORT"], flush=True)
            ws.start()
            while True: ws.sleep(0.1)
        """)
        await s.start()
        await self.until(lambda: any(x.startswith("env") for x in self.logs))
        self.assertIn("cwd scripts", self.logs)
        self.assertIn(f"env 127.0.0.1 {self.udp.port}", self.logs)

    async def test_stalled_after_no_heartbeat_but_not_killed(self):
        old = wsrun.STALL_AFTER
        wsrun.STALL_AFTER = 0.6
        try:
            s = self.script("""
                import time
                ws.start()
                time.sleep(1.5)  # not ws.sleep: no heartbeat
                while True: ws.sleep(0.1)
            """)
            await s.start()
            await self.until(lambda: s.state == "stalled", 3.0)
            self.assertEqual(s.restarts, 0)
            await self.until(lambda: s.state == "running", 3.0)
        finally:
            wsrun.STALL_AFTER = old

    async def test_stdin_eof_stops_the_script(self):
        """If the runner goes away, the script ends and zeros its gates (no orphan notes)."""
        p = self.sd.write("orphan.py", """
            g = ws.gate("G"); ws.start(); g.on()
            while True: ws.sleep(0.05)
        """)
        proc = subprocess.Popen([sys.executable, "-I", "-u", str(p), "--ws-runner"], cwd=p.parent,
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                env={"WS_OSC_HOST": "127.0.0.1", "WS_OSC_PORT": str(self.udp.port)})
        await self.until(lambda: self.values_seen("/ws/g"))
        proc.stdin.close()
        self.assertEqual(proc.wait(5), 0)
        await self.until(lambda: self.values_seen("/ws/g")[-1] == [0.0])

    async def test_generative_ws_runs_under_the_runner(self):
        shutil.copy(GEN, self.sd.root / "generative_ws.py")
        s = wsrun.Script(self.sd.root / "generative_ws.py", self.udp.port, on_log=lambda t: None)
        self.scripts.append(s)
        await s.start()
        await self.until(lambda: {"/ws/trig/1", "/ws/gate/1", "/ws/cv/1"} <= {a for _, a, _ in self.udp.got}, 5.0)
        await s.stop()
        await asyncio.sleep(0.1)
        for i in (1, 2, 3, 4):
            self.assertEqual(self.values_seen(f"/ws/gate/{i}")[-1], [0.0])


class Cli(unittest.TestCase):
    def test_print_config_cli(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripting/wsrun.py"), "print-config", str(GEN)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["name"], "generative_ws")

    def test_serve_start_control_stop(self):
        sd = ScriptDir()
        udp = Listener()
        try:
            sd.write("s.py", "g = ws.gate('G'); ws.start(); g.on()\nwhile True: ws.sleep(0.05)\n")
            p = subprocess.Popen([sys.executable, "-I", str(ROOT / "scripting/wsrun.py"), "serve", "--root",
                                  str(sd.root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            p.stdin.write(json.dumps({"id": 1, "type": "printConfig", "file": "s.py"}) + "\n")
            p.stdin.write(json.dumps({"id": 2, "type": "start", "file": "s.py", "port": udp.port}) + "\n")
            p.stdin.write(json.dumps({"id": 3, "type": "start", "file": "../x.py"}) + "\n")
            p.stdin.flush()
            replies = {}
            while len(replies) < 3:
                m = json.loads(p.stdout.readline())
                if m["type"] == "reply":
                    replies[m["re"]] = m
            self.assertEqual(replies[1]["result"]["outputs"][0]["address"], "/ws/g")
            self.assertTrue(replies[2]["ok"])
            self.assertFalse(replies[3]["ok"])
            time.sleep(0.5)
            p.stdin.write(json.dumps({"id": 4, "type": "stop", "file": "s.py"}) + "\n")
            p.stdin.close()
            self.assertEqual(p.wait(10), 0)
            p.stdout.close()
            time.sleep(0.1)
            vals = [v for _, a, v in udp.drain() if a == "/ws/g"]
            self.assertEqual(vals[0], [1.0])
            self.assertEqual(vals[-1], [0.0])
        finally:
            udp.close()
            sd.cleanup()


if __name__ == "__main__":
    unittest.main()
