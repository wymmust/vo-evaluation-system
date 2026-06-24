"""Evo-compatible batch metrics built on top of ``vo_eval.evaluator``.

This module intentionally lives outside the core ``vo_eval`` package.  It adapts
pipeline-style TUM log directories to a small summary table that matches the
existing evo/Matlab Excel report shape.
"""

from __future__ import annotations

import json
import math
import re

import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RpeDelta:
    """RPE interval parsed from labels such as ``1f`` or ``100m``."""

    label: str
    value: float
    unit: str  # "frames" or "meters"


@dataclass(frozen=True)
class TumTask:
    """One TUM evaluation task discovered under a numeric log directory."""

    log_id: str
    log_dir: Path
    nav_path: Path
    gt_file: Path
    est_file: Path
    source: str


@dataclass(frozen=True)
class TumEvalSettings:
    """Evaluation parameters passed to ``vo_eval.evaluator``."""

    alignment: str = "sim3"
    association_mode: str = "interpolate_gt"
    max_time_diff_s: float | None = None
    max_interpolation_gap_s: float | None = 1.0
    allow_extrapolation: bool = False
    continuous_segment_policy: str = "all"
    rpe_distance_tolerance_ratio: float = 0.05


_DELTA_RE = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[fFmM])\s*$")


def parse_rpe_delta(text: str) -> RpeDelta:
    """Parse one delta spec.

    Accepted examples:
        ``1f``   -> one-frame RPE
        ``100m`` -> 100-meter RPE
    """

    match = _DELTA_RE.match(text)
    if not match:
        raise ValueError(f"Invalid RPE delta '{text}'. Use forms like 1f,100m,500m.")
    value = float(match.group("value"))
    unit_raw = match.group("unit").lower()
    if value <= 0:
        raise ValueError(f"RPE delta must be positive: {text}")
    label_value = int(value) if value.is_integer() else value
    label = f"{label_value}{unit_raw}"
    unit = "frames" if unit_raw == "f" else "meters"
    return RpeDelta(label=str(label), value=value, unit=unit)


def parse_rpe_deltas(text: str) -> list[RpeDelta]:
    """Parse a comma-separated delta list."""

    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        raise ValueError("At least one RPE delta is required.")
    return [parse_rpe_delta(part) for part in parts]


def parse_id_list(text: str | None) -> list[str] | None:
    """Parse comma/space separated log IDs."""

    if not text:
        return None
    parts = re.split(r"[\s,]+", text.strip())
    ids = [part for part in parts if part]
    return ids or None


def discover_tum_tasks(
    log_root: Path,
    *,
    trajectory_file: str = "trajectory_tum.txt",
    gt_file: str = "groundtruth_tum.txt",
    log_ids: list[str] | None = None,
    log_range: tuple[int, int] | None = None,
) -> tuple[list[TumTask], list[dict[str, Any]]]:
    """Discover numeric log directories and resolve their dataset paths.

    The preferred contract is the pipeline ``run_metadata.json`` file.  That
    keeps this CLI independent from ``slam_pipeline`` internals while still
    matching its current output layout.
    """

    log_root = Path(log_root)
    if not log_root.is_dir():
        raise FileNotFoundError(f"log_root not found: {log_root}")

    selected_ids = _selected_log_ids(log_root, log_ids=log_ids, log_range=log_range)
    tasks: list[TumTask] = []
    failures: list[dict[str, Any]] = []

    for log_id in selected_ids:
        log_dir = log_root / log_id
        meta_path = log_dir / "run_metadata.json"
        meta = _read_metadata(meta_path)
        nav_path = _metadata_dataset_path(meta)
        nav_display = str(nav_path) if nav_path else "-"

        if nav_path is None:
            failures.append(_failure_row(log_id, nav_display, "NO_METADATA", f"missing dataset_path in {meta_path}"))
            continue

        est_path = log_dir / trajectory_file
        gt_path = nav_path / gt_file

        if not est_path.is_file():
            failures.append(_failure_row(log_id, nav_display, "NO_EST", f"missing {est_path}"))
            continue
        if not gt_path.is_file():
            failures.append(_failure_row(log_id, nav_display, "NO_GT", f"missing {gt_path}"))
            continue

        tasks.append(
            TumTask(
                log_id=log_id,
                log_dir=log_dir,
                nav_path=nav_path,
                gt_file=gt_path,
                est_file=est_path,
                source=str(meta_path) if meta_path.is_file() else "metadata:none",
            )
        )

    return tasks, failures


