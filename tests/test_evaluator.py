import json
import math
import io

import numpy as np
import pandas as pd

from vo_eval.evaluator import (
    EvaluationConfig,
    Trajectory,
    build_associated_trajectories,
    evaluate_trajectories,
    euler_yaw_pitch_roll_to_matrix,
    load_trajectory_from_text,
    report_to_excel,
    report_to_json,
    yaw_from_rot,
)


def make_tum(rows=120):
    lines = []
    for i in range(rows):
        t = i * 0.1
        x = i * 1.0
        y = 2.0 * np.sin(i / 20.0)
        z = 50.0 + 0.01 * i
        lines.append(f"{t:.3f} {x:.6f} {y:.6f} {z:.6f} 0 0 0 1")
    return "\n".join(lines)


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


def test_csv_xyz_parser():
    text = "timestamp,x,y,z,process_time_ms\n0,0,0,1,10\n1,1,0,1,11\n2,2,0,1,9\n"
    traj = load_trajectory_from_text(text, fmt="csv", name="csv")
    assert traj.positions.shape == (3, 3)
    assert "process_time_ms" in traj.extras


def test_commented_header_ypr_units_are_detected():
    rad_text = """# ts x y z yaw pitch roll unused
# yaw pitch roll rad
0 0 0 0 1.57079632679 0 0 99
"""
    deg_text = """# ts x y z yaw pitch roll unused
# yaw pitch roll degree
0 0 0 0 90 0 0 99
"""
    rad_traj = load_trajectory_from_text(rad_text, fmt="auto", name="rad")
    deg_traj = load_trajectory_from_text(deg_text, fmt="auto", name="deg")
    assert abs(yaw_from_rot(rad_traj.rotations)[0] - np.pi / 2) < 1e-9
    assert abs(yaw_from_rot(deg_traj.rotations)[0] - np.pi / 2) < 1e-9


def test_euroc_commented_header_uses_seconds_and_qw_order():
    text = """#timestamp [ns],p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z []
1403636580863555584.0000000000,1,2,3,1,0,0,0
1403636580913555456.0000000000,2,2,3,1,0,0,0
"""
    traj = load_trajectory_from_text(text, fmt="auto", name="euroc")
    assert traj.source_format == "csv"
    assert abs(traj.duration_s - 0.05) < 1e-6
    assert np.allclose(traj.positions[0], [1, 2, 3])
    assert abs(yaw_from_rot(traj.rotations)[0]) < 1e-9


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
    vo_text = """timestamp,x,y,z,aux,reset_id,tail_a,tail_b,tail_c
0.0,0.0,0.000000,1.0,9,0,0,0,0
0.1,1.0,0.841471,1.0,9,0,0,0,0
0.2,2.0,0.909297,1.0,9,1,0,0,0
0.3,3.0,0.141120,1.0,9,1,0,0,0
0.4,4.0,-0.756802,1.0,9,2,0,0,0
0.5,5.0,-0.958924,1.0,9,2,0,0,0
"""
    gt = load_trajectory_from_text(gt_text, fmt="tum", name="gt")
    est = load_trajectory_from_text(vo_text, fmt="csv", name="vo")
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
