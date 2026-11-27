# SPDX-License-Identifier: GPL-3.0-only
"""H-1: Player API v1 contract against the fake player (lab proposals/0025 §2.5, §2.6).

Every command body, reply, state document and SSE event seen here is validated against
api/player-api.v1.schema.json. H-4 runs the same suite against the real engine.
"""
import asyncio
import json
import unittest

import jsonschema

from player import bundle as B
from player.core import PlayerCore
from player.fake_engine import FakeEngine
from player.server import ApiServer
from tests import apiclient as api
from tests.helpers import ROOT, TempBundle

SCHEMA = json.loads((ROOT / "api" / "player-api.v1.schema.json").read_text())
jsonschema.Draft202012Validator.check_schema(SCHEMA)


def validator(name):
    return jsonschema.Draft202012Validator({**SCHEMA, "$ref": f"#/$defs/{name}"})


V = {n: validator(n) for n in ("command", "reply", "state", "event")}
SEEN_COMMANDS: set[str] = set()


class Base(unittest.IsolatedAsyncioTestCase):
    fakes: list

    async def asyncSetUp(self):
        self.tb = TempBundle()
        b = B.load(self.tb.root)
        self.fakes = []

        def factory():
            f = FakeEngine(status_hz=20)
            self.fakes.append(f)
            return f

        self.core = PlayerCore({b.name: b}, factory, fake=True, control_port=9100)
        self.server = ApiServer(self.core, port=0)
        self.port = await self.server.start()
        await self.core.start()

    async def asyncTearDown(self):
        await self.core.close()
        await self.server.close()
        self.tb.cleanup()

    @property
    def fake(self) -> FakeEngine:
        return self.fakes[-1]

    async def cmd(self, **c):
        V["command"].validate(c)
        SEEN_COMMANDS.add(c["type"])
        reply = await api.command(self.port, c)
        V["reply"].validate(reply)
        return reply

    async def ok(self, **c):
        r = await self.cmd(**c)
        self.assertTrue(r["ok"], r)
        return r["result"]

    async def state(self):
        s = await api.get_state(self.port)
        V["state"].validate(s)
        return s

    async def wait(self, pred, timeout=4.0):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            s = await self.state()
            if pred(s):
                return s
            await asyncio.sleep(0.05)
        self.fail("condition not reached")


class Endpoints(Base):
    async def test_state_boots_to_first_entry(self):
        s = await self.state()
        self.assertEqual(s["api"], "1.0")
        self.assertEqual(s["engine"]["state"], "running")
        self.assertEqual(s["current"]["index"], 0)
        self.assertEqual(len(s["setlist"]), 6)
        self.assertEqual(s["osc"]["controlPort"], 9100)
        self.assertTrue(s["bundle"]["check"]["ok"])

    async def test_stream_starts_with_state(self):
        async with api.Events(self.port) as ev:
            e, d = await ev.next()
            V["event"].validate({"event": e, "data": d})
            self.assertEqual(e, "state")

    async def test_every_event_validates(self):
        async with api.Events(self.port, controller=True) as ev:
            await self.ok(type="select", index=5)
            await self.ok(type="set", control="cutoff", norm=0.25)
            await self.ok(type="fake.inject", what="controller",
                          event={"kind": "cc", "deviceId": "Fake MIDI 1|fake:midi:0", "channel": 1, "controller": 74, "value": 9})
            kinds = set()
            for _ in range(60):
                e, d = await ev.next()
                V["event"].validate({"event": e, "data": d})
                kinds.add(e)
                if {"state", "values", "status", "controller"} <= kinds:
                    break
            self.assertEqual(kinds, {"state", "values", "status", "controller"})

    async def test_controller_only_with_query(self):
        async with api.Events(self.port) as plain, api.Events(self.port, controller=True) as ctl:
            await self.ok(type="fake.inject", what="controller", event={"kind": "pc", "deviceId": "d", "channel": 1, "program": 5})
            d = await ctl.until("controller")
            self.assertEqual(d["events"][0]["program"], 5)
            self.assertIsInstance(d["events"][0]["t"], int)
            got = []
            loop = asyncio.get_running_loop()
            end = loop.time() + 0.5
            try:
                while loop.time() < end:
                    got.append((await plain.next(end - loop.time()))[0])
            except asyncio.TimeoutError:
                pass
            self.assertNotIn("controller", got)

    async def test_http_errors(self):
        s, _ = await api.http(self.port, "POST", "/api/v1/command", b"{bad", {"Content-Type": "application/json"})
        self.assertEqual(s, 400)
        s, _ = await api.http(self.port, "POST", "/api/v1/command", b"{}", {"Content-Type": "text/plain"})
        self.assertEqual(s, 415)
        s, _ = await api.http(self.port, "GET", "/api/v1/state", headers={"Origin": "http://evil.example"})
        self.assertEqual(s, 403)
        s, _ = await api.http(self.port, "GET", "/api/v1/nope")
        self.assertEqual(s, 404)
        s, _ = await api.http(self.port, "GET", "/ui/../player/core.py")
        self.assertEqual(s, 404)

    async def test_unknown_and_malformed_commands(self):
        for c in ({"type": "nope"}, {"index": 1}, []):
            status, body = await api.http(self.port, "POST", "/api/v1/command", json.dumps(c).encode(),
                                          {"Content-Type": "application/json"})
            r = json.loads(body)
            V["reply"].validate(r)
            self.assertEqual((status, r["ok"], r["code"]), (200, False, "invalid"))


