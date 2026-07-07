"""Report output filename and path helpers."""

from __future__ import annotations

import re
from pathlib import Path

def _sanitize_filename_part(value: object) -> str:
    return re.sub(r"_+", "_", re.sub(r'[\\/:*?"<>|\s]+', "_", str(value or "").strip())).strip("_")
def _meaningful_directory_name(value: object) -> str:
    name = _sanitize_filename_part(value)
    if name.lower() in {"data_dir", "log_dir"}:
        return ""
    return name
def _default_html_output_path(report: dict, cwd: Path | None = None) -> Path:
    inputs = report.get("inputs") or {}
    entry_mode = _sanitize_filename_part(inputs.get("entry_mode") or "vloc") or "vloc"
    data_name = _meaningful_directory_name(inputs.get("data_dir_name"))
    log_name = _meaningful_directory_name(inputs.get("log_dir_name"))
    if data_name and log_name and data_name != log_name:
        dataset = f"{data_name}__{log_name}"
    else:
        dataset = log_name or data_name or ""
    prefix = f"{dataset}_{entry_mode}" if dataset else entry_mode
    return (cwd or Path.cwd()) / f"{prefix}_evaluation_report.html"
