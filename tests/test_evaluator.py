import json
import math
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import voeval
from voeval import __main__ as voeval_main
from voeval.io import (
    Calibration,
    HomePoint,
    SfVlocBundle,
    SfVoBundle,
    SUPPORTED_EVALUATION_FORMATS,
    Trajectory,
    get_evaluation_format_spec,
    load_vloc_evaluation_bundle,
    load_vo_evaluation_bundle,
    load_trajectory_from_text,
    normalize_evaluation_format,
    parse_home_point_fixed,
    parse_calib_raw_fixed,
    parse_imu_fixed,
    parse_vloc_fixed,
    parse_vo_fixed,
)
from voeval.core import EvaluationConfig
from voeval.cli import main as cli_main
from voeval.debug import configure_logging
from voeval.reports import evaluate_trajectories, evaluate_vloc_bundle, evaluate_vo_bundle, report_to_json
from voeval.core import (
    euler_yaw_pitch_roll_to_matrix,
    interpolate_reference_to_estimate,
    sim3_alignment,
    yaw_from_rot,
)


def test_package_exposes_voeval_console_script():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["voeval"] == "voeval.__main__:main"
    package_data = pyproject["tool"]["setuptools"]["package-data"]["voeval"]
    assert "visualization/package.json" in package_data
    assert "visualization/**/*.html" in package_data
    assert "visualization/**/*.css" in package_data
    assert "visualization/**/*.js" in package_data


def test_package_supports_python38_legacy_editable_install():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    setup_py = repo_root / "setup.py"

    assert pyproject["project"]["requires-python"] == ">=3.8"
    assert setup_py.exists()
    setup_text = setup_py.read_text(encoding="utf-8")
    assert "voeval=voeval.__main__:main" in setup_text
    assert "python_requires=\">=3.8\"" in setup_text
    assert "visualization" in setup_text
    assert "package_data={\"voeval\": _package_data()}" in setup_text


def test_runtime_modules_delay_annotation_evaluation_for_python38():
    repo_root = Path(__file__).resolve().parents[1]
    modern_annotation_markers = (" | None", " | Path", " | str", " | int", " | float", "list[", "dict[", "tuple[", "set[")
    missing_future_import = []
    for path in sorted((repo_root / "voeval").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in modern_annotation_markers):
            if "from __future__ import annotations" not in text:
                missing_future_import.append(path.relative_to(repo_root).as_posix())

    assert missing_future_import == []


def test_vloc_detail_visual_segments_follow_discontinuity_diagnostics():
    bundle = sample_vloc_bundle_with_large_nav_gap()
    report = evaluate_vloc_bundle(bundle, EvaluationConfig())
    comparison = report["vloc_details"]["comparison"]

    assert report["discontinuities"]["all_matches"]["break_count"] == 0
    assert comparison["visual_segment_id"].tolist() == [0, 0, 0]
    assert comparison["segment_id"].tolist() == [0, 0, 0]


def make_tum(rows=120):
    lines = []
    for i in range(rows):
        t = i * 0.1
        x = i * 1.0
        y = 2.0 * np.sin(i / 20.0)
        z = 50.0 + 0.01 * i
        lines.append(f"{t:.3f} {x:.6f} {y:.6f} {z:.6f} 0 0 0 1")
    return "\n".join(lines)


def test_public_evaluation_formats_match_requirement_doc():
    assert SUPPORTED_EVALUATION_FORMATS == ("sf_vloc", "sf_vo", "tum")

    sf_vloc = get_evaluation_format_spec("sf_vloc")
    assert sf_vloc.mode == "sf_vloc"
    assert sf_vloc.required_files == (
        "data_dir/imu.txt",
        "log_dir/vloc.txt",
        "log_dir/home_point.txt",
        "log_dir/calib_raw.yaml",
    )

    sf_vo = get_evaluation_format_spec("sf_vo")
    assert sf_vo.mode == "sf_vo"
    assert sf_vo.required_files == (
        "data_dir/imu.txt",
        "log_dir/vo.txt",
        "log_dir/calib_raw.yaml",
    )

    tum = get_evaluation_format_spec("tum")
    assert tum.mode == "tum"
    assert tum.required_files == ("ground_truth.tum", "estimate.tum")


def test_public_evaluation_format_rejects_legacy_parser_formats():
    for fmt in ["auto", "sf", "vloc", "csv", "kitti", "xyz"]:
        with pytest.raises(ValueError, match="Supported evaluation formats"):
            normalize_evaluation_format(fmt)


def test_public_evaluation_format_rejects_non_canonical_spellings():
    for fmt in ["SF-VLOC", "sf vo", "Tum"]:
        with pytest.raises(ValueError, match="Supported evaluation formats"):
            normalize_evaluation_format(fmt)


def sample_calib_text() -> str:
    return """%YAML:1.0
---
T_imu_body: [ 1, 0, 0, 0.1, 0, 1, 0, 0.2, 0, 0, 1, 0.3, 0, 0, 0, 1 ]
cam0:
  T_cam_imu: [ 0, -1, 0, 1, 1, 0, 0, 2, 0, 0, 1, 3, 0, 0, 0, 1 ]
cam1:
  T_cn_cnm1: [ 1, 0, 0, 4, 0, 1, 0, 5, 0, 0, 1, 6, 0, 0, 0, 1 ]
"""


def sample_identity_calib_text() -> str:
    return """%YAML:1.0
---
T_imu_body: [ 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 ]
cam0:
  T_cam_imu: [ 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 ]
"""


def sample_imu_text() -> str:
    return """ts ts_fcc status flight_mode x y z yaw pitch roll vx vy vz position_reset_count altitude_reset_count heading_reset_count latitude longitude altitude altitude_msl height
10.0 100.0 4194305 3 1 2 3 1.57079632679 0.1 -0.2 0.4 0.5 0.6 0 1 2 31.1 121.2 50 51 5
10.1 100.1 268435457 3 2 3 4 1.67079632679 0.2 -0.3 0.5 0.6 0.7 0 1 2 31.2 121.3 51 52 6
"""


def sample_vloc_text() -> str:
    return """ts status num_inliers reset_count x y z yaw pitch roll latitude longitude height
10.0 2 42 0 11 12 13 90 2 -1 31.1 121.2 5
10.1 3 43 1 12 13 14 91 3 -2 31.2 121.3 6
"""


def sample_vo_text() -> str:
    return """ts num_inliers x y z yaw pitch roll is_keyframe time_cost reset_count
10.0 50 21 22 23 90 2 -1 1 12.5 0
10.1 51 22 23 24 91 3 -2 0 13.5 1
"""


def _latitude_from_north_offset(home_lat_deg: float, north_m: float) -> float:
    return home_lat_deg + north_m / 111320.0


