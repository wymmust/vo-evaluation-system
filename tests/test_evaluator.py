import json
import math
import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vo_eval.evaluator import (
    Calibration,
    EvaluationConfig,
    HomePoint,
    SfVlocBundle,
    SUPPORTED_EVALUATION_FORMATS,
    Trajectory,
    build_associated_trajectories,
    evaluate_trajectories,
    evaluate_vloc_bundle,
    euler_yaw_pitch_roll_to_matrix,
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
    report_to_excel,
    report_to_json,
    yaw_from_rot,
)


def test_streamlit_dead_time_series_helpers_are_removed():
    source = Path("app.py").read_text()
    for name in ["make_gt_vo_time_series", "make_error_time_series", "render_figure_grid"]:
        assert f"def {name}" not in source


def test_streamlit_composite_angle_time_series_unwraps_180_degree_boundary():
    from app import make_composite_pair_time_series

    frame = pd.DataFrame(
        {
            "timestamp": [0, 1, 2],
            "segment_id": [0, 0, 0],
            "gt_roll_deg": [0, 1, 2],
            "est_roll_aligned_deg": [179, -179, 178],
        }
    )
    fig = make_composite_pair_time_series(
        frame,
        "Roll",
        [("Roll", "gt_roll_deg", "est_roll_aligned_deg", "deg", True)],
        left_name="Ground truth",
        right_name="VO aligned",
    )

    assert list(fig.data[1].y) == [179, 181, 178]


def test_streamlit_composite_angle_error_time_series_unwraps_180_degree_boundary():
    from app import make_composite_error_time_series

    frame = pd.DataFrame(
        {
            "timestamp": [0, 1, 2],
            "segment_id": [0, 0, 0],
            "roll_error_signed_deg": [179, -179, 178],
        }
    )
    fig = make_composite_error_time_series(
        frame,
        "Roll error",
        [("Roll error", "roll_error_signed_deg", "deg", True)],
    )

    assert list(fig.data[0].y) == [179, 181, 178]


def test_streamlit_composite_charts_share_hover_spikes_across_subplots():
    from app import make_composite_pair_time_series, make_composite_error_time_series, make_composite_single_time_series

    frame = pd.DataFrame(
        {
            "timestamp": [0, 1, 2],
            "nav_n_m": [0, 1, 2],
            "vloc_n_m": [0.1, 1.1, 2.1],
            "nav_e_m": [3, 4, 5],
            "vloc_e_m": [3.1, 4.1, 5.1],
            "position_error_n_m": [0.1, 0.2, 0.3],
            "position_error_e_m": [0.4, 0.5, 0.6],
            "vx": [1, 2, 3],
            "vy": [4, 5, 6],
        }
    )
    figures = [
        make_composite_pair_time_series(
            frame,
            "NED",
            [("N", "nav_n_m", "vloc_n_m", "m", False), ("E", "nav_e_m", "vloc_e_m", "m", False)],
            left_name="nav",
            right_name="vloc",
        ),
        make_composite_error_time_series(
            frame,
            "NED error",
            [("N error", "position_error_n_m", "m", False), ("E error", "position_error_e_m", "m", False)],
        ),
        make_composite_single_time_series(
            frame,
            "Velocity",
            [("vx", "vx", "m/s", False), ("vy", "vy", "m/s", False)],
        ),
    ]

    for fig in figures:
        assert fig.layout.hovermode == "x unified"
        assert fig.layout.hoversubplots == "axis"
        assert fig.layout.xaxis.showspikes is True
        assert fig.layout.xaxis2.showspikes is True
        assert fig.layout.xaxis.spikemode == "across"
        assert fig.layout.xaxis2.spikemode == "across"


def test_streamlit_sim3_scale_time_series_uses_exported_scale_by_timestamp():
    from app import make_sim3_scale_time_series

    frame = pd.DataFrame(
        {
            "timestamp": [10, 11, 20],
            "segment_id": [0, 0, 1],
            "local_sim3_scale": [2.0, 2.0, 3.0],
        }
    )
    fig = make_sim3_scale_time_series(frame)

    assert list(fig.data[0].x) == [10, 11, 20]
    assert list(fig.data[0].y) == [2.0, 2.0, 3.0]


