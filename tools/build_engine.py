#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Owner-side engine build: read-only --check or build DIR (no device access)."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("git", "cmake", "ninja", "cc", "c++", "pkg-config", "dpkg-query")
# Headless subset of lab docs/INSTALL.md, Raspberry Pi 5.
PACKAGES = ("git", "build-essential", "pkg-config", "python3", "python3-venv",
            "libasound2-dev", "libportaudio2", "libasound2-plugins")


def check():
    missing = []
    for tool in TOOLS:
        found = shutil.which(tool)
        print(f"tool {tool}: {'found' if found else 'missing'}")
        if not found:
            missing.append(tool)
    for package in PACKAGES:
        installed = False
        if shutil.which("dpkg-query"):
            result = subprocess.run(["dpkg-query", "-W", "-f=${Status}", package],
                                    capture_output=True, text=True)
            installed = result.returncode == 0 and result.stdout.strip() == "install ok installed"
        print(f"package {package}: {'installed' if installed else 'missing or unverified'}")
        if not installed:
            missing.append(package)
    print("missing: " + (", ".join(missing) if missing else "none"))
    return bool(missing)


def run(*args):
    subprocess.run(args, check=True)


def build(work):
    work = work.resolve()
    if work == Path("/opt") or Path("/opt") in work.parents:
        raise ValueError("build outside /opt")
    # Never reuse a potentially dirty source tree or stale CMake cache.
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise ValueError("build directory must be empty")
    source, output = work / "lab", work / "build"
    run(sys.executable, str(ROOT / "tools/labpin.py"), "fetch", str(source))
    import labpin
    pin = labpin.load()
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != pin["commit"]:
        raise ValueError("fetched commit differs from LAB_PIN")
    print("LAB_PIN:", actual, flush=True)
    run("c++", "--version")
    run("cmake", "-S", str(source / "native"), "-B", str(output), "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release")
    run("cmake", "--build", str(output), "--target", "wirescape_engine_sidecar", "--parallel", "2")
    binary = output / "wirescape-engine"
    dest = ROOT / "wirescape-engine"
    if Path("/opt") in dest.resolve().parents:
        raise ValueError("stage outside /opt")
    fd, tmp = tempfile.mkstemp(prefix=".wirescape-engine-", dir=ROOT)
    try:
        with os.fdopen(fd, "wb") as out, binary.open("rb") as src:
            shutil.copyfileobj(src, out)
            os.fchmod(out.fileno(), 0o755)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dest)
        dirfd = os.open(ROOT, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    with dest.open("rb") as f:
        print("sha256:", hashlib.file_digest(f, "sha256").hexdigest())
    print("staged:", dest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report tools and packages without changing anything")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("build").add_argument("dir", type=Path)
    args = parser.parse_args(argv)
    if args.check == bool(args.command):
        parser.error("choose either --check or build DIR")
    if args.check:
        return int(check())
    try:
        if check():
            return 1
        build(args.dir)
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        print(f"build failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