def sample_vloc_bundle_with_large_nav_gap() -> SfVlocBundle:
    home = HomePoint(longitude=121.2, latitude=31.1, altitude_msl=50.0)
    nav_stamps = np.asarray([0.0, 0.5, 1.0, 3.5, 4.0], dtype=float)
    north_samples = np.asarray([0.0, 5.0, 10.0, 35.0, 40.0], dtype=float)
    nav_lat = np.asarray([_latitude_from_north_offset(home.latitude, value) for value in north_samples], dtype=float)
    nav_positions = np.column_stack([north_samples, np.zeros(len(nav_stamps)), np.zeros(len(nav_stamps))])
    nav_rot = euler_yaw_pitch_roll_to_matrix(np.zeros(len(nav_stamps)), np.zeros(len(nav_stamps)), np.zeros(len(nav_stamps)))
    nav = Trajectory(
        "imu.txt",
        nav_stamps,
        nav_positions,
        nav_rot,
        extras={
            "latitude": nav_lat,
            "longitude": np.full(len(nav_stamps), home.longitude, dtype=float),
            "altitude_msl": np.full(len(nav_stamps), home.altitude_msl, dtype=float),
            "height": np.zeros(len(nav_stamps), dtype=float),
            "status": np.zeros(len(nav_stamps), dtype=float),
            "flight_mode": np.zeros(len(nav_stamps), dtype=float),
            "vx": np.zeros(len(nav_stamps), dtype=float),
            "vy": np.zeros(len(nav_stamps), dtype=float),
            "vz": np.zeros(len(nav_stamps), dtype=float),
            "position_reset_count": np.zeros(len(nav_stamps), dtype=float),
            "altitude_reset_count": np.zeros(len(nav_stamps), dtype=float),
            "heading_reset_count": np.zeros(len(nav_stamps), dtype=float),
            "navi_mode": np.zeros(len(nav_stamps), dtype=float),
            "rtk_yaw": np.zeros(len(nav_stamps), dtype=float),
            "rtk_altitude": np.zeros(len(nav_stamps), dtype=float),
        },
        source_format="sf_imu",
    )

    vloc_stamps = np.asarray([0.25, 0.75, 2.0, 3.75, 3.9], dtype=float)
    vloc_north = np.asarray([2.5, 7.5, 20.0, 37.5, 39.0], dtype=float)
    vloc_lat = np.asarray([_latitude_from_north_offset(home.latitude, value) for value in vloc_north], dtype=float)
    vloc_positions = np.column_stack([vloc_north, np.zeros(len(vloc_stamps)), np.full(len(vloc_stamps), -home.altitude_msl, dtype=float)])
    vloc_rot = euler_yaw_pitch_roll_to_matrix(np.zeros(len(vloc_stamps)), np.zeros(len(vloc_stamps)), np.zeros(len(vloc_stamps)))
    vloc = Trajectory(
        "vloc.txt",
        vloc_stamps,
        vloc_positions,
        vloc_rot,
        extras={
            "status": np.asarray([2, 2, 2, 1, 2], dtype=float),
            "num_inliers": np.asarray([30, 31, 32, 33, 34], dtype=float),
            "reset_count": np.zeros(len(vloc_stamps), dtype=float),
            "latitude": vloc_lat,
            "longitude": np.full(len(vloc_stamps), home.longitude, dtype=float),
            "altitude": np.abs(vloc_positions[:, 2]),
            "altitude_msl": np.abs(vloc_positions[:, 2]),
            "height": np.asarray([5.0, 5.0, 5.0, 5.0, 5.0], dtype=float),
            "vloc_mode": np.asarray([2, 2, 2, 1, 2], dtype=float),
        },
        source_format="sf_vloc",
    )
    parsed_calib = parse_calib_raw_fixed(sample_identity_calib_text())
    calibration = Calibration(
        t_imu_body=parsed_calib.t_imu_body,
        t_cam_imu=parsed_calib.t_cam_imu,
        t_cn_cnm1=None,
    )
    return SfVlocBundle(
        nav=nav,
        vloc=vloc,
        home_point=home,
        calibration=calibration,
        data_dir=Path("/tmp/data_dir"),
        log_dir=Path("/tmp/log_dir"),
        files={},
    )


def sample_vo_bundle_with_reset_segments() -> SfVoBundle:
    home = HomePoint(longitude=121.2, latitude=31.1, altitude_msl=50.0)
    nav_stamps = np.round(np.arange(0.0, 55.1, 0.1), 3)
    nav_positions = np.column_stack([nav_stamps, np.zeros(len(nav_stamps)), np.zeros(len(nav_stamps))])
    nav_rot = euler_yaw_pitch_roll_to_matrix(np.zeros(len(nav_stamps)), np.zeros(len(nav_stamps)), np.zeros(len(nav_stamps)))
    nav = Trajectory(
        "imu.txt",
        nav_stamps,
        nav_positions,
        nav_rot,
        extras={
            "latitude": np.full(len(nav_stamps), home.latitude, dtype=float),
            "longitude": np.full(len(nav_stamps), home.longitude, dtype=float),
            "altitude_msl": np.full(len(nav_stamps), home.altitude_msl, dtype=float),
            "height": np.zeros(len(nav_stamps), dtype=float),
            "status": np.zeros(len(nav_stamps), dtype=float),
            "flight_mode": np.zeros(len(nav_stamps), dtype=float),
            "vx": np.ones(len(nav_stamps), dtype=float),
            "vy": np.zeros(len(nav_stamps), dtype=float),
            "vz": np.zeros(len(nav_stamps), dtype=float),
            "position_reset_count": np.zeros(len(nav_stamps), dtype=float),
            "altitude_reset_count": np.zeros(len(nav_stamps), dtype=float),
            "heading_reset_count": np.zeros(len(nav_stamps), dtype=float),
            "navi_mode": np.zeros(len(nav_stamps), dtype=float),
            "rtk_yaw": np.zeros(len(nav_stamps), dtype=float),
            "rtk_altitude": np.zeros(len(nav_stamps), dtype=float),
        },
        source_format="sf_imu",
    )

    invalid_stamps = np.round(np.arange(0.0, 5.0, 0.1), 3)
    valid_1_stamps = np.round(np.arange(10.0, 30.1, 0.1), 3)
    valid_2_stamps = np.round(np.arange(30.2, 50.3, 0.1), 3)
    vo_stamps = np.concatenate([invalid_stamps, valid_1_stamps, valid_2_stamps])
    vo_positions = np.column_stack([vo_stamps, np.zeros(len(vo_stamps)), np.zeros(len(vo_stamps))])
    vo_rot = euler_yaw_pitch_roll_to_matrix(np.zeros(len(vo_stamps)), np.zeros(len(vo_stamps)), np.zeros(len(vo_stamps)))
    vo = Trajectory(
        "vo.txt",
        vo_stamps,
        vo_positions,
        vo_rot,
        extras={
            "num_inliers": np.full(len(vo_stamps), 80.0, dtype=float),
            "is_keyframe": np.ones(len(vo_stamps), dtype=float),
            "time_cost": np.full(len(vo_stamps), 12.0, dtype=float),
            "reset_count": np.concatenate(
                [
                    np.zeros(len(invalid_stamps), dtype=float),
                    np.ones(len(valid_1_stamps), dtype=float),
                    np.full(len(valid_2_stamps), 2.0, dtype=float),
                ]
            ),
        },
        source_format="sf_vo",
    )
    calibration = parse_calib_raw_fixed(sample_identity_calib_text())
    return SfVoBundle(
        nav=nav,
        vo=vo,
        calibration=calibration,
        data_dir=Path("/tmp/data_dir"),
        log_dir=Path("/tmp/log_dir"),
        files={},
    )


def test_vloc_detail_summary_contains_requested_scalar_error_metrics():
    bundle = sample_vloc_bundle_with_large_nav_gap()
    report = evaluate_vloc_bundle(bundle)
    summary = report["vloc_details"]["summary"]

    assert "mean_error_pos_xy" in summary
    assert "mean_error_pos_z" in summary
    assert "mean_error_euler" in summary
    assert "max_error_pos_xy" in summary
    assert "max_error_pos_z" in summary
    assert "max_error_euler" in summary
    assert math.isfinite(summary["mean_error_pos_xy"])
    assert math.isfinite(summary["max_error_pos_xy"])


