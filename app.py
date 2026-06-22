"""Streamlit UI for the VO evaluation system.

这个文件只负责交互和展示：
1. 侧边栏收集评估配置。
2. 按固定目录契约读取 data_dir / log_dir。
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
from plotly.subplots import make_subplots

import vo_eval.evaluator as vo_evaluator


EVALUATION_ENTRY_OPTIONS = {
    "VLOC 评估": "vloc",
    "VO 评估": "vo",
}

SEGMENT_POLICY_OPTIONS = {
    "按VO时间戳统一评估（推荐）": "vo_timestamps",
    "按VO连续段逐段评估": "segments",
    "只评估最长连续段": "longest",
}

VLOC_CHART_OPTIONS = [
    ("trajectory3d", "3D 轨迹"),
    ("trajectoryXY", "俯视 NE 轨迹"),
    ("errorDistance", "误差随路程变化"),
    ("heightComparison", "对地高随时间变化"),
    ("navStatusModes", "导航状态信息"),
    ("navVelocity", "导航速度信息"),
    ("navResetCounts", "导航 reset 计数"),
    ("vlocStatus", "VLOC 状态信息"),
    ("positionCompareComposite", "NED 随时间变化"),
    ("attitudeCompareComposite", "YPR 随时间变化"),
    ("positionErrorComposite", "NED 误差随时间变化"),
    ("attitudeErrorComposite", "YPR 误差随时间变化"),
]

VLOC_CHART_IDS = tuple(chart_id for chart_id, _label in VLOC_CHART_OPTIONS)

VO_CHART_OPTIONS = [
    ("trajectory3d", "3D 轨迹"),
    ("errorDistance", "ATE 绝对位姿误差"),
    ("navStatusModes", "导航状态信息"),
    ("navVelocity", "导航速度信息"),
    ("navResetCounts", "导航 reset 计数"),
    ("voStatus", "VO 状态信息"),
    ("positionCompareComposite", "位置随时间变化"),
    ("attitudeCompareComposite", "姿态随时间变化"),
    ("positionErrorComposite", "位置误差随时间变化"),
    ("attitudeErrorComposite", "姿态误差随时间变化"),
    ("rpeTranslationTime", "RPE 平移误差"),
    ("rpeRotationTime", "RPE 旋转误差"),
    ("scaleFrameTime", "局部 Sim3 尺度"),
]

VO_CHART_IDS = tuple(chart_id for chart_id, _label in VO_CHART_OPTIONS)


def main() -> None:
    """页面入口：选择 VLOC/VO 流程 -> 输入 data_dir/log_dir -> 调用 evaluator -> 展示 report。"""
    st.set_page_config(page_title="VO 评估系统", layout="wide")
    st.title("VO 评估系统")

    with st.sidebar:
        # 这些控件直接映射到 EvaluationConfig：
        # 当前只保留 VO 的 RPE/尺度图间隔可调，其余评估参数走固定默认值。
        st.header("输入设置")
        entry_label = st.radio("评估入口", list(EVALUATION_ENTRY_OPTIONS), index=0)
        entry_mode = EVALUATION_ENTRY_OPTIONS[entry_label]
        data_dir = st.text_input("data_dir", placeholder="/path/to/data_dir")
        log_dir = st.text_input("log_dir", placeholder="/path/to/log_dir")
        st.caption("VLOC 固定读取 data_dir/imu.txt 与 log_dir/vloc.txt；VO 固定读取 data_dir/imu.txt 与 log_dir/vo.txt。")
        if entry_mode == "vloc":
            st.caption("VLOC 固定使用 GT 插值到 VLOC 时间戳，最大 GT 插值间隔 1.0 s；超过 1.0 s 的 VLOC 帧直接丢弃。")
            rpe_delta_value = 1.0
            rpe_delta_unit_label = "f"
            scale_delta_value = 1.0
            scale_delta_unit_label = "f"
            segment_text = "50,100,200,500,1000,2000,5000"
            max_segments = 10000
            segment_step = 10
            length_tolerance = 0.05
            segment_policy_label = "按VO时间戳统一评估（推荐）"
            discontinuity_step = 100.0
            discontinuity_gap = 5.0
            divergence_abs = 30.0
            divergence_rel = 3.0
        if entry_mode == "vo":
            st.caption("VO 固定使用 GT 插值到 VO 时间戳，最大 GT 插值间隔 1.0 s；按 reset_count 有效连续段分别做 Sim3，不允许外推，时间偏移固定为 0。")
            rpe_value_col, rpe_unit_col = st.columns([2, 1])
            with rpe_value_col:
                rpe_delta_value = st.number_input("RPE 统计间隔", value=1.0, min_value=0.001, step=1.0)
            with rpe_unit_col:
                rpe_delta_unit_label = st.selectbox("单位", ["f", "m"], index=0)
            scale_value_col, scale_unit_col = st.columns([2, 1])
            with scale_value_col:
                scale_delta_value = st.number_input("尺度图间隔", value=1.0, min_value=0.001, step=1.0)
            with scale_unit_col:
                scale_delta_unit_label = st.selectbox("单位 ", ["f", "m"], index=0)
            segment_text = "50,100,200,500,1000,2000,5000"
            max_segments = 10000
            segment_step = 10
            length_tolerance = 0.05
            segment_policy_label = "按VO连续段逐段评估"
            discontinuity_step = 100.0
            discontinuity_gap = 5.0
            divergence_abs = 30.0
            divergence_rel = 3.0

        selected_vloc_chart_ids = set(VLOC_CHART_IDS)
        selected_vo_chart_ids = set(VO_CHART_IDS)
        if entry_mode == "vloc":
            selected_vloc_chart_ids = show_vloc_chart_directory()
        if entry_mode == "vo":
            selected_vo_chart_ids = show_chart_directory("vo", VO_CHART_OPTIONS)

    st.subheader(entry_label)

    if not data_dir or not log_dir:
        st.info("先填写 `data_dir` 和 `log_dir`，再运行评估。")
        show_metric_catalog()
        return

    try:
        # Streamlit 热更新有时不会重载普通 Python 模块。
        # 每次评估前 reload evaluator，确保页面使用最新的解析/指标逻辑。
        evaluator = latest_evaluator()
        segment_lengths = parse_float_list(segment_text)
        common_cfg = dict(
            rpe_delta_frames=max(1, int(round(float(rpe_delta_value)))) if rpe_delta_unit_label == "f" else 1,
            rpe_delta_value=float(rpe_delta_value),
            rpe_delta_unit="frames" if rpe_delta_unit_label == "f" else "meters",
            rpe_distance_tolerance_ratio=0.05,
            scale_delta_value=float(scale_delta_value),
            scale_delta_unit="frames" if scale_delta_unit_label == "f" else "meters",
            scale_distance_tolerance_ratio=0.05,
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
        if entry_mode == "vloc":
            cfg = evaluator.EvaluationConfig(
                alignment="none",
                orientation_correction="none",
                association_mode="interpolate_gt",
                max_time_diff_s=None,
                max_interpolation_gap_s=1.0,
                allow_extrapolation=False,
                interpolate_rotation=True,
                interpolation_position_method="linear",
                interpolation_rotation_method="slerp",
                time_offset_s=0.0,
                **common_cfg,
            )
        else:
            cfg = evaluator.EvaluationConfig(
                alignment="sim3",
                orientation_correction="none",
                association_mode="interpolate_gt",
                max_time_diff_s=None,
                max_interpolation_gap_s=1.0,
                allow_extrapolation=False,
                interpolate_rotation=True,
                interpolation_position_method="linear",
                interpolation_rotation_method="slerp",
                time_offset_s=0.0,
                **common_cfg,
            )
        if entry_mode == "vloc":
            bundle = evaluator.load_vloc_evaluation_bundle(data_dir, log_dir)
            report = evaluator.evaluate_vloc_bundle(bundle, cfg)
        else:
            bundle = evaluator.load_vo_evaluation_bundle(data_dir, log_dir)
            report = evaluator.evaluate_vo_bundle(bundle, cfg)
    except Exception as exc:
        st.error(f"评估失败：{exc}")
        return

    show_summary(report, entry_mode)
    show_visuals(report, entry_mode, selected_vloc_chart_ids, selected_vo_chart_ids)
    show_tables_and_downloads(report)


def latest_evaluator():
    return importlib.reload(vo_evaluator)


def evaluation_export_filename(report: dict[str, Any], kind: str, extension: str) -> str:
    """生成导出文件名：数据目录 + 入口模式 + 导出类型。

    例如 2839_traj_vloc_evaluation_report.html。
    如果 data_dir 和 log_dir 名不同，文件名保留两者，避免离线文件混淆。
    """
    inputs = report.get("inputs") or {}
    entry_mode = sanitize_filename_part(inputs.get("entry_mode") or "vloc") or "vloc"
    data_name = meaningful_directory_name(inputs.get("data_dir_name"))
    log_name = meaningful_directory_name(inputs.get("log_dir_name"))
    if data_name and log_name and data_name != log_name:
        dataset = f"{data_name}__{log_name}"
    else:
        dataset = log_name or data_name
    prefix = f"{dataset}_{entry_mode}" if dataset else entry_mode
    return f"{prefix}_{sanitize_filename_part(kind)}.{sanitize_filename_part(extension)}"


def meaningful_directory_name(value: Any) -> str:
    """忽略 data_dir/log_dir 这种固定目录名，只保留真实数据集名。"""
    name = sanitize_filename_part(value)
    if name.lower() in {"data_dir", "log_dir"}:
        return ""
    return name


def sanitize_filename_part(value: Any) -> str:
    """清理单个文件名片段，避免浏览器/系统不接受的字符。"""
    text = str(value or "").strip()
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


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
        ("覆盖率/成功率/丢帧", "matched poses、覆盖率、最大时间间隔；看算法是否完整跑完"),
        ("海拔/垂直误差", "z 方向 RMSE/bias/p95；无人机配送必须单独看"),
        ("水平误差", "XY 平面误差；对应导航和投递位置偏差"),
        ("姿态/航向误差", "orientation/yaw error；影响航向控制和相机朝向"),
        ("速度分箱误差", "按飞行速度统计误差；高速长航段通常更难"),
        ("运行资源", "每帧时间、FPS、CPU、内存；部署到机载算力时需要"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["指标", "用途"]), use_container_width=True, hide_index=True)


def show_summary(report: dict[str, Any], entry_mode: str) -> None:
    """顶部指标卡。

    页面展示顺序和 README “运行结果截图指标卡与代码/公式对应”保持一致：
    #01 ATE RMSE 到 #15 耗时。这里只负责展示，不改变 evaluator 计算结果。
    """
    summary = report["summary"]
    ate = report["ate_position_m"] or {}
    vertical = report["ate_vertical_m"] or {}
    rpe = (report["rpe_frame_delta"].get("translation_m") or {})
    orientation_info = report.get("orientation_correction", {})
    alignment = report.get("alignment", {})
    breaks = nested(report, "discontinuities", "all_matches", "break_count", default=0)
    vloc_summary = nested(report, "vloc_details", "summary", default={}) or {}

    st.subheader("VLOC 运行结果" if entry_mode == "vloc" else "VO 运行结果")
    vo_cards = [
        {
            "label": "#01 ATE RMSE",
            "value": report_value(ate.get("rmse"), "m"),
            "help": f"{report_number(100 * ate.get('rmse', math.nan) / summary.get('gt_path_length_m', math.nan))} % 路程；p95 {report_value(ate.get('p95'), 'm')}",
        },
        {
            "label": "#02 RPE RMSE",
            "value": report_value(rpe.get("rmse"), "m"),
            "help": f"{rpe_delta_label(report.get('rpe_frame_delta', {}))}；p95 {report_value(rpe.get('p95'), 'm')}",
        },
        {
            "label": "#03 长航程路程",
            "value": report_value(summary.get("gt_path_length_m"), "m"),
            "help": f"{report_value(summary.get('duration_s'), 's')} / {summary.get('matched_poses', 'N/A')} 帧",
        },
        {
            "label": "#04 垂直 RMSE",
            "value": report_value(vertical.get("rmse"), "m"),
            "help": f"p95 {report_value(vertical.get('p95'), 'm')}",
        },
        {
            "label": "#05 GT 覆盖率",
            "value": report_value(100 * summary.get("gt_pose_coverage_ratio", summary.get("coverage_ratio", math.nan)), "%"),
            "help": "插值模式按有效评估时间 / GT 全时长解释",
        },
        {
            "label": "#06 Raw 尺度比",
            "value": report_number(summary.get("raw_path_scale_ratio_est_over_gt")),
            "help": "VO 原始路程 / GT 路程",
        },
        {
            "label": "#07 对齐尺度",
            "value": report_number(alignment.get("scale")),
            "help": scale_range_text(alignment),
        },
        {
            "label": "#08 匹配位姿",
            "value": report_value(summary.get("matched_poses")),
            "help": f"{summary.get('original_matched_poses', 'N/A')} 原始匹配",
        },
        {
            "label": "#09 VO 匹配率",
            "value": report_value(100 * summary.get("est_pose_coverage_ratio", math.nan), "%"),
            "help": f"{summary.get('matched_poses', 'N/A')} / {summary.get('est_poses', 'N/A')} 帧",
        },
        {
            "label": "#10 断点数量",
            "value": report_value(breaks),
            "help": f"策略 {nested(report, 'discontinuities', 'selected_segment', 'policy', default='N/A')}",
        },
        {
            "label": "#11 姿态修正",
            "value": orientation_correction_label(orientation_info),
            "help": orientation_summary_label(orientation_info),
        },
        {
            "label": "#12 耗时",
            "value": report_value(summary.get("duration_s"), "s"),
            "help": "有效评估窗口，不是算法运行耗时",
        },
    ]
    vloc_cards = [
        {
            "label": "#01 ATE RMSE",
            "value": report_value(ate.get("rmse"), "m"),
            "help": f"{report_number(100 * ate.get('rmse', math.nan) / summary.get('gt_path_length_m', math.nan))} % 路程；p95 {report_value(ate.get('p95'), 'm')}",
        },
        {
            "label": "#02 长航程路程",
            "value": report_value(summary.get("gt_path_length_m"), "m"),
            "help": f"{report_value(summary.get('duration_s'), 's')} / {summary.get('matched_poses', 'N/A')} 帧",
        },
        {
            "label": "#03 垂直 RMSE",
            "value": report_value(vertical.get("rmse"), "m"),
            "help": f"p95 {report_value(vertical.get('p95'), 'm')}",
        },
        {
            "label": "#04 GT 覆盖率",
            "value": report_value(100 * summary.get("gt_pose_coverage_ratio", summary.get("coverage_ratio", math.nan)), "%"),
            "help": "插值模式按有效评估时间 / GT 全时长解释",
        },
        {
            "label": "#05 匹配位姿",
            "value": report_value(summary.get("matched_poses")),
            "help": f"{summary.get('original_matched_poses', 'N/A')} 原始匹配",
        },
        {
            "label": "#06 VLOC 匹配率",
            "value": report_value(100 * summary.get("est_pose_coverage_ratio", math.nan), "%"),
            "help": f"{summary.get('matched_poses', 'N/A')} / {summary.get('est_poses', 'N/A')} 帧",
        },
        {
            "label": "#07 断点数量",
            "value": report_value(breaks),
            "help": f"策略 {nested(report, 'discontinuities', 'selected_segment', 'policy', default='N/A')}",
        },
        {
            "label": "#08 mean_error_pos_xy",
            "value": report_value(vloc_summary.get("mean_error_pos_xy"), "m"),
            "help": "逐帧水平位置误差范数的平均值",
        },
        {
            "label": "#09 mean_error_pos_z",
            "value": report_value(vloc_summary.get("mean_error_pos_z"), "m"),
            "help": "逐帧垂直位置误差绝对值的平均值",
        },
        {
            "label": "#10 mean_error_euler",
            "value": report_value(vloc_summary.get("mean_error_euler"), "deg"),
            "help": "逐帧欧拉角误差范数 sqrt(yaw^2 + pitch^2 + roll^2) 的平均值",
        },
        {
            "label": "#11 max_error_pos_xy",
            "value": report_value(vloc_summary.get("max_error_pos_xy"), "m"),
            "help": "逐帧水平位置误差范数的最大值",
        },
        {
            "label": "#12 max_error_pos_z",
            "value": report_value(vloc_summary.get("max_error_pos_z"), "m"),
            "help": "逐帧垂直位置误差绝对值的最大值",
        },
        {
            "label": "#13 max_error_euler",
            "value": report_value(vloc_summary.get("max_error_euler"), "deg"),
            "help": "逐帧欧拉角误差范数的最大值",
        },
        {
            "label": "#14 耗时",
            "value": report_value(summary.get("duration_s"), "s"),
            "help": "有效评估窗口，不是算法运行耗时",
        },
    ]
    cards = vloc_cards if entry_mode == "vloc" else vo_cards

    for start in range(0, len(cards), 5):
        cols = st.columns(5)
        for col, item in zip(cols, cards[start : start + 5]):
            col.metric(item["label"], item["value"], help=item["help"])

    if entry_mode == "vo" and orientation_info.get("auto") and orientation_info.get("selected"):
        st.info(
            f"自动姿态修正选择：{orientation_info.get('selected')}，"
            f"score={orientation_info.get('best_score', math.nan):.3f}。"
            "该选择只用于评估坐标系/外参修正，不会改变原始数据。"
        )

    raw_ratio = summary.get("raw_path_scale_ratio_est_over_gt")
    align_info = report.get("alignment", {})
    align_mode = align_info.get("base_mode", align_info.get("mode"))
    if entry_mode == "vo" and raw_ratio is not None and math.isfinite(raw_ratio) and align_mode == "se3" and not 0.8 <= raw_ratio <= 1.25:
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


def rpe_delta_label(rpe_info: dict[str, Any]) -> str:
    unit = rpe_info.get("delta_unit")
    if unit == "meters":
        tol = rpe_info.get("distance_tolerance_percent")
        tol_text = f" ±{report_number(tol)}%" if tol is not None and math.isfinite(float(tol)) else ""
        return f"Δ={report_value(rpe_info.get('delta_distance_m'), 'm')}{tol_text}"
    if unit == "frames":
        return f"Δ={report_value(rpe_info.get('delta_frames'), 'frames')}"
    return f"Δ={rpe_info.get('delta_frames', 'N/A')} frames"


def orientation_correction_label(info: dict[str, Any]) -> str:
    selected = info.get("selected") or "none"
    requested = info.get("requested")
    if info.get("auto") and requested != selected:
        return f"auto -> {selected}"
    return str(selected)


def orientation_summary_label(info: dict[str, Any]) -> str:
    """README #14 姿态修正卡片的备注文本。"""
    if info.get("auto"):
        return f"自动候选评分 {report_number(info.get('best_score'))}"
    return f"请求 {info.get('requested', 'N/A')}"


