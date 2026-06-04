"""Streamlit UI for the VO evaluation system.

这个文件只负责交互和展示：
1. 侧边栏收集评估配置。
2. 上传 GT/VO 文件并交给 vo_eval.evaluator 解析和计算。
3. 把 report 中的指标映射到页面指标卡、Plotly 图表和下载文件。

核心计算不在这里，核心指标都由 vo_eval/evaluator.py 产生。
"""

from __future__ import annotations

import html
import importlib
import math
import re
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import vo_eval.evaluator as vo_evaluator


FORMAT_OPTIONS = {
    "自动识别": "auto",
    "TUM: timestamp tx ty tz qx qy qz qw": "tum",
    "KITTI: 3x4 pose matrix": "kitti",
    "CSV/TSV 表格": "csv",
    "XYZ: [t] x y z": "xyz",
}

ALIGNMENT_OPTIONS = {
    "SE3 刚体对齐（双目/VIO/尺度已知推荐）": "se3",
    "Sim3 相似变换（单目 VO/尺度未知）": "sim3",
    "首帧对齐（看漂移随距离增长）": "first_pose",
    "不对齐": "none",
}

ORIENTATION_CORRECTION_OPTIONS = {
    "自动选择最优姿态修正（推荐）": "auto",
    "不修正": "none",
    "忽略姿态，只评估位置": "ignore",
    "取逆 R^T": "inverse",
    "右乘 Rz(180) camera/body 外参": "rz180_right",
    "左乘 Rz(180)": "rz180_left",
    "右乘 Rx(180)": "rx180_right",
    "右乘 Ry(180)": "ry180_right",
    "ENU/NED 左乘": "enu_ned_left",
    "ENU/NED 右乘": "enu_ned_right",
    "ENU/NED 两侧变换": "enu_ned_both",
}

SEGMENT_POLICY_OPTIONS = {
    "按VO时间戳统一评估（推荐）": "vo_timestamps",
    "按VO连续段逐段评估": "segments",
    "只评估最长连续段": "longest",
}

ASSOCIATION_OPTIONS = {
    "GT插值到VO时间戳（推荐）": "interpolate_gt",
    "TUM最近邻时间戳匹配": "nearest",
    "按索引匹配（不按时间）": "index",
}

INTERPOLATION_GAP_PRESETS = {
    "20 Hz reference（0.15 s 推荐）": 0.15,
    "100 Hz reference（0.05 s）": 0.05,
    "50 Hz reference（0.08 s）": 0.08,
    "10 Hz reference（0.30 s）": 0.30,
    "不限制 GT gap": -1.0,
    "自定义": 0.15,
}


def main() -> None:
    """页面入口：上传文件 -> 构造配置 -> 调用 evaluator -> 展示 report。"""
    st.set_page_config(page_title="VO 评估系统", layout="wide")
    st.title("VO 评估系统")

    with st.sidebar:
        # 这些控件直接映射到 EvaluationConfig：
        # alignment -> 对齐方式；association/max_time_diff/time_offset -> 时间同步；
        # rpe_delta -> RPE；segment_* -> 长航程子轨迹误差；
        # divergence_* -> 发散检测阈值。
        st.header("输入设置")
        gt_format_label = st.selectbox("Ground truth 格式", list(FORMAT_OPTIONS), index=0)
        est_format_label = st.selectbox("VO 输出格式", list(FORMAT_OPTIONS), index=0)
        alignment_label = st.selectbox("轨迹对齐", list(ALIGNMENT_OPTIONS), index=1)
        orientation_label = st.selectbox("VO 姿态修正", list(ORIENTATION_CORRECTION_OPTIONS), index=0)
        association_label = st.selectbox("时间同步方式", list(ASSOCIATION_OPTIONS), index=0)
        max_time_diff = st.number_input("时间关联最大误差 s（不按时间则填 -1）", value=0.02, min_value=-1.0, step=0.01)
        interpolation_preset_label = st.selectbox("Reference 频率 / 插值间隔预设", list(INTERPOLATION_GAP_PRESETS), index=0)
        max_interpolation_gap = st.number_input(
            "GT 插值最大间隔 s（不限制填 -1）",
            value=float(INTERPOLATION_GAP_PRESETS[interpolation_preset_label]),
            min_value=-1.0,
            step=0.01,
        )
        allow_extrapolation = st.checkbox("允许外推（不推荐）", value=False)
        interpolate_rotation = st.checkbox("GT 姿态用 SLERP 插值", value=True)
        time_offset = st.number_input("VO 时间戳偏移 s（按 TUM：加到 VO 时间戳）", value=0.0, step=0.01)
        rpe_delta = st.number_input("RPE 固定帧间隔 Δ", value=1, min_value=1, step=1)
        segment_text = st.text_input("长航程子轨迹长度 m", value="50,100,200,500,1000,2000,5000")
        max_segments = st.number_input("每个长度最多抽样段数", value=10000, min_value=100, step=1000)
        segment_step = st.number_input("子轨迹起点步长 frames（KITTI 默认 10）", value=10, min_value=1, step=1)
        length_tolerance = st.number_input("子轨迹长度容差比例（rpg 默认 0.2）", value=0.2, min_value=0.0, max_value=1.0, step=0.05)
        segment_policy_label = st.selectbox("VO重置/大跳变处理", list(SEGMENT_POLICY_OPTIONS), index=0)
        discontinuity_step = st.number_input("断点步长阈值 m", value=100.0, min_value=0.0, step=10.0)
        discontinuity_gap = st.number_input("断点时间间隔阈值 s", value=5.0, min_value=0.0, step=1.0)
        divergence_abs = st.number_input("发散绝对阈值 m", value=10.0, min_value=0.0, step=1.0)
        divergence_rel = st.number_input("发散相对阈值 % 路程", value=2.0, min_value=0.0, step=0.5)

    left, right = st.columns(2)
    with left:
        gt_file = st.file_uploader("拖入 ground truth 轨迹文件", type=["txt", "csv", "tsv", "log"], key="gt")
    with right:
        est_file = st.file_uploader("拖入 VO 跑完输出的轨迹文件", type=["txt", "csv", "tsv", "log"], key="est")

    st.caption("支持 TUM、KITTI odometry 3x4 矩阵、CSV/TSV/空格表；可从注释表头读取 x/y/z/yaw/pitch/roll，并自动识别弧度/角度。")

    if not gt_file or not est_file:
        show_metric_catalog()
        return

    try:
        # Streamlit 热更新有时不会重载普通 Python 模块。
        # 每次评估前 reload evaluator，确保页面使用最新的解析/指标逻辑。
        evaluator = latest_evaluator()
        segment_lengths = parse_float_list(segment_text)
        cfg = evaluator.EvaluationConfig(
            alignment=ALIGNMENT_OPTIONS[alignment_label],
            orientation_correction=ORIENTATION_CORRECTION_OPTIONS[orientation_label],
            association_mode=ASSOCIATION_OPTIONS[association_label],
            max_time_diff_s=None if max_time_diff < 0 else float(max_time_diff),
            max_interpolation_gap_s=None if max_interpolation_gap < 0 else float(max_interpolation_gap),
            allow_extrapolation=bool(allow_extrapolation),
            interpolate_rotation=bool(interpolate_rotation),
            interpolation_position_method="linear",
            interpolation_rotation_method="slerp",
            time_offset_s=float(time_offset),
            rpe_delta_frames=int(rpe_delta),
            segment_lengths_m=tuple(segment_lengths),
            max_segments_per_length=int(max_segments),
            segment_step_frames=int(segment_step),
            max_segment_length_diff_ratio=float(length_tolerance),
            continuous_segment_policy=SEGMENT_POLICY_OPTIONS[segment_policy_label],
            discontinuity_step_m=float(discontinuity_step),
            discontinuity_time_gap_s=float(discontinuity_gap),
            divergence_abs_m=float(divergence_abs),
            divergence_rel_percent=float(divergence_rel),
        )
        gt = load_uploaded(gt_file, FORMAT_OPTIONS[gt_format_label], evaluator)
        est = load_uploaded(est_file, FORMAT_OPTIONS[est_format_label], evaluator)
        report = evaluator.evaluate_trajectories(gt, est, cfg)
    except Exception as exc:
        st.error(f"评估失败：{exc}")
        return

    show_summary(report)
    show_visuals(report)
    show_tables_and_downloads(report)


def latest_evaluator():
    return importlib.reload(vo_evaluator)


def load_uploaded(uploaded: Any, fmt: str, evaluator: Any):
    text = uploaded.getvalue().decode("utf-8", errors="replace")
    return evaluator.load_trajectory_from_text(text, fmt=fmt, name=uploaded.name)


def parse_float_list(text: str) -> list[float]:
    values: list[float] = []
    for item in text.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        value = float(item)
        if value > 0:
            values.append(value)
    if not values:
        raise ValueError("至少需要一个子轨迹长度")
    return values


