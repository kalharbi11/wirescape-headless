# SPDX-License-Identifier: GPL-3.0-only
"""H-5: `install` and boot (lab proposals/0025 §2.3).

A kill at any install step leaves the old bundle or the new one; the next boot removes
leftover temp folders; the boot chain is state.json → state.good.json → first bundle at
index 0 → no patch, reported in the state.
"""
import asyncio
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

from player import boot as BT, install as I, state as S
from player.core import PlayerCore
from player.fake_engine import FakeEngine
from tests import apiclient as api
from tests.helpers import EXAMPLE, ROOT, TempBundle

STDIO_ENGINE = ROOT / "tests" / "stdio_engine.py"


def marker(root: pathlib.Path) -> str | None:
    p = root / "player.json"
    return json.loads(p.read_text()).get("title") if p.exists() else None


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.state = self.dir / "state"
        self.src = self.dir / "src" / "myset"
        shutil.copytree(EXAMPLE, self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def titled(self, title: str) -> pathlib.Path:
        cfg = json.loads((self.src / "player.json").read_text())
        cfg["title"] = title
        (self.src / "player.json").write_text(json.dumps(cfg))
        return self.src


class Install(Base):
    def test_install_copies_and_replaces(self):
        name = I.install(self.titled("one"), self.state)
        self.assertEqual(name, "myset")
        dest = self.state / "bundles" / "myset"
        self.assertEqual(marker(dest), "one")
        I.install(self.titled("two"), self.state)
        self.assertEqual(marker(dest), "two")
        self.assertEqual(sorted(p.name for p in (self.state / "bundles").iterdir()), ["myset"])

    def test_check_errors_refuse_and_keep_the_old_bundle(self):
        I.install(self.titled("one"), self.state)
        cfg = json.loads((self.src / "player.json").read_text())
        cfg["setlist"][0]["patch"] = "patches/missing.json"
        (self.src / "player.json").write_text(json.dumps(cfg))
        with self.assertRaises(I.InstallError) as cm:
            I.install(self.src, self.state)
        self.assertIn("missing", str(cm.exception))
        self.assertEqual(marker(self.state / "bundles" / "myset"), "one")
        self.assertEqual(sorted(p.name for p in (self.state / "bundles").iterdir()), ["myset"])

    def test_bad_names_and_sources_are_refused(self):
        with self.assertRaises(I.InstallError):
            I.install(self.dir / "nope", self.state)
        bad = self.dir / "src" / "bad name!"
        shutil.copytree(EXAMPLE, bad)
        with self.assertRaises(I.InstallError):
            I.install(bad, self.state)

    def test_source_is_never_modified(self):
        before = {p.relative_to(self.src): p.read_bytes() for p in self.src.rglob("*") if p.is_file()}
        I.install(self.src, self.state)
        after = {p.relative_to(self.src): p.read_bytes() for p in self.src.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_cli_exit_codes(self):
        r = subprocess.run([sys.executable, "-m", "player", "install", str(self.src), "--state", str(self.state)],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, "-m", "player", "install", str(self.dir / "nope"), "--state",
                            str(self.state)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


class KillDuringInstall(Base):
    """SIGKILL at every step of install, then boot: the old or the new bundle, never neither."""

    SCRIPT = ("import os, signal, sys, pathlib; sys.path.insert(0, sys.argv[4])\n"
              "from player import install as I\n"
              "at = sys.argv[3]\n"
              "def step(name):\n"
              "    if name == at: os.kill(os.getpid(), signal.SIGKILL)\n"
              "I._step = step\n"
              "I.install(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))\n")

    def test_kill_at_each_step(self):
        for step in I.STEPS:
            with self.subTest(step=step):
                shutil.rmtree(self.state, ignore_errors=True)
                I.install(self.titled("old"), self.state)
                self.titled("new")
                p = subprocess.run([sys.executable, "-I", "-c", self.SCRIPT, str(self.src), str(self.state), step,
                                    str(ROOT)])
                self.assertEqual(p.returncode, -signal.SIGKILL, step)
                BT.recover(self.state / "bundles")
                names = sorted(x.name for x in (self.state / "bundles").iterdir())
                self.assertEqual(names, ["myset"], step)
                self.assertIn(marker(self.state / "bundles" / "myset"), ("old", "new"), step)

    def test_kill_at_random_times(self):
        import random
        rnd = random.Random(3)
        I.install(self.titled("old"), self.state)
        self.titled("new")
        for _ in range(15):
            p = subprocess.Popen([sys.executable, "-I", "-c", self.SCRIPT, str(self.src), str(self.state), "none",
                                  str(ROOT)])
            try:
                p.wait(rnd.uniform(0.0, 0.15))
            except subprocess.TimeoutExpired:
                os.kill(p.pid, signal.SIGKILL)
                p.wait()
            BT.recover(self.state / "bundles")
            self.assertEqual(sorted(x.name for x in (self.state / "bundles").iterdir()), ["myset"])
            self.assertIn(marker(self.state / "bundles" / "myset"), ("old", "new"))


class Boot(Base):
    def test_leftover_temp_folders_are_deleted(self):
        I.install(self.src, self.state)
        b = self.state / "bundles"
        (b / "myset.tmp-77").mkdir()
        (b / "myset.tmp-77" / "x").write_text("half")
        BT.boot(self.state)
        self.assertEqual(sorted(p.name for p in b.iterdir()), ["myset"])

    def test_old_is_restored_when_new_is_missing(self):
        I.install(self.titled("old"), self.state)
        b = self.state / "bundles"
        os.rename(b / "myset", b / "myset.old")
        BT.recover(b)
        self.assertEqual(marker(b / "myset"), "old")

    def test_chain_state_then_good_then_first_then_none(self):
        bundles, initial = BT.boot(self.state)
        self.assertEqual((bundles, initial), ({}, None))  # no bundle at all
        I.install(self.src, self.state)
        other = self.dir / "src" / "another"
        shutil.copytree(EXAMPLE, other)
        I.install(other, self.state)
        bundles, initial = BT.boot(self.state)
        self.assertEqual(list(bundles), ["another", "myset"])
        self.assertIsNone(initial)  # no state: the core uses the first bundle at index 0
        st = S.StateStore(self.state)
        st.save_good(S.state_doc("myset", 2, {}))
        self.assertEqual(BT.boot(self.state)[1]["index"], 2)
        st.save(S.state_doc("myset", 4, {}))
        self.assertEqual(BT.boot(self.state)[1]["index"], 4)
        (self.state / "state.json").write_text("{")
        self.assertEqual(BT.boot(self.state)[1]["index"], 2)

    def test_unreadable_bundle_is_skipped(self):
        I.install(self.src, self.state)
        bad = self.state / "bundles" / "broken"
        bad.mkdir()
        (bad / "player.json").write_text("{nope")
        bundles, _ = BT.boot(self.state)
        self.assertEqual(list(bundles), ["myset"])


class CoreBoot(unittest.IsolatedAsyncioTestCase):
    async def test_state_for_a_missing_bundle_uses_the_first(self):
        tb = TempBundle()
        from player import bundle as B
        b = B.load(tb.root)
        core = PlayerCore({b.name: b}, FakeEngine, initial=S.state_doc("gone", 3, {}))
        await core.start()
        self.assertEqual((core.bundle.name, core.current["index"]), (b.name, 0))
        await core.close()
        tb.cleanup()

    async def test_no_bundle_runs_the_engine_with_no_patch_and_says_so(self):
        fakes = []

        def factory():
            fakes.append(FakeEngine())
            return fakes[-1]

        core = PlayerCore({}, factory)
        await core.start()
        s = core.state_doc()
        self.assertEqual(s["engine"]["state"], "running")
        self.assertEqual(s["setlist"], [])
        self.assertIsNone(s["current"]["index"])
        self.assertTrue(any("no bundle" in w for w in s["warnings"]))
        self.assertEqual([c["type"] for c in fakes[0].commands if c["type"] == "loadGraph"], [])
        from player.core import CommandError
        with self.assertRaises(CommandError) as cm:
            await core.command({"type": "next"})
        self.assertEqual(cm.exception.code, "not-found")
        await core.close()

    async def test_no_bundle_state_validates(self):
        import jsonschema
        schema = json.loads((ROOT / "api" / "player-api.v1.schema.json").read_text())
        core = PlayerCore({}, FakeEngine)
        await core.start()
        jsonschema.Draft202012Validator({**schema, "$ref": "#/$defs/state"}).validate(core.state_doc())
        await core.close()


class RunCommand(Base):
    """`python -m player run` end to end with the stdio stand-in engine."""

    def start(self, *extra):
        cmd = [sys.executable, "-m", "player", "run", "--state", str(self.state), "--api-port", "0",
               "--engine", sys.executable, "--engine-arg=-I", f"--engine-arg={STDIO_ENGINE}", *extra]
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = p.stdout.readline()
        self.assertIn("player: http://127.0.0.1:", line, p.stderr.read() if p.poll() is not None else line)
        port = int(line.rsplit(":", 1)[1].split("/")[0])
        return p, port

    def wait_state(self, port, pred, timeout=5.0):
        async def go():
            loop = asyncio.get_running_loop()
            end = loop.time() + timeout
            while loop.time() < end:
                s = await api.get_state(port)
                if pred(s):
                    return s
                await asyncio.sleep(0.05)
            raise AssertionError("state not reached")
        return asyncio.run(go())

    def test_run_boots_installed_bundle_and_sigterm_saves_and_exits_0(self):
        I.install(self.src, self.state)
        p, port = self.start()
        try:
            self.wait_state(port, lambda s: s["engine"]["state"] == "running" and s["current"]["index"] == 0)
            asyncio.run(api.command(port, {"type": "select", "index": 2}))
            self.wait_state(port, lambda s: s["current"]["index"] == 2)
        finally:
            p.send_signal(signal.SIGTERM)
            rc = p.wait(10)
            p.stdout.close()
            p.stderr.close()
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads((self.state / "state.json").read_text())["index"], 2)
        self.assertTrue((self.state / "state.good.json").exists())
        # the next boot comes back to entry 2
        p, port = self.start()
        try:
            self.wait_state(port, lambda s: s["current"]["index"] == 2 and s["engine"]["state"] == "running")
        finally:
            p.send_signal(signal.SIGTERM)
            p.wait(10)
            p.stdout.close()
            p.stderr.close()

    def test_run_with_no_bundle_reports_it(self):
        p, port = self.start()
        try:
            s = self.wait_state(port, lambda s: s["engine"]["state"] == "running")
            self.assertTrue(any("no bundle" in w for w in s["warnings"]))
        finally:
            p.send_signal(signal.SIGTERM)
            self.assertEqual(p.wait(10), 0)
            p.stdout.close()
            p.stderr.close()


if __name__ == "__main__":
    unittest.main()
