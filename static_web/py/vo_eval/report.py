"""Report table, JSON, and Excel export helpers."""

from __future__ import annotations

import io
import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from .data_loader import (
    FIXED_TIME_OFFSET_S,
    Trajectory,
)
from .utils import (
    euler_yaw_pitch_roll_from_matrix,
    extra_values_linear,
    extra_values_nearest,
    matrix_to_quaternion,
    path_distance,
    trajectory_extra_or_nan,
    wrap_pi,
)

def build_vloc_detail_report(
    nav: Trajectory,
    vloc: Trajectory,
    nav_eval: Trajectory,
    vloc_eval: Trajectory,
    visual_segment_ids: np.ndarray | None = None,
) -> dict[str, Any]:
    """构造 VLOC 页面专用明细。

    这部分严格对应需求文档中的 VLOC 轨迹对比和可视化：
    - comparison: nav_data.ned - vloc_data.ned 的逐帧位置误差，以及 R_ref^-1 R_est 姿态误差；
    - nav_status: 插值到 VLOC 时间戳后的导航状态、速度和 reset 信息；
    - vloc_status: 与有效 VLOC 样本对应的 vloc_mode、num_inliers、reset_count；
    - summary: VLOC 轨迹长度、水平/垂直平均和最大误差。
    """
    timestamps = vloc_eval.stamps
    target_stamps = np.asarray(vloc_eval.extras.get("target_stamp", timestamps + FIXED_TIME_OFFSET_S), dtype=float)
    if len(timestamps) == 0:
        empty = pd.DataFrame()
        return {"summary": {}, "comparison": empty, "nav_status": empty, "vloc_status": empty}

    nav_status = vloc_nav_status_frame(nav, target_stamps, timestamps)
    vloc_status = vloc_est_status_frame(vloc_eval)
    comparison = vloc_comparison_frame(nav_eval, vloc_eval, nav_status, vloc_status, visual_segment_ids=visual_segment_ids)

    horizontal = comparison["horizontal_position_error_m"].to_numpy(dtype=float)
    vertical_abs = comparison["vertical_position_error_abs_m"].to_numpy(dtype=float)
    euler_norm = comparison["attitude_error_euler_norm_deg"].to_numpy(dtype=float) if "attitude_error_euler_norm_deg" in comparison else np.asarray([], dtype=float)
    summary = {
        "trajectory_length_m": float(path_distance(nav_eval.positions)[-1]) if len(nav_eval.positions) else 0.0,
        "horizontal_error_mean_m": float(np.nanmean(horizontal)) if len(horizontal) else math.nan,
        "horizontal_error_max_m": float(np.nanmax(horizontal)) if len(horizontal) else math.nan,
        "vertical_error_mean_m": float(np.nanmean(vertical_abs)) if len(vertical_abs) else math.nan,
        "vertical_error_max_m": float(np.nanmax(vertical_abs)) if len(vertical_abs) else math.nan,
        "mean_error_pos_xy": float(np.nanmean(horizontal)) if len(horizontal) else math.nan,
        "max_error_pos_xy": float(np.nanmax(horizontal)) if len(horizontal) else math.nan,
        "mean_error_pos_z": float(np.nanmean(vertical_abs)) if len(vertical_abs) else math.nan,
        "max_error_pos_z": float(np.nanmax(vertical_abs)) if len(vertical_abs) else math.nan,
        "mean_error_euler": float(np.nanmean(euler_norm)) if len(euler_norm) else math.nan,
        "max_error_euler": float(np.nanmax(euler_norm)) if len(euler_norm) else math.nan,
    }
    return {
        "summary": summary,
        "comparison": comparison,
        "nav_status": nav_status,
        "vloc_status": vloc_status,
    }