def show_visuals(
    report: dict[str, Any],
    entry_mode: str,
    selected_vloc_chart_ids: set[str] | None = None,
    selected_vo_chart_ids: set[str] | None = None,
) -> None:
    """可视化区域。

    图表与指标对应：
    - 3D 轨迹：per_pose 中 GT 和对齐后的 VO 坐标。
    - 绝对位姿误差：per_pose.error_m / horizontal_error_m。
    - 导航/VO 状态：vo_details.nav_status / vo_details.vo_status。
    - x/y/z/yaw/pitch/roll 随时间变化：用于逐轴检查 GT 和 VO 是否同趋势。
    - x/y/z/yaw/pitch/roll 误差随时间变化：用于定位某个时间段的单轴异常。
    - RPE 平移/旋转误差随时间变化：使用当前 RPE 帧数或距离配置。
    """
    if entry_mode == "vloc":
        show_vloc_visuals(report, selected_vloc_chart_ids)
        return

    per_pose = report["per_pose"]
    segment_records = report["segment_records"]
    trajectory_exports = report.get("trajectory_exports") or {}
    details = report.get("vo_details", {})
    nav_status = pd.DataFrame(details.get("nav_status", []))
    vo_status = pd.DataFrame(details.get("vo_status", []))
    rpe_per_frame = pd.DataFrame(trajectory_exports.get("rpe_per_frame", pd.DataFrame()))
    scale_per_frame = pd.DataFrame(trajectory_exports.get("scale_per_frame", pd.DataFrame()))

    fig3d = make_trajectory_3d(per_pose)
    fig_error = make_error_distance(per_pose)
    nav_mode_fig = make_vloc_multi_series(
        nav_status,
        "导航状态信息",
        [("flight_mode", "flight_mode"), ("navi_mode", "navi_mode"), ("rtk_yaw", "rtk_yaw"), ("rtk_alti", "rtk_alti")],
        "state",
    )
    nav_velocity_fig = make_composite_single_time_series(
        nav_status,
        "导航速度信息",
        [
            ("vx", "vx", "m/s", False),
            ("vy", "vy", "m/s", False),
            ("vz", "vz", "m/s", False),
            ("velocity_norm", "velocity_norm", "m/s", False),
        ],
    )
    nav_reset_fig = make_vloc_multi_series(
        nav_status,
        "导航 reset 计数",
        [
            ("position_reset_count", "position_reset_count"),
            ("altitude_reset_count", "altitude_reset_count"),
            ("heading_reset_count", "heading_reset_count"),
        ],
        "count",
    )
    vo_status_fig = make_composite_single_time_series(
        vo_status,
        "VO 状态信息",
        [
            ("num_inliers", "num_inliers", "value", False),
            ("is_keyframe", "is_keyframe", "value", False),
            ("time_cost", "time_cost", "ms", False),
            ("reset_count", "reset_count", "value", False),
        ],
    )
    fig_position_compare = make_composite_pair_time_series(
        per_pose,
        "位置随时间变化",
        [
            ("X", "gt_x_m", "est_x_aligned_m", "m", False),
            ("Y", "gt_y_m", "est_y_aligned_m", "m", False),
            ("Z", "gt_z_m", "est_z_aligned_m", "m", False),
        ],
        left_name="Ground truth",
        right_name="VO aligned",
    )
    fig_attitude_compare = make_composite_pair_time_series(
        per_pose,
        "姿态随时间变化",
        [
            ("Yaw", "gt_yaw_deg", "est_yaw_aligned_deg", "deg", True),
            ("Pitch", "gt_pitch_deg", "est_pitch_aligned_deg", "deg", True),
            ("Roll", "gt_roll_deg", "est_roll_aligned_deg", "deg", True),
        ],
        left_name="Ground truth",
        right_name="VO aligned",
    )
    fig_position_error = make_composite_error_time_series(
        per_pose,
        "位置误差随时间变化",
        [
            ("X 误差", "x_error_m", "m", False),
            ("Y 误差", "y_error_m", "m", False),
            ("Z 误差", "z_error_m", "m", False),
        ],
    )
    fig_attitude_error = make_composite_error_time_series(
        per_pose,
        "姿态误差随时间变化",
        [
            ("Yaw 误差", "yaw_error_signed_deg", "deg", True),
            ("Pitch 误差", "pitch_error_signed_deg", "deg", True),
            ("Roll 误差", "roll_error_signed_deg", "deg", True),
        ],
    )
    rpe_time_figs = [
        ("rpeTranslationTime", make_rpe_time_series(rpe_per_frame, "RPE 平移误差随时间变化", "rpe_translation_m", "m")),
        ("rpeRotationTime", make_rpe_time_series(rpe_per_frame, "RPE 旋转误差随时间变化", "rpe_rotation_deg", "deg")),
    ]
    scale_time_figs = [
        ("scaleFrameTime", make_scale_time_series(scale_per_frame)),
    ]

    selected = set(selected_vo_chart_ids) if selected_vo_chart_ids is not None else set(VO_CHART_IDS)

    def plot_selected(figures: list[tuple[str, go.Figure]]) -> None:
        for chart_id, fig in figures:
            if chart_id in selected:
                st.plotly_chart(fig, use_container_width=True)

    st.subheader("VO 可视化")
    trajectory_figs = [
        ("trajectory3d", fig3d),
        ("errorDistance", fig_error),
    ]
    status_figs = [
        ("navStatusModes", nav_mode_fig),
        ("navVelocity", nav_velocity_fig),
        ("navResetCounts", nav_reset_fig),
        ("voStatus", vo_status_fig),
    ]
    comparison_figs = [
        ("positionCompareComposite", fig_position_compare),
        ("attitudeCompareComposite", fig_attitude_compare),
        ("positionErrorComposite", fig_position_error),
        ("attitudeErrorComposite", fig_attitude_error),
    ]
    plot_selected(trajectory_figs)

    if selected.intersection(chart_id for chart_id, _fig in status_figs):
        st.markdown("#### 导航 / VO 状态")
        plot_selected(status_figs)

    if selected.intersection(chart_id for chart_id, _fig in comparison_figs):
        st.markdown("#### Nav / VO 随时间变化与误差")
        plot_selected(comparison_figs)

    if selected.intersection(chart_id for chart_id, _fig in rpe_time_figs):
        st.markdown("#### RPE 随时间变化")
        plot_selected(rpe_time_figs)

    if selected.intersection(chart_id for chart_id, _fig in scale_time_figs):
        st.markdown("#### 尺度随时间变化")
        plot_selected(scale_time_figs)

    all_figs = [
        *trajectory_figs,
        *status_figs,
        *comparison_figs,
        *rpe_time_figs,
        *scale_time_figs,
    ]
    if not segment_records.empty:
        with st.expander("按距离子轨迹原始记录"):
            st.dataframe(segment_records, use_container_width=True, hide_index=True)

    html_figs = [fig for chart_id, fig in all_figs if chart_id in selected]
    html = build_html_report(report, html_figs)
    st.download_button(
        "下载 HTML 可视化报告",
        html,
        file_name=evaluation_export_filename(report, "evaluation_report", "html"),
        mime="text/html",
    )


