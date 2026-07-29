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
    - delta_value/delta_unit: 同时控制 RPE 和尺度图的间隔统计。
    """

    delta_value: float = 1.0
    delta_unit: str = "frames"

    def __post_init__(self) -> None:
        self.delta_unit = _normalize_delta_unit(self.delta_unit)
        self.delta_value = _positive_finite_float(self.delta_value)


def _normalize_delta_unit(value: str) -> str:
    token = str(value or "frames").strip().lower()
    if token in {"f", "frame", "frames"}:
        return "frames"
    if token in {"m", "meter", "meters", "metre", "metres"}:
        return "meters"
    raise ValueError("delta_unit must be 'frames' or 'meters'")


def _positive_finite_float(value: float) -> float:
    out = float(value)
    if not math.isfinite(out) or out <= 0:
        raise ValueError("delta_value must be a positive finite value")
    return out

