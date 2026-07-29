// entry-mode.js — 入口模式切换（VLOC/VO）
// 模式 UI 更新、标题切换、图表目录渲染、可见性控制

import { state } from "./state.js";
import {
  VLOC_CHART_OPTIONS, VO_CHART_OPTIONS,
  VLOC_VISIBLE_CHART_IDS, VO_VISIBLE_CHART_IDS,
  PICKABLE_VLOC_CHART_IDS, PICKABLE_VO_CHART_IDS,
  chartIds,
} from "./constants.js";
import { els } from "./dom-refs.js";
import { valueOf, escapeHtml } from "./utils.js";
import { LABELS } from "./labels.js";
import { chartDirectoryHtml } from "../visualization/report_templates.js";

export function reportEntryMode(report = null) {
  return report?.inputs?.entry_mode || valueOf("entryMode") || "vloc";
}

export function visibleChartIdsForEntryMode(entryMode) {
  return entryMode === "vloc" ? VLOC_VISIBLE_CHART_IDS : VO_VISIBLE_CHART_IDS;
}

export function selectedChartIdsForEntryMode(entryMode) {
  if (entryMode === "vloc") {
    return selectedVlocChartIds();
  }
  if (entryMode === "vo") {
    return selectedVoChartIds();
  }
  return new Set();
}

function selectedVlocChartIds() {
  if (!(state.vlocSelectedChartIds instanceof Set)) {
    state.vlocSelectedChartIds = new Set(VLOC_VISIBLE_CHART_IDS);
  }
  return state.vlocSelectedChartIds;
}

function selectedVoChartIds() {
  if (!(state.voSelectedChartIds instanceof Set)) {
    state.voSelectedChartIds = new Set(VO_VISIBLE_CHART_IDS);
  }
  return state.voSelectedChartIds;
}

function resetVlocChartDirectorySelection() {
  state.vlocSelectedChartIds = new Set(VLOC_VISIBLE_CHART_IDS);
}

function resetVoChartDirectorySelection() {
  state.voSelectedChartIds = new Set(VO_VISIBLE_CHART_IDS);
}

export { selectedVlocChartIds, selectedVoChartIds, resetVlocChartDirectorySelection, resetVoChartDirectorySelection };

function chartTitleById(chartId, entryMode = reportEntryMode(state.report)) {
  const primaryOptions = entryMode === "vo" ? VO_CHART_OPTIONS : VLOC_CHART_OPTIONS;
  const fallbackOptions = entryMode === "vo" ? VLOC_CHART_OPTIONS : VO_CHART_OPTIONS;
  return [...primaryOptions, ...fallbackOptions].find((option) => option.id === chartId)?.label || chartId;
}

export { chartTitleById };

function updateEntryModeHint() {
  const entryMode = valueOf("entryMode");
  const dataset = valueOf("dataset") || "rk3399";
  const calibrationName = dataset === "rk3588" ? "bottom_calib_raw.yaml" : "calib_raw.yaml";
  const estimateName = entryMode === "vloc" ? "vloc.txt" : "vo.txt";
  const logFiles = entryMode === "vloc"
    ? `<code>log_dir/${estimateName}</code>、<code>home_point.txt</code> 和 <code>${calibrationName}</code>`
    : `<code>log_dir/${estimateName}</code> 和 <code>${calibrationName}</code>`;
  els.entryModeHint.innerHTML = `${LABELS.entry_hint_vloc} ${logFiles}。`;
}

function applyEntryModeTitles(entryMode) {
  const isVloc = entryMode === "vloc";
  if (els.summaryKicker) {
    els.summaryKicker.textContent = isVloc ? LABELS.summary_kicker_vloc : LABELS.summary_kicker_vo;
  }
  if (els.summaryTitle) {
    els.summaryTitle.textContent = isVloc ? LABELS.summary_title_vloc : LABELS.summary_title_vo;
  }
  if (els.visualKicker) {
    els.visualKicker.textContent = isVloc ? LABELS.visual_kicker_vloc : LABELS.visual_kicker_vo;
  }
  if (els.visualTitle) {
    els.visualTitle.textContent = isVloc ? LABELS.visual_title_vloc : LABELS.visual_title_vo;
  }
}

function applyEntryModeChartVisibility(entryMode) {
  const modeVisibleIds = new Set(visibleChartIdsForEntryMode(entryMode));
  const selectedChartIds = entryMode === "vloc"
    ? selectedVlocChartIds()
    : entryMode === "vo"
      ? selectedVoChartIds()
      : null;
  for (const id of chartIds) {
    const node = document.getElementById(id);
    if (!node) continue;
    const belongsToMode = modeVisibleIds.has(id);
    const shouldShow = belongsToMode && (!selectedChartIds || selectedChartIds.has(id));
    node.hidden = !shouldShow;
    if (!belongsToMode && typeof Plotly !== "undefined" && typeof Plotly.purge === "function") {
      Plotly.purge(id);
    }
  }
  // renderPointSelectionOutput and refreshAllPointSelectionTools are called externally
}

export { applyEntryModeChartVisibility };

function renderChartDirectory(listNode, options, selected) {
  if (!listNode) {
    return;
  }
  listNode.innerHTML = chartDirectoryHtml(options, selected);
}