def build_vo_detail_report(
    nav: Trajectory,
    vo: Trajectory,
    report: dict[str, Any],
    nav_eval: Trajectory,
    vo_eval: Trajectory,
    visual_segment_ids: np.ndarray | None = None,
) -> dict[str, Any]:
    """构造 VO 页面专用明细。

    comparison 使用通用 evaluator 已经算好的 Sim3 后 per_pose 数据：
    这样页面看到的 VO 轨迹、ATE/RPE 和导出结果使用同一套对齐结果。
    """
    timestamps = vo_eval.stamps
    target_stamps = np.asarray(vo_eval.extras.get("target_stamp", timestamps + FIXED_TIME_OFFSET_S), dtype=float)
    if len(timestamps) == 0:
        empty = pd.DataFrame()
        return {"summary": {}, "comparison": empty, "nav_status": empty, "vo_status": empty, "segment_filter": {}}

    nav_status = vloc_nav_status_frame(nav, target_stamps, timestamps)
    vo_status = vo_est_status_frame(vo_eval)
    comparison = vo_comparison_frame(report.get("per_pose", pd.DataFrame()), vo_status, visual_segment_ids=visual_segment_ids)
    summary = {
        "trajectory_length_m": float(report.get("summary", {}).get("gt_path_length_m", math.nan)),
        "mean_error_pos_xy": float(report.get("ate_horizontal_m", {}).get("mean", math.nan)),
        "mean_error_pos_z": float(report.get("ate_vertical_m", {}).get("mean", math.nan)),
        "max_error_pos_xy": float(report.get("ate_horizontal_m", {}).get("max", math.nan)),
        "max_error_pos_z": float(report.get("ate_vertical_m", {}).get("max", math.nan)),
        "mean_error_euler": float(report.get("ate_orientation_deg", {}).get("mean", math.nan)) if report.get("ate_orientation_deg") else math.nan,
        "max_error_euler": float(report.get("ate_orientation_deg", {}).get("max", math.nan)) if report.get("ate_orientation_deg") else math.nan,
    }
    segment_filter = report.get("association", {}).get("vo_reset_segment_filter", {})
    return {
        "summary": summary,
        "comparison": comparison,
        "nav_status": nav_status,
        "vo_status": vo_status,
        "segment_filter": segment_filter,
    }


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

