"""Eval subcommand implementation."""

from __future__ import annotations

import argparse
from pprint import pformat
from pathlib import Path

from .core import EvaluationConfig
from .debug import configure_logging
from .io import DEFAULT_DATASET, SUPPORTED_DATASETS, load_vloc_evaluation_bundle, load_vo_evaluation_bundle
from .reports import _default_html_output_path, _format_cli_number, _preview_html_report, _temporary_html_output_path, _write_html_report, evaluate_vloc_bundle, evaluate_vo_bundle, report_to_json

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voeval",
        description="Trajectory VO/VLOC evaluation CLI.",
    )
    parser.add_argument("mode", choices=["sf_vo", "sf_vloc"], help="Evaluation workflow")
    parser.add_argument("data_dir", type=Path, help="Directory containing imu.txt")
    parser.add_argument("log_dir", type=Path, help="Directory containing vo.txt/vloc.txt and calibration files")
    parser.add_argument(
        "--dataset",
        choices=SUPPORTED_DATASETS,
        default=DEFAULT_DATASET,
        help="Hardware dataset selecting calibration file: rk3399=calib_raw.yaml, rk3588=bottom_calib_raw.yaml",
    )
    parser.add_argument("--vo_filename", type=str, default="vo.txt", help="Vo trajectory filename(default: vo.txt)")
    parser.add_argument("-d", "--delta", type=float, default=100.0, help="RPE delta value (default: 100)")
    parser.add_argument("-u", "--unit", default="m", choices=["m", "f"], help="RPE delta unit: m=meters, f=frames (default: m)")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output metrics JSON path; .json is added automatically")
    parser.add_argument("-p", action="store_true", help="Preview standalone HTML report in browser")
    parser.add_argument("-s", "--save-html", action="store_true", help="Save standalone HTML report")
    parser.add_argument("--html-output", type=Path, default=None, help="HTML report path used with -s/--save-html")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print verbose debug output")
    parser.add_argument("--silent", action="store_true", help="Suppress normal CLI summary output")
    parser.add_argument("--debug", action="store_true", help="Print evo-style debug output with source locations")
    parser.add_argument("--logfile", type=Path, default=None, help="Write DEBUG logs to this file")

    args = parser.parse_args(argv)
    if args.html_output and not args.save_html:
        parser.error("--html-output requires -s/--save-html")
    logger = configure_logging(verbose=args.verbose, silent=args.silent, debug=args.debug, logfile=args.logfile)
    if args.debug or args.logfile:
        logger.debug("main_parser config:\n%s", pformat(_debug_args_dict(args)))
        logger.debug("--------------------------------------------------------------------------------")

    unit = "meters" if args.unit == "m" else "frames"
    config = EvaluationConfig(
        delta_value=args.delta,
        delta_unit=unit,
    )

    try:
        if args.mode == "sf_vo":
            bundle = load_vo_evaluation_bundle(args.data_dir, args.log_dir, args.vo_filename, dataset=args.dataset)
            report = evaluate_vo_bundle(bundle, config)
        else:
            bundle = load_vloc_evaluation_bundle(args.data_dir, args.log_dir, dataset=args.dataset)
            report = evaluate_vloc_bundle(bundle, config)

        if args.mode == "sf_vo":
            _log_vo_result_summary(logger, report, args)
        else:
            _log_vloc_result_summary(logger, report, args)

        # JSON 输出到文件
        if args.output:
            output_path = _json_output_path(args.output)
            json_text = report_to_json(_cli_metrics_report(report, args))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json_text, encoding="utf-8")
            logger.info("[voeval] wrote %s", output_path.resolve())

        if args.save_html or args.p:
            html_output = args.html_output or (_default_html_output_path(report) if args.save_html else _temporary_html_output_path(report))
            _write_html_report(report, html_output)
            if args.save_html:
                logger.info("[voeval] wrote %s", html_output)
            if args.p:
                _preview_html_report(html_output)
                logger.info("[voeval] opened %s", html_output)

        return 0
    except Exception as exc:
        if args.debug:
            logger.exception("[voeval] error: %s", exc)
        else:
            logger.error("[voeval] error: %s", exc)
        return 1


