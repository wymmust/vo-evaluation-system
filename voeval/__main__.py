"""Unified command entry for VO/VLOC evaluation."""

from __future__ import annotations

import sys

from . import cli, server


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: python -m voeval {eval,server} ...")
        print()
        print("VO/VLOC evaluation tools.")
        print()
        print("commands:")
        print("  eval   Run one SF VO/VLOC evaluation")
        print("  server  Serve the local web UI")
        return 0
    command, remainder = args[0], args[1:]
    if command == "eval":
        return cli.main(remainder)
    if command == "server":
        return server.main(remainder)
    print(f"python -m voeval: unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
