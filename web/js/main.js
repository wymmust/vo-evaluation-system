// main.js — ES module 入口
// import 所有模块并 wire init() + wireEvents()，替代原 app.js 的初始化逻辑

import { state } from "./state.js";
import { els } from "./dom-refs.js";
import { runEvaluation, buildConfig, evaluateLocalPathBundle, evaluateSelectedFileBundle, fetchReportSlice } from "./evaluation.js";
import { updateRunButton, handleEntryModeChange, updateEntryModeUi, resetRenderedReport, renderVlocChartDirectory, renderVoChartDirectory, handleVlocChartDirectoryChange, handleVoChartDirectoryChange, selectAllVlocChartDirectory, clearVlocChartDirectory, selectAllVoChartDirectory, clearVoChartDirectory, reportEntryMode } from "./entry-mode.js";
import { updateDirectoryStatus } from "./file-bundle.js";
import { clearAllPointSelections, handlePointSelectionKeydown } from "./point-selection.js";
import { downloadReportJson } from "./download-utils.js";
import { downloadTrajectoryExcel } from "./excel-export.js";
import { downloadHtmlReport } from "./html-export.js";
import { showMessage } from "./report-render.js";
import { valueOf } from "./utils.js";
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
  [els.entryMode, els.dataDirFiles, els.logDirFiles].forEach((input) => input.addEventListener("change", updateRunButton));
  [els.dataDirPath, els.logDirPath].forEach((input) => input?.addEventListener("input", updateRunButton));
  els.dataDirFiles.addEventListener("change", () => updateDirectoryStatus("data"));
  els.logDirFiles.addEventListener("change", () => updateDirectoryStatus("log"));
  els.dataDirPath?.addEventListener("input", () => updateDirectoryStatus("data"));
  els.logDirPath?.addEventListener("input", () => updateDirectoryStatus("log"));
  els.entryMode.addEventListener("change", handleEntryModeChange);
  els.dataDirButton.addEventListener("click", () => els.dataDirFiles.click());
  els.logDirButton.addEventListener("click", () => els.logDirFiles.click());
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
  els.downloadConfigJson.addEventListener("click", () => {
    import("./download-utils.js").then(({ downloadText }) => {
      downloadText("vo_evaluation_config.json", JSON.stringify(state.report?.config || {}, null, 2), "application/json");
    });
  });
  els.downloadTrajectoryExcel.addEventListener("click", downloadTrajectoryExcel);
  els.downloadHtml.addEventListener("click", downloadHtmlReport);
  updateEntryModeUi();
  renderVlocChartDirectory();
  renderVoChartDirectory();
  updateDirectoryStatus("data");
  updateDirectoryStatus("log");
}
