# SPDX-License-Identifier: GPL-3.0-only
"""Owner-only H-f2 evidence collector and offline analyzer (Linux cgroup v2)."""
import argparse
import datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.request import urlopen

DURATION = 1800
MAX_GAP = 1.5
UNIT = "wirescape-ui.service"
CGROUP = Path("/sys/fs/cgroup")
META = ("headless_sha", "lab_sha", "machine", "date", "patch_sha256",
        "workload", "browser", "consent")


def integer(value):
    return type(value) is int and value >= 0


def tree_rss(processes):
    """Sum sampled RSS of every cgroup member, not just its main PID."""
    if not isinstance(processes, list) or not processes:
        return None
    seen = set()
    total = 0
    for p in processes:
        if not isinstance(p, dict):
            return None
        pid, start, rss = (p.get(k) for k in ("pid", "start", "rss_bytes"))
        if not all(integer(v) for v in (pid, start, rss)) or pid == 0 or pid in seen:
            return None
        seen.add(pid)
        total += rss
    return total


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_run(run, ui):
    require(isinstance(run, dict), "missing run")
    require("collection_error" not in run, "collection interrupted: " + str(run.get("collection_error", "")))
    for key in META:
        require(isinstance(run.get(key), str) and bool(run[key].strip()),
                "missing metadata: " + key)
    for key, length in (("headless_sha", 40), ("lab_sha", 40), ("patch_sha256", 64)):
        require(re.fullmatch("[0-9a-f]{" + str(length) + "}", run[key]),
                "invalid digest: " + key)
    datetime.date.fromisoformat(run["date"])
    require(run["machine"] == "Raspberry Pi 5", "not owner Pi 5 evidence")
    require(not ui or run.get("play_30hz_observed") is True,
            "Play page 30 Hz not established")
    samples = run.get("samples")
    require(isinstance(samples, list) and len(samples) >= 2, "missing samples")
    first = samples[0]
    previous = None
    peak = 0
    for s in samples:
        t = s.get("t")
        require(type(t) in (float, int) and math.isfinite(t), "invalid timestamp")
        require(s.get("engine_running") is True, "engine not running")
        for key in ("engine_restarts", "patch_index", "dropouts"):
            require(integer(s.get(key)), "missing/invalid " + key)
        settings = s.get("audio_settings")
        require(isinstance(settings, dict) and
                all(integer(settings.get(k)) and settings[k] > 0
                    for k in ("sampleRate", "bufferFrames")), "missing audio settings")
        for key in ("engine_restarts", "patch_index", "audio_settings", "invocation"):
            require(s.get(key) == first.get(key), "changed " + key)
        require(s.get("ui_active") is ui, "unexpected kiosk state")
        if previous is not None:
            require(0 < t - previous["t"] <= MAX_GAP, "sample gap or nonmonotonic time")
            require(s["dropouts"] >= previous["dropouts"], "dropout counter reset")
        if ui:
            require(isinstance(s.get("invocation"), str) and bool(s["invocation"]),
                    "missing kiosk invocation")
            require(integer(s.get("cpu_usec")), "missing CPU counter")
            if previous is not None:
                require(s["cpu_usec"] >= previous["cpu_usec"], "CPU counter reset")
            rss = tree_rss(s.get("processes"))
            require(rss is not None, "missing or ambiguous process RSS")
            peak = max(peak, rss)
        else:
            require(s.get("processes") == [] and s.get("invocation") is None,
                    "baseline has kiosk processes")
        previous = s
    last = samples[-1]
    elapsed = last["t"] - first["t"]
    require(DURATION <= elapsed <= DURATION + MAX_GAP, "not a complete 30-minute window")
    return {
        "duration": elapsed,
        "dropouts": last["dropouts"] - first["dropouts"],
        "cpu": (last["cpu_usec"] - first["cpu_usec"]) / 1e6 / elapsed * 100 if ui else None,
        "rss": peak if ui else None,
        "patch_index": first["patch_index"],
        "audio_settings": first["audio_settings"],
    }


def analyze(evidence):
    try:
        baseline, ui = evidence["baseline"], evidence["ui"]
        a, b = validate_run(baseline, False), validate_run(ui, True)
        for key in META:
            require(baseline[key] == ui[key], "baseline/UI mismatch: " + key)
        for key in ("patch_index", "audio_settings"):
            require(a[key] == b[key], "baseline/UI mismatch: " + key)
        require(abs(a["duration"] - b["duration"]) <= MAX_GAP, "duration mismatch")
        checks = {
            "cpu": b["cpu"] <= 25,
            "rss": b["rss"] <= 350_000_000,
            "dropouts": b["dropouts"] == a["dropouts"],
        }
        return {"status": "pass" if all(checks.values()) else "fail",
                "mean_cpu_percent": b["cpu"], "peak_rss_bytes": b["rss"],
                "baseline_dropouts": a["dropouts"], "ui_dropouts": b["dropouts"],
                "checks": checks, "baseline_duration": a["duration"], "ui_duration": b["duration"]}
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        return {"status": "inconclusive", "reason": str(exc)}