class Commands(Base):
    async def test_select_next_prev(self):
        self.assertEqual((await self.ok(type="select", index=2))["index"], 2)
        await self.ok(type="next")
        self.assertEqual((await self.state())["current"]["index"], 3)
        await self.ok(type="prev")
        await self.ok(type="prev")
        self.assertEqual((await self.state())["current"]["index"], 1)
        r = await self.cmd(type="select", index=99)
        self.assertEqual(r["code"], "not-found")

    async def test_set_param_and_mod_amount(self):
        await self.ok(type="select", index=5)
        r = await self.ok(type="set", control="cutoff", value=1234)
        self.assertEqual(r["key"], "param:2:cutoff")
        self.assertIn({"type": "setParam", "moduleId": 2, "paramId": "cutoff", "value": 1234}, self.fake.commands)
        r = await self.ok(type="set", control="wob", norm=1.0)
        self.assertEqual(r["value"], 1)
        sent = [c for c in self.fake.commands if c["type"] == "setModAmount"][-1]
        self.assertEqual(sent["connection"], {"kind": "modulation", "from": {"module": 10, "port": "control"},
                                              "to": {"module": 2, "port": "cutoff"}})
        s = await self.state()
        self.assertEqual(s["controls"]["cutoff"]["value"], 1234)
        self.assertEqual(s["controls"]["wob"]["value"], 1)

    async def test_set_any_target_not_in_player_json(self):
        await self.ok(type="select", index=2)
        r = await self.ok(type="set", target={"param": {"module": 7, "param": "feedback"}}, value=0.5)
        self.assertEqual(r["key"], "param:7:feedback")
        r = await self.cmd(type="set", target={"param": {"module": 77, "param": "x"}}, value=1)
        self.assertEqual(r["code"], "not-found")

    async def test_set_script_control_stores_value(self):
        await self.ok(type="select", index=5)
        await self.wait(lambda s: s["controls"]["dens"]["resolved"])
        r = await self.ok(type="set", control="dens", value=0.7)
        self.assertEqual(r["key"], "script:scripts/generative_ws.py:density")

    async def test_set_unresolved_macro_is_not_found(self):
        r = await self.cmd(type="set", control="m1", norm=0.5)
        self.assertEqual(r["code"], "not-found")
        self.assertFalse((await self.state())["controls"]["m1"]["resolved"])

    async def test_reset(self):
        await self.ok(type="select", index=2)
        await self.ok(type="set", control="tempo", value=140)
        r = await self.ok(type="reset", control="tempo")
        self.assertEqual(r["value"], 120)
        await self.ok(type="set", control="echo", value=0.9)
        r = await self.ok(type="reset")
        self.assertEqual(r["reset"], ["param:7:mix"])
        self.assertEqual((await self.state())["controls"]["echo"]["value"], 0.24)

    async def test_params_list(self):
        await self.ok(type="select", index=5)
        r = await self.ok(type="params.list")
        self.assertEqual(len(r["modules"]), 11)
        chaos = next(m for m in r["modules"] if m["id"] == 2)
        self.assertTrue(any(p["id"] == "cutoff" for p in chaos["parameters"]))
        self.assertEqual(len(r["cables"]), 3)
        self.assertFalse(any(c["mapping"] for c in r["cables"]))

    async def test_bundle_commands(self):
        r = await self.ok(type="bundle.list")
        self.assertEqual(r["current"], "set")
        r = await self.ok(type="bundle.check", name="set")
        self.assertFalse(any(f["level"] == "error" for f in r["findings"]))
        self.assertEqual((await self.ok(type="bundle.load", name="set"))["index"], 0)
        self.assertEqual((await self.cmd(type="bundle.load", name="nope"))["code"], "not-found")

    async def test_device_passthrough(self):
        r = await self.ok(type="audio.devices")
        dev = r["devices"][0]["id"]
        await self.ok(type="audio.select", deviceId=dev)
        await self.ok(type="audio.buffer", frames=128)
        await self.ok(type="audio.rate", hz=44100)
        r = await self.cmd(type="audio.select", deviceId="missing")
        self.assertEqual((r["code"], r["engineCode"]), ("engine", "not-found"))
        r = await self.ok(type="midi.devices")
        mid = r["devices"][0]["id"]
        await self.ok(type="midi.enable", deviceId=mid, on=True)
        s = await self.state()
        self.assertTrue(s["midi"]["devices"][0]["enabled"])
        await self.ok(type="panic")

    async def test_stage_gated_commands(self):
        for t in ("script.start", "script.stop", "script.restart"):
            self.assertEqual((await self.cmd(type=t, file="scripts/generative_ws.py"))["code"], "not-found")
        self.assertEqual((await self.cmd(type="config.put", json={}))["code"], "unavailable")
        self.assertEqual((await self.ok(type="config.get"))["json"]["format"], "wirescape.player")


