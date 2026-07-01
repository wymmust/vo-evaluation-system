#!/usr/bin/env python3
"""Sync static_web/py/ copies with the source vo_eval modules.

The static web version runs inside Pyodide in the browser. Pyodide cannot
import from the project's Python package path — it only loads files that
are physically present under static_web/py/ and fetchable via HTTP.

This script copies the canonical sources so the browser build stays
consistent with the main evaluator. Run it after any change to
vo_eval/*.py or to browser_runner.py's API.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODULES = ("data_loader.py", "utils.py", "report.py", "processing.py")
SRC_PACKAGE = ROOT / "vo_eval"
DST_PACKAGE = ROOT / "static_web" / "py" / "vo_eval"

SRC_BROWSER_RUNNER = ROOT / "static_web" / "py" / "browser_runner.py"
# browser_runner.py is authored in static_web/py/ itself — no separate source.
# It imports from the split vo_eval modules at runtime inside Pyodide, so it
# stays in sync with the module public APIs by design.


def main() -> None:
    DST_PACKAGE.mkdir(parents=True, exist_ok=True)
    (DST_PACKAGE / "__init__.py").write_text("", encoding="utf-8")

    for module in MODULES:
        src = SRC_PACKAGE / module
        dst = DST_PACKAGE / module
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        shutil.copy2(src, dst)
        print(f"Synced: {src.relative_to(ROOT)} → {dst.relative_to(ROOT)}")

    # Verify browser_runner.py imports the split module API.
    runner_text = SRC_BROWSER_RUNNER.read_text()
    if "from vo_eval.data_loader" not in runner_text or "from vo_eval.processing" not in runner_text:
        print("Warning: browser_runner.py does not import from the split vo_eval modules")

    print("Done.")


if __name__ == "__main__":
    main()
