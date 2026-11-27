# SPDX-License-Identifier: GPL-3.0-only
"""PG6: kill an actual Player during 500 atomic live-value saves, with null audio."""
import asyncio
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import unittest

from player import bundle as B, state as S
from player.core import PlayerCore
from player.engine_proc import EngineProcess
from tests.helpers import ROOT, TempBundle


async def child(bundle, state, phase):
    b = B.load(bundle)
    store = S.StateStore(state)
    core = PlayerCore({b.name: b}, lambda: EngineProcess(os.environ["WIRESCAPE_ENGINE"],
                      ["--null-audio", "--settings", str(state / "engine-settings.json")]),
                      store=store, initial=store.load())
    try:
        await core.start()
        await core.select(2)
        await core.command({"type": "set", "control": "tempo", "value": 141})
        # Stop at a known atomic-replace boundary, not an arbitrary sleep
        # that could kill before any save began. Exercise the actual writer.
        replace = os.replace

        def interrupted(src, dst, *args, **kwargs):
            if Path(dst) != store.path:
                return replace(src, dst, *args, **kwargs)
            if phase == "after":
                replace(src, dst, *args, **kwargs)
            print("SAVE BOUNDARY", flush=True)
            signal.pause()
            raise AssertionError("parent failed to kill the Player")

        os.replace = interrupted
        core.save_now()
        raise AssertionError("save did not reach the boundary")
    finally:
        await core.close()


class PowerCut(unittest.TestCase):
    def test_pg6_500_kills(self):
        tb = TempBundle()
        self.addCleanup(tb.cleanup)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = Path(temp.name)
        store = S.StateStore(state)
        store.save(S.state_doc(tb.root.name, 2, {2: {"param:1:bpm": 120}}))
        for i in range(500):
            # Before and after replacement are distinct power-cut cases.
            phase = "before" if i % 2 == 0 else "after"
            p = subprocess.Popen(
                [sys.executable, "-m", "tests.integration.test_power_cut",
                 str(tb.root), str(state), phase], cwd=ROOT,
                stdout=subprocess.PIPE, start_new_session=True)
            try:
                ready, _, _ = select.select([p.stdout], [], [], 15)
                self.assertTrue(ready, f"kill {i}: save boundary timeout")
                self.assertEqual(p.stdout.readline(), b"SAVE BOUNDARY\n", f"kill {i}")
                os.kill(p.pid, signal.SIGKILL)
                self.assertEqual(p.wait(5), -signal.SIGKILL)
            finally:
                # The engine exits on stdin EOF; clean the group if it has not.
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait()
                p.stdout.close()
            doc = json.loads(store.path.read_text())
            self.assertTrue(S.valid(doc), f"kill {i}: invalid state")
            self.assertEqual(doc["index"], 2)


if __name__ == "__main__":
    if len(sys.argv) == 4:
        asyncio.run(child(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]))
    else:
        unittest.main()