def show_vloc_chart_directory() -> set[str]:
    """VLOC 图表目录：控制右侧 12 张 VLOC 图的显示/隐藏。"""
    return show_chart_directory("vloc", VLOC_CHART_OPTIONS)


def show_chart_directory(entry_mode: str, options: list[tuple[str, str]]) -> set[str]:
    """通用图表目录：VLOC/VO 都用 3 列小方块控制右侧图表。"""
    label = entry_mode.upper()
    chart_ids = tuple(chart_id for chart_id, _label in options)
    st.header("图表目录")
    st.caption(f"选择要在右侧展示的 {label} 图表；评估完成后默认全部打开。")
    for chart_id in chart_ids:
        key = f"{entry_mode}_chart_{chart_id}"
        if key not in st.session_state:
            st.session_state[key] = True

    select_col, clear_col = st.columns(2)
    if select_col.button("全选", key=f"{entry_mode}_chart_select_all"):
        for chart_id in chart_ids:
            st.session_state[f"{entry_mode}_chart_{chart_id}"] = True
    if clear_col.button("清除", key=f"{entry_mode}_chart_clear"):
        for chart_id in chart_ids:
            st.session_state[f"{entry_mode}_chart_{chart_id}"] = False

    selected: set[str] = set()
    for start in range(0, len(options), 3):
        columns = st.columns(3)
        for column, (chart_id, chart_label) in zip(columns, options[start : start + 3]):
            with column:
                if st.checkbox(chart_label, key=f"{entry_mode}_chart_{chart_id}"):
                    selected.add(chart_id)
    return selected