def test_streamlit_trajectory_3d_marks_each_segment_start_and_end():
    from app import make_trajectory_3d

    frame = pd.DataFrame(
        {
            "segment_id": [0, 0, 1, 1],
            "visual_segment_id": [0, 0, 1, 1],
            "gt_x_m": [0.0, 1.0, 10.0, 11.0],
            "gt_y_m": [0.0, 2.0, 10.0, 12.0],
            "gt_z_m": [0.0, 3.0, 10.0, 13.0],
            "est_x_aligned_m": [0.1, 1.1, 10.1, 11.1],
            "est_y_aligned_m": [0.2, 2.2, 10.2, 12.2],
            "est_z_aligned_m": [0.3, 3.3, 10.3, 13.3],
        }
    )
    fig = make_trajectory_3d(frame)
    traces = {trace.name: trace for trace in fig.data}

    assert {"GT start", "GT end", "VO start", "VO end"}.issubset(traces)
    assert list(traces["GT start"].x) == [0.0, 10.0]
    assert list(traces["GT end"].x) == [1.0, 11.0]
    assert list(traces["GT start"].text) == ["GT S1", "GT S2"]
    assert list(traces["GT end"].text) == ["GT E1", "GT E2"]
    assert traces["GT start"].marker.size == 9
    assert traces["GT start"].marker.color == "#2563eb"
    assert traces["GT end"].marker.color == "#f97316"


def test_streamlit_vloc_trajectory_3d_marks_only_vloc_endpoints_with_small_markers():
    from app import make_vloc_trajectory_3d

    frame = pd.DataFrame(
        {
            "visual_segment_id": [0, 0, 1, 1],
            "nav_n_m": [0.0, 1.0, 10.0, 11.0],
            "nav_e_m": [0.0, 2.0, 10.0, 12.0],
            "nav_d_m": [0.0, 3.0, 10.0, 13.0],
            "vloc_n_m": [0.1, 1.1, 10.1, 11.1],
            "vloc_e_m": [0.2, 2.2, 10.2, 12.2],
            "vloc_d_m": [0.3, 3.3, 10.3, 13.3],
        }
    )
    fig = make_vloc_trajectory_3d(frame)
    traces = {trace.name: trace for trace in fig.data}

    assert "nav start" not in traces
    assert "nav end" not in traces
    assert {"vloc start", "vloc end"}.issubset(traces)
    assert list(traces["vloc start"].x) == [0.1, 10.1]
    assert list(traces["vloc end"].x) == [1.1, 11.1]
    assert list(traces["vloc start"].text) == ["vloc S1", "vloc S2"]
    assert list(traces["vloc end"].text) == ["vloc E1", "vloc E2"]
    assert traces["vloc start"].marker.size == 5
    assert traces["vloc start"].marker.line.width == 1
    assert traces["vloc start"].textfont.size == 10


def test_vloc_detail_visual_segments_follow_discontinuity_diagnostics():
    bundle = sample_vloc_bundle_with_large_nav_gap()
    report = evaluate_vloc_bundle(bundle, EvaluationConfig(discontinuity_step_m=10.0))
    comparison = report["vloc_details"]["comparison"]

    assert report["discontinuities"]["all_matches"]["break_count"] == 1
    assert comparison["visual_segment_id"].tolist() == [0, 0, 1]
    assert comparison["segment_id"].tolist() == [0, 0, 1]


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
        "log_dir/home_point.txt",
        "log_dir/calib_raw.yaml",
    )

    tum = get_evaluation_format_spec("tum")
    assert tum.mode == "tum"
    assert tum.required_files == ("ground_truth.tum", "estimate.tum")


def test_public_evaluation_format_rejects_legacy_parser_formats():
    for fmt in ["auto", "sf", "vloc", "csv", "kitti", "xyz"]:
        with pytest.raises(ValueError, match="Supported evaluation formats"):
            normalize_evaluation_format(fmt)


