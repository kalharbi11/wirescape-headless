#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Print `code=true` unless every changed file is documentation (0025 §5.3 scope job).

Usage: scope.py BASE_SHA   (compares BASE_SHA..HEAD; an unknown base means code=true)
"""
import re
import subprocess
import sys

DOCS = re.compile(r"^(docs/.*|LICENSES/.*|LICENSE|[^/]*\.md|examples/README\.md)$")


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if not base or set(base) == {"0"}:
            raise subprocess.CalledProcessError(1, "no base")
        out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                             check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError:
        print("code=true")
        return 0
    files = [f for f in out.splitlines() if f]
    code = not files or any(not DOCS.match(f) for f in files)
    print(f"code={'true' if code else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