function renderVlocChartDirectory() {
  renderChartDirectory(els.vlocChartList, VLOC_CHART_OPTIONS, selectedVlocChartIds());
}

function renderVoChartDirectory() {
  renderChartDirectory(els.voChartList, VO_CHART_OPTIONS, selectedVoChartIds());
}

export { renderVlocChartDirectory, renderVoChartDirectory };

function handleVlocChartDirectoryChange(event) {
  const target = event.target;
  const chartId = target?.dataset?.chartId;
  if (!chartId || !VLOC_VISIBLE_CHART_IDS.includes(chartId)) {
    return;
  }
  const selected = selectedVlocChartIds();
  if (target.checked) {
    selected.add(chartId);
  } else {
    selected.delete(chartId);
    purgeChart(chartId);
  }
  applyEntryModeChartVisibility(reportEntryMode(state.report));
  scheduleRenderCharts(state.report);
}

function handleVoChartDirectoryChange(event) {
  const target = event.target;
  const chartId = target?.dataset?.chartId;
  if (!chartId || !VO_VISIBLE_CHART_IDS.includes(chartId)) {
    return;
  }
  const selected = selectedVoChartIds();
  if (target.checked) {
    selected.add(chartId);
  } else {
    selected.delete(chartId);
    purgeChart(chartId);
  }
  applyEntryModeChartVisibility(reportEntryMode(state.report));
  scheduleRenderCharts(state.report);
}

function setVlocChartDirectorySelection(chartIdsToShow) {
  state.vlocSelectedChartIds = new Set(chartIdsToShow);
  renderVlocChartDirectory();
  applyEntryModeChartVisibility(reportEntryMode(state.report));
  purgeUnselectedCharts(reportEntryMode(state.report));
  scheduleRenderCharts(state.report);
}

function setVoChartDirectorySelection(chartIdsToShow) {
  state.voSelectedChartIds = new Set(chartIdsToShow);
  renderVoChartDirectory();
  applyEntryModeChartVisibility(reportEntryMode(state.report));
  purgeUnselectedCharts(reportEntryMode(state.report));
  scheduleRenderCharts(state.report);
}

function selectAllVlocChartDirectory() {
  setVlocChartDirectorySelection(VLOC_VISIBLE_CHART_IDS);
}

function clearVlocChartDirectory() {
  setVlocChartDirectorySelection([]);
}

function selectAllVoChartDirectory() {
  setVoChartDirectorySelection(VO_VISIBLE_CHART_IDS);
}

function clearVoChartDirectory() {
  setVoChartDirectorySelection([]);
}

export {
  handleVlocChartDirectoryChange, handleVoChartDirectoryChange,
  selectAllVlocChartDirectory, clearVlocChartDirectory,
  selectAllVoChartDirectory, clearVoChartDirectory,
};

function handleEntryModeChange() {
  updateEntryModeUi();
  if (state.report) {
    resetRenderedReport();
  }
}

function handleDatasetChange() {
  updateEntryModeHint();
  if (state.report) {
    resetRenderedReport();
  }
  updateRunButton();
}

function updateEntryModeUi() {
  const entryMode = valueOf("entryMode");
  document.querySelectorAll("[data-entry-hide]").forEach((node) => {
    node.hidden = entryModeMatchesRule(node.dataset.entryHide, entryMode);
  });
  document.querySelectorAll("[data-entry-show]").forEach((node) => {
    node.hidden = !entryModeMatchesRule(node.dataset.entryShow, entryMode);
  });
  applyEntryModeTitles(entryMode);
  renderVlocChartDirectory();
  renderVoChartDirectory();
  applyEntryModeChartVisibility(entryMode);
  updateEntryModeHint();
  updateRunButton();
}

function entryModeMatchesRule(rule, entryMode) {
  return String(rule || "")
    .split(/[,\s]+/)
    .filter(Boolean)
    .includes(entryMode);
}

function resetRenderedReport() {
  state.report = null;
  state.chartRenderToken += 1;
  resetPointSelectionState();
  clearMessage();
  if (els.metrics) {
    const label = valueOf("entryMode") === "vloc" ? "VLOC" : "VO";
    els.metrics.innerHTML = `<div class="empty-state">${LABELS.mode_switched_prefix} ${label} ${LABELS.mode_switched_suffix}</div>`;
  }
  for (const id of chartIds) {
    const node = document.getElementById(id);
    if (!node) continue;
    if (typeof Plotly !== "undefined" && typeof Plotly.purge === "function") {
      Plotly.purge(id);
    }
    node.innerHTML = "";
  }
  enableDownloads(false);
}

export { handleDatasetChange, handleEntryModeChange, updateEntryModeUi, resetRenderedReport, updateRunButton };

// --- imports needed by this module's internal logic ---
import { resetPointSelectionState } from "./point-selection.js";
import { scheduleRenderCharts, purgeChart, purgeUnselectedCharts } from "./chart-render.js";
import { showMessage, clearMessage, enableDownloads } from "./report-render.js";

function updateRunButton() {
  const hasRuntime = Boolean(state.serverReady);
  const hasLocalPaths = Boolean((els.dataDirPath?.value || "").trim() && (els.logDirPath?.value || "").trim());
  els.runButton.disabled = !(hasRuntime && hasLocalPaths);
}

export { updateRunButton as updateRunButtonFn };
