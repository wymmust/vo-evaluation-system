// metrics.js — 指标卡数据构建
// 构建 VO/VLOC 指标列表用于指标卡渲染

import {
  VLOC_CHART_OPTIONS, VO_CHART_OPTIONS,
} from "./constants.js";
import { reportEntryMode } from "./entry-mode.js";
import { formatValue, formatNumber } from "./utils.js";
import { LABELS } from "./labels.js";

export function metricItems(report) {
  const entryMode = reportEntryMode(report);
  const summary = report.summary || {};
  const ate = report.ate_position_m || {};
  const vertical = report.ate_vertical_m || {};
  const rpe = report.rpe_frame_delta?.translation_m || {};
  const vlocSummary = report.vloc_details?.summary || {};
  const path = summary.gt_path_length_m || 0;
  const ateRel = path > 0 && Number.isFinite(ate.rmse) ? (100 * ate.rmse / path) : NaN;
  const rawRatio = summary.raw_path_scale_ratio_est_over_gt;
  const breakCount = report.discontinuities?.all_matches?.break_count || 0;
  const estCoverage = 100 * summary.est_pose_coverage_ratio;

  const voMetrics = [
    { label: "ATE RMSE", value: ate.rmse, unit: "m", note: Number.isFinite(ateRel) ? `${formatNumber(ateRel)} % 路程` : "全局位置一致性", status: ateRel > 2 ? "high" : ateRel > 1 ? "warning" : "good" },
    { label: "RPE RMSE", value: rpe.rmse, unit: "m", note: rpeDeltaLabel(report.rpe_frame_delta), status: Number.isFinite(rpe.rmse) && Number.isFinite(ate.rmse) && rpe.rmse > ate.rmse ? "warning" : "neutral" },
    { label: "长航程路程", value: summary.gt_path_length_m, unit: "m", note: `${formatValue(summary.duration_s, "s")} / ${summary.matched_poses ?? "N/A"} 帧`, status: "neutral" },
    { label: "垂直 RMSE", value: vertical.rmse, unit: "m", note: "高度方向误差", status: Number.isFinite(vertical.rmse) && Number.isFinite(ate.rmse) && Math.abs(vertical.rmse) > ate.rmse ? "warning" : "neutral" },
    { label: "GT 覆盖率", value: 100 * summary.gt_pose_coverage_ratio, unit: "%", note: "评估覆盖的 GT 范围", status: "neutral" },
    { label: "Raw 尺度比", value: rawRatio, unit: "", note: "VO 原始路程 / GT 路程", status: Number.isFinite(rawRatio) && (rawRatio < 0.8 || rawRatio > 1.25) ? "warning" : "neutral" },
    { label: "对齐尺度", value: report.alignment?.scale, unit: "", note: scaleRangeText(report.alignment || {}) || "全局对齐因子", status: "neutral" },
    { label: "匹配位姿", value: summary.matched_poses, unit: "", note: `${summary.original_matched_poses ?? "N/A"} 原始匹配`, status: "neutral" },
    { label: "VO 匹配率", value: estCoverage, unit: "%", note: `${summary.est_poses ?? "N/A"} 个 VO 位姿`, status: estCoverage < 90 ? "warning" : "neutral" },
    { label: "断点数量", value: breakCount, unit: "", note: report.discontinuities?.selected_segment?.policy || "vo_timestamps", status: breakCount > 0 ? "warning" : "good" },
    { label: "姿态修正", value: "none", unit: "", note: "固定流程不做姿态修正", status: "neutral" },
    { label: "耗时", value: summary.duration_s, unit: "s", note: "有效评估窗口", status: "neutral" },
  ];

  const vlocMetrics = [
    { label: "ATE RMSE", value: ate.rmse, unit: "m", note: Number.isFinite(ateRel) ? `${formatNumber(ateRel)} % 路程` : "整体位置一致性", status: ateRel > 2 ? "high" : ateRel > 1 ? "warning" : "good" },
    { label: "长航程路程", value: summary.gt_path_length_m, unit: "m", note: `${formatValue(summary.duration_s, "s")} / ${summary.matched_poses ?? "N/A"} 帧`, status: "neutral" },
    { label: "垂直 RMSE", value: vertical.rmse, unit: "m", note: "高度方向误差", status: Number.isFinite(vertical.rmse) && Number.isFinite(ate.rmse) && Math.abs(vertical.rmse) > ate.rmse ? "warning" : "neutral" },
    { label: "GT 覆盖率", value: 100 * summary.gt_pose_coverage_ratio, unit: "%", note: "评估覆盖的 GT 范围", status: "neutral" },
    { label: "匹配位姿", value: summary.matched_poses, unit: "", note: `${summary.original_matched_poses ?? "N/A"} 原始匹配`, status: "neutral" },
    { label: "VLOC 匹配率", value: estCoverage, unit: "%", note: `${summary.est_poses ?? "N/A"} 个 VLOC 位姿`, status: estCoverage < 90 ? "warning" : "neutral" },
    { label: "断点数量", value: breakCount, unit: "", note: report.discontinuities?.selected_segment?.policy || "vo_timestamps", status: breakCount > 0 ? "warning" : "good" },
    { label: "mean_error_pos_xy", value: vlocSummary.mean_error_pos_xy, unit: "m", note: "逐帧水平位置误差范数的平均值", status: "neutral" },
    { label: "mean_error_pos_z", value: vlocSummary.mean_error_pos_z, unit: "m", note: "逐帧垂直位置误差绝对值的平均值", status: "neutral" },
    { label: "mean_error_euler", value: vlocSummary.mean_error_euler, unit: "deg", note: "逐帧欧拉角误差范数的平均值", status: "neutral" },
    { label: "max_error_pos_xy", value: vlocSummary.max_error_pos_xy, unit: "m", note: "逐帧水平位置误差范数的最大值", status: "warning" },
    { label: "max_error_pos_z", value: vlocSummary.max_error_pos_z, unit: "m", note: "逐帧垂直位置误差绝对值的最大值", status: "warning" },
    { label: "max_error_euler", value: vlocSummary.max_error_euler, unit: "deg", note: "逐帧欧拉角误差范数的最大值", status: "warning" },
    { label: "耗时", value: summary.duration_s, unit: "s", note: "有效评估窗口", status: "neutral" },
  ];

  return entryMode === "vloc" ? vlocMetrics : voMetrics;
}

function rpeDeltaLabel(rpeInfo) {
  if (rpeInfo?.delta_unit === "meters") {
    const tolerance = Number.isFinite(rpeInfo.distance_tolerance_percent) ? ` ±${formatNumber(rpeInfo.distance_tolerance_percent)}%` : "";
    return `Δ=${formatValue(rpeInfo.delta_distance_m, "m")}${tolerance}`;
  }
  if (rpeInfo?.delta_unit === "frames") {
    return `Δ=${formatValue(rpeInfo.delta_frames, "frames")}`;
  }
  return `Δ=${rpeInfo?.delta_frames ?? "N/A"} frames`;
}

function scaleRangePercent(alignment) {
  const scale = alignment?.scale;
  const min = alignment?.scale_min;
  const max = alignment?.scale_max;
  if (!Number.isFinite(scale) || !Number.isFinite(min) || !Number.isFinite(max) || scale === 0) {
    return NaN;
  }
  return 100 * (max - min) / Math.abs(scale);
}

function scaleRangeText(alignment) {
  const range = scaleRangePercent(alignment);
  if (!Number.isFinite(range)) {
    return "";
  }
  return `${formatNumber(alignment.scale_min)}-${formatNumber(alignment.scale_max)} (${formatNumber(range)}%)`;
}