def evaluate_tum_task(
    task: TumTask,
    deltas: list[RpeDelta],
    settings: TumEvalSettings,
    *,
    include_extra_summary: bool = True,
) -> dict[str, Any]:
    """Evaluate one TUM pair and return a flat Excel row."""

    try:
        evaluator = _load_vo_evaluator()
        gt = evaluator.load_trajectory_from_text(
            task.gt_file.read_text(encoding="utf-8", errors="replace"),
            "tum",
            str(task.gt_file),
        )
        est = evaluator.load_trajectory_from_text(
            task.est_file.read_text(encoding="utf-8", errors="replace"),
            "tum",
            str(task.est_file),
        )

        row: dict[str, Any] = {
            "log_id": task.log_id,
            "nav_path": str(task.nav_path),
            "_frame_count": int(len(est.positions)),
        }

        base_report: dict[str, Any] | None = None
        for delta in deltas:
            cfg = _make_config(evaluator, settings, delta)
            report = evaluator.evaluate_trajectories(gt, est, cfg)
            if base_report is None:
                base_report = report
            _add_evo_compatible_rpe_metrics(row, delta, report, evaluator)

        if base_report is not None:
            _add_ape_metrics(row, base_report)
            if include_extra_summary:
                _add_extra_summary(row, base_report)

        row["status"] = "OK"
        row["message"] = ""
        return row
    except Exception as exc:  # Keep batch execution moving.
        return _failure_row(task.log_id, str(task.nav_path), f"ERR:{type(exc).__name__}", str(exc))


