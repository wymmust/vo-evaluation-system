"""VO evaluation core.

这份文件负责所有“算法层”的工作，页面只是调用这里的函数。

代码分层：
1. 输入解析：把 TUM/KITTI/CSV/EuRoC/注释表头等轨迹文件读成 Trajectory。
2. 时间匹配：按 TUM RGB-D benchmark 的 greedy timestamp association 找 GT/VO 对应位姿。
3. 轨迹对齐：SE3、Sim3、首帧对齐或不对齐，把 VO 坐标系映射到 GT 坐标系。
4. 指标计算：ATE、RPE、长距离子轨迹误差、尺度漂移、覆盖率、发散、速度分箱、runtime。
5. 报告输出：把指标、每帧误差表、子轨迹表组织成 report dict，供 app.py 展示和导出。

指标与代码字段对应：
- 时间关联质量：associate_trajectories() -> report["association"]。
- 轨迹对齐尺度：compute_alignment()/aggregate_alignment() -> report["alignment"]。
- ATE 三维位置误差：pos_error_m -> report["ate_position_m"]。
- ATE 水平误差：horizontal_error_m -> report["ate_horizontal_m"]。
- ATE 垂直/高度误差：vertical_error_m -> report["ate_vertical_m"]。
- 姿态/yaw 误差：rotation_errors()/yaw_from_rot() -> ate_orientation_deg / ate_yaw_deg。
- RPE 固定帧间隔误差：rpe_error_arrays() -> report["rpe_frame_delta"]。
- KITTI/rpg 风格子轨迹误差：segment_errors() -> report["segment_errors"] 和 segment_records。
- 速度分箱误差：summarize_by_speed_bins() -> report["speed_bins"]。
- 终点漂移、覆盖率、路程、耗时、原始尺度比：summary dict。
- 发散检测：detect_divergence() -> report["divergence"]。
- VO 重置/大跳变诊断：detect_associated_discontinuities() -> report["discontinuities"]。
- runtime/资源统计：summarize_runtime() -> report["runtime"]。
"""

from __future__ import annotations

import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


@dataclass
class Trajectory:
    """统一后的轨迹数据结构。

    stamps: 秒级时间戳。所有 ns/us/ms 输入都会先归一化到秒。
    positions: N x 3 的位置，单位默认按输入理解为米。
    rotations: 可选 N x 3 x 3 旋转矩阵；没有姿态时仍可计算位置类指标。
    extras: runtime 或资源字段，例如 process_time_ms、fps、memory_mb。
    """

    name: str
    stamps: np.ndarray
    positions: np.ndarray
    rotations: np.ndarray | None = None
    extras: dict[str, np.ndarray] = field(default_factory=dict)
    source_format: str = "unknown"

    def __post_init__(self) -> None:
        self.stamps = np.asarray(self.stamps, dtype=float).reshape(-1)
        self.positions = np.asarray(self.positions, dtype=float)
        if self.positions.ndim != 2 or self.positions.shape[1] != 3:
            raise ValueError("positions must have shape (N, 3)")
        if len(self.stamps) != len(self.positions):
            raise ValueError("stamps and positions must have the same length")
        if self.rotations is not None:
            self.rotations = np.asarray(self.rotations, dtype=float)
            if self.rotations.shape != (len(self.positions), 3, 3):
                raise ValueError("rotations must have shape (N, 3, 3)")
        order = np.argsort(self.stamps)
        self.stamps = self.stamps[order]
        self.positions = self.positions[order]
        if self.rotations is not None:
            self.rotations = self.rotations[order]
        for key, value in list(self.extras.items()):
            arr = np.asarray(value)
            if len(arr) == len(order):
                self.extras[key] = arr[order]

    @property
    def has_rotation(self) -> bool:
        return self.rotations is not None

    @property
    def duration_s(self) -> float:
        if len(self.stamps) < 2:
            return 0.0
        return float(self.stamps[-1] - self.stamps[0])

    @property
    def path_length_m(self) -> float:
        return float(path_distance(self.positions)[-1]) if len(self.positions) else 0.0


@dataclass
class EvaluationConfig:
    """评估配置，基本都由 app.py 侧边栏控件传入。"""

    alignment: str = "se3"
    max_time_diff_s: float | None = 0.02
    time_offset_s: float = 0.0
    rpe_delta_frames: int = 1
    segment_lengths_m: tuple[float, ...] = (50, 100, 200, 500, 1000, 2000, 5000)
    max_segments_per_length: int = 10000
    segment_step_frames: int = 10
    max_segment_length_diff_ratio: float = 0.2
    continuous_segment_policy: str = "vo_timestamps"
    discontinuity_step_m: float = 100.0
    discontinuity_time_gap_s: float = 5.0
    divergence_abs_m: float = 10.0
    divergence_rel_percent: float = 2.0
    speed_bins_mps: tuple[float, ...] = (0, 5, 10, 15, 20, 30, math.inf)


# 下面这些候选列名用于 CSV/TSV/注释表头自动识别。
# 目的：不要求用户改原始数据列名，只要能识别到所需字段即可。
TIME_COLUMN_CANDIDATES = ["timestamp", "time", "t", "stamp", "sec", "seconds", "ts", "ts1", "frame", "index"]
X_COLUMN_CANDIDATES = [
    "x",
    "tx",
    "px",
    "p_x",
    "p_RS_R_x",
    "p_W_B_x",
    "p_W_C_x",
    "posx",
    "positionx",
    "translationx",
    "utmex",
    "east",
    "easting",
]
Y_COLUMN_CANDIDATES = [
    "y",
    "ty",
    "py",
    "p_y",
    "p_RS_R_y",
    "p_W_B_y",
    "p_W_C_y",
    "posy",
    "positiony",
    "translationy",
    "utmnorth",
    "north",
    "northing",
]
Z_COLUMN_CANDIDATES = [
    "z",
    "tz",
    "pz",
    "p_z",
    "p_RS_R_z",
    "p_W_B_z",
    "p_W_C_z",
    "posz",
    "positionz",
    "translationz",
    "alt",
    "altitude",
    "height",
    "up",
]
QX_COLUMN_CANDIDATES = ["qx", "q_x", "q_RS_x", "q_W_B_x", "q_B_W_x", "quatx", "quaternionx", "orientationx"]
QY_COLUMN_CANDIDATES = ["qy", "q_y", "q_RS_y", "q_W_B_y", "q_B_W_y", "quaty", "quaterniony", "orientationy"]
QZ_COLUMN_CANDIDATES = ["qz", "q_z", "q_RS_z", "q_W_B_z", "q_B_W_z", "quatz", "quaternionz", "orientationz"]
QW_COLUMN_CANDIDATES = ["qw", "q_w", "q_RS_w", "q_W_B_w", "q_B_W_w", "quatw", "quaternionw", "orientationw"]


def load_trajectory(source: str | bytes | Path | io.BytesIO, fmt: str = "auto", name: str | None = None) -> Trajectory:
    """Load a trajectory from TUM, KITTI, or CSV-like text.

    Supported common formats:
    - TUM: timestamp tx ty tz qx qy qz qw
    - KITTI odometry: 12 values per row, row-major 3x4 pose matrix
    - CSV/TSV/whitespace with columns for time, x/y/z and optional quaternion.
    """
    text, inferred_name = _read_text(source)
    return load_trajectory_from_text(text, fmt=fmt, name=name or inferred_name)


