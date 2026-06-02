import numpy as np

from vo_eval.evaluator import EvaluationConfig, evaluate_trajectories, load_trajectory_from_text, yaw_from_rot


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
    report = evaluate_trajectories(gt, est, EvaluationConfig(segment_lengths_m=(10, 20, 50)))
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
    cfg = EvaluationConfig(alignment="sim3", segment_lengths_m=(10, 20, 50))
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