def write_sf_dirs(tmp_path):
    data_dir = tmp_path / "data_dir"
    log_dir = tmp_path / "log_dir"
    data_dir.mkdir()
    log_dir.mkdir()
    (data_dir / "imu.txt").write_text(sample_imu_text(), encoding="utf-8")
    (log_dir / "vloc.txt").write_text(sample_vloc_text(), encoding="utf-8")
    (log_dir / "vo.txt").write_text(sample_vo_text(), encoding="utf-8")
    (log_dir / "home_point.txt").write_text("121.2 31.1 51.0\n", encoding="utf-8")
    (log_dir / "calib_raw.yaml").write_text(sample_calib_text(), encoding="utf-8")
    return data_dir, log_dir


def test_fixed_sf_parsers_use_documented_column_order_without_header_adaptation():
    imu = parse_imu_fixed(sample_imu_text(), name="imu.txt")
    assert imu.source_format == "sf_imu"
    assert np.allclose(imu.stamps, [10.0, 10.1])
    assert np.allclose(imu.positions[0], [1, 2, 3])
    assert abs(yaw_from_rot(imu.rotations)[0] - np.pi / 2) < 1e-9
    assert np.allclose(imu.extras["vx"], [0.4, 0.5])
    assert np.allclose(imu.extras["navi_mode"], [1, 1])

    vloc = parse_vloc_fixed(sample_vloc_text(), name="vloc.txt")
    assert vloc.source_format == "sf_vloc"
    assert np.allclose(vloc.positions[0], [11, 12, 13])
    assert abs(yaw_from_rot(vloc.rotations)[0] - np.pi / 2) < 1e-9
    assert np.allclose(vloc.extras["vloc_mode"], [2, 3])

    vo = parse_vo_fixed(sample_vo_text(), name="vo.txt")
    assert vo.source_format == "sf_vo"
    assert np.allclose(vo.positions[0], [21, 22, 23])
    assert np.allclose(vo.extras["time_cost"], [12.5, 13.5])
    assert "depth_mean" not in vo.extras
    assert "depth_min" not in vo.extras
    assert "depth_max" not in vo.extras

    home = parse_home_point_fixed("121.2 31.1 51.0\n", name="home_point.txt")
    assert home.longitude == 121.2
    assert home.latitude == 31.1
    assert home.altitude_msl == 51.0


def test_vo_fixed_accepts_legacy_14_column_format_without_using_depth_columns():
    legacy_text = """ts num_inliers x y z yaw pitch roll is_keyframe time_cost reset_count depth_mean depth_min depth_max
10.0 50 21 22 23 90 2 -1 1 12.5 0 4.1 0.2 8.9
"""

    vo = parse_vo_fixed(legacy_text, name="vo.txt")

    assert vo.source_format == "sf_vo"
    assert np.allclose(vo.positions[0], [21, 22, 23])
    assert np.allclose(vo.extras["time_cost"], [12.5])
    assert "raw_numeric_table" not in vo.extras


def test_fixed_parsers_do_not_keep_raw_numeric_tables_and_validate_integer_columns():
    imu = parse_imu_fixed(sample_imu_text(), name="imu.txt")
    vloc = parse_vloc_fixed(sample_vloc_text(), name="vloc.txt")
    vo = parse_vo_fixed(sample_vo_text(), name="vo.txt")

    assert "raw_numeric_table" not in imu.extras
    assert "raw_numeric_table" not in vloc.extras
    assert "raw_numeric_table" not in vo.extras
    assert np.allclose(vloc.extras["altitude"], np.abs(vloc.positions[:, 2]))
    assert np.allclose(vloc.extras["altitude_msl"], np.abs(vloc.positions[:, 2]))
    assert np.allclose(vloc.extras["height"], [5.0, 6.0])

    bad_status = sample_vloc_text().replace("10.0 2 42", "10.0 2.5 42", 1)
    with pytest.raises(ValueError, match="integer"):
        parse_vloc_fixed(bad_status, name="vloc.txt")


def test_load_trajectory_rejects_missing_path_and_invalid_tum_quaternion(tmp_path):
    missing = tmp_path / "missing.tum"
    with pytest.raises(FileNotFoundError):
        voeval.load_trajectory(missing)
    with pytest.raises(FileNotFoundError):
        voeval.load_trajectory(str(missing))

    with pytest.raises(ValueError, match="zero-norm"):
        load_trajectory_from_text("0 0 0 0 0 0 0 0\n1 1 0 0 0 0 0 1\n", fmt="tum", name="bad")


def test_trajectory_helpers_reject_mismatched_extra_lengths():
    with pytest.raises(ValueError, match="extras"):
        Trajectory("bad", [0, 1], [[0, 0, 0], [1, 0, 0]], extras={"bad": np.asarray([1, 2, 3])})


def test_evaluation_config_normalizes_units_and_rejects_invalid_values():
    cfg = EvaluationConfig(rpe_delta_value=100, rpe_delta_unit="m", scale_delta_value=10, scale_delta_unit="f")
    assert cfg.rpe_delta_unit == "meters"
    assert cfg.scale_delta_unit == "frames"

    with pytest.raises(ValueError, match="rpe_delta_value"):
        EvaluationConfig(rpe_delta_value=0)
    with pytest.raises(ValueError, match="rpe_delta_unit"):
        EvaluationConfig(rpe_delta_unit="seconds")


def test_vloc_evaluation_bundle_loads_vloc_directory_contract(tmp_path):
    data_dir, log_dir = write_sf_dirs(tmp_path)
    bundle = load_vloc_evaluation_bundle(data_dir, log_dir)

    assert bundle.nav.source_format == "sf_imu"
    assert bundle.vloc.source_format == "sf_vloc"
    assert np.allclose(bundle.vloc.positions[0], [11, 12, 13])
    assert bundle.home_point.longitude == 121.2
    assert np.allclose(bundle.calibration.t_imu_body[:3, 3], [0.1, 0.2, 0.3])
    assert bundle.files["estimate"].name == "vloc.txt"


def test_vo_evaluation_bundle_loads_vo_directory_contract_without_using_vloc(tmp_path):
    data_dir, log_dir = write_sf_dirs(tmp_path)
    (log_dir / "home_point.txt").unlink()

    bundle = load_vo_evaluation_bundle(data_dir, log_dir, "vo.txt")

    assert bundle.nav.source_format == "sf_imu"
    assert bundle.vo.source_format == "sf_vo"
    assert np.allclose(bundle.vo.positions[0], [21, 22, 23])
    assert bundle.files["estimate"].name == "vo.txt"
    assert "home_point" not in bundle.files
    assert not hasattr(bundle, "home_point")


def test_bundle_loader_reports_missing_required_file(tmp_path):
    data_dir, log_dir = write_sf_dirs(tmp_path)
    (log_dir / "vloc.txt").unlink()

    with pytest.raises(FileNotFoundError, match="log_dir/vloc.txt"):
        load_vloc_evaluation_bundle(data_dir, log_dir)


def test_vloc_evaluation_bundle_still_requires_home_point(tmp_path):
    data_dir, log_dir = write_sf_dirs(tmp_path)
    (log_dir / "home_point.txt").unlink()

    with pytest.raises(FileNotFoundError, match="log_dir/home_point.txt"):
        load_vloc_evaluation_bundle(data_dir, log_dir)