def load_trajectory_from_text(text: str, fmt: str = "auto", name: str = "trajectory") -> Trajectory:
    """把文本轨迹读成 Trajectory。

    这里是输入格式分发层：auto 会先看是否有注释表头，再按列数识别
    KITTI/TUM/XYZ/CSV。真正的列解析在 _parse_csv() 和 _parse_numeric_table()。
    """

    lines = _meaningful_lines(text)
    if not lines:
        raise ValueError(f"{name}: empty trajectory file")

    normalized_fmt = fmt.lower()
    if normalized_fmt == "auto":
        normalized_fmt = "csv" if _comment_header(text) else _detect_format(lines)

    if normalized_fmt == "csv":
        return _parse_csv(text, name)
    if normalized_fmt == "tum":
        return _parse_numeric_table(lines, name, "tum")
    if normalized_fmt == "kitti":
        return _parse_numeric_table(lines, name, "kitti")
    if normalized_fmt == "xyz":
        return _parse_numeric_table(lines, name, "xyz")
    raise ValueError(f"Unsupported trajectory format: {fmt}")


def evaluate_trajectories(
    gt: Trajectory,
    est: Trajectory,
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    """评估入口：输入 GT 和 VO 轨迹，输出完整 report。

    流程对应页面上的“运行结果、可视化、明细与导出”：
    1. 时间匹配 -> association / coverage。
    2. 大跳变诊断 -> discontinuities。
    3. 对每个选中连续段做对齐和误差计算。
    4. 汇总 ATE/RPE/子轨迹/速度分箱/runtime/发散等指标。
    5. 返回 report dict，app.py 只负责展示这个 report。
    """
    cfg = config or EvaluationConfig()

    # 1. 时间关联：只比较有对应时间戳的位姿。对 IMU 长时间日志场景，
    #    这一步会自然只取 VO 时间段附近的 GT/IMU 位姿。
    gt_idx, est_idx, assoc = associate_trajectories(gt, est, cfg.max_time_diff_s, cfg.time_offset_s)
    if len(gt_idx) < 2:
        raise ValueError("Need at least two associated poses to evaluate a trajectory")

    # 2. 先在原始匹配序列上诊断断点/跳变。默认策略 vo_timestamps 不丢点，
    #    断点只用于提示 VO 可能发生了重置或局部坐标系切换。
    original_match_count = int(len(gt_idx))
    original_gt_pos = gt.positions[gt_idx]
    original_est_pos = est.positions[est_idx]
    original_stamps = gt.stamps[gt_idx]
    discontinuities_all = detect_associated_discontinuities(
        original_stamps,
        original_gt_pos,
        original_est_pos,
        step_threshold_m=cfg.discontinuity_step_m,
        time_gap_threshold_s=cfg.discontinuity_time_gap_s,
    )
    eval_ranges = select_evaluation_segments(discontinuities_all["segments"], cfg.continuous_segment_policy, original_match_count)
    if not eval_ranges:
        raise ValueError("No continuous segment contains at least two matched poses")

    # 这些列表会收集每个连续段的结果，最后统一 concat/describe。
    per_pose_frames: list[pd.DataFrame] = []
    segment_record_frames: list[pd.DataFrame] = []
    pos_error_parts: list[np.ndarray] = []
    horizontal_error_parts: list[np.ndarray] = []
    vertical_error_parts: list[np.ndarray] = []
    orientation_error_parts: list[np.ndarray] = []
    yaw_error_parts: list[np.ndarray] = []
    rpe_trans_parts: list[np.ndarray] = []
    rpe_rot_parts: list[np.ndarray] = []
    used_gt_indices: list[np.ndarray] = []
    used_est_indices: list[np.ndarray] = []
    alignments: list[dict[str, Any]] = []
    total_gt_path_m = 0.0
    total_raw_est_path_m = 0.0
    total_aligned_est_path_m = 0.0
    total_duration_s = 0.0
    distance_offset = 0.0

    for seg_id, seg in enumerate(eval_ranges):
        # 3. 根据连续段策略切片；默认是一整段 VO 时间戳，segments 模式会分段评估。
        start = int(seg["start"])
        end = int(seg["end"])
        cur_gt_idx = gt_idx[start:end]
        cur_est_idx = est_idx[start:end]
        if len(cur_gt_idx) < 2:
            continue

        gt_pos = gt.positions[cur_gt_idx]
        est_pos = est.positions[cur_est_idx]
        gt_rot = gt.rotations[cur_gt_idx] if gt.rotations is not None else None
        est_rot = est.rotations[cur_est_idx] if est.rotations is not None else None
        stamps = gt.stamps[cur_gt_idx]

        # 4. 对齐 VO 到 GT 坐标系。alignment.scale 是页面“对齐尺度”。
        alignment = compute_alignment(gt_pos, est_pos, gt_rot, est_rot, mode=cfg.alignment)
        alignment["segment_id"] = int(seg_id)
        alignment["start_match_index"] = start
        alignment["end_match_index"] = end
        alignments.append(alignment)

        est_pos_aligned = apply_alignment(est_pos, alignment)
        est_rot_aligned = apply_rotation_alignment(est_rot, alignment) if est_rot is not None else None

        # 5. ATE 逐帧误差：
        #    error_m -> ate_position_m，horizontal_error_m -> ate_horizontal_m，
        #    vertical_error_m -> ate_vertical_m。
        errors = est_pos_aligned - gt_pos
        pos_error_m = np.linalg.norm(errors, axis=1)
        horizontal_error_m = np.linalg.norm(errors[:, :2], axis=1)
        vertical_error_m = errors[:, 2]
        local_distance_m = path_distance(gt_pos)
        plot_distance_m = local_distance_m + distance_offset

        orientation_error_deg = None
        yaw_error_deg = None
        if gt_rot is not None and est_rot_aligned is not None:
            # 6. 如果输入含姿态，额外统计 orientation/yaw ATE。
            orientation_error_deg = np.degrees(rotation_errors(gt_rot, est_rot_aligned))
            yaw_error_deg = np.degrees(wrap_pi(yaw_from_rot(est_rot_aligned) - yaw_from_rot(gt_rot)))
            orientation_error_parts.append(orientation_error_deg)
            yaw_error_parts.append(yaw_error_deg)

        # 7. RPE 固定帧间隔误差，对应页面“RPE RMSE”。
        rpe_trans, rpe_rot = rpe_error_arrays(
            gt_pos,
            est_pos_aligned,
            gt_rot,
            est_rot_aligned,
            delta=max(1, int(cfg.rpe_delta_frames)),
        )
        rpe_trans_parts.append(rpe_trans)
        if len(rpe_rot):
            rpe_rot_parts.append(np.degrees(rpe_rot))

        # 8. 长航程核心指标：按固定距离 L 抽子轨迹，统计漂移百分比、旋转误差和尺度漂移。
        cur_segments = segment_errors(
            gt_pos,
            est_pos_aligned,
            gt_rot,
            est_rot_aligned,
            stamps,
            lengths_m=cfg.segment_lengths_m,
            max_segments_per_length=cfg.max_segments_per_length,
            step_frames=cfg.segment_step_frames,
            max_length_diff_ratio=cfg.max_segment_length_diff_ratio,
        )
        if not cur_segments["records"].empty:
            rec = cur_segments["records"].copy()
            rec["segment_id"] = int(seg_id)
            segment_record_frames.append(rec)

        # 9. per_pose 是每帧明细表，既用于误差曲线，也可导出 CSV。
        frame = pd.DataFrame(
            {
                "timestamp": stamps,
                "segment_id": int(seg_id),
                "distance_m": plot_distance_m,
                "segment_distance_m": local_distance_m,
                "gt_x_m": gt_pos[:, 0],
                "gt_y_m": gt_pos[:, 1],
                "gt_z_m": gt_pos[:, 2],
                "est_x_aligned_m": est_pos_aligned[:, 0],
                "est_y_aligned_m": est_pos_aligned[:, 1],
                "est_z_aligned_m": est_pos_aligned[:, 2],
                "error_m": pos_error_m,
                "horizontal_error_m": horizontal_error_m,
                "vertical_error_m": vertical_error_m,
            }
        )
        if orientation_error_deg is not None:
            frame["orientation_error_deg"] = orientation_error_deg
            frame["yaw_error_deg"] = yaw_error_deg

        per_pose_frames.append(frame)
        pos_error_parts.append(pos_error_m)
        horizontal_error_parts.append(horizontal_error_m)
        vertical_error_parts.append(vertical_error_m)
        used_gt_indices.append(cur_gt_idx)
        used_est_indices.append(cur_est_idx)

        # 10. summary 所需的总路程、raw VO 路程、对齐后 VO 路程、耗时等。
        seg_gt_path = float(local_distance_m[-1])
        total_gt_path_m += seg_gt_path
        total_raw_est_path_m += float(path_distance(est_pos)[-1])
        total_aligned_est_path_m += float(path_distance(est_pos_aligned)[-1])
        total_duration_s += float(stamps[-1] - stamps[0]) if len(stamps) > 1 else 0.0
        distance_offset += seg_gt_path

    if not per_pose_frames:
        raise ValueError("No continuous segment contains at least two matched poses")

    per_pose = pd.concat(per_pose_frames, ignore_index=True)
    segment_records = pd.concat(segment_record_frames, ignore_index=True) if segment_record_frames else pd.DataFrame()
    # 11. 统计汇总：describe() 会统一给出 count/rmse/mean/median/std/min/max/p95/p99。
    segment_summary = summarize_segment_records(segment_records)
    speed_bins = summarize_by_speed_bins(segment_records, cfg.speed_bins_mps)
    pos_error_m = np.concatenate(pos_error_parts)
    horizontal_error_m = np.concatenate(horizontal_error_parts)
    vertical_error_m = np.concatenate(vertical_error_parts)
    orientation_error_deg = np.concatenate(orientation_error_parts) if orientation_error_parts else None
    yaw_error_deg = np.concatenate(yaw_error_parts) if yaw_error_parts else None
    rpe_trans = np.concatenate(rpe_trans_parts) if rpe_trans_parts else np.asarray([], dtype=float)
    rpe_rot_deg = np.concatenate(rpe_rot_parts) if rpe_rot_parts else np.asarray([], dtype=float)
    used_gt_idx = np.concatenate(used_gt_indices)
    used_est_idx = np.concatenate(used_est_indices)
    # 12. runtime 只统计 VO 输出里存在的资源字段；没有字段则返回 None。
    runtime = summarize_runtime(est, used_est_idx)
    divergence = detect_divergence(pos_error_m, per_pose["distance_m"].to_numpy(), cfg.divergence_abs_m, cfg.divergence_rel_percent, per_pose["timestamp"].to_numpy())
    alignment = aggregate_alignment(alignments, cfg.alignment)
    rpe = {
        "delta_frames": int(max(1, int(cfg.rpe_delta_frames))),
        "count": int(len(rpe_trans)),
        "translation_m": describe(rpe_trans),
        "rotation_deg": describe(rpe_rot_deg) if len(rpe_rot_deg) else None,
    }
    selected_segment = {
        "policy": cfg.continuous_segment_policy,
        "segments": [{"start_index": int(seg["start"]), "end_index": int(seg["end"]), "count": int(seg["count"])} for seg in eval_ranges],
        "selected_matches": int(len(used_gt_idx)),
        "dropped_matches": int(original_match_count - len(used_gt_idx)),
    }
    endpoint_error_m = float(pos_error_m[-1])

    # 13. summary 是页面第一屏指标卡的主要来源。
    summary = {
        "gt_path_length_m": float(total_gt_path_m),
        "est_path_length_raw_m": float(total_raw_est_path_m),
        "est_path_length_aligned_m": float(total_aligned_est_path_m),
        "duration_s": float(total_duration_s),
        "matched_poses": int(len(used_gt_idx)),
        "original_matched_poses": original_match_count,
        "gt_poses": int(len(gt.positions)),
        "est_poses": int(len(est.positions)),
        "coverage_ratio": float(len(used_gt_idx) / max(1, len(gt.positions))),
        "gt_pose_coverage_ratio": float(len(used_gt_idx) / max(1, len(gt.positions))),
        "est_pose_coverage_ratio": float(len(used_est_idx) / max(1, len(est.positions))),
        "endpoint_error_m": endpoint_error_m,
        "endpoint_error_percent_of_path": float(100.0 * endpoint_error_m / total_gt_path_m) if total_gt_path_m > 0 else math.nan,
        "raw_path_scale_ratio_est_over_gt": float(total_raw_est_path_m / total_gt_path_m) if total_gt_path_m > 0 else math.nan,
    }

    # 14. report 是唯一对外返回值。app.py 的所有图表/表格/下载都从这里取数据。
    report = {
        "inputs": {
            "ground_truth": {"name": gt.name, "format": gt.source_format},
            "estimate": {"name": est.name, "format": est.source_format},
        },
        "config": _dataclass_to_jsonable(cfg),
        "association": assoc,
        "discontinuities": {
            "all_matches": discontinuities_all,
            "used_matches": detect_associated_discontinuities(
                per_pose["timestamp"].to_numpy(),
                per_pose[["gt_x_m", "gt_y_m", "gt_z_m"]].to_numpy(),
                per_pose[["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"]].to_numpy(),
                step_threshold_m=cfg.discontinuity_step_m,
                time_gap_threshold_s=cfg.discontinuity_time_gap_s,
            ),
            "selected_segment": selected_segment,
        },
        "alignment": alignment,
        "summary": summary,
        "ate_position_m": describe(pos_error_m),
        "ate_horizontal_m": describe(horizontal_error_m),
        "ate_vertical_m": describe(vertical_error_m),
        "ate_orientation_deg": describe(orientation_error_deg) if orientation_error_deg is not None else None,
        "ate_yaw_deg": describe(yaw_error_deg) if yaw_error_deg is not None else None,
        "rpe_frame_delta": rpe,
        "segment_errors": segment_summary,
        "speed_bins": speed_bins,
        "runtime": runtime,
        "divergence": divergence,
        "per_pose": per_pose,
        "segment_records": segment_records,
    }
    return report


def associate_trajectories(
    gt: Trajectory,
    est: Trajectory,
    max_time_diff_s: float | None,
    time_offset_s: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Associate timestamps using the TUM RGB-D benchmark greedy matching rule.

    TUM's associate.py builds all pairs with abs(t_gt - (t_est + offset))
    below max_difference, sorts by time difference, then greedily keeps
    one-to-one matches.

    指标对应：
    - report["association"]["matches"]：成功匹配数量。
    - max_time_diff_s / mean_time_diff_s：时间关联质量。
    - summary 里的 GT/VO 覆盖率由这里返回的索引数量计算。
    """
    if len(gt.stamps) == len(est.stamps):
        diffs = np.abs(gt.stamps - (est.stamps + time_offset_s))
        if max_time_diff_s is None or np.nanmax(diffs) <= max_time_diff_s:
            idx = np.arange(len(gt.stamps), dtype=int)
            return idx, idx, {
                "method": "index_equal_length",
                "matches": int(len(idx)),
                "time_offset_s": float(time_offset_s),
                "max_time_diff_s": float(np.nanmax(diffs)) if len(diffs) else 0.0,
                "mean_time_diff_s": float(np.nanmean(diffs)) if len(diffs) else 0.0,
            }

    if max_time_diff_s is None:
        n = min(len(gt.stamps), len(est.stamps))
        idx = np.arange(n, dtype=int)
        return idx, idx, {"method": "index_truncated", "matches": int(n), "time_offset_s": float(time_offset_s)}

    potential_matches: list[tuple[float, int, int]] = []
    shifted_est_stamps = est.stamps + time_offset_s
    for gt_i, gt_t in enumerate(gt.stamps):
        left = int(np.searchsorted(shifted_est_stamps, gt_t - max_time_diff_s, side="left"))
        right = int(np.searchsorted(shifted_est_stamps, gt_t + max_time_diff_s, side="right"))
        for est_i in range(left, right):
            diff = abs(float(gt_t - shifted_est_stamps[est_i]))
            if diff < max_time_diff_s:
                potential_matches.append((diff, gt_i, est_i))
    potential_matches.sort(key=lambda item: item[0])

    gt_available = set(range(len(gt.stamps)))
    est_available = set(range(len(est.stamps)))
    matches: list[tuple[int, int, float]] = []
    for diff, gt_i, est_i in potential_matches:
        if gt_i in gt_available and est_i in est_available:
            gt_available.remove(gt_i)
            est_available.remove(est_i)
            matches.append((gt_i, est_i, diff))
    matches.sort(key=lambda item: item[0])

    gt_indices = [m[0] for m in matches]
    est_indices = [m[1] for m in matches]
    diffs = [m[2] for m in matches]

    if len(gt_indices) < 2 and len(gt.stamps) == len(est.stamps):
        idx = np.arange(len(gt.stamps), dtype=int)
        return idx, idx, {
            "method": "index_equal_length_fallback",
            "matches": int(len(idx)),
            "time_offset_s": float(time_offset_s),
            "warning": "timestamp association found fewer than two matches; fell back to equal-length index pairing",
        }

    return np.asarray(gt_indices, dtype=int), np.asarray(est_indices, dtype=int), {
        "method": "tum_greedy_timestamp",
        "matches": int(len(gt_indices)),
        "max_allowed_time_diff_s": float(max_time_diff_s),
        "time_offset_s": float(time_offset_s),
        "max_time_diff_s": float(np.max(diffs)) if diffs else math.nan,
        "mean_time_diff_s": float(np.mean(diffs)) if diffs else math.nan,
    }


def compute_alignment(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None = None,
    est_rot: np.ndarray | None = None,
    mode: str = "se3",
) -> dict[str, Any]:
    """计算 VO 到 GT 的轨迹对齐变换。

    指标对应：
    - SE3: 尺度固定为 1，适合双目/VIO/尺度已知。
    - Sim3: 同时估计尺度，适合单目 VO/尺度未知。
    - first_pose: 只把首帧对齐，用于观察误差随航程增长。
    - alignment["scale"] 最终显示为页面“对齐尺度”。
    """
    mode = mode.lower()
    if mode in {"none", "identity"}:
        return _alignment_dict(mode, 1.0, np.eye(3), np.zeros(3))
    if mode in {"first_pose", "first", "origin"}:
        scale = 1.0
        if gt_rot is not None and est_rot is not None:
            rot = gt_rot[0] @ est_rot[0].T
        else:
            rot = np.eye(3)
        trans = gt_pos[0] - scale * (rot @ est_pos[0])
        return _alignment_dict("first_pose", scale, rot, trans)
    if mode in {"se3", "rigid"}:
        scale, rot, trans = umeyama_alignment(est_pos, gt_pos, with_scale=False)
        return _alignment_dict("se3", scale, rot, trans)
    if mode in {"sim3", "similarity"}:
        scale, rot, trans = umeyama_alignment(est_pos, gt_pos, with_scale=True)
        return _alignment_dict("sim3", scale, rot, trans)
    raise ValueError(f"Unknown alignment mode: {mode}")


def umeyama_alignment(src: np.ndarray, dst: np.ndarray, with_scale: bool) -> tuple[float, np.ndarray, np.ndarray]:
    """Umeyama SVD 对齐。

    src 是 VO，dst 是 GT。with_scale=False 得到 SE3；with_scale=True 得到 Sim3。
    """
    src = np.asarray(src, dtype=float)
    dst = np.asarray(dst, dtype=float)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError("src and dst must have shape (N, 3)")
    if len(src) < 2:
        return 1.0, np.eye(3), dst[0] - src[0]

    mu_src = src.mean(axis=0)
    mu_dst = dst.mean(axis=0)
    src_centered = src - mu_src
    dst_centered = dst - mu_dst
    cov = (dst_centered.T @ src_centered) / len(src)
    u, singular_values, vt = np.linalg.svd(cov)
    sign = np.ones(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[-1] = -1
    s_mat = np.diag(sign)
    rot = u @ s_mat @ vt
    if with_scale:
        var_src = float(np.mean(np.sum(src_centered * src_centered, axis=1)))
        scale = float(np.sum(singular_values * sign) / var_src) if var_src > 0 else 1.0
    else:
        scale = 1.0
    trans = mu_dst - scale * (rot @ mu_src)
    return scale, rot, trans


def apply_alignment(positions: np.ndarray, alignment: dict[str, Any]) -> np.ndarray:
    scale = float(alignment["scale"])
    rot = np.asarray(alignment["rotation"], dtype=float)
    trans = np.asarray(alignment["translation"], dtype=float)
    return scale * (positions @ rot.T) + trans


def apply_rotation_alignment(rotations: np.ndarray | None, alignment: dict[str, Any]) -> np.ndarray | None:
    if rotations is None:
        return None
    rot = np.asarray(alignment["rotation"], dtype=float)
    return np.einsum("ij,njk->nik", rot, rotations)


def aggregate_alignment(alignments: list[dict[str, Any]], mode: str) -> dict[str, Any]:
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


def rpe_error_arrays(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    delta: int,
) -> tuple[np.ndarray, np.ndarray]:
    """固定帧间隔 RPE。

    对每个 i 取 j=i+delta，比较 GT 相对运动和 VO 相对运动。
    返回值对应 report["rpe_frame_delta"]["translation_m"] 和 rotation_deg。
    """
    n = len(gt_pos)
    if n <= delta:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    trans_errors: list[float] = []
    rot_errors: list[float] = []
    for i in range(n - delta):
        j = i + delta
        terr, rerr = relative_error(gt_pos, est_pos, gt_rot, est_rot, i, j)
        trans_errors.append(terr)
        if rerr is not None:
            rot_errors.append(rerr)
    return np.asarray(trans_errors, dtype=float), np.asarray(rot_errors, dtype=float)


def rpe_by_frame_delta(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    delta: int,
) -> dict[str, Any]:
    trans_errors, rot_errors = rpe_error_arrays(gt_pos, est_pos, gt_rot, est_rot, delta)
    return {
        "delta_frames": int(delta),
        "count": int(len(trans_errors)),
        "translation_m": describe(trans_errors),
        "rotation_deg": describe(np.degrees(rot_errors)) if len(rot_errors) else None,
    }


def segment_errors(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    stamps: np.ndarray,
    lengths_m: Iterable[float],
    max_segments_per_length: int = 10000,
    step_frames: int = 10,
    max_length_diff_ratio: float = 0.2,
) -> dict[str, Any]:
    """按距离的 KITTI/rpg 风格子轨迹误差。

    这是物流无人机长航程最重要的漂移指标之一：
    - length_m: 目标子轨迹长度 L。
    - translation_error_percent: 100 * 相对位移误差 / L。
    - rotation_error_deg_per_m: 姿态相对误差除以 L。
    - scale_ratio_est_over_gt: 该段 VO 路程 / GT 路程。
    - scale_drift_percent: (scale_ratio - 1) * 100。
    """
    cumulative = path_distance(gt_pos)
    total_length = cumulative[-1] if len(cumulative) else 0.0
    records: list[dict[str, float]] = []
    summaries: list[dict[str, Any]] = []

    for length in sorted({float(x) for x in lengths_m if float(x) > 0}):
        if length > total_length:
            continue
        step = max(1, int(step_frames))
        candidate_starts = np.arange(0, len(gt_pos) - 1, step, dtype=int)
        if len(candidate_starts) > max_segments_per_length:
            stride = int(math.ceil(len(candidate_starts) / max_segments_per_length))
            candidate_starts = candidate_starts[::stride]
        length_records: list[dict[str, float]] = []
        for i in candidate_starts:
            target = cumulative[i] + length
            j = find_segment_end(cumulative, i, target, length * max(0.0, max_length_diff_ratio))
            if j >= len(gt_pos) or j <= i:
                continue
            actual_length = float(cumulative[j] - cumulative[i])
            if actual_length <= 0:
                continue
            terr, rerr = relative_error(gt_pos, est_pos, gt_rot, est_rot, i, j)
            duration = float(stamps[j] - stamps[i]) if len(stamps) else math.nan
            speed = length / duration if duration > 0 else math.nan
            raw_est_segment = float(path_distance(est_pos[i : j + 1])[-1])
            scale_ratio = raw_est_segment / actual_length if actual_length > 0 else math.nan
            rec = {
                "length_m": float(length),
                "start_index": float(i),
                "end_index": float(j),
                "start_distance_m": float(cumulative[i]),
                "end_distance_m": float(cumulative[j]),
                "actual_length_m": actual_length,
                "length_diff_m": float(actual_length - length),
                "translation_error_m": float(terr),
                "translation_error_percent": float(100.0 * terr / length),
                "rotation_error_deg": float(np.degrees(rerr)) if rerr is not None else math.nan,
                "rotation_error_deg_per_m": float(np.degrees(rerr) / length) if rerr is not None else math.nan,
                "speed_mps": float(speed),
                "scale_ratio_est_over_gt": float(scale_ratio),
                "scale_drift_percent": float((scale_ratio - 1.0) * 100.0) if math.isfinite(scale_ratio) else math.nan,
            }
            length_records.append(rec)
            records.append(rec)
        if length_records:
            frame = pd.DataFrame(length_records)
            summaries.append(
                {
                    "length_m": float(length),
                    "count": int(len(frame)),
                    "translation_error_percent": describe(frame["translation_error_percent"].to_numpy()),
                    "translation_error_m": describe(frame["translation_error_m"].to_numpy()),
                    "rotation_error_deg_per_m": describe(frame["rotation_error_deg_per_m"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy()),
                    "scale_ratio_est_over_gt": describe(frame["scale_ratio_est_over_gt"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy()),
                    "scale_drift_percent": describe(frame["scale_drift_percent"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy()),
                }
            )
    records_frame = pd.DataFrame(records)
    return {"summary": summaries or summarize_segment_records(records_frame), "records": records_frame}


def summarize_segment_records(records: pd.DataFrame) -> list[dict[str, Any]]:
    if records.empty or "length_m" not in records:
        return []
    summaries: list[dict[str, Any]] = []
    for length, frame in records.groupby("length_m", sort=True):
        clean_rot = frame["rotation_error_deg_per_m"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy() if "rotation_error_deg_per_m" in frame else np.asarray([])
        clean_scale = frame["scale_ratio_est_over_gt"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy() if "scale_ratio_est_over_gt" in frame else np.asarray([])
        clean_scale_drift = frame["scale_drift_percent"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy() if "scale_drift_percent" in frame else np.asarray([])
        summaries.append(
            {
                "length_m": float(length),
                "count": int(len(frame)),
                "translation_error_percent": describe(frame["translation_error_percent"].to_numpy()),
                "translation_error_m": describe(frame["translation_error_m"].to_numpy()),
                "rotation_error_deg_per_m": describe(clean_rot),
                "scale_ratio_est_over_gt": describe(clean_scale),
                "scale_drift_percent": describe(clean_scale_drift),
            }
        )
    return summaries


def find_segment_end(cumulative: np.ndarray, start_idx: int, target_distance: float, max_diff: float) -> int:
    left = int(np.searchsorted(cumulative, target_distance, side="left"))
    candidates = [idx for idx in (left - 1, left, left + 1) if start_idx < idx < len(cumulative)]
    if not candidates:
        return -1
    best = min(candidates, key=lambda idx: abs(float(cumulative[idx] - target_distance)))
    if abs(float(cumulative[best] - target_distance)) > max_diff:
        return -1
    return best


def summarize_by_speed_bins(records: pd.DataFrame, bins: Iterable[float]) -> list[dict[str, Any]]:
    """速度分箱误差。

    segment_errors() 已经给每个子轨迹记录了 speed_mps，这里按速度区间聚合，
    用于观察高速/低速飞行时 VO 漂移是否不同。
    """
    if records.empty or "speed_mps" not in records:
        return []
    clean = records.replace([np.inf, -np.inf], np.nan).dropna(subset=["speed_mps", "translation_error_percent"])
    if clean.empty:
        return []
    bin_values = list(bins)
    if len(bin_values) < 2:
        return []
    labels: list[str] = []
    for left, right in zip(bin_values[:-1], bin_values[1:]):
        right_label = "inf" if math.isinf(right) else f"{right:g}"
        labels.append(f"{left:g}-{right_label}")
    clean = clean.copy()
    clean["speed_bin_mps"] = pd.cut(clean["speed_mps"], bins=bin_values, labels=labels, include_lowest=True, right=False)
    out: list[dict[str, Any]] = []
    for label, group in clean.groupby("speed_bin_mps", observed=True):
        out.append(
            {
                "speed_bin_mps": str(label),
                "count": int(len(group)),
                "translation_error_percent": describe(group["translation_error_percent"].to_numpy()),
                "rotation_error_deg_per_m": describe(group["rotation_error_deg_per_m"].dropna().to_numpy()),
            }
        )
    return out


def summarize_runtime(est: Trajectory, est_idx: np.ndarray) -> dict[str, Any] | None:
    """运行资源统计。

    如果 VO 输出 CSV 中包含 process_time_ms、fps、cpu_percent、memory_mb 等字段，
    这里会按匹配到的 VO 帧做 describe() 汇总，对应 report["runtime"]。
    """
    runtime_keys = {
        "process_time_ms",
        "processing_time_ms",
        "frame_time_ms",
        "latency_ms",
        "cpu_percent",
        "memory_percent",
        "memory_mb",
        "fps",
    }
    out: dict[str, Any] = {}
    for key, values in est.extras.items():
        if key not in runtime_keys:
            continue
        try:
            arr = np.asarray(values, dtype=float)[est_idx]
        except Exception:
            continue
        out[key] = describe(arr)
    return out or None


def detect_divergence(
    errors_m: np.ndarray,
    cumulative_m: np.ndarray,
    abs_threshold_m: float,
    rel_threshold_percent: float,
    stamps: np.ndarray,
) -> dict[str, Any]:
    """发散检测。

    阈值取 max(绝对阈值, 当前累计路程 * 相对阈值百分比)，
    第一个超过阈值的点就是页面提示的“首次发散”。
    """
    if len(errors_m) == 0:
        return {"diverged": False}
    dynamic_threshold = np.maximum(abs_threshold_m, cumulative_m * rel_threshold_percent / 100.0)
    exceeded = np.flatnonzero(errors_m > dynamic_threshold)
    result = {
        "diverged": bool(len(exceeded)),
        "abs_threshold_m": float(abs_threshold_m),
        "rel_threshold_percent": float(rel_threshold_percent),
        "max_error_m": float(np.nanmax(errors_m)),
        "final_error_m": float(errors_m[-1]),
    }
    if len(exceeded):
        idx = int(exceeded[0])
        result.update(
            {
                "first_divergence_index": idx,
                "first_divergence_time_s": float(stamps[idx]),
                "first_divergence_distance_m": float(cumulative_m[idx]),
                "first_divergence_error_m": float(errors_m[idx]),
                "threshold_at_divergence_m": float(dynamic_threshold[idx]),
            }
        )
    return result


def detect_associated_discontinuities(
    stamps: np.ndarray,
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    step_threshold_m: float,
    time_gap_threshold_s: float,
) -> dict[str, Any]:
    """断点/重置诊断。

    根据 GT 步长、VO 步长、时间间隔判断是否存在大跳变。
    默认评估策略不会丢弃这些点，只把信息放入 report["discontinuities"] 供诊断。
    """
    n = len(stamps)
    if n == 0:
        return {"segment_count": 0, "break_count": 0, "breaks": [], "segments": [], "segment_ids": np.asarray([], dtype=int)}
    if n == 1:
        return {"segment_count": 1, "break_count": 0, "breaks": [], "segments": [{"start": 0, "end": 1, "count": 1}], "segment_ids": np.zeros(1, dtype=int)}

    gt_steps = np.linalg.norm(np.diff(gt_pos, axis=0), axis=1)
    est_steps = np.linalg.norm(np.diff(est_pos, axis=0), axis=1)
    time_gaps = np.diff(stamps)
    break_after = np.zeros(n - 1, dtype=bool)
    breaks: list[dict[str, Any]] = []
    for idx, (gt_step, est_step, time_gap) in enumerate(zip(gt_steps, est_steps, time_gaps)):
        reasons: list[str] = []
        if step_threshold_m > 0 and gt_step > step_threshold_m:
            reasons.append("gt_step")
        if step_threshold_m > 0 and est_step > step_threshold_m:
            reasons.append("est_step")
        if time_gap_threshold_s > 0 and time_gap > time_gap_threshold_s:
            reasons.append("time_gap")
        if reasons:
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


def select_evaluation_segments(segments: list[dict[str, int]], policy: str, total_count: int) -> list[dict[str, int]]:
    valid_segments = [seg for seg in segments if int(seg.get("count", 0)) >= 2]
    if policy in {"vo_timestamps", "all"}:
        return [{"start": 0, "end": int(total_count), "count": int(total_count)}] if total_count >= 2 else []
    if policy == "segments":
        return valid_segments
    if policy == "longest":
        if not valid_segments:
            return []
        start, end = longest_segment_bounds(valid_segments)
        return [{"start": start, "end": end, "count": end - start}]
    raise ValueError(f"Unknown continuous_segment_policy: {policy}")


def segments_from_breaks(n: int, break_after: np.ndarray) -> list[dict[str, int]]:
    starts = [0]
    ends: list[int] = []
    for idx, is_break in enumerate(break_after):
        if is_break:
            ends.append(idx + 1)
            starts.append(idx + 1)
    ends.append(n)
    return [{"start": int(start), "end": int(end), "count": int(end - start)} for start, end in zip(starts, ends) if end > start]


def longest_segment_bounds(segments: list[dict[str, int]]) -> tuple[int, int]:
    if not segments:
        return 0, 0
    best = max(segments, key=lambda seg: seg["count"])
    return int(best["start"]), int(best["end"])


def relative_error(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    i: int,
    j: int,
) -> tuple[float, float | None]:
    """相对运动误差，RPE 和子轨迹误差共用这一段逻辑。

    有姿态时在各自起点坐标系下比较相对位移/相对旋转；
    无姿态时只比较世界系位移差。
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


def relative_pose(r_i: np.ndarray, p_i: np.ndarray, r_j: np.ndarray, p_j: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    r_rel = r_i.T @ r_j
    p_rel = r_i.T @ (p_j - p_i)
    return r_rel, p_rel


def path_distance(positions: np.ndarray) -> np.ndarray:
    """累计路程 D_i。

    用于 summary.gt_path_length_m、误差随路程图、子轨迹长度搜索和发散阈值。
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
    因此 ATE、RPE、子轨迹、速度分箱、runtime 的统计口径一致。
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
    err = np.einsum("nij,nkj->nik", gt_rot, est_rot)
    return np.asarray([rotation_angle(r) for r in err], dtype=float)


def rotation_angle(rot: np.ndarray) -> float:
    value = (float(np.trace(rot)) - 1.0) / 2.0
    return math.acos(float(np.clip(value, -1.0, 1.0)))


def yaw_from_rot(rotations: np.ndarray) -> np.ndarray:
    return np.arctan2(rotations[:, 1, 0], rotations[:, 0, 0])


def wrap_pi(values: np.ndarray) -> np.ndarray:
    return (values + np.pi) % (2.0 * np.pi) - np.pi


def quaternion_to_matrix(qx: np.ndarray, qy: np.ndarray, qz: np.ndarray, qw: np.ndarray) -> np.ndarray:
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
    """Convert yaw-pitch-roll angles to rotation matrices using ZYX order."""
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


def report_to_json(report: dict[str, Any]) -> str:
    return json.dumps(_jsonable_report(report), ensure_ascii=False, indent=2)


def _jsonable_report(report: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in report.items():
        if isinstance(value, pd.DataFrame):
            out[key] = value.to_dict(orient="records")
        elif isinstance(value, dict):
            out[key] = _jsonable_dict(value)
        elif isinstance(value, list):
            out[key] = [_jsonable_dict(x) if isinstance(x, dict) else x for x in value]
        else:
            out[key] = value
    return out


def _jsonable_dict(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, np.ndarray):
            out[key] = value.tolist()
        elif isinstance(value, np.generic):
            out[key] = value.item()
        elif isinstance(value, dict):
            out[key] = _jsonable_dict(value)
        elif isinstance(value, list):
            out[key] = [_jsonable_dict(x) if isinstance(x, dict) else x for x in value]
        else:
            out[key] = value
    return out


def _dataclass_to_jsonable(cfg: EvaluationConfig) -> dict[str, Any]:
    return {
        "alignment": cfg.alignment,
        "max_time_diff_s": cfg.max_time_diff_s,
        "time_offset_s": cfg.time_offset_s,
        "rpe_delta_frames": cfg.rpe_delta_frames,
        "segment_lengths_m": list(cfg.segment_lengths_m),
        "max_segments_per_length": cfg.max_segments_per_length,
        "segment_step_frames": cfg.segment_step_frames,
        "max_segment_length_diff_ratio": cfg.max_segment_length_diff_ratio,
        "continuous_segment_policy": cfg.continuous_segment_policy,
        "discontinuity_step_m": cfg.discontinuity_step_m,
        "discontinuity_time_gap_s": cfg.discontinuity_time_gap_s,
        "divergence_abs_m": cfg.divergence_abs_m,
        "divergence_rel_percent": cfg.divergence_rel_percent,
        "speed_bins_mps": list(cfg.speed_bins_mps),
    }


def _alignment_dict(mode: str, scale: float, rotation: np.ndarray, translation: np.ndarray) -> dict[str, Any]:
    return {
        "mode": mode,
        "scale": float(scale),
        "rotation": np.asarray(rotation, dtype=float),
        "translation": np.asarray(translation, dtype=float),
    }


def _read_text(source: str | bytes | Path | io.BytesIO) -> tuple[str, str]:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8", errors="replace"), source.name
    if isinstance(source, bytes):
        return source.decode("utf-8", errors="replace"), "uploaded"
    if hasattr(source, "read"):
        data = source.read()
        if isinstance(data, str):
            return data, getattr(source, "name", "uploaded")
        return data.decode("utf-8", errors="replace"), getattr(source, "name", "uploaded")
    path = Path(str(source))
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace"), path.name
    return str(source), "text"


def _meaningful_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _detect_format(lines: list[str]) -> str:
    first = lines[0]
    if re.search(r"[A-Za-z_]", first):
        return "csv"
    values = _parse_float_line(first)
    if len(values) == 12:
        return "kitti"
    if len(values) == 8:
        return "tum"
    if len(values) in {3, 4}:
        return "xyz"
    return "csv"


def _parse_float_line(line: str) -> list[float]:
    tokens = re.split(r"[\s,;]+", line.strip())
    values = []
    for token in tokens:
        if not token:
            continue
        values.append(float(token))
    return values


def _parse_numeric_table(lines: list[str], name: str, fmt: str) -> Trajectory:
    """解析无表头数字表。

    TUM: timestamp tx ty tz qx qy qz qw。
    KITTI: 每行 12 个数，表示 3x4 pose matrix。
    XYZ: x y z 或 timestamp x y z。
    TUM/XYZ 的 timestamp 会调用 _normalize_timestamps()，避免 ns 被当成秒。
    """
    rows = [_parse_float_line(line) for line in lines]
    width = max(len(row) for row in rows)
    if any(len(row) != width for row in rows):
        raise ValueError(f"{name}: inconsistent number of columns")
    data = np.asarray(rows, dtype=float)
    if fmt == "tum":
        if data.shape[1] < 8:
            raise ValueError(f"{name}: TUM format needs at least 8 columns")
        stamps = _normalize_timestamps(data[:, 0])
        positions = data[:, 1:4]
        rotations = quaternion_to_matrix(data[:, 4], data[:, 5], data[:, 6], data[:, 7])
        return Trajectory(name, stamps, positions, rotations, source_format="tum")
    if fmt == "kitti":
        if data.shape[1] != 12:
            raise ValueError(f"{name}: KITTI format needs exactly 12 columns")
        mats = data.reshape((-1, 3, 4))
        rotations = mats[:, :, :3]
        positions = mats[:, :, 3]
        stamps = np.arange(len(positions), dtype=float)
        return Trajectory(name, stamps, positions, rotations, source_format="kitti")
    if fmt == "xyz":
        if data.shape[1] == 3:
            stamps = np.arange(len(data), dtype=float)
            positions = data[:, 0:3]
        elif data.shape[1] >= 4:
            stamps = _normalize_timestamps(data[:, 0])
            positions = data[:, 1:4]
        else:
            raise ValueError(f"{name}: XYZ format needs 3 or 4 columns")
        return Trajectory(name, stamps, positions, None, source_format="xyz")
    raise ValueError(fmt)


def _parse_csv(text: str, name: str) -> Trajectory:
    """解析 CSV/TSV/空格表/注释表头。

    这里做三件事：
    1. 自动识别 time/x/y/z 列，兼容 EuRoC 的 p_RS_R_x/y/z。
    2. 自动识别四元数 qx/qy/qz/qw 或 yaw/pitch/roll。
    3. 抽取 runtime extras，供 summarize_runtime() 统计。
    """
    frame = _read_dataframe(text)
    if frame.empty:
        raise ValueError(f"{name}: empty CSV")
    angle_unit_hint = frame.attrs.get("angle_unit")
    timestamp_unit_hint = frame.attrs.get("timestamp_unit")
    normalized = {_normalize_col(col): col for col in frame.columns}
    numeric = frame.apply(pd.to_numeric, errors="coerce")

    time_col = _pick(normalized, TIME_COLUMN_CANDIDATES)
    x_col = _pick(normalized, X_COLUMN_CANDIDATES)
    y_col = _pick(normalized, Y_COLUMN_CANDIDATES)
    z_col = _pick(normalized, Z_COLUMN_CANDIDATES)

    if x_col is None or y_col is None or z_col is None:
        # 没有可靠列名时，退回到数字表解析，尽量支持老式无表头日志。
        numeric_values = numeric.dropna(axis=1, how="all").to_numpy(dtype=float)
        numeric_values = numeric_values[~np.isnan(numeric_values).all(axis=1)]
        if numeric_values.shape[1] == 12:
            return _parse_numeric_table([" ".join(map(str, row)) for row in numeric_values], name, "kitti")
        if numeric_values.shape[1] >= 8:
            return _parse_numeric_table([" ".join(map(str, row[:8])) for row in numeric_values], name, "tum")
        if numeric_values.shape[1] >= 3:
            return _parse_numeric_table([" ".join(map(str, row[:4])) for row in numeric_values], name, "xyz")
        raise ValueError(f"{name}: could not detect x/y/z columns")

    positions = numeric[[x_col, y_col, z_col]].to_numpy(dtype=float)
    if time_col is not None:
        # 所有时间戳在进入 Trajectory 前统一转成秒；
        # EuRoC 的 timestamp [ns] 和无表头 ns 时间戳都在这里处理。
        stamps = _normalize_timestamps(
            numeric[time_col].to_numpy(dtype=float),
            timestamp_unit_hint or _timestamp_unit_hint("", str(time_col)),
        )
    else:
        stamps = np.arange(len(frame), dtype=float)

    qx_col = _pick(normalized, QX_COLUMN_CANDIDATES)
    qy_col = _pick(normalized, QY_COLUMN_CANDIDATES)
    qz_col = _pick(normalized, QZ_COLUMN_CANDIDATES)
    qw_col = _pick(normalized, QW_COLUMN_CANDIDATES)
    rotations = None
    if all(col is not None for col in [qx_col, qy_col, qz_col, qw_col]):
        rotations = quaternion_to_matrix(
            numeric[qx_col].to_numpy(dtype=float),
            numeric[qy_col].to_numpy(dtype=float),
            numeric[qz_col].to_numpy(dtype=float),
            numeric[qw_col].to_numpy(dtype=float),
        )
    else:
        matrix_cols = [_pick(normalized, [f"r{i}{j}", f"rot{i}{j}", f"rotation{i}{j}"]) for i in range(3) for j in range(3)]
        if all(col is not None for col in matrix_cols):
            rotations = numeric[matrix_cols].to_numpy(dtype=float).reshape((-1, 3, 3))
        else:
            yaw_col = _pick_angle_col(normalized, "yaw", ["heading", "psi"])
            pitch_col = _pick_angle_col(normalized, "pitch", ["theta"])
            roll_col = _pick_angle_col(normalized, "roll", ["row", "phi"])
            if yaw_col is not None and pitch_col is not None and roll_col is not None:
                angles = numeric[[yaw_col, pitch_col, roll_col]].to_numpy(dtype=float)
                # 自动识别角度/弧度，兼容用户 IMU/VO 表头单位不同的情况。
                unit = _angle_unit_for_columns([yaw_col, pitch_col, roll_col], angle_unit_hint, angles)
                if unit == "deg":
                    angles = np.deg2rad(angles)
                rotations = euler_yaw_pitch_roll_to_matrix(angles[:, 0], angles[:, 1], angles[:, 2])

    valid = np.isfinite(stamps) & np.isfinite(positions).all(axis=1)
    if rotations is not None:
        valid &= np.isfinite(rotations.reshape(len(rotations), -1)).all(axis=1)
    stamps = stamps[valid]
    positions = positions[valid]
    if rotations is not None:
        rotations = rotations[valid]

    extras: dict[str, np.ndarray] = {}
    for col in frame.columns:
        key = _normalize_col(col)
        # extras 只收集 runtime/资源字段，不参与轨迹几何计算。
        if key in {
            "processtimems",
            "processingtimems",
            "frametimems",
            "latencyms",
            "cpupercent",
            "memorypercent",
            "memorymb",
            "fps",
        }:
            canonical = {
                "processtimems": "process_time_ms",
                "processingtimems": "processing_time_ms",
                "frametimems": "frame_time_ms",
                "latencyms": "latency_ms",
                "cpupercent": "cpu_percent",
                "memorypercent": "memory_percent",
                "memorymb": "memory_mb",
                "fps": "fps",
            }[key]
            extras[canonical] = numeric[col].to_numpy(dtype=float)[valid]

    return Trajectory(name, stamps, positions, rotations, extras=extras, source_format="csv")


def _read_dataframe(text: str) -> pd.DataFrame:
    """把文本读取为 DataFrame。

    优先处理 # 开头的注释表头，例如 "# ts x y z yaw pitch roll ..."；
    否则交给 pandas 尝试自动分隔符、空格分隔和逗号分隔。
    """
    header = _comment_header(text)
    if header:
        frame = _read_commented_header_table(text, header)
        frame.attrs["angle_unit"] = _angle_unit_hint(text)
        frame.attrs["timestamp_unit"] = _timestamp_unit_hint(text)
        return frame

    for kwargs in (
        {"sep": None, "engine": "python"},
        {"sep": r"\s+", "engine": "python"},
        {"sep": ",", "engine": "python"},
    ):
        try:
            frame = pd.read_csv(io.StringIO(text), comment="#", **kwargs)
            if len(frame.columns) > 1 or not frame.empty:
                frame.attrs["timestamp_unit"] = _timestamp_unit_hint(text)
                return frame
        except Exception:
            continue
    raise ValueError("Could not parse CSV-like trajectory")


def _comment_header(text: str) -> list[str] | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        content = stripped.lstrip("#").strip()
        tokens = _comment_header_tokens(content)
        normalized = {_normalize_col(token): token for token in tokens}
        if (
            len(tokens) >= 3
            and _pick(normalized, X_COLUMN_CANDIDATES) is not None
            and _pick(normalized, Y_COLUMN_CANDIDATES) is not None
            and _pick(normalized, Z_COLUMN_CANDIDATES) is not None
        ):
            return tokens
    return None


def _comment_header_tokens(content: str) -> list[str]:
    if "," in content:
        pieces = content.split(",")
    else:
        pieces = re.split(r"[\s,;]+", content)

    tokens: list[str] = []
    for piece in pieces:
        token = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", piece).strip()
        if not token:
            continue
        if not _is_column_token(token) and " " in token:
            token = token.split()[0]
        if _is_column_token(token):
            tokens.append(token)
    return tokens


def _read_commented_header_table(text: str, header: list[str]) -> pd.DataFrame:
    rows: list[list[float]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        data_part = stripped.split("#", 1)[0].strip()
        if not data_part:
            continue
        tokens = [token for token in re.split(r"[\s,;]+", data_part) if token]
        if len(tokens) < len(header):
            continue
        try:
            row = [float(token) for token in tokens[: len(header)]]
        except ValueError:
            continue
        if any(math.isnan(value) or math.isinf(value) for value in row):
            continue
        rows.append(row)
    return pd.DataFrame(rows, columns=header)


def _is_column_token(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token))


def _timestamp_unit_hint(text: str, column: str | None = None) -> str | None:
    """从表头/列名中提取时间单位提示：ns/us/ms/s。"""
    snippets: list[str] = []
    if column:
        snippets.append(str(column))
    for line in text.splitlines()[:50]:
        lower = line.lower()
        if any(marker in lower for marker in ["timestamp", "time", "stamp", "ts", "时间"]):
            snippets.append(line)

    scan = "\n".join(snippets).lower()
    if not scan:
        return None
    if re.search(r"\[\s*ns\s*\]|(?:timestamp|time|stamp|ts)[_\-\s]*ns\b|nanosecond|nanoseconds|纳秒", scan):
        return "ns"
    if re.search(r"\[\s*us\s*\]|\[\s*µs\s*\]|(?:timestamp|time|stamp|ts)[_\-\s]*(?:us|µs)\b|microsecond|microseconds|微秒", scan):
        return "us"
    if re.search(r"\[\s*ms\s*\]|(?:timestamp|time|stamp|ts)[_\-\s]*ms\b|millisecond|milliseconds|毫秒", scan):
        return "ms"
    if re.search(r"\[\s*s\s*\]|(?:timestamp|time|stamp|ts)[_\-\s]*(?:s|sec|secs|second|seconds)\b", scan):
        return "s"
    return None


def _normalize_timestamps(stamps: np.ndarray, unit_hint: str | None = None) -> np.ndarray:
    """时间戳统一换算到秒。

    这直接影响 duration_s、速度分箱、时间间隔断点和 TUM 时间关联阈值。
    """
    arr = np.asarray(stamps, dtype=float)
    unit = unit_hint or _infer_timestamp_unit(arr)
    factors = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}
    return arr * factors.get(unit or "s", 1.0)


def _infer_timestamp_unit(stamps: np.ndarray) -> str:
    """无表头时按时间戳数量级和相邻步长推断单位。"""
    finite = np.asarray(stamps, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) == 0:
        return "s"

    median_abs = float(np.nanmedian(np.abs(finite)))
    sorted_values = np.sort(finite)
    diffs = np.diff(sorted_values)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    median_step = float(np.nanmedian(diffs)) if len(diffs) else 0.0

    if median_abs >= 1e17 or median_step >= 1e7:
        return "ns"
    if median_abs >= 1e14 or median_step >= 1e4:
        return "us"
    if median_abs >= 1e11:
        return "ms"
    return "s"


def _angle_unit_hint(text: str) -> str | None:
    """从注释行推断 yaw/pitch/roll 是角度制还是弧度制。"""
    for line in text.splitlines():
        lower = line.lower()
        if any(word in lower for word in ["角度", "degree", "degrees", " deg"]):
            if any(axis in lower for axis in ["yaw", "pitch", "roll", "row", "heading"]):
                return "deg"
        if any(word in lower for word in ["弧度", "radian", "radians", " rad"]):
            if any(axis in lower for axis in ["yaw", "pitch", "roll", "row", "heading"]):
                return "rad"
    return None


def _pick_angle_col(normalized: dict[str, Any], base: str, aliases: list[str]) -> Any | None:
    candidates: list[str] = []
    for name in [base, *aliases]:
        candidates.extend(
            [
                name,
                f"{name}_rad",
                f"{name}_radian",
                f"{name}_radians",
                f"{name}_deg",
                f"{name}_degree",
                f"{name}_degrees",
            ]
        )
    return _pick(normalized, candidates)


def _angle_unit_for_columns(cols: list[Any], hint: str | None, values: np.ndarray) -> str:
    """确定欧拉角单位。

    优先级：列名 > 注释提示 > 数值范围启发式。
    """
    col_text = " ".join(str(col).lower() for col in cols)
    if any(marker in col_text for marker in ["deg", "degree", "degrees"]):
        return "deg"
    if any(marker in col_text for marker in ["rad", "radian", "radians"]):
        return "rad"
    if hint in {"deg", "rad"}:
        return hint
    finite = values[np.isfinite(values)]
    if len(finite) and np.nanmax(np.abs(finite)) > 2.0 * np.pi + 1e-6:
        return "deg"
    return "rad"


def _normalize_col(col: Any) -> str:
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", str(col).strip().lower())
    return re.sub(r"[^a-z0-9]", "", text)


def _pick(normalized: dict[str, Any], names: list[str]) -> Any | None:
    normalized_names = [_normalize_col(name) for name in names]
    for name in normalized_names:
        if name in normalized:
            return normalized[name]
    return None