def show_vloc_visuals(report: dict[str, Any], selected_chart_ids: set[str] | None = None) -> None:
    """VLOC 专用可视化页面。

    VLOC 需求文档要求按 nav/vloc 对比展示：
    - nav 状态：flight_mode/navi_mode/rtk_yaw/rtk_alti/reset/速度；
    - vloc 状态：vloc_mode/num_inliers/reset_count；
    - nav-vloc 位置、姿态、height 对比；
    - nav - vloc 的位置误差和 R_ref^-1 R_est 的姿态误差。
    """
    details = report.get("vloc_details", {})
    comparison = pd.DataFrame(details.get("comparison", []))
    nav_status = pd.DataFrame(details.get("nav_status", []))
    vloc_status = pd.DataFrame(details.get("vloc_status", []))

    fig3d = make_vloc_trajectory_3d(comparison)
    fig_xy = make_vloc_trajectory_xy(comparison)
    fig_error = make_vloc_error_distance(comparison)
    fig_height = make_vloc_multi_series(
        comparison,
        "对地高随时间变化",
        [("nav_height_m", "nav height"), ("vloc_height_m", "vloc height")],
        "height m",
    )
    nav_mode_fig = make_vloc_multi_series(
        nav_status,
        "导航状态信息",
        [("flight_mode", "flight_mode"), ("navi_mode", "navi_mode"), ("rtk_yaw", "rtk_yaw"), ("rtk_alti", "rtk_alti")],
        "state",
    )
    nav_velocity_fig = make_composite_single_time_series(
        nav_status,
        "导航速度信息",
        [
            ("vx", "vx", "m/s", False),
            ("vy", "vy", "m/s", False),
            ("vz", "vz", "m/s", False),
            ("velocity_norm", "velocity_norm", "m/s", False),
        ],
    )
    nav_reset_fig = make_vloc_multi_series(
        nav_status,
        "导航 reset 计数",
        [
            ("position_reset_count", "position_reset_count"),
            ("altitude_reset_count", "altitude_reset_count"),
            ("heading_reset_count", "heading_reset_count"),
        ],
        "count",
    )
    vloc_status_fig = make_composite_single_time_series(
        vloc_status,
        "VLOC 状态信息",
        [
            ("vloc_mode", "vloc_mode", "value", False),
            ("num_inliers", "num_inliers", "value", False),
            ("reset_count", "reset_count", "value", False),
        ],
    )
    fig_position_compare = make_composite_pair_time_series(
        comparison,
        "NED 随时间变化",
        [
            ("N", "nav_n_m", "vloc_n_m", "m", False),
            ("E", "nav_e_m", "vloc_e_m", "m", False),
            ("D", "nav_d_m", "vloc_d_m", "m", False),
        ],
        left_name="nav",
        right_name="vloc",
    )
    fig_attitude_compare = make_composite_pair_time_series(
        comparison,
        "YPR 随时间变化",
        [
            ("Yaw", "nav_yaw_deg", "vloc_yaw_deg", "deg", True),
            ("Pitch", "nav_pitch_deg", "vloc_pitch_deg", "deg", True),
            ("Roll", "nav_roll_deg", "vloc_roll_deg", "deg", True),
        ],
        left_name="nav",
        right_name="vloc",
    )
    fig_position_error = make_composite_error_time_series(
        comparison,
        "NED 误差随时间变化",
        [
            ("N 误差", "position_error_n_m", "m", False),
            ("E 误差", "position_error_e_m", "m", False),
            ("D 误差", "position_error_d_m", "m", False),
        ],
    )
    fig_attitude_error = make_composite_error_time_series(
        comparison,
        "YPR 误差随时间变化",
        [
            ("Yaw 误差", "attitude_error_yaw_deg", "deg", True),
            ("Pitch 误差", "attitude_error_pitch_deg", "deg", True),
            ("Roll 误差", "attitude_error_roll_deg", "deg", True),
        ],
    )

    selected = selected_chart_ids if selected_chart_ids is not None else set(VLOC_CHART_IDS)
    selected = set(selected)

    def plot_selected(figures: list[tuple[str, go.Figure]]) -> None:
        for chart_id, fig in figures:
            if chart_id in selected:
                st.plotly_chart(fig, use_container_width=True)

    st.subheader("VLOC 可视化")
    trajectory_figs = [
        ("trajectory3d", fig3d),
        ("trajectoryXY", fig_xy),
        ("errorDistance", fig_error),
        ("heightComparison", fig_height),
    ]
    status_figs = [
        ("navStatusModes", nav_mode_fig),
        ("navVelocity", nav_velocity_fig),
        ("navResetCounts", nav_reset_fig),
        ("vlocStatus", vloc_status_fig),
    ]
    comparison_figs = [
        ("positionCompareComposite", fig_position_compare),
        ("attitudeCompareComposite", fig_attitude_compare),
        ("positionErrorComposite", fig_position_error),
        ("attitudeErrorComposite", fig_attitude_error),
    ]
    plot_selected(trajectory_figs)
    if selected.intersection(chart_id for chart_id, _fig in status_figs):
        st.markdown("#### 导航与 VLOC 状态")
        plot_selected(status_figs)
    if selected.intersection(chart_id for chart_id, _fig in comparison_figs):
        st.markdown("#### Nav / VLOC 随时间变化与误差")
        plot_selected(comparison_figs)

    if not comparison.empty:
        with st.expander("VLOC 逐帧对比明细"):
            st.dataframe(comparison, use_container_width=True, hide_index=True)

    html_figs = [fig for chart_id, fig in [*trajectory_figs, *status_figs, *comparison_figs] if chart_id in selected]
    html = build_html_report(report, html_figs)
    st.download_button(
        "下载 HTML 可视化报告",
        html,
        file_name=evaluation_export_filename(report, "evaluation_report", "html"),
        mime="text/html",
    )


