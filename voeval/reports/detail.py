"""VLOC/VO detail report builders."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ..core.config import EvaluationConfig
from ..core.pipeline import evaluate_vloc_bundle_core, evaluate_vo_bundle_core
from ..io.bundle import SfVlocBundle, SfVoBundle
from ..core.statistics import path_distance
from ..io.formats import FIXED_TIME_OFFSET_S
from ..io.trajectory import Trajectory
from .comparison import vloc_comparison_frame, vloc_est_status_frame, vloc_nav_status_frame, vo_comparison_frame, vo_est_status_frame
from .export import attach_trajectory_exports

def evaluate_vloc_bundle(bundle: SfVlocBundle, config: EvaluationConfig | None = None) -> dict[str, Any]:
    """Run the VLOC workflow and attach report-layer details and exports."""
    result = evaluate_vloc_bundle_core(bundle, config)
    report = attach_trajectory_exports(result.trajectory)
    visual_segment_ids = (
        report["per_pose"]["visual_segment_id"].to_numpy(dtype=int)
        if "visual_segment_id" in report["per_pose"]
        else None
    )
    report["vloc_details"] = build_vloc_detail_report(
        result.reference,
        result.estimate,
        visual_segment_ids=visual_segment_ids,
        nav_eval=result.reference_eval,
        vloc_eval=result.estimate_eval,
    )
    return report
def evaluate_vo_bundle(bundle: SfVoBundle, config: EvaluationConfig | None = None) -> dict[str, Any]:
    """Run the VO workflow and attach report-layer details and exports."""
    result = evaluate_vo_bundle_core(bundle, config)
    report = attach_trajectory_exports(result.trajectory)
    visual_segment_ids = (
        report["per_pose"]["visual_segment_id"].to_numpy(dtype=int)
        if "visual_segment_id" in report["per_pose"]
        else None
    )
    report["vo_details"] = build_vo_detail_report(
        result.reference,
        result.estimate,
        report,
        visual_segment_ids=visual_segment_ids,
        nav_eval=result.reference_eval,
        vo_aligned=result.estimate_eval,
    )
    return report

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
    vo_aligned: Trajectory,
    visual_segment_ids: np.ndarray | None = None,
) -> dict[str, Any]:
    """构造 VO 页面专用明细。

    comparison 使用通用 evaluator 已经算好的 Sim3 后 per_pose 数据：
    这样页面看到的 VO 轨迹、ATE/RPE 和导出结果使用同一套对齐结果。
    """
    timestamps = vo_aligned.stamps
    target_stamps = np.asarray(vo_aligned.extras.get("target_stamp", timestamps + FIXED_TIME_OFFSET_S), dtype=float)
    if len(timestamps) == 0:
        empty = pd.DataFrame()
        return {"summary": {}, "comparison": empty, "nav_status": empty, "vo_status": empty, "segment_filter": {}}

    nav_status = vloc_nav_status_frame(nav, target_stamps, timestamps)
    vo_status = vo_est_status_frame(vo_aligned)
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
