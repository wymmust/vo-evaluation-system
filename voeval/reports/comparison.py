"""Detailed comparison/status tables for reports."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.geometry import euler_yaw_pitch_roll_from_matrix, wrap_pi
from ..core.interpolation import extra_values_linear, extra_values_nearest, trajectory_extra_or_nan
from ..core.statistics import path_distance
from ..io.trajectory import Trajectory

def vloc_nav_status_frame(nav: Trajectory, target_stamps: np.ndarray, timestamps: np.ndarray) -> pd.DataFrame:
    """把 nav 状态按需求文档插到有效 VLOC 时间戳。

    离散状态字段按最近邻；速度、高度等连续字段按线性插值。
    """
    frame = pd.DataFrame({"timestamp": timestamps})
    nearest_fields = {
        "flight_mode": "flight_mode",
        "navi_mode": "navi_mode",
        "rtk_yaw": "rtk_yaw",
        "rtk_alti": "rtk_altitude",
        "position_reset_count": "position_reset_count",
        "altitude_reset_count": "altitude_reset_count",
        "heading_reset_count": "heading_reset_count",
    }
    for output_name, extra_name in nearest_fields.items():
        frame[output_name] = extra_values_nearest(nav, extra_name, target_stamps)

    for extra_field in ("vx", "vy", "vz", "height"):
        frame[extra_field] = extra_values_linear(nav, extra_field, target_stamps)
    frame["velocity_norm"] = np.linalg.norm(frame[["vx", "vy", "vz"]].to_numpy(dtype=float), axis=1)
    return frame
def vloc_est_status_frame(vloc: Trajectory) -> pd.DataFrame:
    """提取有效 VLOC 样本自身的状态字段。"""
    frame = pd.DataFrame({"timestamp": vloc.stamps})
    for extra_field in ("vloc_mode", "num_inliers", "reset_count", "height"):
        frame[extra_field] = trajectory_extra_or_nan(vloc, extra_field)
    return frame
def vo_est_status_frame(vo: Trajectory) -> pd.DataFrame:
    """提取有效 VO 样本自身的状态字段。"""
    frame = pd.DataFrame({"timestamp": vo.stamps})
    for extra_field in ("num_inliers", "is_keyframe", "time_cost", "reset_count", "evaluation_segment_id"):
        frame[extra_field] = trajectory_extra_or_nan(vo, extra_field)
    return frame
def vo_comparison_frame(
    per_pose: pd.DataFrame,
    vo_status: pd.DataFrame,
    visual_segment_ids: np.ndarray | None = None,
) -> pd.DataFrame:
    """VO 逐帧对比表，位置误差按 nav - aligned VO 输出。"""
    if per_pose.empty:
        return pd.DataFrame()
    frame = pd.DataFrame(
        {
            "timestamp": per_pose["timestamp"].to_numpy(dtype=float),
            "segment_id": per_pose["segment_id"].to_numpy(dtype=int),
            "visual_segment_id": (
                np.asarray(visual_segment_ids, dtype=int)
                if visual_segment_ids is not None and len(visual_segment_ids) == len(per_pose)
                else per_pose.get("visual_segment_id", per_pose["segment_id"]).to_numpy(dtype=int)
            ),
            "distance_m": per_pose["distance_m"].to_numpy(dtype=float),
            "nav_x_m": per_pose["gt_x_m"].to_numpy(dtype=float),
            "nav_y_m": per_pose["gt_y_m"].to_numpy(dtype=float),
            "nav_z_m": per_pose["gt_z_m"].to_numpy(dtype=float),
            "vo_x_aligned_m": per_pose["est_x_aligned_m"].to_numpy(dtype=float),
            "vo_y_aligned_m": per_pose["est_y_aligned_m"].to_numpy(dtype=float),
            "vo_z_aligned_m": per_pose["est_z_aligned_m"].to_numpy(dtype=float),
            "position_error_x_m": -per_pose["x_error_m"].to_numpy(dtype=float),
            "position_error_y_m": -per_pose["y_error_m"].to_numpy(dtype=float),
            "position_error_z_m": -per_pose["z_error_m"].to_numpy(dtype=float),
            "position_error_3d_m": per_pose["error_m"].to_numpy(dtype=float),
            "horizontal_position_error_m": per_pose["horizontal_error_m"].to_numpy(dtype=float),
            "vertical_position_error_signed_m": -per_pose["z_error_m"].to_numpy(dtype=float),
            "vertical_position_error_abs_m": per_pose["vertical_error_abs_m"].to_numpy(dtype=float),
        }
    )
    if {"gt_yaw_deg", "est_yaw_aligned_deg", "yaw_error_signed_deg"}.issubset(per_pose.columns):
        frame["nav_yaw_deg"] = per_pose["gt_yaw_deg"].to_numpy(dtype=float)
        frame["nav_pitch_deg"] = per_pose["gt_pitch_deg"].to_numpy(dtype=float)
        frame["nav_roll_deg"] = per_pose["gt_roll_deg"].to_numpy(dtype=float)
        frame["vo_yaw_aligned_deg"] = per_pose["est_yaw_aligned_deg"].to_numpy(dtype=float)
        frame["vo_pitch_aligned_deg"] = per_pose["est_pitch_aligned_deg"].to_numpy(dtype=float)
        frame["vo_roll_aligned_deg"] = per_pose["est_roll_aligned_deg"].to_numpy(dtype=float)
        frame["attitude_error_yaw_deg"] = -per_pose["yaw_error_signed_deg"].to_numpy(dtype=float)
        frame["attitude_error_pitch_deg"] = -per_pose["pitch_error_signed_deg"].to_numpy(dtype=float)
        frame["attitude_error_roll_deg"] = -per_pose["roll_error_signed_deg"].to_numpy(dtype=float)
        frame["attitude_error_euler_norm_deg"] = np.linalg.norm(
            frame[["attitude_error_yaw_deg", "attitude_error_pitch_deg", "attitude_error_roll_deg"]].to_numpy(dtype=float),
            axis=1,
        )
    if len(vo_status) == len(frame):
        for extra_field in ("num_inliers", "is_keyframe", "time_cost", "reset_count", "evaluation_segment_id"):
            if extra_field in vo_status:
                frame[extra_field] = vo_status[extra_field].to_numpy(dtype=float)
    return frame
def vloc_comparison_frame(
    nav_eval: Trajectory,
    vloc_eval: Trajectory,
    nav_status: pd.DataFrame,
    vloc_status: pd.DataFrame,
    visual_segment_ids: np.ndarray | None = None,
) -> pd.DataFrame:
    """VLOC 逐帧对比表，位置误差按需求文档使用 nav - vloc。"""
    nav_pos = np.asarray(nav_eval.positions, dtype=float)
    vloc_pos = np.asarray(vloc_eval.positions, dtype=float)
    pos_error = nav_pos - vloc_pos
    segment_ids = np.zeros(len(vloc_eval.stamps), dtype=int)
    if visual_segment_ids is not None and len(visual_segment_ids) == len(vloc_eval.stamps):
        segment_ids = np.asarray(visual_segment_ids, dtype=int)
    frame = pd.DataFrame(
        {
            "timestamp": vloc_eval.stamps,
            "segment_id": segment_ids,
            "visual_segment_id": segment_ids,
            "distance_m": path_distance(nav_pos),
            "nav_n_m": nav_pos[:, 0],
            "nav_e_m": nav_pos[:, 1],
            "nav_d_m": nav_pos[:, 2],
            "vloc_n_m": vloc_pos[:, 0],
            "vloc_e_m": vloc_pos[:, 1],
            "vloc_d_m": vloc_pos[:, 2],
            "position_error_n_m": pos_error[:, 0],
            "position_error_e_m": pos_error[:, 1],
            "position_error_d_m": pos_error[:, 2],
            "position_error_3d_m": np.linalg.norm(pos_error, axis=1),
            "horizontal_position_error_m": np.linalg.norm(pos_error[:, :2], axis=1),
            "vertical_position_error_signed_m": pos_error[:, 2],
            "vertical_position_error_abs_m": np.abs(pos_error[:, 2]),
        }
    )
    frame["nav_height_m"] = nav_status["height"].to_numpy(dtype=float) if "height" in nav_status else np.nan
    frame["vloc_height_m"] = vloc_status["height"].to_numpy(dtype=float) if "height" in vloc_status else np.nan
    if nav_eval.rotations is not None and vloc_eval.rotations is not None:
        nav_ypr = np.degrees(euler_yaw_pitch_roll_from_matrix(nav_eval.rotations))
        vloc_ypr = np.degrees(euler_yaw_pitch_roll_from_matrix(vloc_eval.rotations))
        err_rot = np.einsum("nji,njk->nik", nav_eval.rotations, vloc_eval.rotations)
        err_ypr = np.degrees(wrap_pi(euler_yaw_pitch_roll_from_matrix(err_rot)))
        frame["nav_yaw_deg"] = nav_ypr[:, 0]
        frame["nav_pitch_deg"] = nav_ypr[:, 1]
        frame["nav_roll_deg"] = nav_ypr[:, 2]
        frame["vloc_yaw_deg"] = vloc_ypr[:, 0]
        frame["vloc_pitch_deg"] = vloc_ypr[:, 1]
        frame["vloc_roll_deg"] = vloc_ypr[:, 2]
        frame["attitude_error_yaw_deg"] = err_ypr[:, 0]
        frame["attitude_error_pitch_deg"] = err_ypr[:, 1]
        frame["attitude_error_roll_deg"] = err_ypr[:, 2]
        frame["attitude_error_euler_norm_deg"] = np.linalg.norm(err_ypr, axis=1)
    return frame
