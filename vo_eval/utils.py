"""Math, geometry, interpolation, and trajectory utility functions."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .data_loader import (
    Calibration,
    FIXED_TIME_OFFSET_S,
    HomePoint,
    Trajectory,
    VLOC_FIXED_MAX_INTERPOLATION_GAP_S,
    VO_MIN_VALID_SEGMENT_DURATION_S,
    VO_MIN_VALID_SEGMENT_FRAMES,
    WGS84_A_M,
    WGS84_E2,
)

def trajectory_extra_or_nan(traj: Trajectory, key: str) -> np.ndarray:
    """读取等长 extras；不存在时返回 NaN，方便前端图表跳过。"""
    values = traj.extras.get(key)
    if values is None or len(values) != len(traj.positions):
        return np.full(len(traj.positions), math.nan, dtype=float)
    return np.asarray(values, dtype=float)


def extra_values_linear(traj: Trajectory, key: str, target_stamps: np.ndarray) -> np.ndarray:
    """连续字段线性插值到 target_stamps。"""
    unique = _unique_timestamp_trajectory(traj)
    values = trajectory_extra_or_nan(unique, key)
    if len(values) == 0:
        return np.asarray([], dtype=float)
    if np.all(~np.isfinite(values)):
        return np.full(len(target_stamps), math.nan, dtype=float)
    return np.interp(target_stamps, unique.stamps, values)


def extra_values_nearest(traj: Trajectory, key: str, target_stamps: np.ndarray) -> np.ndarray:
    """离散状态字段最近邻插值到 target_stamps。"""
    unique = _unique_timestamp_trajectory(traj)
    values = trajectory_extra_or_nan(unique, key)
    if len(values) == 0:
        return np.asarray([], dtype=float)
    indices = nearest_indices_for_stamps(unique.stamps, target_stamps)
    return values[indices]


def nearest_indices_for_stamps(stamps: np.ndarray, target_stamps: np.ndarray) -> np.ndarray:
    """向量化最近时间戳索引，用于状态字段最近邻插值。"""
    src = np.asarray(stamps, dtype=float)
    target = np.asarray(target_stamps, dtype=float)
    if len(src) == 0:
        raise ValueError("Cannot find nearest index in an empty timestamp array")
    insert = np.searchsorted(src, target, side="left")
    left = np.clip(insert - 1, 0, len(src) - 1)
    right = np.clip(insert, 0, len(src) - 1)
    choose_right = np.abs(src[right] - target) < np.abs(target - src[left])
    return np.where(choose_right, right, left)

def sf_nav_to_body_ned_trajectory(nav: Trajectory, home_point: HomePoint) -> Trajectory:
    """把 nav GT 转成以 home_point 为原点的 body/NED 轨迹。

    水平 N/E 使用经纬度转 NED；垂直分量按原 MATLAB VLOC 口径处理：
    nav 使用 altitude_msl，VLOC 使用 raw z，因此后续误差等价于
    abs(nav_altitude_msl + vloc_body_z)。
    """
    latitude = _required_extra(nav, "latitude")
    longitude = _required_extra(nav, "longitude")
    altitude_msl = _required_extra(nav, "altitude_msl")
    ned = geodetic_to_ned(latitude, longitude, altitude_msl, home_point)
    extras = dict(nav.extras)
    extras["body_x_m"] = nav.positions[:, 0]
    extras["body_y_m"] = nav.positions[:, 1]
    extras["body_z_m"] = nav.positions[:, 2]
    extras["ned_n_m"] = ned[:, 0]
    extras["ned_e_m"] = ned[:, 1]
    extras["ned_d_m"] = ned[:, 2]
    return Trajectory(
        nav.name,
        nav.stamps,
        ned,
        nav.rotations,
        extras=extras,
        source_format="sf_imu_body_ned",
    )


def sf_vloc_to_body_ned_trajectory(vloc: Trajectory, home_point: HomePoint, calibration: Calibration) -> Trajectory:
    """把 vloc 的 imu 位姿转成 body/NED 轨迹。"""
    latitude = _required_extra(vloc, "latitude")
    longitude = _required_extra(vloc, "longitude")
    altitude_msl = np.asarray(vloc.extras.get("altitude_msl", vloc.positions[:, 2]), dtype=float)
    imu_ned = geodetic_to_ned(latitude, longitude, altitude_msl, home_point)

    rotations = vloc.rotations
    body_ned = imu_ned
    body_rot = rotations
    if rotations is not None:
        rot_imu_body = np.asarray(calibration.t_imu_body[:3, :3], dtype=float)
        trans_imu_body = np.asarray(calibration.t_imu_body[:3, 3], dtype=float)
        rot_body_imu = rot_imu_body.T
        trans_body_in_imu = -rot_body_imu @ trans_imu_body
        body_ned = imu_ned + np.einsum("nij,j->ni", rotations, trans_body_in_imu)
        body_rot = np.einsum("nij,jk->nik", rotations, rot_body_imu)

    extras = dict(vloc.extras)
    extras["imu_x_m"] = vloc.positions[:, 0]
    extras["imu_y_m"] = vloc.positions[:, 1]
    extras["imu_z_m"] = vloc.positions[:, 2]
    extras["ned_n_m"] = body_ned[:, 0]
    extras["ned_e_m"] = body_ned[:, 1]
    extras["ned_d_m"] = body_ned[:, 2]
    return Trajectory(
        vloc.name,
        vloc.stamps,
        body_ned,
        body_rot,
        extras=extras,
        source_format="sf_vloc_body_ned",
    )


def sf_nav_to_camera_trajectory(nav: Trajectory, calibration: Calibration) -> Trajectory:
    """把 nav 从 body/IMU 系转到 camera 系，使 nav 与 VO 在同一坐标系下评估。

    数学（参考 convert_nav_to_tum.py）：
      R_b_c = R_b_i @ R_c_i^T
      P_b_c = P_b_i - R_b_c @ P_c_i
    对每一帧 nav：
      R_w_c = R_w_b @ R_b_c
      P_w_c = P_w_b + R_w_b @ P_b_c

    来源对应：需求明确 VO 在 cam frame 输出，因此把 GT 转到 cam frame 比较，
    而不是把 VO 转到 body frame。单位外参时输出应与原始 nav 完全一致。
    """
    t_imu_body = np.asarray(calibration.t_imu_body, dtype=float)
    t_cam_imu = np.asarray(calibration.t_cam_imu, dtype=float)

    rot_b_i = t_imu_body[:3, :3]
    trans_b_i = t_imu_body[:3, 3]
    rot_c_i = t_cam_imu[:3, :3]
    trans_c_i = t_cam_imu[:3, 3]

    rot_b_c = rot_b_i @ rot_c_i.T
    trans_b_c = trans_b_i - rot_b_c @ trans_c_i

    rotations = nav.rotations
    cam_positions = np.asarray(nav.positions, dtype=float)
    cam_rotations = rotations
    if rotations is not None:
        cam_positions = cam_positions + np.einsum("nij,j->ni", rotations, trans_b_c)
        cam_rotations = np.einsum("nij,jk->nik", rotations, rot_b_c)

    extras = dict(nav.extras)
    extras["body_x_m"] = nav.positions[:, 0]
    extras["body_y_m"] = nav.positions[:, 1]
    extras["body_z_m"] = nav.positions[:, 2]
    extras["cam_x_m"] = cam_positions[:, 0]
    extras["cam_y_m"] = cam_positions[:, 1]
    extras["cam_z_m"] = cam_positions[:, 2]
    return Trajectory(
        nav.name,
        nav.stamps,
        cam_positions,
        cam_rotations,
        extras=extras,
        source_format="sf_imu_camera",
    )


def vo_valid_segment_indices(vo: Trajectory) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """按 reset_count 连续段筛选 VO 有效段。

    规则来自需求文档：
    - reset_count 变化代表 VO 重新初始化，新段不能和旧段混成一条连续轨迹；
    - 每段 duration < 10 s 或 frame count < 200 都视为无效，先过滤；
    - 剩余有效段会重新编号为 evaluation_segment_id，供 Sim3 分段对齐和 3D 起终点显示使用。
    """
    reset_count = trajectory_extra_or_nan(vo, "reset_count")
    n = len(vo.positions)
    if n == 0:
        return np.asarray([], dtype=int), np.asarray([], dtype=int), {
            "segments": [],
            "valid_segment_count": 0,
            "invalid_segment_count": 0,
            "dropped_pose_count": 0,
        }

    starts = [0]
    for idx in range(n - 1):
        current = reset_count[idx]
        nxt = reset_count[idx + 1]
        changed = current != nxt
        if not np.isfinite(current) or not np.isfinite(nxt):
            changed = True
        if changed:
            starts.append(idx + 1)
    starts.append(n)

    valid_indices: list[int] = []
    valid_segment_ids: list[int] = []
    segment_infos: list[dict[str, Any]] = []
    next_valid_segment_id = 0
    for raw_segment_id, (start, end) in enumerate(zip(starts[:-1], starts[1:])):
        count = int(end - start)
        duration_s = float(vo.stamps[end - 1] - vo.stamps[start]) if count > 1 else 0.0
        valid = count >= VO_MIN_VALID_SEGMENT_FRAMES and duration_s >= VO_MIN_VALID_SEGMENT_DURATION_S
        info = {
            "raw_segment_id": int(raw_segment_id),
            "start_index": int(start),
            "end_index": int(end),
            "count": count,
            "duration_s": duration_s,
            "reset_count": float(reset_count[start]) if np.isfinite(reset_count[start]) else math.nan,
            "valid": bool(valid),
        }
        if valid:
            segment_indices = list(range(start, end))
            valid_indices.extend(segment_indices)
            valid_segment_ids.extend([next_valid_segment_id] * count)
            info["evaluation_segment_id"] = int(next_valid_segment_id)
            next_valid_segment_id += 1
        segment_infos.append(info)

    valid_idx_arr = np.asarray(valid_indices, dtype=int)
    valid_seg_arr = np.asarray(valid_segment_ids, dtype=int)
    return valid_idx_arr, valid_seg_arr, {
        "min_duration_s": float(VO_MIN_VALID_SEGMENT_DURATION_S),
        "min_frames": int(VO_MIN_VALID_SEGMENT_FRAMES),
        "segments": segment_infos,
        "valid_segment_count": int(next_valid_segment_id),
        "invalid_segment_count": int(sum(1 for item in segment_infos if not item["valid"])),
        "dropped_pose_count": int(n - len(valid_idx_arr)),
    }


def _required_extra(traj: Trajectory, key: str) -> np.ndarray:
    values = traj.extras.get(key)
    if values is None:
        raise ValueError(f"{traj.name}: missing required trajectory extra '{key}'")
    arr = np.asarray(values, dtype=float)
    if len(arr) != len(traj.positions):
        raise ValueError(f"{traj.name}: extra '{key}' length mismatch")
    return arr


def geodetic_to_ned(
    latitude_deg: np.ndarray,
    longitude_deg: np.ndarray,
    altitude_m: np.ndarray,
    home_point: HomePoint,
) -> np.ndarray:
    """WGS84 经纬高转以 home_point 为原点的 NED。"""
    lat = np.asarray(latitude_deg, dtype=float).reshape(-1)
    lon = np.asarray(longitude_deg, dtype=float).reshape(-1)
    alt = np.asarray(altitude_m, dtype=float).reshape(-1)
    if not (len(lat) == len(lon) == len(alt)):
        raise ValueError("latitude/longitude/altitude arrays must have the same length")

    ecef = geodetic_to_ecef(lat, lon, alt)
    home_ecef = geodetic_to_ecef(
        np.asarray([home_point.latitude], dtype=float),
        np.asarray([home_point.longitude], dtype=float),
        np.asarray([home_point.altitude_msl], dtype=float),
    )[0]
    lat0 = math.radians(float(home_point.latitude))
    lon0 = math.radians(float(home_point.longitude))
    sin_lat0, cos_lat0 = math.sin(lat0), math.cos(lat0)
    sin_lon0, cos_lon0 = math.sin(lon0), math.cos(lon0)
    ecef_to_ned = np.asarray(
        [
            [-sin_lat0 * cos_lon0, -sin_lat0 * sin_lon0, cos_lat0],
            [-sin_lon0, cos_lon0, 0.0],
            [-cos_lat0 * cos_lon0, -cos_lat0 * sin_lon0, -sin_lat0],
        ],
        dtype=float,
    )
    delta = ecef - home_ecef
    return delta @ ecef_to_ned.T


def geodetic_to_ecef(latitude_deg: np.ndarray, longitude_deg: np.ndarray, altitude_m: np.ndarray) -> np.ndarray:
    """WGS84 经纬高转 ECEF。"""
    lat = np.deg2rad(np.asarray(latitude_deg, dtype=float).reshape(-1))
    lon = np.deg2rad(np.asarray(longitude_deg, dtype=float).reshape(-1))
    alt = np.asarray(altitude_m, dtype=float).reshape(-1)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    sin_lon = np.sin(lon)
    cos_lon = np.cos(lon)
    radius = WGS84_A_M / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (radius + alt) * cos_lat * cos_lon
    y = (radius + alt) * cos_lat * sin_lon
    z = (radius * (1.0 - WGS84_E2) + alt) * sin_lat
    return np.column_stack([x, y, z])

def prepare_evaluation_trajectories(
    gt: Trajectory,
    est: Trajectory,
    *,
    max_interpolation_gap_s: float,
) -> tuple[Trajectory, Trajectory, np.ndarray, np.ndarray, dict[str, Any]]:
    """把 GT/reference 和 estimate 准备成同一时间轴上的评估序列。

    代码意义：
    - 固定以 estimate 时间戳为基准，把 GT/reference 插值到 estimate 时刻。
      这适合物流无人机/IMU GT 长时间记录场景，算法输出只有运行段也不会引入无关 GT。

    指标对应：
    - 返回的 assoc 会进入 report["association"]。
    - interpolate_reference_to_estimate() 会先构造同一时间轴上的 gt_eval/est_eval；
      这里返回的 gt_idx/est_idx 是等长索引，不表示插值模式下的原始离散 GT 索引。

    来源对应：
    - interpolate_gt 是工程扩展：Schubert18/TUM VI 提供高频同步 GT 的评估语境；
      对物流无人机这种“GT 全程跑、estimate 只在算法段输出”的数据，按 estimate 时间戳插 GT 更合理。
    """
    gt_eval, est_eval, assoc = interpolate_reference_to_estimate(
        gt,
        est,
        max_interpolation_gap_s=max_interpolation_gap_s,
    )
    idx = np.arange(len(gt_eval.positions), dtype=int)
    return gt_eval, est_eval, idx, idx, assoc


def interpolate_reference_to_estimate(
    reference: Trajectory,
    estimate: Trajectory,
    *,
    max_interpolation_gap_s: float = VLOC_FIXED_MAX_INTERPOLATION_GAP_S,
) -> tuple[Trajectory, Trajectory, dict[str, Any]]:
    """把 reference 轨迹插值到 estimate 时间戳。

    这是当前 sf_vloc/sf_vo 的固定时间同步方法：
    - estimate 自己的时间戳作为评估行；
    - reference 的查询时刻是 estimate.stamps；
    - 超出 reference 时间范围、时间戳非法或左右 reference 样本间隔超过 max_interpolation_gap_s 的 estimate 帧会被丢弃，不允许外推；
    - 返回的 ref_interp 和 est_matched 等长，且都使用原始 estimate 时间戳，target_stamp 会保存在 extras 中方便排查固定时间偏移。
    """
    ref_unique = _unique_timestamp_trajectory(reference)
    duplicate_timestamp_count = int(len(reference.stamps) - len(ref_unique.stamps))
    shifted_est_stamps = estimate.stamps + FIXED_TIME_OFFSET_S
    finite_est = np.isfinite(shifted_est_stamps)
    before_range = finite_est & (shifted_est_stamps < ref_unique.stamps[0])
    after_range = finite_est & (shifted_est_stamps > ref_unique.stamps[-1])
    in_range = finite_est & ~before_range & ~after_range

    candidate_est_indices = np.flatnonzero(in_range)
    target_candidates = shifted_est_stamps[candidate_est_indices]
    bracket_info = interpolation_brackets(ref_unique.stamps, target_candidates)
    candidate_gaps = bracket_info["gap_s"]
    candidate_valid_timestamp = bracket_info["valid_timestamp"]
    valid_gap = candidate_gaps <= float(max_interpolation_gap_s)
    valid = candidate_valid_timestamp & valid_gap

    est_indices = candidate_est_indices[valid]
    target_stamps = target_candidates[valid]
    common_stamps = estimate.stamps[est_indices]
    bracket_gaps = candidate_gaps[valid]
    left_indices = bracket_info["left_index"][valid]
    right_indices = bracket_info["right_index"][valid]
    alphas = bracket_info["alpha"][valid]
    left_offsets = bracket_info["left_offset_s"][valid]
    right_offsets = bracket_info["right_offset_s"][valid]
    nearest_side_offsets = bracket_info["nearest_side_offset_s"][valid]

    dropped_invalid_timestamp = int(np.count_nonzero(~finite_est) + np.count_nonzero(in_range) - np.count_nonzero(candidate_valid_timestamp))
    dropped_before = int(np.count_nonzero(before_range))
    dropped_after = int(np.count_nonzero(after_range))
    dropped_gap = int(np.count_nonzero(candidate_valid_timestamp & ~valid_gap))

    ref_positions = interpolate_positions_from_brackets(ref_unique.positions, left_indices, right_indices, alphas)
    if ref_unique.rotations is not None:
        ref_rotations = interpolate_rotations_from_brackets(ref_unique.rotations, left_indices, right_indices, alphas)
        rotation_method_report = "slerp"
    else:
        ref_rotations = None
        rotation_method_report = "skipped_no_reference_rotation"

    est_matched = subset_trajectory(estimate, est_indices, stamps_override=common_stamps)
    est_matched.extras["source_index"] = est_indices
    est_matched.extras["original_est_stamp"] = estimate.stamps[est_indices]
    est_matched.extras["target_stamp"] = target_stamps
    ref_interp = Trajectory(
        f"{reference.name}_interpolated_to_{estimate.name}",
        common_stamps,
        ref_positions,
        ref_rotations,
        extras={
            "source_index": est_indices,
            "original_est_stamp": estimate.stamps[est_indices],
            "target_stamp": target_stamps,
            "gt_left_index": left_indices,
            "gt_right_index": right_indices,
            "interp_alpha": alphas,
            "gt_bracket_gap_s": bracket_gaps,
        },
        source_format=f"{reference.source_format}+interpolated",
    )
    matched_duration = float(common_stamps[-1] - common_stamps[0]) if len(common_stamps) > 1 else 0.0
    info = {
        "method": "interpolate_gt",
        "mode": "interpolate_gt",
        "target": "estimate_timestamps",
        "interpolated": True,
        "position_method": "linear",
        "rotation_method": rotation_method_report,
        "time_offset_s": float(FIXED_TIME_OFFSET_S),
        "max_interpolation_gap_s": max_interpolation_gap_s,
        "max_interpolation_gap_s_allowed": max_interpolation_gap_s,
        "max_interpolation_gap_config_s": max_interpolation_gap_s,
        "allow_extrapolation": False,
        "estimate_count_input": int(len(estimate.stamps)),
        "reference_count_input": int(len(reference.stamps)),
        "estimate_pose_count": int(len(estimate.positions)),
        "reference_pose_count": int(len(reference.positions)),
        "reference_duplicate_timestamp_count": duplicate_timestamp_count,
        "matched_count": int(len(est_indices)),
        "matches": int(len(est_indices)),
        "dropped_count": int(len(estimate.stamps) - len(est_indices)),
        "dropped": int(len(estimate.stamps) - len(est_indices)),
        "coverage_estimate_ratio": float(len(est_indices) / max(1, len(estimate.stamps))),
        "est_pose_coverage_ratio": float(len(est_indices) / max(1, len(estimate.positions))),
        "candidate_pose_count_inside_gt_range": int(len(candidate_est_indices)),
        "dropped_before_reference_range": dropped_before,
        "dropped_after_reference_range": dropped_after,
        "dropped_gt_gap_too_large": dropped_gap,
        "dropped_invalid_timestamp": dropped_invalid_timestamp,
        "outside_gt_range_count": int(dropped_before + dropped_after),
        "large_interpolation_gap_count": dropped_gap,
        "dropped_est_outside_gt_range": int(dropped_before + dropped_after),
        "dropped_est_large_gt_gap": dropped_gap,
        "max_used_gt_gap_s": float(np.max(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "mean_used_gt_gap_s": float(np.mean(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "median_used_gt_gap_s": float(np.median(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "p95_used_gt_gap_s": float(np.percentile(bracket_gaps, 95)) if len(bracket_gaps) else 0.0,
        "max_interpolation_gap_used_s": float(np.max(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "mean_interpolation_gap_s": float(np.mean(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "median_interpolation_gap_s": float(np.median(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "p95_interpolation_gap_s": float(np.percentile(bracket_gaps, 95)) if len(bracket_gaps) else 0.0,
        "max_abs_time_offset_to_left_sample_s": float(np.max(left_offsets)) if len(left_offsets) else 0.0,
        "max_abs_time_offset_to_right_sample_s": float(np.max(right_offsets)) if len(right_offsets) else 0.0,
        "mean_abs_time_offset_to_left_or_right_s": float(np.mean(nearest_side_offsets)) if len(nearest_side_offsets) else 0.0,
        "gt_time_coverage_ratio": float(matched_duration / reference.duration_s) if reference.duration_s > 0 else 1.0,
    }
    if ref_unique.rotations is None:
        info["rotation_interpolation_note"] = "rotation interpolation skipped: no reference rotation"
    if info["coverage_estimate_ratio"] < 0.8:
        info["warning"] = "low interpolate_gt coverage; check timestamp units, GT/estimate time ranges, time_offset_s, and max_interpolation_gap_s"
    if not len(est_indices):
        info["warning"] = "no estimate timestamp remains after interpolation filtering"
    elif len(est_indices) < 2:
        info["warning"] = "fewer than two estimate timestamps remain after interpolation filtering"
    return ref_interp, est_matched, info


def _unique_timestamp_trajectory(traj: Trajectory) -> Trajectory:
    """Keep the first sample for duplicate timestamps before interpolation."""
    unique_stamps, unique_indices = np.unique(traj.stamps, return_index=True)
    if len(unique_stamps) == len(traj.stamps):
        return traj
    return subset_trajectory(traj, np.sort(unique_indices), stamps_override=traj.stamps[np.sort(unique_indices)])


def subset_trajectory(traj: Trajectory, indices: np.ndarray, stamps_override: np.ndarray | None = None) -> Trajectory:
    """按索引截取轨迹，并可把时间戳替换成统一后的评估时间戳。"""
    rotations = traj.rotations[indices] if traj.rotations is not None else None
    extras = {key: np.asarray(value)[indices] for key, value in traj.extras.items() if len(value) == len(traj.positions)}
    stamps = np.asarray(stamps_override, dtype=float) if stamps_override is not None else traj.stamps[indices]
    return Trajectory(traj.name, stamps, traj.positions[indices], rotations, extras=extras, source_format=traj.source_format)


def interpolate_positions_from_brackets(
    src_positions: np.ndarray,
    left_indices: np.ndarray,
    right_indices: np.ndarray,
    alphas: np.ndarray,
) -> np.ndarray:
    """使用预先计算好的左右样本和 alpha 做位置线性插值。"""
    if len(left_indices) == 0:
        return np.empty((0, 3), dtype=float)
    p0 = src_positions[left_indices]
    p1 = src_positions[right_indices]
    alpha = np.asarray(alphas, dtype=float).reshape(-1, 1)
    return (1.0 - alpha) * p0 + alpha * p1


def interpolation_brackets(
    src_stamps: np.ndarray,
    target_stamps: np.ndarray,
) -> dict[str, np.ndarray]:
    """找到每个目标时间戳两侧的 GT 样本，并计算插值诊断量。

    输出字段对应 report["association"] 和 gt_eval.extras：
    - left_index/right_index: GT 插值使用的左右样本。若目标时间戳正好命中 GT，左右索引相同。
    - alpha: 线性插值/SLERP 的比例，0 表示左端，1 表示右端。
    - gap_s: 左右 GT 样本间隔，用于 max_interpolation_gap_s 过滤。
    - nearest_side_offset_s: 目标时间戳离左右样本较近一侧的时间差，用于诊断采样偏差。
    """
    src = np.asarray(src_stamps, dtype=float)
    target = np.asarray(target_stamps, dtype=float)
    if len(src) == 0:
        raise ValueError("Cannot interpolate against an empty reference trajectory")
    insert = np.searchsorted(src, target, side="left")
    clipped_insert = np.clip(insert, 0, max(0, len(src) - 1))
    exact = (insert < len(src)) & np.isclose(src[clipped_insert], target)

    left = np.empty(len(target), dtype=int)
    right = np.empty(len(target), dtype=int)
    left[exact] = clipped_insert[exact]
    right[exact] = clipped_insert[exact]

    middle = (~exact) & (insert > 0) & (insert < len(src))
    left[middle] = insert[middle] - 1
    right[middle] = insert[middle]

    before = (~exact) & (insert <= 0)
    after = (~exact) & (insert >= len(src))
    outside = before | after
    left[outside] = np.clip(insert[outside] - 1, 0, max(0, len(src) - 1))
    right[outside] = np.clip(insert[outside], 0, max(0, len(src) - 1))

    gaps = np.zeros(len(target), dtype=float)
    gaps[middle] = src[right[middle]] - src[left[middle]]
    gaps[outside] = math.inf

    alpha = np.zeros(len(target), dtype=float)
    valid_denominator = gaps > 0
    alpha[valid_denominator] = (target[valid_denominator] - src[left[valid_denominator]]) / gaps[valid_denominator]
    alpha = np.clip(alpha, 0.0, 1.0)

    left_offset = np.abs(target - src[left])
    right_offset = np.abs(src[right] - target)
    nearest_side_offset = np.minimum(left_offset, right_offset)
    invalid = outside
    nearest_side_offset[invalid] = math.inf
    left_offset[invalid] = math.inf
    right_offset[invalid] = math.inf
    return {
        "left_index": left,
        "right_index": right,
        "alpha": alpha,
        "gap_s": gaps,
        "left_offset_s": left_offset,
        "right_offset_s": right_offset,
        "nearest_side_offset_s": nearest_side_offset,
        "valid_timestamp": np.isfinite(gaps),
    }


def interpolate_rotations_from_brackets(
    src_rotations: np.ndarray | None,
    left_indices: np.ndarray,
    right_indices: np.ndarray,
    alphas: np.ndarray,
) -> np.ndarray | None:
    """使用预先计算好的左右样本和 alpha 对旋转做 SLERP。"""
    if src_rotations is None:
        return None
    if len(left_indices) == 0:
        return np.empty((0, 3, 3), dtype=float)
    quats = matrix_to_quaternion(src_rotations)
    out = np.empty((len(left_indices), 4), dtype=float)
    for i, (left, right, alpha) in enumerate(zip(left_indices, right_indices, alphas)):
        if left == right or abs(float(alpha)) < 1e-15:
            out[i] = quats[left]
        elif abs(float(alpha) - 1.0) < 1e-15:
            out[i] = quats[right]
        else:
            out[i] = slerp_quaternion(quats[left], quats[right], float(alpha))
    return quaternion_to_matrix(out[:, 0], out[:, 1], out[:, 2], out[:, 3])


def slerp_quaternion(q0: np.ndarray, q1: np.ndarray, alpha: float) -> np.ndarray:
    """四元数球面线性插值，避免直接线性插姿态造成旋转误差。"""
    q0 = np.asarray(q0, dtype=float)
    q1 = np.asarray(q1, dtype=float)
    q0_norm = np.linalg.norm(q0)
    q1_norm = np.linalg.norm(q1)
    if q0_norm == 0 or q1_norm == 0:
        raise ValueError("Cannot SLERP a zero-norm quaternion")
    q0 = q0 / q0_norm
    q1 = q1 / q1_norm
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    if dot > 0.9995:
        q = q0 + alpha * (q1 - q0)
        return q / np.linalg.norm(q)
    theta_0 = math.acos(float(np.clip(dot, -1.0, 1.0)))
    theta = theta_0 * alpha
    sin_theta = math.sin(theta)
    sin_theta_0 = math.sin(theta_0)
    s0 = math.cos(theta) - dot * sin_theta / sin_theta_0
    s1 = sin_theta / sin_theta_0
    return s0 * q0 + s1 * q1


def _gt_coverage_ratio(total_duration_s: float, original_gt: Trajectory) -> float:
    """GT 覆盖率口径：按有效评估时间窗口占原始 GT 总时长计算。"""
    return float(total_duration_s / original_gt.duration_s) if original_gt.duration_s > 0 else 1.0


def identity_alignment() -> dict[str, Any]:
    """VLOC 固定不做轨迹对齐，直接统计 nav-vloc 坐标差。"""
    return _alignment_dict("none", 1.0, np.eye(3), np.zeros(3))


def sim3_alignment(gt_pos: np.ndarray, est_pos: np.ndarray) -> dict[str, Any]:
    """VO 固定使用 Sim3，把 estimate 对齐到 GT/reference 坐标系。

    指标对应：
    - alignment["scale"] 最终显示为页面“对齐尺度”。
    - 所有 VO ATE/RPE 都基于 Sim3 后的 est_pos_aligned 计算。

    来源对应：
    - Sturm12 的 ATE 需要先把估计轨迹配准到 GT 后再算绝对误差。
    - Zhang18 明确说明单目无尺度通常看 Sim3。
    """
    scale, rot, trans = umeyama_alignment(est_pos, gt_pos)
    return _alignment_dict("sim3", scale, rot, trans)


def umeyama_alignment(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Umeyama Sim3 SVD 对齐。

    src 是 estimate，dst 是 GT。当前固定流程只保留 VO 的 Sim3 对齐；
    VLOC 直接走 alignment=none，不会调用这里。

    代码意义：
    - 通过最小二乘求 R/t/s，使 s * R * estimate + t 尽量贴近 GT。
    - 这是 evo、rpg_trajectory_evaluation、KITTI 类评估中常见的轨迹对齐口径。
    - det 修正用于避免 SVD 给出反射矩阵；轨迹对齐必须是合法旋转。

    指标影响：
    - scale 会进入 report["alignment"]，也会影响所有对齐后的 ATE/RPE/segment 误差。
    - Sim3 会降低无尺度 VO 的位置误差，但 raw_path_scale_ratio 和局部尺度图仍能暴露尺度问题。

    来源对应：
    - 对齐这个评估步骤来自 Sturm12/Zhang18；Umeyama 是这里采用的 SVD 数值实现。
    - 如果启用 Sim3，报告里的尺度结论应按 Zhang18 的“尺度可观性”来解释。
    """
    src = np.asarray(src, dtype=float)
    dst = np.asarray(dst, dtype=float)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError("src and dst must have shape (N, 3)")
    if len(src) < 2:
        return 1.0, np.eye(3), dst[0] - src[0]

    # 1. 先去中心化，避免平移影响旋转和尺度估计。
    mu_src = src.mean(axis=0)
    mu_dst = dst.mean(axis=0)
    src_centered = src - mu_src
    dst_centered = dst - mu_dst

    # 2. 交叉协方差描述 estimate 与 GT 的主方向关系，SVD 从中恢复最优旋转。
    cov = (dst_centered.T @ src_centered) / len(src)
    u, singular_values, vt = np.linalg.svd(cov)
    sign = np.ones(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[-1] = -1
    s_mat = np.diag(sign)
    rot = u @ s_mat @ vt

    # 3. 固定 Sim3 模式估计尺度。
    var_src = float(np.mean(np.sum(src_centered * src_centered, axis=1)))
    scale = float(np.sum(singular_values * sign) / var_src) if var_src > 0 else 1.0

    # 4. 在旋转/尺度确定后，用两条轨迹的中心点求平移。
    trans = mu_dst - scale * (rot @ mu_src)
    return scale, rot, trans


def apply_alignment(positions: np.ndarray, alignment: dict[str, Any]) -> np.ndarray:
    """把 estimate 位置应用到 GT 坐标系。

    公式：p_aligned = scale * R * p_est + t。
    之后所有位置误差字段都基于这个结果：
    - per_pose.error_m / horizontal_error_m / vertical_error_m
    - ate_position_m / ate_horizontal_m / ate_vertical_m
    - rpe_frame_delta.translation_m
    - scale_frame_delta / scale_per_frame 中的局部尺度统计
    """
    scale = float(alignment["scale"])
    rot = np.asarray(alignment["rotation"], dtype=float)
    trans = np.asarray(alignment["translation"], dtype=float)
    return scale * (positions @ rot.T) + trans


def apply_rotation_alignment(rotations: np.ndarray | None, alignment: dict[str, Any]) -> np.ndarray | None:
    """把 estimate 姿态应用同一个对齐旋转。

    只应用 rotation，不应用 scale/translation，因为姿态没有尺度和平移。
    结果用于姿态 ATE、yaw 误差和 RPE 旋转误差。
    """
    if rotations is None:
        return None
    rot = np.asarray(alignment["rotation"], dtype=float)
    return np.einsum("ij,njk->nik", rot, rotations)


def alignment_export_columns(alignment: dict[str, Any], count: int, prefix: str) -> dict[str, Any]:
    """把 Sim3/SE3 对齐参数展开成可写入 Excel sheet 的列。

    Sim3 不是只有尺度，还包含完整变换：
    p_gt = scale * R * p_vo + t。
    因此导出中间轨迹时同时保留：
    - scale: 尺度因子；
    - rotation_r00...r22: 3x3 旋转矩阵；
    - translation_x/y/z: 平移向量。
    """
    rot = np.asarray(alignment["rotation"], dtype=float)
    trans = np.asarray(alignment["translation"], dtype=float)
    out: dict[str, Any] = {
        f"{prefix}_mode": np.asarray([alignment.get("mode", prefix)] * count, dtype=object),
        f"{prefix}_scale": np.full(count, float(alignment["scale"]), dtype=float),
        f"{prefix}_translation_x": np.full(count, float(trans[0]), dtype=float),
        f"{prefix}_translation_y": np.full(count, float(trans[1]), dtype=float),
        f"{prefix}_translation_z": np.full(count, float(trans[2]), dtype=float),
    }
    for row in range(3):
        for col in range(3):
            out[f"{prefix}_rotation_r{row}{col}"] = np.full(count, float(rot[row, col]), dtype=float)
    return out


def aggregate_alignment(alignments: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    """聚合每个连续段的对齐信息。

    代码意义：
    - 默认系统可以按 estimate 时间戳统一评估，也可以按连续段分别对齐/评估。
    - 多段时每段都有自己的 scale/rotation/translation，这里把 scale 做 min/max/mean 汇总。

    指标对应：
    - alignment.scale: 平均对齐尺度。
    - alignment.scale_min / scale_max: 不同连续段的尺度范围。
    - alignment.segment_count: 参与对齐的连续段数量。
    - 报告里的“分段尺度变化明显”就是根据 scale_min/scale_max/scale 触发的。

    来源对应：
    - 单段 SE3/Sim3 对齐来自 Sturm12/Zhang18。
    - 分段尺度范围是工程扩展，用来暴露长航程单目 VO 在不同连续段的尺度不稳定。
    """
    if not alignments:
        return _alignment_dict(mode, 1.0, np.eye(3), np.zeros(3))
    scales = np.asarray([float(item["scale"]) for item in alignments], dtype=float)
    return {
        "mode": "per_segment",
        "base_mode": mode,
        "scale": float(np.mean(scales)),
        "scale_min": float(np.min(scales)),
        "scale_max": float(np.max(scales)),
        "segment_count": int(len(alignments)),
        "segments": alignments,
    }


def detect_associated_discontinuities(
    stamps: np.ndarray,
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    step_threshold_m: float,
    time_gap_threshold_s: float,
    forced_segment_ids: np.ndarray | None = None,
) -> dict[str, Any]:
    """断点/重置诊断。

    根据 GT 步长、estimate 步长、时间间隔判断是否存在大跳变。
    如果传入 forced_segment_ids，则相邻样本的分段 id 变化也会被当作断点，
    这用于 sf_vo reset_count 切段后的强制分段评估。
    默认评估策略不会丢弃这些点，只把信息放入 report["discontinuities"] 供诊断。

    断点来源：
    - gt_step: GT 自己相邻点跳得很远，可能是 GT 数据中断或坐标跳变。
    - est_step: estimate 相邻点跳得很远，可能是 VO/VLOC 重置、丢跟踪后重新初始化或坐标系切换。
    - evaluation_segment_id: sf_vo 的 reset_count 过滤后，不同 reset 段边界会被强制标成断点。
    - time_gap: 相邻评估时间差很大，可能是日志中断或算法停顿。

    指标/页面影响：
    - break_count > 0 会触发“检测到 reset/gap/大跳变”提示。
    - segment_ids 会写入 per_pose，让可视化在断点处断开，不错误连线。

    来源对应：
    - 这是工程扩展，5 篇论文没有把“reset 断点”定义成标准数值指标。
    - 目的在于保护 Geiger12/KITTI 风格的子轨迹统计，避免跨重定位/重置段计算相对误差。
    """
    n = len(stamps)
    if n == 0:
        return {"segment_count": 0, "break_count": 0, "breaks": [], "segments": [], "segment_ids": np.asarray([], dtype=int)}
    if n == 1:
        return {"segment_count": 1, "break_count": 0, "breaks": [], "segments": [{"start": 0, "end": 1, "count": 1}], "segment_ids": np.zeros(1, dtype=int)}

    gt_steps = np.linalg.norm(np.diff(gt_pos, axis=0), axis=1)
    est_steps = np.linalg.norm(np.diff(est_pos, axis=0), axis=1)
    time_gaps = np.diff(stamps)
    forced_ids = np.asarray(forced_segment_ids).reshape(-1) if forced_segment_ids is not None else None
    if forced_ids is not None and len(forced_ids) != n:
        forced_ids = None
    break_after = np.zeros(n - 1, dtype=bool)
    breaks: list[dict[str, Any]] = []
    for idx, (gt_step, est_step, time_gap) in enumerate(zip(gt_steps, est_steps, time_gaps)):
        reasons: list[str] = []
        if forced_ids is not None and forced_ids[idx] != forced_ids[idx + 1]:
            reasons.append("evaluation_segment_id")
        if step_threshold_m > 0 and gt_step > step_threshold_m:
            reasons.append("gt_step")
        if step_threshold_m > 0 and est_step > step_threshold_m:
            reasons.append("est_step")
        if time_gap_threshold_s > 0 and time_gap > time_gap_threshold_s:
            reasons.append("time_gap")
        if reasons:
            # break_after[idx] 表示 idx 和 idx+1 之间存在断点。
            break_after[idx] = True
            breaks.append(
                {
                    "after_index": int(idx),
                    "before_time_s": float(stamps[idx]),
                    "after_time_s": float(stamps[idx + 1]),
                    "time_gap_s": float(time_gap),
                    "gt_step_m": float(gt_step),
                    "est_step_m": float(est_step),
                    "reasons": reasons,
                }
            )

    segments = segments_from_breaks(n, break_after)
    segment_ids = np.zeros(n, dtype=int)
    for seg_id, seg in enumerate(segments):
        segment_ids[seg["start"] : seg["end"]] = seg_id

    return {
        "step_threshold_m": float(step_threshold_m),
        "time_gap_threshold_s": float(time_gap_threshold_s),
        "break_count": int(len(breaks)),
        "segment_count": int(len(segments)),
        "breaks": breaks,
        "segments": segments,
        "segment_ids": segment_ids,
    }


def segments_from_breaks(n: int, break_after: np.ndarray) -> list[dict[str, int]]:
    """把断点布尔数组转换成连续段列表。"""
    starts = [0]
    ends: list[int] = []
    for idx, is_break in enumerate(break_after):
        if is_break:
            ends.append(idx + 1)
            starts.append(idx + 1)
    ends.append(n)
    return [{"start": int(start), "end": int(end), "count": int(end - start)} for start, end in zip(starts, ends) if end > start]


def relative_error(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    i: int,
    j: int,
) -> tuple[float, float | None]:
    """RPE 相对运动误差。

    有姿态时在各自起点坐标系下比较相对位移/相对旋转；
    无姿态时只比较世界系位移差。

    指标对应：
    - RPE: i 和 j 通常是固定帧间隔，或 evo consecutive-pairs 固定路程锚点。

    为什么有姿态时要转到起点坐标系：
    - RPE/子轨迹关心的是“这段相对运动估得准不准”，不希望被世界系整体旋转影响。
    - 这也和 TUM/RPG/KITTI 常见相对误差定义一致。

    来源对应：
    - 固定帧 i->j 的相对误差来自 Sturm12 RPE。
    - Zhang18 给出了统一的相对轨迹误差解释。
    """
    if gt_rot is not None and est_rot is not None:
        gt_r, gt_t = relative_pose(gt_rot[i], gt_pos[i], gt_rot[j], gt_pos[j])
        est_r, est_t = relative_pose(est_rot[i], est_pos[i], est_rot[j], est_pos[j])
        err_r = gt_r.T @ est_r
        err_t = gt_r.T @ (est_t - gt_t)
        return float(np.linalg.norm(err_t)), float(rotation_angle(err_r))
    gt_delta = gt_pos[j] - gt_pos[i]
    est_delta = est_pos[j] - est_pos[i]
    return float(np.linalg.norm(est_delta - gt_delta)), None
    # gt_dist = float(np.linalg.norm(gt_pos[j] - gt_pos[i]))
    # est_dist = float(np.linalg.norm(est_pos[j] - est_pos[i]))
    # return abs(est_dist - gt_dist), None


def relative_pose(r_i: np.ndarray, p_i: np.ndarray, r_j: np.ndarray, p_j: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """计算从第 i 帧到第 j 帧的相对位姿。

    r_rel = R_i^T R_j，p_rel = R_i^T (p_j - p_i)。
    这个局部坐标系表达会被 relative_error() 用来比较 GT 和 estimate 的相对运动。
    """
    r_rel = r_i.T @ r_j
    p_rel = r_i.T @ (p_j - p_i)
    return r_rel, p_rel


def path_distance(positions: np.ndarray) -> np.ndarray:
    """累计路程 D_i。

    用于 summary.gt_path_length_m、误差随路程图、RPE 距离间隔和局部尺度窗口。

    来源对应：
    - 本系统把累计路程用于无人机长航程误差曲线、RPE 和局部尺度分析。
    """
    positions = np.asarray(positions, dtype=float)
    if len(positions) == 0:
        return np.asarray([], dtype=float)
    if len(positions) == 1:
        return np.asarray([0.0], dtype=float)
    steps = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(steps)])


def describe(values: Any) -> dict[str, float | int] | None:
    """统一统计描述函数。

    所有 RMSE/mean/median/std/min/max/p95/p99 都从这里产生，
    因此 ATE、RPE 和局部尺度的统计口径一致。

    来源对应：
    - RMSE 是 Sturm12/TUM 和 Zhang18 轨迹误差报告中最常用的汇总方式。
    - mean/median/std/min/max/p95/p99 是报告可读性扩展，用于定位尾部风险和最坏情况。
    """
    if values is None:
        return None
    arr = np.asarray(values, dtype=float).reshape(-1)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return None
    return {
        "count": int(len(arr)),
        "rmse": float(np.sqrt(np.mean(arr * arr))),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
    }


def rotation_errors(gt_rot: np.ndarray, est_rot: np.ndarray) -> np.ndarray:
    """逐帧姿态角误差，单位为弧度。

    输出会在 evaluate_trajectories() 中转成角度，进入 ate_orientation_deg。
    """
    err = np.einsum("nij,nkj->nik", gt_rot, est_rot)
    return np.asarray([rotation_angle(r) for r in err], dtype=float)


def rotation_angle(rot: np.ndarray) -> float:
    """旋转矩阵对应的最小旋转角。

    trace 公式：theta = acos((trace(R)-1)/2)。clip 用于抵抗浮点误差。
    """
    value = (float(np.trace(rot)) - 1.0) / 2.0
    return math.acos(float(np.clip(value, -1.0, 1.0)))


def yaw_from_rot(rotations: np.ndarray) -> np.ndarray:
    """从旋转矩阵提取 ZYX 约定下的 yaw，用于 ate_yaw_deg。"""
    return np.arctan2(rotations[:, 1, 0], rotations[:, 0, 0])


def euler_yaw_pitch_roll_from_matrix(rotations: np.ndarray) -> np.ndarray:
    """从旋转矩阵提取 ZYX yaw/pitch/roll，输出弧度。

    这和 euler_yaw_pitch_roll_to_matrix() 使用同一约定：
    R = Rz(yaw) * Ry(pitch) * Rx(roll)。
    输出列顺序固定为 yaw, pitch, roll，用于 per_pose 里的 6 张姿态时间序列图和 3 张姿态误差图。
    """
    rot = np.asarray(rotations, dtype=float)
    yaw = np.arctan2(rot[:, 1, 0], rot[:, 0, 0])
    pitch = np.arcsin(np.clip(-rot[:, 2, 0], -1.0, 1.0))
    roll = np.arctan2(rot[:, 2, 1], rot[:, 2, 2])
    return np.column_stack([yaw, pitch, roll])


def wrap_pi(values: np.ndarray) -> np.ndarray:
    """把角度差包到 [-pi, pi)，避免 359 度和 1 度被看成差 358 度。"""
    return (values + np.pi) % (2.0 * np.pi) - np.pi


def quaternion_to_matrix(qx: np.ndarray, qy: np.ndarray, qz: np.ndarray, qw: np.ndarray) -> np.ndarray:
    """四元数转旋转矩阵。

    TUM/EuRoC 等数据常用 qx qy qz qw。这里先归一化，避免数值误差导致旋转矩阵不正交。
    """
    q = np.column_stack([qx, qy, qz, qw]).astype(float)
    norms = np.linalg.norm(q, axis=1)
    valid = norms > 0
    q[valid] /= norms[valid, None]
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    n = len(q)
    rot = np.empty((n, 3, 3), dtype=float)
    rot[:, 0, 0] = 1 - 2 * (y * y + z * z)
    rot[:, 0, 1] = 2 * (x * y - z * w)
    rot[:, 0, 2] = 2 * (x * z + y * w)
    rot[:, 1, 0] = 2 * (x * y + z * w)
    rot[:, 1, 1] = 1 - 2 * (x * x + z * z)
    rot[:, 1, 2] = 2 * (y * z - x * w)
    rot[:, 2, 0] = 2 * (x * z - y * w)
    rot[:, 2, 1] = 2 * (y * z + x * w)
    rot[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return rot


def euler_yaw_pitch_roll_to_matrix(yaw: np.ndarray, pitch: np.ndarray, roll: np.ndarray) -> np.ndarray:
    """yaw-pitch-roll 欧拉角转旋转矩阵，使用 ZYX 顺序。

    代码意义：
    - 当前 SF 固定格式的 imu.txt、vloc.txt、vo.txt 都给 yaw/pitch/roll，而不是四元数。
    - 调用方必须先把输入角度统一成弧度；固定格式 parser 会在进入这里之前完成这一步。

    注意：
    - 这里默认列语义是 yaw, pitch, roll。
    - 如果外部数据实际是 roll/pitch/yaw 或坐标系相反，需要用姿态修正选项或调整输入约定。
    """
    yaw = np.asarray(yaw, dtype=float)
    pitch = np.asarray(pitch, dtype=float)
    roll = np.asarray(roll, dtype=float)

    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)

    rot = np.empty((len(yaw), 3, 3), dtype=float)
    rot[:, 0, 0] = cy * cp
    rot[:, 0, 1] = cy * sp * sr - sy * cr
    rot[:, 0, 2] = cy * sp * cr + sy * sr
    rot[:, 1, 0] = sy * cp
    rot[:, 1, 1] = sy * sp * sr + cy * cr
    rot[:, 1, 2] = sy * sp * cr - cy * sr
    rot[:, 2, 0] = -sp
    rot[:, 2, 1] = cp * sr
    rot[:, 2, 2] = cp * cr
    return rot


def matrix_to_quaternion(rot: np.ndarray) -> np.ndarray:
    """旋转矩阵转四元数。

    主要用于姿态插值：先把矩阵转四元数，再在插值流程里做 SLERP。
    """
    out = []
    for r in rot:
        tr = float(np.trace(r))
        if tr > 0:
            s = math.sqrt(tr + 1.0) * 2
            qw = 0.25 * s
            qx = (r[2, 1] - r[1, 2]) / s
            qy = (r[0, 2] - r[2, 0]) / s
            qz = (r[1, 0] - r[0, 1]) / s
        else:
            idx = int(np.argmax(np.diag(r)))
            if idx == 0:
                s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
                qw = (r[2, 1] - r[1, 2]) / s
                qx = 0.25 * s
                qy = (r[0, 1] + r[1, 0]) / s
                qz = (r[0, 2] + r[2, 0]) / s
            elif idx == 1:
                s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
                qw = (r[0, 2] - r[2, 0]) / s
                qx = (r[0, 1] + r[1, 0]) / s
                qy = 0.25 * s
                qz = (r[1, 2] + r[2, 1]) / s
            else:
                s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
                qw = (r[1, 0] - r[0, 1]) / s
                qx = (r[0, 2] + r[2, 0]) / s
                qy = (r[1, 2] + r[2, 1]) / s
                qz = 0.25 * s
        out.append([qx, qy, qz, qw])
    return np.asarray(out, dtype=float)

def normalize_rpe_delta_config(cfg: EvaluationConfig) -> dict[str, Any]:
    """把 RPE 的 UI/API 配置统一成 report 可读字段。

    rpe_delta_unit 只支持 frames 和 meters 两类：
    - frames: 按 evo consecutive-pairs 取 0->N、N->2N 这类非重叠 pair。
    - meters: 按对齐后的 estimate 累计路程每达到目标距离记录锚点，相邻锚点组成 pair。

    rpe_delta_value 是新参数；如果为空则退回旧的 rpe_delta_frames，保证旧配置还能复现。
    """
    unit_raw = str(cfg.rpe_delta_unit or "frames").strip().lower()
    if unit_raw == "frames":
        value = cfg.rpe_delta_value if cfg.rpe_delta_value is not None else cfg.rpe_delta_frames
        frames = max(1, int(round(float(value))))
        return {
            "delta_unit": "frames",
            "delta_value": float(frames),
            "delta_frames": int(frames),
            "delta_distance_m": None,
            "distance_tolerance_ratio": None,
            "distance_tolerance_percent": None,
        }
    if unit_raw == "meters":
        value = cfg.rpe_delta_value if cfg.rpe_delta_value is not None else cfg.rpe_delta_frames
        distance_m = float(value)
        if distance_m <= 0:
            raise ValueError("RPE distance delta must be positive")
        tolerance_ratio = max(0.0, float(cfg.rpe_distance_tolerance_ratio))
        return {
            "delta_unit": "meters",
            "delta_value": distance_m,
            "delta_frames": None,
            "delta_distance_m": distance_m,
            "distance_tolerance_ratio": tolerance_ratio,
            "distance_tolerance_percent": 100.0 * tolerance_ratio,
        }
    raise ValueError(f"Unknown rpe_delta_unit: {cfg.rpe_delta_unit}")


def normalize_scale_delta_config(cfg: EvaluationConfig) -> dict[str, Any]:
    """把尺度图的窗口配置统一成 report 可读字段。

    这个配置独立于 RPE，但单位和语义保持一致：
    - frames: 从每个起点 i 往后取固定帧数 j=i+N。
    - meters: 从每个起点 i 往后找 GT 路程 target*(1±tolerance) 内的候选终点。

    meters 模式和 RPE 的差别在于：尺度图选 GT 距离最接近目标距离的候选，
    不按误差最小选择，避免把尺度问题人为挑好。
    """
    unit_raw = str(cfg.scale_delta_unit or "frames").strip().lower()
    if unit_raw == "frames":
        value = cfg.scale_delta_value if cfg.scale_delta_value is not None else cfg.rpe_delta_frames
        frames = max(1, int(round(float(value))))
        return {
            "delta_unit": "frames",
            "delta_value": float(frames),
            "delta_frames": int(frames),
            "delta_distance_m": None,
            "distance_tolerance_ratio": None,
            "distance_tolerance_percent": None,
        }
    if unit_raw == "meters":
        value = cfg.scale_delta_value if cfg.scale_delta_value is not None else cfg.rpe_delta_frames
        distance_m = float(value)
        if distance_m <= 0:
            raise ValueError("Scale distance delta must be positive")
        tolerance_ratio = max(0.0, float(cfg.scale_distance_tolerance_ratio))
        return {
            "delta_unit": "meters",
            "delta_value": distance_m,
            "delta_frames": None,
            "delta_distance_m": distance_m,
            "distance_tolerance_ratio": tolerance_ratio,
            "distance_tolerance_percent": 100.0 * tolerance_ratio,
        }
    raise ValueError(f"Unknown scale_delta_unit: {cfg.scale_delta_unit}")


def rpe_frame_dataframe(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    stamps: np.ndarray,
    *,
    segment_id: int,
    match_indices: np.ndarray,
    delta: int,
    delta_value: float | None = None,
    delta_unit: str = "frames",
    distance_tolerance_ratio: float = 0.05,
) -> pd.DataFrame:
    """生成每个时间戳一行的 RPE 明细 sheet。

    RPE 比较的是 evo consecutive-pairs 选出的起点 i 和终点 j 的相对运动：
    - frames 模式：0->delta、delta->2*delta 这类非重叠固定帧 pair。
    - meters 模式：按对齐后的 estimate 路程累计，每达到 target_distance_m 记录一个锚点，
      相邻锚点组成非重叠 pair。
    - rpe_translation_m: 这段相对位移的误差。
    - rpe_rotation_deg: 这段相对旋转的误差；没有姿态输入时为 NaN。
    - rpe_available: 当前时间戳是否是 evo pair 的起点。

    没有被 evo 选为 pair 起点的时间戳仍保留一行，但 rpe_available=False。
    这样 Excel 里仍然能做到“每个时间戳都有一行”，同时 summary 和 evo 的 pair 统计口径一致。
    """
    stamps = np.asarray(stamps, dtype=float)
    match_indices = np.asarray(match_indices, dtype=int)
    n = len(stamps)
    unit_raw = str(delta_unit or "frames").strip().lower()
    if unit_raw == "frames":
        unit = "frames"
    elif unit_raw == "meters":
        unit = "meters"
    else:
        raise ValueError(f"Unknown rpe_delta_unit: {delta_unit}")
    delta_frames = max(1, int(round(float(delta_value)))) if unit == "frames" and delta_value is not None else max(1, int(delta))
    target_distance_m = float(delta_value) if unit == "meters" and delta_value is not None else float(delta)
    if unit == "meters" and target_distance_m <= 0:
        raise ValueError("RPE distance delta must be positive")
    tolerance_ratio = max(0.0, float(distance_tolerance_ratio))
    min_distance_m = target_distance_m * (1.0 - tolerance_ratio) if unit == "meters" else math.nan
    max_distance_m = target_distance_m * (1.0 + tolerance_ratio) if unit == "meters" else math.nan
    gt_distance = path_distance(gt_pos)

    rpe_translation = np.full(n, math.nan, dtype=float)
    rpe_rotation = np.full(n, math.nan, dtype=float)
    end_timestamp = np.full(n, math.nan, dtype=float)
    end_match_index = np.full(n, -1, dtype=int)
    time_delta = np.full(n, math.nan, dtype=float)
    actual_distance = np.full(n, math.nan, dtype=float)
    distance_error = np.full(n, math.nan, dtype=float)
    candidate_count = np.zeros(n, dtype=int)
    available = np.zeros(n, dtype=bool)

    # evo 的 filter_pairs_by_path(all_pairs=False) 口径：
    # 按累计路程每走过 delta 就记录一个起点 ids[k]，pair 是 (ids[k], ids[k+1])，
    # 这样每段路程至少为 delta，且不重叠。仅在 meters 模式下启用。
    # evo 使用 reference 轨迹（Sim3 对齐后的 est）计算累计路程，这里对齐 evo。
    evo_ids: list[int] = []
    if unit == "meters":
        evo_path = 0.0
        for k in range(1, n):
            evo_path += float(np.linalg.norm(est_pos[k] - est_pos[k - 1]))
            if evo_path >= target_distance_m:
                evo_ids.append(k)
                evo_path = 0.0
    evo_next_by_start = {
        int(evo_ids[idx]): int(evo_ids[idx + 1])
        for idx in range(len(evo_ids) - 1)
    } if len(evo_ids) > 1 else {}

    for i in range(n):
        if unit == "frames":
            # candidates = [i + delta_frames] if i + delta_frames < n else []
            # evo 的 filter_pairs_by_index(all_pairs=False) 口径：
            # 起点为 delta 的整数倍，终点 = 起点 + delta，非重叠覆盖。
            if i % delta_frames == 0 and i + delta_frames < n:
                candidates = [i + delta_frames]
            else:
                candidates = []

        else:
            # evo 的 filter_pairs_by_path(all_pairs=False) 口径：
            # 只有 i 出现在 evo_ids 里时才计算 RPE，候选终点固定为 evo_ids 的下一个。
            evo_next = evo_next_by_start.get(i)
            candidates = [evo_next] if evo_next is not None else []
            # 旧口径（tolerance 窗口内选最小误差候选），保留参考：
            # start_distance = gt_distance[i]
            # left = int(np.searchsorted(gt_distance, start_distance + min_distance_m, side="left"))
            # right = int(np.searchsorted(gt_distance, start_distance + max_distance_m, side="right"))
            # candidates = [idx for idx in range(max(i + 1, left), min(right, n))]
        candidate_count[i] = len(candidates)
        if not candidates:
            continue
        best: tuple[float, float, int, float | None] | None = None
        for j in candidates:
            trans_error, rot_error = relative_error(gt_pos, est_pos, gt_rot, est_rot, i, j)
            cur_distance = float(gt_distance[j] - gt_distance[i])
            cur_distance_error = abs(cur_distance - target_distance_m) if unit == "meters" else math.nan
            key = (float(trans_error), cur_distance_error if math.isfinite(cur_distance_error) else 0.0, int(j))
            if best is None or key < (best[0], best[1], best[2]):
                best = (float(trans_error), cur_distance_error, int(j), rot_error)
        if best is None:
            continue
        trans_error, cur_distance_error, j, rot_error = best
        rpe_translation[i] = trans_error
        if rot_error is not None:
            rpe_rotation[i] = math.degrees(rot_error)
        end_timestamp[i] = stamps[j]
        end_match_index[i] = int(match_indices[j]) if j < len(match_indices) else -1
        time_delta[i] = stamps[j] - stamps[i]
        actual_distance[i] = float(gt_distance[j] - gt_distance[i])
        distance_error[i] = cur_distance_error
        available[i] = True

    return pd.DataFrame(
        {
            "timestamp": stamps,
            "segment_id": np.full(n, int(segment_id), dtype=int),
            "match_index": match_indices if len(match_indices) == n else np.arange(n, dtype=int),
            "rpe_delta_unit": np.asarray([unit] * n, dtype=object),
            "rpe_delta_value": np.full(n, float(delta_frames if unit == "frames" else target_distance_m), dtype=float),
            "rpe_delta_frames": np.full(n, delta_frames if unit == "frames" else math.nan, dtype=float),
            "rpe_target_distance_m": np.full(n, target_distance_m if unit == "meters" else math.nan, dtype=float),
            "rpe_distance_tolerance_min_m": np.full(n, min_distance_m, dtype=float),
            "rpe_distance_tolerance_max_m": np.full(n, max_distance_m, dtype=float),
            "rpe_end_match_index": end_match_index,
            "rpe_end_timestamp": end_timestamp,
            "rpe_time_delta_s": time_delta,
            "rpe_actual_distance_m": actual_distance,
            "rpe_distance_error_m": distance_error,
            "rpe_candidate_count": candidate_count,
            "rpe_translation_m": rpe_translation,
            "rpe_rotation_deg": rpe_rotation,
            "rpe_available": available,
        }
    )


def scale_frame_dataframe(
    gt_pos: np.ndarray,
    est_pos_raw: np.ndarray,
    stamps: np.ndarray,
    *,
    segment_id: int,
    match_indices: np.ndarray,
    delta: int,
    delta_value: float | None = None,
    delta_unit: str = "frames",
    distance_tolerance_ratio: float = 0.05,
) -> pd.DataFrame:
    """生成每个起点时间戳对应的局部尺度明细。

    对每个起点 i 选择未来终点 j，计算该窗口内的路程比例：
    - local_scale_ratio_est_over_gt = VO_raw_window_length / GT_window_length。
    - local_sim3_scale = GT_window_length / VO_raw_window_length。
    - local_scale_drift_percent = (local_scale_ratio_est_over_gt - 1) * 100。

    注意这里使用未对齐的 estimate 位置 est_pos_raw。否则 Sim3 对齐后的轨迹已经被整体缩放，
    会掩盖原始 estimate 的局部尺度变化。
    """
    stamps = np.asarray(stamps, dtype=float)
    match_indices = np.asarray(match_indices, dtype=int)
    n = len(stamps)
    unit_raw = str(delta_unit or "frames").strip().lower()
    if unit_raw == "frames":
        unit = "frames"
    elif unit_raw == "meters":
        unit = "meters"
    else:
        raise ValueError(f"Unknown scale_delta_unit: {delta_unit}")
    delta_frames = max(1, int(round(float(delta_value)))) if unit == "frames" and delta_value is not None else max(1, int(delta))
    target_distance_m = float(delta_value) if unit == "meters" and delta_value is not None else float(delta)
    if unit == "meters" and target_distance_m <= 0:
        raise ValueError("Scale distance delta must be positive")
    tolerance_ratio = max(0.0, float(distance_tolerance_ratio))
    min_distance_m = target_distance_m * (1.0 - tolerance_ratio) if unit == "meters" else math.nan
    max_distance_m = target_distance_m * (1.0 + tolerance_ratio) if unit == "meters" else math.nan
    gt_distance = path_distance(gt_pos)
    est_distance = path_distance(est_pos_raw)

    local_scale_ratio = np.full(n, math.nan, dtype=float)
    local_sim3_scale = np.full(n, math.nan, dtype=float)
    local_scale_drift = np.full(n, math.nan, dtype=float)
    end_timestamp = np.full(n, math.nan, dtype=float)
    end_match_index = np.full(n, -1, dtype=int)
    time_delta = np.full(n, math.nan, dtype=float)
    actual_distance = np.full(n, math.nan, dtype=float)
    est_actual_distance = np.full(n, math.nan, dtype=float)
    distance_error = np.full(n, math.nan, dtype=float)
    candidate_count = np.zeros(n, dtype=int)
    available = np.zeros(n, dtype=bool)

    for i in range(n):
        if unit == "frames":
            candidates = [i + delta_frames] if i + delta_frames < n else []
        else:
            start_distance = gt_distance[i]
            left = int(np.searchsorted(gt_distance, start_distance + min_distance_m, side="left"))
            right = int(np.searchsorted(gt_distance, start_distance + max_distance_m, side="right"))
            candidates = [idx for idx in range(max(i + 1, left), min(right, n))]
        candidate_count[i] = len(candidates)
        if not candidates:
            continue
        if unit == "meters":
            j = min(candidates, key=lambda idx: (abs(float(gt_distance[idx] - gt_distance[i]) - target_distance_m), idx))
        else:
            j = candidates[0]
        gt_len = float(gt_distance[j] - gt_distance[i])
        est_len = float(est_distance[j] - est_distance[i])
        if gt_len <= 0 or est_len <= 0:
            continue
        ratio = est_len / gt_len
        local_scale_ratio[i] = ratio
        local_sim3_scale[i] = gt_len / est_len
        local_scale_drift[i] = (ratio - 1.0) * 100.0
        end_timestamp[i] = stamps[j]
        end_match_index[i] = int(match_indices[j]) if j < len(match_indices) else -1
        time_delta[i] = stamps[j] - stamps[i]
        actual_distance[i] = gt_len
        est_actual_distance[i] = est_len
        distance_error[i] = abs(gt_len - target_distance_m) if unit == "meters" else math.nan
        available[i] = True

    return pd.DataFrame(
        {
            "timestamp": stamps,
            "local_sim3_scale": local_sim3_scale,
            "local_scale_ratio_est_over_gt": local_scale_ratio,
            "local_scale_drift_percent": local_scale_drift,
            "scale_available": available,
            "segment_id": np.full(n, int(segment_id), dtype=int),
            "match_index": match_indices if len(match_indices) == n else np.arange(n, dtype=int),
            "scale_delta_unit": np.asarray([unit] * n, dtype=object),
            "scale_delta_value": np.full(n, float(delta_frames if unit == "frames" else target_distance_m), dtype=float),
            "scale_delta_frames": np.full(n, delta_frames if unit == "frames" else math.nan, dtype=float),
            "scale_target_distance_m": np.full(n, target_distance_m if unit == "meters" else math.nan, dtype=float),
            "scale_distance_tolerance_min_m": np.full(n, min_distance_m, dtype=float),
            "scale_distance_tolerance_max_m": np.full(n, max_distance_m, dtype=float),
            "scale_end_match_index": end_match_index,
            "scale_end_timestamp": end_timestamp,
            "scale_time_delta_s": time_delta,
            "scale_actual_distance_m": actual_distance,
            "scale_est_actual_distance_m": est_actual_distance,
            "scale_distance_error_m": distance_error,
            "scale_candidate_count": candidate_count,
        }
    )

def _alignment_dict(mode: str, scale: float, rotation: np.ndarray, translation: np.ndarray) -> dict[str, Any]:
    """统一构造 alignment 字段。

    rotation/translation 保留 ndarray，后续 _jsonable_value() 会在导出时转成 list。
    """
    return {
        "mode": mode,
        "scale": float(scale),
        "rotation": np.asarray(rotation, dtype=float),
        "translation": np.asarray(translation, dtype=float),
    }
