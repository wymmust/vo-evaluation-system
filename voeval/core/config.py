"""Evaluation configuration validation."""

from __future__ import annotations

import math
from dataclasses import dataclass


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

    def __post_init__(self) -> None:
        self.rpe_delta_unit = _normalize_delta_unit(self.rpe_delta_unit, "rpe_delta_unit")
        self.scale_delta_unit = _normalize_delta_unit(self.scale_delta_unit, "scale_delta_unit")
        self.rpe_delta_frames = _positive_int(self.rpe_delta_frames, "rpe_delta_frames")
        if self.rpe_delta_value is not None:
            self.rpe_delta_value = _positive_finite_float(self.rpe_delta_value, "rpe_delta_value")
        if self.scale_delta_value is not None:
            self.scale_delta_value = _positive_finite_float(self.scale_delta_value, "scale_delta_value")
        self.rpe_distance_tolerance_ratio = _nonnegative_finite_float(
            self.rpe_distance_tolerance_ratio,
            "rpe_distance_tolerance_ratio",
        )
        self.scale_distance_tolerance_ratio = _nonnegative_finite_float(
            self.scale_distance_tolerance_ratio,
            "scale_distance_tolerance_ratio",
        )
def _normalize_delta_unit(value: str, name: str) -> str:
    token = str(value or "frames").strip().lower()
    if token in {"f", "frame", "frames"}:
        return "frames"
    if token in {"m", "meter", "meters", "metre", "metres"}:
        return "meters"
    raise ValueError(f"{name} must be 'frames' or 'meters'")
def _positive_int(value: int, name: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if out < 1:
        raise ValueError(f"{name} must be a positive integer")
    return out
def _positive_finite_float(value: float, name: str) -> float:
    out = float(value)
    if not math.isfinite(out) or out <= 0:
        raise ValueError(f"{name} must be a positive finite value")
    return out
def _nonnegative_finite_float(value: float, name: str) -> float:
    out = float(value)
    if not math.isfinite(out) or out < 0:
        raise ValueError(f"{name} must be a non-negative finite value")
    return out
