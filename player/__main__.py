# SPDX-License-Identifier: GPL-3.0-only
"""python -m player run|fake|check|install (lab proposals/0025 §2.1)."""
import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip() + "\n  run     the Player with the real engine\n"
              "  fake    the Player with the fake engine\n  check   check a bundle\n"
              "  install install a bundle atomically")
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "check":
        from .check import main as m
        return m(rest)
    if cmd == "fake":
        from .server import main_fake
        return main_fake(rest)
    if cmd == "run":
        from .run import main as m
        return m(rest)
    if cmd == "install":
        from .install import main as m
        return m(rest)
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
