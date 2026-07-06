"""Command line entry for single-trajectory VO/VIO evaluation."""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

from .data_loader import load_vloc_evaluation_bundle, load_vo_evaluation_bundle
# from .html_report import report_to_interactive_html  # 纯 Python 报告，暂不用，保留模块
from .processing import EvaluationConfig, evaluate_vloc_bundle, evaluate_vo_bundle
from .report import report_to_json


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


def _format_cli_number(value: object, precision: int = 4) -> str:
    """Format optional numeric values without crashing on missing report fields."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(number):
        return "N/A"
    return f"{number:.{precision}f}"


def _write_html_report(report: dict, output_path: Path) -> None:
    """通过 Node.js export_report_cli.js 生成交互式 HTML 报告（与 web UI 同一套可视化）。"""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("生成 HTML 报告需要 Node.js：请先安装 node，或不使用 -p")
    repo_root = Path(__file__).resolve().parents[1]
    exporter = repo_root / "web" / "cli" / "export_report_cli.js"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m vo_eval",
        description="Trajectory VO/VLOC evaluation CLI.",
    )
    parser.add_argument("--mode", choices=["sf_vo", "sf_vloc"], required=True, help="Evaluation workflow")
    parser.add_argument("--data_dir", type=Path, required=True, help="Directory containing imu.txt")
    parser.add_argument("--log_dir", type=Path, required=True, help="Directory containing vo.txt/vloc.txt + calib_raw.yaml; VLOC also requires home_point.txt")
    parser.add_argument("-d", "--delta", type=float, default=100.0, help="RPE delta value (default: 100)")
    parser.add_argument("-u", "--unit", default="m", choices=["m", "f"], help="RPE delta unit: m=meters, f=frames (default: m)")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output JSON path (optional)")
    parser.add_argument("-p", action="store_true", help="Preview standalone HTML report in browser")
    parser.add_argument("-s", "--save-html", action="store_true", help="Save standalone HTML report")
    parser.add_argument("--html-output", type=Path, default=None, help="HTML report path used with -s/--save-html")

    args = parser.parse_args(argv)
    if args.html_output and not args.save_html:
        parser.error("--html-output requires -s/--save-html")

    unit = "meters" if args.unit == "m" else "frames"
    config = EvaluationConfig(
        rpe_delta_value=args.delta,
        rpe_delta_unit=unit,
        rpe_delta_frames=max(1, int(round(args.delta))) if unit == "frames" else 1,
        scale_delta_value=args.delta,
        scale_delta_unit=unit,
    )

    try:
        if args.mode == "sf_vo":
            bundle = load_vo_evaluation_bundle(args.data_dir, args.log_dir)
            report = evaluate_vo_bundle(bundle, config)
        else:
            bundle = load_vloc_evaluation_bundle(args.data_dir, args.log_dir)
            report = evaluate_vloc_bundle(bundle, config)

        # 提取关键误差指标
        print("\n========== 评估结果 ==========")

        rpe = report.get("rpe_frame_delta") or {}
        rpe_trans = rpe.get("translation_m") or {}
        if rpe_trans:
            print(f"RPE 平移误差 (delta={args.delta}{args.unit}):")
            print(f"  RMSE: {_format_cli_number(rpe_trans.get('rmse'))} m")
            print(f"  Mean: {_format_cli_number(rpe_trans.get('mean'))} m")
            print(f"  Max:  {_format_cli_number(rpe_trans.get('max'))} m")
            print(f"  Count: {rpe.get('count', 'N/A')}")

        ate = report.get("ate_position_m") or {}
        if ate:
            print(f"\nATE 绝对轨迹误差:")
            print(f"  RMSE: {_format_cli_number(ate.get('rmse'))} m")
            print(f"  Mean: {_format_cli_number(ate.get('mean'))} m")

        alignment = report.get("alignment") or {}
        if (alignment.get("base_mode") or alignment.get("mode")) == "sim3":
            print(f"\nSim3 对齐:")
            print(f"  Scale: {_format_cli_number(alignment.get('scale'))}")

        print("================================\n")

        # JSON 输出到文件
        if args.output:
            json_text = report_to_json(report)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json_text, encoding="utf-8")
            print(f"[vo_eval] wrote {args.output}", file=sys.stderr)

        if args.save_html or args.p:
            html_output = args.html_output or (_default_html_output_path(report) if args.save_html else _temporary_html_output_path(report))
            _write_html_report(report, html_output)
            if args.save_html:
                print(f"[vo_eval] wrote {html_output}", file=sys.stderr)
            if args.p:
                _preview_html_report(html_output)
                print(f"[vo_eval] opened {html_output}", file=sys.stderr)

        return 0
    except Exception as exc:
        import traceback
        print(f"[vo_eval] error: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
