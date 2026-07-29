"""CLI summary formatting helpers."""

from __future__ import annotations

import math

def _format_cli_number(value: object, precision: int = 4) -> str:
    """Format optional numeric values without crashing on missing report fields."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(number):
        return "N/A"
    return f"{number:.{precision}f}"
