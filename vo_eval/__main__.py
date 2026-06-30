"""Command line entry for single-trajectory VO/VIO evaluation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .evaluator import (
    EvaluationConfig,
    evaluate_vloc_bundle,
    evaluate_vo_bundle,
    load_vloc_evaluation_bundle,
    load_vo_evaluation_bundle,
    report_to_json,
)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m vo_eval",
        description="Trajectory VO/VLOC evaluation CLI.",
    )
    parser.add_argument("--mode", choices=["sf_vo", "sf_vloc"], help="Evaluation workflow")
    parser.add_argument("--data_dir", type=Path, help="Directory containing imu.txt")
    parser.add_argument("--log_dir", type=Path, help="Directory containing vo.txt/vloc.txt + home_point.txt + calib_raw.yaml")
    parser.add_argument("-d", "--delta", type=float, default=100.0, help="RPE delta value (default: 100)")
    parser.add_argument("-u", "--unit", default="m", choices=["m", "f"], help="RPE delta unit: m=meters, f=frames (default: m)")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output JSON path (optional)")
    parser.add_argument("-p", "--plot", action="store_true", help="Open interactive HTML report in browser")

    args = parser.parse_args(argv)

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
            print(f"  RMSE: {rpe_trans.get('rmse', 'N/A'):.4f} m")
            print(f"  Mean: {rpe_trans.get('mean', 'N/A'):.4f} m")
            print(f"  Max:  {rpe_trans.get('max', 'N/A'):.4f} m")
            print(f"  Count: {rpe.get('count', 'N/A')}")

        ate = report.get("ate_position_m") or {}
        if ate:
            print(f"\nATE 绝对轨迹误差:")
            print(f"  RMSE: {ate.get('rmse', 'N/A'):.4f} m")
            print(f"  Mean: {ate.get('mean', 'N/A'):.4f} m")

        alignment = report.get("alignment") or {}
        if alignment:
            print(f"\nSim3 对齐:")
            print(f"  Scale: {alignment.get('scale', 'N/A'):.4f}")

        print("================================\n")

        # JSON 输出到文件
        if args.output:
            json_text = report_to_json(report)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json_text, encoding="utf-8")
            print(f"[vo_eval] wrote {args.output}", file=sys.stderr)

        return 0
    except Exception as exc:
        import traceback
        print(f"[vo_eval] error: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