def show_metric_catalog() -> None:
    st.subheader("建议纳入的核心指标")
    rows = [
        ("ATE 全局位置误差", "RMSE/median/p95/max；看整体轨迹一致性"),
        ("RPE 局部相对误差", "固定帧或固定时间间隔；看局部漂移"),
        ("按距离子轨迹误差", "KITTI/rpg 风格，固定段长分母；长航程无人机最关键"),
        ("尺度误差/尺度漂移", "raw path scale ratio 与分段 scale ratio；单目 VO 必看"),
        ("终点漂移", "最终位置误差及占总路程百分比；物流长航线直观"),
        ("覆盖率/成功率/丢帧", "matched poses、覆盖率、最大时间间隔；看算法是否完整跑完"),
        ("发散点", "误差超过绝对阈值或随路程增长阈值的位置"),
        ("海拔/垂直误差", "z 方向 RMSE/bias/p95；无人机配送必须单独看"),
        ("水平误差", "XY 平面误差；对应导航和投递位置偏差"),
        ("姿态/航向误差", "orientation/yaw error；影响航向控制和相机朝向"),
        ("速度分箱误差", "按飞行速度统计误差；高速长航段通常更难"),
        ("运行资源", "每帧时间、FPS、CPU、内存；部署到机载算力时需要"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["指标", "用途"]), use_container_width=True, hide_index=True)


def show_summary(report: dict[str, Any]) -> None:
    """顶部指标卡。

    UI 指标与 report 字段对应：
    - 路程 -> summary.gt_path_length_m
    - ATE RMSE -> ate_position_m.rmse
    - RPE RMSE -> rpe_frame_delta.translation_m.rmse
    - 终点漂移 -> summary.endpoint_error_m
    - 垂直 RMSE -> ate_vertical_m.rmse
    - 覆盖率/匹配位姿/耗时 -> summary
    - 是否发散 -> divergence.diverged
    """
    summary = report["summary"]
    ate = report["ate_position_m"] or {}
    vertical = report["ate_vertical_m"] or {}
    rpe = (report["rpe_frame_delta"].get("translation_m") or {})
    div = report["divergence"]

    st.subheader("运行结果")
    cols = st.columns(6)
    metric(cols[0], "路程", summary.get("gt_path_length_m"), "m")
    metric(cols[1], "ATE RMSE", ate.get("rmse"), "m")
    metric(cols[2], "RPE RMSE", rpe.get("rmse"), "m")
    metric(cols[3], "终点漂移", summary.get("endpoint_error_m"), "m")
    metric(cols[4], "垂直 RMSE", vertical.get("rmse"), "m")
    cols[5].metric("是否发散", "是" if div.get("diverged") else "否")

    cols = st.columns(6)
    metric(cols[0], "GT覆盖率", 100 * summary.get("gt_pose_coverage_ratio", summary.get("coverage_ratio", math.nan)), "%")
    metric(cols[1], "Raw 尺度比", summary.get("raw_path_scale_ratio_est_over_gt"), "")
    metric(cols[2], "对齐尺度", report["alignment"].get("scale"), "")
    metric(cols[3], "匹配位姿", summary.get("matched_poses"), "")
    metric(cols[4], "VO匹配率", 100 * summary.get("est_pose_coverage_ratio", math.nan), "%")
    metric(cols[5], "耗时", summary.get("duration_s"), "s")

    assoc = report.get("association", {})
    orientation_info = report.get("orientation_correction", {})
    cols = st.columns(4)
    cols[0].metric("时间同步", association_label(assoc))
    metric(cols[1], "最大插值间隔", assoc.get("max_interpolation_gap_s"), "s")
    metric(cols[2], "平均时间差", assoc.get("mean_time_diff_s"), "s")
    cols[3].metric("VO姿态修正", orientation_correction_label(orientation_info))

    if orientation_info.get("auto") and orientation_info.get("selected"):
        st.info(
            f"自动姿态修正选择：{orientation_info.get('selected')}，"
            f"score={orientation_info.get('best_score', math.nan):.3f}。"
            "该选择只用于评估坐标系/外参修正，不会改变原始数据。"
        )

    if div.get("diverged"):
        st.warning(
            f"首次发散：distance={div.get('first_divergence_distance_m'):.2f} m, "
            f"error={div.get('first_divergence_error_m'):.2f} m, "
            f"threshold={div.get('threshold_at_divergence_m'):.2f} m"
        )
    raw_ratio = summary.get("raw_path_scale_ratio_est_over_gt")
    align_info = report.get("alignment", {})
    align_mode = align_info.get("base_mode", align_info.get("mode"))
    if raw_ratio is not None and math.isfinite(raw_ratio) and align_mode == "se3" and not 0.8 <= raw_ratio <= 1.25:
        st.warning(
            f"当前使用 SE3 刚体对齐，但 VO/GT 原始路程比例为 {raw_ratio:.3f}，尺度明显不一致。"
            "这会导致轨迹无法重合；若 VO 是单目或尺度未知，请改用 Sim3。"
        )
    disc = report.get("discontinuities", {})
    all_disc = disc.get("all_matches", {})
    selected = disc.get("selected_segment", {})
    if all_disc.get("break_count", 0) > 0:
        dropped = selected.get("dropped_matches", 0)
        if selected.get("policy") == "vo_timestamps":
            st.info(
                f"在 VO 的 {summary.get('original_matched_poses')} 个匹配时间戳内部检测到 {all_disc.get('break_count')} 个大跳变/时间间隔。"
                "当前仍按全部 VO 时间戳统一评估，不会因此丢弃匹配点；这些提示只用于诊断 VO 是否发生重置或局部坐标系切换。"
            )
        else:
            st.warning(
                f"检测到 {all_disc.get('break_count')} 个大跳变/时间间隔、{all_disc.get('segment_count')} 个连续段。"
                f"当前策略：{selected.get('policy')}；已用于评估的匹配点 {summary.get('matched_poses')} / VO匹配点 {summary.get('original_matched_poses')}。"
                + (f" 已丢弃跨断点匹配点 {dropped} 个。" if dropped else "")
            )
        with st.expander("查看大跳变/时间间隔明细"):
            st.dataframe(pd.DataFrame(all_disc.get("breaks", [])), use_container_width=True, hide_index=True)


def association_label(assoc: dict[str, Any]) -> str:
    method = assoc.get("mode") or assoc.get("method")
    if method == "interpolate_gt":
        return "GT插值到VO"
    if method == "nearest":
        return "最近邻"
    if method == "index":
        return "按索引"
    return str(method or "N/A")


def orientation_correction_label(info: dict[str, Any]) -> str:
    selected = info.get("selected") or "none"
    requested = info.get("requested")
    if info.get("auto") and requested != selected:
        return f"auto -> {selected}"
    return str(selected)


def show_visuals(report: dict[str, Any]) -> None:
    """可视化区域。

    图表与指标对应：
    - 3D/XY 轨迹：per_pose 中 GT 和对齐后的 VO 坐标。
    - 误差随路程：per_pose.error_m / horizontal_error_m。
    - 高度与垂直误差：per_pose.gt_z_m / est_z_aligned_m / vertical_error_m。
    - 按距离子轨迹误差：segment_errors。
    - 速度分箱误差：speed_bins。
    """
    per_pose = report["per_pose"]
    segment_records = report["segment_records"]

    fig3d = make_trajectory_3d(per_pose)
    fig_xy = make_trajectory_xy(per_pose)
    fig_error = make_error_distance(per_pose)
    fig_alt = make_altitude_distance(per_pose)
    fig_segment = make_segment_error(report["segment_errors"])
    fig_speed = make_speed_error(report["speed_bins"])

    st.subheader("可视化")
    top_left, top_right = st.columns(2)
    top_left.plotly_chart(fig3d, use_container_width=True)
    top_right.plotly_chart(fig_xy, use_container_width=True)

    mid_left, mid_right = st.columns(2)
    mid_left.plotly_chart(fig_error, use_container_width=True)
    mid_right.plotly_chart(fig_alt, use_container_width=True)

    low_left, low_right = st.columns(2)
    low_left.plotly_chart(fig_segment, use_container_width=True)
    low_right.plotly_chart(fig_speed, use_container_width=True)

    if not segment_records.empty:
        with st.expander("按距离子轨迹原始记录"):
            st.dataframe(segment_records, use_container_width=True, hide_index=True)

    html = build_html_report(report, [fig3d, fig_xy, fig_error, fig_alt, fig_segment, fig_speed])
    st.download_button("下载 HTML 可视化报告", html, file_name="vo_evaluation_report.html", mime="text/html")


def show_tables_and_downloads(report: dict[str, Any]) -> None:
    """明细表和导出。

    JSON 导出完整 report；per_pose CSV 导出逐帧误差；
    segment_records CSV 导出每个固定距离子轨迹的原始误差记录。
    """
    st.subheader("明细与导出")
    summary_rows = flatten_report_summary(report)
    st.dataframe(summary_rows, use_container_width=True, hide_index=True)

    col1, col2, col3 = st.columns(3)
    col1.download_button(
        "下载 JSON 指标",
        vo_evaluator.report_to_json(report),
        file_name="vo_evaluation_metrics.json",
        mime="application/json",
    )
    col2.download_button(
        "下载每帧误差 CSV",
        report["per_pose"].to_csv(index=False),
        file_name="vo_per_pose_errors.csv",
        mime="text/csv",
    )
    segment_csv = report["segment_records"].to_csv(index=False) if not report["segment_records"].empty else ""
    col3.download_button(
        "下载子轨迹误差 CSV",
        segment_csv,
        file_name="vo_segment_errors.csv",
        mime="text/csv",
        disabled=not bool(segment_csv),
    )


