"""VO reset segment filtering and discontinuity diagnostics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..io.formats import FIXED_DISCONTINUITY_STEP_M, FIXED_DISCONTINUITY_TIME_GAP_S, VO_MIN_VALID_SEGMENT_DURATION_S, VO_MIN_VALID_SEGMENT_FRAMES
from ..io.trajectory import Trajectory
from .interpolation import trajectory_extra_or_nan

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
