"""Eval subcommand implementation."""

from __future__ import annotations

import argparse
from pprint import pformat
from pathlib import Path

from .core import EvaluationConfig
from .debug import configure_logging
from .io import load_vloc_evaluation_bundle, load_vo_evaluation_bundle
from .reports import _default_html_output_path, _format_cli_number, _preview_html_report, _temporary_html_output_path, _write_html_report, evaluate_vloc_bundle, evaluate_vo_bundle, report_to_json

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voeval",
        description="Trajectory VO/VLOC evaluation CLI.",
    )
    parser.add_argument("mode", choices=["sf_vo", "sf_vloc"], help="Evaluation workflow")
    parser.add_argument("data_dir", type=Path, help="Directory containing imu.txt")
    parser.add_argument("log_dir", type=Path, help="Directory containing vo.txt/vloc.txt and calibration files")
    parser.add_argument("--vo_filename", type=str, default="vo.txt", help="Vo trajectory filename(default: vo.txt)")
    parser.add_argument("-d", "--delta", type=float, default=100.0, help="RPE delta value (default: 100)")
    parser.add_argument("-u", "--unit", default="m", choices=["m", "f"], help="RPE delta unit: m=meters, f=frames (default: m)")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output JSON path (optional)")
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
        rpe_delta_value=args.delta,
        rpe_delta_unit=unit,
        scale_delta_value=args.delta,
        scale_delta_unit=unit,
    )

    try:
        if args.mode == "sf_vo":
            bundle = load_vo_evaluation_bundle(args.data_dir, args.log_dir, args.vo_filename)
            report = evaluate_vo_bundle(bundle, config)
        else:
            bundle = load_vloc_evaluation_bundle(args.data_dir, args.log_dir)
            report = evaluate_vloc_bundle(bundle, config)

        if args.mode == "sf_vo":
            _log_vo_result_summary(logger, report, args)
        else:
            _log_vloc_result_summary(logger, report, args)

        # JSON 输出到文件
        if args.output:
            json_text = report_to_json(report)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json_text, encoding="utf-8")
            logger.info("[voeval] wrote %s", args.output)

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
        logger.info("\nSim3 对齐:")
        logger.info(f"  Scale: {_format_cli_number(alignment.get('scale'))}")

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
        logger.info(f"  Max:  {_format_cli_number(rpe_trans.get('max'))} m")
        logger.info(f"  Count: {rpe.get('count', 'N/A')}")

    ate = report.get("ate_position_m") or {}
    if isinstance(ate, dict) and ate:
        logger.debug("ATE position summary: %s", ate)
        logger.info("\nATE 绝对轨迹误差:")
        logger.info(f"  RMSE: {_format_cli_number(ate.get('rmse'))} m")
        logger.info(f"  Mean: {_format_cli_number(ate.get('mean'))} m")


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
