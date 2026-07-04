// evaluation.js — 评估调度 + config 构建
// runEvaluation、buildConfig、本地路径评估、文件 bundle 评估

import { state } from "./state.js";
import { workerRequest, fetchLocalText } from "./worker-client.js";
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
  const defaultSegmentLengthsM = [50, 100, 200, 500, 1000, 2000, 5000];
  return {
    profile: "monocular_long_range_uav",
    alignment: isVloc ? "none" : "sim3",
    orientation_correction: "none",
    association_mode: "interpolate_gt",
    max_time_diff_s: null,
    max_interpolation_gap_s: 1.0,
    allow_extrapolation: false,
    interpolate_rotation: true,
    interpolation_position_method: "linear",
    interpolation_rotation_method: "slerp",
    time_offset_s: 0.0,
    rpe_delta_frames: rpeDeltaUnit === "frames" ? Math.max(1, Math.round(rpeDeltaValue)) : 1,
    rpe_delta_value: rpeDeltaValue,
    rpe_delta_unit: rpeDeltaUnit,
    rpe_distance_tolerance_ratio: 0.05,
    scale_delta_value: scaleDeltaValue,
    scale_delta_unit: scaleDeltaUnit,
    scale_distance_tolerance_ratio: 0.05,
    rpe_delta_seconds: [1, 5, 10],
    segment_lengths_m: defaultSegmentLengthsM,
    max_segments_per_length: 10000,
    segment_step_frames: 10,
    max_segment_length_diff_ratio: 0.05,
    continuous_segment_policy: isVloc ? "vo_timestamps" : "segments",
    discontinuity_step_m: 100,
    discontinuity_time_gap_s: 5,
    divergence_abs_m: 30,
    divergence_rel_percent: 3,
    divergence_min_distance_m: 100,
    divergence_min_time_s: 5,
    top_k_worst_segments: 10,
  };
}

async function evaluateSelectedFileBundle(entryMode, config) {
  const payload = await buildBundlePayload(entryMode);
  state.reportSource = "worker";
  return workerRequest("evaluate", {
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
  });
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
  if (state.reportSource === "local_paths") {
    const response = await fetch(`/api/report-slice?slice=${encodeURIComponent(sliceName)}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.error || `HTTP ${response.status}`);
    }
    return payload.data;
  }
  if (!state.workerReady) {
    if (sliceName === "full_report") return state.report || {};
    if (sliceName === "trajectory_exports") return state.report?.trajectory_exports || {};
    return state.report?.[sliceName] || (sliceName === "config" ? {} : []);
  }
  const text = await workerRequest("slice", { sliceName });
  return JSON.parse(String(text));
}

export { fetchReportSlice, evaluateSelectedFileBundle, evaluateLocalPathBundle };

// --- UI helpers used by evaluation flow ---
import { numberOf } from "./utils.js";
import { showMessage, clearMessage, setBusy, enableDownloads } from "./report-render.js";
import { renderReport } from "./report-render.js";
