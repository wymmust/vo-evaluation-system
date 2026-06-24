"""Command line entry point for batch VO evaluation summaries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .evo_compat import (
    TumEvalSettings,
    discover_tum_tasks,
    evaluate_tum_task,
    parse_id_list,
    parse_rpe_deltas,
)
from .excel_summary import Thresholds, default_output_path, write_eval_summary
from .vo_mode import (
    VoEvalSettings,
    default_vo_output_dir,
    discover_vo_tasks,
    evaluate_vo_task,
    parse_vo_ids,
)
from .vloc_mode import (
    VlocEvalSettings,
    default_vloc_output_dir,
    discover_vloc_tasks,
    evaluate_vloc_task,
    parse_vloc_ids,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        deltas = parse_rpe_deltas(args.rpe_deltas)
        rows: list[dict] = []
        output_base: Path
        mode_primary_key: str | None = None

        if args.mode == "tum":
            if not args.log_root:
                parser.error("--log-root is required for --mode tum")
            log_ids = parse_id_list(args.ids)
            log_range = tuple(args.log_range) if args.log_range else None
            settings = TumEvalSettings(
                alignment=args.alignment,
                association_mode=args.association_mode,
                max_time_diff_s=args.max_time_diff_s,
                max_interpolation_gap_s=None if args.max_interpolation_gap_s < 0 else args.max_interpolation_gap_s,
                allow_extrapolation=args.allow_extrapolation,
                continuous_segment_policy=args.continuous_segment_policy,
                rpe_distance_tolerance_ratio=args.rpe_distance_tolerance_ratio,
            )
            tasks, failure_rows = discover_tum_tasks(
                Path(args.log_root),
                trajectory_file=args.trajectory_file,
                gt_file=args.gt_file,
                log_ids=log_ids,
                log_range=log_range,
            )
            rows.extend(failure_rows)
            output_base = Path(args.log_root)
            total = len(tasks)
            for index, task in enumerate(tasks, 1):
                print(f"[{index}/{total}] {task.log_id}: {task.nav_path}")
                row = evaluate_tum_task(
                    task,
                    deltas,
                    settings,
                    include_extra_summary=not args.compat_only,
                )
                rows.append(row)
                status = row.get("status", "OK")
                primary_preview = row.get(args.primary_key or "rpe_100m_trans_rmse", "-")
                print(f"    status={status} primary={primary_preview}")
        elif args.mode == "vo":
            if not args.data_root:
                parser.error("--data-root is required for --mode vo")
            vo_ids = parse_vo_ids(args.ids)
            rpe_delta = deltas[0] if deltas else None
            settings = VoEvalSettings(
                max_interpolation_gap_s=None if args.max_interpolation_gap_s < 0 else args.max_interpolation_gap_s,
                continuous_segment_policy=args.vo_segment_policy,
                rpe_delta=rpe_delta,
                scale_delta=rpe_delta,
                rpe_distance_tolerance_ratio=args.rpe_distance_tolerance_ratio,
            )
            tasks, failure_rows = discover_vo_tasks(Path(args.data_root), ids=vo_ids)
            rows.extend(failure_rows)
            output_base = default_vo_output_dir(Path(args.data_root))
            mode_primary_key = "mean_xy"
            total = len(tasks)
            for index, task in enumerate(tasks, 1):
                print(f"[{index}/{total}] {task.log_id}: {task.data_dir}")
                row = evaluate_vo_task(task, settings)
                rows.append(row)
                status = row.get("status", "OK")
                primary_preview = row.get(args.primary_key or mode_primary_key, "-")
                print(f"    status={status} primary={primary_preview}")
        elif args.mode == "vloc":
            if not args.data_root:
                parser.error("--data-root is required for --mode vloc")
            vloc_ids = parse_vloc_ids(args.ids)
            rpe_delta = deltas[0] if deltas else None
            settings = VlocEvalSettings(
                rpe_delta=rpe_delta,
                rpe_distance_tolerance_ratio=args.rpe_distance_tolerance_ratio,
            )
            tasks, failure_rows = discover_vloc_tasks(Path(args.data_root), ids=vloc_ids)
            rows.extend(failure_rows)
            output_base = default_vloc_output_dir(Path(args.data_root))
            mode_primary_key = "mean_xy"
            total = len(tasks)
            for index, task in enumerate(tasks, 1):
                print(f"[{index}/{total}] {task.log_id}: {task.data_dir}")
                row = evaluate_vloc_task(task, settings)
                rows.append(row)
                status = row.get("status", "OK")
                primary_preview = row.get(args.primary_key or mode_primary_key, "-")
                print(f"    status={status} primary={primary_preview}")
        else:
            parser.error(f"unsupported --mode {args.mode}")
    except Exception as exc:
        print(f"[vo_eval_cli] setup failed: {exc}", file=sys.stderr)
        return 2

    if not rows:
        print("[vo_eval_cli] no tasks found", file=sys.stderr)
        return 1

    out_path = Path(args.output) if args.output else default_output_path(output_base)
    thresholds = Thresholds(
        xy_warn=args.xy_warn,
        z_warn=args.z_warn,
        xy_fail=args.xy_fail,
        z_fail=args.z_fail,
        rpe_trans_warn=args.rpe_trans_warn,
        rpe_trans_fail=args.rpe_trans_fail,
    )
    try:
        actual = write_eval_summary(
            rows,
            out_path,
            rpe_labels=[delta.label for delta in deltas],
            thresholds=thresholds,
            primary_key=args.primary_key or mode_primary_key,
        )
    except Exception as exc:
        print(f"[vo_eval_cli] Excel output failed: {exc}", file=sys.stderr)
        return 3

    ok_count = sum(1 for row in rows if str(row.get("status", "")).upper() == "OK")
    fail_count = len(rows) - ok_count
    print(f"[vo_eval_cli] wrote {actual}")
    print(f"[vo_eval_cli] rows={len(rows)} ok={ok_count} fail={fail_count}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vo_eval_cli",
        description="Batch VO evaluation CLI that writes evo/Matlab-style Excel summaries.",
    )
    parser.add_argument("--mode", default="tum", choices=["tum", "vo", "vloc"], help="Input workflow: tum replaces evo; vo/vloc evaluate SF fixed-format bundles.")
    parser.add_argument("--log-root", default="", help="Root containing numeric log directories with run_metadata.json; required for --mode tum.")
    parser.add_argument("--data-root", default="", help="Root containing SFdataset sequence directories; required for --mode vo or --mode vloc.")
    parser.add_argument("--output", "-o", default="", help="Output .xlsx path. Defaults to log_root/eval_summary_TIMESTAMP.xlsx.")
    parser.add_argument("--trajectory-file", default="trajectory_tum.txt", help="Estimated TUM trajectory filename under each log dir.")
    parser.add_argument("--gt-file", default="groundtruth_tum.txt", help="Ground truth TUM filename under each dataset dir.")
    parser.add_argument("--ids", default="", help="Comma or space separated log IDs, e.g. '0,1,2'.")
    parser.add_argument("--log-range", nargs=2, type=int, metavar=("START", "END"), help="Inclusive numeric log ID range.")
    parser.add_argument("--rpe-deltas", default="1f,100m,500m", help="Comma-separated RPE deltas, e.g. 1f,100m,500m.")

    parser.add_argument("--alignment", default="sim3", choices=["none", "first_pose", "se3", "sim3"], help="Trajectory alignment mode.")
    parser.add_argument("--association-mode", default="interpolate_gt", choices=["interpolate_gt", "nearest", "index"], help="Timestamp association mode.")
    parser.add_argument("--max-time-diff-s", type=float, default=None, help="Nearest association max time diff. Usually unused with interpolate_gt.")
    parser.add_argument("--max-interpolation-gap-s", type=float, default=1.0, help="Max GT interpolation gap; use -1 to disable.")
    parser.add_argument("--allow-extrapolation", action="store_true", help="Allow GT extrapolation outside reference range.")
    parser.add_argument("--continuous-segment-policy", default="all", choices=["all", "vo_timestamps", "segments", "longest"], help="How discontinuities affect TUM evaluation.")
    parser.add_argument("--vo-segment-policy", default="segments", choices=["all", "vo_timestamps", "segments", "longest"], help="How VO reset/discontinuity segments affect --mode vo evaluation.")
    parser.add_argument("--rpe-distance-tolerance-ratio", type=float, default=0.05, help="Tolerance for meter-based RPE endpoint lookup.")

    parser.add_argument("--primary-key", default="", help="Metric used for progress/Excel classification. Defaults to rpe_100m_trans_rmse for tum and mean_xy for vo/vloc.")
    parser.add_argument("--compat-only", action="store_true", help="Only write evo-style metric columns; omit coverage/duration extras.")

    parser.add_argument("--xy-warn", type=float, default=20.0)
    parser.add_argument("--xy-fail", type=float, default=50.0)
    parser.add_argument("--z-warn", type=float, default=20.0)
    parser.add_argument("--z-fail", type=float, default=50.0)
    parser.add_argument("--rpe-trans-warn", type=float, default=0.05)
    parser.add_argument("--rpe-trans-fail", type=float, default=0.10)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