def show_tables_and_downloads(report: dict[str, Any]) -> None:
    """明细表和导出。

    JSON 导出完整 report；per_pose CSV 导出逐帧误差；
    segment_records CSV 导出每个固定距离子轨迹的原始误差记录。
    """
    st.subheader("明细与导出")
    summary_rows = flatten_report_summary(report)
    st.dataframe(summary_rows, use_container_width=True, hide_index=True)

    col1, col2, col3, col4 = st.columns(4)
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
    col4.download_button(
        "下载轨迹 Excel",
        vo_evaluator.report_to_excel(report),
        file_name=evaluation_export_filename(report, "trajectory_exports", "xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=not bool(report.get("trajectory_exports")),
    )


def make_trajectory_3d(df: pd.DataFrame) -> go.Figure:
    """3D 轨迹图：用于肉眼检查 GT 与 VO aligned 是否重合、是否重置。"""
    fig = go.Figure()
    gt_x, gt_y, gt_z = segmented_values(df, ["gt_x_m", "gt_y_m", "gt_z_m"], segment_col="visual_segment_id")
    est_x, est_y, est_z = segmented_values(df, ["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"], segment_col="visual_segment_id")
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
    add_segment_endpoint_markers_3d(
        fig,
        df,
        ["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"],
        "vo",
        start_color="#9333ea",
        end_color="#ef4444",
        start_symbol="diamond",
        end_symbol="x",
        marker_size=5,
        marker_line_width=1,
        text_size=10,
    )
    fig.update_layout(title="3D 轨迹", scene=dict(xaxis_title="x m", yaxis_title="y m", zaxis_title="z m"), height=460)
    return fig


def make_error_distance(df: pd.DataFrame) -> go.Figure:
    """误差随路程变化：展示 ATE 3D/horizontal 是否随长航程增长。"""
    fig = go.Figure()
    dist_3d, err_3d = segmented_values(df, ["distance_m", "error_m"])
    dist_h, err_h = segmented_values(df, ["distance_m", "horizontal_error_m"])
    fig.add_trace(go.Scatter(x=dist_3d, y=err_3d, mode="lines", name="3D error"))
    fig.add_trace(go.Scatter(x=dist_h, y=err_h, mode="lines", name="horizontal"))
    fig.update_layout(title="ATE 绝对位姿误差", xaxis_title="distance m", yaxis_title="error m", height=360)
    return fig


def make_vloc_trajectory_3d(df: pd.DataFrame) -> go.Figure:
    """VLOC 3D 轨迹图：nav 和 vloc 都使用 body/NED 统一后的坐标。"""
    fig = go.Figure()
    if {"nav_n_m", "nav_e_m", "nav_d_m", "vloc_n_m", "vloc_e_m", "vloc_d_m"}.issubset(df.columns):
        nav_n, nav_e, nav_d = segmented_values(df, ["nav_n_m", "nav_e_m", "nav_d_m"], segment_col="visual_segment_id")
        vloc_n, vloc_e, vloc_d = segmented_values(df, ["vloc_n_m", "vloc_e_m", "vloc_d_m"], segment_col="visual_segment_id")
        fig.add_trace(go.Scatter3d(x=nav_n, y=nav_e, z=nav_d, mode="lines", name="nav"))
        fig.add_trace(go.Scatter3d(x=vloc_n, y=vloc_e, z=vloc_d, mode="lines", name="vloc"))
        add_segment_endpoint_markers_3d(
            fig,
            df,
            ["vloc_n_m", "vloc_e_m", "vloc_d_m"],
            "vloc",
            start_color="#9333ea",
            end_color="#ef4444",
            start_symbol="diamond",
            end_symbol="x",
            marker_size=5,
            marker_line_width=1,
            text_size=10,
        )
    fig.update_layout(title="3D 轨迹", scene=dict(xaxis_title="north m", yaxis_title="east m", zaxis_title="down m"), height=460)
    return fig


def make_vloc_trajectory_xy(df: pd.DataFrame) -> go.Figure:
    """VLOC 俯视轨迹图：N/E 平面路径对比。"""
    fig = go.Figure()
    if {"nav_n_m", "nav_e_m", "vloc_n_m", "vloc_e_m"}.issubset(df.columns):
        nav_n, nav_e = segmented_values(df, ["nav_n_m", "nav_e_m"])
        vloc_n, vloc_e = segmented_values(df, ["vloc_n_m", "vloc_e_m"])
        fig.add_trace(go.Scatter(x=nav_n, y=nav_e, mode="lines", name="nav"))
        fig.add_trace(go.Scatter(x=vloc_n, y=vloc_e, mode="lines", name="vloc"))
    fig.update_layout(title="俯视 NE 轨迹", xaxis_title="north m", yaxis_title="east m", yaxis_scaleanchor="x", height=460)
    return fig


def make_vloc_error_distance(df: pd.DataFrame) -> go.Figure:
    """VLOC 位置误差随 nav 轨迹路程变化。"""
    fig = go.Figure()
    for col, name in [
        ("position_error_3d_m", "3D position error"),
        ("horizontal_position_error_m", "horizontal error"),
        ("vertical_position_error_abs_m", "vertical abs error"),
    ]:
        if {"distance_m", col}.issubset(df.columns):
            distance, values = segmented_values(df, ["distance_m", col])
            fig.add_trace(go.Scatter(x=distance, y=values, mode="lines", name=name))
    fig.update_layout(title="误差随路程变化", xaxis_title="distance m", yaxis_title="error m", height=360)
    return fig


def make_vloc_multi_series(
    df: pd.DataFrame,
    title: str,
    columns: list[tuple[str, str]],
    y_title: str,
) -> go.Figure:
    """VLOC 状态/height 多曲线图。"""
    fig = go.Figure()
    for col, name in columns:
        if {"timestamp", col}.issubset(df.columns):
            timestamps, values = segmented_values(df, ["timestamp", col])
            fig.add_trace(go.Scatter(x=timestamps, y=values, mode="lines", name=name))
    fig.update_layout(title=title, xaxis_title="timestamp s", yaxis_title=y_title, height=360)
    return fig


def make_composite_pair_time_series(
    df: pd.DataFrame,
    title: str,
    series_specs: list[tuple[str, str, str, str, bool]],
    left_name: str,
    right_name: str,
) -> go.Figure:
    """三联图：两组轨迹分量共享一个时间轴，缩放时一起观察。"""
    fig = make_subplots(rows=len(series_specs), cols=1, shared_xaxes=True, subplot_titles=[spec[0] for spec in series_specs], vertical_spacing=0.04)
    for row_idx, (label, left_col, right_col, unit, unwrap_angles) in enumerate(series_specs, start=1):
        left_color, right_color = composite_pair_colors(row_idx - 1)
        if {"timestamp", left_col, right_col}.issubset(df.columns):
            t_left, left_values = segmented_values(df, ["timestamp", left_col])
            t_right, right_values = segmented_values(df, ["timestamp", right_col])
            if unwrap_angles:
                left_values = unwrap_degrees(left_values)
                right_values = unwrap_degrees(right_values)
            fig.add_trace(
                go.Scatter(
                    x=t_left,
                    y=left_values,
                    mode="lines",
                    name=f"{label} {left_name}",
                    legendgroup=f"{label}-{left_name}",
                    showlegend=True,
                    line=dict(color=left_color),
                ),
                row=row_idx,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=t_right,
                    y=right_values,
                    mode="lines",
                    name=f"{label} {right_name}",
                    legendgroup=f"{label}-{right_name}",
                    showlegend=True,
                    line=dict(color=right_color),
                ),
                row=row_idx,
                col=1,
            )
        fig.update_yaxes(title_text=unit, row=row_idx, col=1)
    fig.update_xaxes(title_text="timestamp s", row=len(series_specs), col=1)
    apply_composite_time_interaction(fig, title=title, height=320 * len(series_specs))
    return fig


