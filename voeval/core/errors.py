"""ATE/RPE relative-pose error helpers."""

from __future__ import annotations

import numpy as np

from .geometry import rotation_angle

def relative_error(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    i: int,
    j: int,
) -> tuple[float, float | None]:
    """RPE 相对运动误差。

    有姿态时在各自起点坐标系下比较相对位移/相对旋转；
    无姿态时只比较世界系位移差。

    指标对应：
    - RPE: i 和 j 通常是固定帧间隔，或 evo consecutive-pairs 固定路程锚点。

    为什么有姿态时要转到起点坐标系：
    - RPE/子轨迹关心的是“这段相对运动估得准不准”，不希望被世界系整体旋转影响。
    - 这也和 TUM/RPG/KITTI 常见相对误差定义一致。

    来源对应：
    - 固定帧 i->j 的相对误差来自 Sturm12 RPE。
    - Zhang18 给出了统一的相对轨迹误差解释。
    """
    if gt_rot is not None and est_rot is not None:
        gt_r, gt_t = relative_pose(gt_rot[i], gt_pos[i], gt_rot[j], gt_pos[j])
        est_r, est_t = relative_pose(est_rot[i], est_pos[i], est_rot[j], est_pos[j])
        err_r = gt_r.T @ est_r
        err_t = gt_r.T @ (est_t - gt_t)
        return float(np.linalg.norm(err_t)), float(rotation_angle(err_r))
    gt_delta = gt_pos[j] - gt_pos[i]
    est_delta = est_pos[j] - est_pos[i]
    return float(np.linalg.norm(est_delta - gt_delta)), None
def relative_pose(r_i: np.ndarray, p_i: np.ndarray, r_j: np.ndarray, p_j: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """计算从第 i 帧到第 j 帧的相对位姿。

    r_rel = R_i^T R_j，p_rel = R_i^T (p_j - p_i)。
    这个局部坐标系表达会被 relative_error() 用来比较 GT 和 estimate 的相对运动。
    """
    r_rel = r_i.T @ r_j
    p_rel = r_i.T @ (p_j - p_i)
    return r_rel, p_rel
def rotation_errors(gt_rot: np.ndarray, est_rot: np.ndarray) -> np.ndarray:
    """逐帧姿态角误差，单位为弧度。

    输出会在 evaluate_trajectories() 中转成角度，进入 ate_orientation_deg。
    """
    err = np.einsum("nij,nkj->nik", gt_rot, est_rot)
    return np.asarray([rotation_angle(r) for r in err], dtype=float)
