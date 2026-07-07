"""Unified command entry for VO/VLOC evaluation."""

from __future__ import annotations

import sys

from . import cli, server


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: python -m voeval {sf_vo,sf_vloc,eval,server} ...")
        print()
        print("VO/VLOC evaluation tools.")
        print()
        print("commands:")
        print("  sf_vo DATA_DIR LOG_DIR    Run one SF VO evaluation")
        print("  sf_vloc DATA_DIR LOG_DIR  Run one SF VLOC evaluation")
        print("  eval   Run one SF VO/VLOC evaluation with legacy flags")
        print("  server  Serve the local web UI")
        return 0
    command, remainder = args[0], args[1:]
    if command in {"sf_vo", "sf_vloc"}:
        return cli.main(args)
    if command == "eval":
        return cli.main(remainder)
    if command == "server":
        return server.main(remainder)
    if command.startswith("-"):
        return cli.main(args)
    print(f"python -m voeval: unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
