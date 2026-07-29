"""Standalone HTML report generation and preview helpers."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import webbrowser
from pathlib import Path

from .export import report_to_json
from .paths import _default_html_output_path

def _write_html_report(report: dict, output_path: Path) -> None:
    """通过 Node.js export_report_cli.js 生成交互式 HTML 报告（与 web UI 同一套可视化）。"""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("生成 HTML 报告需要 Node.js：请先安装 node，或不使用 -p")
    package_root = Path(__file__).resolve().parents[1]
    exporter = package_root / "visualization" / "cli" / "export_report_cli.js"
    if not exporter.exists():
        raise RuntimeError(f"找不到 HTML 导出器：{exporter}")
    try:
        subprocess.run(
            [node, str(exporter), str(output_path)],
            input=report_to_json(report),
            text=True,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"HTML 报告生成失败：{detail}") from exc
def _temporary_html_output_path(report: dict) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="vo_eval_report_"))
    return _default_html_output_path(report, cwd=temp_dir)
def _preview_html_report(path: Path) -> None:
    webbrowser.open(path.resolve().as_uri())
