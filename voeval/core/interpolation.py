"""Trajectory interpolation and timestamp matching helpers."""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from ..io.formats import FIXED_TIME_OFFSET_S, VLOC_FIXED_MAX_INTERPOLATION_GAP_S
from ..io.trajectory import Trajectory
from .geometry import matrix_to_quaternion, quaternion_to_matrix

logger = logging.getLogger(__name__)

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
    }
    if ref_unique.rotations is None:
        info["rotation_interpolation_note"] = "rotation interpolation skipped: no reference rotation"
    if info["coverage_estimate_ratio"] < 0.8:
        info["warning"] = "low interpolate_gt coverage; check timestamp units, GT/estimate time ranges, time_offset_s, and max_interpolation_gap_s"
    if not len(est_indices):
        info["warning"] = "no estimate timestamp remains after interpolation filtering"
    elif len(est_indices) < 2:
        info["warning"] = "fewer than two estimate timestamps remain after interpolation filtering"
    logger.debug(
        "Found %d of max. %d possible matching timestamps between...\n\t%s\nand:\t%s\n..with max. interpolation gap: %.3g (s) and time offset: %.1f (s).",
        int(info["matches"]),
        int(info["estimate_count_input"]),
        reference.name,
        estimate.name,
        float(info["max_interpolation_gap_s"]),
        float(info["time_offset_s"]),
    )
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
    extras: dict[str, np.ndarray] = {}
    for key, value in traj.extras.items():
        arr = np.asarray(value)
        if arr.ndim == 0:
            extras[key] = arr
        elif len(arr) == len(traj.positions):
            extras[key] = arr[indices]
        else:
            raise ValueError(f"extras['{key}'] length must match trajectory length or be scalar")
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
    out = s0 * q0 + s1 * q1
    out_norm = np.linalg.norm(out)
    if out_norm == 0 or not np.isfinite(out_norm):
        raise ValueError("SLERP produced an invalid quaternion")
    return out / out_norm