def test_public_evaluation_format_normalizes_common_separators():
    assert normalize_evaluation_format("SF-VLOC") == "sf_vloc"
    assert normalize_evaluation_format("sf vo") == "sf_vo"
    assert normalize_evaluation_format("Tum") == "tum"


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
    vloc_positions = np.column_stack([vloc_north, np.zeros(len(vloc_stamps)), np.full(len(vloc_stamps), home.altitude_msl, dtype=float)])
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

    home = parse_home_point_fixed("121.2 31.1 51.0\n", name="home_point.txt")
    assert home.longitude == 121.2
    assert home.latitude == 31.1
    assert home.altitude_msl == 51.0


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
    bundle = load_vo_evaluation_bundle(data_dir, log_dir)

    assert bundle.nav.source_format == "sf_imu"
    assert bundle.vo.source_format == "sf_vo"
    assert np.allclose(bundle.vo.positions[0], [21, 22, 23])
    assert bundle.files["estimate"].name == "vo.txt"


def test_bundle_loader_reports_missing_required_file(tmp_path):
    data_dir, log_dir = write_sf_dirs(tmp_path)
    (log_dir / "vloc.txt").unlink()

    with pytest.raises(FileNotFoundError, match="log_dir/vloc.txt"):
        load_vloc_evaluation_bundle(data_dir, log_dir)


def test_vloc_bundle_uses_fixed_interpolation_defaults_and_drops_invalid_frames():
    bundle = sample_vloc_bundle_with_large_nav_gap()
    cfg = EvaluationConfig(
        alignment="sim3",
        orientation_correction="auto",
        association_mode="nearest",
        max_interpolation_gap_s=10.0,
        allow_extrapolation=True,
        time_offset_s=3.0,
    )

    report = evaluate_vloc_bundle(bundle, cfg)

    assert report["inputs"]["entry_mode"] == "vloc"
    assert report["config"]["alignment"] == "none"
    assert report["config"]["orientation_correction"] == "none"
    assert report["config"]["association_mode"] == "interpolate_gt"
    assert report["config"]["max_interpolation_gap_s"] == 1.0
    assert report["config"]["allow_extrapolation"] is False
    assert report["config"]["time_offset_s"] == 0.0
    assert report["summary"]["matched_poses"] == 3
    assert report["association"]["dropped_est_large_gt_gap"] == 1
    assert report["association"]["dropped_est_invalid_mode"] == 1
    assert report["ate_position_m"]["rmse"] < 1e-3


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


def test_fixed_parser_rejects_wrong_column_count():
    bad_vloc = "10.0 2 42 0 11 12 13 90 2 -1 31.1 121.2\n"
    with pytest.raises(ValueError, match="13 columns"):
        parse_vloc_fixed(bad_vloc, name="vloc.txt")


def test_tum_zero_error_after_se3_alignment():
    gt = load_trajectory_from_text(make_tum(), fmt="tum", name="gt")
    est = load_trajectory_from_text(make_tum(), fmt="tum", name="est")
    report = evaluate_trajectories(gt, est, EvaluationConfig(segment_lengths_m=(10, 20, 50), max_interpolation_gap_s=0.3))
    assert report["ate_position_m"]["rmse"] < 1e-6
    assert report["rpe_frame_delta"]["translation_m"]["rmse"] < 1e-9
    assert report["summary"]["coverage_ratio"] == 1.0


def test_sim3_recovers_scale_for_monocular_like_output():
    gt = load_trajectory_from_text(make_tum(), fmt="tum", name="gt")
    est_positions = gt.positions * 0.5 + np.array([10.0, -3.0, 2.0])
    lines = []
    for t, p in zip(gt.stamps, est_positions):
        lines.append(f"{t:.3f} {p[0]:.6f} {p[1]:.6f} {p[2]:.6f} 0 0 0 1")
    est = load_trajectory_from_text("\n".join(lines), fmt="tum", name="est")
    cfg = EvaluationConfig(alignment="sim3", segment_lengths_m=(10, 20, 50), max_interpolation_gap_s=0.3)
    report = evaluate_trajectories(gt, est, cfg)
    assert abs(report["alignment"]["scale"] - 2.0) < 1e-9
    assert report["ate_position_m"]["rmse"] < 1e-6


