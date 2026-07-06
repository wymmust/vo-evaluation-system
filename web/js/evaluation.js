// evaluation.js — 评估调度 + config 构建
// runEvaluation、buildConfig、本地路径评估、文件 bundle 评估

import { state } from "./state.js";
import { els } from "./dom-refs.js";
import { valueOf } from "./utils.js";
import { buildBundlePayload, hasLocalPathInputs, missingBundleFiles } from "./file-bundle.js";
import { reportEntryMode } from "./entry-mode.js";
import { LABELS } from "./labels.js";

export async function runEvaluation() {
  clearMessage();
  setBusy(true);
  try {
    const entryMode = valueOf("entryMode");
    const config = buildConfig();
    const reportJson = hasLocalPathInputs()
      ? await evaluateLocalPathBundle(entryMode, config)
      : await evaluateSelectedFileBundle(entryMode, config);
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
  const isVloc = entryMode === "vloc";
  const rpeDeltaValue = isVloc ? 1.0 : numberOf("rpeDeltaValue");
  const rpeDeltaUnit = isVloc ? "frames" : valueOf("rpeDeltaUnit");
  const scaleDeltaValue = isVloc ? 1.0 : numberOf("scaleDeltaValue");
  const scaleDeltaUnit = isVloc ? "frames" : valueOf("scaleDeltaUnit");
  return {
    rpe_delta_frames: rpeDeltaUnit === "frames" ? Math.max(1, Math.round(rpeDeltaValue)) : 1,
    rpe_delta_value: rpeDeltaValue,
    rpe_delta_unit: rpeDeltaUnit,
    rpe_distance_tolerance_ratio: 0.05,
    scale_delta_value: scaleDeltaValue,
    scale_delta_unit: scaleDeltaUnit,
    scale_distance_tolerance_ratio: 0.05,
  };
}

async function evaluateSelectedFileBundle(entryMode, config) {
  const payload = await buildBundlePayload(entryMode);
  const response = await fetch("/api/evaluate-bundle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      entryMode,
      imuText: payload.imuText,
      estimateText: payload.estimateText,
      homePointText: payload.homePointText,
      calibRawText: payload.calibRawText,
      configJson: JSON.stringify(config),
      imuName: payload.imuName,
      estimateName: payload.estimateName,
      homePointName: payload.homePointName,
      calibRawName: payload.calibRawName,
      dataDirName: payload.dataDirName,
      logDirName: payload.logDirName,
    }),
  });
  let result = null;
  try {
    result = await response.json();
  } catch {
    result = null;
  }
  if (!response.ok || result?.ok === false) {
    throw new Error(result?.error || `HTTP ${response.status}`);
  }
  state.reportSource = "local_server";
  return JSON.stringify(result.report || result);
}

async function evaluateLocalPathBundle(entryMode, config) {
  const response = await fetch("/api/evaluate-paths", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      entryMode,
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

async function fetchReportSlice(sliceName) {
  const response = await fetch(`/api/report-slice?slice=${encodeURIComponent(sliceName)}`, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.error || `HTTP ${response.status}`);
  }
  return payload.data;
}

export { fetchReportSlice, evaluateSelectedFileBundle, evaluateLocalPathBundle };

// --- UI helpers used by evaluation flow ---
import { numberOf } from "./utils.js";
import { showMessage, clearMessage, setBusy, enableDownloads } from "./report-render.js";
import { renderReport } from "./report-render.js";