def test_vloc_bundle_uses_fixed_interpolation_defaults_and_drops_invalid_frames():
    bundle = sample_vloc_bundle_with_large_nav_gap()
    report = evaluate_vloc_bundle(bundle, EvaluationConfig())

    assert report["inputs"]["entry_mode"] == "vloc"
    assert "fixed_rules" not in report["inputs"]
    assert "config" not in report
    assert "method" not in report["association"]
    assert "max_interpolation_gap_s" not in report["association"]
    assert "time_offset_s" not in report["association"]
    assert report["summary"]["matched_poses"] == 3
    assert report["association"]["dropped_est_large_gt_gap"] == 1
    assert report["association"]["dropped_est_invalid_mode"] == 1
    assert report["alignment"]["base_mode"] == "none"


def test_vloc_report_contains_nav_vloc_specific_detail_tables():
    bundle = sample_vloc_bundle_with_large_nav_gap()
    shifted_vloc_north = np.asarray([1.5, 6.5, 19.0, 36.5, 38.0], dtype=float)
    bundle.vloc.extras["latitude"] = np.asarray(
        [_latitude_from_north_offset(bundle.home_point.latitude, value) for value in shifted_vloc_north],
        dtype=float,
    )

    report = evaluate_vloc_bundle(bundle, EvaluationConfig())
    details = report["vloc_details"]
    comparison = details["comparison"]
    nav_status = details["nav_status"]
    vloc_status = details["vloc_status"]

    assert details["summary"]["trajectory_length_m"] > 0
    assert details["summary"]["horizontal_error_mean_m"] == pytest.approx(1.0, abs=0.02)
    assert details["summary"]["vertical_error_max_m"] == pytest.approx(0.0, abs=1e-4)
    assert {"flight_mode", "navi_mode", "rtk_yaw", "rtk_alti", "velocity_norm"}.issubset(nav_status.columns)
    assert {"vloc_mode", "num_inliers", "reset_count"}.issubset(vloc_status.columns)
    assert {"position_error_n_m", "position_error_e_m", "position_error_d_m"}.issubset(comparison.columns)
    assert np.allclose(comparison["position_error_n_m"].to_numpy(), 1.0, atol=0.02)
    assert np.allclose(comparison["position_error_e_m"].to_numpy(), 0.0, atol=1e-6)


def test_vloc_trajectory_exports_omit_sim3_sheets_because_vloc_has_metric_scale():
    bundle = sample_vloc_bundle_with_large_nav_gap()
    report = evaluate_vloc_bundle(bundle, EvaluationConfig())

    exports = report["trajectory_exports"]
    assert "sim3_gt_tum" not in exports
    assert "sim3_vo_tum" not in exports
    assert "scale_frame_delta" not in report
    assert set(exports) == {"rpe_per_frame"}


def test_package_all_exports_vo_bundle_entrypoint():
    assert "evaluate_vo_bundle" in voeval.__all__


def test_cli_requires_explicit_mode_and_directories():
    with pytest.raises(SystemExit):
        cli_main([])


def test_module_main_dispatches_direct_sf_mode_to_cli(monkeypatch):
    received: list[list[str]] = []

    monkeypatch.setattr(voeval_main.cli, "main", lambda argv: received.append(list(argv)) or 0)

    exit_code = voeval_main.main(["sf_vloc", "/data/path", "/log/path", "-v"])

    assert exit_code == 0
    assert received == [["sf_vloc", "/data/path", "/log/path", "-v"]]


def test_module_main_keeps_legacy_flag_mode_entry(monkeypatch):
    received: list[list[str]] = []

    monkeypatch.setattr(voeval_main.cli, "main", lambda argv: received.append(list(argv)) or 0)

    exit_code = voeval_main.main(["--mode", "sf_vloc", "--data_dir", "/data/path", "--log_dir", "/log/path"])

    assert exit_code == 0
    assert received == [["--mode", "sf_vloc", "--data_dir", "/data/path", "--log_dir", "/log/path"]]