def test_load_trajectory_from_text_rejects_legacy_single_file_formats():
    text = "0 0 0 0 0 0 0 1\n1 1 0 0 0 0 0 1\n"
    for fmt in ["auto", "sf", "vloc", "csv", "kitti", "xyz"]:
        with pytest.raises(ValueError, match="Unsupported trajectory format"):
            load_trajectory_from_text(text, fmt=fmt, name=f"legacy_{fmt}")


def test_numeric_tum_nanosecond_timestamps_are_normalized():
    text = """1000000000 0 0 0 0 0 0 1
1050000000 1 0 0 0 0 0 1
"""
    traj = load_trajectory_from_text(text, fmt="tum", name="tum_ns")
    assert abs(traj.duration_s - 0.05) < 1e-12


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
    cfg = EvaluationConfig(alignment="none", segment_lengths_m=(0.1,), max_interpolation_gap_s=0.3)
    report = evaluate_trajectories(gt, est, cfg)
    assert report["association"]["method"] == "interpolate_gt"
    assert report["association"]["target"] == "estimate_timestamps"
    assert report["summary"]["matched_poses"] == 3
    assert report["ate_position_m"]["rmse"] < 1e-12


def test_rpe_frame_mode_uses_configured_frame_delta_in_per_frame_sheet():
    gt = load_trajectory_from_text(make_tum(rows=8), fmt="tum", name="gt")
    est = load_trajectory_from_text(make_tum(rows=8), fmt="tum", name="est")
    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(
            alignment="none",
            rpe_delta_value=3,
            rpe_delta_unit="frames",
            segment_lengths_m=(1.0,),
            max_interpolation_gap_s=0.3,
        ),
    )

    rpe = report["rpe_frame_delta"]
    assert rpe["delta_unit"] == "frames"
    assert rpe["delta_value"] == 3
    assert rpe["delta_frames"] == 3
    assert rpe["count"] == 5

    sheet = report["trajectory_exports"]["rpe_per_frame"]
    assert sheet["rpe_delta_unit"].tolist() == ["frames"] * len(sheet)
    assert sheet["rpe_end_match_index"].tolist()[:2] == [3, 4]
    assert sheet["rpe_available"].tolist() == [True, True, True, True, True, False, False, False]


def test_rpe_distance_mode_uses_gt_distance_window_and_best_error_candidate():
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
            alignment="none",
            rpe_delta_value=100.0,
            rpe_delta_unit="meters",
            rpe_distance_tolerance_ratio=0.05,
            segment_lengths_m=(10.0,),
            discontinuity_step_m=1000.0,
        ),
    )

    rpe = report["rpe_frame_delta"]
    assert rpe["delta_unit"] == "meters"
    assert rpe["delta_distance_m"] == 100.0
    assert rpe["distance_tolerance_ratio"] == 0.05
    assert rpe["count"] == 4

    sheet = report["trajectory_exports"]["rpe_per_frame"]
    first = sheet.iloc[0]
    assert bool(first["rpe_available"]) is True
    assert first["rpe_end_match_index"] == 3
    assert first["rpe_actual_distance_m"] == 104.0
    assert first["rpe_candidate_count"] == 3
    assert first["rpe_translation_m"] == 1.0
    assert sheet["rpe_available"].tolist()[-2:] == [False, False]


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
    )

    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(
            alignment="none",
            scale_delta_value=2,
            scale_delta_unit="frames",
            segment_lengths_m=(1.0,),
            max_interpolation_gap_s=1.1,
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
    )

    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(
            alignment="none",
            scale_delta_value=100.0,
            scale_delta_unit="meters",
            scale_distance_tolerance_ratio=0.05,
            segment_lengths_m=(1.0,),
            discontinuity_step_m=1000.0,
        ),
    )

    scale_info = report["scale_frame_delta"]
    assert scale_info["delta_unit"] == "meters"
    assert scale_info["delta_distance_m"] == 100.0
    assert scale_info["distance_tolerance_ratio"] == 0.05

    sheet = report["trajectory_exports"]["scale_per_frame"]
    first = sheet.iloc[0]
    assert bool(first["scale_available"]) is True
    assert first["scale_end_match_index"] == 2
    assert first["scale_candidate_count"] == 3
    assert first["scale_actual_distance_m"] == 100.0
    assert first["local_scale_ratio_est_over_gt"] == 0.5
    assert first["local_sim3_scale"] == 2.0


