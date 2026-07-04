// report-render.js — 报告渲染（指标卡 + 消息）
// renderReport、renderMetrics、renderMessages + UI helpers (showMessage/clearMessage/setBusy/enableDownloads)

import { state } from "./state.js";
import { els } from "./dom-refs.js";
import { reportEntryMode } from "./entry-mode.js";
import { metricItems } from "./metrics.js";
import { formatValue, formatNumber, escapeHtml } from "./utils.js";
import { LABELS } from "./labels.js";

export function renderReport(report) {
  if (reportEntryMode(report) === "vloc") {
    // imported functions called below
    resetVlocChartDirectorySelection();
    resetPointSelectionState();
    renderVlocChartDirectory();
  } else if (reportEntryMode(report) === "vo") {
    resetVoChartDirectorySelection();
    resetPointSelectionState();
    renderVoChartDirectory();
  }
  updateEntryModeUi();
  renderMetrics(report);
  renderMessages(report);
  scheduleRenderCharts(report);
}

export function renderMetrics(report) {
  document.getElementById("metrics").innerHTML = metricGridHtml(metricItems(report), { formatValue });
}

export function renderMessages(report) {
  const entryMode = reportEntryMode(report);
  const messages = [];
  const summary = report.summary || {};
  const orientationInfo = report.orientation_correction || {};
  if (entryMode === "vo" && orientationInfo.auto && orientationInfo.selected) {
    messages.push(`${LABELS.orientation_auto_selected_prefix}${orientationInfo.selected}，score=${formatNumber(orientationInfo.best_score)}。${LABELS.orientation_auto_suffix}`);
  }
  const rawRatio = summary.raw_path_scale_ratio_est_over_gt;
  const alignMode = report.alignment?.base_mode || report.alignment?.mode;
  if (entryMode === "vo" && Number.isFinite(rawRatio) && alignMode === "se3" && (rawRatio < 0.8 || rawRatio > 1.25)) {
    messages.push(`${LABELS.se3_scale_warning_prefix} ${rawRatio.toFixed(3)}${LABELS.se3_scale_warning_suffix}`);
  }
  const allDisc = report.discontinuities?.all_matches || {};
  const selected = report.discontinuities?.selected_segment || {};
  if ((allDisc.break_count || 0) > 0) {
    if (selected.policy === "vo_timestamps") {
      messages.push(`${LABELS.discontinuity_detected_prefix} ${allDisc.break_count} ${LABELS.discontinuity_detected_break_suffix}${LABELS.discontinuity_vo_timestamps_suffix}`);
    } else {
      messages.push(`${LABELS.discontinuity_detected_prefix} ${allDisc.break_count} ${LABELS.discontinuity_detected_break_suffix}${LABELS.discontinuity_policy_suffix} ${selected.policy}，评估匹配点 ${summary.matched_poses}/${summary.original_matched_poses}。`);
    }
  }
  if (
    report.association?.mode === "interpolate_gt" &&
    ((report.association.dropped_est_outside_gt_range || 0) > 0 || (report.association.dropped_est_large_gt_gap || 0) > 0)
  ) {
    const maxGap = report.association.max_interpolation_gap_s;
    messages.push(`${LABELS.interpolation_dropped_prefix}，${LABELS.interpolation_max_gap_suffix} ${formatNumber(maxGap)} s。`);
  }
  if (report.divergence?.diverged) {
    messages.push(`${LABELS.divergence_prefix}distance=${formatNumber(report.divergence.first_divergence_distance_m)} m, error=${formatNumber(report.divergence.first_divergence_error_m)} m。`);
  }
  if (messages.length) {
    showMessage(messages.join(" "), "warning");
  } else {
    clearMessage();
  }
}

function orientationCorrectionLabel(info) {
  const selected = info.selected || "none";
  const requested = info.requested || selected;
  if (info.auto && requested !== selected) {
    return `auto -> ${selected}`;
  }
  return selected;
}

export { orientationCorrectionLabel };

export function showMessage(text, type = "") {
  els.message.hidden = false;
  els.message.textContent = text;
  els.message.className = `message ${type}`.trim();
}

export function clearMessage() {
  els.message.hidden = true;
  els.message.textContent = "";
  els.message.className = "message";
}

export function setBusy(isBusy) {
  els.runButton.textContent = isBusy ? LABELS.button_busy : LABELS.button_run;
  if (isBusy) {
    els.runButton.disabled = true;
    return;
  }
  updateRunButton();
}

export function enableDownloads(enabled) {
  [els.downloadJson, els.downloadConfigJson, els.downloadTrajectoryExcel, els.downloadHtml].forEach((button) => {
    button.disabled = !enabled;
  });
}

import { metricGridHtml, chartDirectoryHtml } from "../visualization/report_templates.js";
import { buildVisualizationFigureSpecs } from "../visualization/figure_specs.js";



import { resetVlocChartDirectorySelection, resetVoChartDirectorySelection,
  updateEntryModeUi, updateRunButton,
  renderVlocChartDirectory, renderVoChartDirectory } from "./entry-mode.js";
import { resetPointSelectionState } from "./point-selection.js";
import { scheduleRenderCharts } from "./chart-render.js";