def make_trajectory_3d(df: pd.DataFrame) -> go.Figure:
    """3D 轨迹图：用于肉眼检查 GT 与 VO aligned 是否重合、是否重置。"""
    fig = go.Figure()
    gt_x, gt_y, gt_z = segmented_values(df, ["gt_x_m", "gt_y_m", "gt_z_m"])
    est_x, est_y, est_z = segmented_values(df, ["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"])
    fig.add_trace(go.Scatter3d(x=gt_x, y=gt_y, z=gt_z, mode="lines", name="Ground truth"))
    fig.add_trace(
        go.Scatter3d(
            x=est_x,
            y=est_y,
            z=est_z,
            mode="lines",
            name="VO aligned",
        )
    )
    fig.update_layout(title="3D 轨迹", scene=dict(xaxis_title="x m", yaxis_title="y m", zaxis_title="z m"), height=460)
    return fig


def make_trajectory_xy(df: pd.DataFrame) -> go.Figure:
    """俯视 XY 轨迹图：对应水平路径形状和水平误差观察。"""
    fig = go.Figure()
    gt_x, gt_y = segmented_values(df, ["gt_x_m", "gt_y_m"])
    est_x, est_y = segmented_values(df, ["est_x_aligned_m", "est_y_aligned_m"])
    fig.add_trace(go.Scatter(x=gt_x, y=gt_y, mode="lines", name="Ground truth"))
    fig.add_trace(go.Scatter(x=est_x, y=est_y, mode="lines", name="VO aligned"))
    fig.update_layout(title="俯视 XY 轨迹", xaxis_title="x m", yaxis_title="y m", yaxis_scaleanchor="x", height=460)
    return fig


def make_error_distance(df: pd.DataFrame) -> go.Figure:
    """误差随路程变化：展示 ATE 3D/horizontal 是否随长航程增长。"""
    fig = go.Figure()
    dist_3d, err_3d = segmented_values(df, ["distance_m", "error_m"])
    dist_h, err_h = segmented_values(df, ["distance_m", "horizontal_error_m"])
    fig.add_trace(go.Scatter(x=dist_3d, y=err_3d, mode="lines", name="3D error"))
    fig.add_trace(go.Scatter(x=dist_h, y=err_h, mode="lines", name="horizontal"))
    fig.update_layout(title="误差随路程变化", xaxis_title="distance m", yaxis_title="error m", height=360)
    return fig


def make_altitude_distance(df: pd.DataFrame) -> go.Figure:
    """高度与垂直误差：无人机高度方向单独看，避免被 XY 误差掩盖。"""
    fig = go.Figure()
    dist_gt, gt_z = segmented_values(df, ["distance_m", "gt_z_m"])
    dist_est, est_z = segmented_values(df, ["distance_m", "est_z_aligned_m"])
    dist_err, z_err = segmented_values(df, ["distance_m", "vertical_error_m"])
    fig.add_trace(go.Scatter(x=dist_gt, y=gt_z, mode="lines", name="GT altitude"))
    fig.add_trace(go.Scatter(x=dist_est, y=est_z, mode="lines", name="VO altitude"))
    fig.add_trace(go.Scatter(x=dist_err, y=z_err, mode="lines", name="vertical error"))
    fig.update_layout(title="高度与垂直误差", xaxis_title="distance m", yaxis_title="z/error m", height=360)
    return fig


def segmented_values(df: pd.DataFrame, cols: list[str]) -> list[list[float | None]]:
    """Plotly 分段画线辅助函数。

    segment_id 之间插入 None，避免 VO 重置/分段评估时图上被错误连线。
    """
    if "segment_id" not in df.columns:
        return [df[col].tolist() for col in cols]
    outputs: list[list[float | None]] = [[] for _ in cols]
    for _, group in df.groupby("segment_id", sort=False):
        for idx, col in enumerate(cols):
            outputs[idx].extend(group[col].tolist())
            outputs[idx].append(None)
    return outputs


def make_segment_error(segment_summary: list[dict[str, Any]]) -> go.Figure:
    """长航程子轨迹误差图，对应 KITTI/rpg 风格 segment_errors。"""
    fig = go.Figure()
    if segment_summary:
        lengths = [row["length_m"] for row in segment_summary]
        mean_trans = [row["translation_error_percent"]["mean"] for row in segment_summary]
        p95_trans = [row["translation_error_percent"]["p95"] for row in segment_summary]
        fig.add_trace(go.Scatter(x=lengths, y=mean_trans, mode="lines+markers", name="translation mean %"))
        fig.add_trace(go.Scatter(x=lengths, y=p95_trans, mode="lines+markers", name="translation p95 %"))
        rot = [
            row["rotation_error_deg_per_m"]["mean"]
            if row.get("rotation_error_deg_per_m") is not None
            else None
            for row in segment_summary
        ]
        if any(v is not None for v in rot):
            fig.add_trace(go.Scatter(x=lengths, y=rot, mode="lines+markers", name="rotation deg/m", yaxis="y2"))
            fig.update_layout(yaxis2=dict(title="rotation deg/m", overlaying="y", side="right"))
    fig.update_layout(title="按距离子轨迹误差", xaxis_title="segment length m", yaxis_title="translation error %", height=360)
    return fig


def make_speed_error(speed_bins: list[dict[str, Any]]) -> go.Figure:
    """速度分箱误差图，用于判断高速/低速时 VO 漂移是否不同。"""
    fig = go.Figure()
    if speed_bins:
        labels = [row["speed_bin_mps"] for row in speed_bins]
        means = [row["translation_error_percent"]["mean"] for row in speed_bins]
        p95 = [row["translation_error_percent"]["p95"] for row in speed_bins]
        fig.add_trace(go.Bar(x=labels, y=means, name="mean %"))
        fig.add_trace(go.Bar(x=labels, y=p95, name="p95 %"))
    fig.update_layout(title="速度分箱误差", xaxis_title="speed m/s", yaxis_title="translation error %", barmode="group", height=360)
    return fig


def metric(col: Any, label: str, value: Any, unit: str) -> None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        col.metric(label, "N/A")
        return
    if isinstance(value, int):
        text = f"{value}"
    else:
        text = f"{float(value):.3f}"
    col.metric(label, f"{text} {unit}".strip())


def flatten_report_summary(report: dict[str, Any]) -> pd.DataFrame:
    """把嵌套 report 摊平成 metric/value 表，供页面展示。"""
    rows: list[dict[str, Any]] = []

    def add(prefix: str, data: Any) -> None:
        if data is None:
            return
        if isinstance(data, dict):
            for key, value in data.items():
                add(f"{prefix}.{key}" if prefix else key, value)
        elif isinstance(data, (str, int, float, bool)):
            rows.append({"metric": prefix, "value": data})

    for key in [
        "summary",
        "ate_position_m",
        "ate_horizontal_m",
        "ate_vertical_m",
        "ate_orientation_deg",
        "ate_yaw_deg",
        "orientation_correction",
        "rpe_frame_delta",
        "divergence",
        "runtime",
    ]:
        add(key, report.get(key))
    return pd.DataFrame(rows)


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def report_value(value: Any, unit: str = "") -> str:
    if value is None:
        return "N/A"
    if isinstance(value, str):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "N/A"
    text = f"{int(number)}" if number.is_integer() else f"{number:.3f}"
    return f"{text} {unit}".strip()


def report_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{number:.2f}" if math.isfinite(number) else "N/A"


def nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def report_subtitle(report: dict[str, Any]) -> str:
    gt = nested(report, "inputs", "ground_truth", "name", default="Ground truth")
    est = nested(report, "inputs", "estimate", "name", default="VO")
    matched = nested(report, "summary", "matched_poses", default="N/A")
    path = report_value(nested(report, "summary", "gt_path_length_m"), "m")
    return f"{gt} vs {est}，匹配 {matched} 帧，评估路程 {path}"


def report_overall_status(findings: list[dict[str, str]]) -> dict[str, str]:
    if any(item["severity"] == "high" for item in findings):
        return {"label": "存在高风险项", "class_name": "high"}
    if any(item["severity"] == "warning" for item in findings):
        return {"label": "有需要关注的指标", "class_name": "warning"}
    return {"label": "整体可用", "class_name": "good"}


def build_report_metric_cards(report: dict[str, Any]) -> list[dict[str, str]]:
    summary = report.get("summary", {})
    ate = report.get("ate_position_m") or {}
    rpe = nested(report, "rpe_frame_delta", "translation_m", default={}) or {}
    orient = report.get("ate_orientation_deg") or {}
    yaw = report.get("ate_yaw_deg") or {}
    alignment = report.get("alignment") or {}
    breaks = nested(report, "discontinuities", "all_matches", "break_count", default="N/A")
    return [
        {"label": "ATE RMSE", "value": report_value(ate.get("rmse"), "m"), "note": f"p95 {report_value(ate.get('p95'), 'm')}"},
        {"label": "RPE 平移 RMSE", "value": report_value(rpe.get("rmse"), "m"), "note": f"p95 {report_value(rpe.get('p95'), 'm')}"},
        {
            "label": "终点漂移",
            "value": report_value(summary.get("endpoint_error_m"), "m"),
            "note": f"{report_number(summary.get('endpoint_error_percent_of_path'))} % 路程",
        },
        {"label": "姿态 RMSE", "value": report_value(orient.get("rmse"), "deg"), "note": f"yaw {report_value(yaw.get('rmse'), 'deg')}"},
        {"label": "对齐尺度", "value": report_number(alignment.get("scale")), "note": scale_range_text(alignment)},
        {"label": "断点数量", "value": str(breaks), "note": f"策略 {nested(report, 'discontinuities', 'selected_segment', 'policy', default='N/A')}"},
        {
            "label": "VO 匹配率",
            "value": report_value(100 * summary.get("est_pose_coverage_ratio", math.nan), "%"),
            "note": f"{summary.get('matched_poses', 'N/A')} / {summary.get('est_poses', 'N/A')} 帧",
        },
        {
            "label": "GT 覆盖率",
            "value": report_value(100 * summary.get("gt_time_coverage_ratio", summary.get("gt_pose_coverage_ratio", math.nan)), "%"),
            "note": "仅表示评估覆盖的 GT 段",
        },
    ]


