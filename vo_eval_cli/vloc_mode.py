"""Batch SF VLOC fixed-format evaluation for ``vo_eval_cli``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vo_eval.data_loader import load_vloc_evaluation_bundle
from vo_eval.processing import EvaluationConfig, evaluate_vloc_bundle

from .evo_compat import RpeDelta, _failure_row, parse_id_list


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
        bundle = load_vloc_evaluation_bundle(task.data_dir, task.log_dir)
        cfg = _make_vloc_config(settings)
        report = evaluate_vloc_bundle(bundle, cfg)

        row: dict[str, Any] = {
            "log_id": task.log_id,
            "nav_path": str(task.data_dir),
        }
        _add_vloc_summary(row, report)
        row["status"] = "OK"
        row["message"] = ""
        return row
    except Exception as exc:
        return _failure_row(task.log_id, str(task.data_dir), f"ERR:{type(exc).__name__}", str(exc))


def _make_vloc_config(settings: VlocEvalSettings):
    kwargs: dict[str, Any] = {
        "rpe_distance_tolerance_ratio": settings.rpe_distance_tolerance_ratio,
    }
    if settings.rpe_delta is not None:
        kwargs.update(
            rpe_delta_frames=max(1, int(round(settings.rpe_delta.value))) if settings.rpe_delta.unit == "frames" else 1,
            rpe_delta_value=float(settings.rpe_delta.value),
            rpe_delta_unit=settings.rpe_delta.unit,
        )
    return EvaluationConfig(**kwargs)



def _add_vloc_summary(row: dict[str, Any], report: dict[str, Any]) -> None:
    detail_summary = ((report.get("vloc_details") or {}).get("summary") or {})

    row["mean_error_pos_xy"] = detail_summary.get("mean_error_pos_xy", "-")
    row["mean_error_pos_z"] = detail_summary.get("mean_error_pos_z", "-")
    row["mean_error_euler"] = detail_summary.get("mean_error_euler", "-")
    row["max_error_pos_xy"] = detail_summary.get("max_error_pos_xy", "-")
    row["max_error_pos_z"] = detail_summary.get("max_error_pos_z", "-")
    row["max_error_euler"] = detail_summary.get("max_error_euler", "-")


def default_vloc_output_dir(data_root: Path) -> Path:
    return Path(data_root)


def parse_vloc_ids(text: str | None) -> list[str] | None:
    return parse_id_list(text)


def _natural_key(text: str) -> tuple[int, str]:
    return (0, f"{int(text):012d}") if str(text).isdigit() else (1, str(text))