def _log_vo_result_summary(logger, report: dict[str, object], args: argparse.Namespace) -> None:
    """Print CLI result summary for VO evaluation."""

    logger.info("\n========== VO 评估结果 ==========")
    _log_common_trajectory_summary(logger, report, args)

    alignment = report.get("alignment") or {}
    if isinstance(alignment, dict) and (alignment.get("base_mode") or alignment.get("mode")) == "sim3":
        logger.debug("Alignment summary: %s", alignment)
        _log_sim3_transforms(logger, alignment)

    logger.info("================================\n")


def _log_vloc_result_summary(logger, report: dict[str, object], args: argparse.Namespace) -> None:
    """Print CLI result summary for VLOC evaluation."""

    logger.info("\n========== VLOC 评估结果 ==========")
    _log_common_trajectory_summary(logger, report, args)
    _log_vloc_specific_metrics(logger, report)
    logger.info("================================\n")


def _log_common_trajectory_summary(logger, report: dict[str, object], args: argparse.Namespace) -> None:
    """Print metrics shared by VO and VLOC CLI summaries."""

    rpe = report.get("rpe_frame_delta") or {}
    rpe_trans = rpe.get("translation_m") if isinstance(rpe, dict) else {}
    if isinstance(rpe, dict) and isinstance(rpe_trans, dict) and rpe_trans:
        logger.debug("RPE translation summary: count=%s stats=%s", rpe.get("count", "N/A"), rpe_trans)
        logger.info(f"RPE 平移误差 (delta={args.delta}{args.unit}):")
        logger.info(f"  RMSE: {_format_cli_number(rpe_trans.get('rmse'))} m")
        logger.info(f"  Mean: {_format_cli_number(rpe_trans.get('mean'))} m")
        logger.info(f"  Median: {_format_cli_number(rpe_trans.get('median'))} m")
        logger.info(f"  Max:  {_format_cli_number(rpe_trans.get('max'))} m")
        logger.info(f"  Min:  {_format_cli_number(rpe_trans.get('min'))} m")
        logger.info(f"  Count: {rpe.get('count', rpe_trans.get('count', 'N/A'))}")

    ate = report.get("ate_position_m") or {}
    if isinstance(ate, dict) and ate:
        logger.debug("ATE position summary: %s", ate)
        logger.info("\nATE 绝对轨迹误差:")
        logger.info(f"  RMSE: {_format_cli_number(ate.get('rmse'))} m")
        logger.info(f"  Mean: {_format_cli_number(ate.get('mean'))} m")
        logger.info(f"  Median: {_format_cli_number(ate.get('median'))} m")
        logger.info(f"  Max:  {_format_cli_number(ate.get('max'))} m")
        logger.info(f"  Min:  {_format_cli_number(ate.get('min'))} m")

    logger.info(f"\nSegment 数量: {_evaluated_segment_count(report)}")


def _evaluated_segment_count(report: dict[str, object]) -> object:
    """Return the number of continuous segments that actually entered evaluation."""

    discontinuities = report.get("discontinuities") or {}
    if isinstance(discontinuities, dict):
        selected = discontinuities.get("selected_segment") or {}
        if isinstance(selected, dict):
            segments = selected.get("segments")
            if isinstance(segments, list):
                return len(segments)

    alignment = report.get("alignment") or {}
    if isinstance(alignment, dict) and alignment.get("segment_count") is not None:
        return alignment["segment_count"]
    return "N/A"


def _log_sim3_transforms(logger, alignment: dict[str, object]) -> None:
    """Print every evaluated VO segment's Sim3 scale, rotation, and translation."""

    segments = alignment.get("segments")
    if not isinstance(segments, list) or not segments:
        segments = [alignment]

    logger.info("\nSim3 变换:")
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue
        segment_id = segment.get("segment_id", index)
        logger.info(f"  Segment {segment_id}:")
        logger.info(f"    Scale: {_format_cli_number(segment.get('scale'))}")
        logger.info("    Rotation:")
        rotation = segment.get("rotation")
        try:
            rows = list(rotation)  # type: ignore[arg-type]
        except TypeError:
            rows = []
        if rows:
            for row in rows:
                logger.info(f"      {_format_cli_vector(row)}")
        else:
            logger.info("      N/A")
        logger.info(f"    Translation: {_format_cli_vector(segment.get('translation'))} m")


def _format_cli_vector(values: object) -> str:
    """Format a numeric vector or matrix row for compact CLI output."""

    try:
        items = list(values)  # type: ignore[arg-type]
    except TypeError:
        return "N/A"
    return "[" + " ".join(_format_cli_number(item) for item in items) + "]"


