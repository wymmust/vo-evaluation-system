"""SF calibration and home-point data structures."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HomePoint:
    """SF 评估目录中的 home_point.txt。

    固定格式：longitude latitude altitude_msl。
    这里只负责读取固定三列，后续 NED 转换再使用这个原点。
    """

    longitude: float
    latitude: float
    altitude_msl: float


@dataclass(frozen=True)
class Calibration:
    """SF 评估目录中的 calib_raw.yaml 关键外参。

    只提取需求文档后续坐标变换会用到的 4x4 矩阵。
    """

    t_imu_body: np.ndarray
    t_cam_imu: np.ndarray
    t_cn_cnm1: np.ndarray | None = None