def tum_dataframe_from_arrays(
    stamps: np.ndarray,
    positions: np.ndarray,
    rotations: np.ndarray | None,
    extra: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """把轨迹数组转成 TUM 表格，前 8 列固定为 timestamp tx ty tz qx qy qz qw。

    这个函数只负责导出格式，不参与 ATE/RPE 计算：
    - 有姿态时把旋转矩阵转成 TUM 四元数 qx qy qz qw。
    - 没有姿态时写单位四元数，并额外标记 has_rotation=False，保证 sheet 仍是 TUM 结构。
    - extra 列统一追加在 TUM 8 列之后，用于保存 segment_id、source_index、jump 文件名等诊断信息。
    """
    stamps = np.asarray(stamps, dtype=float)
    positions = np.asarray(positions, dtype=float)
    count = len(positions)
    if count == 0:
        quats = np.empty((0, 4), dtype=float)
        has_rotation = np.asarray([], dtype=bool)
    elif rotations is not None:
        quats = matrix_to_quaternion(np.asarray(rotations, dtype=float))
        has_rotation = np.ones(count, dtype=bool)
    else:
        quats = np.zeros((count, 4), dtype=float)
        quats[:, 3] = 1.0
        has_rotation = np.zeros(count, dtype=bool)

    frame = pd.DataFrame(
        {
            "timestamp": stamps,
            "tx": positions[:, 0] if count else np.asarray([], dtype=float),
            "ty": positions[:, 1] if count else np.asarray([], dtype=float),
            "tz": positions[:, 2] if count else np.asarray([], dtype=float),
            "qx": quats[:, 0] if count else np.asarray([], dtype=float),
            "qy": quats[:, 1] if count else np.asarray([], dtype=float),
            "qz": quats[:, 2] if count else np.asarray([], dtype=float),
            "qw": quats[:, 3] if count else np.asarray([], dtype=float),
            "has_rotation": has_rotation,
        }
    )
    if extra:
        for key, value in extra.items():
            arr = np.asarray(value)
            if arr.ndim == 0:
                frame[key] = arr.item()
            elif len(arr) == count:
                frame[key] = arr
    return frame


def trajectory_to_tum_dataframe(traj: Trajectory, extra: dict[str, Any] | None = None) -> pd.DataFrame:
    """把 Trajectory 转成 TUM 表格。

    原始输入、插值后 GT、筛选后 estimate 和 Sim3 输出都通过这个函数统一导出，
    避免不同 sheet 的列顺序或四元数顺序不一致。
    """
    return tum_dataframe_from_arrays(traj.stamps, traj.positions, traj.rotations, extra=extra)


def jump_export_columns_from_source(
    source: Trajectory,
    source_indices: np.ndarray | None,
    prefix: str,
) -> dict[str, Any]:
    """根据固定格式 reset_count 的 +1 变化生成导出分段列。

    历史需求：如果 estimate 输出文件 reset_count 出现 0->1、1->2 这类 +1 跳变，
    就把跳变后的数据视为新的 TUM 文件，例如 vo_tum_01、vo_tum_02。
    当前 sf_vo/sf_vloc 解析阶段都会把 reset_count 放入 extras，导出不再依赖“倒数第四列”。

    Excel 当前是 9 个固定 sheet，因此这里不额外创建无限多个 sheet，而是在相关 sheet 中写入：
    - tum_file: 逻辑文件名，如 vo_tum_01；这里的 vo_tum 是历史命名，实际代表 estimate_tum。
    - jump_segment_id: 从 0 开始的分段编号。
    - jump_source_value: reset_count 的值，方便复查跳变点。
    """
    n = len(source.positions)
    if source_indices is None:
        indices = np.arange(n, dtype=int)
    else:
        indices = np.asarray(source_indices, dtype=int)

    all_segment_ids = np.zeros(n, dtype=int)
    all_values = np.full(n, math.nan, dtype=float)
    reset_count = source.extras.get("reset_count")
    if reset_count is not None and len(reset_count) == n:
        all_values = np.asarray(reset_count, dtype=float)
        diffs = np.diff(all_values)
        jumps = np.isfinite(diffs) & np.isclose(diffs, 1.0, rtol=0.0, atol=1e-9)
        all_segment_ids = np.concatenate([[0], np.cumsum(jumps)]).astype(int)

    safe_indices = np.clip(indices, 0, max(0, n - 1)) if n else indices
    segment_ids = all_segment_ids[safe_indices] if n else np.asarray([], dtype=int)
    values = all_values[safe_indices] if n else np.asarray([], dtype=float)
    return {
        "source_index": indices,
        "jump_segment_id": segment_ids,
        "jump_source_field": np.asarray(["reset_count"] * len(indices), dtype=object),
        "jump_source_value": values,
        "tum_file": np.asarray([f"{prefix}_{seg_id + 1:02d}" for seg_id in segment_ids], dtype=object),
    }


def interpolated_gt_extra_columns(gt_eval: Trajectory) -> dict[str, Any]:
    """整理 GT 插值 sheet 的诊断列，保留左右 GT 样本和 alpha。"""
    n = len(gt_eval.positions)
    extra: dict[str, Any] = {"row_index": np.arange(n, dtype=int)}
    for key in ["original_est_stamp", "target_stamp", "gt_left_index", "gt_right_index", "interp_alpha", "gt_bracket_gap_s"]:
        value = gt_eval.extras.get(key)
        if value is not None and len(value) == n:
            extra[key] = value
    return extra


def ate_frame_dataframe(per_pose: pd.DataFrame) -> pd.DataFrame:
    """生成每个时间戳一行的 ATE 明细 sheet。

    ATE 不是只在最后算一个总 RMSE。evaluate_trajectories() 已经在 per_pose 里保存了
    每一帧的对齐后位置误差，这里只把这些逐帧误差换成更适合导出阅读的列名：
    - ate_position_m: 三维位置绝对轨迹误差，等于 per_pose.error_m。
    - ate_horizontal_m: XY 平面绝对误差，等于 per_pose.horizontal_error_m。
    - ate_vertical_signed_m: Z 方向带符号误差，正负能看出高度偏高还是偏低。
    - ate_vertical_abs_m: Z 方向绝对误差，适合做 RMSE/阈值判断。

    如果输入包含姿态，还会追加姿态/yaw 的逐帧绝对误差。
    """
    if per_pose.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "segment_id",
                "distance_m",
                "segment_distance_m",
                "ate_position_m",
                "ate_horizontal_m",
                "ate_vertical_signed_m",
                "ate_vertical_abs_m",
            ]
        )

    data: dict[str, Any] = {
        "timestamp": per_pose["timestamp"].to_numpy(),
        "segment_id": per_pose["segment_id"].to_numpy(),
        "distance_m": per_pose["distance_m"].to_numpy() if "distance_m" in per_pose else np.full(len(per_pose), math.nan),
        "segment_distance_m": per_pose["segment_distance_m"].to_numpy() if "segment_distance_m" in per_pose else np.full(len(per_pose), math.nan),
        "ate_position_m": per_pose["error_m"].to_numpy(),
        "ate_horizontal_m": per_pose["horizontal_error_m"].to_numpy(),
        "ate_vertical_signed_m": per_pose["vertical_error_signed_m"].to_numpy(),
        "ate_vertical_abs_m": per_pose["vertical_error_abs_m"].to_numpy(),
    }
    if "orientation_error_deg" in per_pose:
        data["ate_orientation_deg"] = per_pose["orientation_error_deg"].to_numpy()
    if "yaw_error_signed_deg" in per_pose:
        data["ate_yaw_signed_deg"] = per_pose["yaw_error_signed_deg"].to_numpy()
    if "yaw_error_abs_deg" in per_pose:
        data["ate_yaw_abs_deg"] = per_pose["yaw_error_abs_deg"].to_numpy()
    return pd.DataFrame(data)

