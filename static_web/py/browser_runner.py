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
from pathlib import Path

from vo_eval.evaluator import (
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


def _config_from_json(config_json: str) -> EvaluationConfig:
    config_data = json.loads(config_json)
    return EvaluationConfig(**config_data)


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