def test_build_associated_trajectories_linearly_interpolates_gt_position():
    gt = Trajectory("gt", np.array([0.0, 10.0]), np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]))
    est = Trajectory("est", np.array([5.0]), np.array([[5.0, 0.0, 0.0]]))
    gt_eval, est_eval, assoc = build_associated_trajectories(
        gt,
        est,
        EvaluationConfig(association_mode="interpolate_gt", max_interpolation_gap_s=20.0),
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


def test_build_associated_trajectories_slerps_gt_rotation():
    gt_rot = euler_yaw_pitch_roll_to_matrix(np.array([0.0, np.pi / 2]), np.zeros(2), np.zeros(2))
    gt = Trajectory("gt", np.array([0.0, 10.0]), np.zeros((2, 3)), gt_rot)
    est = Trajectory("est", np.array([5.0]), np.zeros((1, 3)))
    gt_eval, _, assoc = build_associated_trajectories(
        gt,
        est,
        EvaluationConfig(association_mode="interpolate_gt", max_interpolation_gap_s=20.0),
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
    gt_eval, est_eval, assoc = build_associated_trajectories(
        gt,
        est,
        EvaluationConfig(association_mode="interpolate_gt", max_interpolation_gap_s=20.0),
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
    gt_eval, est_eval, assoc = build_associated_trajectories(
        gt,
        est,
        EvaluationConfig(association_mode="interpolate_gt", max_interpolation_gap_s=1.0),
    )
    assert assoc["matches"] == 0
    assert assoc["large_interpolation_gap_count"] == 1
    assert assoc["dropped"] == 1
    assert len(gt_eval.positions) == 0
    assert len(est_eval.positions) == 0

    gt_eval, est_eval, assoc = build_associated_trajectories(
        gt,
        est,
        EvaluationConfig(association_mode="interpolate_gt", max_interpolation_gap_s=20.0),
    )
    assert assoc["matches"] == 1
    assert assoc["large_interpolation_gap_count"] == 0
    assert len(gt_eval.positions) == len(est_eval.positions) == 1


def test_nearest_association_keeps_tum_greedy_behavior_without_interpolation():
    gt = Trajectory("gt", np.array([0.0, 10.0]), np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]))
    est = Trajectory("est", np.array([5.0]), np.array([[5.0, 0.0, 0.0]]))
    gt_eval, est_eval, assoc = build_associated_trajectories(
        gt,
        est,
        EvaluationConfig(association_mode="nearest", max_time_diff_s=0.02),
    )
    assert assoc["mode"] == "nearest"
    assert assoc["interpolated"] is False
    assert assoc["matches"] == 0
    assert len(gt_eval.positions) == 0
    assert len(est_eval.positions) == 0


def test_report_json_replaces_non_finite_values_with_null():
    text = report_to_json({"values": [1.0, math.inf, -math.inf, math.nan, np.float64(np.nan)]})
    parsed = json.loads(text)
    assert parsed == {"values": [1.0, None, None, None, None]}


def test_excel_export_contains_six_tum_sheets_and_vo_jump_groups():
    gt_text = "\n".join(
        f"{i * 0.1:.1f} {i:.3f} {np.sin(i):.6f} 1.000 0 0 0 1"
        for i in range(6)
    )
    gt = load_trajectory_from_text(gt_text, fmt="tum", name="gt")
    est_stamps = np.arange(6, dtype=float) * 0.1
    est_positions = np.column_stack([np.arange(6, dtype=float), np.sin(np.arange(6, dtype=float)), np.ones(6, dtype=float)])
    raw_numeric = np.asarray(
        [
            [0.0, 0.0, 0.000000, 1.0, 9, 0, 0, 0, 0],
            [0.1, 1.0, 0.841471, 1.0, 9, 0, 0, 0, 0],
            [0.2, 2.0, 0.909297, 1.0, 9, 1, 0, 0, 0],
            [0.3, 3.0, 0.141120, 1.0, 9, 1, 0, 0, 0],
            [0.4, 4.0, -0.756802, 1.0, 9, 2, 0, 0, 0],
            [0.5, 5.0, -0.958924, 1.0, 9, 2, 0, 0, 0],
        ],
        dtype=float,
    )
    est = Trajectory(
        "vo",
        est_stamps,
        est_positions,
        rotations=None,
        extras={"raw_numeric_table": raw_numeric},
        source_format="sf_vo",
    )
    report = evaluate_trajectories(
        gt,
        est,
        EvaluationConfig(segment_lengths_m=(1.0,), max_interpolation_gap_s=0.2),
    )

    sheets = report["trajectory_exports"]
    assert list(sheets) == [
        "input_gt_tum",
        "input_vo_tum",
        "filtered_vo_tum",
        "interpolated_gt_tum",
        "sim3_gt_tum",
        "sim3_vo_tum",
        "ate_per_frame",
        "rpe_per_frame",
        "scale_per_frame",
    ]
    for frame in [sheets[name] for name in list(sheets)[:6]]:
        assert list(frame.columns[:8]) == ["timestamp", "tx", "ty", "tz", "qx", "qy", "qz", "qw"]

    assert sheets["input_vo_tum"]["tum_file"].tolist() == [
        "vo_tum_01",
        "vo_tum_01",
        "vo_tum_02",
        "vo_tum_02",
        "vo_tum_03",
        "vo_tum_03",
    ]
    sim3_columns = [
        "sim3_scale",
        "sim3_rotation_r00",
        "sim3_rotation_r01",
        "sim3_rotation_r02",
        "sim3_rotation_r10",
        "sim3_rotation_r11",
        "sim3_rotation_r12",
        "sim3_rotation_r20",
        "sim3_rotation_r21",
        "sim3_rotation_r22",
        "sim3_translation_x",
        "sim3_translation_y",
        "sim3_translation_z",
    ]
    for sheet_name in ["sim3_gt_tum", "sim3_vo_tum"]:
        for column in sim3_columns:
            assert column in sheets[sheet_name].columns
        assert np.isfinite(sheets[sheet_name][sim3_columns].to_numpy(dtype=float)).all()
    ate_sheet = sheets["ate_per_frame"]
    assert {"timestamp", "segment_id", "ate_position_m", "ate_horizontal_m", "ate_vertical_abs_m"}.issubset(ate_sheet.columns)
    assert len(ate_sheet) == report["summary"]["matched_poses"]
    assert np.allclose(ate_sheet["ate_position_m"].to_numpy(), report["per_pose"]["error_m"].to_numpy())

    rpe_sheet = sheets["rpe_per_frame"]
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

    workbook = report_to_excel(report)
    xlsx = pd.ExcelFile(io.BytesIO(workbook))
    assert xlsx.sheet_names == list(sheets)
    sim3_vo_from_workbook = pd.read_excel(xlsx, sheet_name="sim3_vo_tum")
    for column in sim3_columns:
        assert column in sim3_vo_from_workbook.columns
    ate_from_workbook = pd.read_excel(xlsx, sheet_name="ate_per_frame")
    rpe_from_workbook = pd.read_excel(xlsx, sheet_name="rpe_per_frame")
    assert "ate_position_m" in ate_from_workbook.columns
    assert "rpe_translation_m" in rpe_from_workbook.columns


def test_auto_orientation_correction_selects_right_rz180():
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
        EvaluationConfig(alignment="none", orientation_correction="auto", segment_lengths_m=(1.0,)),
    )

    assert report["orientation_correction"]["selected"] == "rz180_right"
    assert report["ate_orientation_deg"]["rmse"] < 1e-9
    assert report["rpe_frame_delta"]["rotation_deg"]["rmse"] < 1e-6


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
        EvaluationConfig(alignment="none", segment_lengths_m=(0.1,), max_interpolation_gap_s=0.2),
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
