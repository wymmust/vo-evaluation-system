// evaluation.js — 评估调度 + config 构建
// runEvaluation、buildConfig、本地路径评估

import { state } from "./state.js";
import { els } from "./dom-refs.js";
import { valueOf } from "./utils.js";
import { LABELS } from "./labels.js";

export async function runEvaluation() {
  clearMessage();
  setBusy(true);
  try {
    const entryMode = valueOf("entryMode");
    const config = buildConfig();
    const reportJson = await evaluateLocalPathBundle(entryMode, config);
    state.report = JSON.parse(String(reportJson));
    renderReport(state.report);
    enableDownloads(true);
  } catch (error) {
    showMessage(`${LABELS.button_evaluation_failed_prefix}${error.message}`, "error");
    enableDownloads(false);
  } finally {
    setBusy(false);
  }
}

export function buildConfig() {
  const entryMode = valueOf("entryMode");
  if (entryMode === "vloc") {
    return {};
  }
  return {
    delta_value: numberOf("deltaValue"),
    delta_unit: valueOf("deltaUnit"),
  };
}

async function evaluateLocalPathBundle(entryMode, config) {
  const response = await fetch("/api/evaluate-paths", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      entryMode,
      dataset: valueOf("dataset") || "rk3399",
      dataDirPath: (els.dataDirPath?.value || "").trim(),
      logDirPath: (els.logDirPath?.value || "").trim(),
      config,
    }),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok || payload?.ok === false) {
    const detail = localPathServerErrorMessage(response, payload);
    throw new Error(`${LABELS.error_local_path_evaluation_failed_prefix}${detail}`);
  }
  state.reportSource = "local_paths";
  return JSON.stringify(payload.report || payload);
}

function localPathServerErrorMessage(response, payload) {
  if ([404, 405, 501].includes(response.status)) {
    return LABELS.error_local_path_no_server;
  }
  return payload?.error || `HTTP ${response.status}`;
}

export { evaluateLocalPathBundle };

// --- UI helpers used by evaluation flow ---
import { numberOf } from "./utils.js";
import { showMessage, clearMessage, setBusy, enableDownloads } from "./report-render.js";
import { renderReport } from "./report-render.js";