def _load_vo_evaluator():
    try:
        from vo_eval import evaluator
    except ModuleNotFoundError as exc:
        missing = exc.name or "dependency"
        raise RuntimeError(
            f"Cannot import vo_eval dependency '{missing}'. "
            "Install vo-evaluation-system requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return evaluator


def _make_config(evaluator, settings: TumEvalSettings, delta: RpeDelta):
    return evaluator.EvaluationConfig(
        alignment=settings.alignment,
        association_mode=settings.association_mode,
        max_time_diff_s=settings.max_time_diff_s,
        max_interpolation_gap_s=settings.max_interpolation_gap_s,
        allow_extrapolation=settings.allow_extrapolation,
        interpolate_rotation=True,
        interpolation_position_method="linear",
        interpolation_rotation_method="slerp",
        time_offset_s=0.0,
        rpe_delta_frames=max(1, int(round(delta.value))) if delta.unit == "frames" else 1,
        rpe_delta_value=float(delta.value),
        rpe_delta_unit=delta.unit,
        rpe_distance_tolerance_ratio=settings.rpe_distance_tolerance_ratio,
        scale_delta_value=float(delta.value),
        scale_delta_unit=delta.unit,
        scale_distance_tolerance_ratio=settings.rpe_distance_tolerance_ratio,
        continuous_segment_policy=settings.continuous_segment_policy,
    )


def _add_evo_compatible_rpe_metrics(
    row: dict[str, Any],
    delta: RpeDelta,
    report: dict[str, Any],
    evaluator,
) -> None:
    """Add RPE metrics using evo's default pair selection.

    ``evo_rpe`` defaults to non-overlapping pairs.  For meter deltas, pair
    indices are selected from the aligned estimate trajectory's accumulated
    path.  This differs from ``vo_eval``'s diagnostic meter RPE, which searches
    around every frame, so the CLI implements the evo-compatible reduction here
    without changing the core evaluator.
    """

    stats = _evo_compatible_rpe_stats(delta, report, evaluator)
    if stats is None:
        # Fallback keeps a useful row if report internals change.
        stats = ((report.get("rpe_frame_delta") or {}).get("translation_m") or {})
    _add_rpe_stat_metrics(row, delta.label, stats)


def _add_rpe_stat_metrics(row: dict[str, Any], label: str, trans: dict[str, Any]) -> None:
    prefix = f"rpe_{label}_trans"
    row[f"{prefix}_rmse"] = _stat(trans, "rmse")
    row[f"{prefix}_max"] = _stat(trans, "max")
    row[f"{prefix}_mean"] = _stat(trans, "mean")
    row[f"{prefix}_median"] = _stat(trans, "median")
    row[f"{prefix}_min"] = _stat(trans, "min")
    row[f"{prefix}_sse"] = _sse(trans)
    row[f"{prefix}_std"] = _stat(trans, "std")


def _evo_compatible_rpe_stats(delta: RpeDelta, report: dict[str, Any], evaluator) -> dict[str, Any] | None:
    per_pose = report.get("per_pose")
    if per_pose is None or len(per_pose) < 2:
        return None

    try:
        gt_pos = per_pose[["gt_x_m", "gt_y_m", "gt_z_m"]].to_numpy(dtype=float)
        est_pos = per_pose[["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"]].to_numpy(dtype=float)
    except Exception:
        return None

    pairs = _evo_default_pairs(est_pos, delta)
    if not pairs:
        return None

    gt_rot, est_rot = _rotations_from_per_pose(per_pose, evaluator)
    errors: list[float] = []
    for i, j in pairs:
        trans_error, _rot_error = evaluator.relative_error(gt_pos, est_pos, gt_rot, est_rot, i, j)
        errors.append(float(trans_error))

    stats = evaluator.describe(np.asarray(errors, dtype=float))
    return stats if stats is not None else None


def _evo_default_pairs(est_positions: np.ndarray, delta: RpeDelta) -> list[tuple[int, int]]:
    n = int(len(est_positions))
    if n < 2:
        return []

    if delta.unit == "frames":
        step = max(1, int(delta.value))
        ids = np.arange(0, n, step, dtype=int).tolist()
        return [(int(i), int(j)) for i, j in zip(ids, ids[1:])]

    ids: list[int] = []
    previous = np.asarray(est_positions[0], dtype=float)
    current_path = 0.0
    for i, current in enumerate(np.asarray(est_positions, dtype=float)):
        current_path += float(np.linalg.norm(current - previous))
        previous = current
        if current_path >= float(delta.value):
            ids.append(int(i))
            current_path = 0.0
    return [(int(i), int(j)) for i, j in zip(ids, ids[1:])]


def _rotations_from_per_pose(per_pose, evaluator) -> tuple[np.ndarray | None, np.ndarray | None]:
    gt_cols = ["gt_yaw_deg", "gt_pitch_deg", "gt_roll_deg"]
    est_cols = ["est_yaw_aligned_deg", "est_pitch_aligned_deg", "est_roll_aligned_deg"]
    if not all(col in per_pose for col in gt_cols + est_cols):
        return None, None
    try:
        gt_ypr = np.radians(per_pose[gt_cols].to_numpy(dtype=float))
        est_ypr = np.radians(per_pose[est_cols].to_numpy(dtype=float))
        gt_rot = evaluator.euler_yaw_pitch_roll_to_matrix(gt_ypr[:, 0], gt_ypr[:, 1], gt_ypr[:, 2])
        est_rot = evaluator.euler_yaw_pitch_roll_to_matrix(est_ypr[:, 0], est_ypr[:, 1], est_ypr[:, 2])
        return gt_rot, est_rot
    except Exception:
        return None, None


def _add_ape_metrics(row: dict[str, Any], report: dict[str, Any]) -> None:
    ape = report.get("ate_position_m") or {}
    row["ape_trans_max"] = _stat(ape, "max")
    row["ape_trans_mean"] = _stat(ape, "mean")
    row["ape_trans_median"] = _stat(ape, "median")
    row["ape_trans_min"] = _stat(ape, "min")
    row["ape_trans_rmse"] = _stat(ape, "rmse")
    row["ape_trans_sse"] = _sse(ape)
    row["ape_trans_std"] = _stat(ape, "std")


def _add_extra_summary(row: dict[str, Any], report: dict[str, Any]) -> None:
    summary = report.get("summary") or {}
    alignment = report.get("alignment") or {}
    row["matched_poses"] = summary.get("matched_poses", "-")
    row["gt_coverage"] = summary.get("gt_pose_coverage_ratio", "-")
    row["est_coverage"] = summary.get("est_pose_coverage_ratio", "-")
    row["duration_s"] = summary.get("duration_s", "-")
    row["alignment_scale"] = alignment.get("scale", "-")


def _stat(stats: dict[str, Any], key: str) -> float | str:
    value = stats.get(key)
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return number if math.isfinite(number) else "-"


def _sse(stats: dict[str, Any]) -> float | str:
    rmse = _stat(stats, "rmse")
    count = stats.get("count")
    if not isinstance(rmse, float):
        return "-"
    try:
        n = int(count)
    except (TypeError, ValueError):
        return "-"
    return float(rmse * rmse * n)


def _selected_log_ids(
    log_root: Path,
    *,
    log_ids: list[str] | None,
    log_range: tuple[int, int] | None,
) -> list[str]:
    if log_ids is not None:
        return [str(item) for item in log_ids if (log_root / str(item)).is_dir()]

    numeric = sorted(
        [entry.name for entry in log_root.iterdir() if entry.is_dir() and entry.name.isdigit()],
        key=int,
    )
    if log_range is None:
        return numeric
    start, end = log_range
    return [item for item in numeric if start <= int(item) <= end]


def _read_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _metadata_dataset_path(meta: dict[str, Any]) -> Path | None:
    raw = meta.get("dataset_path") or meta.get("nav_gt_path")
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.is_dir() else None


def _failure_row(log_id: str, nav_path: str, status: str, message: str) -> dict[str, Any]:
    return {
        "log_id": log_id,
        "nav_path": nav_path,
        "status": status,
        "message": message,
    }
