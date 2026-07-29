"""Shared trajectory data structure."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Trajectory:
    """统一后的轨迹数据结构。

    stamps: 秒级时间戳。当前固定输入格式都按秒读取。
    positions: N x 3 的位置，单位默认按输入理解为米。
    rotations: 可选 N x 3 x 3 旋转矩阵；没有姿态时仍可计算位置类指标。
    extras: 与轨迹等长的附加字段，例如状态位、速度、reset_count、经纬高或 source_index。
    """

    name: str
    stamps: np.ndarray
    positions: np.ndarray
    rotations: np.ndarray | None = None
    extras: dict[str, np.ndarray] = field(default_factory=dict)
    source_format: str = "unknown"

    def __post_init__(self) -> None:
        """进入评估前的最后一道数据标准化。

        代码意义：
        - 所有输入格式最终都会走到 Trajectory，因此这里统一做 shape 校验、类型转换和时间排序。
        - 时间排序很重要：后续 path_distance()、插值、RPE 和断点检测都默认轨迹按时间递增。
        - extras 会跟随相同排序同步重排，确保状态、reset_count 等字段仍然和位姿一一对应。

        指标影响：
        - 如果这里不排序，summary.duration_s、RPE、尺度窗口和断点检测都会被乱序时间污染。
        - 如果 rotations 维度不一致，姿态 ATE/RPE 会直接变成错误指标，所以这里提前报错。
        """
        self.stamps = np.asarray(self.stamps, dtype=float).reshape(-1)
        self.positions = np.asarray(self.positions, dtype=float)
        if self.positions.ndim != 2 or self.positions.shape[1] != 3:
            raise ValueError("positions must have shape (N, 3)")
        if len(self.stamps) != len(self.positions):
            raise ValueError("stamps and positions must have the same length")
        if self.rotations is not None:
            self.rotations = np.asarray(self.rotations, dtype=float)
            if self.rotations.shape != (len(self.positions), 3, 3):
                raise ValueError("rotations must have shape (N, 3, 3)")
        order = np.argsort(self.stamps)
        self.stamps = self.stamps[order]
        self.positions = self.positions[order]
        if self.rotations is not None:
            self.rotations = self.rotations[order]
        for key, value in list(self.extras.items()):
            arr = np.asarray(value)
            if arr.ndim == 0:
                self.extras[key] = arr
            elif len(arr) == len(order):
                self.extras[key] = arr[order]
            else:
                raise ValueError(f"extras['{key}'] length must match trajectory length or be scalar")

    @property
    def duration_s(self) -> float:
        if len(self.stamps) < 2:
            return 0.0
        return float(self.stamps[-1] - self.stamps[0])