class Faults(Base):
    async def test_engine_crash_restarts_and_reloads_composed(self):
        await self.ok(type="select", index=5)
        await self.ok(type="set", control="cutoff", value=2222)
        await self.ok(type="set", control="wob", value=-0.5)
        await self.ok(type="fake.inject", what="engineCrash")
        s = await self.wait(lambda s: s["engine"]["restarts"] == 1 and s["engine"]["state"] == "running"
                            and len(self.fakes) == 2 and self.fake.graph is not None)
        self.assertEqual(s["engine"]["lastExit"]["signal"], "SIGSEGV")
        self.assertEqual(s["current"]["index"], 5)
        doc = self.fake.graph
        self.assertEqual(B.find_module(doc, 2)["parameters"]["cutoff"], 2222)
        cable = B.find_mod_cable(doc, {"module": 10, "port": "control"}, {"module": 2, "param": "cutoff"})
        self.assertEqual(cable["amount"], -0.5)
        sent = [c["type"] for c in self.fake.commands]
        self.assertEqual(sent[0], "loadGraph")  # hello -> loadGraph(composed), no separate replay

    async def test_engine_stall_is_killed_and_restarted(self):
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await self.ok(type="fake.inject", what="engineStall")
        await self.wait(lambda s: s["engine"]["restarts"] == 1 and s["engine"]["state"] == "running")
        self.assertLess(loop.time() - t0, 1.5 + 0.25 + 0.5)
        self.assertEqual(self.core.engine_info["lastExit"]["signal"], "SIGKILL")

    async def test_engine_restart_command_has_no_backoff(self):
        await self.ok(type="engine.restart")
        s = await self.wait(lambda s: s["engine"]["restarts"] == 1 and s["engine"]["state"] == "running", 1.0)
        self.assertEqual(s["current"]["index"], 0)

    async def test_commands_while_restarting_are_unavailable(self):
        self.fake.crash()
        r = await self.cmd(type="set", target={"param": {"module": 2, "param": "frequency"}}, value=300)
        self.assertEqual(r["code"], "unavailable")

    async def test_bad_inject(self):
        self.assertEqual((await self.cmd(type="fake.inject", what="scriptCrash"))["code"], "unavailable")


