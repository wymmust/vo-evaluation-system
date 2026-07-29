"""Metric summaries and per-frame RPE/scale tables."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .config import EvaluationConfig
from .errors import relative_error

FIXED_DISTANCE_TOLERANCE_RATIO = 0.05

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
    std 使用 numpy 默认的总体标准差 ddof=0。

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
def normalize_delta_config(cfg: EvaluationConfig) -> dict[str, Any]:
    """把 UI/API 配置统一成 report 可读字段。

    delta_unit 只支持 frames 和 meters 两类：
    - frames: 按帧数间隔取样。
    - meters: 按距离间隔取样。

    delta_value 是唯一的间隔数值入口；单位由 delta_unit 决定。
    """
    unit_raw = str(cfg.delta_unit or "frames").strip().lower()
    if unit_raw == "frames":
        frames = max(1, int(round(float(cfg.delta_value))))
        return {
            "delta_unit": "frames",
            "delta_value": float(frames),
            "delta_frames": int(frames),
            "delta_distance_m": None,
            "distance_tolerance_ratio": None,
            "distance_tolerance_percent": None,
        }
    if unit_raw == "meters":
        distance_m = float(cfg.delta_value)
        if distance_m <= 0:
            raise ValueError("Distance delta must be positive")
        return {
            "delta_unit": "meters",
            "delta_value": distance_m,
            "delta_frames": None,
            "delta_distance_m": distance_m,
            "distance_tolerance_ratio": FIXED_DISTANCE_TOLERANCE_RATIO,
            "distance_tolerance_percent": 100.0 * FIXED_DISTANCE_TOLERANCE_RATIO,
        }
    raise ValueError(f"Unknown delta_unit: {cfg.delta_unit}")
def rpe_frame_dataframe(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    stamps: np.ndarray,
    *,
    segment_id: int,
    match_indices: np.ndarray,
    delta_value: float,
    delta_unit: str = "frames",
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
        raise ValueError(f"Unknown delta_unit: {delta_unit}")
    delta_frames = max(1, int(round(float(delta_value)))) if unit == "frames" else 1
    target_distance_m = float(delta_value) if unit == "meters" else math.nan
    if unit == "meters" and target_distance_m <= 0:
        raise ValueError("RPE distance delta must be positive")
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
    delta_value: float,
    delta_unit: str = "frames",
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
        raise ValueError(f"Unknown delta_unit: {delta_unit}")
    delta_frames = max(1, int(round(float(delta_value)))) if unit == "frames" else 1
    target_distance_m = float(delta_value) if unit == "meters" else math.nan
    if unit == "meters" and target_distance_m <= 0:
        raise ValueError("Scale distance delta must be positive")
    tolerance_ratio = FIXED_DISTANCE_TOLERANCE_RATIO
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
