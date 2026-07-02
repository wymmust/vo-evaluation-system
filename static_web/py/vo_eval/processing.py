"""Evaluation orchestration for VO/VLOC reports."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .data_loader import (
    FIXED_DISCONTINUITY_STEP_M,
    FIXED_DISCONTINUITY_TIME_GAP_S,
    FIXED_TIME_OFFSET_S,
    SfVlocBundle,
    SfVoBundle,
    Trajectory,
    VLOC_FIXED_MAX_INTERPOLATION_GAP_S,
    VO_FIXED_MAX_INTERPOLATION_GAP_S,
    VO_MIN_VALID_SEGMENT_DURATION_S,
    VO_MIN_VALID_SEGMENT_FRAMES,
)
from .report import (
    _dataclass_to_jsonable,
    ate_frame_dataframe,
    build_trajectory_export_sheets,
    build_vloc_detail_report,
    build_vo_detail_report,
    tum_dataframe_from_arrays,
)
from .utils import (
    aggregate_alignment,
    alignment_export_columns,
    apply_alignment,
    apply_rotation_alignment,
    describe,
    detect_associated_discontinuities,
    euler_yaw_pitch_roll_from_matrix,
    identity_alignment,
    normalize_rpe_delta_config,
    normalize_scale_delta_config,
    path_distance,
    prepare_evaluation_trajectories,
    rpe_frame_dataframe,
    rotation_errors,
    scale_frame_dataframe,
    sim3_alignment,
    sf_nav_to_body_ned_trajectory,
    sf_nav_to_camera_trajectory,
    sf_vloc_to_body_ned_trajectory,
    subset_trajectory,
    vo_valid_segment_indices,
    wrap_pi,
    _gt_coverage_ratio,
)

@dataclass
class EvaluationConfig:
    """评估配置。

    当前前端只暴露少量必要参数：
    - sf_vloc: 页面不暴露对齐/时间同步/RPE 配置，固定 GT 插值到 VLOC 时间戳、最大 GT 插值间隔 1.0s、禁止外推、不做 Sim3。
    - sf_vo: 页面只保留 RPE 统计间隔和尺度图间隔，固定 GT 插值到 VO 时间戳、最大 GT 插值间隔 1.0s、禁止外推、按 reset 连续段分别 Sim3。

    配置与指标/流程的对应关系：
    - rpe_delta_value/rpe_delta_unit: 控制 VO 页面 RPE 按 evo consecutive-pairs 的帧数或距离间隔统计，对应 report["rpe_frame_delta"] 和 rpe_per_frame。
    - scale_delta_value/scale_delta_unit: 控制 VO 页面局部尺度图按帧数或按 GT 距离取窗口，对应 report["scale_frame_delta"] 和 scale_per_frame。
    """

    rpe_delta_frames: int = 1
    rpe_delta_value: float | None = None
    rpe_delta_unit: str = "frames"
    rpe_distance_tolerance_ratio: float = 0.05
    scale_delta_value: float | None = None
    scale_delta_unit: str = "frames"
    scale_distance_tolerance_ratio: float = 0.05

def evaluate_vloc_bundle(bundle: SfVlocBundle, config: EvaluationConfig | None = None) -> dict[str, Any]:
    """按需求文档固定流程评估 sf_vloc。

    这条入口不暴露对齐/姿态修正/时间同步模式选择：
    - 固定使用经纬高 -> NED；
    - 固定把 vloc 的 imu 位姿转到 body；
    - 固定按有效 vloc 时间戳插值 nav；
    - 固定最大 GT 插值间隔 1.0 s，超过直接丢弃该 vloc 帧；
    - 固定不外推、固定 time_offset=0、固定不做 Sim3/SE3 用户选择。
    """

    cfg = normalized_vloc_evaluation_config(config)
    nav_ned_body = sf_nav_to_body_ned_trajectory(bundle.nav, bundle.home_point)
    vloc_ned_body = sf_vloc_to_body_ned_trajectory(bundle.vloc, bundle.home_point, bundle.calibration)

    vloc_mode = np.asarray(vloc_ned_body.extras.get("vloc_mode", np.zeros(len(vloc_ned_body.positions))), dtype=float)
    valid_mode = np.isfinite(vloc_mode) & (vloc_mode > 1.0)
    dropped_invalid_mode = int(np.count_nonzero(~valid_mode))
    if not np.any(valid_mode):
        raise ValueError("No VLOC samples remain after filtering vloc_mode > 1")

    valid_indices = np.flatnonzero(valid_mode)
    vloc_valid = subset_trajectory(vloc_ned_body, valid_indices)
    report, nav_eval, vloc_eval = _evaluate_trajectories_core(nav_ned_body, vloc_valid, cfg)
    visual_segment_ids = (
        report["per_pose"]["visual_segment_id"].to_numpy(dtype=int)
        if "visual_segment_id" in report["per_pose"]
        else None
    )
    report["vloc_details"] = build_vloc_detail_report(
        nav_ned_body,
        vloc_valid,
        visual_segment_ids=visual_segment_ids,
        nav_eval=nav_eval,
        vloc_eval=vloc_eval,
    )
    report["inputs"]["entry_mode"] = "vloc"
    report["inputs"]["workflow"] = "sf_vloc"
    report["inputs"]["data_dir_name"] = bundle.data_dir.name or "data_dir"
    report["inputs"]["log_dir_name"] = bundle.log_dir.name or "log_dir"
    report["inputs"]["fixed_rules"] = {
        "alignment": "none",
        "association_mode": "interpolate_gt",
        "max_interpolation_gap_s": float(VLOC_FIXED_MAX_INTERPOLATION_GAP_S),
        "allow_extrapolation": False,
        "time_offset_s": float(FIXED_TIME_OFFSET_S),
    }
    report["association"]["dropped_est_invalid_mode"] = dropped_invalid_mode
    report["association"]["valid_est_after_mode_filter"] = int(len(vloc_valid.positions))
    report["summary"]["raw_est_poses"] = int(len(bundle.vloc.positions))
    for sheet_name in ("sim3_gt_tum", "sim3_vo_tum"):
        report["trajectory_exports"].pop(sheet_name, None)
    return report


def evaluate_vo_bundle(bundle: SfVoBundle, config: EvaluationConfig | None = None) -> dict[str, Any]:
    """按需求文档固定流程评估 sf_vo。

    这条入口和 VLOC 分开：
    - 固定读取 data_dir/imu.txt 和 log_dir/vo.txt；
    - 固定把 nav body 位姿通过 calib_raw.yaml 外参转到 cam；VO 保持在 cam frame；
    - 固定按 reset_count 连续段切分，丢弃小于 10 s 或小于 200 帧的短段；
    - 固定把 GT 插值到有效 VO 时间戳，最大 GT 插值间隔 1.0 s；
    - 固定按连续段分别做 Sim3，让每个 VO 重置后的局部坐标系单独对齐。
    """

    cfg = normalized_vo_evaluation_config(config)
    nav_cam = sf_nav_to_camera_trajectory(bundle.nav, bundle.calibration)
    vo_cam = bundle.vo

    valid_indices, valid_segment_ids, segment_filter = vo_valid_segment_indices(vo_cam)
    if len(valid_indices) < 2:
        raise ValueError("No VO reset segment remains after filtering duration >= 10s and frame count >= 200")

    vo_valid = subset_trajectory(vo_cam, valid_indices)
    vo_valid.extras["evaluation_segment_id"] = np.asarray(valid_segment_ids, dtype=int)
    report, nav_eval, vo_eval = _evaluate_trajectories_core(nav_cam, vo_valid, cfg)
    report["association"]["dropped_est_invalid_segment"] = int(segment_filter["dropped_pose_count"])
    report["association"]["valid_est_after_segment_filter"] = int(len(vo_valid.positions))
    report["association"]["vo_reset_segment_filter"] = segment_filter
    visual_segment_ids = (
        report["per_pose"]["visual_segment_id"].to_numpy(dtype=int)
        if "visual_segment_id" in report["per_pose"]
        else None
    )
    report["vo_details"] = build_vo_detail_report(
        nav_cam,
        vo_valid,
        report,
        visual_segment_ids=visual_segment_ids,
        nav_eval=nav_eval,
        vo_eval=vo_eval,
    )
    report["inputs"]["entry_mode"] = "vo"
    report["inputs"]["workflow"] = "sf_vo"
    report["inputs"]["data_dir_name"] = bundle.data_dir.name or "data_dir"
    report["inputs"]["log_dir_name"] = bundle.log_dir.name or "log_dir"
    report["inputs"]["fixed_rules"] = {
        "alignment": "sim3",
        "association_mode": "interpolate_gt",
        "max_interpolation_gap_s": float(VO_FIXED_MAX_INTERPOLATION_GAP_S),
        "allow_extrapolation": False,
        "time_offset_s": float(FIXED_TIME_OFFSET_S),
        "continuous_segment_policy": "segments",
        "min_valid_segment_duration_s": float(VO_MIN_VALID_SEGMENT_DURATION_S),
        "min_valid_segment_frames": int(VO_MIN_VALID_SEGMENT_FRAMES),
    }
    report["summary"]["raw_est_poses"] = int(len(bundle.vo.positions))
    return report

def normalized_vloc_evaluation_config(config: EvaluationConfig | None = None) -> EvaluationConfig:
    """把用户配置收敛成 sf_vloc 固定评估参数。"""
    return _copy_user_delta_config(config)


def normalized_vo_evaluation_config(config: EvaluationConfig | None = None) -> EvaluationConfig:
    """把用户配置收敛成 sf_vo 固定评估参数。

    VO 和 VLOC 的关键区别是：VO 是可能无尺度且会 reset 的轨迹，因此固定走 Sim3，
    并把 reset_count 形成的连续段交给 evaluate_trajectories() 逐段对齐。
    """
    return _copy_user_delta_config(config)


def _copy_user_delta_config(config: EvaluationConfig | None = None) -> EvaluationConfig:
    """只复制仍允许用户控制的 RPE/尺度窗口参数。"""
    base = config if config is not None else EvaluationConfig()
    return EvaluationConfig(
        rpe_delta_frames=base.rpe_delta_frames,
        rpe_delta_value=base.rpe_delta_value,
        rpe_delta_unit=base.rpe_delta_unit,
        rpe_distance_tolerance_ratio=base.rpe_distance_tolerance_ratio,
        scale_delta_value=base.scale_delta_value,
        scale_delta_unit=base.scale_delta_unit,
        scale_distance_tolerance_ratio=base.scale_distance_tolerance_ratio,
    )

def evaluate_trajectories(
    gt: Trajectory,
    est: Trajectory,
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    report, _gt_eval, _est_eval = _evaluate_trajectories_core(gt, est, config)
    return report


def _evaluate_trajectories_core(
    gt: Trajectory,
    est: Trajectory,
    config: EvaluationConfig | None = None,
) -> tuple[dict[str, Any], Trajectory, Trajectory]:
    """通用轨迹评估入口：输入 GT/reference 和 estimate，输出完整 report。

    这里是 VLOC 和 VO 都会复用的核心计算层：
    - VLOC 入口会先把 nav/vloc 都转成 body/NED，再固定不对齐地调用这里。
    - VO 入口会先把 nav/GT 转成 camera pose、按 reset_count 筛掉短段，再用分段 Sim3 调用这里。
    - TUM/测试入口也可以直接传两条 Trajectory 进来。

    流程对应页面上的“运行结果、可视化、明细与导出”：
    1. 时间同步 -> association / coverage。
    2. 大跳变诊断 -> discontinuities。
    3. 对每个选中连续段做对齐和误差计算。
    4. 汇总 ATE/RPE/局部尺度等指标。
    5. 返回 report dict，app.py 只负责展示这个 report。

    来源对应：
    - ATE/RPE 主干来自 Sturm12 和 Zhang18。
    - 长序列覆盖率和断点是 Schubert18/Delmerico18 场景下的工程扩展。
    """
    cfg = config or EvaluationConfig()
    is_vo_workflow = est.source_format == "sf_vo" or "evaluation_segment_id" in est.extras
    alignment_mode = "sim3" if is_vo_workflow else "none"
    segment_policy = "segments" if is_vo_workflow else "vo_timestamps"
    max_interpolation_gap_s = VO_FIXED_MAX_INTERPOLATION_GAP_S if is_vo_workflow else VLOC_FIXED_MAX_INTERPOLATION_GAP_S

    # 1. 时间同步：默认以 estimate 时间戳为评估基准，把 GT/reference 插值到 estimate 时刻。
    #    这样 GT=0.1/0.3/0.5、estimate=0.2/0.4/0.6 的相位错开数据不会被错误丢弃。
    original_gt = gt
    original_est = est
    gt, est, gt_idx, est_idx, assoc = prepare_evaluation_trajectories(
        original_gt,
        original_est,
        max_interpolation_gap_s=max_interpolation_gap_s,
    )
    if len(gt_idx) < 2:
        raise ValueError("Need at least two associated poses to evaluate a trajectory")

    # 2. 先在同步后的原始匹配序列上诊断断点/跳变。
    #    sf_vo 会把 reset_count 分段结果写入 evaluation_segment_id，因此 reset 边界也会被标为断点；
    #    sf_vloc 没有 VO reset 分段时，则主要看 GT/estimate 步长和时间 gap。
    original_match_count = int(len(gt_idx))
    original_gt_pos = gt.positions[gt_idx]
    original_est_pos = est.positions[est_idx]
    original_stamps = gt.stamps[gt_idx]
    forced_segment_ids = None
    if "evaluation_segment_id" in est.extras:
        candidate_segment_ids = np.asarray(est.extras["evaluation_segment_id"])
        if len(candidate_segment_ids) == len(est.positions):
            forced_segment_ids = candidate_segment_ids[est_idx]
    discontinuities_all = detect_associated_discontinuities(
        original_stamps,
        original_gt_pos,
        original_est_pos,
        step_threshold_m=FIXED_DISCONTINUITY_STEP_M,
        time_gap_threshold_s=FIXED_DISCONTINUITY_TIME_GAP_S,
        forced_segment_ids=forced_segment_ids,
    )
    valid_segments = [seg for seg in discontinuities_all["segments"] if int(seg.get("count", 0)) >= 2]
    eval_ranges = (
        valid_segments
        if is_vo_workflow
        else ([{"start": 0, "end": original_match_count, "count": original_match_count}] if original_match_count >= 2 else [])
    )
    if not eval_ranges:
        raise ValueError("No continuous segment contains at least two matched poses")
    # 这些列表会收集每个连续段的结果，最后统一 concat/describe。
    per_pose_frames: list[pd.DataFrame] = []
    pos_error_parts: list[np.ndarray] = []
    horizontal_error_parts: list[np.ndarray] = []
    vertical_error_signed_parts: list[np.ndarray] = []
    vertical_error_abs_parts: list[np.ndarray] = []
    orientation_error_parts: list[np.ndarray] = []
    yaw_error_signed_parts: list[np.ndarray] = []
    yaw_error_abs_parts: list[np.ndarray] = []
    rpe_trans_parts: list[np.ndarray] = []
    rpe_rot_parts: list[np.ndarray] = []
    used_gt_indices: list[np.ndarray] = []
    used_est_indices: list[np.ndarray] = []
    used_match_indices: list[np.ndarray] = []
    alignments: list[dict[str, Any]] = []
    sim3_gt_export_frames: list[pd.DataFrame] = []
    sim3_vo_export_frames: list[pd.DataFrame] = []
    rpe_frame_export_frames: list[pd.DataFrame] = []
    scale_frame_export_frames: list[pd.DataFrame] = []
    total_gt_path_m = 0.0
    total_raw_est_path_m = 0.0
    total_aligned_est_path_m = 0.0
    total_duration_s = 0.0
    distance_offset = 0.0

    for seg_id, seg in enumerate(eval_ranges):
        # 4. 根据连续段策略切片。
        #    sf_vloc 固定基本是一整段有效 vloc 时间戳；sf_vo 固定按 reset_count 连续段分别评估。
        start = int(seg["start"])
        end = int(seg["end"])
        cur_gt_idx = gt_idx[start:end]
        cur_est_idx = est_idx[start:end]
        if len(cur_gt_idx) < 2:
            continue

        gt_pos = gt.positions[cur_gt_idx]
        est_pos = est.positions[cur_est_idx]
        gt_rot = gt.rotations[cur_gt_idx] if gt.rotations is not None else None
        est_rot_raw = est.rotations[cur_est_idx] if est.rotations is not None else None
        est_rot = est_rot_raw
        stamps = gt.stamps[cur_gt_idx]

        # 5. 对齐 estimate 到 GT 坐标系。
        #    sf_vloc 固定 alignment=none，位置误差就是 nav-vloc 原始坐标差；
        #    sf_vo 固定 alignment=sim3，位置误差基于每段 Sim3 后的 aligned VO。
        alignment = sim3_alignment(gt_pos, est_pos) if is_vo_workflow else identity_alignment()
        alignment["segment_id"] = int(seg_id)
        alignment["start_match_index"] = start
        alignment["end_match_index"] = end
        alignments.append(alignment)

        est_pos_aligned = apply_alignment(est_pos, alignment)
        est_rot_aligned = apply_rotation_alignment(est_rot, alignment) if est_rot is not None else None

        if is_vo_workflow:
            # VO 导出固定保留一份 Sim3 中间轨迹；VLOC 有真实尺度，不生成 Sim3 sheet。
            sim3_extra = {
                "segment_id": np.full(len(stamps), int(seg_id), dtype=int),
                "match_index": np.arange(start, end, dtype=int),
            }
            sim3_extra.update(alignment_export_columns(alignment, len(stamps), "sim3"))
            sim3_gt_export_frames.append(tum_dataframe_from_arrays(stamps, gt_pos, gt_rot, extra=sim3_extra))
            sim3_vo_export_frames.append(tum_dataframe_from_arrays(stamps, est_pos_aligned, est_rot_aligned, extra=sim3_extra))

        # 6. ATE 逐帧误差：
        #    error_m -> ate_position_m，horizontal_error_m -> ate_horizontal_m，
        #    vertical_error_m -> ate_vertical_m。
        #    来源：error_m 直接对应 Sturm12/Zhang18 的 ATE；
        #    horizontal/vertical 是本系统面向无人机航线偏差和高度安全做的 ATE 分量扩展。
        errors = est_pos_aligned - gt_pos
        x_error_m = errors[:, 0]
        y_error_m = errors[:, 1]
        z_error_m = errors[:, 2]
        pos_error_m = np.linalg.norm(errors, axis=1)
        horizontal_error_m = np.linalg.norm(errors[:, :2], axis=1)
        vertical_error_signed_m = z_error_m
        vertical_error_abs_m = np.abs(vertical_error_signed_m)
        local_distance_m = path_distance(gt_pos)
        plot_distance_m = local_distance_m + distance_offset

        orientation_error_deg = None
        yaw_error_signed_deg = None
        yaw_error_abs_deg = None
        gt_ypr_deg = None
        est_ypr_deg = None
        ypr_error_signed_deg = None
        ypr_error_abs_deg = None
        if gt_rot is not None and est_rot_aligned is not None:
            # 7. 如果输入含姿态，额外统计 orientation/yaw ATE。
            #    来源：orientation_error_deg 来自 Zhang18/Schubert18 的 SE(3) 姿态误差语境；
            #    yaw_error_deg 是无人机航向分析扩展，不是 5 篇论文的独立排行榜指标。
            orientation_error_deg = np.degrees(rotation_errors(gt_rot, est_rot_aligned))
            gt_ypr = euler_yaw_pitch_roll_from_matrix(gt_rot)
            est_ypr = euler_yaw_pitch_roll_from_matrix(est_rot_aligned)
            ypr_error_signed = wrap_pi(est_ypr - gt_ypr)
            gt_ypr_deg = np.degrees(gt_ypr)
            est_ypr_deg = np.degrees(est_ypr)
            ypr_error_signed_deg = np.degrees(ypr_error_signed)
            ypr_error_abs_deg = np.abs(ypr_error_signed_deg)
            yaw_error_signed_deg = ypr_error_signed_deg[:, 0]
            yaw_error_abs_deg = np.abs(yaw_error_signed_deg)
            orientation_error_parts.append(orientation_error_deg)
            yaw_error_signed_parts.append(yaw_error_signed_deg)
            yaw_error_abs_parts.append(yaw_error_abs_deg)

        # 8. RPE 相对位姿误差，对应页面“RPE RMSE”和 Excel 的 rpe_per_frame。
        #    unit=frames/meters 都按 evo consecutive-pairs 取非重叠 pair；
        #    meters 模式用对齐后的 estimate 累计路程生成锚点，避免和 evo_rpe 的默认口径不一致。
        #    来源：Sturm12 RPE；evo 是该公式的常用开源实现口径。
        rpe_frame = rpe_frame_dataframe(
            gt_pos,
            est_pos_aligned,
            gt_rot,
            est_rot_aligned,
            stamps,
            segment_id=int(seg_id),
            match_indices=np.arange(start, end, dtype=int),
            delta=max(1, int(cfg.rpe_delta_frames)),
            delta_value=cfg.rpe_delta_value,
            delta_unit=cfg.rpe_delta_unit,
            distance_tolerance_ratio=cfg.rpe_distance_tolerance_ratio,
        )
        rpe_frame_export_frames.append(rpe_frame)
        rpe_valid = rpe_frame["rpe_available"].to_numpy(dtype=bool) if "rpe_available" in rpe_frame else np.asarray([], dtype=bool)
        rpe_trans = rpe_frame.loc[rpe_valid, "rpe_translation_m"].to_numpy(dtype=float) if len(rpe_frame) else np.asarray([], dtype=float)
        rpe_rot_deg = rpe_frame.loc[rpe_valid, "rpe_rotation_deg"].dropna().to_numpy(dtype=float) if len(rpe_frame) else np.asarray([], dtype=float)
        rpe_trans_parts.append(rpe_trans)
        if len(rpe_rot_deg):
            rpe_rot_parts.append(rpe_rot_deg)
        if is_vo_workflow:
            scale_frame = scale_frame_dataframe(
                gt_pos,
                est_pos,
                stamps,
                segment_id=int(seg_id),
                match_indices=np.arange(start, end, dtype=int),
                delta=max(1, int(cfg.rpe_delta_frames)),
                delta_value=cfg.scale_delta_value,
                delta_unit=cfg.scale_delta_unit,
                distance_tolerance_ratio=cfg.scale_distance_tolerance_ratio,
            )
            scale_frame_export_frames.append(scale_frame)

        # 10. per_pose 是每帧明细表，既用于误差曲线，也可导出 CSV。
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
                "x_error_m": x_error_m,
                "y_error_m": y_error_m,
                "z_error_m": z_error_m,
                "error_m": pos_error_m,
                "horizontal_error_m": horizontal_error_m,
                "vertical_error_signed_m": vertical_error_signed_m,
                "vertical_error_abs_m": vertical_error_abs_m,
                "vertical_error_m": vertical_error_abs_m,
            }
        )
        if orientation_error_deg is not None:
            frame["orientation_error_deg"] = orientation_error_deg
            frame["gt_yaw_deg"] = gt_ypr_deg[:, 0]
            frame["gt_pitch_deg"] = gt_ypr_deg[:, 1]
            frame["gt_roll_deg"] = gt_ypr_deg[:, 2]
            frame["est_yaw_aligned_deg"] = est_ypr_deg[:, 0]
            frame["est_pitch_aligned_deg"] = est_ypr_deg[:, 1]
            frame["est_roll_aligned_deg"] = est_ypr_deg[:, 2]
            frame["yaw_error_signed_deg"] = yaw_error_signed_deg
            frame["yaw_error_abs_deg"] = yaw_error_abs_deg
            frame["yaw_error_deg"] = yaw_error_abs_deg
            frame["pitch_error_signed_deg"] = ypr_error_signed_deg[:, 1]
            frame["pitch_error_abs_deg"] = ypr_error_abs_deg[:, 1]
            frame["roll_error_signed_deg"] = ypr_error_signed_deg[:, 2]
            frame["roll_error_abs_deg"] = ypr_error_abs_deg[:, 2]

        per_pose_frames.append(frame)
        pos_error_parts.append(pos_error_m)
        horizontal_error_parts.append(horizontal_error_m)
        vertical_error_signed_parts.append(vertical_error_signed_m)
        vertical_error_abs_parts.append(vertical_error_abs_m)
        used_gt_indices.append(cur_gt_idx)
        used_est_indices.append(cur_est_idx)
        used_match_indices.append(np.arange(start, end, dtype=int))

        # 11. summary 所需的总路程、raw estimate 路程、对齐后 estimate 路程、耗时等。
        #     来源：路程支撑长航程可用性统计；
        #     raw_path_scale_ratio 支撑 Zhang18 的尺度可观性判断。
        seg_gt_path = float(local_distance_m[-1])
        total_gt_path_m += seg_gt_path
        total_raw_est_path_m += float(path_distance(est_pos)[-1])
        total_aligned_est_path_m += float(path_distance(est_pos_aligned)[-1])
        total_duration_s += float(stamps[-1] - stamps[0]) if len(stamps) > 1 else 0.0
        distance_offset += seg_gt_path

    if not per_pose_frames:
        raise ValueError("No continuous segment contains at least two matched poses")

    per_pose = pd.concat(per_pose_frames, ignore_index=True)
    rpe_per_frame = pd.concat(rpe_frame_export_frames, ignore_index=True) if rpe_frame_export_frames else pd.DataFrame()
    scale_per_frame = pd.concat(scale_frame_export_frames, ignore_index=True) if scale_frame_export_frames else pd.DataFrame()
    # 12. 统计汇总：describe() 会统一给出 count/rmse/mean/median/std/min/max/p95/p99。
    pos_error_m = np.concatenate(pos_error_parts)
    horizontal_error_m = np.concatenate(horizontal_error_parts)
    vertical_error_signed_m = np.concatenate(vertical_error_signed_parts)
    vertical_error_abs_m = np.concatenate(vertical_error_abs_parts)
    orientation_error_deg = np.concatenate(orientation_error_parts) if orientation_error_parts else None
    yaw_error_signed_deg = np.concatenate(yaw_error_signed_parts) if yaw_error_signed_parts else None
    yaw_error_abs_deg = np.concatenate(yaw_error_abs_parts) if yaw_error_abs_parts else None
    rpe_trans = np.concatenate(rpe_trans_parts) if rpe_trans_parts else np.asarray([], dtype=float)
    rpe_rot_deg = np.concatenate(rpe_rot_parts) if rpe_rot_parts else np.asarray([], dtype=float)
    used_gt_idx = np.concatenate(used_gt_indices)
    used_est_idx = np.concatenate(used_est_indices)
    used_match_idx = np.concatenate(used_match_indices)
    visual_segment_ids = np.asarray(discontinuities_all.get("segment_ids", []), dtype=int)
    if len(visual_segment_ids) and len(used_match_idx) == len(per_pose):
        per_pose["visual_segment_id"] = visual_segment_ids[used_match_idx]
    else:
        per_pose["visual_segment_id"] = per_pose["segment_id"].to_numpy(dtype=int)
    alignment = aggregate_alignment(alignments, alignment_mode)
    ate_report = {
        "primary_label": f"{alignment_mode.upper()} ATE",
        "primary_position_m": describe(pos_error_m),
    }
    rpe_delta_info = normalize_rpe_delta_config(cfg)
    rpe = {
        **rpe_delta_info,
        "count": int(len(rpe_trans)),
        "translation_m": describe(rpe_trans),
        "rotation_deg": describe(rpe_rot_deg) if len(rpe_rot_deg) else None,
    }
    scale_frame_delta = None
    if is_vo_workflow:
        scale_valid = scale_per_frame["scale_available"].to_numpy(dtype=bool) if "scale_available" in scale_per_frame else np.asarray([], dtype=bool)
        local_sim3_scale = scale_per_frame.loc[scale_valid, "local_sim3_scale"].to_numpy(dtype=float) if len(scale_per_frame) else np.asarray([], dtype=float)
        local_scale_ratio = scale_per_frame.loc[scale_valid, "local_scale_ratio_est_over_gt"].to_numpy(dtype=float) if len(scale_per_frame) else np.asarray([], dtype=float)
        local_scale_drift = scale_per_frame.loc[scale_valid, "local_scale_drift_percent"].to_numpy(dtype=float) if len(scale_per_frame) else np.asarray([], dtype=float)
        scale_delta_info = normalize_scale_delta_config(cfg)
        scale_frame_delta = {
            **scale_delta_info,
            "count": int(len(local_sim3_scale)),
            "local_sim3_scale": describe(local_sim3_scale),
            "local_scale_ratio_est_over_gt": describe(local_scale_ratio),
            "local_scale_drift_percent": describe(local_scale_drift),
        }
    selected_segment = {
        "policy": segment_policy,
        "segments": [{"start_index": int(seg["start"]), "end_index": int(seg["end"]), "count": int(seg["count"])} for seg in eval_ranges],
        "selected_matches": int(len(used_gt_idx)),
        "dropped_matches": int(original_match_count - len(used_gt_idx)),
    }

    # 14. summary 是页面第一屏指标卡的主要来源。
    #     coverage/path 是物流无人机长航程可用性扩展；
    #     这些扩展的动机来自 Schubert18 长序列 VIO 和 Delmerico18 飞行机器人 benchmark。
    summary = {
        "gt_path_length_m": float(total_gt_path_m),
        "est_path_length_raw_m": float(total_raw_est_path_m),
        "est_path_length_aligned_m": float(total_aligned_est_path_m),
        "duration_s": float(total_duration_s),
        "matched_poses": int(len(used_gt_idx)),
        "original_matched_poses": original_match_count,
        "gt_poses": int(len(original_gt.positions)),
        "est_poses": int(len(original_est.positions)),
        "coverage_ratio": _gt_coverage_ratio(total_duration_s, original_gt),
        "gt_pose_coverage_ratio": _gt_coverage_ratio(total_duration_s, original_gt),
        "gt_time_coverage_ratio": float(total_duration_s / original_gt.duration_s) if original_gt.duration_s > 0 else 1.0,
        "est_pose_coverage_ratio": float(len(used_est_idx) / max(1, len(original_est.positions))),
        "raw_path_scale_ratio_est_over_gt": float(total_raw_est_path_m / total_gt_path_m) if total_gt_path_m > 0 else math.nan,
    }

    # 15. report 是唯一对外返回值。app.py 的所有图表/表格/下载都从这里取数据。
    #     新增 report 指标时，同步更新 METRIC_CODE_MAP 和 README 的指标-代码总表。
    trajectory_exports = build_trajectory_export_sheets(
        original_gt,
        original_est,
        gt,
        est,
        pd.concat(sim3_gt_export_frames, ignore_index=True) if sim3_gt_export_frames else pd.DataFrame(),
        pd.concat(sim3_vo_export_frames, ignore_index=True) if sim3_vo_export_frames else pd.DataFrame(),
        ate_frame_dataframe(per_pose),
        rpe_per_frame,
        scale_per_frame,
    )
    report = {
        "inputs": {
            "ground_truth": {"name": original_gt.name, "format": original_gt.source_format},
            "estimate": {"name": original_est.name, "format": original_est.source_format},
        },
        "config": _dataclass_to_jsonable(cfg),
        "association": assoc,
        "discontinuities": {
            "all_matches": discontinuities_all,
            "selected_segment": selected_segment,
        },
        "alignment": alignment,
        "summary": summary,
        "ate": ate_report,
        "ate_position_m": describe(pos_error_m),
        "ate_horizontal_m": describe(horizontal_error_m),
        "ate_vertical_m": describe(vertical_error_abs_m),
        "vertical_error_signed_m": describe(vertical_error_signed_m),
        "vertical_error_abs_m": describe(vertical_error_abs_m),
        "ate_orientation_deg": describe(orientation_error_deg) if orientation_error_deg is not None else None,
        "ate_yaw_deg": describe(yaw_error_abs_deg) if yaw_error_abs_deg is not None else None,
        "yaw_error_signed_deg": describe(yaw_error_signed_deg) if yaw_error_signed_deg is not None else None,
        "yaw_error_abs_deg": describe(yaw_error_abs_deg) if yaw_error_abs_deg is not None else None,
        "rpe_frame_delta": rpe,
        "per_pose": per_pose,
        "trajectory_exports": trajectory_exports,
    }
    if scale_frame_delta is not None:
        report["scale_frame_delta"] = scale_frame_delta
    return report, gt, est