def report_metric_card_html(item: dict[str, str]) -> str:
    return (
        "<div class='card'>"
        f"<div class='metric-label'>{escape(item['label'])}</div>"
        f"<div class='metric-value'>{escape(item['value'])}</div>"
        f"<div class='metric-note'>{escape(item.get('note', ''))}</div>"
        "</div>"
    )


def build_report_findings(report: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def add(severity: str, title: str, evidence: str, advice: str) -> None:
        findings.append({"severity": severity, "title": title, "evidence": evidence, "advice": advice})

    summary = report.get("summary", {})
    ate = report.get("ate_position_m") or {}
    orient = report.get("ate_orientation_deg") or {}
    yaw = report.get("ate_yaw_deg") or {}
    alignment = report.get("alignment") or {}
    association = report.get("association") or {}
    disc = nested(report, "discontinuities", "all_matches", default={}) or {}
    selected = nested(report, "discontinuities", "selected_segment", default={}) or {}
    orientation_info = report.get("orientation_correction") or {}

    path = summary.get("gt_path_length_m")
    ate_rmse = ate.get("rmse")
    ate_rel = 100 * ate_rmse / path if isinstance(path, (int, float)) and path > 0 and isinstance(ate_rmse, (int, float)) else math.nan
    if math.isfinite(ate_rel) and ate_rel > 2:
        add("high", "整体位置误差偏大", f"ATE RMSE {report_value(ate_rmse, 'm')}，约 {report_number(ate_rel)} % 路程。", "优先检查时间同步、坐标轴方向、尺度来源和 Sim3/SE3 选择；再看轨迹图中是否存在局部大偏移。")
    elif math.isfinite(ate_rel) and ate_rel > 1:
        add("warning", "整体位置误差需要关注", f"ATE RMSE {report_value(ate_rmse, 'm')}，约 {report_number(ate_rel)} % 路程。", "长航程无人机建议继续看 p95/max 误差和终点漂移，避免均值掩盖局部异常。")

    break_count = disc.get("break_count", 0)
    if break_count:
        largest_gap = max([item.get("time_gap_s", 0.0) for item in disc.get("breaks", [])] or [0.0])
        add("high", "检测到 VO 重置或大跳变", f"断点 {break_count} 个，最大时间间隔 {report_value(largest_gap, 's')}；当前评估策略 {selected.get('policy', 'N/A')}。", "如果目标是连续长航程定位，需要减少跟踪丢失，加入重定位/地图复用；评估时继续按连续段看，不要把跨断点结果当成单条连续轨迹。")

    scale_range = scale_range_percent(alignment)
    if math.isfinite(scale_range) and scale_range > 15:
        add("high", "分段尺度变化明显", f"Sim3 scale 范围 {report_number(alignment.get('scale_min'))} 到 {report_number(alignment.get('scale_max'))}，相对均值变化约 {report_number(scale_range)} %。", "无尺度 VO 不能只靠一个全局尺度解释全程；真实无人机导航需要双目/深度/高度计/GPS/IMU 融合提供尺度。")
    elif math.isfinite(scale_range) and scale_range > 8:
        add("warning", "尺度稳定性需要关注", f"Sim3 scale 相对均值变化约 {report_number(scale_range)} %。", "检查不同连续段的尺度是否由 reset、特征退化或高度变化引起。")

    raw_ratio = summary.get("raw_path_scale_ratio_est_over_gt")
    if isinstance(raw_ratio, (int, float)) and math.isfinite(raw_ratio) and (raw_ratio < 0.8 or raw_ratio > 1.25):
        add("info", "VO 输出是无尺度或尺度不一致数据", f"Raw VO/GT 路程比 {report_number(raw_ratio)}。", "使用 Sim3 评估轨迹形状是合理的；如果要真实飞控定位，需要外部尺度源，不能直接使用原始 VO 单位。")

    if orientation_info.get("auto") and orientation_info.get("selected") and orientation_info.get("selected") != "none":
        add("info", "自动姿态修正已生效", f"自动选择 {orientation_info.get('selected')}，姿态 RMSE {report_value(orient.get('rmse'), 'deg')}，yaw RMSE {report_value(yaw.get('rmse'), 'deg')}。", "这说明 VO 和 GT 姿态坐标系/外参不完全一致；建议在 VO 输出端明确 camera-to-body 或 ENU/NED 约定。")
    orient_rmse = orient.get("rmse")
    if isinstance(orient_rmse, (int, float)) and orient_rmse > 10:
        add("high", "姿态误差偏大", f"姿态 RMSE {report_value(orient_rmse, 'deg')}。", "检查 yaw/pitch/roll 顺序、角度/弧度、旋转取逆、相机系到机体系外参和 ENU/NED 转换。")
    elif isinstance(orient_rmse, (int, float)) and orient_rmse > 5:
        add("warning", "姿态误差略高", f"姿态 RMSE {report_value(orient_rmse, 'deg')}，yaw RMSE {report_value(yaw.get('rmse'), 'deg')}。", "如果姿态要用于控制或相机指向，继续校准外参和欧拉角约定。")

    seg50 = find_segment(report, 50)
    seg_long = find_segment(report, 1000) or find_segment(report, 500)
    seg50_mean = nested(seg50 or {}, "translation_error_percent", "mean")
    seg_long_mean = nested(seg_long or {}, "translation_error_percent", "mean")
    if isinstance(seg50_mean, (int, float)) and seg50_mean > 10:
        add("high", "短距离局部漂移偏大", f"50m 子轨迹平均误差 {report_value(seg50_mean, '%')}。", "优先调特征跟踪、RANSAC、关键帧策略和图像质量；短段差通常说明帧间估计不稳定。")
    elif isinstance(seg50_mean, (int, float)) and seg50_mean > 5:
        add("warning", "短距离局部漂移需要关注", f"50m 子轨迹平均误差 {report_value(seg50_mean, '%')}。", "检查高速、弱纹理、运动模糊区间的误差分箱。")
    if isinstance(seg_long_mean, (int, float)) and seg_long_mean > 5:
        add("high", "长距离累计漂移偏大", f"{seg_long.get('length_m')}m 子轨迹平均误差 {report_value(seg_long_mean, '%')}。", "优化后端约束、闭环/重定位和尺度融合；长段差说明累计漂移无法满足长航程要求。")
    elif isinstance(seg_long_mean, (int, float)) and seg_long_mean > 2:
        add("warning", "长距离累计漂移需要关注", f"{seg_long.get('length_m')}m 子轨迹平均误差 {report_value(seg_long_mean, '%')}。", "对物流无人机建议同时看 2000m/5000m 段和终点漂移，确认长航程稳定性。")

    divergence = report.get("divergence") or {}
    if divergence.get("diverged"):
        add("warning", "发散阈值被触发", f"首次触发 distance={report_value(divergence.get('first_divergence_distance_m'), 'm')}，error={report_value(divergence.get('first_divergence_error_m'), 'm')}。", "如果首帧附近触发，可能是阈值过严或对齐后起点仍有偏差；建议结合 ATE 曲线判断是否真实发散。")

    dropped = association.get("dropped_est_outside_gt_range", 0) + association.get("dropped_est_large_gt_gap", 0)
    if dropped:
        add("warning", "部分 VO 帧未纳入评估", f"超出 GT 或插值间隔过大丢弃 {dropped} 帧。", "检查 GT/VO 时间戳单位、固定偏移和最大插值间隔设置。")
    est_coverage = summary.get("est_pose_coverage_ratio")
    if isinstance(est_coverage, (int, float)) and est_coverage < 0.95:
        add("warning", "VO 匹配率偏低", f"VO 匹配率 {report_value(100 * est_coverage, '%')}。", "优先检查时间同步方式、时间偏移和 GT 时间覆盖范围。")

    if not any(item["severity"] in {"high", "warning"} for item in findings):
        add("good", "主要误差指标未触发严重告警", "ATE、RPE、子轨迹误差和姿态误差在当前阈值下基本可读。", "继续结合轨迹图、速度分箱和任务容差做最终判断。")
    return findings


def report_finding_html(item: dict[str, str]) -> str:
    return (
        f"<div class='finding {escape(item['severity'])}'>"
        f"<div class='severity'>{escape(item['severity'])}</div>"
        f"<h3>{escape(item['title'])}</h3>"
        f"<p class='evidence'>{escape(item['evidence'])}</p>"
        f"<p class='advice'>{escape(item['advice'])}</p>"
        "</div>"
    )


def build_segment_summary_rows(report: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for row in report.get("segment_errors") or []:
        rows.append(
            {
                "length": report_number(row.get("length_m")),
                "mean": report_number(nested(row, "translation_error_percent", "mean")),
                "p95": report_number(nested(row, "translation_error_percent", "p95")),
                "scale_p95": report_number(nested(row, "scale_drift_percent", "p95")),
                "count": str(row.get("count", "")),
            }
        )
    return rows


def segment_table_html(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "<div class='card'>没有可用的子轨迹统计。</div>"
    body = "".join(
        f"<tr><td>{row['length']}</td><td>{row['mean']}</td><td>{row['p95']}</td><td>{row['scale_p95']}</td><td>{row['count']}</td></tr>"
        for row in rows
    )
    return "<table><thead><tr><th>长度 m</th><th>平移误差 mean %</th><th>平移误差 p95 %</th><th>尺度漂移 p95 %</th><th>样本数</th></tr></thead><tbody>" + body + "</tbody></table>"


def build_config_rows(report: dict[str, Any]) -> list[dict[str, str]]:
    summary = report.get("summary") or {}
    cfg = report.get("config") or {}
    assoc = report.get("association") or {}
    correction = report.get("orientation_correction") or {}
    return [
        {"label": "Ground truth", "value": f"{nested(report, 'inputs', 'ground_truth', 'name', default='N/A')} ({nested(report, 'inputs', 'ground_truth', 'format', default='N/A')})"},
        {"label": "VO 输出", "value": f"{nested(report, 'inputs', 'estimate', 'name', default='N/A')} ({nested(report, 'inputs', 'estimate', 'format', default='N/A')})"},
        {"label": "时间同步", "value": f"{assoc.get('method') or assoc.get('mode') or 'N/A'}，匹配 {assoc.get('matches', 'N/A')} 帧"},
        {"label": "轨迹对齐", "value": str(cfg.get("alignment", "N/A"))},
        {"label": "姿态修正", "value": f"auto -> {correction.get('selected')}" if correction.get("auto") else str(correction.get("selected") or cfg.get("orientation_correction", "N/A"))},
        {"label": "断点策略", "value": str(cfg.get("continuous_segment_policy", "N/A"))},
        {"label": "评估路程/耗时", "value": f"{report_value(summary.get('gt_path_length_m'), 'm')} / {report_value(summary.get('duration_s'), 's')}"},
    ]


def flatten_full_report_metrics(report: dict[str, Any]) -> list[dict[str, str]]:
    """把 report 中所有已计算的标量指标摊平成表格。

    per_pose 和 segment_records 是逐帧/逐子轨迹明细，数据量很大，报告里保留在原始 JSON 和 CSV 下载中；
    这里展开 summary、ATE/RPE、alignment、association、orientation、segment_errors 等统计结果。
    """
    rows: list[dict[str, str]] = []
    skip_root = {"per_pose", "segment_records"}
    skip_leaf = {"segment_ids"}

    def add(path: str, value: Any) -> None:
        if not path:
            return
        root = path.split(".", 1)[0]
        leaf = path.rsplit(".", 1)[-1]
        if root in skip_root or leaf in skip_leaf:
            return
        if value is None:
            rows.append({"metric": path, "value": ""})
            return
        if isinstance(value, pd.DataFrame):
            rows.append({"metric": path, "value": f"[{len(value)} rows skipped; use CSV download]"})
            return
        if isinstance(value, pd.Series):
            add(path, value.to_list())
            return
        if isinstance(value, dict):
            for key, item in value.items():
                add(f"{path}.{key}" if path else str(key), item)
            return
        if isinstance(value, (list, tuple)):
            if len(value) > 60 and all(not isinstance(item, (dict, list, tuple)) for item in value):
                rows.append({"metric": path, "value": f"[{len(value)} values skipped; see raw JSON]"})
                return
            for index, item in enumerate(value):
                add(f"{path}[{index}]", item)
            return
        rows.append({"metric": path, "value": report_metric_value(value)})

    for key, value in report.items():
        add(str(key), value)
    return rows


def report_metric_value(value: Any) -> str:
    """完整指标统计表中的数值格式化，保留比页面卡片更多的小数。"""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "N/A"
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


METRIC_GROUP_LABELS = {
    "summary": "总体统计",
    "inputs": "输入文件",
    "config": "评估配置",
    "association": "时间同步与匹配",
    "alignment": "轨迹对齐",
    "ate_position_m": "ATE 绝对位置误差",
    "ate_horizontal_m": "水平 ATE",
    "ate_vertical_m": "垂直 ATE",
    "ate_orientation_deg": "姿态 ATE",
    "ate_yaw_deg": "Yaw 绝对误差",
    "orientation_correction": "姿态修正选择",
    "rpe_frame_delta": "RPE 相对位姿误差",
    "divergence": "发散检测",
    "runtime": "耗时统计",
    "discontinuities": "断点/重置诊断",
    "segment_errors": "长航程子轨迹误差",
    "speed_bins": "速度分箱误差",
}


METRIC_FIELD_LABELS = {
    "count": "样本数",
    "rmse": "均方根误差",
    "mean": "平均值",
    "median": "中位数",
    "std": "标准差",
    "min": "最小值",
    "max": "最大值",
    "p95": "95 分位值",
    "p99": "99 分位值",
    "length_m": "子轨迹长度",
    "speed_bin_mps": "速度区间",
    "translation_error_percent": "平移误差百分比",
    "translation_m": "平移误差",
    "rotation_error_deg_per_m": "旋转误差 deg/m",
    "rotation_deg": "旋转误差",
    "translation_error_m": "平移误差 m",
    "scale_drift_percent": "尺度漂移百分比",
    "scale_ratio_est_over_gt": "VO/GT 尺度比",
    "gt_path_length_m": "GT 轨迹长度",
    "est_path_length_raw_m": "VO 原始轨迹长度",
    "est_path_length_aligned_m": "VO 对齐后轨迹长度",
    "duration_s": "评估时长",
    "matched_poses": "匹配位姿数",
    "original_matched_poses": "原始匹配位姿数",
    "gt_poses": "GT 位姿数",
    "est_poses": "VO 位姿数",
    "coverage_ratio": "覆盖率",
    "gt_pose_coverage_ratio": "GT 位姿覆盖率",
    "gt_time_coverage_ratio": "GT 时间覆盖率",
    "est_pose_coverage_ratio": "VO 匹配率",
    "endpoint_error_m": "终点误差",
    "endpoint_error_percent_of_path": "终点误差占路程比例",
    "raw_path_scale_ratio_est_over_gt": "VO/GT 原始路程比",
    "scale": "对齐尺度",
    "scale_min": "分段最小尺度",
    "scale_max": "分段最大尺度",
    "scale_std": "分段尺度标准差",
    "method": "匹配方法",
    "mode": "匹配模式",
    "matches": "匹配数量",
    "mean_time_diff_s": "平均时间差",
    "max_time_diff_s": "最大时间差阈值",
    "max_interpolation_gap_s": "最大插值间隔",
    "max_interpolation_gap_s_allowed": "允许的最大插值间隔",
    "mean_interpolation_gap_s": "平均插值间隔",
    "dropped_est_outside_gt_range": "超出 GT 范围的 VO 帧数",
    "dropped_est_large_gt_gap": "GT 插值间隔过大丢弃帧数",
    "break_count": "断点数量",
    "segment_count": "连续段数量",
    "step_threshold_m": "步长断点阈值",
    "time_gap_threshold_s": "时间断点阈值",
    "start": "起始索引",
    "end": "结束索引",
    "start_index": "起始索引",
    "end_index": "结束索引",
    "policy": "评估段策略",
    "selected_matches": "纳入评估的匹配数",
    "dropped_matches": "未纳入评估的匹配数",
    "first_divergence_distance_m": "首次发散路程",
    "first_divergence_error_m": "首次发散误差",
    "max_error_m": "最大误差",
    "final_error_m": "最终误差",
    "abs_threshold_m": "绝对误差阈值",
    "rel_threshold_percent": "相对误差阈值",
    "diverged": "是否发散",
    "requested": "请求的姿态修正",
    "selected": "实际选择的姿态修正",
    "auto": "是否自动选择",
    "best_score": "自动选择评分",
    "name": "名称",
    "format": "格式",
    "ground_truth": "Ground truth",
    "estimate": "VO 输出",
    "alignment": "轨迹对齐方式",
    "base_mode": "基础对齐方式",
    "association_mode": "时间同步方式",
    "orientation_correction": "姿态修正方式",
    "time_offset_s": "时间偏移",
    "rpe_delta_frames": "RPE 间隔帧数",
    "segment_lengths_m": "子轨迹长度列表",
    "max_segments_per_length": "每个长度最大采样数",
    "segment_step_frames": "子轨迹采样步长",
    "max_segment_length_diff_ratio": "子轨迹长度容差比例",
    "continuous_segment_policy": "连续段处理策略",
    "discontinuity_step_m": "断点步长阈值",
    "discontinuity_time_gap_s": "断点时间间隔阈值",
    "divergence_abs_m": "发散绝对阈值",
    "divergence_rel_percent": "发散相对阈值",
    "speed_bins_mps": "速度分箱边界",
    "all_matches": "全部匹配",
    "used_matches": "已使用匹配",
    "selected_segment": "选中的评估段",
    "segments": "连续段",
}


def metric_table_html(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "<div class='card'>没有可展示的统计值。</div>"
    groups = group_metric_rows(rows)
    sections = []
    for group in groups:
        body = "".join(
            "<tr>"
            f"<td>{escape(metric_param_label(item['field']))}</td>"
            f"<td><code>{escape(item['metric'])}</code></td>"
            f"<td>{escape(item['value'])}</td>"
            f"<td>{escape(metric_issue(item['metric']))}</td>"
            "</tr>"
            for item in group["items"]
        )
        sections.append(
            "<details class='metric-group'>"
            "<summary>"
            f"<span class='group-title'>{escape(metric_group_label(group['key']))}</span>"
            f"<code>{escape(group['key'])}</code>"
            f"<span class='group-count'>{len(group['items'])} 项</span>"
            "</summary>"
            f"<p class='metric-help'>{escape(metric_issue(group['key']))}</p>"
            "<table><thead><tr><th>参数</th><th>原始字段</th><th>值</th><th>反映的问题</th></tr></thead><tbody>"
            + body
            + "</tbody></table></details>"
        )
    return "".join(sections)


def group_metric_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        metric = row["metric"]
        group_key, field = split_metric_path(metric)
        item = {**row, "field": field}
        groups.setdefault(group_key, []).append(item)
    return [{"key": key, "items": items} for key, items in groups.items()]


def split_metric_path(metric: str) -> tuple[str, str]:
    if "." not in metric:
        return "general", metric
    group, field = metric.rsplit(".", 1)
    return group, field


def metric_group_label(group_key: str) -> str:
    if group_key == "general":
        return "其他指标"
    parts = group_key.split(".")
    labels = [metric_path_part_label(part) for part in parts]
    return " / ".join(label for label in labels if label)


def metric_path_part_label(part: str) -> str:
    match = re.fullmatch(r"([A-Za-z_]+)\[(\d+)\]", part)
    if match:
        root, index = match.groups()
        base = METRIC_GROUP_LABELS.get(root) or METRIC_FIELD_LABELS.get(root) or root
        return f"{base} 第 {int(index) + 1} 项"
    return METRIC_GROUP_LABELS.get(part) or METRIC_FIELD_LABELS.get(part) or part.replace("_", " ")


def metric_param_label(field: str) -> str:
    match = re.fullmatch(r"([A-Za-z_]+)(\[\d+\])+", field)
    if match:
        base = match.group(1)
        return f"{METRIC_FIELD_LABELS.get(base, base)} {field[len(base):]}"
    return METRIC_FIELD_LABELS.get(field) or field.replace("_", " ")


def metric_leaf(metric: str) -> str:
    return metric.rsplit(".", 1)[-1]


def metric_field_base(field: str) -> str:
    return re.sub(r"(\[\d+\])+$", "", field)


def metric_issue(metric: str) -> str:
    field = metric_field_base(metric_leaf(metric))
    if metric.startswith("alignment."):
        return alignment_metric_issue(field)
    if metric.startswith("summary."):
        return summary_metric_issue(field)
    if metric.startswith("association."):
        return association_metric_issue(field)
    if metric.startswith("discontinuities."):
        return discontinuity_metric_issue(field)
    if metric.startswith("divergence."):
        return divergence_metric_issue(field)
    if metric.startswith("orientation_correction."):
        return orientation_correction_metric_issue(field)
    if metric.startswith("config."):
        return config_metric_issue(field)
    if metric.startswith("inputs."):
        return "记录本次评估使用的输入文件信息，主要用于复现实验和排查是否传错数据。"

    statistic_issue = statistic_metric_issue(metric, field)
    if statistic_issue:
        return statistic_issue
    if "segment_errors" in metric:
        specific = segment_metric_issue(field)
        if specific:
            return specific
    if "speed_bins" in metric:
        specific = speed_bin_metric_issue(field)
        if specific:
            return specific

    if "speed_bins" in metric:
        if "translation_error_percent" in metric:
            return "反映某个速度区间内的平移漂移；高速区间偏高通常要检查运动模糊、滚快门、特征跟踪和曝光，低速区间偏高则要看初始化、弱纹理或悬停退化。"
        return "反映不同飞行速度下的误差分布，用来判断 VO 是否在特定速度范围内明显退化。"
    if "segment_errors" in metric:
        if "scale_drift_percent" in metric:
            return "反映固定航程子轨迹内尺度是否稳定；无尺度 VO 或高度/IMU 融合不足时这里会偏高。"
        if "rotation_error_deg_per_m" in metric:
            return "反映单位距离的姿态累计漂移；偏高时要检查外参、欧拉角约定、IMU/视觉姿态融合和后端约束。"
        return "反映固定距离内的累计漂移；短距离偏高说明前端跟踪不稳，长距离偏高说明尺度、后端约束或闭环能力不足。"
    if "rpe_frame_delta" in metric:
        return "反映相邻或固定间隔帧之间的相对运动误差；偏高通常说明帧间 VO 估计不稳定。"
    if "ate_position_m" in metric:
        return "反映对齐后整条轨迹的绝对位置误差；偏高要优先检查时间同步、坐标系、尺度和局部漂移。"
    if "ate_horizontal_m" in metric:
        return "反映 XY 平面误差；偏高会直接影响航线跟踪和水平定位。"
    if "ate_vertical_m" in metric:
        return "反映高度方向误差；偏高要检查高度计、Z 轴方向、NED/ENU 转换和尺度。"
    if "ate_orientation_deg" in metric or "ate_yaw_deg" in metric:
        return "反映姿态或航向误差；偏高要检查 yaw/pitch/roll 顺序、角度/弧度、坐标系和 camera-to-body 外参。"
    if metric.startswith("association"):
        return "反映 GT 与 VO 时间戳是否正确对齐；匹配率低或时间差大时，后续误差指标可信度会下降。"
    if metric.startswith("alignment"):
        return "反映对齐变换和尺度；尺度变化大说明 VO 尺度不稳定或不同连续段不在同一坐标系。"
    if metric.startswith("discontinuities"):
        return "反映 VO 是否发生重置、丢跟踪或大跳变；长航程无人机需要重点关注连续性。"
    if metric.startswith("divergence"):
        return "反映误差是否超过设定阈值；触发后说明轨迹在某处已明显不可用或阈值设置过严。"
    if metric.startswith("runtime"):
        return "反映算法运行效率；耗时、FPS、CPU 或内存异常会影响实时部署。"
    if metric.startswith("summary"):
        if "coverage" in metric or "matched" in metric:
            return "反映本次评估覆盖了多少有效数据；覆盖不足时不能代表整段飞行。"
        if "endpoint" in metric:
            return "反映终点累计漂移；长航程任务中比单帧误差更能说明最终定位偏差。"
        if "raw_path_scale_ratio" in metric:
            return "反映 VO 原始尺度与 GT 的比例；明显不为 1 时说明数据可能是无尺度或尺度不一致。"
        return "反映本次评估的总体数据规模、路程和时长，是解释其他误差指标的上下文。"
    if metric.startswith("orientation_correction"):
        return "反映系统为 VO 姿态选择的坐标系/外参修正；自动选择非 none 时说明 VO 与 GT 的姿态约定不一致。"
    if metric.startswith("inputs") or metric.startswith("config"):
        return "这是评估输入和配置，不直接代表好坏，但会影响所有误差指标的计算方式。"
    return "用于辅助定位误差来源；需要结合轨迹图、ATE/RPE 和子轨迹误差一起判断。"


def alignment_metric_issue(field: str) -> str:
    issues = {
        "mode": "说明最终采用的是全局对齐还是按连续段分别对齐；如果是 per_segment，跨段结果不能当作一条完全连续轨迹解释。",
        "base_mode": "说明基础对齐模型；Sim3 会同时估计旋转、平移和尺度，适合无尺度 VO，但会掩盖原始尺度误差。",
        "scale": "VO 坐标乘到 GT 坐标上的平均尺度因子；明显不接近 1 时，说明原始 VO 尺度与真实尺度不一致。",
        "scale_min": "所有连续段里最小的对齐尺度；如果它和最大尺度差距大，说明某些航段的 VO 原始尺度明显偏大或尺度发生漂移。",
        "scale_max": "所有连续段里最大的对齐尺度；如果它和最小尺度差距大，说明某些航段的 VO 原始尺度明显偏小或尺度发生漂移。",
        "scale_std": "不同连续段对齐尺度的离散程度；数值越大，说明 VO 尺度稳定性越差。",
        "segment_count": "参与对齐统计的连续段数量；数量大于 1 时通常意味着存在断点、重置或分段评估。",
    }
    return issues.get(field, "该参数描述轨迹对齐变换的一个组成部分，用来判断坐标系、尺度和连续段处理是否合理。")


def summary_metric_issue(field: str) -> str:
    issues = {
        "gt_path_length_m": "GT 在本次有效评估窗口内的真实路程；后续百分比误差都要以这个路程作为背景理解。",
        "est_path_length_raw_m": "VO 原始输出轨迹长度；与 GT 路程差很多时，通常说明 VO 是无尺度或尺度漂移明显。",
        "est_path_length_aligned_m": "VO 对齐后的轨迹长度；用于检查对齐后路程是否仍明显偏离 GT。",
        "duration_s": "本次评估覆盖的飞行时间；时间过短时不能代表长航程表现。",
        "matched_poses": "最终纳入评估的位姿数量；数量少会降低 ATE、RPE、p95 等统计可信度。",
        "original_matched_poses": "时间同步后原始可匹配位姿数量；和 matched_poses 差距大说明后续断点策略丢掉了不少数据。",
        "gt_poses": "GT 文件中可解析出的位姿数量；用于确认 GT 数据量是否足够。",
        "est_poses": "VO 文件中可解析出的位姿数量；用于确认 VO 输出是否完整。",
        "coverage_ratio": "整体覆盖比例；覆盖低说明本次评估只代表局部飞行段。",
        "gt_pose_coverage_ratio": "GT 位姿被评估覆盖的比例；过低时要检查 VO 是否只覆盖 GT 的一小段。",
        "gt_time_coverage_ratio": "GT 时间跨度被 VO 覆盖的比例；过低时说明 VO 与 GT 时间范围不一致。",
        "est_pose_coverage_ratio": "VO 位姿被成功匹配并纳入评估的比例；过低时优先检查时间戳单位、时间偏移和插值阈值。",
        "endpoint_error_m": "轨迹终点的累计位置误差；长航程任务里它直接反映最终落点/定位偏差。",
        "endpoint_error_percent_of_path": "终点误差占总路程比例；便于不同航程之间比较终点漂移。",
        "raw_path_scale_ratio_est_over_gt": "VO 原始路程与 GT 路程的比例；明显不为 1 时说明原始输出没有真实尺度或尺度不稳定。",
    }
    return issues.get(field, "该总体参数提供评估数据规模、覆盖范围或全局漂移背景，用来解释后续误差指标。")


def association_metric_issue(field: str) -> str:
    issues = {
        "method": "实际使用的时间同步算法；决定 GT/VO 如何被放到同一时间轴。",
        "mode": "用户选择的时间同步模式；选错会导致轨迹错位，从而让所有误差变大。",
        "matches": "成功匹配的时间戳数量；数量越少，统计结果越不稳定。",
        "time_offset_s": "应用到 VO 或 GT 的时间偏移；如果设置不对，会出现整体轨迹相位错开。",
        "max_time_diff_s": "最近邻匹配允许的最大时间差；阈值过大可能误匹配，过小可能丢匹配。",
        "mean_time_diff_s": "匹配后的平均时间差；越大越可能引入运动中的位置误差。",
        "max_interpolation_gap_s_allowed": "允许 GT 插值跨越的最大时间间隔；过大可能跨过 GT 空洞，过小可能丢掉 VO 帧。",
        "max_interpolation_gap_s": "实际使用到的最大 GT 插值间隔；接近阈值时要检查 GT 是否有采样空洞。",
        "mean_interpolation_gap_s": "GT 插值使用的平均邻近间隔；越小通常时间同步越可靠。",
        "dropped_est_outside_gt_range": "因 VO 时间戳超出 GT 时间范围而丢弃的帧数；非零时说明两份数据起止时间不一致。",
        "dropped_est_large_gt_gap": "因 GT 邻近采样间隔过大而丢弃的 VO 帧数；非零时说明 GT 中间可能有时间空洞。",
        "gt_time_coverage_ratio": "VO 覆盖到的 GT 时间比例；低值说明评估不是完整 GT 飞行。",
        "est_pose_coverage_ratio": "VO 输出中被成功评估的比例；低值说明 VO 有大量帧无法和 GT 对齐。",
    }
    return issues.get(field, "该参数用于判断 GT 和 VO 时间戳是否对齐；时间同步不好会污染所有误差指标。")


def statistic_metric_issue(metric: str, field: str) -> str | None:
    context = metric_context(metric)
    issues = {
        "count": f"{context}的样本数量；样本太少时，均值、p95 和 p99 都不稳定。",
        "rmse": f"{context}的均方根值；会放大大误差，适合发现局部严重漂移或离群问题。",
        "mean": f"{context}的平均水平；用于看整体常态表现，但可能被极端值影响。",
        "median": f"{context}的中位数；代表更典型的表现，和 mean 差很多时说明误差分布偏斜或有离群点。",
        "std": f"{context}的波动程度；越大说明不同片段/速度/帧之间表现越不稳定。",
        "min": f"{context}的最好情况；只能说明最佳片段表现，不能代表整体质量。",
        "max": f"{context}的最坏情况；用于定位最严重漂移、跟踪失败或异常航段。",
        "p95": f"{context}的 95 分位值；代表大多数情况下的上界，比 max 更适合做工程容差判断。",
        "p99": f"{context}的 99 分位值；用于观察极端但非单点的尾部风险。",
    }
    return issues.get(field)


def metric_context(metric: str) -> str:
    if "translation_error_percent" in metric:
        return "平移误差百分比"
    if "translation_error_m" in metric or "translation_m" in metric:
        return "平移误差"
    if "rotation_error_deg_per_m" in metric:
        return "单位距离旋转误差"
    if "rotation_deg" in metric:
        return "旋转误差"
    if "scale_drift_percent" in metric:
        return "尺度漂移百分比"
    if "scale_ratio_est_over_gt" in metric:
        return "VO/GT 尺度比"
    if "ate_position_m" in metric:
        return "ATE 位置误差"
    if "ate_horizontal_m" in metric:
        return "水平 ATE"
    if "ate_vertical_m" in metric:
        return "垂直 ATE"
    if "ate_orientation_deg" in metric:
        return "姿态 ATE"
    if "ate_yaw_deg" in metric:
        return "Yaw 误差"
    if "speed_bins" in metric:
        return "该速度区间误差"
    if "segment_errors" in metric:
        return "该子轨迹误差"
    return "该指标"


def segment_metric_issue(field: str) -> str | None:
    issues = {
        "length_m": "当前子轨迹统计对应的航程长度；短段主要看局部跟踪稳定性，长段主要看累计漂移。",
        "translation_error_percent": "该长度子轨迹的平移误差占路程比例；越高说明固定航程内累计漂移越明显。",
        "translation_error_m": "该长度子轨迹的绝对平移误差；用于判断实际米级偏差是否超过任务容差。",
        "rotation_error_deg_per_m": "单位距离姿态累计误差；偏高时要检查外参、姿态约定和后端约束。",
        "scale_ratio_est_over_gt": "子轨迹内 VO 路程与 GT 路程的比例；偏离 1 说明该段尺度不准。",
        "scale_drift_percent": "子轨迹内尺度漂移百分比；偏高说明尺度随航段变化，常见于单目无尺度或高度/IMU 融合不足。",
    }
    return issues.get(field)


def speed_bin_metric_issue(field: str) -> str | None:
    issues = {
        "speed_bin_mps": "当前误差统计对应的飞行速度区间；用于定位 VO 在低速、巡航或高速时是否退化。",
        "count": "该速度区间内参与统计的样本数；样本少时不能据此判断该速度段好坏。",
        "translation_error_percent": "该速度区间内的平移误差比例；高速偏高常和运动模糊/曝光/滚快门有关，低速偏高常和弱纹理或悬停退化有关。",
        "rotation_error_deg_per_m": "该速度区间内单位距离姿态误差；偏高说明该速度下姿态估计或外参约定更不稳定。",
    }
    return issues.get(field)


def discontinuity_metric_issue(field: str) -> str:
    issues = {
        "step_threshold_m": "用于判断相邻匹配之间是否出现位置大跳变的距离阈值。",
        "time_gap_threshold_s": "用于判断相邻匹配之间是否出现时间断裂的阈值。",
        "break_count": "检测到的断点数量；非零通常表示 VO 重置、丢跟踪或时间数据不连续。",
        "segment_count": "由断点切出的连续段数量；数量越多，越不适合把结果当作单条连续长航程轨迹。",
        "start": "连续段在匹配序列中的起点索引，用于定位断点前后的数据范围。",
        "end": "连续段在匹配序列中的终点索引，用于定位断点前后的数据范围。",
        "start_index": "被选中评估段的起点索引；用于复查具体从哪一帧开始纳入统计。",
        "end_index": "被选中评估段的终点索引；用于复查具体到哪一帧结束统计。",
        "count": "该连续段包含的匹配位姿数量；段太短时误差统计代表性不足。",
        "policy": "断点处理策略；决定是保留所有 VO 时间戳、逐段评估，还是只评估最长连续段。",
        "selected_matches": "最终纳入评估的匹配数量；和原始匹配差距大时说明断点策略丢弃了不少数据。",
        "dropped_matches": "因为断点策略未纳入评估的匹配数量；过高说明 VO 连续性问题明显。",
    }
    return issues.get(field, "该参数用于定位 VO 是否有重置、丢跟踪或大跳变，并判断长航程连续性。")


def divergence_metric_issue(field: str) -> str:
    issues = {
        "diverged": "是否触发发散判定；True 表示误差超过了设定的绝对或相对阈值。",
        "abs_threshold_m": "发散检测使用的绝对误差阈值；超过该米级误差会被认为不可接受。",
        "rel_threshold_percent": "发散检测使用的相对路程阈值；用于长航程下按路程比例判断误差是否过大。",
        "first_divergence_distance_m": "第一次触发发散时已经飞过的路程；用于定位问题开始出现的位置。",
        "first_divergence_error_m": "第一次触发发散时的误差大小；用于判断触发是否严重。",
        "max_error_m": "整段评估中的最大位置误差；用于定位最坏时刻。",
        "final_error_m": "末尾位置误差；用于判断飞完整段后累计漂移是否仍可接受。",
    }
    return issues.get(field, "该参数用于判断误差是否超过任务容差，并定位首次失效位置。")


def orientation_correction_metric_issue(field: str) -> str:
    issues = {
        "requested": "用户请求的姿态修正方式；用于确认评估时是否启用了自动选择或手动外参修正。",
        "selected": "系统实际采用的姿态修正方式；自动模式下如果不是 none，说明 VO 和 GT 的姿态坐标约定不一致。",
        "auto": "是否启用自动姿态修正选择；开启后系统会尝试多种坐标系/外参候选。",
        "best_score": "自动姿态修正候选的评分；分数越低通常表示该候选下姿态/轨迹误差更好。",
    }
    return issues.get(field, "该参数描述 VO 姿态坐标系或外参修正选择，用于排查 yaw/pitch/roll、ENU/NED 和 camera/body 约定。")


def config_metric_issue(field: str) -> str:
    issues = {
        "alignment": "控制使用 SE3、Sim3、首帧或不对齐；会直接影响所有位置误差解释。",
        "orientation_correction": "控制是否修正 VO 姿态坐标系/外参；会影响姿态 ATE、旋转 RPE 和带姿态的子轨迹指标。",
        "association_mode": "控制 GT 与 VO 如何按时间匹配；选错会让轨迹错位。",
        "max_time_diff_s": "最近邻匹配允许的最大时间差；过大可能错配，过小可能丢帧。",
        "max_interpolation_gap_s": "GT 插值允许跨越的最大采样间隔；用于避免跨 GT 空洞插值。",
        "time_offset_s": "手动时间偏移；用于修正 GT 与 VO 固定延迟。",
        "rpe_delta_frames": "RPE 使用的帧间隔；间隔越大越接近中短程累计漂移。",
        "segment_lengths_m": "长航程子轨迹统计使用的距离列表；决定报告会比较哪些航程长度。",
        "max_segments_per_length": "每个子轨迹长度最多抽样数量；限制计算量，过低会降低统计代表性。",
        "segment_step_frames": "子轨迹抽样步长；步长越小样本越密，但计算更慢。",
        "max_segment_length_diff_ratio": "允许实际子轨迹长度偏离目标长度的比例；过严会导致长距离样本不足。",
        "continuous_segment_policy": "断点处理策略；决定跨 VO 重置的数据是否仍纳入同一评估。",
        "discontinuity_step_m": "断点检测的位置跳变阈值；过小容易误报，过大可能漏掉重置。",
        "discontinuity_time_gap_s": "断点检测的时间间隔阈值；用于发现数据中断或 VO 输出停顿。",
        "divergence_abs_m": "发散检测的绝对误差阈值；用于判定米级误差是否不可接受。",
        "divergence_rel_percent": "发散检测的相对路程阈值；用于长航程下按比例判断误差。",
        "speed_bins_mps": "速度分箱边界；决定速度分箱误差如何分组。",
    }
    return issues.get(field, "该配置项会影响评估方式或统计范围，不直接代表算法好坏，但会改变指标解释。")


def find_segment(report: dict[str, Any], length: float) -> dict[str, Any] | None:
    for row in report.get("segment_errors") or []:
        if row.get("length_m") == length:
            return row
    return None


def scale_range_percent(alignment: dict[str, Any]) -> float:
    try:
        scale = float(alignment.get("scale"))
        min_scale = float(alignment.get("scale_min"))
        max_scale = float(alignment.get("scale_max"))
    except (TypeError, ValueError):
        return math.nan
    if not math.isfinite(scale) or scale == 0:
        return math.nan
    return 100 * (max_scale - min_scale) / abs(scale)


def scale_range_text(alignment: dict[str, Any]) -> str:
    percent = scale_range_percent(alignment)
    if not math.isfinite(percent):
        return ""
    return f"{report_number(alignment.get('scale_min'))}-{report_number(alignment.get('scale_max'))} ({report_number(percent)}%)"


def build_html_report(report: dict[str, Any], figures: list[go.Figure]) -> str:
    """生成更易读的离线 HTML 报告。

    第一屏展示结论、风险提示和关键指标；完整 JSON 放在折叠区，避免读者先被原始数据淹没。
    """
    findings = build_report_findings(report)
    status = report_overall_status(findings)
    metric_cards = build_report_metric_cards(report)
    segment_rows = build_segment_summary_rows(report)
    config_rows = build_config_rows(report)
    metric_rows = flatten_full_report_metrics(report)
    raw_json = vo_evaluator.report_to_json(report)
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><title>VO Evaluation Report</title>",
        """
<style>
:root{--text:#20242a;--muted:#667085;--line:#d8dee8;--bg:#f5f7fb;--card:#fff;--good:#15803d;--warn:#b45309;--bad:#b42318;--info:#175cd3}
*{box-sizing:border-box}body{font-family:Arial,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;color:var(--text);background:var(--bg);line-height:1.55}.page{max-width:1180px;margin:0 auto;padding:28px}
.hero{background:#fff;border:1px solid var(--line);border-radius:12px;padding:24px;margin-bottom:18px}h1{margin:0 0 6px;font-size:30px}.subtitle{margin:0;color:var(--muted)}h2{margin:26px 0 12px;font-size:21px}h3{margin:0 0 8px;font-size:16px}
.badge{display:inline-flex;border-radius:999px;padding:5px 10px;font-weight:700;font-size:13px;margin-top:14px}.badge.good{color:var(--good);background:#dcfce7}.badge.warning{color:var(--warn);background:#fef3c7}.badge.high{color:var(--bad);background:#fee4e2}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}.metric-label{font-size:12px;color:var(--muted);margin-bottom:4px}.metric-value{font-size:24px;font-weight:750}.metric-note{font-size:12px;color:var(--muted);margin-top:3px}
.findings{display:grid;gap:10px}.finding{border-left:5px solid var(--info);background:#fff;border-radius:10px;padding:14px;border-top:1px solid var(--line);border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.finding.high{border-left-color:var(--bad)}.finding.warning{border-left-color:var(--warn)}.finding.info{border-left-color:var(--info)}.finding.good{border-left-color:var(--good)}.severity{font-size:12px;font-weight:700;text-transform:uppercase;color:var(--muted)}.evidence{color:var(--muted);margin:6px 0}.advice{margin:0}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}th,td{border-bottom:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}th{background:#eef2f7;font-size:13px}tr:last-child td{border-bottom:0}code{background:#f1f5f9;border-radius:5px;padding:2px 5px}.metric-group{background:#fff;border:1px solid var(--line);border-radius:10px;padding:0;margin:10px 0;overflow:hidden}.metric-group summary{cursor:pointer;font-weight:700;display:grid;grid-template-columns:minmax(180px,1fr) minmax(220px,1.6fr) auto;gap:10px;align-items:center;padding:12px 14px}.metric-group table{border-radius:0;border-left:0;border-right:0;border-bottom:0}.group-title{font-size:15px}.group-count{color:var(--muted);font-size:12px}.metric-help{color:var(--muted);margin:0;padding:0 14px 12px}.chart{margin:18px 0;overflow:visible}.plotly-graph-div{background:#fff;border:1px solid var(--line);border-radius:4px}details{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px;margin-top:18px}summary{cursor:pointer;font-weight:700}pre{white-space:pre-wrap;word-break:break-word;background:#f8fafc;border:1px solid var(--line);padding:12px;border-radius:8px;max-height:520px;overflow:auto}
</style>
""",
        "</head><body><main class='page'>",
        "<section class='hero'>",
        "<h1>VO 评估报告</h1>",
        f"<p class='subtitle'>{escape(report_subtitle(report))}</p>",
        f"<span class='badge {status['class_name']}'>{escape(status['label'])}</span>",
        "</section>",
        "<section><h2>需要关注的问题</h2><div class='findings'>",
        "".join(report_finding_html(item) for item in findings),
        "</div></section>",
        "<section><h2>关键指标</h2><div class='grid'>",
        "".join(report_metric_card_html(item) for item in metric_cards),
        "</div></section>",
        "<section><h2>长航程子轨迹误差</h2>",
        segment_table_html(segment_rows),
        "</section>",
        "<section><h2>完整指标统计</h2>",
        "<p class='subtitle'>包含所有计算出的标量统计值；逐帧 per_pose 和子轨迹明细 segment_records 请使用 CSV 下载或查看原始 JSON。</p>",
        metric_table_html(metric_rows),
        "</section>",
        "<section><h2>配置与数据</h2>",
        "<table><tbody>" + "".join(f"<tr><th>{escape(row['label'])}</th><td>{escape(row['value'])}</td></tr>" for row in config_rows) + "</tbody></table>",
        "</section>",
        "<section><h2>可视化</h2>",
    ]
    for idx, fig in enumerate(figures):
        parts.append("<div class='chart'>")
        parts.append(fig.to_html(full_html=False, include_plotlyjs=True if idx == 0 else False))
        parts.append("</div>")
    parts.extend(
        [
            "</section>",
            "<details><summary>原始 JSON 指标</summary>",
            f"<pre>{escape(raw_json)}</pre>",
            "</details>",
            "</main></body></html>",
        ]
    )
    return "\n".join(parts)


if __name__ == "__main__":
    main()
