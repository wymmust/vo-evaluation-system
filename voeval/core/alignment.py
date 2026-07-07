"""Sim3/Umeyama alignment helpers."""

from __future__ import annotations

from typing import Any

import numpy as np

def identity_alignment() -> dict[str, Any]:
    """VLOC 固定不做轨迹对齐，直接统计 nav-vloc 坐标差。"""
    return _alignment_dict("none", 1.0, np.eye(3), np.zeros(3))
def sim3_alignment(gt_pos: np.ndarray, est_pos: np.ndarray) -> dict[str, Any]:
    """VO 固定使用 Sim3，把 estimate 对齐到 GT/reference 坐标系。

    指标对应：
    - alignment["scale"] 最终显示为页面“对齐尺度”。
    - 所有 VO ATE/RPE 都基于 Sim3 后的 est_pos_aligned 计算。

    来源对应：
    - Sturm12 的 ATE 需要先把估计轨迹配准到 GT 后再算绝对误差。
    - Zhang18 明确说明单目无尺度通常看 Sim3。
    """
    scale, rot, trans = umeyama_alignment(est_pos, gt_pos)
    return _alignment_dict("sim3", scale, rot, trans)
def umeyama_alignment(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Umeyama Sim3 SVD 对齐。

    src 是 estimate，dst 是 GT。当前固定流程只保留 VO 的 Sim3 对齐；
    VLOC 直接走 alignment=none，不会调用这里。

    代码意义：
    - 通过最小二乘求 R/t/s，使 s * R * estimate + t 尽量贴近 GT。
    - 这是 evo、rpg_trajectory_evaluation、KITTI 类评估中常见的轨迹对齐口径。
    - det 修正用于避免 SVD 给出反射矩阵；轨迹对齐必须是合法旋转。

    指标影响：
    - scale 会进入 report["alignment"]，也会影响所有对齐后的 ATE/RPE/segment 误差。
    - Sim3 会降低无尺度 VO 的位置误差，但 raw_path_scale_ratio 和局部尺度图仍能暴露尺度问题。

    来源对应：
    - 对齐这个评估步骤来自 Sturm12/Zhang18；Umeyama 是这里采用的 SVD 数值实现。
    - 如果启用 Sim3，报告里的尺度结论应按 Zhang18 的“尺度可观性”来解释。
    """
    src = np.asarray(src, dtype=float)
    dst = np.asarray(dst, dtype=float)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError("src and dst must have shape (N, 3)")
    if len(src) < 2:
        return 1.0, np.eye(3), dst[0] - src[0]

    # 1. 先去中心化，避免平移影响旋转和尺度估计。
    mu_src = src.mean(axis=0)
    mu_dst = dst.mean(axis=0)
    src_centered = src - mu_src
    dst_centered = dst - mu_dst

    # 2. 交叉协方差描述 estimate 与 GT 的主方向关系，SVD 从中恢复最优旋转。
    cov = (dst_centered.T @ src_centered) / len(src)
    u, singular_values, vt = np.linalg.svd(cov)
    sign = np.ones(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[-1] = -1
    s_mat = np.diag(sign)
    rot = u @ s_mat @ vt

    # 3. 固定 Sim3 模式估计尺度。
    var_src = float(np.mean(np.sum(src_centered * src_centered, axis=1)))
    scale = float(np.sum(singular_values * sign) / var_src) if var_src > 0 else 1.0

    # 4. 在旋转/尺度确定后，用两条轨迹的中心点求平移。
    trans = mu_dst - scale * (rot @ mu_src)
    return scale, rot, trans
def apply_alignment(positions: np.ndarray, alignment: dict[str, Any]) -> np.ndarray:
    """把 estimate 位置应用到 GT 坐标系。

    公式：p_aligned = scale * R * p_est + t。
    之后所有位置误差字段都基于这个结果：
    - per_pose.error_m / horizontal_error_m / vertical_error_m
    - ate_position_m / ate_horizontal_m / ate_vertical_m
    - rpe_frame_delta.translation_m
    - scale_frame_delta / scale_per_frame 中的局部尺度统计
    """
    scale = float(alignment["scale"])
    rot = np.asarray(alignment["rotation"], dtype=float)
    trans = np.asarray(alignment["translation"], dtype=float)
    return scale * (positions @ rot.T) + trans
def apply_rotation_alignment(rotations: np.ndarray | None, alignment: dict[str, Any]) -> np.ndarray | None:
    """把 estimate 姿态应用同一个对齐旋转。

    只应用 rotation，不应用 scale/translation，因为姿态没有尺度和平移。
    结果用于姿态 ATE、yaw 误差和 RPE 旋转误差。
    """
    if rotations is None:
        return None
    rot = np.asarray(alignment["rotation"], dtype=float)
    return np.einsum("ij,njk->nik", rot, rotations)
def alignment_export_columns(alignment: dict[str, Any], count: int, prefix: str) -> dict[str, Any]:
    """把 Sim3/SE3 对齐参数展开成可写入 Excel sheet 的列。

    Sim3 不是只有尺度，还包含完整变换：
    p_gt = scale * R * p_vo + t。
    因此导出中间轨迹时同时保留：
    - scale: 尺度因子；
    - rotation_r00...r22: 3x3 旋转矩阵；
    - translation_x/y/z: 平移向量。
    """
    rot = np.asarray(alignment["rotation"], dtype=float)
    trans = np.asarray(alignment["translation"], dtype=float)
    out: dict[str, Any] = {
        f"{prefix}_mode": np.asarray([alignment.get("mode", prefix)] * count, dtype=object),
        f"{prefix}_scale": np.full(count, float(alignment["scale"]), dtype=float),
        f"{prefix}_translation_x": np.full(count, float(trans[0]), dtype=float),
        f"{prefix}_translation_y": np.full(count, float(trans[1]), dtype=float),
        f"{prefix}_translation_z": np.full(count, float(trans[2]), dtype=float),
    }
    for row in range(3):
        for col in range(3):
            out[f"{prefix}_rotation_r{row}{col}"] = np.full(count, float(rot[row, col]), dtype=float)
    return out
def aggregate_alignment(alignments: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    """聚合每个连续段的对齐信息。

    代码意义：
    - 默认系统可以按 estimate 时间戳统一评估，也可以按连续段分别对齐/评估。
    - 多段时每段都有自己的 scale/rotation/translation，这里把 scale 做 min/max/mean 汇总。

    指标对应：
    - alignment.scale: 平均对齐尺度。
    - alignment.scale_min / scale_max: 不同连续段的尺度范围。
    - alignment.segment_count: 参与对齐的连续段数量。
    - 报告里的“分段尺度变化明显”就是根据 scale_min/scale_max/scale 触发的。

    来源对应：
    - 单段 SE3/Sim3 对齐来自 Sturm12/Zhang18。
    - 分段尺度范围是工程扩展，用来暴露长航程单目 VO 在不同连续段的尺度不稳定。
    """
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
def _alignment_dict(mode: str, scale: float, rotation: np.ndarray, translation: np.ndarray) -> dict[str, Any]:
    """统一构造 alignment 字段。

    rotation/translation 保留 ndarray，后续 _jsonable_value() 会在导出时转成 list。
    """
    return {
        "mode": mode,
        "scale": float(scale),
        "rotation": np.asarray(rotation, dtype=float),
        "translation": np.asarray(translation, dtype=float),
    }
