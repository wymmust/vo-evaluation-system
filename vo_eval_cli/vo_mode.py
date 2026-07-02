"""Batch SF VO bundle evaluation for ``vo_eval_cli``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vo_eval.data_loader import load_vo_evaluation_bundle
from vo_eval.processing import EvaluationConfig, evaluate_vo_bundle

from .evo_compat import RpeDelta, _failure_row, _stat, _sse, parse_id_list


@dataclass(frozen=True)
class VoTask:
    """One SF VO directory evaluation task."""

    log_id: str
    data_dir: Path
    log_dir: Path


@dataclass(frozen=True)
class VoEvalSettings:
    """Configurable VO report settings exposed by the CLI."""

    max_interpolation_gap_s: float | None = 1.0
    continuous_segment_policy: str = "segments"
    rpe_delta: RpeDelta | None = None
    rpe_deltas: tuple[RpeDelta, ...] = ()
    scale_delta: RpeDelta | None = None
    rpe_distance_tolerance_ratio: float = 0.05


def discover_vo_tasks(
    data_root: Path,
    *,
    ids: list[str] | None = None,
) -> tuple[list[VoTask], list[dict[str, Any]]]:
    """Discover SFdataset sequence directories with VO bundle files."""

    data_root = Path(data_root)
    if not data_root.is_dir():
        raise FileNotFoundError(f"data_root not found: {data_root}")

    selected = ids or sorted(
        [entry.name for entry in data_root.iterdir() if entry.is_dir()],
        key=_natural_key,
    )
    tasks: list[VoTask] = []
    failures: list[dict[str, Any]] = []

    for item in selected:
        data_dir = data_root / str(item)
        missing = [name for name in ("imu.txt", "vo.txt", "calib_raw.yaml") if not (data_dir / name).is_file()]
        if missing:
            failures.append(_failure_row(str(item), str(data_dir), "MISSING_FILES", ",".join(missing)))
            continue
        tasks.append(VoTask(log_id=str(item), data_dir=data_dir, log_dir=data_dir))

    return tasks, failures


def evaluate_vo_task(task: VoTask, settings: VoEvalSettings) -> dict[str, Any]:
    """Evaluate one SF VO directory and flatten the report for Excel."""

    try:
        bundle = load_vo_evaluation_bundle(task.data_dir, task.log_dir)
        rpe_deltas = _configured_rpe_deltas(settings)
        base_delta = rpe_deltas[0] if rpe_deltas else None
        cfg = _make_vo_config(settings, rpe_delta=base_delta)
        report = evaluate_vo_bundle(bundle, cfg)

        row: dict[str, Any] = {
            "log_id": task.log_id,
            "nav_path": str(task.data_dir),
            "_frame_count": int(report.get("summary", {}).get("raw_est_poses", len(bundle.vo.positions))),
        }
        _add_ate_metrics(row, report)
        for index, delta in enumerate(rpe_deltas):
            delta_report = report if index == 0 else evaluate_vo_bundle(
                bundle,
                _make_vo_config(settings, rpe_delta=delta),
            )
            _add_vo_rpe_metrics(row, delta_report, delta)
        _add_vo_summary(row, report)
        row["status"] = "OK"
        row["message"] = ""
        return row
    except Exception as exc:
        return _failure_row(task.log_id, str(task.data_dir), f"ERR:{type(exc).__name__}", str(exc))


def _configured_rpe_deltas(settings: VoEvalSettings) -> tuple[RpeDelta, ...]:
    if settings.rpe_deltas:
        return tuple(settings.rpe_deltas)
    if settings.rpe_delta is not None:
        return (settings.rpe_delta,)
    return ()


def _make_vo_config(settings: VoEvalSettings, rpe_delta: RpeDelta | None = None):
    rpe_delta = rpe_delta or settings.rpe_delta
    scale_delta = settings.scale_delta or rpe_delta
    kwargs: dict[str, Any] = {
        "rpe_distance_tolerance_ratio": settings.rpe_distance_tolerance_ratio,
        "scale_distance_tolerance_ratio": settings.rpe_distance_tolerance_ratio,
    }
    if rpe_delta is not None:
        kwargs.update(
            rpe_delta_frames=max(1, int(round(rpe_delta.value))) if rpe_delta.unit == "frames" else 1,
            rpe_delta_value=float(rpe_delta.value),
            rpe_delta_unit=rpe_delta.unit,
        )
    if scale_delta is not None:
        kwargs.update(
            scale_delta_value=float(scale_delta.value),
            scale_delta_unit=scale_delta.unit,
        )
    return EvaluationConfig(**kwargs)


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


def _add_vo_rpe_metrics(row: dict[str, Any], report: dict[str, Any], delta: RpeDelta) -> None:
    label = delta.label
    trans = ((report.get("rpe_frame_delta") or {}).get("translation_m") or {})
    prefix = f"rpe_{label}_trans"
    row[f"{prefix}_rmse"] = _stat(trans, "rmse")
    row[f"{prefix}_max"] = _stat(trans, "max")
    row[f"{prefix}_mean"] = _stat(trans, "mean")
    row[f"{prefix}_median"] = _stat(trans, "median")
    row[f"{prefix}_min"] = _stat(trans, "min")
    row[f"{prefix}_sse"] = _sse(trans)
    row[f"{prefix}_std"] = _stat(trans, "std")


def _add_vo_summary(row: dict[str, Any], report: dict[str, Any]) -> None:
    summary = report.get("summary") or {}
    assoc = report.get("association") or {}
    alignment = report.get("alignment") or {}
    row["matched_poses"] = summary.get("matched_poses", "-")
    row["gt_coverage"] = summary.get("gt_pose_coverage_ratio", "-")
    row["est_coverage"] = summary.get("est_pose_coverage_ratio", "-")
    row["duration_s"] = summary.get("duration_s", "-")
    row["alignment_scale"] = alignment.get("scale", "-")
    row["valid_est_after_segment_filter"] = assoc.get("valid_est_after_segment_filter", "-")
    row["dropped_est_invalid_segment"] = assoc.get("dropped_est_invalid_segment", "-")


def default_vo_output_dir(data_root: Path) -> Path:
    return Path(data_root)


def parse_vo_ids(text: str | None) -> list[str] | None:
    return parse_id_list(text)


def _natural_key(text: str) -> tuple[int, str]:
    return (0, f"{int(text):012d}") if str(text).isdigit() else (1, str(text))
