# SPDX-License-Identifier: GPL-3.0-only
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/build_engine.py"


class BuildEngine(unittest.TestCase):
    def test_help_and_required_command(self):
        self.assertEqual(subprocess.run([sys.executable, str(TOOL), "--help"],
                                       capture_output=True).returncode, 0)
        self.assertNotEqual(subprocess.run([sys.executable, str(TOOL), "build"],
                                          capture_output=True).returncode, 0)

    def test_empty_path_reports_missing_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PATH=tmp)
            result = subprocess.run([sys.executable, str(TOOL), "--check"], cwd=tmp,
                                    env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            for name in ("git", "cmake", "ninja", "dpkg-query", "libasound2-dev"):
                self.assertIn(name, result.stdout)
            self.assertEqual(list(pathlib.Path(tmp).iterdir()), [])

    def test_fake_path_reports_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for name in ("git", "cmake", "ninja", "c++", "cc", "pkg-config", "dpkg-query"):
                p = root / name
                p.write_text("#!/bin/sh\nprintf 'install ok installed\\n'\n")
                p.chmod(0o755)
            result = subprocess.run([sys.executable, str(TOOL), "--check"], cwd=tmp,
                                    env=dict(os.environ, PATH=tmp), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("missing: none", result.stdout)