def composite_pair_colors(row_index: int) -> tuple[str, str]:
    """三联对比图按行分配颜色，避免第三行 D/Roll 两条线太接近。"""
    palette = [
        ("#2563eb", "#16a34a"),
        ("#7c3aed", "#f97316"),
        ("#dc2626", "#0891b2"),
    ]
    return palette[row_index % len(palette)]


def add_segment_endpoint_markers_3d(
    fig: go.Figure,
    df: pd.DataFrame,
    coord_cols: list[str],
    trace_prefix: str,
    start_color: str,
    end_color: str,
    start_symbol: str,
    end_symbol: str,
    marker_size: int = 9,
    marker_line_width: int = 2,
    text_size: int | None = None,
) -> None:
    """在每个连续段的 3D 轨迹首尾加标记，帮助判断断点前后的起止位置。"""
    if df.empty or not set(coord_cols).issubset(df.columns):
        return

    segment_col = "visual_segment_id" if "visual_segment_id" in df.columns else "segment_id"
    groups = df.groupby(segment_col, sort=False) if segment_col in df.columns else [(0, df)]
    starts: list[pd.Series] = []
    ends: list[pd.Series] = []
    for _, group in groups:
        clean = group.dropna(subset=coord_cols)
        if clean.empty:
            continue
        starts.append(clean.iloc[0])
        ends.append(clean.iloc[-1])
    if not starts:
        return

    start_frame = pd.DataFrame(starts)
    end_frame = pd.DataFrame(ends)
    labels = [f"{trace_prefix} S{idx + 1}" for idx in range(len(start_frame))]
    end_labels = [f"{trace_prefix} E{idx + 1}" for idx in range(len(end_frame))]
    marker_common = dict(size=marker_size, line=dict(color="#0f172a", width=marker_line_width))
    textfont = dict(size=text_size) if text_size is not None else None
    fig.add_trace(
        go.Scatter3d(
            x=start_frame[coord_cols[0]],
            y=start_frame[coord_cols[1]],
            z=start_frame[coord_cols[2]],
            mode="markers+text",
            name=f"{trace_prefix} start",
            text=labels,
            textposition="top center",
            textfont=textfont,
            marker={**marker_common, "symbol": start_symbol, "color": start_color},
        )
    )
    fig.add_trace(
        go.Scatter3d(
            x=end_frame[coord_cols[0]],
            y=end_frame[coord_cols[1]],
            z=end_frame[coord_cols[2]],
            mode="markers+text",
            name=f"{trace_prefix} end",
            text=end_labels,
            textposition="bottom center",
            textfont=textfont,
            marker={**marker_common, "symbol": end_symbol, "color": end_color},
        )
    )


