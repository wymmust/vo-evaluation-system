"""Plotly Python 图表定义，从 report dict 提取数据生成交互式图表。

当前主前端在 web/ 下，CLI/HTML fallback 复用这里的 Python 图表构建逻辑。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go


# ===== 颜色方案 =====
_COLOR_GT = "#2563eb"       # 蓝色
_COLOR_ESTIMATE = "#16a34a" # 绿色
_COLOR_ERROR = "#dc2626"    # 红色


def _get_comparison(report: dict[str, Any], entry_mode: str) -> pd.DataFrame:
    """根据 entry_mode 返回正确的 comparison DataFrame。"""
    if entry_mode == "vloc":
        return report.get("vloc_details", {}).get("comparison", pd.DataFrame())
    else:  # vo
        return report.get("vo_details", {}).get("comparison", pd.DataFrame())


def _get_nav_status(report: dict[str, Any], entry_mode: str) -> pd.DataFrame:
    """根据 entry_mode 返回正确的 nav_status DataFrame。"""
    if entry_mode == "vloc":
        return report.get("vloc_details", {}).get("nav_status", pd.DataFrame())
    else:  # vo
        return report.get("vo_details", {}).get("nav_status", pd.DataFrame())


def _no_data_figure(message: str = "暂无数据") -> go.Figure:
    """返回一个简单的"暂无数据"占位图。"""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=16),
    )
    fig.update_layout(
        template="plotly_white",
        hovermode="x unified",
        height=400,
        title="无可用数据",
    )
    return fig


def trajectory3d_figure(report: dict[str, Any], entry_mode: str) -> go.Figure:
    """3D 轨迹散点图：GT（蓝线+标记）vs Estimate（绿线+标记）。"""
    comp = _get_comparison(report, entry_mode)
    if comp.empty:
        return _no_data_figure()

    if entry_mode == "vloc":
        gt_cols = {"x": "nav_n_m", "y": "nav_e_m", "z": "nav_d_m"}
        est_cols = {"x": "vloc_n_m", "y": "vloc_e_m", "z": "vloc_d_m"}
    else:  # vo
        gt_cols = {"x": "nav_x_m", "y": "nav_y_m", "z": "nav_z_m"}
        est_cols = {"x": "vo_x_aligned_m", "y": "vo_y_aligned_m", "z": "vo_z_aligned_m"}

    for col in list(gt_cols.values()) + list(est_cols.values()):
        if col not in comp.columns:
            return _no_data_figure(f"缺少列: {col}")

    fig = go.Figure()

    # GT 轨迹
    fig.add_trace(go.Scatter3d(
        x=comp[gt_cols["x"]],
        y=comp[gt_cols["y"]],
        z=comp[gt_cols["z"]],
        mode="lines+markers",
        name="GT",
        line=dict(color=_COLOR_GT, width=3),
        marker=dict(size=2, color=_COLOR_GT),
    ))

    # Estimate 轨迹
    fig.add_trace(go.Scatter3d(
        x=comp[est_cols["x"]],
        y=comp[est_cols["y"]],
        z=comp[est_cols["z"]],
        mode="lines+markers",
        name="Estimate",
        line=dict(color=_COLOR_ESTIMATE, width=3),
        marker=dict(size=2, color=_COLOR_ESTIMATE),
    ))

    fig.update_layout(
        title="3D 轨迹对比",
        template="plotly_white",
        hovermode="x unified",
        height=600,
        scene=dict(
            xaxis_title="N / X (m)",
            yaxis_title="E / Y (m)",
            zaxis_title="D / Z (m)",
        ),
        legend=dict(orientation="h", y=1.05, x=0),
    )
    return fig


def error_distance_figure(report: dict[str, Any], entry_mode: str) -> go.Figure:
    """误差-距离图：X=distance_m, Y=水平位置误差(VLOC)或3D位置误差(VO)。"""
    comp = _get_comparison(report, entry_mode)
    if comp.empty:
        return _no_data_figure()

    if "distance_m" not in comp.columns:
        return _no_data_figure()

    if entry_mode == "vloc":
        y_col = "horizontal_position_error_m"
        y_label = "水平位置误差 (m)"
    else:  # vo
        y_col = "position_error_3d_m"
        y_label = "3D 位置误差 (m)"

    if y_col not in comp.columns:
        return _no_data_figure(f"缺少列: {y_col}")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=comp["distance_m"],
        y=comp[y_col],
        mode="lines+markers",
        name=y_label,
        line=dict(color=_COLOR_ERROR, width=1),
        marker=dict(size=3, color=_COLOR_ERROR),
    ))

    fig.update_layout(
        title="误差随距离变化",
        xaxis_title="累计距离 (m)",
        yaxis_title=y_label,
        template="plotly_white",
        hovermode="x unified",
        height=400,
        legend=dict(orientation="h", y=1.1, x=0),
    )
    return fig


def nav_status_modes_figure(report: dict[str, Any], entry_mode: str) -> go.Figure:
    """导航状态模式图：flight_mode 随时间变化的阶梯线。"""
    nav_status = _get_nav_status(report, entry_mode)
    if nav_status.empty:
        return _no_data_figure()

    if "timestamp" not in nav_status.columns or "flight_mode" not in nav_status.columns:
        return _no_data_figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=nav_status["timestamp"],
        y=nav_status["flight_mode"],
        mode="lines",
        name="飞行模式",
        line=dict(shape="hv", color=_COLOR_GT, width=2),
    ))

    fig.update_layout(
        title="导航状态模式",
        xaxis_title="时间戳 (s)",
        yaxis_title="飞行模式",
        template="plotly_white",
        hovermode="x unified",
        height=400,
        legend=dict(orientation="h", y=1.1, x=0),
    )
    return fig


def nav_velocity_figure(report: dict[str, Any], entry_mode: str) -> go.Figure:
    """导航速度图：3 个子图 (vx, vy, vz) + velocity_norm。"""
    nav_status = _get_nav_status(report, entry_mode)
    if nav_status.empty:
        return _no_data_figure()

    if "timestamp" not in nav_status.columns:
        return _no_data_figure()

    vel_cols = ["vx", "vy", "vz"]
    has_vel = all(col in nav_status.columns for col in vel_cols)
    has_norm = "velocity_norm" in nav_status.columns

    if not has_vel and not has_norm:
        return _no_data_figure("缺少速度列")

    axis_layout: dict[str, Any] = {}
    rowCount = 3
    colors = [_COLOR_GT, _COLOR_ESTIMATE, _COLOR_ERROR]

    fig = go.Figure()

    for index in range(rowCount):
        axisId = index + 1
        xaxisName = f"xaxis{axisId}"
        yaxisName = f"yaxis{axisId}"
        traceXAxis = f"x{axisId}"
        traceYAxis = f"y{axisId}"
        top = 1 - (index / rowCount)
        bottom = 1 - ((index + 1) / rowCount)

        col = vel_cols[index]
        if col in nav_status.columns:
            fig.add_trace(go.Scatter(
                x=nav_status["timestamp"],
                y=nav_status[col],
                xaxis=traceXAxis,
                yaxis=traceYAxis,
                mode="lines",
                name=col.upper(),
                line=dict(color=colors[index], width=1.5),
            ))

        # 第3个子图额外添加 velocity_norm
        if index == 2 and has_norm:
            fig.add_trace(go.Scatter(
                x=nav_status["timestamp"],
                y=nav_status["velocity_norm"],
                xaxis=traceXAxis,
                yaxis=traceYAxis,
                mode="lines",
                name="速度幅值",
                line=dict(color="#7c3aed", width=1.5, dash="dash"),
            ))

        y_title = {0: "vx (m/s)", 1: "vy (m/s)"}.get(index)
        if index == 2:
            y_title = "vz (m/s) / 速度幅值"

        axis_layout[xaxisName] = dict(
            title="时间戳 (s)" if index == rowCount - 1 else "",
            domain=[0, 1],
            anchor=traceYAxis,
            matches="x" if index > 0 else None,
            showticklabels=index == rowCount - 1,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
            showspikes=False,
        )
        axis_layout[yaxisName] = dict(
            title=y_title,
            domain=[bottom + 0.02, top - 0.02],
            anchor=traceXAxis,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
        )

    fig.update_layout(
        title="导航速度",
        template="plotly_white",
        height=980,
        hovermode="x unified",
        hoversubplots="axis",
        hoverdistance=20,
        spikedistance=-1,
        legend=dict(orientation="h", y=1.05, x=0),
        **axis_layout,
    )
    return fig


def nav_reset_counts_figure(report: dict[str, Any], entry_mode: str) -> go.Figure:
    """导航重置计数图：position/altitude/heading reset_count 阶梯线。"""
    nav_status = _get_nav_status(report, entry_mode)
    if nav_status.empty:
        return _no_data_figure()

    if "timestamp" not in nav_status.columns:
        return _no_data_figure()

    reset_cols = ["position_reset_count", "altitude_reset_count", "heading_reset_count"]
    available_cols = [col for col in reset_cols if col in nav_status.columns]

    if not available_cols:
        return _no_data_figure("缺少重置计数列")

    fig = go.Figure()
    colors = [_COLOR_GT, _COLOR_ESTIMATE, _COLOR_ERROR]
    labels = {
        "position_reset_count": "位置重置",
        "altitude_reset_count": "高度重置",
        "heading_reset_count": "航向重置",
    }

    for i, col in enumerate(available_cols):
        fig.add_trace(go.Scatter(
            x=nav_status["timestamp"],
            y=nav_status[col],
            mode="lines",
            name=labels.get(col, col),
            line=dict(shape="hv", color=colors[i], width=2),
        ))

    fig.update_layout(
        title="导航重置计数",
        xaxis_title="时间戳 (s)",
        yaxis_title="重置次数",
        template="plotly_white",
        hovermode="x unified",
        height=400,
        legend=dict(orientation="h", y=1.1, x=0),
    )
    return fig


def position_compare_composite_figure(report: dict[str, Any], entry_mode: str) -> go.Figure:
    """位置对比复合图：3 个子图 (N/X, E/Y, D/Z)，GT vs Estimate。"""
    comp = _get_comparison(report, entry_mode)
    if comp.empty:
        return _no_data_figure()

    if entry_mode == "vloc":
        axes = [
            ("nav_n_m", "vloc_n_m", "N"),
            ("nav_e_m", "vloc_e_m", "E"),
            ("nav_d_m", "vloc_d_m", "D"),
        ]
    else:  # vo
        axes = [
            ("nav_x_m", "vo_x_aligned_m", "X"),
            ("nav_y_m", "vo_y_aligned_m", "Y"),
            ("nav_z_m", "vo_z_aligned_m", "Z"),
        ]

    for gt_col, est_col, _ in axes:
        if gt_col not in comp.columns or est_col not in comp.columns:
            return _no_data_figure(f"缺少列: {gt_col} 或 {est_col}")

    if "timestamp" not in comp.columns:
        return _no_data_figure()

    axis_layout: dict[str, Any] = {}
    rowCount = 3

    fig = go.Figure()

    for index, (gt_col, est_col, label) in enumerate(axes):
        axisId = index + 1
        xaxisName = f"xaxis{axisId}"
        yaxisName = f"yaxis{axisId}"
        traceXAxis = f"x{axisId}"
        traceYAxis = f"y{axisId}"
        top = 1 - (index / rowCount)
        bottom = 1 - ((index + 1) / rowCount)

        fig.add_trace(go.Scatter(
            x=comp["timestamp"],
            y=comp[gt_col],
            xaxis=traceXAxis,
            yaxis=traceYAxis,
            mode="lines",
            name=f"GT {label}",
            line=dict(color=_COLOR_GT, width=1.5),
        ))
        fig.add_trace(go.Scatter(
            x=comp["timestamp"],
            y=comp[est_col],
            xaxis=traceXAxis,
            yaxis=traceYAxis,
            mode="lines",
            name=f"Estimate {label}",
            line=dict(color=_COLOR_ESTIMATE, width=1.5),
        ))

        axis_layout[xaxisName] = dict(
            title="时间戳 (s)" if index == rowCount - 1 else "",
            domain=[0, 1],
            anchor=traceYAxis,
            matches="x" if index > 0 else None,
            showticklabels=index == rowCount - 1,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
            showspikes=False,
        )
        axis_layout[yaxisName] = dict(
            title=f"{label} (m)",
            domain=[bottom + 0.02, top - 0.02],
            anchor=traceXAxis,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
        )

    fig.update_layout(
        title="位置对比 (GT vs Estimate)",
        template="plotly_white",
        height=980,
        hovermode="x unified",
        hoversubplots="axis",
        hoverdistance=20,
        spikedistance=-1,
        legend=dict(orientation="h", y=1.05, x=0),
        **axis_layout,
    )
    return fig


def attitude_compare_composite_figure(report: dict[str, Any], entry_mode: str) -> go.Figure:
    """姿态对比复合图：3 个子图 (yaw, pitch, roll)，GT vs Estimate。"""
    comp = _get_comparison(report, entry_mode)
    if comp.empty:
        return _no_data_figure()

    att_cols = [
        ("nav_yaw_deg", "vloc_yaw_deg" if entry_mode == "vloc" else "vo_yaw_aligned_deg", "Yaw"),
        ("nav_pitch_deg", "vloc_pitch_deg" if entry_mode == "vloc" else "vo_pitch_aligned_deg", "Pitch"),
        ("nav_roll_deg", "vloc_roll_deg" if entry_mode == "vloc" else "vo_roll_aligned_deg", "Roll"),
    ]

    for gt_col, est_col, _ in att_cols:
        if gt_col not in comp.columns or est_col not in comp.columns:
            return _no_data_figure(f"缺少姿态列: {gt_col} 或 {est_col}")

    if "timestamp" not in comp.columns:
        return _no_data_figure()

    axis_layout: dict[str, Any] = {}
    rowCount = 3

    fig = go.Figure()

    for index, (gt_col, est_col, label) in enumerate(att_cols):
        axisId = index + 1
        xaxisName = f"xaxis{axisId}"
        yaxisName = f"yaxis{axisId}"
        traceXAxis = f"x{axisId}"
        traceYAxis = f"y{axisId}"
        top = 1 - (index / rowCount)
        bottom = 1 - ((index + 1) / rowCount)

        fig.add_trace(go.Scatter(
            x=comp["timestamp"],
            y=comp[gt_col],
            xaxis=traceXAxis,
            yaxis=traceYAxis,
            mode="lines",
            name=f"GT {label}",
            line=dict(color=_COLOR_GT, width=1.5),
        ))
        fig.add_trace(go.Scatter(
            x=comp["timestamp"],
            y=comp[est_col],
            xaxis=traceXAxis,
            yaxis=traceYAxis,
            mode="lines",
            name=f"Estimate {label}",
            line=dict(color=_COLOR_ESTIMATE, width=1.5),
        ))

        axis_layout[xaxisName] = dict(
            title="时间戳 (s)" if index == rowCount - 1 else "",
            domain=[0, 1],
            anchor=traceYAxis,
            matches="x" if index > 0 else None,
            showticklabels=index == rowCount - 1,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
            showspikes=False,
        )
        axis_layout[yaxisName] = dict(
            title=f"{label} (deg)",
            domain=[bottom + 0.02, top - 0.02],
            anchor=traceXAxis,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
        )

    fig.update_layout(
        title="姿态对比 (GT vs Estimate)",
        template="plotly_white",
        height=980,
        hovermode="x unified",
        hoversubplots="axis",
        hoverdistance=20,
        spikedistance=-1,
        legend=dict(orientation="h", y=1.05, x=0),
        **axis_layout,
    )
    return fig


def position_error_composite_figure(report: dict[str, Any], entry_mode: str) -> go.Figure:
    """位置误差复合图：3 个子图 (N/X 误差, E/Y 误差, D/Z 误差)。"""
    comp = _get_comparison(report, entry_mode)
    if comp.empty:
        return _no_data_figure()

    if entry_mode == "vloc":
        error_cols = [
            ("position_error_n_m", "N"),
            ("position_error_e_m", "E"),
            ("position_error_d_m", "D"),
        ]
    else:  # vo
        error_cols = [
            ("position_error_x_m", "X"),
            ("position_error_y_m", "Y"),
            ("position_error_z_m", "Z"),
        ]

    for col, _ in error_cols:
        if col not in comp.columns:
            return _no_data_figure(f"缺少误差列: {col}")

    if "timestamp" not in comp.columns:
        return _no_data_figure()

    axis_layout: dict[str, Any] = {}
    rowCount = 3

    fig = go.Figure()

    for index, (col, label) in enumerate(error_cols):
        axisId = index + 1
        xaxisName = f"xaxis{axisId}"
        yaxisName = f"yaxis{axisId}"
        traceXAxis = f"x{axisId}"
        traceYAxis = f"y{axisId}"
        top = 1 - (index / rowCount)
        bottom = 1 - ((index + 1) / rowCount)

        fig.add_trace(go.Scatter(
            x=comp["timestamp"],
            y=comp[col],
            xaxis=traceXAxis,
            yaxis=traceYAxis,
            mode="lines",
            name=f"{label} 误差",
            line=dict(color=_COLOR_ERROR, width=1.5),
        ))

        axis_layout[xaxisName] = dict(
            title="时间戳 (s)" if index == rowCount - 1 else "",
            domain=[0, 1],
            anchor=traceYAxis,
            matches="x" if index > 0 else None,
            showticklabels=index == rowCount - 1,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
            showspikes=False,
        )
        axis_layout[yaxisName] = dict(
            title="误差 (m)",
            domain=[bottom + 0.02, top - 0.02],
            anchor=traceXAxis,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
        )

    fig.update_layout(
        title="位置误差",
        template="plotly_white",
        height=980,
        hovermode="x unified",
        hoversubplots="axis",
        hoverdistance=20,
        spikedistance=-1,
        legend=dict(orientation="h", y=1.05, x=0),
        **axis_layout,
    )
    return fig


def attitude_error_composite_figure(report: dict[str, Any], entry_mode: str) -> go.Figure:
    """姿态误差复合图：3 个子图 (yaw 误差, pitch 误差, roll 误差)。"""
    comp = _get_comparison(report, entry_mode)
    if comp.empty:
        return _no_data_figure()

    error_cols = [
        ("attitude_error_yaw_deg", "Yaw"),
        ("attitude_error_pitch_deg", "Pitch"),
        ("attitude_error_roll_deg", "Roll"),
    ]

    for col, _ in error_cols:
        if col not in comp.columns:
            return _no_data_figure(f"缺少姿态误差列: {col}")

    if "timestamp" not in comp.columns:
        return _no_data_figure()

    axis_layout: dict[str, Any] = {}
    rowCount = 3

    fig = go.Figure()

    for index, (col, label) in enumerate(error_cols):
        axisId = index + 1
        xaxisName = f"xaxis{axisId}"
        yaxisName = f"yaxis{axisId}"
        traceXAxis = f"x{axisId}"
        traceYAxis = f"y{axisId}"
        top = 1 - (index / rowCount)
        bottom = 1 - ((index + 1) / rowCount)

        fig.add_trace(go.Scatter(
            x=comp["timestamp"],
            y=comp[col],
            xaxis=traceXAxis,
            yaxis=traceYAxis,
            mode="lines",
            name=f"{label} 误差",
            line=dict(color=_COLOR_ERROR, width=1.5),
        ))

        axis_layout[xaxisName] = dict(
            title="时间戳 (s)" if index == rowCount - 1 else "",
            domain=[0, 1],
            anchor=traceYAxis,
            matches="x" if index > 0 else None,
            showticklabels=index == rowCount - 1,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
            showspikes=False,
        )
        axis_layout[yaxisName] = dict(
            title="误差 (deg)",
            domain=[bottom + 0.02, top - 0.02],
            anchor=traceXAxis,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
        )

    fig.update_layout(
        title="姿态误差",
        template="plotly_white",
        height=980,
        hovermode="x unified",
        hoversubplots="axis",
        hoverdistance=20,
        spikedistance=-1,
        legend=dict(orientation="h", y=1.05, x=0),
        **axis_layout,
    )
    return fig


# ==================== VLOC-only charts ====================

def trajectory_xy_figure(report: dict[str, Any]) -> go.Figure:
    """VLOC 俯视 NE 轨迹：X=nav_e_m, Y=nav_n_m (GT); X=vloc_e_m, Y=vloc_n_m (估计)。"""
    vloc_detail = report.get("vloc_details", {})
    comparison = vloc_detail.get("comparison", pd.DataFrame())

    if not isinstance(comparison, pd.DataFrame) or comparison.empty:
        return _no_data_figure("俯视 NE 轨迹（无数据）")

    required_cols = ["nav_e_m", "nav_n_m", "vloc_e_m", "vloc_n_m"]
    for col in required_cols:
        if col not in comparison.columns:
            return _no_data_figure(f"缺少列: {col}")

    gt_e = comparison["nav_e_m"].to_numpy(dtype=float)
    gt_n = comparison["nav_n_m"].to_numpy(dtype=float)
    vloc_e = comparison["vloc_e_m"].to_numpy(dtype=float)
    vloc_n = comparison["vloc_n_m"].to_numpy(dtype=float)

    valid = np.isfinite(gt_e) & np.isfinite(gt_n) & np.isfinite(vloc_e) & np.isfinite(vloc_n)
    gt_e = gt_e[valid]
    gt_n = gt_n[valid]
    vloc_e = vloc_e[valid]
    vloc_n = vloc_n[valid]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=gt_e, y=gt_n,
        mode="lines",
        name="GT (nav)",
        line=dict(color=_COLOR_GT, width=2),
        hovertemplate="E: %{x:.2f} m<br>N: %{y:.2f} m<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=vloc_e, y=vloc_n,
        mode="lines",
        name="VLOC",
        line=dict(color=_COLOR_ESTIMATE, width=2),
        hovertemplate="E: %{x:.2f} m<br>N: %{y:.2f} m<extra></extra>",
    ))

    summary = vloc_detail.get("summary", {})
    traj_len = summary.get("trajectory_length_m", 0)
    fig.add_annotation(
        text=f"GT 轨迹长度: {traj_len:.1f} m",
        showarrow=False,
        xref="paper", yref="paper",
        x=0.01, y=0.99,
        xanchor="left", yanchor="top",
        font=dict(size=10),
    )

    fig.update_layout(
        title="俯视 NE 轨迹对比",
        xaxis_title="东向 E [m]",
        yaxis_title="北向 N [m]",
        template="plotly_white",
        hovermode="x unified",
        legend=dict(x=0, y=1),
    )
    return fig


def height_comparison_figure(report: dict[str, Any]) -> go.Figure:
    """VLOC 高度对比：X=timestamp, Y=nav_height_m (GT) 和 vloc_height_m (估计)。"""
    vloc_detail = report.get("vloc_details", {})
    comparison = vloc_detail.get("comparison", pd.DataFrame())

    if not isinstance(comparison, pd.DataFrame) or comparison.empty:
        return _no_data_figure("高度对比（无数据）")

    required_cols = ["timestamp", "nav_height_m", "vloc_height_m"]
    for col in required_cols:
        if col not in comparison.columns:
            return _no_data_figure(f"缺少列: {col}")

    timestamps = comparison["timestamp"].to_numpy(dtype=float)
    nav_height = comparison["nav_height_m"].to_numpy(dtype=float)
    vloc_height = comparison["vloc_height_m"].to_numpy(dtype=float)

    valid = np.isfinite(timestamps) & np.isfinite(nav_height) & np.isfinite(vloc_height)
    timestamps = timestamps[valid]
    nav_height = nav_height[valid]
    vloc_height = vloc_height[valid]

    if len(timestamps) == 0:
        return _no_data_figure("高度对比（无有效数据）")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=nav_height,
        mode="lines",
        name="GT 高度",
        line=dict(color=_COLOR_GT, width=2),
        hovertemplate="时间: %{x:.3f} s<br>高度: %{y:.2f} m<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=timestamps, y=vloc_height,
        mode="lines",
        name="VLOC 高度",
        line=dict(color=_COLOR_ESTIMATE, width=2),
        hovertemplate="时间: %{x:.3f} s<br>高度: %{y:.2f} m<extra></extra>",
    ))
    fig.update_layout(
        title="对地高度随时间变化",
        xaxis_title="时间戳 [s]",
        yaxis_title="高度 [m]",
        template="plotly_white",
        hovermode="x unified",
        legend=dict(x=0, y=1),
    )
    return fig


def vloc_status_figure(report: dict[str, Any]) -> go.Figure:
    """VLOC 状态信息：3 个子图 — vloc_mode, num_inliers, reset_count vs timestamp。"""
    vloc_detail = report.get("vloc_details", {})
    vloc_status = vloc_detail.get("vloc_status", pd.DataFrame())

    if not isinstance(vloc_status, pd.DataFrame) or vloc_status.empty:
        return _no_data_figure("VLOC 状态（无数据）")

    required_cols = ["timestamp", "vloc_mode", "num_inliers", "reset_count"]
    for col in required_cols:
        if col not in vloc_status.columns:
            return _no_data_figure(f"缺少列: {col}")

    timestamps = vloc_status["timestamp"].to_numpy(dtype=float)
    vloc_mode = vloc_status["vloc_mode"].to_numpy(dtype=float)
    num_inliers = vloc_status["num_inliers"].to_numpy(dtype=float)
    reset_count = vloc_status["reset_count"].to_numpy(dtype=float)

    valid_ts = np.isfinite(timestamps)
    timestamps = timestamps[valid_ts]
    vloc_mode = vloc_mode[valid_ts]
    num_inliers = num_inliers[valid_ts]
    reset_count = reset_count[valid_ts]

    if len(timestamps) == 0:
        return _no_data_figure("VLOC 状态（无有效数据）")

    axis_layout: dict[str, Any] = {}
    rowCount = 3
    status_cols = [
        ("vloc_mode", "模式"),
        ("num_inliers", "内点数量"),
        ("reset_count", "Reset 次数"),
    ]

    fig = go.Figure()

    for index, (col, title) in enumerate(status_cols):
        axisId = index + 1
        xaxisName = f"xaxis{axisId}"
        yaxisName = f"yaxis{axisId}"
        traceXAxis = f"x{axisId}"
        traceYAxis = f"y{axisId}"
        top = 1 - (index / rowCount)
        bottom = 1 - ((index + 1) / rowCount)

        data = {"vloc_mode": vloc_mode, "num_inliers": num_inliers, "reset_count": reset_count}[col]

        fig.add_trace(go.Scatter(
            x=timestamps,
            y=data,
            xaxis=traceXAxis,
            yaxis=traceYAxis,
            mode="lines+markers",
            name=col,
            line=dict(width=2),
            marker=dict(size=4),
        ))

        axis_layout[xaxisName] = dict(
            title="时间戳 [s]" if index == rowCount - 1 else "",
            domain=[0, 1],
            anchor=traceYAxis,
            matches="x" if index > 0 else None,
            showticklabels=index == rowCount - 1,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
            showspikes=False,
        )
        axis_layout[yaxisName] = dict(
            title=title,
            domain=[bottom + 0.02, top - 0.02],
            anchor=traceXAxis,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
        )

    fig.update_layout(
        title="VLOC 状态信息",
        template="plotly_white",
        height=980,
        hovermode="x unified",
        hoversubplots="axis",
        hoverdistance=20,
        spikedistance=-1,
        showlegend=False,
        **axis_layout,
    )
    return fig


# ==================== VO-only charts ====================

def vo_status_figure(report: dict[str, Any]) -> go.Figure:
    """VO 状态信息：3 个子图 — num_inliers, is_keyframe, reset_count vs timestamp。"""
    vo_detail = report.get("vo_details", {})
    vo_status = vo_detail.get("vo_status", pd.DataFrame())

    if not isinstance(vo_status, pd.DataFrame) or vo_status.empty:
        return _no_data_figure("VO 状态（无数据）")

    required_cols = ["timestamp", "num_inliers", "is_keyframe", "reset_count"]
    for col in required_cols:
        if col not in vo_status.columns:
            return _no_data_figure(f"缺少列: {col}")

    timestamps = vo_status["timestamp"].to_numpy(dtype=float)
    num_inliers = vo_status["num_inliers"].to_numpy(dtype=float)
    is_keyframe = vo_status["is_keyframe"].to_numpy(dtype=float)
    reset_count = vo_status["reset_count"].to_numpy(dtype=float)

    valid_ts = np.isfinite(timestamps)
    timestamps = timestamps[valid_ts]
    num_inliers = num_inliers[valid_ts]
    is_keyframe = is_keyframe[valid_ts]
    reset_count = reset_count[valid_ts]

    if len(timestamps) == 0:
        return _no_data_figure("VO 状态（无有效数据）")

    axis_layout: dict[str, Any] = {}
    rowCount = 3
    status_cols = [
        ("num_inliers", "内点数量"),
        ("is_keyframe", "关键帧 (0/1)"),
        ("reset_count", "Reset 次数"),
    ]

    fig = go.Figure()

    for index, (col, title) in enumerate(status_cols):
        axisId = index + 1
        xaxisName = f"xaxis{axisId}"
        yaxisName = f"yaxis{axisId}"
        traceXAxis = f"x{axisId}"
        traceYAxis = f"y{axisId}"
        top = 1 - (index / rowCount)
        bottom = 1 - ((index + 1) / rowCount)

        data = {"num_inliers": num_inliers, "is_keyframe": is_keyframe, "reset_count": reset_count}[col]

        if col == "is_keyframe":
            fig.add_trace(go.Scatter(
                x=timestamps,
                y=data,
                xaxis=traceXAxis,
                yaxis=traceYAxis,
                mode="markers",
                name=col,
                marker=dict(size=4, symbol="square"),
            ))
        else:
            fig.add_trace(go.Scatter(
                x=timestamps,
                y=data,
                xaxis=traceXAxis,
                yaxis=traceYAxis,
                mode="lines+markers",
                name=col,
                line=dict(width=2),
                marker=dict(size=4),
            ))

        axis_layout[xaxisName] = dict(
            title="时间戳 [s]" if index == rowCount - 1 else "",
            domain=[0, 1],
            anchor=traceYAxis,
            matches="x" if index > 0 else None,
            showticklabels=index == rowCount - 1,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
            showspikes=False,
        )
        axis_layout[yaxisName] = dict(
            title=title,
            domain=[bottom + 0.02, top - 0.02],
            anchor=traceXAxis,
            gridcolor="#e8eef7",
            zerolinecolor="#d9e1ec",
            tickvals=[0, 1] if col == "is_keyframe" else None,
        )

    fig.update_layout(
        title="VO 状态信息",
        template="plotly_white",
        height=980,
        hovermode="x unified",
        hoversubplots="axis",
        hoverdistance=20,
        spikedistance=-1,
        showlegend=False,
        **axis_layout,
    )
    return fig


def rpe_translation_time_figure(report: dict[str, Any]) -> go.Figure:
    """RPE 平移误差随时间：X=timestamp, Y=rpe_translation_m (rpe_available==True)。"""
    trajectory_exports = report.get("trajectory_exports", {})
    rpe_per_frame = trajectory_exports.get("rpe_per_frame", pd.DataFrame())

    if not isinstance(rpe_per_frame, pd.DataFrame) or rpe_per_frame.empty:
        return _no_data_figure("RPE 平移（无数据）")

    if "rpe_translation_m" not in rpe_per_frame.columns:
        return _no_data_figure("缺少 rpe_translation_m 列")

    # 过滤 rpe_available 为 True 的样本
    if "rpe_available" in rpe_per_frame.columns:
        mask = rpe_per_frame["rpe_available"].to_numpy(dtype=bool)
        rpe_data = rpe_per_frame[mask]
    else:
        rpe_data = rpe_per_frame

    if rpe_data.empty:
        return _no_data_figure("RPE 平移（无可用数据）")

    if "timestamp" not in rpe_data.columns:
        return _no_data_figure("缺少 timestamp 列")

    timestamps = rpe_data["timestamp"].to_numpy(dtype=float)
    rpe_translation = rpe_data["rpe_translation_m"].to_numpy(dtype=float)

    valid = np.isfinite(timestamps) & np.isfinite(rpe_translation)
    timestamps = timestamps[valid]
    rpe_translation = rpe_translation[valid]

    if len(timestamps) == 0:
        return _no_data_figure("RPE 平移（无有效数据）")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=rpe_translation,
        mode="markers",
        name="RPE 平移",
        marker=dict(color=_COLOR_GT, size=4),
        hovertemplate="时间: %{x:.3f} s<br>RPE 平移: %{y:.4f} m<extra></extra>",
    ))
    fig.update_layout(
        title="RPE 平移误差随时间",
        xaxis_title="时间戳 [s]",
        yaxis_title="RPE 平移误差 [m]",
        template="plotly_white",
        hovermode="x unified",
    )
    return fig


def rpe_rotation_time_figure(report: dict[str, Any]) -> go.Figure:
    """RPE 旋转误差随时间：X=timestamp, Y=rpe_rotation_deg (rpe_available==True)。"""
    trajectory_exports = report.get("trajectory_exports", {})
    rpe_per_frame = trajectory_exports.get("rpe_per_frame", pd.DataFrame())

    if not isinstance(rpe_per_frame, pd.DataFrame) or rpe_per_frame.empty:
        return _no_data_figure("RPE 旋转（无数据）")

    if "rpe_rotation_deg" not in rpe_per_frame.columns:
        return _no_data_figure("缺少 rpe_rotation_deg 列")

    # 过滤 rpe_available 为 True 的样本
    if "rpe_available" in rpe_per_frame.columns:
        mask = rpe_per_frame["rpe_available"].to_numpy(dtype=bool)
        rpe_data = rpe_per_frame[mask]
    else:
        rpe_data = rpe_per_frame

    if rpe_data.empty:
        return _no_data_figure("RPE 旋转（无可用数据）")

    if "timestamp" not in rpe_data.columns:
        return _no_data_figure("缺少 timestamp 列")

    timestamps = rpe_data["timestamp"].to_numpy(dtype=float)
    rpe_rotation = rpe_data["rpe_rotation_deg"].to_numpy(dtype=float)

    valid = np.isfinite(timestamps) & np.isfinite(rpe_rotation)
    timestamps = timestamps[valid]
    rpe_rotation = rpe_rotation[valid]

    if len(timestamps) == 0:
        return _no_data_figure("RPE 旋转（无有效数据）")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=rpe_rotation,
        mode="markers",
        name="RPE 旋转",
        marker=dict(color=_COLOR_ESTIMATE, size=4),
        hovertemplate="时间: %{x:.3f} s<br>RPE 旋转: %{y:.4f} deg<extra></extra>",
    ))
    fig.update_layout(
        title="RPE 旋转误差随时间",
        xaxis_title="时间戳 [s]",
        yaxis_title="RPE 旋转误差 [deg]",
        template="plotly_white",
        hovermode="x unified",
    )
    return fig


def scale_frame_time_figure(report: dict[str, Any]) -> go.Figure:
    """局部 Sim3 尺度随时间：X=timestamp, Y=local_sim3_scale (如果存在 scale_per_frame)。"""
    trajectory_exports = report.get("trajectory_exports", {})
    scale_per_frame = trajectory_exports.get("scale_per_frame", pd.DataFrame())

    if not isinstance(scale_per_frame, pd.DataFrame) or scale_per_frame.empty:
        return _no_data_figure("局部 Sim3 尺度（无数据）")

    if "local_sim3_scale" not in scale_per_frame.columns:
        return _no_data_figure("缺少 local_sim3_scale 列")

    if "timestamp" not in scale_per_frame.columns:
        return _no_data_figure("缺少 timestamp 列")

    timestamps = scale_per_frame["timestamp"].to_numpy(dtype=float)
    local_scale = scale_per_frame["local_sim3_scale"].to_numpy(dtype=float)

    valid = np.isfinite(timestamps) & np.isfinite(local_scale)
    timestamps = timestamps[valid]
    local_scale = local_scale[valid]

    if len(timestamps) == 0:
        return _no_data_figure("局部 Sim3 尺度（无有效数据）")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=local_scale,
        mode="markers",
        name="局部尺度",
        marker=dict(color=_COLOR_ERROR, size=4),
        hovertemplate="时间: %{x:.3f} s<br>尺度: %{y:.6f}<extra></extra>",
    ))
    # 添加 y=1 参考线
    fig.add_hline(
        y=1.0,
        line_dash="dash",
        line_color="gray",
        opacity=0.5,
        annotation_text="理想尺度 (1.0)",
        annotation_position="bottom right",
    )
    fig.update_layout(
        title="局部 Sim3 尺度随时间",
        xaxis_title="时间戳 [s]",
        yaxis_title="局部 Sim3 尺度",
        template="plotly_white",
        hovermode="x unified",
    )
    return fig


# ==================== Dispatch functions ====================

def build_vloc_figures(report: dict[str, Any]) -> list[dict]:
    """生成所有 12 个 VLOC 图表。

    返回格式: [{"id": chart_id, "label": label, "figure": go.Figure}, ...]
    """
    figures = []

    chart_specs = [
        ("trajectory3d", "3D 轨迹", lambda r: trajectory3d_figure(r, "vloc")),
        ("trajectoryXY", "俯视 NE 轨迹", trajectory_xy_figure),
        ("errorDistance", "误差随路程变化", lambda r: error_distance_figure(r, "vloc")),
        ("heightComparison", "对地高随时间变化", height_comparison_figure),
        ("navStatusModes", "导航状态信息", lambda r: nav_status_modes_figure(r, "vloc")),
        ("navVelocity", "导航速度信息", lambda r: nav_velocity_figure(r, "vloc")),
        ("navResetCounts", "导航 reset 计数", lambda r: nav_reset_counts_figure(r, "vloc")),
        ("vlocStatus", "VLOC 状态信息", vloc_status_figure),
        ("positionCompareComposite", "NED 随时间变化", lambda r: position_compare_composite_figure(r, "vloc")),
        ("attitudeCompareComposite", "YPR 随时间变化", lambda r: attitude_compare_composite_figure(r, "vloc")),
        ("positionErrorComposite", "NED 误差随时间变化", lambda r: position_error_composite_figure(r, "vloc")),
        ("attitudeErrorComposite", "YPR 误差随时间变化", lambda r: attitude_error_composite_figure(r, "vloc")),
    ]

    for chart_id, label, figure_fn in chart_specs:
        try:
            fig = figure_fn(report)
            figures.append({
                "id": chart_id,
                "label": label,
                "figure": fig,
            })
        except Exception:
            pass

    return figures


def build_vo_figures(report: dict[str, Any]) -> list[dict]:
    """生成所有 VO 图表。

    返回格式: [{"id": chart_id, "label": label, "figure": go.Figure}, ...]
    """
    figures = []

    chart_specs = [
        ("trajectory3d", "3D 轨迹", lambda r: trajectory3d_figure(r, "vo")),
        ("trajectoryXY", "俯视 NE 轨迹", lambda r: trajectory3d_figure(r, "vo")),  # placeholder
        ("errorDistance", "误差随路程变化", lambda r: error_distance_figure(r, "vo")),
        ("heightComparison", "对地高随时间变化", lambda r: trajectory3d_figure(r, "vo")),  # placeholder
        ("navStatusModes", "导航状态信息", lambda r: nav_status_modes_figure(r, "vo")),
        ("navVelocity", "导航速度信息", lambda r: nav_velocity_figure(r, "vo")),
        ("navResetCounts", "导航 reset 计数", lambda r: nav_reset_counts_figure(r, "vo")),
        ("vlocStatus", "VO 状态信息", vo_status_figure),
        ("positionCompareComposite", "NED 随时间变化", lambda r: position_compare_composite_figure(r, "vo")),
        ("attitudeCompareComposite", "YPR 随时间变化", lambda r: attitude_compare_composite_figure(r, "vo")),
        ("positionErrorComposite", "NED 误差随时间变化", lambda r: position_error_composite_figure(r, "vo")),
        ("attitudeErrorComposite", "YPR 误差随时间变化", lambda r: attitude_error_composite_figure(r, "vo")),
        ("rpeTranslationTime", "RPE 平移误差", rpe_translation_time_figure),
        ("rpeRotationTime", "RPE 旋转误差", rpe_rotation_time_figure),
        ("scaleFrameTime", "局部 Sim3 尺度", scale_frame_time_figure),
    ]

    for chart_id, label, figure_fn in chart_specs:
        try:
            fig = figure_fn(report)
            figures.append({
                "id": chart_id,
                "label": label,
                "figure": fig,
            })
        except Exception:
            pass

    return figures