class RealPlayerRefusesInject(unittest.IsolatedAsyncioTestCase):
    async def test_inject_unavailable_without_fake(self):
        tb = TempBundle()
        b = B.load(tb.root)
        core = PlayerCore({b.name: b}, FakeEngine, fake=False)
        await core.start()
        server = ApiServer(core, port=0)
        port = await server.start()
        r = await api.command(port, {"type": "fake.inject", "what": "engineCrash"})
        self.assertEqual(r["code"], "unavailable")
        await core.close()
        await server.close()
        tb.cleanup()


class Arbiter(Base):
    async def test_one_in_flight_single_pending(self):
        gate = asyncio.Event()
        real = self.fake.request

        async def slow(msg):
            if msg["type"] == "loadGraph":
                await gate.wait()
            return await real(msg)

        self.fake.request = slow
        first = asyncio.create_task(self.core.command({"type": "select", "index": 1}))
        await asyncio.sleep(0.05)
        for i in (2, 3, 4):
            r = await self.core.command({"type": "select", "index": i})
            self.assertTrue(r["queued"])
        self.assertEqual(self.core.current["pending"], 4)
        gate.set()
        await first
        loads = [c for c in self.fake.commands if c["type"] == "loadGraph"]
        self.assertEqual(len(loads), 3)  # boot entry 0, then 1, then only the last pending (4)
        self.assertEqual(self.core.current["index"], 4)

    async def test_next_counts_from_latest_request(self):
        gate = asyncio.Event()
        real = self.fake.request

        async def slow(msg):
            if msg["type"] == "loadGraph":
                await gate.wait()
            return await real(msg)

        self.fake.request = slow
        first = asyncio.create_task(self.core.command({"type": "next"}))
        await asyncio.sleep(0.05)
        await self.core.command({"type": "next"})
        await self.core.command({"type": "next"})
        gate.set()
        await first
        self.assertEqual(self.core.current["index"], 3)

    async def test_refused_load_keeps_previous_patch(self):
        real = self.fake.request

        async def refuse(msg):
            if msg["type"] == "loadGraph":
                return {"v": 0, "session": "x", "re": None, "ok": False, "gen": "1", "code": "limit",
                        "message": "Graph capacity exceeded"}
            return await real(msg)

        self.fake.request = refuse
        r = await self.cmd(type="select", index=3)
        self.assertEqual((r["code"], r["engineCode"]), ("engine", "limit"))
        s = await self.state()
        self.assertEqual(s["current"]["index"], 0)
        self.assertIn("limit", s["current"]["error"])

    async def test_recall_patch_clears_values(self):
        await self.ok(type="select", index=4)
        await self.ok(type="set", target={"param": {"module": 2, "param": "frequency"}}, value=300)
        await self.ok(type="select", index=0)
        await self.ok(type="select", index=4)
        self.assertEqual(B.find_module(self.fake.graph, 2)["parameters"]["frequency"],
                         B.find_module(json.loads((self.tb.root / "patches/quad-vca-01-lpg-plucks.json").read_text()), 2)
                         ["parameters"]["frequency"])


class ZzCoverage(unittest.TestCase):
    """Runs last (classes load alphabetically): every command type in the schema was exercised above."""

    def test_zz_every_command_type_exercised(self):
        types = set()
        for alt in SCHEMA["$defs"]["command"]["oneOf"]:
            alt = alt["allOf"][0] if "allOf" in alt else alt
            types.add(alt["properties"]["type"]["const"])
        if len(SEEN_COMMANDS) < 5:
            self.skipTest("only meaningful when the whole module runs")  # a single-test run, not CI
        self.assertEqual(types - SEEN_COMMANDS, set())


class Examples(unittest.TestCase):
    def test_api_examples_validate(self):
        files = sorted((ROOT / "api" / "examples").glob("*.json"))
        self.assertGreater(len(files), 5)
        for f in files:
            doc = json.loads(f.read_text())
            if f.name == "state.json":
                V["state"].validate(doc)
            else:
                V["command"].validate(doc["request"])
                V["reply"].validate(doc["reply"])