def make_composite_error_time_series(
    df: pd.DataFrame,
    title: str,
    series_specs: list[tuple[str, str, str, bool]],
) -> go.Figure:
    """三联图：单组误差分量共享一个时间轴。"""
    fig = make_subplots(rows=len(series_specs), cols=1, shared_xaxes=True, subplot_titles=[spec[0] for spec in series_specs], vertical_spacing=0.04)
    for row_idx, (label, error_col, unit, unwrap_angles) in enumerate(series_specs, start=1):
        if {"timestamp", error_col}.issubset(df.columns):
            timestamps, values = segmented_values(df, ["timestamp", error_col])
            if unwrap_angles:
                values = unwrap_degrees(values)
            fig.add_trace(
                go.Scatter(x=timestamps, y=values, mode="lines", name=label, legendgroup=label, showlegend=False),
                row=row_idx,
                col=1,
            )
        fig.update_yaxes(title_text=unit, row=row_idx, col=1)
    fig.update_xaxes(title_text="timestamp s", row=len(series_specs), col=1)
    apply_composite_time_interaction(fig, title=title, height=320 * len(series_specs))
    return fig


def make_composite_single_time_series(
    df: pd.DataFrame,
    title: str,
    series_specs: list[tuple[str, str, str, bool]],
) -> go.Figure:
    """多联图：同一状态类信号拆成多行，共享时间轴。"""
    fig = make_subplots(rows=len(series_specs), cols=1, shared_xaxes=True, subplot_titles=[spec[0] for spec in series_specs], vertical_spacing=0.04)
    for row_idx, (label, field, unit, unwrap_angles) in enumerate(series_specs, start=1):
        if {"timestamp", field}.issubset(df.columns):
            timestamps, values = segmented_values(df, ["timestamp", field])
            if unwrap_angles:
                values = unwrap_degrees(values)
            fig.add_trace(
                go.Scatter(x=timestamps, y=values, mode="lines", name=label, legendgroup=label, showlegend=False),
                row=row_idx,
                col=1,
            )
        fig.update_yaxes(title_text=unit, row=row_idx, col=1)
    fig.update_xaxes(title_text="timestamp s", row=len(series_specs), col=1)
    apply_composite_time_interaction(fig, title=title, height=270 * len(series_specs))
    return fig


def apply_composite_time_interaction(fig: go.Figure, title: str, height: int) -> None:
    """给多行时间序列统一配置跨子图 hover 虚线和共享时间轴交互。"""
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikedash="dot",
        spikesnap="cursor",
        spikethickness=1,
    )
    fig.update_layout(
        title=title,
        height=height,
        hovermode="x unified",
        hoversubplots="axis",
        hoverdistance=20,
        spikedistance=-1,
    )


def segmented_values(df: pd.DataFrame, cols: list[str], segment_col: str | None = None) -> list[list[float | None]]:
    """Plotly 分段画线辅助函数。

    默认不插入断点，避免 NED/YPR/误差等普通时间序列中间断开。
    只有 3D 轨迹会显式传 visual_segment_id，用断点诊断来断开重置位置。
    """
    if segment_col is None or segment_col not in df.columns:
        return [df[col].tolist() for col in cols]
    outputs: list[list[float | None]] = [[] for _ in cols]
    for _, group in df.groupby(segment_col, sort=False):
        for idx, col in enumerate(cols):
            outputs[idx].extend(group[col].tolist())
            outputs[idx].append(None)
    return outputs