def unit_properties():
    output = subprocess.check_output(
        ["systemctl", "--user", "show", UNIT, "--property=ActiveState",
         "--property=InvocationID", "--property=ControlGroup", "--property=MainPID"],
        text=True, timeout=2)
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def members(group):
    files = [group / "cgroup.procs", *group.glob("**/cgroup.procs")]
    return {int(pid) for file in set(files) for pid in file.read_text().split()}


def process_sample(pid):
    # comm can contain spaces and parentheses. Fields after the final ')' start at field 3.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "start": int(fields[19]),
            "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE")}


def kiosk_sample(ui):
    before = unit_properties()
    if not ui:
        require(before.get("ActiveState") == "inactive" and before.get("MainPID") == "0",
                "stop kiosk before baseline")
        path = before.get("ControlGroup", "")
        if path:
            group = (CGROUP / path.lstrip("/")).resolve()
            require(group.is_relative_to(CGROUP) and group != CGROUP, "bad kiosk cgroup")
            require(not group.exists() or not members(group), "kiosk cgroup is not empty")
        return {"ui_active": False, "invocation": None, "cpu_usec": None, "processes": []}
    require(before.get("ActiveState") == "active", "kiosk not active")
    path = before.get("ControlGroup", "")
    group = (CGROUP / path.lstrip("/")).resolve()
    require(group.is_relative_to(CGROUP) and group != CGROUP, "bad kiosk cgroup")
    inode = group.stat().st_ino
    pids = members(group)
    require(int(before["MainPID"]) in pids, "main PID not in kiosk cgroup")
    processes = [process_sample(pid) for pid in sorted(pids)]
    usage = dict(line.split() for line in (group / "cpu.stat").read_text().splitlines())
    # Never accidentally join a recycled PID to an earlier process sample.
    require(pids == members(group) and
            all(process_sample(p["pid"])["start"] == p["start"] for p in processes),
            "process membership changed during sample")
    require(before == unit_properties() and inode == group.stat().st_ino,
            "kiosk restarted during sample")
    require(bool(before.get("InvocationID")), "missing invocation ID")
    main = next(p for p in processes if p["pid"] == int(before["MainPID"]))
    identity = f'{before["InvocationID"]}:{inode}:{main["pid"]}:{main["start"]}'
    return {"ui_active": True, "invocation": identity,
            "cpu_usec": int(usage["usage_usec"]), "processes": processes}


def engine_sample():
    with urlopen("http://127.0.0.1:8770/api/v1/state", timeout=2) as response:
        state = json.load(response)
    engine = state["engine"]
    audio = engine.get("audio") or {}
    return {"engine_running": engine.get("state") == "running",
            "engine_restarts": engine.get("restarts"),
            "patch_index": state["current"].get("index"),
            "audio_settings": {k: audio.get(k) for k in ("sampleRate", "bufferFrames", "deviceId")},
            "dropouts": audio.get("dropouts")}


def write_json(path, data):
    path = Path(path)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".ui-cost-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def collect(metadata, ui):
    run = dict(metadata, samples=[])
    # Record actual checkout/pin, not a short or manually guessed revision.
    run["headless_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    run["lab_sha"] = next(line.split("=", 1)[1] for line in Path("LAB_PIN").read_text().splitlines()
                          if line.startswith("commit="))
    start = time.monotonic()
    try:
        for i in range(DURATION + 1):
            time.sleep(max(0, start + i - time.monotonic()))
            # Timestamp after the CPU/status snapshots, at a fixed one-second target cadence.
            sample = {**engine_sample(), **kiosk_sample(ui)}
            sample["t"] = time.monotonic()
            run["samples"].append(sample)
        # Sampling jitter can put the first/last observations slightly under 1800 s apart.
        if run["samples"][-1]["t"] - run["samples"][0]["t"] < DURATION:
            time.sleep(max(0, run["samples"][0]["t"] + DURATION - time.monotonic()))
            sample = {**engine_sample(), **kiosk_sample(ui), "t": time.monotonic()}
            run["samples"].append(sample)
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError,
            KeyboardInterrupt) as exc:
        run["collection_error"] = str(exc) or type(exc).__name__
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("collect")
    capture.add_argument("phase", choices=("baseline", "ui"))
    capture.add_argument("metadata", type=Path)
    capture.add_argument("output", type=Path)
    report = sub.add_parser("analyze")
    report.add_argument("baseline", type=Path)
    report.add_argument("ui", type=Path)
    args = parser.parse_args()
    if args.command == "collect":
        run = collect(json.loads(args.metadata.read_text()), args.phase == "ui")
        write_json(args.output, run)
        return 2 if "collection_error" in run else 0
    try:
        result = analyze({"baseline": json.loads(args.baseline.read_text()),
                          "ui": json.loads(args.ui.read_text())})
    except (OSError, ValueError) as exc:
        result = {"status": "inconclusive", "reason": str(exc)}
    print(json.dumps(result, indent=2))
    return {"pass": 0, "fail": 1, "inconclusive": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
