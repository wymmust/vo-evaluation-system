"""Browser wrapper for the static Pyodide build.

The static web app loads this module inside Pyodide. It keeps the public API
small: JavaScript passes file text and config JSON, Python returns report JSON.
"""

from __future__ import annotations

import json

from vo_eval.evaluator import EvaluationConfig, evaluate_trajectories, load_trajectory_from_text, report_to_json


def evaluate_json(
    gt_text: str,
    est_text: str,
    gt_fmt: str,
    est_fmt: str,
    config_json: str,
    gt_name: str = "ground_truth",
    est_name: str = "vo_output",
) -> str:
    config_data = json.loads(config_json)
    config = EvaluationConfig(**config_data)
    gt = load_trajectory_from_text(gt_text, fmt=gt_fmt, name=gt_name)
    est = load_trajectory_from_text(est_text, fmt=est_fmt, name=est_name)
    report = evaluate_trajectories(gt, est, config)
    return report_to_json(report)
