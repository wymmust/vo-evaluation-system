// main.js — ES module 入口
// 前端模块入口：装配 init() 和 wireEvents()

import { state } from "./state.js";
import { els } from "./dom-refs.js";
import { runEvaluation } from "./evaluation.js";
import { updateRunButton, handleDatasetChange, handleEntryModeChange, updateEntryModeUi, renderVlocChartDirectory, renderVoChartDirectory, handleVlocChartDirectoryChange, handleVoChartDirectoryChange, selectAllVlocChartDirectory, clearVlocChartDirectory, selectAllVoChartDirectory, clearVoChartDirectory } from "./entry-mode.js";
import { clearAllPointSelections, handlePointSelectionKeydown } from "./point-selection.js";
import { downloadReportJson } from "./download-utils.js";
import { downloadHtmlReport } from "./html-export.js";
import { showMessage } from "./report-render.js";
import { LABELS } from "./labels.js";
import { VLOC_VISIBLE_CHART_IDS, VO_VISIBLE_CHART_IDS } from "./constants.js";

// Initialize default selected chart sets
state.vlocSelectedChartIds = new Set(VLOC_VISIBLE_CHART_IDS);
state.voSelectedChartIds = new Set(VO_VISIBLE_CHART_IDS);

init();

async function init() {
  wireEvents();
  try {
    await checkServerHealth();
  } catch (error) {
    els.status.textContent = LABELS.server_disconnected;
    showMessage(LABELS.server_disconnected, "error");
  }
}

async function checkServerHealth() {
  const response = await fetch("/api/health");
  if (!response.ok) {
    throw new Error(`Server health check failed: ${response.status}`);
  }
  state.serverReady = true;
  els.status.textContent = LABELS.server_connected;
  els.status.classList.add("ready");
  updateRunButton();
}

function wireEvents() {
  els.entryMode.addEventListener("change", updateRunButton);
  els.dataset?.addEventListener("change", handleDatasetChange);
  [els.dataDirPath, els.logDirPath].forEach((input) => input?.addEventListener("input", updateRunButton));
  els.entryMode.addEventListener("change", handleEntryModeChange);
  els.vlocChartList?.addEventListener("change", handleVlocChartDirectoryChange);
  els.vlocChartSelectAll?.addEventListener("click", selectAllVlocChartDirectory);
  els.vlocChartClear?.addEventListener("click", clearVlocChartDirectory);
  els.voChartList?.addEventListener("change", handleVoChartDirectoryChange);
  els.voChartSelectAll?.addEventListener("click", selectAllVoChartDirectory);
  els.voChartClear?.addEventListener("click", clearVoChartDirectory);
  els.clearAllPointSelections?.addEventListener("click", clearAllPointSelections);
  document.addEventListener("keydown", handlePointSelectionKeydown);
  els.runButton.addEventListener("click", runEvaluation);
  els.downloadJson.addEventListener("click", downloadReportJson);
  els.downloadHtml.addEventListener("click", downloadHtmlReport);
  updateEntryModeUi();
  renderVlocChartDirectory();
  renderVoChartDirectory();
}
