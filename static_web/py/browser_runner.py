"""Browser wrapper for the static Pyodide build.

The static web app loads this module inside Pyodide. It now follows the same
fixed-contract entry model as the refactor backend:
- VLOC mode: data_dir/imu.txt + log_dir/vloc.txt + home_point + calib_raw
- VO mode:   data_dir/imu.txt + log_dir/vo.txt   + home_point + calib_raw

JavaScript passes file contents, Python validates/parses them with the fixed
parsers, then returns report JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve()
_REPO_ROOT = _MODULE_PATH.parents[2] if len(_MODULE_PATH.parents) > 2 else Path("/")
if (_REPO_ROOT / "vo_eval").exists() and str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from vo_eval.evaluator import (  # noqa: E402
    EvaluationConfig,
    evaluate_vloc_bundle,
    evaluate_vo_bundle,
    parse_calib_raw_fixed,
    parse_home_point_fixed,
    parse_imu_fixed,
    parse_vloc_fixed,
    parse_vo_fixed,
    report_to_json,
    SfVlocBundle,
    SfVoBundle,
)

_LAST_REPORT: dict | None = None


def _config_from_json(config_json: str) -> EvaluationConfig:
    config_data = json.loads(config_json)
    return EvaluationConfig(**config_data)


def _remember_report(report: dict) -> dict:
    """Store the full report in Pyodide so the browser can fetch heavy slices later."""
    global _LAST_REPORT
    _LAST_REPORT = report
    return report


def _light_report(report: dict) -> dict:
    """Return the initial browser payload without heavy export-only tables.

    The first render still keeps all data required by the visible charts:
    - vloc_details.comparison / vo_details.comparison for trajectory and error plots.
    - trajectory_exports.rpe_per_frame for the two RPE plots.
    - trajectory_exports.scale_per_frame for the VO local Sim3 scale plot.

    Large tables used only for download are fetched on demand via get_report_slice_json().
    This avoids serializing per_pose, segment_records and the full Excel sheet payload
    during the critical "Run evaluation" path.
    """
    skip_keys = {"per_pose", "segment_records", "trajectory_exports"}
    light = {key: value for key, value in report.items() if key not in skip_keys}
    entry_mode = (report.get("inputs") or {}).get("entry_mode")
    trajectory_exports = report.get("trajectory_exports") or {}
    rpe_per_frame = trajectory_exports.get("rpe_per_frame")
    scale_per_frame = trajectory_exports.get("scale_per_frame")
    if rpe_per_frame is not None:
        light.setdefault("trajectory_exports", {})["rpe_per_frame"] = rpe_per_frame
    if entry_mode == "vo" and scale_per_frame is not None:
        light.setdefault("trajectory_exports", {})["scale_per_frame"] = scale_per_frame
    light["report_layers"] = {
        "initial_payload": "light",
        "omitted": sorted(skip_keys),
        "download_slices_available": [
            "full_report",
            "per_pose",
            "segment_records",
            "worst_segments",
            "config",
            "trajectory_exports",
        ],
    }
    return light


def get_report_slice_json(slice_name: str) -> str:
    """Return one full-report slice for download/export after evaluation."""
    if _LAST_REPORT is None:
        raise RuntimeError("No report has been evaluated yet")
    if slice_name == "full_report":
        return report_to_json(_LAST_REPORT)
    if slice_name == "trajectory_exports":
        return report_to_json(_LAST_REPORT.get("trajectory_exports") or {})
    if slice_name in {"per_pose", "segment_records", "worst_segments", "config"}:
        return report_to_json(_LAST_REPORT.get(slice_name, [] if slice_name != "config" else {}))
    raise ValueError(f"Unknown report slice: {slice_name}")


def evaluate_vloc_bundle_json(
    imu_text: str,
    vloc_text: str,
    home_point_text: str,
    calib_raw_text: str,
    config_json: str,
    imu_name: str = "imu.txt",
    vloc_name: str = "vloc.txt",
    home_point_name: str = "home_point.txt",
    calib_raw_name: str = "calib_raw.yaml",
) -> str:
    config = _config_from_json(config_json)
    nav = parse_imu_fixed(imu_text, name=imu_name)
    est = parse_vloc_fixed(vloc_text, name=vloc_name)
    home_point = parse_home_point_fixed(home_point_text, name=home_point_name)
    calibration = parse_calib_raw_fixed(calib_raw_text, name=calib_raw_name)
    bundle = SfVlocBundle(
        nav=nav,
        vloc=est,
        home_point=home_point,
        calibration=calibration,
        data_dir=Path("/data_dir"),
        log_dir=Path("/log_dir"),
        files={},
    )
    report = evaluate_vloc_bundle(bundle, config)
    return report_to_json(report)


def evaluate_vloc_bundle_json_light(
    imu_text: str,
    vloc_text: str,
    home_point_text: str,
    calib_raw_text: str,
    config_json: str,
    imu_name: str = "imu.txt",
    vloc_name: str = "vloc.txt",
    home_point_name: str = "home_point.txt",
    calib_raw_name: str = "calib_raw.yaml",
) -> str:
    config = _config_from_json(config_json)
    nav = parse_imu_fixed(imu_text, name=imu_name)
    est = parse_vloc_fixed(vloc_text, name=vloc_name)
    home_point = parse_home_point_fixed(home_point_text, name=home_point_name)
    calibration = parse_calib_raw_fixed(calib_raw_text, name=calib_raw_name)
    bundle = SfVlocBundle(
        nav=nav,
        vloc=est,
        home_point=home_point,
        calibration=calibration,
        data_dir=Path("/data_dir"),
        log_dir=Path("/log_dir"),
        files={},
    )
    return report_to_json(_light_report(_remember_report(evaluate_vloc_bundle(bundle, config))))


def evaluate_vo_bundle_json(
    imu_text: str,
    vo_text: str,
    home_point_text: str,
    calib_raw_text: str,
    config_json: str,
    imu_name: str = "imu.txt",
    vo_name: str = "vo.txt",
    home_point_name: str = "home_point.txt",
    calib_raw_name: str = "calib_raw.yaml",
) -> str:
    config = _config_from_json(config_json)
    nav = parse_imu_fixed(imu_text, name=imu_name)
    est = parse_vo_fixed(vo_text, name=vo_name)
    home_point = parse_home_point_fixed(home_point_text, name=home_point_name)
    calibration = parse_calib_raw_fixed(calib_raw_text, name=calib_raw_name)
    bundle = SfVoBundle(
        nav=nav,
        vo=est,
        home_point=home_point,
        calibration=calibration,
        data_dir=Path("/data_dir"),
        log_dir=Path("/log_dir"),
        files={},
    )
    report = evaluate_vo_bundle(bundle, config)
    return report_to_json(report)


def evaluate_vo_bundle_json_light(
    imu_text: str,
    vo_text: str,
    home_point_text: str,
    calib_raw_text: str,
    config_json: str,
    imu_name: str = "imu.txt",
    vo_name: str = "vo.txt",
    home_point_name: str = "home_point.txt",
    calib_raw_name: str = "calib_raw.yaml",
) -> str:
    config = _config_from_json(config_json)
    nav = parse_imu_fixed(imu_text, name=imu_name)
    est = parse_vo_fixed(vo_text, name=vo_name)
    home_point = parse_home_point_fixed(home_point_text, name=home_point_name)
    calibration = parse_calib_raw_fixed(calib_raw_text, name=calib_raw_name)
    bundle = SfVoBundle(
        nav=nav,
        vo=est,
        home_point=home_point,
        calibration=calibration,
        data_dir=Path("/data_dir"),
        log_dir=Path("/log_dir"),
        files={},
    )
    return report_to_json(_light_report(_remember_report(evaluate_vo_bundle(bundle, config))))