def _cli_metrics_report(report: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    """Build the compact metrics-only payload written by ``-o``."""

    rpe = report.get("rpe_frame_delta") or {}
    rpe_stats = rpe.get("translation_m") if isinstance(rpe, dict) else {}
    ate_stats = report.get("ate_position_m") or {}
    result: dict[str, object] = {
        "mode": args.mode,
        "rpe_translation_m": {
            "delta_value": float(args.delta),
            "delta_unit": args.unit,
            **_selected_error_statistics(rpe_stats),
            "count": rpe.get("count", rpe_stats.get("count")) if isinstance(rpe, dict) and isinstance(rpe_stats, dict) else None,
        },
        "ate_position_m": _selected_error_statistics(ate_stats),
        "segment_count": _evaluated_segment_count(report),
    }

    if args.mode == "sf_vo":
        alignment = report.get("alignment") or {}
        if isinstance(alignment, dict):
            segments = alignment.get("segments")
            if not isinstance(segments, list) or not segments:
                segments = [alignment]
            result["sim3"] = {
                "segment_count": alignment.get("segment_count", len(segments)),
                "segments": [
                    {
                        "segment_id": segment.get("segment_id", index),
                        "scale": segment.get("scale"),
                        "rotation": segment.get("rotation"),
                        "translation": segment.get("translation"),
                    }
                    for index, segment in enumerate(segments)
                    if isinstance(segment, dict)
                ],
            }
    else:
        details = report.get("vloc_details") or {}
        summary = details.get("summary") if isinstance(details, dict) else {}
        if isinstance(summary, dict):
            result["vloc_metrics"] = {
                key: summary.get(key)
                for key in (
                    "trajectory_length_m",
                    "mean_error_pos_xy",
                    "mean_error_pos_z",
                    "mean_error_euler",
                    "max_error_pos_xy",
                    "max_error_pos_z",
                    "max_error_euler",
                )
            }
    return result


def _json_output_path(path: Path) -> Path:
    """Return a metrics output path with a JSON file extension."""

    return path if path.suffix.lower() == ".json" else path.with_suffix(".json")


def _selected_error_statistics(value: object) -> dict[str, object]:
    """Select exactly the error statistics displayed by the CLI summary."""

    stats = value if isinstance(value, dict) else {}
    return {key: stats.get(key) for key in ("rmse", "mean", "median", "max", "min")}


def _log_vloc_specific_metrics(logger, report: dict[str, object]) -> None:
    """Print VLOC-only position, attitude, and trajectory-length metrics."""

    details = report.get("vloc_details") or {}
    summary = details.get("summary") if isinstance(details, dict) else {}
    if not isinstance(summary, dict) or not summary:
        return

    logger.debug("VLOC detail summary: %s", summary)
    logger.info("\nVLOC 专项指标:")
    for key, unit in (
        ("trajectory_length_m", "m"),
        ("mean_error_pos_xy", "m"),
        ("mean_error_pos_z", "m"),
        ("mean_error_euler", "deg"),
        ("max_error_pos_xy", "m"),
        ("max_error_pos_z", "m"),
        ("max_error_euler", "deg"),
    ):
        logger.info(f"  {key}: {_format_cli_number(summary.get(key))} {unit}")


def _debug_args_dict(args: argparse.Namespace) -> dict[str, object]:
    """Return CLI debug config with only user-visible variable inputs."""

    is_vo = args.mode == "sf_vo"
    estimate_name = "vo.txt" if is_vo else "vloc.txt"
    data_dir = Path(args.data_dir)
    log_dir = Path(args.log_dir)
    return {
        "mode": args.mode,
        "data_dir": str(data_dir),
        "log_dir": str(log_dir),
        "dataset": args.dataset,
        "ref_file": str(data_dir / "imu.txt"),
        "est_file": str(log_dir / estimate_name),
        "delta": float(args.delta),
        "delta_unit": args.unit,
        "output": str(args.output) if args.output else None,
        "preview_html": bool(args.p),
        "save_html": bool(args.save_html),
        "html_output": str(args.html_output) if args.html_output else None,
        "debug": bool(args.debug),
        "verbose": bool(args.verbose),
        "silent": bool(args.silent),
        "logfile": str(args.logfile) if args.logfile else None,
    }
