#!/usr/bin/env python3
"""Sync static_web/py/ copies with the source vo_eval/evaluator.py.

The static web version runs inside Pyodide in the browser. Pyodide cannot
import from the project's Python package path — it only loads files that
are physically present under static_web/py/ and fetchable via HTTP.

This script copies the canonical sources so the browser build stays
consistent with the main evaluator. Run it after any change to
vo_eval/evaluator.py or to browser_runner.py's API.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SRC_EVALUATOR = ROOT / "vo_eval" / "evaluator.py"
DST_EVALUATOR = ROOT / "static_web" / "py" / "evaluator.py"

SRC_BROWSER_RUNNER = ROOT / "static_web" / "py" / "browser_runner.py"
# browser_runner.py is authored in static_web/py/ itself — no separate source.
# It imports from vo_eval.evaluator at runtime inside Pyodide, so it stays
# in sync with evaluator.py's public API by design.


def main() -> None:
    if not SRC_EVALUATOR.exists():
        raise FileNotFoundError(f"Source not found: {SRC_EVALUATOR}")

    # Copy evaluator.py
    shutil.copy2(SRC_EVALUATOR, DST_EVALUATOR)
    print(f"Synced: {SRC_EVALUATOR.relative_to(ROOT)} → {DST_EVALUATOR.relative_to(ROOT)}")

    # Verify browser_runner.py imports match evaluator public API
    runner_text = SRC_BROWSER_RUNNER.read_text()
    if "from vo_eval.evaluator" not in runner_text:
        print("Warning: browser_runner.py does not import from vo_eval.evaluator")

    print("Done.")


if __name__ == "__main__":
    main()