def unwrap_degrees(values: list[float | None]) -> list[float | None]:
    """把角度显示值从 [-180, 180] 展开成连续曲线，避免图上出现边界竖线。"""
    out: list[float | None] = []
    previous_raw: float | None = None
    offset = 0.0
    for value in values:
        if value is None:
            out.append(None)
            previous_raw = None
            offset = 0.0
            continue
        raw = float(value)
        if not math.isfinite(raw):
            out.append(value)
            previous_raw = None
            offset = 0.0
            continue
        if previous_raw is not None:
            delta = raw - previous_raw
            if delta > 180.0:
                offset -= 360.0
            elif delta < -180.0:
                offset += 360.0
        out.append(raw + offset)
        previous_raw = raw
    return out


def make_rpe_time_series(df: pd.DataFrame, title: str, error_col: str, unit: str) -> go.Figure:
    """当前 RPE 帧数/距离配置下，每个起点时间戳对应的 RPE 误差。"""
    fig = go.Figure()
    if {"timestamp", error_col, "rpe_available"}.issubset(df.columns):
        clean = df[df["rpe_available"].astype(bool)].copy()
        clean = clean[pd.to_numeric(clean[error_col], errors="coerce").notna()]
        if not clean.empty:
            timestamps, values = segmented_values(clean, ["timestamp", error_col])
            fig.add_trace(go.Scatter(x=timestamps, y=values, mode="lines+markers", name=error_col))
    fig.update_layout(title=title, xaxis_title="timestamp s", yaxis_title=unit, height=360)
    return fig


def make_scale_time_series(df: pd.DataFrame) -> go.Figure:
    """当前尺度图帧数/距离配置下，每个起点时间戳对应的局部 Sim3 尺度。"""
    fig = go.Figure()
    if {"timestamp", "local_sim3_scale", "scale_available"}.issubset(df.columns):
        clean = df[df["scale_available"].astype(bool)].copy()
        clean = clean[pd.to_numeric(clean["local_sim3_scale"], errors="coerce").notna()]
        if not clean.empty:
            timestamps, values = segmented_values(clean, ["timestamp", "local_sim3_scale"])
            fig.add_trace(go.Scatter(x=timestamps, y=values, mode="lines+markers", name="local_sim3_scale"))
    fig.update_layout(title="局部 Sim3 尺度随时间变化", xaxis_title="timestamp s", yaxis_title="scale", height=360)
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
    vertical = report.get("ate_vertical_m") or {}
    alignment = report.get("alignment") or {}
    breaks = nested(report, "discontinuities", "all_matches", "break_count", default="N/A")
    correction = report.get("orientation_correction") or {}
    return [
        {"label": "#01 ATE RMSE", "value": report_value(ate.get("rmse"), "m"), "note": f"{report_number(100 * ate.get('rmse', math.nan) / summary.get('gt_path_length_m', math.nan))} % 路程；p95 {report_value(ate.get('p95'), 'm')}"},
        {"label": "#02 RPE RMSE", "value": report_value(rpe.get("rmse"), "m"), "note": f"{rpe_delta_label(report.get('rpe_frame_delta', {}))}；p95 {report_value(rpe.get('p95'), 'm')}"},
        {"label": "#03 长航程路程", "value": report_value(summary.get("gt_path_length_m"), "m"), "note": f"{report_value(summary.get('duration_s'), 's')} / {summary.get('matched_poses', 'N/A')} 帧"},
        {"label": "#04 垂直 RMSE", "value": report_value(vertical.get("rmse"), "m"), "note": f"p95 {report_value(vertical.get('p95'), 'm')}"},
        {
            "label": "#05 GT 覆盖率",
            "value": report_value(100 * summary.get("gt_time_coverage_ratio", summary.get("gt_pose_coverage_ratio", math.nan)), "%"),
            "note": "仅表示评估覆盖的 GT 段",
        },
        {"label": "#06 Raw 尺度比", "value": report_number(summary.get("raw_path_scale_ratio_est_over_gt")), "note": "VO 原始路程 / GT 路程"},
        {"label": "#07 对齐尺度", "value": report_number(alignment.get("scale")), "note": scale_range_text(alignment)},
        {"label": "#08 匹配位姿", "value": report_value(summary.get("matched_poses")), "note": f"{summary.get('original_matched_poses', 'N/A')} 原始匹配"},
        {
            "label": "#09 VO 匹配率",
            "value": report_value(100 * summary.get("est_pose_coverage_ratio", math.nan), "%"),
            "note": f"{summary.get('matched_poses', 'N/A')} / {summary.get('est_poses', 'N/A')} 帧",
        },
        {"label": "#10 断点数量", "value": str(breaks), "note": f"策略 {nested(report, 'discontinuities', 'selected_segment', 'policy', default='N/A')}"},
        {"label": "#11 姿态修正", "value": orientation_correction_label(correction), "note": orientation_summary_label(correction)},
        {"label": "#12 耗时", "value": report_value(summary.get("duration_s"), "s"), "note": "有效评估窗口，不是算法运行耗时"},
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
    "rpe_delta_frames": "RPE 间隔帧数（兼容字段）",
    "rpe_delta_value": "RPE 统计间隔数值",
    "rpe_delta_unit": "RPE 统计单位",
    "rpe_distance_tolerance_ratio": "RPE 距离容差比例",
    "scale_delta_value": "尺度图间隔数值",
    "scale_delta_unit": "尺度图统计单位",
    "scale_distance_tolerance_ratio": "尺度图距离容差比例",
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
        "rpe_delta_frames": "RPE 使用的帧间隔兼容字段；新配置优先看 rpe_delta_value 和 rpe_delta_unit。",
        "rpe_delta_value": "RPE 统计间隔数值；配合 rpe_delta_unit 使用，单位可以是帧 f 或距离 m。",
        "rpe_delta_unit": "RPE 统计单位；frames/f 表示按固定帧数，meters/m 表示按 GT 路程窗口。",
        "rpe_distance_tolerance_ratio": "RPE 距离模式的容差比例；例如 0.05 表示 100m 会在 95-105m 候选中选择误差最小的终点。",
        "scale_delta_value": "尺度图统计间隔数值；配合 scale_delta_unit 使用，单位可以是帧 f 或距离 m。",
        "scale_delta_unit": "尺度图统计单位；frames/f 表示按固定帧数，meters/m 表示按 GT 路程窗口。",
        "scale_distance_tolerance_ratio": "尺度图距离模式的容差比例；例如 0.05 表示 100m 会在 95-105m 候选中取 GT 距离最接近 100m 的终点。",
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
