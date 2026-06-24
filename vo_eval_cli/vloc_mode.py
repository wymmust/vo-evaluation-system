"""Batch SF VLOC fixed-format evaluation for ``vo_eval_cli``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .evo_compat import RpeDelta, _failure_row, _load_vo_evaluator, _stat, _sse, parse_id_list


@dataclass(frozen=True)
class VlocTask:
    """One SF VLOC directory evaluation task."""

    log_id: str
    data_dir: Path
    log_dir: Path


@dataclass(frozen=True)
class VlocEvalSettings:
    """Configurable VLOC report settings exposed by the CLI."""

    rpe_delta: RpeDelta | None = None
    rpe_distance_tolerance_ratio: float = 0.05


def discover_vloc_tasks(
    data_root: Path,
    *,
    ids: list[str] | None = None,
) -> tuple[list[VlocTask], list[dict[str, Any]]]:
    """Discover SFdataset sequence directories with VLOC bundle files."""

    data_root = Path(data_root)
    if not data_root.is_dir():
        raise FileNotFoundError(f"data_root not found: {data_root}")

    selected = ids or sorted(
        [entry.name for entry in data_root.iterdir() if entry.is_dir()],
        key=_natural_key,
    )
    tasks: list[VlocTask] = []
    failures: list[dict[str, Any]] = []

    for item in selected:
        data_dir = data_root / str(item)
        missing = [name for name in ("imu.txt", "vloc.txt", "home_point.txt", "calib_raw.yaml") if not (data_dir / name).is_file()]
        if missing:
            failures.append(_failure_row(str(item), str(data_dir), "MISSING_FILES", ",".join(missing)))
            continue
        tasks.append(VlocTask(log_id=str(item), data_dir=data_dir, log_dir=data_dir))

    return tasks, failures


def evaluate_vloc_task(task: VlocTask, settings: VlocEvalSettings) -> dict[str, Any]:
    """Evaluate one SF VLOC directory and flatten the report for Excel."""

    try:
        evaluator = _load_vo_evaluator()
        bundle = evaluator.load_vloc_evaluation_bundle(task.data_dir, task.log_dir)
        cfg = _make_vloc_config(evaluator, settings)
        report = evaluator.evaluate_vloc_bundle(bundle, cfg)

        row: dict[str, Any] = {
            "log_id": task.log_id,
            "nav_path": str(task.data_dir),
            "_frame_count": int(report.get("summary", {}).get("raw_est_poses", len(bundle.vloc.positions))),
        }
        _add_ate_metrics(row, report)
        _add_vloc_rpe_metrics(row, report, settings)
        _add_vloc_summary(row, report)
        row["status"] = "OK"
        row["message"] = ""
        return row
    except Exception as exc:
        return _failure_row(task.log_id, str(task.data_dir), f"ERR:{type(exc).__name__}", str(exc))


def _make_vloc_config(evaluator, settings: VlocEvalSettings):
    kwargs: dict[str, Any] = {
        "alignment": "none",
        "orientation_correction": "none",
        "association_mode": "interpolate_gt",
        "max_time_diff_s": None,
        "max_interpolation_gap_s": 1.0,
        "allow_extrapolation": False,
        "interpolate_rotation": True,
        "interpolation_position_method": "linear",
        "interpolation_rotation_method": "slerp",
        "time_offset_s": 0.0,
        "continuous_segment_policy": "vo_timestamps",
        "rpe_distance_tolerance_ratio": settings.rpe_distance_tolerance_ratio,
    }
    if settings.rpe_delta is not None:
        kwargs.update(
            rpe_delta_frames=max(1, int(round(settings.rpe_delta.value))) if settings.rpe_delta.unit == "frames" else 1,
            rpe_delta_value=float(settings.rpe_delta.value),
            rpe_delta_unit=settings.rpe_delta.unit,
        )
    return evaluator.EvaluationConfig(**kwargs)


def _add_ate_metrics(row: dict[str, Any], report: dict[str, Any]) -> None:
    ate = report.get("ate_position_m") or {}
    row["ate_trans_rmse"] = _stat(ate, "rmse")
    row["ate_trans_mean"] = _stat(ate, "mean")
    row["ate_trans_median"] = _stat(ate, "median")
    row["ate_trans_min"] = _stat(ate, "min")
    row["ate_trans_max"] = _stat(ate, "max")
    row["ate_trans_sse"] = _sse(ate)
    row["ate_trans_std"] = _stat(ate, "std")

    h = report.get("ate_horizontal_m") or {}
    z = report.get("ate_vertical_m") or {}
    row["mean_xy"] = _stat(h, "mean")
    row["max_xy"] = _stat(h, "max")
    row["mean_z"] = _stat(z, "mean")
    row["max_z"] = _stat(z, "max")


def _add_vloc_rpe_metrics(row: dict[str, Any], report: dict[str, Any], settings: VlocEvalSettings) -> None:
    label = settings.rpe_delta.label if settings.rpe_delta is not None else "1f"
    trans = ((report.get("rpe_frame_delta") or {}).get("translation_m") or {})
    prefix = f"rpe_{label}_trans"
    row[f"{prefix}_rmse"] = _stat(trans, "rmse")
    row[f"{prefix}_max"] = _stat(trans, "max")
    row[f"{prefix}_mean"] = _stat(trans, "mean")
    row[f"{prefix}_median"] = _stat(trans, "median")
    row[f"{prefix}_min"] = _stat(trans, "min")
    row[f"{prefix}_sse"] = _sse(trans)
    row[f"{prefix}_std"] = _stat(trans, "std")


def _add_vloc_summary(row: dict[str, Any], report: dict[str, Any]) -> None:
    summary = report.get("summary") or {}
    assoc = report.get("association") or {}
    alignment = report.get("alignment") or {}
    detail_summary = ((report.get("vloc_details") or {}).get("summary") or {})

    row["trajectory_length_m"] = detail_summary.get("trajectory_length_m", summary.get("gt_path_length_m", "-"))
    row["mean_xy"] = detail_summary.get("mean_error_pos_xy", row.get("mean_xy", "-"))
    row["max_xy"] = detail_summary.get("max_error_pos_xy", row.get("max_xy", "-"))
    row["mean_z"] = detail_summary.get("mean_error_pos_z", row.get("mean_z", "-"))
    row["max_z"] = detail_summary.get("max_error_pos_z", row.get("max_z", "-"))
    row["mean_error_euler"] = detail_summary.get("mean_error_euler", "-")
    row["max_error_euler"] = detail_summary.get("max_error_euler", "-")

    row["matched_poses"] = summary.get("matched_poses", "-")
    row["gt_coverage"] = summary.get("gt_pose_coverage_ratio", "-")
    row["est_coverage"] = summary.get("est_pose_coverage_ratio", "-")
    row["duration_s"] = summary.get("duration_s", "-")
    row["alignment_scale"] = alignment.get("scale", "-")
    row["valid_est_after_mode_filter"] = assoc.get("valid_est_after_mode_filter", "-")
    row["dropped_est_invalid_mode"] = assoc.get("dropped_est_invalid_mode", "-")


def default_vloc_output_dir(data_root: Path) -> Path:
    return Path(data_root)


def parse_vloc_ids(text: str | None) -> list[str] | None:
    return parse_id_list(text)


def _natural_key(text: str) -> tuple[int, str]:
    return (0, f"{int(text):012d}") if str(text).isdigit() else (1, str(text))