def test_cli_accepts_positional_mode_and_directories(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("voeval.cli.load_vloc_evaluation_bundle", lambda data_dir, log_dir: object())
    monkeypatch.setattr(
        "voeval.cli.evaluate_vloc_bundle",
        lambda bundle, config: {
            "inputs": {"entry_mode": "vloc"},
            "rpe_frame_delta": {"translation_m": {"rmse": 1.0, "mean": 0.5, "max": 2.0}, "count": 3},
            "ate_position_m": {"rmse": 2.0, "mean": 1.0},
            "alignment": {"base_mode": "none"},
            "vloc_details": {"summary": {"trajectory_length_m": 100.0}},
        },
    )

    exit_code = cli_main(["sf_vloc", str(tmp_path), str(tmp_path), "-v"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "========== VLOC 评估结果 ==========" in captured.out


def test_cli_reconstructs_unquoted_directory_paths_with_spaces(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data dir"
    log_dir = tmp_path / "log dir"
    data_dir.mkdir()
    log_dir.mkdir()
    received: list[tuple[Path, Path]] = []

    def fake_load_vloc(data_dir_arg: Path, log_dir_arg: Path) -> object:
        received.append((data_dir_arg, log_dir_arg))
        return object()

    monkeypatch.setattr("voeval.cli.load_vloc_evaluation_bundle", fake_load_vloc)
    monkeypatch.setattr(
        "voeval.cli.evaluate_vloc_bundle",
        lambda bundle, config: {
            "inputs": {"entry_mode": "vloc"},
            "rpe_frame_delta": {"translation_m": {"rmse": 1.0, "mean": 0.5, "max": 2.0}, "count": 3},
            "ate_position_m": {"rmse": 2.0, "mean": 1.0},
            "alignment": {"base_mode": "none"},
            "vloc_details": {"summary": {"trajectory_length_m": 100.0}},
        },
    )

    argv = ["sf_vloc", *str(data_dir).split(" "), *str(log_dir).split(" "), "-v"]
    exit_code = cli_main(argv)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert received == [(data_dir, log_dir)]
    assert "========== VLOC 评估结果 ==========" in captured.out


def test_cli_prints_missing_metrics_without_format_crash(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("voeval.cli.load_vloc_evaluation_bundle", lambda data_dir, log_dir: object())
    monkeypatch.setattr(
        "voeval.cli.evaluate_vloc_bundle",
        lambda bundle, config: {
            "inputs": {"entry_mode": "vloc"},
            "rpe_frame_delta": {"translation_m": {"rmse": math.nan, "mean": None, "max": "bad"}, "count": 0},
            "ate_position_m": {"rmse": math.nan, "mean": None},
            "alignment": {"base_mode": "none"},
            "vloc_details": {
                "summary": {
                    "trajectory_length_m": math.nan,
                    "mean_error_pos_xy": None,
                    "mean_error_pos_z": "bad",
                    "mean_error_euler": math.nan,
                    "max_error_pos_xy": None,
                    "max_error_pos_z": "bad",
                    "max_error_euler": math.nan,
                }
            },
        },
    )

    exit_code = cli_main(["--mode", "sf_vloc", "--data_dir", str(tmp_path), "--log_dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "RMSE: N/A m" in captured.out
    assert "mean_error_pos_xy: N/A m" in captured.out
    assert "max_error_euler: N/A deg" in captured.out


def test_cli_vloc_outputs_common_summary_and_vloc_specific_metrics(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("voeval.cli.load_vloc_evaluation_bundle", lambda data_dir, log_dir: object())
    monkeypatch.setattr(
        "voeval.cli.evaluate_vloc_bundle",
        lambda bundle, config: {
            "inputs": {"entry_mode": "vloc"},
            "rpe_frame_delta": {"translation_m": {"rmse": 0.75, "mean": 0.5, "max": 1.2}, "count": 9},
            "ate_position_m": {"rmse": 1.25, "mean": 0.9},
            "alignment": {"base_mode": "none"},
            "vloc_details": {
                "summary": {
                    "trajectory_length_m": 5645.292,
                    "mean_error_pos_xy": 4.720043,
                    "mean_error_pos_z": 1.639898,
                    "mean_error_euler": 0.707676,
                    "max_error_pos_xy": 11.641345,
                    "max_error_pos_z": 7.929585,
                    "max_error_euler": 3.963572,
                }
            },
        },
    )

    exit_code = cli_main(["--mode", "sf_vloc", "--data_dir", str(tmp_path), "--log_dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "========== VLOC 评估结果 ==========" in captured.out
    assert "RPE 平移误差" in captured.out
    assert "ATE 绝对轨迹误差" in captured.out
    assert "VLOC 专项指标" in captured.out
    assert "trajectory_length_m: 5645.2920 m" in captured.out
    assert "mean_error_pos_xy: 4.7200 m" in captured.out
    assert "mean_error_pos_z: 1.6399 m" in captured.out
    assert "mean_error_euler: 0.7077 deg" in captured.out
    assert "max_error_pos_xy: 11.6413 m" in captured.out
    assert "max_error_pos_z: 7.9296 m" in captured.out
    assert "max_error_euler: 3.9636 deg" in captured.out
    assert "Sim3 对齐" not in captured.out


def test_cli_debug_outputs_system_info_and_parser_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("voeval.cli.load_vo_evaluation_bundle", lambda data_dir, log_dir, vo_filename: object())
    monkeypatch.setattr(
        "voeval.cli.evaluate_vo_bundle",
        lambda bundle, config: {
            "inputs": {"entry_mode": "vo"},
            "rpe_frame_delta": {"translation_m": {"rmse": 1.0, "mean": 0.5, "max": 2.0}, "count": 3},
            "ate_position_m": {"rmse": 2.0, "mean": 1.0},
            "alignment": {"base_mode": "sim3", "scale": 3.0},
        },
    )

    exit_code = cli_main(["--mode", "sf_vo", "--data_dir", str(tmp_path), "--log_dir", str(tmp_path), "--debug"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "System info:" in captured.out
    assert "\nPython " in captured.out
    assert "Python:" not in captured.out
    assert "Platform:" not in captured.out
    assert "Executable:" not in captured.out
    assert "main_parser config:" in captured.out
    assert "'mode': 'sf_vo'" in captured.out
    assert "'delta': 100.0" in captured.out
    assert "'delta_unit': 'm'" in captured.out
    assert "'ref_file':" in captured.out and "imu.txt" in captured.out
    assert "'est_file':" in captured.out and "vo.txt" in captured.out
    assert "'data_dir':" in captured.out
    assert "'log_dir':" in captured.out
    assert "'align':" not in captured.out
    assert "'correct_scale':" not in captured.out
    assert "'delta_tol':" not in captured.out
    assert "'pose_relation':" not in captured.out
    assert "'subcommand':" not in captured.out
    assert "'t_max_diff':" not in captured.out
    assert "'t_offset':" not in captured.out
    assert "--------------------------------------------------------------------------------" in captured.out
    assert "RPE 平移误差" in captured.out


def test_cli_silent_suppresses_success_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("voeval.cli.load_vo_evaluation_bundle", lambda data_dir, log_dir, vo_filename: object())
    monkeypatch.setattr(
        "voeval.cli.evaluate_vo_bundle",
        lambda bundle, config: {
            "inputs": {"entry_mode": "vo"},
            "rpe_frame_delta": {"translation_m": {"rmse": 1.0, "mean": 0.5, "max": 2.0}, "count": 3},
            "ate_position_m": {"rmse": 2.0, "mean": 1.0},
            "alignment": {"base_mode": "sim3", "scale": 3.0},
        },
    )

    exit_code = cli_main(["--mode", "sf_vo", "--data_dir", str(tmp_path), "--log_dir", str(tmp_path), "--silent"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "评估结果" not in captured.out
    assert "RPE 平移误差" not in captured.out


def test_cli_logfile_writes_debug_log(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "voeval_debug.log"
    monkeypatch.setattr("voeval.cli.load_vo_evaluation_bundle", lambda data_dir, log_dir, vo_filename: object())
    monkeypatch.setattr(
        "voeval.cli.evaluate_vo_bundle",
        lambda bundle, config: {
            "inputs": {"entry_mode": "vo"},
            "rpe_frame_delta": {"translation_m": {"rmse": 1.0, "mean": 0.5, "max": 2.0}, "count": 3},
            "ate_position_m": {"rmse": 2.0, "mean": 1.0},
            "alignment": {"base_mode": "sim3", "scale": 3.0},
        },
    )

    exit_code = cli_main(
        [
            "--mode",
            "sf_vo",
            "--data_dir",
            str(tmp_path),
            "--log_dir",
            str(tmp_path),
            "--logfile",
            str(log_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "RPE 平移误差" in captured.out
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "main_parser config:" in log_text
    assert "--------------------------------------------------------------------------------" in log_text
    assert "RPE translation summary" in log_text


def test_cli_logfile_includes_backend_debug_steps(tmp_path):
    data_dir, log_dir = write_sf_dirs(tmp_path)
    log_path = tmp_path / "voeval_backend_debug.log"

    exit_code = cli_main(
        [
            "--mode",
            "sf_vloc",
            "--data_dir",
            str(data_dir),
            "--log_dir",
            str(log_dir),
            "--logfile",
            str(log_path),
        ]
    )

    assert exit_code == 0
    log_text = log_path.read_text(encoding="utf-8")
    assert "Loaded " in log_text
    assert " stamps and poses from:" in log_text
    assert "Synchronizing trajectories..." in log_text
    assert "Found " in log_text
    assert " possible matching timestamps between..." in log_text
    assert "VLOC mode filter" in log_text
    assert "Trajectory evaluation summary" in log_text


def test_debug_log_uses_evo_like_alignment_and_rpe_messages(tmp_path):
    log_path = tmp_path / "voeval_evo_like_debug.log"
    configure_logging(logfile=log_path)

    report = evaluate_vo_bundle(
        sample_vo_bundle_with_reset_segments(),
        EvaluationConfig(rpe_delta_value=100, rpe_delta_unit="frames"),
    )

    assert report["rpe_frame_delta"]["count"] > 0
    log_text = log_path.read_text(encoding="utf-8")
    assert "Aligning using Umeyama's method... (with scale correction)" in log_text
    assert "Rotation of alignment:" in log_text
    assert "Translation of alignment:" in log_text
    assert "Scale correction:" in log_text
    assert "Found " in log_text
    assert " pairs with delta 100 (frames) among " in log_text
    assert " using consecutive pairs." in log_text
    assert "Compared " in log_text
    assert " relative pose pairs, delta = 100 (frames) with consecutive pairs." in log_text
    assert "Calculating RPE for translation part pose relation..." in log_text


def test_cli_p_option_previews_temp_html_report(tmp_path, monkeypatch):
    data_dir, log_dir = write_sf_dirs(tmp_path)
    opened_urls: list[str] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("voeval.reports.preview.webbrowser.open", lambda url: opened_urls.append(url) or True)

    exit_code = cli_main(
        [
            "--mode",
            "sf_vloc",
            "--data_dir",
            str(data_dir),
            "--log_dir",
            str(log_dir),
            "-p",
        ]
    )

    assert exit_code == 0
    assert not (tmp_path / "data_dir__log_dir_vloc_evaluation_report.html").exists()
    assert len(opened_urls) == 1
    output_path = Path(opened_urls[0].removeprefix("file://"))
    assert output_path.exists()
    assert output_path.parent != tmp_path
    html = output_path.read_text(encoding="utf-8")
    assert "VLOC 运行结果" in html
    assert "图表目录" in html
    assert "Plotly.newPlot" in html


def test_cli_s_option_uses_default_html_filename(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "513"
    dataset_dir.mkdir()
    (dataset_dir / "imu.txt").write_text(sample_imu_text(), encoding="utf-8")
    (dataset_dir / "vloc.txt").write_text(sample_vloc_text(), encoding="utf-8")
    (dataset_dir / "home_point.txt").write_text("121.2 31.1 51.0\n", encoding="utf-8")
    (dataset_dir / "calib_raw.yaml").write_text(sample_calib_text(), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main(
        [
            "--mode",
            "sf_vloc",
            "--data_dir",
            str(dataset_dir),
            "--log_dir",
            str(dataset_dir),
            "-s",
        ]
    )

    assert exit_code == 0
    output_path = tmp_path / "513_vloc_evaluation_report.html"
    assert output_path.exists()
    assert "VLOC 运行结果" in output_path.read_text(encoding="utf-8")


def test_cli_s_option_writes_custom_html_output(tmp_path):
    data_dir, log_dir = write_sf_dirs(tmp_path)
    output_path = tmp_path / "cli_report.html"

    exit_code = cli_main(
        [
            "--mode",
            "sf_vloc",
            "--data_dir",
            str(data_dir),
            "--log_dir",
            str(log_dir),
            "-s",
            "--html-output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    html = output_path.read_text(encoding="utf-8")
    assert "VLOC 运行结果" in html
    assert "图表目录" in html


def test_cli_html_output_requires_save_flag(tmp_path):
    data_dir, log_dir = write_sf_dirs(tmp_path)

    with pytest.raises(SystemExit):
        cli_main(
            [
                "--mode",
                "sf_vloc",
                "--data_dir",
                str(data_dir),
                "--log_dir",
                str(log_dir),
                "-p",
                "--html-output",
                str(tmp_path / "report.html"),
            ]
        )


def test_vo_bundle_filters_reset_segments_and_uses_fixed_sim3_workflow():
    bundle = sample_vo_bundle_with_reset_segments()
    report = evaluate_vo_bundle(bundle, EvaluationConfig())

    assert report["inputs"]["entry_mode"] == "vo"
    assert report["inputs"]["workflow"] == "sf_vo"
    assert "fixed_rules" not in report["inputs"]
    assert "config" not in report
    assert "method" not in report["association"]
    assert "max_interpolation_gap_s" not in report["association"]
    assert "time_offset_s" not in report["association"]

    assert report["association"]["dropped_est_invalid_segment"] == 50
    assert report["association"]["valid_est_after_segment_filter"] == 402
    assert report["summary"]["raw_est_poses"] == int(len(bundle.vo.positions))
    assert report["summary"]["matched_poses"] == 402
    assert report["alignment"]["base_mode"] == "sim3"
    assert report["alignment"]["segment_count"] == 2
    assert report["ate_position_m"]["rmse"] < 1e-6

    all_breaks = report["discontinuities"]["all_matches"]["breaks"]
    assert any("evaluation_segment_id" in item["reasons"] for item in all_breaks)

    details = report["vo_details"]
    assert {"comparison", "nav_status", "vo_status", "segment_filter"}.issubset(details)
    assert len(details["comparison"]) == 402
    assert set(details["comparison"]["segment_id"].astype(int)) == {0, 1}
    assert {"num_inliers", "is_keyframe", "time_cost", "reset_count"}.issubset(details["vo_status"].columns)


def test_fixed_parser_rejects_wrong_column_count():
    bad_vloc = "10.0 2 42 0 11 12 13 90 2 -1 31.1 121.2\n"
    with pytest.raises(ValueError, match="13 columns"):
        parse_vloc_fixed(bad_vloc, name="vloc.txt")


def test_tum_zero_error_without_user_alignment_config():
    gt = load_trajectory_from_text(make_tum(), fmt="tum", name="gt")
    est = load_trajectory_from_text(make_tum(), fmt="tum", name="est")
    report = evaluate_trajectories(gt, est, EvaluationConfig())
    assert report["ate_position_m"]["rmse"] < 1e-6
    assert report["rpe_frame_delta"]["translation_m"]["rmse"] < 1e-9
    assert report["summary"]["gt_pose_coverage_ratio"] == 1.0
    assert "coverage_ratio" not in report["summary"]
    assert "gt_time_coverage_ratio" not in report["summary"]


def test_sim3_recovers_scale_for_monocular_like_output():
    gt = load_trajectory_from_text(make_tum(), fmt="tum", name="gt")
    est_positions = gt.positions * 0.5 + np.array([10.0, -3.0, 2.0])
    lines = []
    for t, p in zip(gt.stamps, est_positions):
        lines.append(f"{t:.3f} {p[0]:.6f} {p[1]:.6f} {p[2]:.6f} 0 0 0 1")
    est = load_trajectory_from_text("\n".join(lines), fmt="tum", name="est")
    alignment = sim3_alignment(gt.positions, est.positions)
    assert abs(alignment["scale"] - 2.0) < 1e-9


def test_load_trajectory_from_text_rejects_legacy_single_file_formats():
    text = "0 0 0 0 0 0 0 1\n1 1 0 0 0 0 0 1\n"
    for fmt in ["auto", "sf", "vloc", "csv", "kitti", "xyz"]:
        with pytest.raises(ValueError, match="Unsupported trajectory format"):
            load_trajectory_from_text(text, fmt=fmt, name=f"legacy_{fmt}")


def test_numeric_tum_timestamps_are_read_as_seconds():
    text = """1.000 0 0 0 0 0 0 1
1.050 1 0 0 0 0 0 1
"""
    traj = load_trajectory_from_text(text, fmt="tum", name="tum_seconds")
    assert abs(traj.duration_s - 0.05) < 1e-12


def test_numeric_tum_requires_exactly_eight_columns():
    text = "1.000 0 0 0 0 0 0 1 99\n1.050 1 0 0 0 0 0 1 99\n"
    with pytest.raises(ValueError, match="TUM format expects exactly 8 columns"):
        load_trajectory_from_text(text, fmt="tum", name="tum_extra_column")


def test_gt_is_interpolated_to_vo_timestamps_by_default():
    gt_text = """0.1 0.1 0 0 0 0 0 1
0.3 0.3 0 0 0 0 0 1
0.5 0.5 0 0 0 0 0 1
0.7 0.7 0 0 0 0 0 1
"""
    est_text = """0.2 0.2 0 0 0 0 0 1
0.4 0.4 0 0 0 0 0 1
0.6 0.6 0 0 0 0 0 1
"""
    gt = load_trajectory_from_text(gt_text, fmt="tum", name="gt")
    est = load_trajectory_from_text(est_text, fmt="tum", name="est")
    report = evaluate_trajectories(gt, est, EvaluationConfig())
    assert "method" not in report["association"]
    assert "target" not in report["association"]
    assert report["summary"]["matched_poses"] == 3
    assert report["ate_position_m"]["rmse"] < 1e-12


def test_rpe_frame_mode_uses_evo_consecutive_frame_pairs_in_per_frame_sheet():
    gt = load_trajectory_from_text(make_tum(rows=8), fmt="tum", name="gt")
    est = load_trajectory_from_text(make_tum(rows=8), fmt="tum", name="est")
    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(
            rpe_delta_value=3,
            rpe_delta_unit="frames",
        ),
    )

    rpe = report["rpe_frame_delta"]
    assert rpe["delta_unit"] == "frames"
    assert rpe["delta_value"] == 3
    assert rpe["delta_frames"] == 3
    assert rpe["count"] == 2

    sheet = report["trajectory_exports"]["rpe_per_frame"]
    assert sheet["rpe_delta_unit"].tolist() == ["frames"] * len(sheet)
    assert sheet["rpe_end_match_index"].tolist() == [3, -1, -1, 6, -1, -1, -1, -1]
    assert sheet["rpe_available"].tolist() == [True, False, False, True, False, False, False, False]


def test_rpe_distance_mode_uses_evo_consecutive_estimate_path_pairs():
    stamps = np.arange(6, dtype=float)
    gt_pos = np.array(
        [
            [0.0, 0.0, 0.0],
            [96.0, 0.0, 0.0],
            [100.0, 0.0, 0.0],
            [104.0, 0.0, 0.0],
            [196.0, 0.0, 0.0],
            [205.0, 0.0, 0.0],
        ]
    )
    est_pos = np.array(
        [
            [0.0, 0.0, 0.0],
            [106.0, 0.0, 0.0],
            [105.0, 0.0, 0.0],
            [105.0, 0.0, 0.0],
            [195.0, 0.0, 0.0],
            [205.0, 0.0, 0.0],
        ]
    )
    gt = Trajectory("gt", stamps, gt_pos)
    est = Trajectory("est", stamps, est_pos)

    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(
            rpe_delta_value=100.0,
            rpe_delta_unit="meters",
        ),
    )

    rpe = report["rpe_frame_delta"]
    assert rpe["delta_unit"] == "meters"
    assert rpe["delta_distance_m"] == 100.0
    assert rpe["distance_tolerance_percent"] == 5.0
    assert rpe["distance_tolerance_ratio"] == 0.05
    assert rpe["count"] == 1

    sheet = report["trajectory_exports"]["rpe_per_frame"]
    assert sheet["rpe_available"].tolist() == [False, True, False, False, False, False]
    active = sheet[sheet["rpe_available"]].iloc[0]
    assert active["rpe_end_match_index"] == 5
    assert active["rpe_actual_distance_m"] == 109.0
    assert active["rpe_candidate_count"] == 1
    assert active["rpe_translation_m"] == 10.0


def test_scale_frame_mode_outputs_local_scale_per_start_timestamp():
    stamps = np.arange(5, dtype=float)
    gt = Trajectory(
        "gt",
        stamps,
        np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [20.0, 0.0, 0.0], [30.0, 0.0, 0.0], [40.0, 0.0, 0.0]]),
    )
    est = Trajectory(
        "est",
        stamps,
        np.array([[0.0, 0.0, 0.0], [5.0, 0.0, 0.0], [10.0, 0.0, 0.0], [15.0, 0.0, 0.0], [20.0, 0.0, 0.0]]),
        source_format="sf_vo",
    )

    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(
            scale_delta_value=2,
            scale_delta_unit="frames",
        ),
    )

    scale_info = report["scale_frame_delta"]
    assert scale_info["delta_unit"] == "frames"
    assert scale_info["delta_frames"] == 2
    assert scale_info["count"] == 3
    assert scale_info["local_sim3_scale"]["mean"] == 2.0

    sheet = report["trajectory_exports"]["scale_per_frame"]
    assert sheet["scale_available"].tolist() == [True, True, True, False, False]
    assert sheet["scale_end_match_index"].tolist()[:3] == [2, 3, 4]
    assert sheet["local_scale_ratio_est_over_gt"].tolist()[:3] == [0.5, 0.5, 0.5]
    assert sheet["local_sim3_scale"].tolist()[:3] == [2.0, 2.0, 2.0]
    assert sheet["local_scale_drift_percent"].tolist()[:3] == [-50.0, -50.0, -50.0]


def test_scale_distance_mode_uses_gt_distance_window_closest_to_target():
    stamps = np.arange(5, dtype=float)
    gt = Trajectory(
        "gt",
        stamps,
        np.array([[0.0, 0.0, 0.0], [96.0, 0.0, 0.0], [100.0, 0.0, 0.0], [104.0, 0.0, 0.0], [205.0, 0.0, 0.0]]),
    )
    est = Trajectory(
        "est",
        stamps,
        np.array([[0.0, 0.0, 0.0], [48.0, 0.0, 0.0], [50.0, 0.0, 0.0], [52.0, 0.0, 0.0], [102.5, 0.0, 0.0]]),
        source_format="sf_vo",
    )

    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(
            scale_delta_value=100.0,
            scale_delta_unit="meters",
        ),
    )

    scale_info = report["scale_frame_delta"]
    assert scale_info["delta_unit"] == "meters"
    assert scale_info["delta_distance_m"] == 100.0
    assert scale_info["distance_tolerance_percent"] == 5.0
    assert scale_info["distance_tolerance_ratio"] == 0.05

    sheet = report["trajectory_exports"]["scale_per_frame"]
    first = sheet.iloc[0]
    assert bool(first["scale_available"]) is True
    assert first["scale_end_match_index"] == 2
    assert first["scale_candidate_count"] == 3
    assert first["scale_actual_distance_m"] == 100.0
    assert first["local_scale_ratio_est_over_gt"] == 0.5
    assert first["local_sim3_scale"] == 2.0


def test_interpolate_reference_to_estimate_linearly_interpolates_gt_position():
    gt = Trajectory("gt", np.array([0.0, 10.0]), np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]))
    est = Trajectory("est", np.array([5.0]), np.array([[5.0, 0.0, 0.0]]))
    gt_eval, est_eval, assoc = interpolate_reference_to_estimate(
        gt,
        est,
        max_interpolation_gap_s=20.0,
    )
    assert assoc["method"] == "interpolate_gt"
    assert assoc["position_method"] == "linear"
    assert assoc["matches"] == 1
    assert np.allclose(gt_eval.positions[0], [5.0, 0.0, 0.0])
    assert np.allclose(gt_eval.stamps, est_eval.stamps)
    assert np.allclose(est_eval.stamps, [5.0])
    assert gt_eval.extras["gt_left_index"][0] == 0
    assert gt_eval.extras["gt_right_index"][0] == 1
    assert abs(gt_eval.extras["interp_alpha"][0] - 0.5) < 1e-12


def test_interpolate_reference_to_estimate_slerps_gt_rotation():
    gt_rot = euler_yaw_pitch_roll_to_matrix(np.array([0.0, np.pi / 2]), np.zeros(2), np.zeros(2))
    gt = Trajectory("gt", np.array([0.0, 10.0]), np.zeros((2, 3)), gt_rot)
    est = Trajectory("est", np.array([5.0]), np.zeros((1, 3)))
    gt_eval, _, assoc = interpolate_reference_to_estimate(
        gt,
        est,
        max_interpolation_gap_s=20.0,
    )
    assert assoc["matches"] == 1
    assert assoc["rotation_method"] == "slerp"
    assert abs(yaw_from_rot(gt_eval.rotations)[0] - np.pi / 4) < 1e-9


def test_interpolate_gt_does_not_extrapolate_by_default():
    gt = Trajectory(
        "gt",
        np.array([10.0, 20.0]),
        np.array([[10.0, 0.0, 0.0], [20.0, 0.0, 0.0]]),
    )
    est = Trajectory(
        "est",
        np.array([9.0, 15.0, 21.0]),
        np.array([[9.0, 0.0, 0.0], [15.0, 0.0, 0.0], [21.0, 0.0, 0.0]]),
    )
    gt_eval, est_eval, assoc = interpolate_reference_to_estimate(
        gt,
        est,
        max_interpolation_gap_s=20.0,
    )
    assert assoc["allow_extrapolation"] is False
    assert assoc["matches"] == 1
    assert assoc["dropped_before_reference_range"] == 1
    assert assoc["dropped_after_reference_range"] == 1
    assert np.allclose(est_eval.stamps, [15.0])
    assert np.allclose(gt_eval.positions[0], [15.0, 0.0, 0.0])


def test_interpolate_gt_respects_max_interpolation_gap():
    gt = Trajectory("gt", np.array([0.0, 10.0]), np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]))
    est = Trajectory("est", np.array([5.0]), np.array([[5.0, 0.0, 0.0]]))
    gt_eval, est_eval, assoc = interpolate_reference_to_estimate(
        gt,
        est,
        max_interpolation_gap_s=1.0,
    )
    assert assoc["matches"] == 0
    assert assoc["large_interpolation_gap_count"] == 1
    assert assoc["dropped"] == 1
    assert len(gt_eval.positions) == 0
    assert len(est_eval.positions) == 0

    gt_eval, est_eval, assoc = interpolate_reference_to_estimate(
        gt,
        est,
        max_interpolation_gap_s=20.0,
    )
    assert assoc["matches"] == 1
    assert assoc["large_interpolation_gap_count"] == 0
    assert len(gt_eval.positions) == len(est_eval.positions) == 1


def test_interpolate_reference_to_estimate_no_longer_supports_nearest_mode():
    gt = Trajectory("gt", np.array([0.0, 10.0]), np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]))
    est = Trajectory("est", np.array([5.0]), np.array([[5.0, 0.0, 0.0]]))
    gt_eval, est_eval, assoc = interpolate_reference_to_estimate(gt, est, max_interpolation_gap_s=20.0)
    assert assoc["mode"] == "interpolate_gt"
    assert assoc["interpolated"] is True
    assert assoc["matches"] == 1
    assert np.allclose(gt_eval.positions[0], [5.0, 0.0, 0.0])
    assert np.allclose(est_eval.positions[0], [5.0, 0.0, 0.0])


def test_report_json_replaces_non_finite_values_with_null():
    text = report_to_json({"values": [1.0, math.inf, -math.inf, math.nan, np.float64(np.nan)]})
    parsed = json.loads(text)
    assert parsed == {"values": [1.0, None, None, None, None]}


def test_trajectory_exports_only_keep_visualization_data_tables():
    gt_text = "\n".join(
        f"{i * 0.1:.1f} {i:.3f} {np.sin(i):.6f} 1.000 0 0 0 1"
        for i in range(6)
    )
    gt = load_trajectory_from_text(gt_text, fmt="tum", name="gt")
    est_stamps = np.arange(6, dtype=float) * 0.1
    est_positions = np.column_stack([np.arange(6, dtype=float), np.sin(np.arange(6, dtype=float)), np.ones(6, dtype=float)])
    est = Trajectory(
        "vo",
        est_stamps,
        est_positions,
        rotations=None,
        extras={"reset_count": np.asarray([0, 0, 1, 1, 2, 2], dtype=int)},
        source_format="sf_vo",
    )
    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(),
    )

    exports = report["trajectory_exports"]
    assert set(exports) == {"rpe_per_frame", "scale_per_frame"}

    rpe_sheet = exports["rpe_per_frame"]
    assert {
        "timestamp",
        "segment_id",
        "rpe_delta_frames",
        "rpe_end_timestamp",
        "rpe_translation_m",
        "rpe_rotation_deg",
        "rpe_available",
    }.issubset(rpe_sheet.columns)
    assert len(rpe_sheet) == report["summary"]["matched_poses"]
    assert rpe_sheet["rpe_available"].tolist()[:-1] == [True] * (len(rpe_sheet) - 1)
    assert rpe_sheet["rpe_available"].tolist()[-1] is False
    assert "rpe_translation_m" in rpe_sheet.columns
    assert "local_sim3_scale" in exports["scale_per_frame"].columns


def test_orientation_correction_is_not_applied_in_fixed_evaluator():
    stamps = np.arange(40, dtype=float) * 0.1
    positions = np.column_stack([stamps, np.sin(stamps), 0.1 * stamps])
    gt_rot = euler_yaw_pitch_roll_to_matrix(0.2 * stamps, 0.1 * np.sin(stamps), 0.05 * np.cos(stamps))
    rz180 = np.diag([-1.0, -1.0, 1.0])
    est_rot = np.einsum("nij,jk->nik", gt_rot, rz180)
    gt = Trajectory("gt", stamps, positions, gt_rot)
    est = Trajectory("est", stamps, positions, est_rot)

    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(),
    )

    assert "orientation_correction" not in report
    assert report["ate_orientation_deg"]["rmse"] > 100.0


def test_per_pose_contains_position_and_ypr_series_for_visualization():
    stamps = np.arange(5, dtype=float) * 0.1
    positions = np.column_stack([stamps, 2.0 * stamps, 3.0 * stamps])
    gt_rot = euler_yaw_pitch_roll_to_matrix(
        0.2 * stamps,
        0.1 * stamps,
        -0.05 * stamps,
    )
    est_rot = euler_yaw_pitch_roll_to_matrix(
        0.2 * stamps + 0.01,
        0.1 * stamps - 0.02,
        -0.05 * stamps + 0.03,
    )
    est_positions = positions + np.array([1.0, -2.0, 3.0])
    gt = Trajectory("gt", stamps, positions, gt_rot)
    est = Trajectory("est", stamps, est_positions, est_rot)

    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(),
    )
    per_pose = report["per_pose"]

    expected_columns = {
        "x_error_m",
        "y_error_m",
        "z_error_m",
        "gt_yaw_deg",
        "gt_pitch_deg",
        "gt_roll_deg",
        "est_yaw_aligned_deg",
        "est_pitch_aligned_deg",
        "est_roll_aligned_deg",
        "pitch_error_signed_deg",
        "roll_error_signed_deg",
    }
    assert expected_columns.issubset(per_pose.columns)
    assert np.allclose(per_pose["x_error_m"].to_numpy(), 1.0)
    assert np.allclose(per_pose["y_error_m"].to_numpy(), -2.0)
    assert np.allclose(per_pose["z_error_m"].to_numpy(), 3.0)
    assert np.allclose(per_pose["yaw_error_signed_deg"].to_numpy(), np.degrees(0.01), atol=1e-9)
    assert np.allclose(per_pose["pitch_error_signed_deg"].to_numpy(), np.degrees(-0.02), atol=1e-9)
    assert np.allclose(per_pose["roll_error_signed_deg"].to_numpy(), np.degrees(0.03), atol=1e-9)
