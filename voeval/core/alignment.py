"""Sim3/Umeyama alignment helpers."""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def sim3_alignment(gt_pos: np.ndarray, est_pos: np.ndarray) -> dict[str, float | np.ndarray]:
    """VO 固定使用 Sim3，把 estimate 对齐到 GT/reference 坐标系。

    指标对应：
    - alignment["scale"] 最终显示为页面"对齐尺度"。
    - 所有 VO ATE/RPE 都基于 Sim3 后的 est_pos_aligned 计算。

    来源对应：
    - Sturm12 的 ATE 需要先把估计轨迹配准到 GT 后再算绝对误差。
    - Zhang18 明确说明单目无尺度通常看 Sim3。
    """
    scale, rot, trans = umeyama_alignment(est_pos, gt_pos)
    return {"scale": float(scale), "rotation": np.asarray(rot, dtype=float), "translation": np.asarray(trans, dtype=float)}


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
    - 如果启用 Sim3，报告里的尺度结论应按 Zhang18 的"尺度可观性"来解释。
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
    logger.debug("Aligning using Umeyama's method... (with scale correction)")
    logger.debug("Rotation of alignment:\n%s\nTranslation of alignment:\n%s", rot, trans)
    logger.debug("Scale correction: %.12g", scale)
    return scale, rot, trans


def apply_alignment(positions: np.ndarray, rotations: np.ndarray | None, alignment: dict) -> tuple[np.ndarray, np.ndarray | None]:
    """把 estimate 位置和姿态应用到 GT 坐标系。

    位置公式：p_aligned = scale * R * p_est + t。
    姿态公式：rot_aligned = R * rot_est（只应用旋转，不应用 scale/translation）。

    之后所有位置和姿态误差字段都基于这个结果：
    - per_pose.error_m / horizontal_error_m / vertical_error_m
    - ate_position_m / ate_horizontal_m / ate_vertical_m
    - ate_orientation_deg / ate_yaw_deg
    - rpe_frame_delta.translation_m / rotation_deg
    - scale_frame_delta / scale_per_frame 中的局部尺度统计
    """
    scale = float(alignment["scale"])
    rot = np.asarray(alignment["rotation"], dtype=float)
    trans = np.asarray(alignment["translation"], dtype=float)
    positions_aligned = scale * (positions @ rot.T) + trans
    rotations_aligned = np.einsum("ij,njk->nik", rot, rotations) if rotations is not None else None
    return positions_aligned, rotations_aligned
