"""Streamlit UI for the VO evaluation system.

这个文件只负责交互和展示：
1. 侧边栏收集评估配置。
2. 上传 GT/VO 文件并交给 vo_eval.evaluator 解析和计算。
3. 把 report 中的指标映射到页面指标卡、Plotly 图表和下载文件。

核心计算不在这里，核心指标都由 vo_eval/evaluator.py 产生。
"""

from __future__ import annotations

import importlib
import math
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
        association_label = st.selectbox("时间同步方式", list(ASSOCIATION_OPTIONS), index=0)
        max_time_diff = st.number_input("时间关联最大误差 s（不按时间则填 -1）", value=0.02, min_value=-1.0, step=0.01)
        max_interpolation_gap = st.number_input("GT 插值最大间隔 s（不限制填 -1）", value=1.0, min_value=-1.0, step=0.1)
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
            association_mode=ASSOCIATION_OPTIONS[association_label],
            max_time_diff_s=None if max_time_diff < 0 else float(max_time_diff),
            max_interpolation_gap_s=None if max_interpolation_gap < 0 else float(max_interpolation_gap),
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
    cols = st.columns(3)
    cols[0].metric("时间同步", association_label(assoc))
    metric(cols[1], "最大插值间隔", assoc.get("max_interpolation_gap_s"), "s")
    metric(cols[2], "平均时间差", assoc.get("mean_time_diff_s"), "s")

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
        "rpe_frame_delta",
        "divergence",
        "runtime",
    ]:
        add(key, report.get(key))
    return pd.DataFrame(rows)


def build_html_report(report: dict[str, Any], figures: list[go.Figure]) -> str:
    """生成离线 HTML 报告，包含指标表和 Plotly 图表。"""
    summary = flatten_report_summary(report).to_html(index=False, escape=True)
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><title>VO Evaluation Report</title>",
        "<style>body{font-family:Arial,sans-serif;margin:28px;color:#20242a}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{border:1px solid #d5dbe3;padding:6px 8px;text-align:left}h1,h2{margin:0.6em 0}</style>",
        "</head><body><h1>VO Evaluation Report</h1><h2>Metrics</h2>",
        summary,
        "<h2>Visualizations</h2>",
    ]
    for idx, fig in enumerate(figures):
        parts.append(fig.to_html(full_html=False, include_plotlyjs=True if idx == 0 else False))
    parts.append("</body></html>")
    return "\n".join(parts)


if __name__ == "__main__":
    main()
