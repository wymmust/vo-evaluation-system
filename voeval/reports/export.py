"""JSON export helpers."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

from ..core.pipeline import TrajectoryEvaluationResult, evaluate_trajectory_result
def attach_trajectory_exports(evaluation: TrajectoryEvaluationResult) -> dict[str, Any]:
    """把 core 评估结果补成网页绘图需要的逐帧数据。"""
    report = evaluation.report
    trajectory_exports: dict[str, pd.DataFrame] = {}
    if not evaluation.rpe_per_frame.empty:
        trajectory_exports["rpe_per_frame"] = evaluation.rpe_per_frame
    if not evaluation.scale_per_frame.empty:
        trajectory_exports["scale_per_frame"] = evaluation.scale_per_frame
    if trajectory_exports:
        report["trajectory_exports"] = trajectory_exports
    return report
def evaluate_trajectories(
    gt: Trajectory,
    est: Trajectory,
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    """Public trajectory evaluator returning the full report/export payload."""
    return attach_trajectory_exports(evaluate_trajectory_result(gt, est, config))
def report_to_json(report: dict[str, Any]) -> str:
    """导出严格 JSON 报告，供网页下载和 Pyodide 传回 JavaScript。"""
    return json.dumps(_jsonable_report(report), ensure_ascii=False, indent=2, allow_nan=False)
def _jsonable_report(report: dict[str, Any]) -> dict[str, Any]:
    """report_to_json() 的入口包装，保持调用语义清晰。"""
    return _jsonable_value(report)
def _jsonable_value(value: Any) -> Any:
    """把 report 递归转成标准 JSON 值。

    代码意义：
    - DataFrame -> records list，供 per_pose/rpe_per_frame/scale_per_frame 导出。
    - numpy scalar/array -> Python 原生类型，避免 json.dumps 不认识。
    - NaN/Infinity -> None，浏览器 JSON.parse 会把它读成 null。

    指标对应：
    - 所有 report 字段最终都经过这里，确保 ATE/RPE/alignment/export 等结果可以稳定导出。
    """
    if isinstance(value, pd.DataFrame):
        return [_jsonable_value(row) for row in value.to_dict(orient="records")]
    if isinstance(value, np.ndarray):
        return _jsonable_value(value.tolist())
    if isinstance(value, np.generic):
        return _jsonable_value(value.item())
    if isinstance(value, dict):
        return {key: _jsonable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value
