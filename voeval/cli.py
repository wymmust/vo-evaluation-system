"""Eval subcommand implementation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import EvaluationConfig
from .io import load_vloc_evaluation_bundle, load_vo_evaluation_bundle
from .reports import _default_html_output_path, _format_cli_number, _preview_html_report, _temporary_html_output_path, _write_html_report, evaluate_vloc_bundle, evaluate_vo_bundle, report_to_json

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m voeval eval",
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
            print(f"[voeval] wrote {args.output}", file=sys.stderr)

        if args.save_html or args.p:
            html_output = args.html_output or (_default_html_output_path(report) if args.save_html else _temporary_html_output_path(report))
            _write_html_report(report, html_output)
            if args.save_html:
                print(f"[voeval] wrote {html_output}", file=sys.stderr)
            if args.p:
                _preview_html_report(html_output)
                print(f"[voeval] opened {html_output}", file=sys.stderr)

        return 0
    except Exception as exc:
        import traceback
        print(f"[voeval] error: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