def build_trajectory_export_sheets(
    original_gt: Trajectory,
    original_est: Trajectory,
    gt_eval: Trajectory,
    est_eval: Trajectory,
    sim3_gt_tum: pd.DataFrame,
    sim3_vo_tum: pd.DataFrame,
    ate_per_frame: pd.DataFrame,
    rpe_per_frame: pd.DataFrame,
    scale_per_frame: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """构造 Excel 导出的中间结果 sheet。

    Sheet 设计：
    1. input_gt_tum: 原始 GT 转 TUM。
    2. input_vo_tum: 原始 estimate 转 TUM，并按 reset_count 跳变标记 vo_tum_XX。
       这里保留 vo_tum 作为历史 sheet 名称；在 VLOC 模式下它代表 vloc estimate。
    3. filtered_vo_tum: 时间同步后保留下来的 estimate。
    4. interpolated_gt_tum: 插值到 estimate 时间戳后的 GT。
    5. sim3_gt_tum: Sim3 评估时使用的 GT，VLOC 入口会移除这张表。
    6. sim3_vo_tum: Sim3 对齐后的 estimate，VLOC 入口会移除这张表。
    7. ate_per_frame: 每个评估时间戳的 ATE 明细。
    8. rpe_per_frame: 每个评估时间戳起算的固定帧/距离 RPE 明细。
    9. scale_per_frame: 每个评估时间戳起算的局部尺度比例/尺度漂移明细。
    """
    raw_gt_extra = {
        "source_index": np.arange(len(original_gt.positions), dtype=int),
        "tum_file": np.asarray(["gt_tum_01"] * len(original_gt.positions), dtype=object),
    }
    raw_vo_extra = jump_export_columns_from_source(original_est, None, "vo_tum")

    est_source_index = est_eval.extras.get("source_index")
    filtered_vo_extra = jump_export_columns_from_source(original_est, est_source_index, "vo_tum")
    filtered_vo_extra["matched_index"] = np.arange(len(est_eval.positions), dtype=int)

    sheets = {
        "input_gt_tum": trajectory_to_tum_dataframe(original_gt, raw_gt_extra),
        "input_vo_tum": trajectory_to_tum_dataframe(original_est, raw_vo_extra),
        "filtered_vo_tum": trajectory_to_tum_dataframe(est_eval, filtered_vo_extra),
        "interpolated_gt_tum": trajectory_to_tum_dataframe(gt_eval, interpolated_gt_extra_columns(gt_eval)),
        "sim3_gt_tum": sim3_gt_tum,
        "sim3_vo_tum": sim3_vo_tum,
        "ate_per_frame": ate_per_frame,
        "rpe_per_frame": rpe_per_frame,
    }
    if isinstance(scale_per_frame, pd.DataFrame) and not scale_per_frame.empty:
        sheets["scale_per_frame"] = scale_per_frame
    return sheets


def report_to_excel(report: dict[str, Any]) -> bytes:
    """把 report 中的轨迹和逐帧误差导出 sheet 写成一个 xlsx 工作簿。"""
    sheets = report.get("trajectory_exports") or {}
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            safe_name = re.sub(r"[\[\]:*?/\\]", "_", str(name))[:31] or "sheet"
            if isinstance(frame, pd.DataFrame):
                frame.to_excel(writer, sheet_name=safe_name, index=False)
            else:
                pd.DataFrame(frame).to_excel(writer, sheet_name=safe_name, index=False)
    return output.getvalue()


def report_to_json(report: dict[str, Any]) -> str:
    """导出严格 JSON 报告，供网页下载和 Pyodide 传回 JavaScript。"""
    return json.dumps(_jsonable_report(report), ensure_ascii=False, indent=2, allow_nan=False)


def _jsonable_report(report: dict[str, Any]) -> dict[str, Any]:
    """report_to_json() 的入口包装，保持调用语义清晰。"""
    return _jsonable_value(report)


def _jsonable_value(value: Any) -> Any:
    """把 report 递归转成标准 JSON 值。

    代码意义：
    - DataFrame -> records list，供 per_pose/rpe_per_frame/scale_per_frame 导出。
    - numpy scalar/array -> Python 原生类型，避免 json.dumps 不认识。
    - NaN/Infinity -> None，浏览器 JSON.parse 会把它读成 null。

    指标对应：
    - 所有 report 字段最终都经过这里，确保 ATE/RPE/alignment/export 等结果可以稳定导出。
    """
    if isinstance(value, pd.DataFrame):
        return [_jsonable_value(row) for row in value.to_dict(orient="records")]
    if isinstance(value, np.ndarray):
        return _jsonable_value(value.tolist())
    if isinstance(value, np.generic):
        return _jsonable_value(value.item())
    if isinstance(value, dict):
        return {key: _jsonable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _dataclass_to_jsonable(cfg: EvaluationConfig) -> dict[str, Any]:
    """把 EvaluationConfig 展开成普通 dict，写入 report["config"]。

    代码意义：
    - 报告里保留本次评估的所有参数，便于复现实验。
    - 这些配置不是算法结果，但会改变所有指标的解释方式。
    """
    return {
        "rpe_delta_frames": cfg.rpe_delta_frames,
        "rpe_delta_value": cfg.rpe_delta_value,
        "rpe_delta_unit": cfg.rpe_delta_unit,
        "rpe_distance_tolerance_ratio": cfg.rpe_distance_tolerance_ratio,
        "scale_delta_value": cfg.scale_delta_value,
        "scale_delta_unit": cfg.scale_delta_unit,
        "scale_distance_tolerance_ratio": cfg.scale_distance_tolerance_ratio,
    }
