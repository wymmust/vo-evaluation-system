"""Recursive Baseline dataset evaluation helpers for slam_pipeline.

This module keeps the vendored evaluator usable without ORB-SLAM3 runtime logs.
It scans SF Baseline dataset directories directly and writes the same Excel
summary format as the normal vo_eval_cli workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .evo_compat import (
    TumEvalSettings,
    TumTask,
    _failure_row,
    evaluate_tum_task,
    parse_rpe_deltas,
)
from .excel_summary import Thresholds, write_eval_summary
from .vo_mode import VoEvalSettings, VoTask, evaluate_vo_task
from .vloc_mode import VlocEvalSettings, VlocTask, evaluate_vloc_task

BASELINE_MODES = ("tum", "vo", "vloc")


@dataclass(frozen=True)
class BaselineOutputs:
    """Paths written by one recursive baseline evaluation run."""

    mode: str
    path: Path
    total_rows: int
    ok_rows: int


def discover_baseline_dirs(data_root: Path) -> list[Path]:
    """Return SF dataset leaf directories under ``data_root``.

    Baseline is grouped by scenario, so the normal one-level ``--data-root``
    discovery is not enough.  ``imu.txt`` is the common marker for the data
    bundles used by TUM/VO/VLOC evaluation.
    """

    root = Path(data_root)
    if not root.is_dir():
        raise FileNotFoundError(f"data_root not found: {root}")

    dirs = {path.parent for path in root.rglob("imu.txt") if path.is_file()}
    return sorted(dirs, key=lambda p: _natural_path_key(p.relative_to(root)))


def run_baseline_modes(
    data_root: Path,
    output_dir: Path,
    *,
    modes: tuple[str, ...] = BASELINE_MODES,
    rpe_deltas: str = "1f,100m,500m",
    tum_est_file: str = "groundtruth_tum.txt",
    gt_file: str = "groundtruth_tum.txt",
    rpe_distance_tolerance_ratio: float = 0.05,
    thresholds: Thresholds | None = None,
) -> list[BaselineOutputs]:
    """Run one or more recursive baseline modes and write Excel files."""

    root = Path(data_root)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset_dirs = discover_baseline_dirs(root)
    parsed_deltas = parse_rpe_deltas(rpe_deltas)
    labels = [delta.label for delta in parsed_deltas]
    thresholds = thresholds or Thresholds()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    outputs: list[BaselineOutputs] = []
    for mode in modes:
        mode = mode.lower().strip()
        if mode not in BASELINE_MODES:
            raise ValueError(f"unsupported baseline mode: {mode}")
        rows = evaluate_baseline_rows(
            mode,
            root,
            dataset_dirs,
            parsed_deltas=parsed_deltas,
            rpe_deltas_text=rpe_deltas,
            tum_est_file=tum_est_file,
            gt_file=gt_file,
            rpe_distance_tolerance_ratio=rpe_distance_tolerance_ratio,
        )
        output_path = out_dir / f"baseline_{mode}_{ts}.xlsx"
        primary_key = (
            "max_error_pos_xy" if mode == "vloc"
            else (_default_rpe_primary_key(parsed_deltas) if mode == "vo" else None)
        )
        actual = write_eval_summary(
            rows,
            output_path,
            rpe_labels=labels,
            thresholds=thresholds,
            primary_key=primary_key,
        )
        ok_rows = sum(1 for row in rows if str(row.get("status", "")).upper() == "OK")
        outputs.append(BaselineOutputs(mode=mode, path=actual, total_rows=len(rows), ok_rows=ok_rows))
    return outputs


def evaluate_baseline_rows(
    mode: str,
    data_root: Path,
    dataset_dirs: list[Path],
    *,
    parsed_deltas,
    rpe_deltas_text: str,
    tum_est_file: str,
    gt_file: str,
    rpe_distance_tolerance_ratio: float,
) -> list[dict[str, Any]]:
    """Evaluate already discovered baseline dataset directories for one mode."""

    rows: list[dict[str, Any]] = []
    if mode == "tum":
        settings = TumEvalSettings(
            alignment="sim3",
            association_mode="interpolate_gt",
            max_time_diff_s=None,
            max_interpolation_gap_s=1.0,
            allow_extrapolation=False,
            continuous_segment_policy="all",
            rpe_distance_tolerance_ratio=rpe_distance_tolerance_ratio,
        )
        for data_dir in dataset_dirs:
            log_id = _relative_id(data_root, data_dir)
            gt_path = data_dir / gt_file
            est_path = data_dir / tum_est_file
            missing = []
            if not gt_path.is_file():
                missing.append(str(gt_path.name))
            if not est_path.is_file():
                missing.append(str(est_path.name))
            if missing:
                rows.append(_failure_row(log_id, str(data_dir), "MISSING_FILES", ",".join(missing)))
                continue
            if _same_file(gt_path, est_path):
                row = _tum_selfcheck_row(log_id, data_dir, gt_path, parsed_deltas)
            else:
                row = evaluate_tum_task(
                    TumTask(
                        log_id=log_id,
                        log_dir=data_dir,
                        nav_path=data_dir,
                        gt_file=gt_path,
                        est_file=est_path,
                        source="baseline:data_dir",
                    ),
                    parsed_deltas,
                    settings,
                    include_extra_summary=True,
                )
            row["tum_est_file"] = tum_est_file
            rows.append(row)
        return rows

    if mode == "vo":
        rpe_delta = parsed_deltas[0] if parsed_deltas else None
        settings = VoEvalSettings(
            max_interpolation_gap_s=1.0,
            continuous_segment_policy="segments",
            rpe_delta=rpe_delta,
            rpe_deltas=tuple(parsed_deltas),
            scale_delta=rpe_delta,
            rpe_distance_tolerance_ratio=rpe_distance_tolerance_ratio,
        )
        required = ("imu.txt", "vo.txt", "calib_raw.yaml")
        for data_dir in dataset_dirs:
            log_id = _relative_id(data_root, data_dir)
            missing = [name for name in required if not (data_dir / name).is_file()]
            if missing:
                rows.append(_failure_row(log_id, str(data_dir), "MISSING_FILES", ",".join(missing)))
                continue
            rows.append(evaluate_vo_task(VoTask(log_id=log_id, data_dir=data_dir, log_dir=data_dir), settings))
        return rows

    if mode == "vloc":
        rpe_delta = parsed_deltas[0] if parsed_deltas else None
        settings = VlocEvalSettings(
            rpe_delta=rpe_delta,
            rpe_distance_tolerance_ratio=rpe_distance_tolerance_ratio,
        )
        required = ("imu.txt", "vloc.txt", "home_point.txt", "calib_raw.yaml")
        for data_dir in dataset_dirs:
            log_id = _relative_id(data_root, data_dir)
            missing = [name for name in required if not (data_dir / name).is_file()]
            if missing:
                rows.append(_failure_row(log_id, str(data_dir), "MISSING_FILES", ",".join(missing)))
                continue
            rows.append(evaluate_vloc_task(VlocTask(log_id=log_id, data_dir=data_dir, log_dir=data_dir), settings))
        return rows

    raise ValueError(f"unsupported baseline mode: {mode}")


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _tum_selfcheck_row(log_id: str, data_dir: Path, gt_path: Path, parsed_deltas) -> dict[str, Any]:
    count, duration_s = _tum_file_stats(gt_path)
    row: dict[str, Any] = {
        "log_id": log_id,
        "nav_path": str(data_dir),
        "_frame_count": count,
        "ape_trans_max": 0.0,
        "ape_trans_mean": 0.0,
        "ape_trans_median": 0.0,
        "ape_trans_min": 0.0,
        "ape_trans_rmse": 0.0,
        "ape_trans_sse": 0.0,
        "ape_trans_std": 0.0,
        "matched_poses": count,
        "gt_coverage": 1.0 if count else 0.0,
        "est_coverage": 1.0 if count else 0.0,
        "duration_s": duration_s,
        "alignment_scale": 1.0,
        "status": "OK",
        "message": "TUM self-check: gt_file used as est_file",
    }
    for delta in parsed_deltas:
        prefix = f"rpe_{delta.label}_trans"
        row[f"{prefix}_rmse"] = 0.0
        row[f"{prefix}_max"] = 0.0
        row[f"{prefix}_mean"] = 0.0
        row[f"{prefix}_median"] = 0.0
        row[f"{prefix}_min"] = 0.0
        row[f"{prefix}_sse"] = 0.0
        row[f"{prefix}_std"] = 0.0
    return row


def _tum_file_stats(path: Path) -> tuple[int, float]:
    count = 0
    first_ts: float | None = None
    last_ts: float | None = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            try:
                ts = float(parts[0])
            except (IndexError, ValueError):
                continue
            if first_ts is None:
                first_ts = ts
            last_ts = ts
            count += 1
    duration = float(last_ts - first_ts) if first_ts is not None and last_ts is not None else 0.0
    return count, duration


def _default_rpe_primary_key(parsed_deltas) -> str | None:
    primary = next((delta for delta in parsed_deltas if delta.unit == "meters"), parsed_deltas[0] if parsed_deltas else None)
    return f"rpe_{primary.label}_trans_rmse" if primary is not None else None


def parse_modes(text: str) -> tuple[str, ...]:
    """Parse comma/space separated baseline modes."""

    parts = [part.strip().lower() for chunk in text.split(",") for part in chunk.split() if part.strip()]
    modes = tuple(parts or BASELINE_MODES)
    unknown = [mode for mode in modes if mode not in BASELINE_MODES]
    if unknown:
        raise ValueError(f"unsupported baseline mode(s): {', '.join(unknown)}")
    return modes


def _relative_id(root: Path, data_dir: Path) -> str:
    try:
        return data_dir.relative_to(root).as_posix()
    except ValueError:
        return data_dir.as_posix()


def _natural_path_key(path: Path) -> tuple[tuple[int, str], ...]:
    return tuple(_natural_text_key(part) for part in path.parts)


def _natural_text_key(text: str) -> tuple[int, str]:
    return (0, f"{int(text):012d}") if text.isdigit() else (1, text)
