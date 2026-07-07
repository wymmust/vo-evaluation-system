"""JSON, Excel, and TUM export helpers."""

from __future__ import annotations

import io
import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from ..core.config import EvaluationConfig
from ..core.geometry import matrix_to_quaternion
from ..core.pipeline import TrajectoryEvaluationResult, evaluate_trajectory_result
from ..io.trajectory import Trajectory

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
def attach_trajectory_exports(evaluation: TrajectoryEvaluationResult) -> dict[str, Any]:
    """把 core 评估结果补成带 trajectory_exports 的完整 report。"""
    sim3_gt_tum = pd.concat(
        [
            tum_dataframe_from_arrays(segment.stamps, segment.gt_positions, segment.gt_rotations, extra=segment.extras)
            for segment in evaluation.aligned_segments
        ],
        ignore_index=True,
    ) if evaluation.aligned_segments else pd.DataFrame()
    sim3_vo_tum = pd.concat(
        [
            tum_dataframe_from_arrays(segment.stamps, segment.est_positions, segment.est_rotations, extra=segment.extras)
            for segment in evaluation.aligned_segments
        ],
        ignore_index=True,
    ) if evaluation.aligned_segments else pd.DataFrame()
    report = evaluation.report
    report["trajectory_exports"] = build_trajectory_export_sheets(
        evaluation.original_gt,
        evaluation.original_est,
        evaluation.gt_eval,
        evaluation.est_eval,
        sim3_gt_tum,
        sim3_vo_tum,
        ate_frame_dataframe(report.get("per_pose", pd.DataFrame())),
        evaluation.rpe_per_frame,
        evaluation.scale_per_frame,
    )
    return report
def evaluate_trajectories(
    gt: Trajectory,
    est: Trajectory,
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    """Public trajectory evaluator returning the full report/export payload."""
    return attach_trajectory_exports(evaluate_trajectory_result(gt, est, config))
def report_to_excel(report: dict[str, Any]) -> bytes:
    """把 report 中的轨迹和逐帧误差导出 sheet 写成一个 xlsx 工作簿。"""
    sheets = report.get("trajectory_exports") or {}
    output = io.BytesIO()
    used_names: set[str] = set()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            safe_name = _unique_excel_sheet_name(str(name), used_names)
            if isinstance(frame, pd.DataFrame):
                frame.to_excel(writer, sheet_name=safe_name, index=False)
            else:
                pd.DataFrame(frame).to_excel(writer, sheet_name=safe_name, index=False)
    return output.getvalue()
def _unique_excel_sheet_name(name: str, used_names: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "_", name).strip() or "sheet"
    base = base[:31]
    candidate = base
    suffix = 1
    while candidate in used_names:
        marker = f"_{suffix}"
        candidate = f"{base[: 31 - len(marker)]}{marker}"
        suffix += 1
    used_names.add(candidate)
    return candidate
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
def evaluation_config_to_jsonable(cfg: EvaluationConfig) -> dict[str, Any]:
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
