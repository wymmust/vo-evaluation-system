const state = {
  pyodide: null,
  evaluateVlocBundleJson: null,
  evaluateVoBundleJson: null,
  report: null,
  loadingStep: "",
};

const PYODIDE_INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

const els = {
  status: document.getElementById("runtimeStatus"),
  message: document.getElementById("message"),
  runButton: document.getElementById("runButton"),
  metrics: document.getElementById("metrics"),
  entryMode: document.getElementById("entryMode"),
  entryModeHint: document.getElementById("entryModeHint"),
  summaryKicker: document.getElementById("summaryKicker"),
  summaryTitle: document.getElementById("summaryTitle"),
  visualKicker: document.getElementById("visualKicker"),
  visualTitle: document.getElementById("visualTitle"),
  dataDirFiles: document.getElementById("dataDirFiles"),
  logDirFiles: document.getElementById("logDirFiles"),
  dataDirButton: document.getElementById("dataDirButton"),
  logDirButton: document.getElementById("logDirButton"),
  dataDirStatus: document.getElementById("dataDirStatus"),
  logDirStatus: document.getElementById("logDirStatus"),
  modeAndAlignmentSection: document.getElementById("modeAndAlignmentSection"),
  vlocChartDirectorySection: document.getElementById("vlocChartDirectorySection"),
  vlocChartList: document.getElementById("vlocChartList"),
  vlocChartSelectAll: document.getElementById("vlocChartSelectAll"),
  vlocChartClear: document.getElementById("vlocChartClear"),
  downloadJson: document.getElementById("downloadJson"),
  downloadPoseCsv: document.getElementById("downloadPoseCsv"),
  downloadSegmentCsv: document.getElementById("downloadSegmentCsv"),
  downloadWorstCsv: document.getElementById("downloadWorstCsv"),
  downloadConfigJson: document.getElementById("downloadConfigJson"),
  downloadTrajectoryExcel: document.getElementById("downloadTrajectoryExcel"),
  downloadHtml: document.getElementById("downloadHtml"),
};

const chartIds = [
  "trajectory3d",
  "trajectoryXY",
  "errorDistance",
  "heightComparison",
  "navStatusModes",
  "navVelocity",
  "navResetCounts",
  "vlocStatus",
  "segmentError",
  "speedError",
  "sim3ScaleTime",
  "positionCompareComposite",
  "attitudeCompareComposite",
  "positionErrorComposite",
  "attitudeErrorComposite",
  "rpeTranslationTime",
  "rpeRotationTime",
];

const VLOC_ONLY_CHART_IDS = new Set([
  "heightComparison",
  "navStatusModes",
  "navVelocity",
  "navResetCounts",
  "vlocStatus",
]);

const VLOC_CHART_OPTIONS = [
  { id: "trajectory3d", label: "3D 轨迹" },
  { id: "trajectoryXY", label: "俯视 NE 轨迹" },
  { id: "errorDistance", label: "误差随路程变化" },
  { id: "heightComparison", label: "对地高随时间变化" },
  { id: "navStatusModes", label: "导航状态信息" },
  { id: "navVelocity", label: "导航速度信息" },
  { id: "navResetCounts", label: "导航 reset 计数" },
  { id: "vlocStatus", label: "VLOC 状态信息" },
  { id: "positionCompareComposite", label: "NED 随时间变化" },
  { id: "attitudeCompareComposite", label: "YPR 随时间变化" },
  { id: "positionErrorComposite", label: "NED 误差随时间变化" },
  { id: "attitudeErrorComposite", label: "YPR 误差随时间变化" },
];

const VO_ONLY_CHART_IDS = new Set([
  "segmentError",
  "speedError",
  "sim3ScaleTime",
  "rpeTranslationTime",
  "rpeRotationTime",
]);

const VLOC_VISIBLE_CHART_IDS = VLOC_CHART_OPTIONS.map((option) => option.id);
const VO_VISIBLE_CHART_IDS = chartIds.filter((id) => !VLOC_ONLY_CHART_IDS.has(id));

state.vlocSelectedChartIds = new Set(VLOC_VISIBLE_CHART_IDS);

init();

async function init() {
  wireEvents();
  try {
    await initPyodide();
    els.status.textContent = "运行环境已就绪";
    els.status.classList.add("ready");
    updateRunButton();
  } catch (error) {
    showMessage(`运行环境加载失败：${describeRuntimeError(error)}`, "error");
    els.status.textContent = "加载失败";
  }
}

function wireEvents() {
  [els.entryMode, els.dataDirFiles, els.logDirFiles].forEach((input) => input.addEventListener("change", updateRunButton));
  els.dataDirFiles.addEventListener("change", () => updateDirectoryStatus("data"));
  els.logDirFiles.addEventListener("change", () => updateDirectoryStatus("log"));
  els.entryMode.addEventListener("change", handleEntryModeChange);
  els.dataDirButton.addEventListener("click", () => els.dataDirFiles.click());
  els.logDirButton.addEventListener("click", () => els.logDirFiles.click());
  document.getElementById("interpolationPreset").addEventListener("change", applyInterpolationPreset);
  els.vlocChartList?.addEventListener("change", handleVlocChartDirectoryChange);
  els.vlocChartSelectAll?.addEventListener("click", selectAllVlocChartDirectory);
  els.vlocChartClear?.addEventListener("click", clearVlocChartDirectory);
  els.runButton.addEventListener("click", runEvaluation);
  els.downloadJson.addEventListener("click", () => downloadText("vo_evaluation_metrics.json", JSON.stringify(state.report, null, 2), "application/json"));
  els.downloadPoseCsv.addEventListener("click", () => downloadText("vo_per_pose_errors.csv", toCsv(state.report?.per_pose || []), "text/csv"));
  els.downloadSegmentCsv.addEventListener("click", () => downloadText("vo_segment_errors.csv", toCsv(state.report?.segment_records || []), "text/csv"));
  els.downloadWorstCsv.addEventListener("click", () => downloadText("vo_worst_segments.csv", toCsv(state.report?.worst_segments || []), "text/csv"));
  els.downloadConfigJson.addEventListener("click", () => downloadText("vo_evaluation_config.json", JSON.stringify(state.report?.config || {}, null, 2), "application/json"));
  els.downloadTrajectoryExcel.addEventListener("click", () => downloadBytes(
    "vo_trajectory_exports.xlsx",
    buildTrajectoryWorkbook(state.report?.trajectory_exports || {}),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ));
  els.downloadHtml.addEventListener("click", () => downloadText("vo_evaluation_report.html", buildHtmlReport(), "text/html"));
  updateEntryModeUi();
  renderVlocChartDirectory();
  updateDirectoryStatus("data");
  updateDirectoryStatus("log");
}

async function initPyodide() {
  if (window.location.protocol === "file:") {
    throw new Error("local_file_protocol");
  }
  if (typeof loadPyodide !== "function") {
    throw new Error("pyodide_script_missing");
  }

  state.loadingStep = "pyodide";
  els.status.textContent = "加载 Pyodide...";
  state.pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX_URL });

  state.loadingStep = "packages";
  els.status.textContent = "加载 numpy/pandas...";
  await state.pyodide.loadPackage(["numpy", "pandas"]);

  state.loadingStep = "local_python";
  const [evaluatorCode, runnerCode] = await Promise.all([
    fetchText("./py/evaluator.py"),
    fetchText("./py/browser_runner.py"),
  ]);

  state.pyodide.FS.mkdirTree("/vo_eval");
  state.pyodide.FS.writeFile("/vo_eval/__init__.py", "");
  state.pyodide.FS.writeFile("/vo_eval/evaluator.py", evaluatorCode);
  state.pyodide.FS.writeFile("/browser_runner.py", runnerCode);
  state.pyodide.runPython(`
import sys
sys.path.insert(0, "/")
from browser_runner import evaluate_vloc_bundle_json, evaluate_vo_bundle_json
`);
  state.evaluateVlocBundleJson = state.pyodide.globals.get("evaluate_vloc_bundle_json");
  state.evaluateVoBundleJson = state.pyodide.globals.get("evaluate_vo_bundle_json");
}

async function fetchText(url) {
  let response;
  const cacheBust = `cache_bust=${Date.now()}`;
  const requestUrl = `${url}${url.includes("?") ? "&" : "?"}${cacheBust}`;
  try {
    response = await fetch(requestUrl, { cache: "no-store" });
  } catch (error) {
    throw new Error(`local_fetch_failed:${url}:${error.message}`);
  }
  if (!response.ok) {
    throw new Error(`local_fetch_status:${url}:${response.status}`);
  }
  return response.text();
}

function describeRuntimeError(error) {
  const message = error?.message || String(error);
  if (message === "local_file_protocol") {
    return "当前页面是直接打开的本地 index.html。请进入 static_web 目录后运行 python3 -m http.server 8765，再访问 http://localhost:8765/；公网部署时也必须通过 http/https URL 访问。";
  }
  if (message === "pyodide_script_missing") {
    return "Pyodide 脚本没有加载成功。请检查网络是否能访问 cdn.jsdelivr.net，或部署时改用可访问的 Pyodide CDN/本地镜像。";
  }
  if (message.startsWith("local_fetch_failed:")) {
    const [, url] = message.split(":");
    return `无法读取静态资源 ${url}。如果你打开的是 localhost，请确认静态服务器还在运行；如果是公网部署，请确认 static_web/py 目录也一起上传了。`;
  }
  if (message.startsWith("local_fetch_status:")) {
    const [, url, status] = message.split(":");
    return `无法读取静态资源 ${url}，HTTP 状态码 ${status}。请确认 static_web/py 目录已经和 index.html 一起部署。`;
  }
  if (message.includes("Failed to fetch") && state.loadingStep === "packages") {
    return "无法下载 numpy/pandas 运行包。请检查当前网络是否能访问 Pyodide CDN，或部署时使用可访问的镜像资源。";
  }
  if (message.includes("Failed to fetch")) {
    return "浏览器无法获取运行资源。请确认页面是通过 http/https 打开的、静态服务器没有停止，并且 CDN 网络可访问。";
  }
  return message;
}

function updateRunButton() {
  const hasRuntime = Boolean(state.evaluateVlocBundleJson && state.evaluateVoBundleJson);
  const missing = missingBundleFiles();
  els.runButton.disabled = !(hasRuntime && missing.length === 0);
}

async function runEvaluation() {
  clearMessage();
  setBusy(true);
  try {
    const entryMode = valueOf("entryMode");
    const payload = await buildBundlePayload(entryMode);
    const config = buildConfig();
    const reportJson = entryMode === "vloc"
      ? state.evaluateVlocBundleJson(
        payload.imuText,
        payload.estimateText,
        payload.homePointText,
        payload.calibRawText,
        JSON.stringify(config),
        payload.imuName,
        payload.estimateName,
        payload.homePointName,
        payload.calibRawName,
      )
      : state.evaluateVoBundleJson(
        payload.imuText,
        payload.estimateText,
        payload.homePointText,
        payload.calibRawText,
        JSON.stringify(config),
        payload.imuName,
        payload.estimateName,
        payload.homePointName,
        payload.calibRawName,
      );
    state.report = JSON.parse(String(reportJson));
    renderReport(state.report);
    enableDownloads(true);
  } catch (error) {
    showMessage(`评估失败：${error.message}`, "error");
    enableDownloads(false);
  } finally {
    setBusy(false);
  }
}

function buildConfig() {
  const entryMode = valueOf("entryMode");
  const isVloc = entryMode === "vloc";
  const maxTimeDiff = isVloc ? -1 : numberOf("maxTimeDiff");
  const maxInterpolationGap = isVloc ? 1.0 : numberOf("maxInterpolationGap");
  const rpeDeltaValue = isVloc ? 1.0 : numberOf("rpeDeltaValue");
  const rpeDeltaUnit = isVloc ? "frames" : valueOf("rpeDeltaUnit");
  const scaleDeltaValue = isVloc ? 1.0 : numberOf("scaleDeltaValue");
  const scaleDeltaUnit = isVloc ? "frames" : valueOf("scaleDeltaUnit");
  const segmentLengths = isVloc ? [50, 100, 200, 500, 1000, 2000, 5000] : parseFloatList(valueOf("segmentLengths"));
  return {
    profile: "monocular_long_range_uav",
    alignment: isVloc ? "none" : valueOf("alignment"),
    orientation_correction: isVloc ? "none" : valueOf("orientationCorrection"),
    association_mode: isVloc ? "interpolate_gt" : valueOf("associationMode"),
    max_time_diff_s: isVloc ? null : (maxTimeDiff < 0 ? null : maxTimeDiff),
    max_interpolation_gap_s: isVloc ? 1.0 : (maxInterpolationGap < 0 ? null : maxInterpolationGap),
    allow_extrapolation: isVloc ? false : boolOf("allowExtrapolation"),
    interpolate_rotation: isVloc ? true : boolOf("interpolateRotation"),
    interpolation_position_method: "linear",
    interpolation_rotation_method: "slerp",
    time_offset_s: isVloc ? 0.0 : numberOf("timeOffset"),
    rpe_delta_frames: rpeDeltaUnit === "frames" ? Math.max(1, Math.round(rpeDeltaValue)) : 1,
    rpe_delta_value: rpeDeltaValue,
    rpe_delta_unit: rpeDeltaUnit,
    rpe_distance_tolerance_ratio: 0.05,
    scale_delta_value: scaleDeltaValue,
    scale_delta_unit: scaleDeltaUnit,
    scale_distance_tolerance_ratio: 0.05,
    rpe_delta_seconds: [1, 5, 10],
    segment_lengths_m: segmentLengths,
    max_segments_per_length: isVloc ? 10000 : integerOf("maxSegments"),
    segment_step_frames: isVloc ? 10 : integerOf("segmentStep"),
    max_segment_length_diff_ratio: isVloc ? 0.05 : numberOf("lengthTolerance"),
    continuous_segment_policy: isVloc ? "vo_timestamps" : valueOf("segmentPolicy"),
    discontinuity_step_m: isVloc ? 100 : numberOf("discontinuityStep"),
    discontinuity_time_gap_s: isVloc ? 5 : numberOf("discontinuityGap"),
    divergence_abs_m: isVloc ? 30 : numberOf("divergenceAbs"),
    divergence_rel_percent: isVloc ? 3 : numberOf("divergenceRel"),
    divergence_min_distance_m: 100,
    divergence_min_time_s: 5,
    top_k_worst_segments: 10,
  };
}

function applyInterpolationPreset() {
  const preset = valueOf("interpolationPreset");
  if (preset === "custom") {
    return;
  }
  document.getElementById("maxInterpolationGap").value = preset;
}

function requiredBundleFiles(entryMode) {
  const estimateName = entryMode === "vloc" ? "vloc.txt" : "vo.txt";
  return {
    data: ["imu.txt"],
    log: [estimateName, "home_point.txt", "calib_raw.yaml"],
  };
}

function selectedFiles(input) {
  return Array.from(input?.files || []);
}

function directoryFileMap(input) {
  const files = selectedFiles(input);
  const out = new Map();
  for (const file of files) {
    const relative = file.webkitRelativePath || file.name;
    const parts = relative.split("/");
    const basename = parts[parts.length - 1];
    if (!out.has(basename)) {
      out.set(basename, file);
    }
  }
  return out;
}

function directoryNameFromFiles(files) {
  if (!files.length) {
    return "";
  }
  const relative = files[0].webkitRelativePath || "";
  if (relative.includes("/")) {
    return relative.split("/")[0];
  }
  return files[0].name || "";
}

function updateDirectoryStatus(kind) {
  const isData = kind === "data";
  const input = isData ? els.dataDirFiles : els.logDirFiles;
  const target = isData ? els.dataDirStatus : els.logDirStatus;
  const files = selectedFiles(input);
  if (!files.length) {
    target.textContent = "未选择目录";
    return;
  }
  const name = directoryNameFromFiles(files) || (isData ? "data_dir" : "log_dir");
  target.textContent = `${name} · ${files.length} 个文件`;
}

function missingBundleFiles() {
  const entryMode = valueOf("entryMode");
  const required = requiredBundleFiles(entryMode);
  const dataFiles = directoryFileMap(els.dataDirFiles);
  const logFiles = directoryFileMap(els.logDirFiles);
  const missing = [];
  for (const name of required.data) {
    if (!dataFiles.has(name)) {
      missing.push(`data_dir/${name}`);
    }
  }
  for (const name of required.log) {
    if (!logFiles.has(name)) {
      missing.push(`log_dir/${name}`);
    }
  }
  return missing;
}

async function buildBundlePayload(entryMode) {
  const missing = missingBundleFiles();
  if (missing.length) {
    throw new Error(`缺少必需文件：${missing.join("，")}`);
  }
  const required = requiredBundleFiles(entryMode);
  const dataFiles = directoryFileMap(els.dataDirFiles);
  const logFiles = directoryFileMap(els.logDirFiles);
  const imuFile = dataFiles.get(required.data[0]);
  const estimateFile = logFiles.get(required.log[0]);
  const homePointFile = logFiles.get("home_point.txt");
  const calibRawFile = logFiles.get("calib_raw.yaml");
  const [imuText, estimateText, homePointText, calibRawText] = await Promise.all([
    imuFile.text(),
    estimateFile.text(),
    homePointFile.text(),
    calibRawFile.text(),
  ]);
  return {
    imuText,
    estimateText,
    homePointText,
    calibRawText,
    imuName: imuFile.name,
    estimateName: estimateFile.name,
    homePointName: homePointFile.name,
    calibRawName: calibRawFile.name,
  };
}

function updateEntryModeHint() {
  const entryMode = valueOf("entryMode");
  const estimateName = entryMode === "vloc" ? "vloc.txt" : "vo.txt";
  els.entryModeHint.innerHTML = `当前模式会读取 <code>log_dir/${estimateName}</code>、<code>home_point.txt</code> 和 <code>calib_raw.yaml</code>。`;
}

function reportEntryMode(report = null) {
  return report?.inputs?.entry_mode || valueOf("entryMode") || "vloc";
}

function visibleChartIdsForEntryMode(entryMode) {
  return entryMode === "vloc" ? VLOC_VISIBLE_CHART_IDS : VO_VISIBLE_CHART_IDS;
}

function selectedVlocChartIds() {
  if (!(state.vlocSelectedChartIds instanceof Set)) {
    state.vlocSelectedChartIds = new Set(VLOC_VISIBLE_CHART_IDS);
  }
  return state.vlocSelectedChartIds;
}

function resetVlocChartDirectorySelection() {
  state.vlocSelectedChartIds = new Set(VLOC_VISIBLE_CHART_IDS);
}

function renderVlocChartDirectory() {
  if (!els.vlocChartList) {
    return;
  }
  const selected = selectedVlocChartIds();
  els.vlocChartList.innerHTML = VLOC_CHART_OPTIONS.map((option) => `
    <label class="chart-directory-item">
      <input type="checkbox" data-chart-id="${escapeHtml(option.id)}" ${selected.has(option.id) ? "checked" : ""} />
      <span>${escapeHtml(option.label)}</span>
    </label>
  `).join("");
}

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
  }
  applyEntryModeChartVisibility(reportEntryMode(state.report));
}

function setVlocChartDirectorySelection(chartIdsToShow) {
  state.vlocSelectedChartIds = new Set(chartIdsToShow);
  renderVlocChartDirectory();
  applyEntryModeChartVisibility(reportEntryMode(state.report));
}

function selectAllVlocChartDirectory() {
  setVlocChartDirectorySelection(VLOC_VISIBLE_CHART_IDS);
}

function clearVlocChartDirectory() {
  setVlocChartDirectorySelection([]);
}

function applyEntryModeTitles(entryMode) {
  const isVloc = entryMode === "vloc";
  if (els.summaryKicker) {
    els.summaryKicker.textContent = isVloc ? "VLOC Evaluation Summary" : "VO Evaluation Summary";
  }
  if (els.summaryTitle) {
    els.summaryTitle.textContent = isVloc ? "VLOC 运行结果" : "VO 运行结果";
  }
  if (els.visualKicker) {
    els.visualKicker.textContent = isVloc ? "Navigation & Estimation" : "Trajectory & Drift";
  }
  if (els.visualTitle) {
    els.visualTitle.textContent = isVloc ? "VLOC 可视化" : "VO 可视化";
  }
}

function applyEntryModeChartVisibility(entryMode) {
  const modeVisibleIds = new Set(visibleChartIdsForEntryMode(entryMode));
  const selectedVlocIds = entryMode === "vloc" ? selectedVlocChartIds() : null;
  for (const id of chartIds) {
    const node = document.getElementById(id);
    if (!node) continue;
    const belongsToMode = modeVisibleIds.has(id);
    const shouldShow = belongsToMode && (entryMode !== "vloc" || selectedVlocIds.has(id));
    node.hidden = !shouldShow;
    if (!belongsToMode && typeof Plotly !== "undefined" && typeof Plotly.purge === "function") {
      Plotly.purge(id);
    }
  }
}

function resetRenderedReport() {
  state.report = null;
  clearMessage();
  if (els.metrics) {
    const label = valueOf("entryMode") === "vloc" ? "VLOC" : "VO";
    els.metrics.innerHTML = `<div class="empty-state">已切换到 ${label} 评估，请重新导入目录并运行评估。</div>`;
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

function handleEntryModeChange() {
  updateEntryModeUi();
  if (state.report) {
    resetRenderedReport();
  }
}

function updateEntryModeUi() {
  const entryMode = valueOf("entryMode");
  document.querySelectorAll("[data-entry-hide]").forEach((node) => {
    node.hidden = node.dataset.entryHide === entryMode;
  });
  document.querySelectorAll("[data-entry-show]").forEach((node) => {
    node.hidden = node.dataset.entryShow !== entryMode;
  });
  if (els.modeAndAlignmentSection) {
    els.modeAndAlignmentSection.hidden = entryMode === "vloc";
  }
  applyEntryModeTitles(entryMode);
  renderVlocChartDirectory();
  applyEntryModeChartVisibility(entryMode);
  updateEntryModeHint();
  updateRunButton();
}

function valueOf(id) {
  return document.getElementById(id).value;
}

function numberOf(id) {
  const value = Number(valueOf(id));
  if (!Number.isFinite(value)) {
    throw new Error(`${id} 不是有效数字`);
  }
  return value;
}

function integerOf(id) {
  return Math.trunc(numberOf(id));
}

function boolOf(id) {
  return valueOf(id) === "true";
}

function parseFloatList(text) {
  const values = text
    .replaceAll(";", ",")
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((value) => Number.isFinite(value) && value > 0);
  if (!values.length) {
    throw new Error("至少需要一个子轨迹长度");
  }
  return values;
}

function setBusy(isBusy) {
  const hasRuntime = Boolean(state.evaluateVlocBundleJson && state.evaluateVoBundleJson);
  els.runButton.disabled = isBusy || !hasRuntime || missingBundleFiles().length > 0;
  els.runButton.textContent = isBusy ? "计算中..." : "运行评估";
}

function renderReport(report) {
  if (reportEntryMode(report) === "vloc") {
    resetVlocChartDirectorySelection();
    renderVlocChartDirectory();
  }
  updateEntryModeUi();
  renderMetrics(report);
  renderMessages(report);
  renderCharts(report);
}

function renderMetrics(report) {
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
    { label: "GT 覆盖率", value: 100 * (summary.gt_pose_coverage_ratio ?? summary.coverage_ratio), unit: "%", note: "评估覆盖的 GT 范围", status: "neutral" },
    { label: "Raw 尺度比", value: rawRatio, unit: "", note: "VO 原始路程 / GT 路程", status: Number.isFinite(rawRatio) && (rawRatio < 0.8 || rawRatio > 1.25) ? "warning" : "neutral" },
    { label: "对齐尺度", value: report.alignment?.scale, unit: "", note: scaleRangeText(report.alignment || {}) || "全局对齐因子", status: "neutral" },
    { label: "匹配位姿", value: summary.matched_poses, unit: "", note: `${summary.original_matched_poses ?? "N/A"} 原始匹配`, status: "neutral" },
    { label: "VO 匹配率", value: estCoverage, unit: "%", note: `${summary.est_poses ?? "N/A"} 个 VO 位姿`, status: estCoverage < 90 ? "warning" : "neutral" },
    { label: "断点数量", value: breakCount, unit: "", note: report.discontinuities?.selected_segment?.policy || "vo_timestamps", status: breakCount > 0 ? "warning" : "good" },
    { label: "姿态修正", value: orientationCorrectionLabel(report.orientation_correction || {}), unit: "", note: report.orientation_correction?.auto ? "自动选择" : "手动/默认", status: report.orientation_correction?.selected && report.orientation_correction.selected !== "none" ? "warning" : "neutral" },
    { label: "耗时", value: summary.duration_s, unit: "s", note: "有效评估窗口", status: "neutral" },
  ];
  const vlocMetrics = [
    { label: "ATE RMSE", value: ate.rmse, unit: "m", note: Number.isFinite(ateRel) ? `${formatNumber(ateRel)} % 路程` : "整体位置一致性", status: ateRel > 2 ? "high" : ateRel > 1 ? "warning" : "good" },
    { label: "长航程路程", value: summary.gt_path_length_m, unit: "m", note: `${formatValue(summary.duration_s, "s")} / ${summary.matched_poses ?? "N/A"} 帧`, status: "neutral" },
    { label: "垂直 RMSE", value: vertical.rmse, unit: "m", note: "高度方向误差", status: Number.isFinite(vertical.rmse) && Number.isFinite(ate.rmse) && Math.abs(vertical.rmse) > ate.rmse ? "warning" : "neutral" },
    { label: "GT 覆盖率", value: 100 * (summary.gt_pose_coverage_ratio ?? summary.coverage_ratio), unit: "%", note: "评估覆盖的 GT 范围", status: "neutral" },
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
  const metrics = entryMode === "vloc" ? vlocMetrics : voMetrics;

  document.getElementById("metrics").innerHTML = metrics.map((item, index) => `
    <div class="metric ${metricStatusClass(item.status)}">
      <div class="metric-top">
        <div class="label">${escapeHtml(item.label)}</div>
        <div class="metric-rank">#${String(index + 1).padStart(2, "0")}</div>
      </div>
      <div class="value">${formatValue(item.value, item.unit)}</div>
      <div class="metric-note">${escapeHtml(item.note || "")}</div>
    </div>
  `).join("");
}

function metricStatusClass(status) {
  if (status === "high") return "rank-high";
  if (status === "warning") return "rank-warning";
  if (status === "good") return "rank-good";
  return "";
}

function orientationCorrectionLabel(info) {
  const selected = info.selected || "none";
  const requested = info.requested || selected;
  if (info.auto && requested !== selected) {
    return `auto -> ${selected}`;
  }
  return selected;
}

function renderMessages(report) {
  const entryMode = reportEntryMode(report);
  const messages = [];
  const summary = report.summary || {};
  const orientationInfo = report.orientation_correction || {};
  if (entryMode === "vo" && orientationInfo.auto && orientationInfo.selected) {
    messages.push(`自动姿态修正选择：${orientationInfo.selected}，score=${formatNumber(orientationInfo.best_score)}。该选择只用于评估坐标系/外参修正，不会改变原始数据。`);
  }
  const rawRatio = summary.raw_path_scale_ratio_est_over_gt;
  const alignMode = report.alignment?.base_mode || report.alignment?.mode;
  if (entryMode === "vo" && Number.isFinite(rawRatio) && alignMode === "se3" && (rawRatio < 0.8 || rawRatio > 1.25)) {
    messages.push(`当前使用 SE3 刚体对齐，但 VO/GT 原始路程比例为 ${rawRatio.toFixed(3)}，尺度明显不一致。若 VO 是单目或尺度未知，请改用 Sim3。`);
  }

  const allDisc = report.discontinuities?.all_matches || {};
  const selected = report.discontinuities?.selected_segment || {};
  if ((allDisc.break_count || 0) > 0) {
    if (selected.policy === "vo_timestamps") {
      messages.push(`检测到 ${allDisc.break_count} 个大跳变/时间间隔；当前仍按全部 VO 时间戳统一评估，不会因此丢弃匹配点。`);
    } else {
      messages.push(`检测到 ${allDisc.break_count} 个大跳变/时间间隔；当前策略 ${selected.policy}，评估匹配点 ${summary.matched_poses}/${summary.original_matched_poses}。`);
    }
  }

  if (
    report.association?.mode === "interpolate_gt" &&
    ((report.association.dropped_est_outside_gt_range || 0) > 0 || (report.association.dropped_est_large_gt_gap || 0) > 0)
  ) {
    const maxGap = report.association.max_interpolation_gap_s;
    messages.push(`当前将 GT 插值到 VO 时间戳；因超出 GT 时间范围或插值间隔过大丢弃了部分 VO 点，最大 GT 插值间隔 ${formatNumber(maxGap)} s。`);
  }

  if (report.divergence?.diverged) {
    messages.push(`首次发散：distance=${formatNumber(report.divergence.first_divergence_distance_m)} m, error=${formatNumber(report.divergence.first_divergence_error_m)} m。`);
  }

  if (messages.length) {
    showMessage(messages.join(" "), "warning");
  } else {
    clearMessage();
  }
}

function renderCharts(report) {
  const entryMode = reportEntryMode(report);
  const isVloc = entryMode === "vloc";
  applyEntryModeChartVisibility(entryMode);
  if (isVloc) {
    renderVlocCharts(report);
    return;
  }

  const perPose = report.per_pose || [];
  const segmentSummary = report.segment_errors || [];
  const speedBins = report.speed_bins || [];
  const sim3Rows = report.trajectory_exports?.scale_per_frame || report.trajectory_exports?.sim3_vo_tum || [];
  const rpeRows = report.trajectory_exports?.rpe_per_frame || [];

  const [gtX3d, gtY3d, gtZ3d] = segmentedValues(perPose, ["gt_x_m", "gt_y_m", "gt_z_m"], "visual_segment_id");
  const [estX3d, estY3d, estZ3d] = segmentedValues(perPose, ["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"], "visual_segment_id");
  Plotly.newPlot("trajectory3d", [
    { x: gtX3d, y: gtY3d, z: gtZ3d, mode: "lines", type: "scatter3d", name: "Ground truth" },
    { x: estX3d, y: estY3d, z: estZ3d, mode: "lines", type: "scatter3d", name: "VO aligned" },
    ...segmentEndpointTraces3d(perPose, ["gt_x_m", "gt_y_m", "gt_z_m"], "GT", {
      startColor: "#2563eb",
      endColor: "#f97316",
      startSymbol: "circle",
      endSymbol: "square",
    }),
    ...segmentEndpointTraces3d(perPose, ["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"], "VO", {
      startColor: "#9333ea",
      endColor: "#ef4444",
      startSymbol: "diamond",
      endSymbol: "x",
    }),
  ], layout("3D 轨迹", { scene: { xaxis: { title: "x m" }, yaxis: { title: "y m" }, zaxis: { title: "z m" } } }));

  const [gtX, gtY] = segmentedValues(perPose, ["gt_x_m", "gt_y_m"]);
  const [estX, estY] = segmentedValues(perPose, ["est_x_aligned_m", "est_y_aligned_m"]);
  Plotly.newPlot("trajectoryXY", [
    { x: gtX, y: gtY, mode: "lines", type: "scatter", name: "Ground truth" },
    { x: estX, y: estY, mode: "lines", type: "scatter", name: "VO aligned" },
  ], layout("俯视 XY 轨迹", { xaxis: { title: "x m" }, yaxis: { title: "y m", scaleanchor: "x" } }));

  const [dist3d, err3d] = segmentedValues(perPose, ["distance_m", "error_m"]);
  const [distH, errH] = segmentedValues(perPose, ["distance_m", "horizontal_error_m"]);
  Plotly.newPlot("errorDistance", [
    { x: dist3d, y: err3d, mode: "lines", type: "scatter", name: "3D error" },
    { x: distH, y: errH, mode: "lines", type: "scatter", name: "horizontal" },
  ], layout("误差随路程变化", { xaxis: { title: "distance m" }, yaxis: { title: "error m" } }));

  const lengths = segmentSummary.map((row) => row.length_m);
  Plotly.newPlot("segmentError", [
    { x: lengths, y: segmentSummary.map((row) => row.translation_error_percent?.mean), mode: "lines+markers", type: "scatter", name: "translation mean %" },
    { x: lengths, y: segmentSummary.map((row) => row.translation_error_percent?.p95), mode: "lines+markers", type: "scatter", name: "translation p95 %" },
    { x: lengths, y: segmentSummary.map((row) => row.rotation_error_deg_per_m?.mean ?? null), mode: "lines+markers", type: "scatter", name: "rotation deg/m", yaxis: "y2" },
  ], layout("按距离子轨迹误差", {
    xaxis: { title: "segment length m" },
    yaxis: { title: "translation error %" },
    yaxis2: { title: "rotation deg/m", overlaying: "y", side: "right" },
  }));

  Plotly.newPlot("speedError", [
    { x: speedBins.map((row) => row.speed_bin_mps), y: speedBins.map((row) => row.translation_error_percent?.mean), type: "bar", name: "mean %" },
    { x: speedBins.map((row) => row.speed_bin_mps), y: speedBins.map((row) => row.translation_error_percent?.p95), type: "bar", name: "p95 %" },
  ], layout("速度分箱误差", { xaxis: { title: "speed m/s" }, yaxis: { title: "translation error %" }, barmode: "group" }));

  renderSim3ScaleTimeChart("sim3ScaleTime", sim3Rows, report.alignment || {});
  renderPairCompositeChart("positionCompareComposite", perPose, {
    title: "位置随时间变化",
    leftName: "Ground truth",
    rightName: "VO aligned",
    rows: [
      { label: "X", left: "gt_x_m", right: "est_x_aligned_m", unit: "m" },
      { label: "Y", left: "gt_y_m", right: "est_y_aligned_m", unit: "m" },
      { label: "Z", left: "gt_z_m", right: "est_z_aligned_m", unit: "m" },
    ],
  });
  renderPairCompositeChart("attitudeCompareComposite", perPose, {
    title: "姿态随时间变化",
    leftName: "Ground truth",
    rightName: "VO aligned",
    rows: [
      { label: "Yaw", left: "gt_yaw_deg", right: "est_yaw_aligned_deg", unit: "deg", unwrap: true },
      { label: "Pitch", left: "gt_pitch_deg", right: "est_pitch_aligned_deg", unit: "deg", unwrap: true },
      { label: "Roll", left: "gt_roll_deg", right: "est_roll_aligned_deg", unit: "deg", unwrap: true },
    ],
  });
  renderSingleCompositeChart("positionErrorComposite", perPose, {
    title: "位置误差随时间变化",
    rows: [
      { label: "X 误差", field: "x_error_m", unit: "m" },
      { label: "Y 误差", field: "y_error_m", unit: "m" },
      { label: "Z 误差", field: "z_error_m", unit: "m" },
    ],
  });
  renderSingleCompositeChart("attitudeErrorComposite", perPose, {
    title: "姿态误差随时间变化",
    rows: [
      { label: "Yaw 误差", field: "yaw_error_signed_deg", unit: "deg", unwrap: true },
      { label: "Pitch 误差", field: "pitch_error_signed_deg", unit: "deg", unwrap: true },
      { label: "Roll 误差", field: "roll_error_signed_deg", unit: "deg", unwrap: true },
    ],
  });

  renderRpeTimeChart("rpeTranslationTime", rpeRows, {
    title: "RPE 平移误差随时间变化",
    field: "rpe_translation_m",
    unit: "m",
    name: "rpe_translation_m",
  });
  renderRpeTimeChart("rpeRotationTime", rpeRows, {
    title: "RPE 旋转误差随时间变化",
    field: "rpe_rotation_deg",
    unit: "deg",
    name: "rpe_rotation_deg",
  });
}

function renderVlocCharts(report) {
  const details = report.vloc_details || {};
  const comparison = details.comparison || [];
  const navStatus = details.nav_status || [];
  const vlocStatus = details.vloc_status || [];
  const rows = comparison;

  const [navN3d, navE3d, navD3d] = segmentedValues(rows, ["nav_n_m", "nav_e_m", "nav_d_m"], "visual_segment_id");
  const [vlocN3d, vlocE3d, vlocD3d] = segmentedValues(rows, ["vloc_n_m", "vloc_e_m", "vloc_d_m"], "visual_segment_id");
  Plotly.newPlot("trajectory3d", [
    { x: navN3d, y: navE3d, z: navD3d, mode: "lines", type: "scatter3d", name: "nav" },
    { x: vlocN3d, y: vlocE3d, z: vlocD3d, mode: "lines", type: "scatter3d", name: "vloc" },
    ...segmentEndpointTraces3d(rows, ["vloc_n_m", "vloc_e_m", "vloc_d_m"], "vloc", {
      startColor: "#9333ea",
      endColor: "#ef4444",
      startSymbol: "diamond",
      endSymbol: "x",
      markerSize: 5,
      markerLineWidth: 1,
      textSize: 10,
    }),
  ], layout("3D 轨迹", { scene: { xaxis: { title: "north m" }, yaxis: { title: "east m" }, zaxis: { title: "down m" } } }));

  const [navN, navE] = segmentedValues(rows, ["nav_n_m", "nav_e_m"]);
  const [vlocN, vlocE] = segmentedValues(rows, ["vloc_n_m", "vloc_e_m"]);
  Plotly.newPlot("trajectoryXY", [
    { x: navN, y: navE, mode: "lines", type: "scatter", name: "nav" },
    { x: vlocN, y: vlocE, mode: "lines", type: "scatter", name: "vloc" },
  ], layout("俯视 NE 轨迹", { xaxis: { title: "north m" }, yaxis: { title: "east m", scaleanchor: "x" } }));

  renderMultiFieldTimeChart("errorDistance", rows, "误差随路程变化", [
    { field: "position_error_3d_m", name: "3D position error" },
    { field: "horizontal_position_error_m", name: "horizontal error" },
    { field: "vertical_position_error_abs_m", name: "vertical abs error" },
  ], { xField: "distance_m", xTitle: "distance m", yTitle: "error m" });

  renderMultiFieldTimeChart("heightComparison", rows, "对地高随时间变化", [
    { field: "nav_height_m", name: "nav height" },
    { field: "vloc_height_m", name: "vloc height" },
  ], { yTitle: "height m" });
  renderPairCompositeChart("positionCompareComposite", rows, {
    title: "NED 随时间变化",
    leftName: "nav",
    rightName: "vloc",
    rows: [
      { label: "N", left: "nav_n_m", right: "vloc_n_m", unit: "m" },
      { label: "E", left: "nav_e_m", right: "vloc_e_m", unit: "m" },
      { label: "D", left: "nav_d_m", right: "vloc_d_m", unit: "m" },
    ],
  });
  renderPairCompositeChart("attitudeCompareComposite", rows, {
    title: "YPR 随时间变化",
    leftName: "nav",
    rightName: "vloc",
    rows: [
      { label: "Yaw", left: "nav_yaw_deg", right: "vloc_yaw_deg", unit: "deg", unwrap: true },
      { label: "Pitch", left: "nav_pitch_deg", right: "vloc_pitch_deg", unit: "deg", unwrap: true },
      { label: "Roll", left: "nav_roll_deg", right: "vloc_roll_deg", unit: "deg", unwrap: true },
    ],
  });
  renderSingleCompositeChart("positionErrorComposite", rows, {
    title: "NED 误差随时间变化",
    rows: [
      { label: "N 误差", field: "position_error_n_m", unit: "m" },
      { label: "E 误差", field: "position_error_e_m", unit: "m" },
      { label: "D 误差", field: "position_error_d_m", unit: "m" },
    ],
  });
  renderSingleCompositeChart("attitudeErrorComposite", rows, {
    title: "YPR 误差随时间变化",
    rows: [
      { label: "Yaw 误差", field: "attitude_error_yaw_deg", unit: "deg", unwrap: true },
      { label: "Pitch 误差", field: "attitude_error_pitch_deg", unit: "deg", unwrap: true },
      { label: "Roll 误差", field: "attitude_error_roll_deg", unit: "deg", unwrap: true },
    ],
  });

  renderMultiFieldTimeChart("navStatusModes", navStatus, "导航状态信息", [
    { field: "flight_mode", name: "flight_mode" },
    { field: "navi_mode", name: "navi_mode" },
    { field: "rtk_yaw", name: "rtk_yaw" },
    { field: "rtk_alti", name: "rtk_alti" },
  ], { yTitle: "state" });
  renderSingleCompositeChart("navVelocity", navStatus, {
    title: "导航速度信息",
    rows: [
      { label: "vx", field: "vx", unit: "m/s" },
      { label: "vy", field: "vy", unit: "m/s" },
      { label: "vz", field: "vz", unit: "m/s" },
      { label: "velocity_norm", field: "velocity_norm", unit: "m/s" },
    ],
  });
  renderMultiFieldTimeChart("navResetCounts", navStatus, "导航 reset 计数", [
    { field: "position_reset_count", name: "position_reset_count" },
    { field: "altitude_reset_count", name: "altitude_reset_count" },
    { field: "heading_reset_count", name: "heading_reset_count" },
  ], { yTitle: "count" });
  renderSingleCompositeChart("vlocStatus", vlocStatus, {
    title: "VLOC 状态信息",
    rows: [
      { label: "vloc_mode", field: "vloc_mode", unit: "value" },
      { label: "num_inliers", field: "num_inliers", unit: "value" },
      { label: "reset_count", field: "reset_count", unit: "value" },
    ],
  });
}

function renderPairCompositeChart(id, rows, spec) {
  const traces = [];
  const axisLayout = {};
  const rowCount = spec.rows.length;
  spec.rows.forEach((row, index) => {
    const [leftColor, rightColor] = compositePairColors(index);
    const axisId = index === 0 ? "" : String(index + 1);
    const xaxisName = `xaxis${axisId}`;
    const yaxisName = `yaxis${axisId}`;
    const traceXAxis = `x${axisId}`;
    const traceYAxis = `y${axisId}`;
    const top = 1 - (index / rowCount);
    const bottom = 1 - ((index + 1) / rowCount);
    axisLayout[xaxisName] = {
      title: index === rowCount - 1 ? "timestamp s" : "",
      domain: [0, 1],
      anchor: traceYAxis,
      matches: index === 0 ? undefined : "x",
      showticklabels: index === rowCount - 1,
      gridcolor: "#e8eef7",
      zerolinecolor: "#d9e1ec",
      showspikes: false,
    };
    axisLayout[yaxisName] = {
      title: row.unit,
      domain: [bottom + 0.02, top - 0.02],
      anchor: traceXAxis,
      gridcolor: "#e8eef7",
      zerolinecolor: "#d9e1ec",
    };
    const [tLeft, leftValues] = segmentedValues(rows, ["timestamp", row.left]);
    const [tRight, rightValues] = segmentedValues(rows, ["timestamp", row.right]);
    const displayLeft = row.unwrap ? unwrapDegrees(leftValues) : leftValues;
    const displayRight = row.unwrap ? unwrapDegrees(rightValues) : rightValues;
    traces.push(
      { x: tLeft, y: displayLeft, mode: "lines", type: "scatter", name: `${row.label} ${spec.leftName}`, legendgroup: `${row.label}-${spec.leftName}`, showlegend: true, hoverinfo: "none", line: { color: leftColor }, xaxis: traceXAxis, yaxis: traceYAxis },
      { x: tRight, y: displayRight, mode: "lines", type: "scatter", name: `${row.label} ${spec.rightName}`, legendgroup: `${row.label}-${spec.rightName}`, showlegend: true, hoverinfo: "none", line: { color: rightColor }, xaxis: traceXAxis, yaxis: traceYAxis },
    );
  });
  Plotly.newPlot(id, traces, layout(spec.title, {
    height: 980,
    hovermode: "x unified",
    hoversubplots: "axis",
    hoverdistance: 20,
    spikedistance: -1,
    annotations: spec.rows.map((row, index) => ({
      text: row.label,
      x: 0,
      xref: "paper",
      xanchor: "left",
      y: 1 - (index / rowCount) - 0.015,
      yref: "paper",
      yanchor: "bottom",
      showarrow: false,
      font: { size: 14, color: "#0f172a" },
    })),
    ...axisLayout,
  }));
  attachCompositeOverlay(id, rows, spec);
}

function compositePairColors(index) {
  const palette = [
    ["#2563eb", "#16a34a"],
    ["#7c3aed", "#f97316"],
    ["#dc2626", "#0891b2"],
  ];
  return palette[index % palette.length];
}

function compositeFieldSpecs(spec) {
  const fields = [];
  for (const row of spec.rows || []) {
    if (row.left && row.right) {
      fields.push({ label: `${row.label} ${spec.leftName || "left"}`, field: row.left, unit: row.unit || "" });
      fields.push({ label: `${row.label} ${spec.rightName || "right"}`, field: row.right, unit: row.unit || "" });
    } else if (row.field) {
      fields.push({ label: row.label || row.field, field: row.field, unit: row.unit || "" });
    }
  }
  return fields;
}

function finiteOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function nearestTimestampRow(rows, timestamp) {
  const target = Number(timestamp);
  if (!Number.isFinite(target)) {
    return null;
  }
  let bestRow = null;
  let bestDiff = Infinity;
  for (const row of rows || []) {
    const rowTime = Number(row.timestamp);
    if (!Number.isFinite(rowTime)) {
      continue;
    }
    const diff = Math.abs(rowTime - target);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestRow = row;
    }
  }
  return bestRow;
}

function compositeHoverPayload(rows, spec, timestamp) {
  const row = nearestTimestampRow(rows, timestamp);
  if (!row) {
    return { timestamp: finiteOrNull(timestamp), values: [] };
  }
  const values = compositeFieldSpecs(spec).map((fieldSpec) => ({
    label: fieldSpec.label,
    value: finiteOrNull(row[fieldSpec.field]),
    unit: fieldSpec.unit,
  }));
  return { timestamp: Number(row.timestamp), values };
}

function compositeRangePayload(rows, spec, range) {
  const left = Number(range?.[0]);
  const right = Number(range?.[1]);
  if (!Number.isFinite(left) || !Number.isFinite(right)) {
    return { start: null, end: null, sampleCount: 0, stats: [] };
  }
  const start = Math.min(left, right);
  const end = Math.max(left, right);
  const selectedRows = (rows || []).filter((row) => {
    const timestamp = Number(row.timestamp);
    return Number.isFinite(timestamp) && timestamp >= start && timestamp <= end;
  });
  const stats = compositeFieldSpecs(spec).map((fieldSpec) => {
    const values = selectedRows.map((row) => Number(row[fieldSpec.field])).filter((value) => Number.isFinite(value));
    const count = values.length;
    const sum = values.reduce((acc, value) => acc + value, 0);
    return {
      label: fieldSpec.label,
      unit: fieldSpec.unit,
      count,
      min: count ? roundForDisplay(Math.min(...values)) : null,
      max: count ? roundForDisplay(Math.max(...values)) : null,
      mean: count ? roundForDisplay(sum / count) : null,
    };
  });
  return { start, end, sampleCount: selectedRows.length, stats };
}

function roundForDisplay(value) {
  return Number.isFinite(value) ? Number(value.toFixed(6)) : null;
}

function relayoutXRange(eventData) {
  if (!eventData) {
    return null;
  }
  const axisNames = ["xaxis", "xaxis2", "xaxis3", "xaxis4"];
  for (const axisName of axisNames) {
    const range = eventData[`${axisName}.range`];
    if (Array.isArray(range) && range.length >= 2) {
      return [range[0], range[1]];
    }
    const start = eventData[`${axisName}.range[0]`];
    const end = eventData[`${axisName}.range[1]`];
    if (start !== undefined && end !== undefined) {
      return [start, end];
    }
  }
  return null;
}

function ensureCompositeOverlay(id) {
  const plot = document.getElementById(id);
  if (!plot) {
    return null;
  }
  if (!plot.style.position) {
    plot.style.position = "relative";
  }
  const crosshairId = `${id}Crosshair`;
  const tooltipId = `${id}Tooltip`;
  let crosshair = document.getElementById(crosshairId);
  if (!crosshair) {
    crosshair = document.createElement("div");
    crosshair.id = crosshairId;
    crosshair.className = "composite-crosshair";
    plot.appendChild(crosshair);
  }
  let tooltip = document.getElementById(tooltipId);
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = tooltipId;
    tooltip.className = "composite-floating-tooltip";
    plot.appendChild(tooltip);
  }
  return { plot, crosshair, tooltip };
}

function formatOverlayNumber(value) {
  if (!Number.isFinite(Number(value))) {
    return "N/A";
  }
  const number = Number(value);
  return number.toFixed(3);
}

function compositeMousePosition(eventData, plot) {
  const event = eventData?.event;
  const rect = plot.getBoundingClientRect ? plot.getBoundingClientRect() : { left: 0, top: 0 };
  const mouseX = Number.isFinite(Number(event?.clientX)) ? Number(event.clientX) - rect.left : 24;
  const mouseY = Number.isFinite(Number(event?.clientY)) ? Number(event.clientY) - rect.top : 24;
  return { x: mouseX, y: mouseY };
}

function compositeCrosshairX(eventData, mouseX) {
  const point = eventData?.points?.[0];
  const axis = point?.xaxis;
  if (axis && typeof axis.l2p === "function") {
    const axisOffset = Number(axis._offset || 0);
    const axisPixel = Number(axis.l2p(point.x));
    if (Number.isFinite(axisPixel)) {
      return axisOffset + axisPixel;
    }
  }
  return Number.isFinite(Number(mouseX)) ? Number(mouseX) : 0;
}

function positionCompositeTooltip(tooltip, plot, mouse) {
  const tooltipWidth = 360;
  const tooltipHeight = 190;
  const plotWidth = Number(plot.clientWidth || 0);
  const plotHeight = Number(plot.clientHeight || 0);
  const preferRight = mouse.x + tooltipWidth + 18 <= plotWidth;
  const left = preferRight ? mouse.x + 14 : Math.max(8, mouse.x - tooltipWidth - 14);
  const top = Math.max(8, Math.min(mouse.y + 14, Math.max(8, plotHeight - tooltipHeight)));
  tooltip.style.left = `${Math.round(left)}px`;
  tooltip.style.top = `${Math.round(top)}px`;
}

function renderCompositeHoverOverlay(id, rows, spec, eventData) {
  const overlay = ensureCompositeOverlay(id);
  if (!overlay) {
    return;
  }
  const mouse = compositeMousePosition(eventData, overlay.plot);
  const x = compositeCrosshairX(eventData, mouse.x);
  const timestamp = eventData?.points?.[0]?.x;
  const payload = compositeHoverPayload(rows, spec, timestamp);
  const chips = payload.values.map((item) => (
    `<span class="metric-chip"><strong>${escapeHtml(item.label)}</strong>: ${formatOverlayNumber(item.value)}${item.unit ? ` ${escapeHtml(item.unit)}` : ""}</span>`
  )).join("");
  overlay.crosshair.style.left = `${Math.round(x)}px`;
  overlay.crosshair.style.top = "0px";
  overlay.crosshair.style.bottom = "0px";
  overlay.crosshair.style.display = "block";
  overlay.tooltip.innerHTML = `<strong>当前时间戳 ${formatOverlayNumber(payload.timestamp)} s</strong><div>${chips || "没有可用数据"}</div>`;
  positionCompositeTooltip(overlay.tooltip, overlay.plot, mouse);
  overlay.tooltip.style.display = "block";
}

function renderCompositeRangeOverlay(id, rows, spec, range) {
  const overlay = ensureCompositeOverlay(id);
  if (!overlay) {
    return;
  }
  const payload = compositeRangePayload(rows, spec, range);
  const chips = payload.stats.map((item) => (
    `<span class="metric-chip"><strong>${escapeHtml(item.label)}</strong>: mean ${formatOverlayNumber(item.mean)}, min ${formatOverlayNumber(item.min)}, max ${formatOverlayNumber(item.max)}, n=${item.count}${item.unit ? ` ${escapeHtml(item.unit)}` : ""}</span>`
  )).join("");
  overlay.tooltip.innerHTML = `<strong>选区 ${formatOverlayNumber(payload.start)}-${formatOverlayNumber(payload.end)} s，${payload.sampleCount} 帧</strong><div>${chips || "没有可用数据"}</div>`;
  overlay.tooltip.style.left = "12px";
  overlay.tooltip.style.top = "12px";
  overlay.tooltip.style.display = "block";
}

function hideCompositeOverlay(id) {
  const crosshair = document.getElementById(`${id}Crosshair`);
  const tooltip = document.getElementById(`${id}Tooltip`);
  if (crosshair) {
    crosshair.style.display = "none";
  }
  if (tooltip) {
    tooltip.style.display = "none";
  }
}

function attachCompositeOverlay(id, rows, spec) {
  const plot = document.getElementById(id);
  ensureCompositeOverlay(id);
  if (!plot || typeof plot.on !== "function") {
    return;
  }
  plot.on("plotly_hover", (eventData) => {
    renderCompositeHoverOverlay(id, rows, spec, eventData);
  });
  plot.on("plotly_unhover", () => hideCompositeOverlay(id));
  plot.on("plotly_relayout", (eventData) => {
    const range = relayoutXRange(eventData);
    if (range) {
      renderCompositeRangeOverlay(id, rows, spec, range);
    }
  });
  if (typeof plot.addEventListener === "function") {
    plot.addEventListener("mouseleave", () => hideCompositeOverlay(id));
  }
}

function renderSingleCompositeChart(id, rows, spec) {
  const traces = [];
  const axisLayout = {};
  const rowCount = spec.rows.length;
  spec.rows.forEach((row, index) => {
    const axisId = index === 0 ? "" : String(index + 1);
    const xaxisName = `xaxis${axisId}`;
    const yaxisName = `yaxis${axisId}`;
    const traceXAxis = `x${axisId}`;
    const traceYAxis = `y${axisId}`;
    const top = 1 - (index / rowCount);
    const bottom = 1 - ((index + 1) / rowCount);
    axisLayout[xaxisName] = {
      title: index === rowCount - 1 ? "timestamp s" : "",
      domain: [0, 1],
      anchor: traceYAxis,
      matches: index === 0 ? undefined : "x",
      showticklabels: index === rowCount - 1,
      gridcolor: "#e8eef7",
      zerolinecolor: "#d9e1ec",
      showspikes: false,
    };
    axisLayout[yaxisName] = {
      title: row.unit,
      domain: [bottom + 0.02, top - 0.02],
      anchor: traceXAxis,
      gridcolor: "#e8eef7",
      zerolinecolor: "#d9e1ec",
    };
    const [timestamps, values] = segmentedValues(rows, ["timestamp", row.field]);
    const displayValues = row.unwrap ? unwrapDegrees(values) : values;
    traces.push({
      x: timestamps,
      y: displayValues,
      mode: "lines",
      type: "scatter",
      name: row.label,
      legendgroup: row.label,
      showlegend: false,
      hoverinfo: "none",
      xaxis: traceXAxis,
      yaxis: traceYAxis,
    });
  });
  Plotly.newPlot(id, traces, layout(spec.title, {
    height: rowCount === 4 ? 1120 : 980,
    hovermode: "x unified",
    hoversubplots: "axis",
    hoverdistance: 20,
    spikedistance: -1,
    annotations: spec.rows.map((row, index) => ({
      text: row.label,
      x: 0,
      xref: "paper",
      xanchor: "left",
      y: 1 - (index / rowCount) - 0.015,
      yref: "paper",
      yanchor: "bottom",
      showarrow: false,
      font: { size: 14, color: "#0f172a" },
    })),
    ...axisLayout,
  }));
  attachCompositeOverlay(id, rows, spec);
}

function renderMultiFieldTimeChart(id, rows, title, specs, options = {}) {
  const xField = options.xField || "timestamp";
  const traces = specs.map((spec) => {
    const [xValues, yValues] = segmentedValues(rows, [xField, spec.field]);
    const displayY = spec.unwrap ? unwrapDegrees(yValues) : yValues;
    return { x: xValues, y: displayY, mode: "lines", type: "scatter", name: spec.name || spec.field };
  });
  Plotly.newPlot(id, traces, layout(title, {
    xaxis: { title: options.xTitle || "timestamp s" },
    yaxis: { title: options.yTitle || "" },
  }));
}

function renderRpeTimeChart(id, rows, spec) {
  const cleanRows = rows.filter((row) => row.rpe_available !== false && Number.isFinite(Number(row[spec.field])));
  const [timestamps, values] = segmentedValues(cleanRows, ["timestamp", spec.field]);
  Plotly.newPlot(id, [
    { x: timestamps, y: values, mode: "lines+markers", type: "scatter", name: spec.name },
  ], layout(spec.title, { xaxis: { title: "timestamp s" }, yaxis: { title: spec.unit } }));
}

function renderSim3ScaleTimeChart(id, rows, alignment = {}) {
  const cleanRows = rows.filter((row) => (
    row.scale_available !== false
    && Number.isFinite(Number(row.timestamp))
    && (Number.isFinite(Number(row.local_sim3_scale)) || Number.isFinite(Number(row.sim3_scale)))
  ));
  const displayRows = cleanRows.map((row) => ({
    ...row,
    display_scale: Number.isFinite(Number(row.local_sim3_scale)) ? row.local_sim3_scale : row.sim3_scale,
  }));
  const [timestamps, scales] = segmentedValues(displayRows, ["timestamp", "display_scale"]);
  const fallbackScale = Number(alignment?.scale);
  const data = timestamps.length
    ? [{ x: timestamps, y: scales, mode: "lines+markers", type: "scatter", name: "local_sim3_scale" }]
    : [{
        x: Number.isFinite(fallbackScale) ? [0] : [],
        y: Number.isFinite(fallbackScale) ? [fallbackScale] : [],
        mode: "markers",
        type: "scatter",
        name: "local_sim3_scale",
      }];
  Plotly.newPlot(id, data, layout("局部 Sim3 尺度随时间戳变化", { xaxis: { title: "timestamp s" }, yaxis: { title: "GT/VO local scale" } }));
}

function segmentEndpointTraces3d(rows, columns, prefix, style) {
  const endpoints = segmentEndpoints(rows, columns);
  return [
    endpointTrace3d(endpoints.starts, columns, `${prefix} start`, style.startColor, style.startSymbol, `${prefix} S`, "top center", style),
    endpointTrace3d(endpoints.ends, columns, `${prefix} end`, style.endColor, style.endSymbol, `${prefix} E`, "bottom center", style),
  ];
}

function segmentEndpoints(rows, columns) {
  const starts = [];
  const ends = [];
  if (!rows.length) {
    return { starts, ends };
  }

  let currentSegment = plotSegmentId(rows[0]);
  let currentRows = [];
  const flush = () => {
    const validRows = currentRows.filter((row) => columns.every((column) => Number.isFinite(Number(row[column]))));
    if (validRows.length) {
      starts.push(validRows[0]);
      ends.push(validRows[validRows.length - 1]);
    }
  };

  for (const row of rows) {
    const segmentId = plotSegmentId(row);
    if (segmentId !== currentSegment) {
      flush();
      currentSegment = segmentId;
      currentRows = [];
    }
    currentRows.push(row);
  }
  flush();
  return { starts, ends };
}

function plotSegmentId(row) {
  return row.visual_segment_id ?? row.segment_id ?? 0;
}

function rowSegmentId(row, segmentField = "segment_id") {
  return row[segmentField] ?? row.segment_id ?? 0;
}

function endpointTrace3d(rows, columns, name, color, symbol, labelPrefix, textPosition, style = {}) {
  const markerSize = style.markerSize ?? 9;
  const markerLineWidth = style.markerLineWidth ?? 2;
  const textfont = style.textSize ? { size: style.textSize } : undefined;
  return {
    x: rows.map((row) => row[columns[0]]),
    y: rows.map((row) => row[columns[1]]),
    z: rows.map((row) => row[columns[2]]),
    mode: "markers+text",
    type: "scatter3d",
    name,
    text: rows.map((_, index) => `${labelPrefix}${index + 1}`),
    textposition: textPosition,
    textfont,
    marker: { size: markerSize, color, symbol, line: { color: "#0f172a", width: markerLineWidth } },
  };
}

function segmentedValues(rows, columns, segmentField = null) {
  if (!rows.length) {
    return columns.map(() => []);
  }
  if (!segmentField) {
    return columns.map((column) => rows.map((row) => row[column]));
  }
  const outputs = columns.map(() => []);
  let currentSegment = rowSegmentId(rows[0], segmentField);
  for (const row of rows) {
    const segmentId = rowSegmentId(row, segmentField);
    if (segmentId !== currentSegment) {
      outputs.forEach((items) => items.push(null));
      currentSegment = segmentId;
    }
    columns.forEach((column, index) => outputs[index].push(row[column]));
  }
  return outputs;
}

function unwrapDegrees(values) {
  const out = [];
  let previousRaw = null;
  let offset = 0;
  for (const value of values) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
      out.push(value);
      previousRaw = null;
      offset = 0;
      continue;
    }
    const raw = Number(value);
    if (previousRaw !== null) {
      const delta = raw - previousRaw;
      if (delta > 180) {
        offset -= 360;
      } else if (delta < -180) {
        offset += 360;
      }
    }
    out.push(raw + offset);
    previousRaw = raw;
  }
  return out;
}

function layout(title, extra = {}) {
  return {
    title,
    height: 380,
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    font: { family: "Inter, system-ui, sans-serif", color: "#334155" },
    colorway: ["#2563eb", "#16a34a", "#f97316", "#9333ea", "#0f766e"],
    margin: { l: 56, r: 26, t: 52, b: 50 },
    legend: { orientation: "h", y: 1.1, x: 0, font: { size: 12 } },
    xaxis: { gridcolor: "#e8eef7", zerolinecolor: "#d9e1ec", title: "" },
    yaxis: { gridcolor: "#e8eef7", zerolinecolor: "#d9e1ec", title: "" },
    ...extra,
  };
}

function formatValue(value, unit) {
  if (typeof value === "string") {
    return escapeHtml(value);
  }
  if (!Number.isFinite(value)) {
    return "N/A";
  }
  const text = Number.isInteger(value) ? String(value) : value.toFixed(3);
  return `${text}${unit ? ` ${unit}` : ""}`;
}

function formatNumber(value) {
  return Number.isFinite(value) ? value.toFixed(2) : "N/A";
}

function showMessage(text, type = "") {
  els.message.hidden = false;
  els.message.textContent = text;
  els.message.className = `message ${type}`.trim();
}

function clearMessage() {
  els.message.hidden = true;
  els.message.textContent = "";
  els.message.className = "message";
}

function enableDownloads(enabled) {
  [els.downloadJson, els.downloadPoseCsv, els.downloadSegmentCsv, els.downloadWorstCsv, els.downloadConfigJson, els.downloadTrajectoryExcel, els.downloadHtml].forEach((button) => {
    button.disabled = !enabled;
  });
}

function toCsv(rows) {
  if (!rows.length) {
    return "";
  }
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(",")];
  for (const row of rows) {
    lines.push(headers.map((header) => csvCell(row[header])).join(","));
  }
  return lines.join("\n");
}

function csvCell(value) {
  if (value === null || value === undefined) {
    return "";
  }
  const text = String(value);
  if (/[",\n]/.test(text)) {
    return `"${text.replaceAll('"', '""')}"`;
  }
  return text;
}

function buildHtmlReport() {
  const report = reportForHtmlExport(state.report || {});
  const tuningRows = buildTuningConclusionRows(report);
  const status = reportDiagnosticStatus(tuningRows);
  const healthCards = buildHealthDashboardCards(report);
  const associationRows = buildAssociationDiagnosticRows(report);
  const longRangeRows = buildLongRangeDiagnosticRows(report);
  const worstRows = buildWorstSegmentRows(report);
  const conditionRows = buildConditionDiagnosticRows(report);
  const auxiliaryCards = buildAuxiliaryMetricCards(report);
  const metricRows = flattenReportMetrics(report);
  const configRows = buildConfigRows(report);
  const figureSpecs = buildReportPlotSpecs(report);
  const summary = report.summary || {};
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>VO Evaluation Report</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"><\/script>
<style>
:root{--text:#1f2937;--heading:#0f172a;--muted:#64748b;--line:#d8e2ef;--bg:#f4f7fb;--card:#fff;--soft:#f8fafc;--blue:#2563eb;--blue2:#1e40af;--good:#15803d;--warn:#b45309;--bad:#b42318;--info:#175cd3;--shadow:0 16px 38px rgba(15,23,42,.08)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{font-family:Inter,Arial,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;color:var(--text);background:linear-gradient(180deg,#eaf1ff 0,#f8fbff 280px,var(--bg) 680px);line-height:1.55}
.page{max-width:1320px;margin:0 auto;padding:28px 24px 46px}.hero{background:linear-gradient(135deg,#fff 0,#f8fbff 55%,#edf5ff 100%);border:1px solid var(--line);border-radius:8px;padding:28px;margin-bottom:18px;box-shadow:var(--shadow)}
.hero-top{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:start}.eyebrow{font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:var(--blue);margin-bottom:8px}h1{margin:0 0 8px;color:var(--heading);font-size:36px;line-height:1.05;font-weight:860}.subtitle{margin:0;color:var(--muted)}h2{margin:30px 0 14px;color:var(--heading);font-size:22px}h3{margin:0 0 8px;font-size:16px}.section-note{color:var(--muted);margin:-6px 0 14px}
.badge{display:inline-flex;align-items:center;border-radius:999px;padding:7px 13px;font-weight:900;font-size:13px;border:1px solid transparent;white-space:nowrap}.badge.good{color:var(--good);background:#eaf7ee;border-color:#b8dfc3}.badge.warning{color:var(--warn);background:#fff7ed;border-color:#fed7aa}.badge.high{color:var(--bad);background:#fff1f2;border-color:#fecdd3}.badge.info{color:var(--info);background:#eff6ff;border-color:#bfdbfe}
.hero-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-top:20px}.hero-item{background:rgba(255,255,255,.8);border:1px solid var(--line);border-radius:8px;padding:12px}.hero-label{font-size:12px;font-weight:800;color:var(--muted);margin-bottom:4px}.hero-value{font-weight:820;color:var(--heading);word-break:break-word}
.notice{border-left:5px solid var(--warn);background:#fffbeb;border:1px solid #fed7aa;border-left-color:var(--warn);border-radius:8px;padding:12px 14px;margin-top:14px;color:#7c2d12}.anchor-nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}.anchor-nav a{color:var(--blue2);background:#eff6ff;border:1px solid #bfdbfe;border-radius:999px;padding:6px 10px;text-decoration:none;font-weight:780;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.health-grid{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.card{background:linear-gradient(180deg,#fff 0,#f9fbfe 100%);border:1px solid var(--line);border-radius:8px;padding:15px;box-shadow:0 1px 0 rgba(15,23,42,.02);position:relative;overflow:hidden}.card:before{content:"";position:absolute;inset:0 0 auto;height:4px;background:var(--blue)}.card.high:before{background:var(--bad)}.card.warning:before{background:var(--warn)}.card.good:before{background:var(--good)}.card.info:before{background:var(--info)}
.metric-label{font-size:12px;color:var(--muted);font-weight:900;margin-bottom:6px}.metric-value{font-size:26px;line-height:1.05;font-weight:860;color:var(--heading)}.metric-note{font-size:12px;color:var(--muted);margin-top:8px}.metric-source{margin-top:8px;font-size:11px;color:#475569}
table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden;box-shadow:0 1px 0 rgba(15,23,42,.02)}th,td{border-bottom:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top}th{background:#eef3f9;font-size:13px;color:#334155}tr:last-child td{border-bottom:0}code{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;padding:2px 6px;white-space:nowrap}.priority{font-weight:900}.priority.p0{color:var(--bad)}.priority.p1{color:var(--warn)}.priority.p2{color:var(--info)}.tag{display:inline-flex;border-radius:999px;padding:3px 8px;font-size:12px;font-weight:800;background:#f1f5f9;color:#334155}.tag.high{background:#fff1f2;color:var(--bad)}.tag.warning{background:#fff7ed;color:var(--warn)}.tag.good{background:#eaf7ee;color:var(--good)}.tag.info{background:#eff6ff;color:var(--info)}
.metric-group{background:#fff;border:1px solid var(--line);border-radius:8px;padding:0;margin:10px 0;overflow:hidden;box-shadow:0 8px 22px rgba(15,23,42,.04)}.metric-group summary{cursor:pointer;font-weight:760;display:grid;grid-template-columns:minmax(180px,1fr) minmax(220px,1.6fr) auto;gap:10px;align-items:center;padding:13px 14px;background:#fff}.metric-group table{border-radius:0;border-left:0;border-right:0;border-bottom:0;box-shadow:none}.group-title{font-size:15px;color:var(--heading)}.group-count{color:var(--muted);font-size:12px}.metric-help{color:var(--muted);margin:0;padding:0 14px 13px}
.chart{margin:18px 0;overflow:visible}.plotly-graph-div{background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 22px rgba(15,23,42,.04)}details{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px;margin-top:18px;box-shadow:0 8px 22px rgba(15,23,42,.04)}summary{cursor:pointer;font-weight:760}pre{white-space:pre-wrap;word-break:break-word;background:#f8fafc;border:1px solid var(--line);padding:12px;border-radius:8px;max-height:520px;overflow:auto}.downloads{display:flex;flex-wrap:wrap;gap:10px}.downloads button{border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8;border-radius:8px;padding:8px 10px;font-weight:800;cursor:pointer}
@media(max-width:760px){.page{padding:18px}.hero{padding:20px}.hero-top{grid-template-columns:1fr}h1{font-size:28px}.metric-group summary{grid-template-columns:1fr}.grid{grid-template-columns:1fr}table{font-size:13px}th,td{padding:8px}}
</style>
</head><body>
<main class="page">
<section class="hero">
  <div class="hero-top">
    <div>
      <div class="eyebrow">Monocular Long Range UAV VO</div>
      <h1>VO 调参诊断报告</h1>
      <p class="subtitle">物流无人机 / 单目 VO / 长航程 / Sim3 形状评估</p>
    </div>
    <span class="badge ${status.className}">${escapeHtml(status.label)}</span>
  </div>
  <div class="hero-grid">
    <div class="hero-item"><div class="hero-label">estimate</div><div class="hero-value">${escapeHtml(report.inputs?.estimate?.name || "VO")}</div></div>
    <div class="hero-item"><div class="hero-label">reference</div><div class="hero-value">${escapeHtml(referenceLabel(report))}</div></div>
    <div class="hero-item"><div class="hero-label">matched frames</div><div class="hero-value">${escapeHtml(summary.matched_poses ?? "N/A")}</div></div>
    <div class="hero-item"><div class="hero-label">matched duration</div><div class="hero-value">${formatValue(summary.duration_s, "s")}</div></div>
    <div class="hero-item"><div class="hero-label">matched path length</div><div class="hero-value">${formatValue(summary.gt_path_length_m, "m")}</div></div>
    <div class="hero-item"><div class="hero-label">profile</div><div class="hero-value">${escapeHtml(report.config?.profile || "monocular_long_range_uav")}</div></div>
    <div class="hero-item"><div class="hero-label">alignment summary</div><div class="hero-value">${escapeHtml(alignmentSummaryLabel(report))}</div></div>
    <div class="hero-item"><div class="hero-label">risk level</div><div class="hero-value">${escapeHtml(status.shortLabel)}</div></div>
  </div>
  ${referenceWarningHtml(report)}
  <nav class="anchor-nav">
    <a href="#tuning">调参结论</a><a href="#health">健康指标</a><a href="#longrange">长航程</a><a href="#worst">最差片段</a><a href="#advanced">完整指标</a>
  </nav>
</section>
<section id="tuning">
  <h2>调参结论摘要</h2>
  <p class="section-note">这里不是简单列指标，而是按 P0/P1/P2 给出“先改什么、证据是什么、可能原因是什么”。</p>
  ${tuningConclusionTableHtml(tuningRows)}
</section>
<section id="health">
  <h2>核心健康指标 Dashboard</h2>
  <div class="grid health-grid">${healthCards.map(reportHealthCardHtml).join("\n")}</div>
</section>
<section>
  <h2>时间同步诊断</h2>
  <p class="section-note">这里说明 GT/Reference 和 VO 到底是如何放到同一时间轴上的。插值模式下，GT 会被插值到 VO 时间戳；nearest 模式不会插值。</p>
  ${associationDiagnosticTableHtml(associationRows)}
</section>
<section id="longrange">
  <h2>长航程子轨迹误差</h2>
  <p class="section-note">长距离段用于看累计漂移；短距离段用于看局部跟踪稳定性。百分比越低越好，p95 比 mean 更适合作为工程容差参考。</p>
  ${longRangeDiagnosticTableHtml(longRangeRows)}
</section>
<section id="worst">
  <h2>Top-K 最差片段</h2>
  <p class="section-note">这些片段最适合回放图像、特征数、RANSAC 内点率、关键帧和重定位日志。</p>
  ${worstSegmentsTableHtml(worstRows)}
</section>
<section>
  <h2>条件诊断</h2>
  ${conditionDiagnosticTableHtml(conditionRows)}
</section>
<section>
  <h2>A/B 对比</h2>
  ${comparisonPlaceholderHtml()}
</section>
<section>
  <h2>辅助论文指标</h2>
  <p class="section-note">这些指标仍然保留，但不作为首页第一优先级；命名会明确是否为分段 Sim3、全局 Sim3 或固定帧/固定时间 RPE。</p>
  <div class="grid">${auxiliaryCards.map(reportHealthCardHtml).join("\n")}</div>
</section>
<section>
  <h2>可视化</h2>
  ${figureSpecs.map((spec, index) => plotHtml(`reportPlot${index}`, spec)).join("\n")}
</section>
<section>
  <h2>导出与复现</h2>
  <p class="section-note">HTML 报告内嵌完整 report；如果在网页工具里导出，还可以拿到 per_pose、segment_records、worst_segments 和 config 文件。报告和 CSV 会包含轨迹坐标、时间戳、逐帧误差和最差片段；真实飞行或敏感数据请勿公开分享。</p>
  <div class="downloads">
    <button onclick="downloadEmbeddedReport('json')">下载 JSON 指标</button>
    <button onclick="downloadEmbeddedReport('per_pose')">下载每帧误差 CSV</button>
    <button onclick="downloadEmbeddedReport('segment_records')">下载子轨迹误差 CSV</button>
    <button onclick="downloadEmbeddedReport('worst_segments')">下载最差片段 CSV</button>
    <button onclick="downloadEmbeddedReport('config')">下载配置 JSON</button>
  </div>
</section>
<section>
  <h2>配置与数据</h2>
  <table><tbody>${configRows.map((row) => `<tr><th>${escapeHtml(row.label)}</th><td>${escapeHtml(row.value)}</td></tr>`).join("")}</tbody></table>
</section>
<section id="advanced">
  <h2>高级详情 / 完整指标</h2>
  <p class="section-note">完整指标默认折叠，展开后可以看到所有字段、中文解释以及它们反映的问题。逐帧 per_pose 和子轨迹明细请从上方 CSV 导出。</p>
  ${metricTableHtml(metricRows)}
</section>
<details>
  <summary>原始 JSON 指标</summary>
  <pre>${escapeHtml(JSON.stringify(report, null, 2))}</pre>
</details>
</main>
<script>
window.__VO_REPORT__ = ${safeJson(report)};
function downloadEmbeddedReport(kind) {
  const report = window.__VO_REPORT__ || {};
  if (kind === "json") return downloadBlob("vo_evaluation_metrics.json", JSON.stringify(report, null, 2), "application/json");
  if (kind === "config") return downloadBlob("vo_evaluation_config.json", JSON.stringify(report.config || {}, null, 2), "application/json");
  const rows = report[kind] || [];
  return downloadBlob("vo_" + kind + ".csv", rowsToCsv(rows), "text/csv");
}
function rowsToCsv(rows) {
  if (!Array.isArray(rows) || !rows.length) return "";
  const headers = Object.keys(rows[0]);
  const csvCell = (value) => {
    if (value === null || value === undefined) return "";
    const text = String(value);
    return /[",\\n]/.test(text) ? '"' + text.replaceAll('"', '""') + '"' : text;
  };
  return [headers.join(","), ...rows.map((row) => headers.map((key) => csvCell(row[key])).join(","))].join("\\n");
}
function downloadBlob(filename, text, mime) {
  const blob = new Blob([text], { type: mime + ";charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
<\/script>
</body></html>`;
}

function reportForHtmlExport(report) {
  const { trajectory_exports: _trajectoryExports, ...htmlReport } = report || {};
  return htmlReport;
}

function referenceLabel(report) {
  const input = report.inputs?.ground_truth;
  const name = input?.name || "reference trajectory";
  if (isLikelyImuReference(report)) {
    return `${name}（疑似 IMU/reference，请确认真值来源）`;
  }
  return name;
}

function isLikelyImuReference(report) {
  const name = (report.inputs?.ground_truth?.name || "").toLowerCase();
  return /\bimu\b|imu\.txt|惯性/.test(name);
}

function referenceWarningHtml(report) {
  if (!isLikelyImuReference(report)) {
    return "";
  }
  return `<div class="notice">reference: ${escapeHtml(report.inputs?.ground_truth?.name || "imu.txt")}（请确认是否为 GNSS/RTK/INS 融合轨迹；纯 IMU 积分不建议视为长航程真值）</div>`;
}

function alignmentSummaryLabel(report) {
  const cfg = report.config || {};
  const alignment = report.alignment || {};
  const mode = (alignment.base_mode || alignment.mode || cfg.alignment || "N/A").toString();
  const policy = cfg.continuous_segment_policy || report.discontinuities?.selected_segment?.policy || "N/A";
  if (policy === "segments" && mode.toLowerCase().includes("sim3")) {
    return "segment-wise Sim3 / 按连续段形状评估";
  }
  if (mode.toLowerCase().includes("sim3")) {
    return "global Sim3 / 全局尺度形状评估";
  }
  if (mode.toLowerCase().includes("se3")) {
    return "SE3 / 米制尺度刚体评估";
  }
  return `${policy} / ${mode}`;
}

function reportDiagnosticStatus(rows) {
  if (rows.some((row) => row.priority === "P0")) {
    return { label: "HIGH：必须先处理 P0 问题", shortLabel: "high", className: "high" };
  }
  if (rows.some((row) => row.priority === "P1")) {
    return { label: "WARNING：存在长航程风险", shortLabel: "warning", className: "warning" };
  }
  return { label: "GOOD：未触发主要调参告警", shortLabel: "good", className: "good" };
}

function buildTuningConclusionRows(report) {
  const rows = [];
  const summary = report.summary || {};
  const disc = report.discontinuities?.all_matches || {};
  const continuity = report.discontinuities?.continuity || disc.continuity || {};
  const alignment = report.alignment || {};
  const association = report.association || {};
  const correction = report.orientation_correction || {};
  const add = (priority, problem, evidence, cause, action, anchor) => rows.push({ priority, problem, evidence, cause, action, anchor });

  const breakCount = disc.break_count || 0;
  const maxGap = maxBreakGap(disc);
  if (isLikelyImuReference(report)) {
    add("P1", "Reference 真值来源需要确认", `reference 文件为 ${report.inputs?.ground_truth?.name || "imu.txt"}。`, "如果它只是纯 IMU 积分，长航程位置会快速漂移，不能当作可靠 ground truth。", "确认该文件是否来自 GNSS/RTK/INS 融合轨迹；若只有 IMU，先更换真值源再判断 VO 好坏。", "#advanced");
  }
  if (breakCount > 0) {
    add("P0", "VO 重置 / 大跳变", `断点 ${breakCount} 个，最大 gap ${formatValue(maxGap, "s")}。`, "跟踪丢失、重定位失败、关键帧/局部地图断裂，或 VO 输出中途重置坐标系。", "回放断点附近图像和日志；检查特征数、光流、RANSAC 内点率、关键帧切换、重定位/地图复用。", "#worst");
  }

  const scaleRange = scaleRangePercent(alignment);
  if (Number.isFinite(scaleRange) && scaleRange > 15) {
    add("P0", "单目尺度不稳定", `Sim3 scale ${formatNumber(alignment.scale_min)} 到 ${formatNumber(alignment.scale_max)}，变化 ${formatNumber(scaleRange)} %。`, "单目 VO 无绝对尺度，或不同连续段重初始化后尺度不同。", "检查尺度初始化和三角化基线；真实无人机定位需要高度计/GNSS/IMU/双目/深度等尺度源。", "#health");
  } else if (Number.isFinite(scaleRange) && scaleRange > 8) {
    add("P1", "尺度稳定性需要关注", `Sim3 scale 相对变化 ${formatNumber(scaleRange)} %。`, "局部尺度漂移、航段退化或重定位后坐标系尺度变化。", "比较各连续段 scale 与长距离 scale drift，确认是否只在某些航段发生。", "#longrange");
  }

  const coverage = summary.gt_time_coverage_ratio ?? summary.coverage_ratio;
  if (Number.isFinite(coverage) && coverage < 0.8) {
    add("P0", "评估覆盖不足", `GT 时间覆盖率 ${formatValue(100 * coverage, "%")}。`, "VO 与 reference 时间范围不一致，或插值阈值/时间偏移导致大量帧无法使用。", "先修时间戳单位、固定 offset、GT/VO 起止时间和最大插值间隔，再比较算法误差。", "#advanced");
  }

  const seg1000 = findSegment(report, 1000);
  const seg5000 = findSegment(report, 5000);
  const segLong = seg5000 || seg1000 || findLongestSegmentSummary(report);
  if (seg5000?.translation_error_percent?.p95 > 8 || seg1000?.translation_error_percent?.p95 > 5) {
    add("P0", "长距离累计漂移偏大", longRangeEvidence(seg1000, seg5000), "尺度、航向或后端约束随距离累积漂移，短段可能看不出来。", "重点看 1000/5000m 最差片段；增加长航程约束、地图复用、闭环、IMU/GNSS/高度计融合。", "#longrange");
  } else if (seg1000?.translation_error_percent?.mean > 2 || seg5000?.translation_error_percent?.mean > 4) {
    add("P1", "长距离漂移需要关注", longRangeEvidence(seg1000, seg5000), "长期尺度或航向漂移，可能影响巡航段定位。", "对比 1000m、2000m、5000m p95 和 Top-K 片段，优先修最坏航段。", "#longrange");
  } else if (segLong) {
    add("P2", "长航程漂移未触发高风险", `${formatNumber(segLong.length_m)}m mean ${formatValue(segLong.translation_error_percent?.mean, "%")}，p95 ${formatValue(segLong.translation_error_percent?.p95, "%")}。`, "当前长距离子轨迹统计没有超过默认阈值。", "仍建议结合任务容差和最差片段确认是否满足飞行要求。", "#longrange");
  }

  if (correction.auto && correction.selected && correction.selected !== "none" && correction.selected !== "ignore") {
    add("P1", "姿态坐标系需要固化", `auto selected ${correction.selected}，yaw RMSE ${formatValue(report.ate_yaw_deg?.rmse, "deg")}。`, "camera-to-body、ENU/NED、旋转取逆或 yaw/pitch/roll 约定不完全一致。", "在 VO 输出端明确外参和坐标系转换；不要长期依赖评估页面自动猜测。", "#advanced");
  }

  if (report.divergence?.diverged) {
    const priority = (report.divergence.first_divergence_distance_m || 0) < 100 ? "P2" : "P1";
    add(priority, "发散阈值被触发", `首次触发 distance=${formatValue(report.divergence.first_divergence_distance_m, "m")}，error=${formatValue(report.divergence.first_divergence_error_m, "m")}。`, "真实发散、断点附近大误差，或阈值不适合当前分段 Sim3 评估。", "优先看触发点是否靠近起点/断点；必要时调大 min_distance/min_time 或分段判断。", "#advanced");
  }

  const rawRatio = summary.raw_path_scale_ratio_est_over_gt;
  if (Number.isFinite(rawRatio) && (rawRatio < 0.8 || rawRatio > 1.25)) {
    add("P2", "VO 原始输出无尺度或尺度不一致", `Raw VO/GT 路程比 ${formatNumber(rawRatio)}。`, "单目 VO 原始单位不是米，或尺度没有被稳定约束。", "Sim3 可用于比较轨迹形状；如果要真实飞控定位，必须引入外部尺度源。", "#health");
  }

  if ((association.dropped_est_outside_gt_range || 0) > 0 || (association.dropped_est_large_gt_gap || 0) > 0) {
    add("P1", "部分 VO 帧未进入评估", `丢弃 ${association.dropped_est_outside_gt_range || 0} + ${association.dropped_est_large_gt_gap || 0} 帧。`, "VO 时间戳超出 reference 范围，或 GT 插值附近采样空洞太大。", "检查时间戳单位、固定偏移和 reference 数据连续性。", "#advanced");
  }

  const resetRateKm = continuity.reset_rate_per_km;
  if (Number.isFinite(resetRateKm) && resetRateKm > 0.2 && breakCount > 0) {
    add("P1", "单位航程重置率偏高", `重置率 ${formatValue(resetRateKm, "/km")}。`, "不同长度航线可比的连续性指标偏高，说明长航程稳定性不足。", "降低丢跟踪概率，增加重定位/地图复用，并分开统计每次 reset 前后的尺度。", "#health");
  }

  if (!rows.some((row) => row.priority === "P0" || row.priority === "P1")) {
    add("P2", "未发现阻塞调参的主要风险", "断点、尺度变化、覆盖率和长距离 p95 未触发默认高风险阈值。", "当前数据在默认规则下可用于下一轮对比。", "继续用 Top-K 片段和完整指标检查任务特定容差。", "#advanced");
  }

  return rows;
}

function tuningConclusionTableHtml(rows) {
  return `<table><thead><tr><th>优先级</th><th>问题</th><th>证据</th><th>可能原因</th><th>建议动作</th><th>跳转</th></tr></thead><tbody>${rows.map((row) => `<tr><td><span class="priority ${row.priority.toLowerCase()}">${escapeHtml(row.priority)}</span></td><td>${escapeHtml(row.problem)}</td><td>${escapeHtml(row.evidence)}</td><td>${escapeHtml(row.cause)}</td><td>${escapeHtml(row.action)}</td><td><a href="${escapeHtml(row.anchor)}">${escapeHtml(anchorLabel(row.anchor))}</a></td></tr>`).join("")}</tbody></table>`;
}

function buildHealthDashboardCards(report) {
  const summary = report.summary || {};
  const disc = report.discontinuities?.all_matches || {};
  const continuity = report.discontinuities?.continuity || disc.continuity || {};
  const alignment = report.alignment || {};
  const seg100 = findSegment(report, 100);
  const seg1000 = findSegment(report, 1000);
  const seg5000 = findSegment(report, 5000);
  const scaleRange = scaleRangePercent(alignment);
  const maxGap = maxBreakGap(disc);
  const cards = [
    {
      label: "断点数量",
      value: disc.break_count ?? "N/A",
      note: "长航程连续性；非零表示 VO 可能 reset、丢跟踪或输出中断。",
      source: "discontinuities.all_matches.break_count",
      severity: (disc.break_count || 0) > 0 ? "high" : "good",
    },
    {
      label: "最大时间 gap",
      value: formatValue(maxGap, "s"),
      note: "判断 VO 是否长时间无有效输出；越大越不适合连续定位。",
      source: "discontinuities.all_matches.breaks[].time_gap_s",
      severity: maxGap > 5 ? "high" : maxGap > 1 ? "warning" : "good",
    },
    {
      label: "最长连续段",
      value: `${formatValue(continuity.longest_continuous_segment_m, "m")} / ${formatValue(continuity.longest_continuous_segment_s, "s")}`,
      note: "比断点数量更直观；看单次不 reset 能飞多远。",
      source: "discontinuities.continuity.longest_continuous_segment_m/s",
      severity: continuity.longest_continuous_segment_m && continuity.longest_continuous_segment_m < 1000 ? "warning" : "info",
    },
    {
      label: "重置率",
      value: formatValue(continuity.reset_rate_per_km, "/km"),
      note: "不同航线长度可比；越高说明连续性越差。",
      source: "discontinuities.continuity.reset_rate_per_km",
      severity: continuity.reset_rate_per_km > 0 ? "warning" : "good",
    },
    {
      label: "Raw VO/GT 路程比",
      value: formatNumber(summary.raw_path_scale_ratio_est_over_gt),
      note: "原始 VO 是否接近米制；明显不为 1 表示无尺度或尺度不一致。",
      source: "summary.raw_path_scale_ratio_est_over_gt",
      severity: ratioSeverity(summary.raw_path_scale_ratio_est_over_gt),
    },
    {
      label: "Sim3 scale 范围",
      value: scaleRangeText(alignment) || "N/A",
      note: "分段尺度是否一致；范围越大越说明单目尺度不稳。",
      source: "alignment.scale_min / scale_max / scale",
      severity: scaleRange > 15 ? "high" : scaleRange > 8 ? "warning" : "info",
    },
    {
      label: "100m 局部漂移",
      value: percentMeanP95(seg100?.translation_error_percent),
      note: "短距离局部稳定性；偏高优先查前端跟踪和图像质量。",
      source: "segment_errors[100m].translation_error_percent",
      severity: segmentSeverity(seg100?.translation_error_percent, 5, 10),
    },
    {
      label: "1000m 巡航漂移",
      value: percentMeanP95(seg1000?.translation_error_percent),
      note: "巡航段累计漂移；偏高通常是尺度、航向或后端约束问题。",
      source: "segment_errors[1000m].translation_error_percent",
      severity: segmentSeverity(seg1000?.translation_error_percent, 2, 5),
    },
    {
      label: "5000m 长航程漂移",
      value: percentMeanP95(seg5000?.translation_error_percent),
      note: "长航程累计误差；样本少时需要结合 Top-K 和完整明细。",
      source: "segment_errors[5000m].translation_error_percent",
      severity: segmentSeverity(seg5000?.translation_error_percent, 4, 8),
    },
    {
      label: "1000m yaw drift p95",
      value: formatValue(seg1000?.segment_yaw_error_abs_deg?.p95, "deg"),
      note: "固定距离航向漂移；偏高要查 yaw 约定、外参、IMU/视觉姿态融合。",
      source: "segment_errors[1000m].segment_yaw_error_abs_deg.p95",
      severity: seg1000?.segment_yaw_error_abs_deg?.p95 > 5 ? "warning" : "info",
    },
    {
      label: "1000m vertical drift p95",
      value: formatValue(seg1000?.vertical_error_abs_m?.p95, "m"),
      note: "固定距离高度误差；偏高要查 Z 轴方向、尺度和高度约束。",
      source: "segment_errors[1000m].vertical_error_abs_m.p95",
      severity: seg1000?.vertical_error_abs_m?.p95 > 20 ? "warning" : "info",
    },
    {
      label: "Frame-to-frame RPE",
      value: formatValue(report.rpe_frame_delta?.translation_m?.rmse, "m"),
      note: `${rpeDeltaLabel(report.rpe_frame_delta)} 相对平移误差；偏高说明局部相对运动估计不稳。`,
      source: "rpe_frame_delta.translation_m.rmse",
      severity: "info",
    },
  ];
  return cards.slice(0, 12);
}

function reportHealthCardHtml(item) {
  return `<div class="card ${escapeHtml(item.severity || "info")}"><div class="metric-label">${escapeHtml(item.label)}</div><div class="metric-value">${escapeHtml(item.value)}</div><div class="metric-note">${escapeHtml(item.note || "")}</div><div class="metric-source"><code>${escapeHtml(item.source || "")}</code></div></div>`;
}

function buildAssociationDiagnosticRows(report) {
  const assoc = report.association || {};
  const summary = report.summary || {};
  const mode = assoc.mode || assoc.method || "N/A";
  const rows = [
    {
      label: "时间同步方式",
      value: mode,
      meaning: mode === "interpolate_gt" ? "真正执行 GT 插值，不是最近邻匹配。" : mode === "nearest" ? "阈值内最近时间戳一一匹配，不进行轨迹插值。" : "按索引或其他方式对齐。",
    },
    {
      label: "Position interpolation",
      value: assoc.position_method || (mode === "interpolate_gt" ? "linear" : "N/A"),
      meaning: "interpolate_gt 模式下，reference position 使用时间线性插值。",
    },
    {
      label: "Rotation interpolation",
      value: assoc.rotation_method || (mode === "interpolate_gt" ? "slerp / skipped if unavailable" : "N/A"),
      meaning: "reference 有姿态时使用 SLERP；没有姿态时只插 position，姿态类指标自动跳过。",
    },
    {
      label: "是否允许外推",
      value: assoc.allow_extrapolation ? "yes" : "no",
      meaning: "默认 no。VO 时间戳早于 reference 首帧或晚于末帧时会被丢弃，不会硬外推。",
    },
    {
      label: "插值目标时间轴",
      value: assoc.target || (mode === "interpolate_gt" ? "estimate_timestamps" : "nearest_timestamp_pairs"),
      meaning: "estimate_timestamps 表示以 VO 输出时刻为评估基准；nearest_timestamp_pairs 表示只保留时间差足够小的离散配对。",
    },
    {
      label: "原始 VO 帧数",
      value: assoc.estimate_count_input ?? assoc.estimate_pose_count ?? summary.est_poses ?? "N/A",
      meaning: "VO 文件中可解析出的原始输出数量。",
    },
    {
      label: "原始 Reference 帧数",
      value: assoc.reference_count_input ?? assoc.reference_pose_count ?? summary.gt_poses ?? "N/A",
      meaning: "GT/reference 文件中可解析出的原始轨迹数量。",
    },
    {
      label: "成功对齐帧数",
      value: assoc.matched_count ?? assoc.matches ?? summary.matched_poses ?? "N/A",
      meaning: "最终进入 ATE/RPE/子轨迹误差计算的 VO 时间戳数量。",
    },
    {
      label: "丢弃 VO 帧数",
      value: assoc.dropped_count ?? assoc.dropped ?? ((assoc.dropped_est_outside_gt_range || 0) + (assoc.dropped_est_large_gt_gap || 0)),
      meaning: "没有进入评估的 VO 帧；插值模式下主要来自超出 GT 时间范围或 GT 空洞过大。",
    },
    {
      label: "VO 插值覆盖率",
      value: formatValue(100 * (assoc.coverage_estimate_ratio ?? assoc.est_pose_coverage_ratio), "%"),
      meaning: "成功插值帧数 / 原始 VO 帧数。低于 80% 时优先检查时间戳单位、时间范围、time_offset_s 和 max_interpolation_gap_s。",
    },
    {
      label: "早于 Reference 范围",
      value: assoc.dropped_before_reference_range ?? 0,
      meaning: "VO 时间戳加 time_offset_s 后早于 reference 第一帧，默认不外推所以丢弃。",
    },
    {
      label: "晚于 Reference 范围",
      value: assoc.dropped_after_reference_range ?? 0,
      meaning: "VO 时间戳加 time_offset_s 后晚于 reference 最后一帧，默认不外推所以丢弃。",
    },
    {
      label: "超出 GT 范围",
      value: assoc.outside_gt_range_count ?? assoc.dropped_est_outside_gt_range ?? 0,
      meaning: "VO 时间戳加 time_offset_s 后不在 GT/reference 起止时间内，因此无法评估。",
    },
    {
      label: "GT 空洞过大",
      value: assoc.dropped_gt_gap_too_large ?? assoc.large_interpolation_gap_count ?? assoc.dropped_est_large_gt_gap ?? 0,
      meaning: "目标 VO 时刻左右相邻 GT 样本间隔超过 max_interpolation_gap_s，系统拒绝跨空洞插值。",
    },
    {
      label: "无效时间戳",
      value: assoc.dropped_invalid_timestamp ?? 0,
      meaning: "VO 时间戳不是有效数字，无法用于插值或匹配。",
    },
    {
      label: "最大允许插值间隔",
      value: formatValue(assoc.max_interpolation_gap_s_allowed ?? assoc.max_interpolation_gap_config_s, "s"),
      meaning: "配置阈值；只在 interpolate_gt 模式下用于过滤 GT 空洞。",
    },
    {
      label: "最大使用插值间隔",
      value: formatValue(assoc.max_used_gt_gap_s ?? assoc.max_interpolation_gap_used_s ?? assoc.max_interpolation_gap_s, "s"),
      meaning: "实际成功插值样本中，左右 GT 样本的最大时间间隔；越大表示 GT 采样越稀或局部有空洞。",
    },
    {
      label: "平均使用插值间隔",
      value: formatValue(assoc.mean_used_gt_gap_s ?? assoc.mean_interpolation_gap_s, "s"),
      meaning: "实际成功插值样本的平均 GT 左右样本间隔；越小通常时间同步越可靠。",
    },
    {
      label: "P95 使用插值间隔",
      value: formatValue(assoc.p95_used_gt_gap_s ?? assoc.p95_interpolation_gap_s, "s"),
      meaning: "95% 成功插值样本使用的 GT 左右间隔不超过这个值；比 max 更适合判断常态插值质量。",
    },
    {
      label: "time_offset_s",
      value: formatValue(assoc.time_offset_s, "s"),
      meaning: "先把 VO 时间戳加上该值，再映射到 GT 时间轴。正值表示 VO 时间戳向后移，负值表示向前移。",
    },
  ];
  if (mode === "nearest") {
    rows.push({
      label: "nearest 最大时间差",
      value: formatValue(assoc.max_time_diff_s, "s"),
      meaning: "nearest / TUM greedy 模式下使用的时间差阈值；该模式不做 position 插值，也不做 rotation SLERP。",
    });
  }
  return rows;
}

function associationDiagnosticTableHtml(rows) {
  return `<table><thead><tr><th>字段</th><th>值</th><th>解释</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.label)}</td><td>${escapeHtml(row.value)}</td><td>${escapeHtml(row.meaning)}</td></tr>`).join("")}</tbody></table>`;
}

function buildLongRangeDiagnosticRows(report) {
  return (report.segment_errors || []).map((row) => {
    const tag = longRangeTag(row);
    return {
      length: formatNumber(row.length_m),
      count: row.count ?? 0,
      mean: formatNumber(row.translation_error_percent?.mean),
      p95: formatNumber(row.translation_error_percent?.p95),
      max: formatNumber(row.translation_error_percent?.max),
      yawP95: formatValue(row.segment_yaw_error_abs_deg?.p95, "deg"),
      verticalP95: formatValue(row.vertical_error_abs_m?.p95, "m"),
      scaleP95: formatValue(row.scale_drift_percent?.p95, "%"),
      tag,
    };
  });
}

function longRangeDiagnosticTableHtml(rows) {
  if (!rows.length) {
    return `<div class="card">没有可用的子轨迹统计。需要检查轨迹长度、segment_lengths_m 或长度容差设置。</div>`;
  }
  return `<table><thead><tr><th>长度 m</th><th>样本数</th><th>平移 mean %</th><th>平移 p95 %</th><th>平移 max %</th><th>yaw p95</th><th>vertical p95</th><th>scale p95</th><th>诊断标签</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${row.length}</td><td>${row.count}</td><td>${row.mean}</td><td>${row.p95}</td><td>${row.max}</td><td>${row.yawP95}</td><td>${row.verticalP95}</td><td>${row.scaleP95}</td><td><span class="tag ${row.tag.className}">${escapeHtml(row.tag.label)}</span></td></tr>`).join("")}</tbody></table>`;
}

function buildWorstSegmentRows(report) {
  return (report.worst_segments || []).map((row, index) => ({
    rank: row.rank ?? index + 1,
    time: `${formatValue(row.start_time_s, "s")} -> ${formatValue(row.end_time_s, "s")}`,
    length: formatValue(row.length_m ?? row.actual_length_m, "m"),
    errorPercent: formatValue(row.translation_error_percent, "%"),
    errorMeter: formatValue(row.translation_error_m, "m"),
    speed: formatValue(row.speed_mps, "m/s"),
    yaw: formatValue(row.yaw_error_abs_deg, "deg"),
    vertical: formatValue(row.vertical_error_abs_m, "m"),
    nearBreak: row.near_break ? "是" : "否",
    action: worstSegmentAction(row),
  }));
}

function worstSegmentsTableHtml(rows) {
  if (!rows.length) {
    return `<div class="card good">没有可用 Top-K 片段。通常是子轨迹样本为空，或当前轨迹长度不足以计算配置的 segment_lengths_m。</div>`;
  }
  return `<table><thead><tr><th>#</th><th>时间段</th><th>长度</th><th>平移误差</th><th>米级误差</th><th>速度</th><th>yaw</th><th>vertical</th><th>近断点</th><th>建议动作</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${row.rank}</td><td>${row.time}</td><td>${row.length}</td><td>${row.errorPercent}</td><td>${row.errorMeter}</td><td>${row.speed}</td><td>${row.yaw}</td><td>${row.vertical}</td><td>${row.nearBreak}</td><td>${escapeHtml(row.action)}</td></tr>`).join("")}</tbody></table>`;
}

function buildConditionDiagnosticRows(report) {
  const rows = [];
  const speedBins = report.speed_bins || [];
  if (speedBins.length) {
    const worst = speedBins.reduce((best, row) => {
      const score = row.translation_error_percent?.p95 ?? row.translation_error_percent?.mean ?? -Infinity;
      const bestScore = best?.translation_error_percent?.p95 ?? best?.translation_error_percent?.mean ?? -Infinity;
      return score > bestScore ? row : best;
    }, null);
    rows.push({
      condition: "速度分箱",
      status: "available",
      evidence: worst ? `${worst.speed_bin_mps}: p95 ${formatValue(worst.translation_error_percent?.p95, "%")}，count ${worst.count}` : "无速度分箱统计。",
      meaning: "判断高速、低速或巡航速度下 VO 是否退化；高速差通常看运动模糊/曝光/滚快门，低速差看弱纹理/悬停退化。",
    });
  } else {
    rows.push({ condition: "速度分箱", status: "not available", evidence: "没有 speed_bins。", meaning: "需要 segment_records 中有 duration 和 length 才能按速度聚合。" });
  }
  const worstNearBreak = (report.worst_segments || []).filter((row) => row.near_break).length;
  rows.push({
    condition: "断点附近",
    status: worstNearBreak ? "available" : "compatible",
    evidence: worstNearBreak ? `Top-K 中 ${worstNearBreak} 个靠近断点。` : "Top-K 中未标记 near_break，或当前没有断点。",
    meaning: "如果最差片段集中在断点附近，优先修跟踪丢失、重定位和 reset，而不是先调普通帧间误差。",
  });
  rows.push({
    condition: "转弯 / yaw-rate",
    status: "not available",
    evidence: "当前 report 没有 yaw_rate_deg_s 分箱。",
    meaning: "需要在 segment_records 中增加 yaw rate 后，才能判断急转弯是否导致方向估计退化。",
  });
  rows.push({
    condition: "爬升 / 下降",
    status: "not available",
    evidence: "当前 report 没有 climb_rate_mps 分箱。",
    meaning: "需要在 segment_records 中增加 climb rate 后，才能判断高度变化是否导致尺度或 Z 轴漂移。",
  });
  return rows;
}

function conditionDiagnosticTableHtml(rows) {
  return `<table><thead><tr><th>条件</th><th>状态</th><th>证据</th><th>能反映什么问题</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.condition)}</td><td><span class="tag ${row.status === "available" ? "good" : row.status === "compatible" ? "info" : "warning"}">${escapeHtml(row.status)}</span></td><td>${escapeHtml(row.evidence)}</td><td>${escapeHtml(row.meaning)}</td></tr>`).join("")}</tbody></table>`;
}

function comparisonPlaceholderHtml() {
  return `<div class="card info"><div class="metric-label">当前报告未包含 baseline</div><div class="metric-value">A/B 对比待接入</div><div class="metric-note">如果后续上传 baseline_report + current_report，可直接对比断点数量、scale variation、1000/5000m p95、Top-K 最差片段和运行耗时。</div><div class="metric-source"><code>comparison</code></div></div>`;
}

function buildAuxiliaryMetricCards(report) {
  const ateLabel = report.ate?.primary_label || ateMetricName(report);
  const cards = [
    {
      label: `${ateLabel} RMSE`,
      value: formatValue((report.ate?.primary_position_m || report.ate_position_m)?.rmse, "m"),
      note: "对齐后整体位置误差；如果是 segment-wise Sim3，只代表每个连续段形状，不代表跨 reset 连续性。",
      source: "ate.primary_position_m.rmse",
      severity: "info",
    },
    {
      label: "Global Sim3 ATE RMSE",
      value: formatValue(report.ate?.global_sim3_ate_position_m?.rmse || report.ate?.global?.sim3?.position_m?.rmse, "m"),
      note: "全程只用一个 Sim3 对齐；比 segment-wise 更能暴露跨段尺度和坐标不一致。",
      source: "ate.global.sim3.position_m.rmse",
      severity: "info",
    },
    {
      label: "Frame-to-frame RPE translation",
      value: formatValue(report.rpe_frame_delta?.translation_m?.rmse, "m"),
      note: `${rpeDeltaLabel(report.rpe_frame_delta)}；反映局部相对运动稳定性。`,
      source: "rpe_frame_delta.translation_m.rmse",
      severity: "info",
    },
    {
      label: "1s RPE translation",
      value: formatValue(report.rpe_time_delta?.["1s"]?.translation_m?.rmse, "m"),
      note: "固定 1 秒间隔，避免不同帧率下 frame delta 不可比。",
      source: "rpe_time_delta.1s.translation_m.rmse",
      severity: "info",
    },
    {
      label: "5s RPE translation",
      value: formatValue(report.rpe_time_delta?.["5s"]?.translation_m?.rmse, "m"),
      note: "中短时累计漂移，比相邻帧更接近飞行控制窗口。",
      source: "rpe_time_delta.5s.translation_m.rmse",
      severity: "info",
    },
    {
      label: "10s RPE translation",
      value: formatValue(report.rpe_time_delta?.["10s"]?.translation_m?.rmse, "m"),
      note: "固定 10 秒局部累计误差；适合看巡航段局部稳定性。",
      source: "rpe_time_delta.10s.translation_m.rmse",
      severity: "info",
    },
    {
      label: "Endpoint drift",
      value: `${formatValue(report.summary?.endpoint_error_m, "m")} / ${formatValue(report.summary?.endpoint_error_percent_of_path, "%")}`,
      note: "最终位置偏差；长航程任务中需要和落点/航线容差对比。",
      source: "summary.endpoint_error_m / endpoint_error_percent_of_path",
      severity: "info",
    },
    {
      label: "Attitude / yaw RMSE",
      value: `${formatValue(report.ate_orientation_deg?.rmse, "deg")} / ${formatValue(report.ate_yaw_deg?.rmse, "deg")}`,
      note: "姿态和航向误差；偏高优先检查欧拉角顺序、角度/弧度、ENU/NED、camera-to-body。",
      source: "ate_orientation_deg.rmse / ate_yaw_deg.rmse",
      severity: "info",
    },
  ];
  return cards;
}

function maxBreakGap(discontinuities) {
  return Math.max(...(discontinuities?.breaks || []).map((item) => item.time_gap_s || 0), 0);
}

function longRangeEvidence(seg1000, seg5000) {
  const parts = [];
  if (seg1000) {
    parts.push(`1000m mean ${formatValue(seg1000.translation_error_percent?.mean, "%")} / p95 ${formatValue(seg1000.translation_error_percent?.p95, "%")}`);
  }
  if (seg5000) {
    parts.push(`5000m mean ${formatValue(seg5000.translation_error_percent?.mean, "%")} / p95 ${formatValue(seg5000.translation_error_percent?.p95, "%")}`);
  }
  return parts.length ? parts.join("；") : "缺少 1000m/5000m 子轨迹样本。";
}

function percentMeanP95(stat) {
  if (!stat) {
    return "N/A";
  }
  return `${formatValue(stat.mean, "%")} / ${formatValue(stat.p95, "%")}`;
}

function ratioSeverity(value) {
  if (!Number.isFinite(value)) return "info";
  return value < 0.8 || value > 1.25 ? "warning" : "good";
}

function segmentSeverity(stat, warnMean, highP95) {
  if (!stat) return "info";
  if (stat.p95 > highP95) return "high";
  if (stat.mean > warnMean) return "warning";
  return "good";
}

function longRangeTag(row) {
  const p95 = row.translation_error_percent?.p95;
  const scaleP95 = Math.abs(row.scale_drift_percent?.p95 || 0);
  const yawP95 = row.segment_yaw_error_abs_deg?.p95;
  const verticalP95 = row.vertical_error_abs_m?.p95;
  if (p95 > 8) return { label: "平移漂移高", className: "high" };
  if (scaleP95 > 15) return { label: "尺度漂移高", className: "high" };
  if (yawP95 > 8) return { label: "航向漂移高", className: "warning" };
  if (verticalP95 > 30) return { label: "高度漂移高", className: "warning" };
  if (p95 > 3) return { label: "需要关注", className: "warning" };
  return { label: "正常", className: "good" };
}

function worstSegmentAction(row) {
  if (row.near_break) {
    return "优先回放断点附近：检查丢跟踪、重定位、地图切换和 reset。";
  }
  if ((row.yaw_error_abs_deg || 0) > 8) {
    return "重点检查航向：yaw 约定、外参、ENU/NED 或 IMU/视觉姿态融合。";
  }
  if ((row.vertical_error_abs_m || 0) > 30) {
    return "重点检查高度：Z 轴方向、尺度、气压计/高度计约束和爬升下降场景。";
  }
  if ((row.speed_mps || 0) > 16) {
    return "重点检查高速段：运动模糊、曝光、滚快门、特征跟踪和 RANSAC。";
  }
  return "回放该时间段图像和前端/后端日志，定位平移漂移来源。";
}

function findLongestSegmentSummary(report) {
  const rows = report.segment_errors || [];
  if (!rows.length) return null;
  return rows.reduce((best, row) => (row.length_m > (best?.length_m || -Infinity) ? row : best), null);
}

function ateMetricName(report) {
  const cfg = report.config || {};
  if (cfg.continuous_segment_policy === "segments" && String(cfg.alignment || "").toLowerCase() === "sim3") {
    return "Segment-wise Sim3 ATE";
  }
  if (String(cfg.alignment || "").toLowerCase() === "sim3") {
    return "Global Sim3 ATE";
  }
  if (String(cfg.alignment || "").toLowerCase() === "se3") {
    return "SE3 ATE";
  }
  return "ATE";
}

function anchorLabel(anchor) {
  return {
    "#worst": "Top-K",
    "#health": "健康指标",
    "#longrange": "长航程",
    "#advanced": "高级详情",
  }[anchor] || "详情";
}

function buildReportPlotSpecs(report) {
  const perPose = report.per_pose || [];
  const segmentSummary = report.segment_errors || [];
  const worstSegments = report.worst_segments || [];
  const [dist3d, err3d] = segmentedValues(perPose, ["distance_m", "error_m"]);
  const lengths = segmentSummary.map((row) => row.length_m);

  return [
    {
      title: "长航程漂移 vs 距离",
      data: [
        { x: lengths, y: segmentSummary.map((row) => row.translation_error_percent?.mean), mode: "lines+markers", type: "scatter", name: "translation mean %" },
        { x: lengths, y: segmentSummary.map((row) => row.translation_error_percent?.p95), mode: "lines+markers", type: "scatter", name: "translation p95 %" },
        { x: lengths, y: segmentSummary.map((row) => row.translation_error_percent?.max), mode: "lines+markers", type: "scatter", name: "translation max %" },
      ],
      layout: reportLayout("长航程漂移 vs 距离", {
        xaxis: { title: "segment length m" },
        yaxis: { title: "translation error %" },
      }),
    },
    {
      title: "尺度稳定性",
      data: [
        { x: lengths, y: segmentSummary.map((row) => row.raw_scale_ratio_est_over_gt?.mean ?? row.scale_ratio_est_over_gt?.mean), mode: "lines+markers", type: "scatter", name: "raw scale ratio mean" },
        { x: lengths, y: segmentSummary.map((row) => row.raw_scale_ratio_est_over_gt?.p95 ?? row.scale_ratio_est_over_gt?.p95), mode: "lines+markers", type: "scatter", name: "raw scale ratio p95" },
        { x: lengths, y: segmentSummary.map((row) => row.scale_drift_percent?.p95), mode: "lines+markers", type: "scatter", name: "scale drift p95 %", yaxis: "y2" },
      ],
      layout: reportLayout("尺度稳定性", {
        xaxis: { title: "segment length m" },
        yaxis: { title: "scale ratio" },
        yaxis2: { title: "scale drift %", overlaying: "y", side: "right" },
      }),
    },
    {
      title: worstSegments.length ? "Top-K 最差片段" : "误差随路程变化",
      data: worstSegments.length ? [
        { x: worstSegments.map((row) => `#${row.rank}`), y: worstSegments.map((row) => row.translation_error_percent), type: "bar", name: "translation error %", text: worstSegments.map((row) => `${formatValue(row.start_time_s, "s")} -> ${formatValue(row.end_time_s, "s")}`), hovertemplate: "%{x}<br>%{y:.3f}%<br>%{text}<extra></extra>" },
        { x: worstSegments.map((row) => `#${row.rank}`), y: worstSegments.map((row) => row.yaw_error_abs_deg), mode: "lines+markers", type: "scatter", name: "yaw error deg", yaxis: "y2" },
      ] : [
        { x: dist3d, y: err3d, mode: "lines", type: "scatter", name: "3D error" },
      ],
      layout: worstSegments.length ? reportLayout("Top-K 最差片段", {
        xaxis: { title: "worst segment rank" },
        yaxis: { title: "translation error %" },
        yaxis2: { title: "yaw error deg", overlaying: "y", side: "right" },
      }) : reportLayout("误差随路程变化", { xaxis: { title: "distance m" }, yaxis: { title: "error m" } }),
    },
  ];
}

function reportLayout(title, extra = {}) {
  return {
    title,
    height: 380,
    margin: { l: 58, r: 28, t: 52, b: 50 },
    legend: { orientation: "h" },
    ...extra,
  };
}

function plotHtml(id, spec) {
  return `<div class="chart"><div id="${id}" class="plotly-graph-div" style="height:${spec.layout.height || 380}px;width:100%;"></div><script>
if (document.getElementById("${id}")) {
  Plotly.newPlot("${id}", ${safeJson(spec.data)}, ${safeJson(spec.layout)}, {responsive: true});
}
<\/script></div>`;
}

function safeJson(value) {
  return JSON.stringify(value).replaceAll("</", "<\\/");
}

function buildConfigRows(report) {
  const summary = report.summary || {};
  const cfg = report.config || {};
  const assoc = report.association || {};
  const correction = report.orientation_correction || {};
  return [
    { label: "Ground truth", value: `${report.inputs?.ground_truth?.name || "N/A"} (${report.inputs?.ground_truth?.format || "N/A"})` },
    { label: "VO 输出", value: `${report.inputs?.estimate?.name || "N/A"} (${report.inputs?.estimate?.format || "N/A"})` },
    { label: "时间同步", value: `${assoc.method || assoc.mode || "N/A"}，匹配 ${assoc.matches ?? "N/A"} 帧` },
    { label: "轨迹对齐", value: cfg.alignment || "N/A" },
    { label: "姿态修正", value: correction.auto ? `auto -> ${correction.selected}` : (correction.selected || cfg.orientation_correction || "N/A") },
    { label: "RPE 间隔", value: rpeDeltaLabel(report.rpe_frame_delta || cfg) },
    { label: "尺度图间隔", value: rpeDeltaLabel(report.scale_frame_delta || cfg) },
    { label: "断点策略", value: cfg.continuous_segment_policy || "N/A" },
    { label: "评估路程/耗时", value: `${formatValue(summary.gt_path_length_m, "m")} / ${formatValue(summary.duration_s, "s")}` },
  ];
}

function flattenReportMetrics(report) {
  const rows = [];
  const skipRoot = new Set(["per_pose", "segment_records"]);
  const skipLeaf = new Set(["segment_ids"]);

  function add(path, value) {
    if (!path) {
      return;
    }
    const root = path.split(".")[0];
    const leaf = path.split(".").at(-1);
    if (skipRoot.has(root) || skipLeaf.has(leaf)) {
      return;
    }
    if (value === null || value === undefined) {
      rows.push({ metric: path, value: "" });
      return;
    }
    if (typeof value === "number" || typeof value === "string" || typeof value === "boolean") {
      rows.push({ metric: path, value: metricValueText(value) });
      return;
    }
    if (Array.isArray(value)) {
      if (value.length > 60 && value.every((item) => typeof item !== "object" || item === null)) {
        rows.push({ metric: path, value: `[${value.length} values skipped; see raw JSON]` });
        return;
      }
      value.forEach((item, index) => add(`${path}[${index}]`, item));
      return;
    }
    if (typeof value === "object") {
      Object.entries(value).forEach(([key, item]) => add(path ? `${path}.${key}` : key, item));
    }
  }

  Object.entries(report || {}).forEach(([key, value]) => add(key, value));
  return rows;
}

function metricValueText(value) {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return "N/A";
    }
    return Number.isInteger(value) ? String(value) : value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  }
  return String(value);
}

function metricTableHtml(rows) {
  if (!rows.length) {
    return `<div class="card">没有可展示的统计值。</div>`;
  }
  return groupMetricRows(rows).map((group) => {
    const body = group.items.map((item) => `<tr><td>${escapeHtml(metricParamLabel(item.metric, item.field))}</td><td><code>${escapeHtml(item.metric)}</code></td><td>${escapeHtml(item.value)}</td><td>${escapeHtml(metricIssue(item.metric, item.value))}</td></tr>`).join("");
    return `<details class="metric-group"><summary><span class="group-title">${escapeHtml(metricGroupLabel(group.key))}</span><code>${escapeHtml(group.key)}</code><span class="group-count">${group.items.length} 项</span></summary><p class="metric-help">${escapeHtml(metricIssue(group.key))}</p><table><thead><tr><th>参数</th><th>原始字段</th><th>值</th><th>反映的问题</th></tr></thead><tbody>${body}</tbody></table></details>`;
  }).join("");
}

function groupMetricRows(rows) {
  const groups = new Map();
  for (const row of rows) {
    const [key, field] = splitMetricPath(row.metric);
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key).push({ ...row, field });
  }
  return Array.from(groups.entries()).map(([key, items]) => ({ key, items }));
}

function splitMetricPath(metric) {
  const index = metric.lastIndexOf(".");
  if (index < 0) {
    return ["general", metric];
  }
  return [metric.slice(0, index), metric.slice(index + 1)];
}

const METRIC_GROUP_LABELS = {
  summary: "总体统计",
  inputs: "输入文件",
  config: "评估配置",
  association: "时间同步与匹配",
  alignment: "轨迹对齐",
  ate_position_m: "ATE 绝对位置误差",
  ate_horizontal_m: "水平 ATE",
  ate_vertical_m: "垂直 ATE",
  ate_orientation_deg: "姿态 ATE",
  ate_yaw_deg: "Yaw 绝对误差",
  orientation_correction: "姿态修正选择",
  rpe_frame_delta: "RPE 相对位姿误差",
  divergence: "发散检测",
  runtime: "耗时统计",
  discontinuities: "断点/重置诊断",
  segment_errors: "长航程子轨迹误差",
  speed_bins: "速度分箱误差",
};

const METRIC_FIELD_LABELS = {
  count: "样本数",
  rmse: "均方根误差",
  mean: "平均值",
  median: "中位数",
  std: "标准差",
  min: "最小值",
  max: "最大值",
  p95: "95 分位值",
  p99: "99 分位值",
  length_m: "子轨迹长度",
  speed_bin_mps: "速度区间",
  translation_error_percent: "平移误差百分比",
  translation_m: "平移误差",
  rotation_error_deg_per_m: "旋转误差 deg/m",
  rotation_deg: "旋转误差",
  translation_error_m: "平移误差 m",
  scale_drift_percent: "尺度漂移百分比",
  scale_ratio_est_over_gt: "VO/GT 尺度比",
  gt_path_length_m: "GT 轨迹长度",
  est_path_length_raw_m: "VO 原始轨迹长度",
  est_path_length_aligned_m: "VO 对齐后轨迹长度",
  duration_s: "评估时长",
  matched_poses: "匹配位姿数",
  original_matched_poses: "原始匹配位姿数",
  gt_poses: "GT 位姿数",
  est_poses: "VO 位姿数",
  coverage_ratio: "覆盖率",
  gt_pose_coverage_ratio: "GT 位姿覆盖率",
  gt_time_coverage_ratio: "GT 时间覆盖率",
  est_pose_coverage_ratio: "VO 匹配率",
  endpoint_error_m: "终点误差",
  endpoint_error_percent_of_path: "终点误差占路程比例",
  raw_path_scale_ratio_est_over_gt: "VO/GT 原始路程比",
  scale: "对齐尺度",
  scale_min: "分段最小尺度",
  scale_max: "分段最大尺度",
  scale_std: "分段尺度标准差",
  method: "匹配方法",
  mode: "匹配模式",
  target: "插值/匹配目标时间轴",
  interpolated: "是否执行插值",
  position_method: "位置插值方法",
  rotation_method: "姿态插值方法",
  allow_extrapolation: "是否允许外推",
  estimate_count_input: "原始 VO 帧数",
  reference_count_input: "原始 Reference 帧数",
  matched_count: "成功插值/匹配帧数",
  matches: "匹配数量",
  dropped_count: "丢弃帧数",
  coverage_estimate_ratio: "VO 插值覆盖率",
  dropped_before_reference_range: "早于 Reference 范围丢弃数",
  dropped_after_reference_range: "晚于 Reference 范围丢弃数",
  dropped_gt_gap_too_large: "GT 空洞过大丢弃数",
  dropped_invalid_timestamp: "无效时间戳丢弃数",
  max_used_gt_gap_s: "最大使用 GT 间隔",
  mean_used_gt_gap_s: "平均使用 GT 间隔",
  median_used_gt_gap_s: "中位使用 GT 间隔",
  p95_used_gt_gap_s: "P95 使用 GT 间隔",
  max_abs_time_offset_to_left_sample_s: "距左侧 GT 样本最大时间差",
  max_abs_time_offset_to_right_sample_s: "距右侧 GT 样本最大时间差",
  mean_time_diff_s: "平均时间差",
  max_time_diff_s: "最大时间差阈值",
  max_interpolation_gap_s: "最大插值间隔",
  max_interpolation_gap_s_allowed: "允许的最大插值间隔",
  mean_interpolation_gap_s: "平均插值间隔",
  dropped_est_outside_gt_range: "超出 GT 范围的 VO 帧数",
  dropped_est_large_gt_gap: "GT 插值间隔过大丢弃帧数",
  break_count: "断点数量",
  segment_count: "连续段数量",
  step_threshold_m: "步长断点阈值",
  time_gap_threshold_s: "时间断点阈值",
  start: "起始索引",
  end: "结束索引",
  start_index: "起始索引",
  end_index: "结束索引",
  policy: "评估段策略",
  selected_matches: "纳入评估的匹配数",
  dropped_matches: "未纳入评估的匹配数",
  first_divergence_distance_m: "首次发散路程",
  first_divergence_error_m: "首次发散误差",
  max_error_m: "最大误差",
  final_error_m: "最终误差",
  abs_threshold_m: "绝对误差阈值",
  rel_threshold_percent: "相对误差阈值",
  diverged: "是否发散",
  requested: "请求的姿态修正",
  selected: "实际选择的姿态修正",
  auto: "是否自动选择",
  best_score: "自动选择评分",
  name: "名称",
  format: "格式",
  ground_truth: "Ground truth",
  estimate: "VO 输出",
  alignment: "轨迹对齐方式",
  base_mode: "基础对齐方式",
  association_mode: "时间同步方式",
  allow_extrapolation: "是否允许外推",
  interpolate_rotation: "是否插值姿态",
  interpolation_position_method: "位置插值方法",
  interpolation_rotation_method: "姿态插值方法",
  orientation_correction: "姿态修正方式",
  time_offset_s: "时间偏移",
  rpe_delta_frames: "RPE 间隔帧数（兼容字段）",
  rpe_delta_value: "RPE 统计间隔数值",
  rpe_delta_unit: "RPE 统计单位",
  rpe_distance_tolerance_ratio: "RPE 距离容差比例",
  scale_delta_value: "尺度图间隔数值",
  scale_delta_unit: "尺度图统计单位",
  scale_distance_tolerance_ratio: "尺度图距离容差比例",
  segment_lengths_m: "子轨迹长度列表",
  max_segments_per_length: "每个长度最大采样数",
  segment_step_frames: "子轨迹采样步长",
  max_segment_length_diff_ratio: "子轨迹长度容差比例",
  continuous_segment_policy: "连续段处理策略",
  discontinuity_step_m: "断点步长阈值",
  discontinuity_time_gap_s: "断点时间间隔阈值",
  divergence_abs_m: "发散绝对阈值",
  divergence_rel_percent: "发散相对阈值",
  speed_bins_mps: "速度分箱边界",
  all_matches: "全部匹配",
  used_matches: "已使用匹配",
  selected_segment: "选中的评估段",
  segments: "连续段",
};

function metricGroupLabel(groupKey) {
  if (groupKey === "general") {
    return "其他指标";
  }
  return groupKey.split(".").map(metricPathPartLabel).filter(Boolean).join(" / ");
}

function metricPathPartLabel(part) {
  const match = part.match(/^([A-Za-z_]+)\[(\d+)\]$/);
  if (match) {
    const [, root, index] = match;
    const base = METRIC_GROUP_LABELS[root] || METRIC_FIELD_LABELS[root] || root;
    return `${base} 第 ${Number(index) + 1} 项`;
  }
  return METRIC_GROUP_LABELS[part] || METRIC_FIELD_LABELS[part] || part.replaceAll("_", " ");
}

function metricParamLabel(metric, field) {
  if (metric.startsWith("orientation_correction.candidates")) {
    const candidateLabels = {
      mode: "候选修正方式",
      score: "候选综合评分",
      orientation_rmse_deg: "姿态 RMSE",
      yaw_rmse_deg: "Yaw RMSE",
      rpe_translation_rmse_m: "RPE 平移 RMSE",
      rpe_rotation_rmse_deg: "RPE 旋转 RMSE",
    };
    if (candidateLabels[field]) {
      return candidateLabels[field];
    }
  }
  if (metric.startsWith("alignment.segments")) {
    const segmentLabels = {
      mode: "该段对齐方式",
      scale: "该段对齐尺度",
      segment_id: "连续段编号",
      start_match_index: "该段起始匹配索引",
      end_match_index: "该段结束匹配索引",
    };
    if (segmentLabels[field]) {
      return segmentLabels[field];
    }
  }
  const rotationMatch = metric.match(/\.rotation\[(\d+)\]\[(\d+)\]$/);
  if (rotationMatch) {
    return `旋转矩阵 R[${rotationMatch[1]}][${rotationMatch[2]}]`;
  }
  const translationMatch = metric.match(/\.translation\[(\d+)\]$/);
  if (translationMatch) {
    return `平移向量 ${axisLabel(Number(translationMatch[1]))}`;
  }
  const match = field.match(/^([A-Za-z_]+)((?:\[\d+\])+)$/);
  if (match && match[2]) {
    const base = match[1];
    return `${METRIC_FIELD_LABELS[base] || base}${match[2]}`;
  }
  return METRIC_FIELD_LABELS[field] || field.replaceAll("_", " ");
}

function metricIssue(metric, valueText = "") {
  const field = metricFieldBase(metricLeaf(metric));
  if (metric.startsWith("alignment.")) {
    return alignmentMetricIssue(field, metric, valueText);
  }
  if (metric.startsWith("summary.")) {
    return summaryMetricIssue(field);
  }
  if (metric.startsWith("association.")) {
    return associationMetricIssue(field);
  }
  if (metric.startsWith("discontinuities.")) {
    return discontinuityMetricIssue(field);
  }
  if (metric.startsWith("divergence.")) {
    return divergenceMetricIssue(field);
  }
  if (metric.startsWith("orientation_correction.")) {
    return orientationCorrectionMetricIssue(field, metric, valueText);
  }
  if (metric.startsWith("config.")) {
    return configMetricIssue(field);
  }
  if (metric.startsWith("inputs.")) {
    return "记录本次评估使用的输入文件信息，主要用于复现实验和排查是否传错数据。";
  }
  const statIssue = statisticMetricIssue(metric, field);
  if (statIssue) {
    return statIssue;
  }
  if (metric.includes("segment_errors")) {
    const specific = segmentMetricIssue(field);
    if (specific) {
      return specific;
    }
  }
  if (metric.includes("speed_bins")) {
    const specific = speedBinMetricIssue(field);
    if (specific) {
      return specific;
    }
  }

  if (metric.includes("speed_bins")) {
    if (metric.includes("translation_error_percent")) {
      return "反映某个速度区间内的平移漂移；高速区间偏高通常要检查运动模糊、滚快门、特征跟踪和曝光，低速区间偏高则要看初始化、弱纹理或悬停退化。";
    }
    return "反映不同飞行速度下的误差分布，用来判断 VO 是否在特定速度范围内明显退化。";
  }
  if (metric.includes("segment_errors")) {
    if (metric.includes("scale_drift_percent")) {
      return "反映固定航程子轨迹内尺度是否稳定；无尺度 VO 或高度/IMU 融合不足时这里会偏高。";
    }
    if (metric.includes("rotation_error_deg_per_m")) {
      return "反映单位距离的姿态累计漂移；偏高时要检查外参、欧拉角约定、IMU/视觉姿态融合和后端约束。";
    }
    return "反映固定距离内的累计漂移；短距离偏高说明前端跟踪不稳，长距离偏高说明尺度、后端约束或闭环能力不足。";
  }
  if (metric.includes("rpe_frame_delta")) {
    return "反映相邻或固定间隔帧之间的相对运动误差；偏高通常说明帧间 VO 估计不稳定。";
  }
  if (metric.includes("ate_position_m")) {
    return "反映对齐后整条轨迹的绝对位置误差；偏高要优先检查时间同步、坐标系、尺度和局部漂移。";
  }
  if (metric.includes("ate_horizontal_m")) {
    return "反映 XY 平面误差；偏高会直接影响航线跟踪和水平定位。";
  }
  if (metric.includes("ate_vertical_m")) {
    return "反映高度方向误差；偏高要检查高度计、Z 轴方向、NED/ENU 转换和尺度。";
  }
  if (metric.includes("ate_orientation_deg") || metric.includes("ate_yaw_deg")) {
    return "反映姿态或航向误差；偏高要检查 yaw/pitch/roll 顺序、角度/弧度、坐标系和 camera-to-body 外参。";
  }
  if (metric.startsWith("association")) {
    return "反映 GT 与 VO 时间戳是否正确对齐；匹配率低或时间差大时，后续误差指标可信度会下降。";
  }
  if (metric.startsWith("alignment")) {
    return "反映对齐变换和尺度；尺度变化大说明 VO 尺度不稳定或不同连续段不在同一坐标系。";
  }
  if (metric.startsWith("discontinuities")) {
    return "反映 VO 是否发生重置、丢跟踪或大跳变；长航程无人机需要重点关注连续性。";
  }
  if (metric.startsWith("divergence")) {
    return "反映误差是否超过设定阈值；触发后说明轨迹在某处已明显不可用或阈值设置过严。";
  }
  if (metric.startsWith("runtime")) {
    return "反映算法运行效率；耗时、FPS、CPU 或内存异常会影响实时部署。";
  }
  if (metric.startsWith("summary")) {
    if (metric.includes("coverage") || metric.includes("matched")) {
      return "反映本次评估覆盖了多少有效数据；覆盖不足时不能代表整段飞行。";
    }
    if (metric.includes("endpoint")) {
      return "反映终点累计漂移；长航程任务中比单帧误差更能说明最终定位偏差。";
    }
    if (metric.includes("raw_path_scale_ratio")) {
      return "反映 VO 原始尺度与 GT 的比例；明显不为 1 时说明数据可能是无尺度或尺度不一致。";
    }
    return "反映本次评估的总体数据规模、路程和时长，是解释其他误差指标的上下文。";
  }
  if (metric.startsWith("orientation_correction")) {
    return "反映系统为 VO 姿态选择的坐标系/外参修正；自动选择非 none 时说明 VO 与 GT 的姿态约定不一致。";
  }
  if (metric.startsWith("inputs") || metric.startsWith("config")) {
    return "这是评估输入和配置，不直接代表好坏，但会影响所有误差指标的计算方式。";
  }
  return "用于辅助定位误差来源；需要结合轨迹图、ATE/RPE 和子轨迹误差一起判断。";
}

function metricLeaf(metric) {
  const index = metric.lastIndexOf(".");
  return index >= 0 ? metric.slice(index + 1) : metric;
}

function metricFieldBase(field) {
  return field.replace(/(?:\[\d+\])+$/, "");
}

function alignmentMetricIssue(field, metric = "", valueText = "") {
  if (metric === "alignment") {
    return "轨迹对齐总览：判断 VO 坐标系如何变到 GT 坐标系。主要看 mode/base_mode、scale、rotation 和 translation；scale 说明尺度，rotation 说明轴方向，translation 说明整体平移。";
  }
  if (/^alignment\.segments\[\d+\]$/.test(metric)) {
    return "单个连续段的对齐结果：用于判断这一段 VO 是否和 GT 在同一尺度、方向和原点附近。不同段之间 scale/rotation 差异大，说明 VO 重置后坐标系或尺度可能变了。";
  }
  const rotationMatch = metric.match(/\.rotation\[(\d+)\]\[(\d+)\]$/);
  if (rotationMatch) {
    return rotationMatrixElementIssue(Number(rotationMatch[1]), Number(rotationMatch[2]), valueText);
  }
  const translationMatch = metric.match(/\.translation\[(\d+)\]$/);
  if (translationMatch) {
    return translationElementIssue(Number(translationMatch[1]));
  }
  const issues = {
    mode: "说明最终采用的是全局对齐还是按连续段分别对齐；如果是 per_segment，跨段结果不能当作一条完全连续轨迹解释。",
    base_mode: "说明基础对齐模型；Sim3 会同时估计旋转、平移和尺度，适合无尺度 VO，但会掩盖原始尺度误差。",
    scale: "VO 坐标乘到 GT 坐标上的平均尺度因子；明显不接近 1 时，说明原始 VO 尺度与真实尺度不一致。",
    scale_min: "所有连续段里最小的对齐尺度；如果它和最大尺度差距大，说明某些航段的 VO 原始尺度明显偏大或尺度发生漂移。",
    scale_max: "所有连续段里最大的对齐尺度；如果它和最小尺度差距大，说明某些航段的 VO 原始尺度明显偏小或尺度发生漂移。",
    scale_std: "不同连续段对齐尺度的离散程度；数值越大，说明 VO 尺度稳定性越差。",
    segment_count: "参与对齐统计的连续段数量；数量大于 1 时通常意味着存在断点、重置或分段评估。",
    segment_id: "该对齐结果属于第几个连续段；它本身不判断好坏，用来把这一段的 scale、rotation、translation 和轨迹断点对应起来。",
    start_match_index: "该连续段在匹配序列中的起点；数值越大表示它越靠后，不代表误差大小，用于定位是哪段飞行在使用这组对齐参数。",
    end_match_index: "该连续段在匹配序列中的终点；和 start_match_index 一起确定该段范围，不代表好坏，用于复查断点前后对应的航段。",
  };
  return issues[field] || "该参数描述轨迹对齐变换的一个组成部分，用来判断坐标系、尺度和连续段处理是否合理。";
}

function rotationMatrixElementIssue(row, col, valueText) {
  const rowAxis = axisName(row);
  const colAxis = axisName(col);
  const value = Number(valueText);
  const isDiagonal = row === col;
  const valueHint = Number.isFinite(value) ? `当前值 ${valueText}。` : "";
  if (isDiagonal) {
    return `${valueHint}这是对齐旋转矩阵的对角项，表示 VO 的 ${colAxis} 轴投到 GT 的 ${rowAxis} 轴上的程度。接近 +1 说明两轴方向基本一致；接近 -1 说明该轴方向相反；接近 0 说明该轴主要被旋到其他 GT 轴上。单个元素不能单独判断好坏，要和同一行/列的非对角项一起看。`;
  }
  return `${valueHint}这是对齐旋转矩阵的非对角项，表示 VO 的 ${colAxis} 轴混入 GT 的 ${rowAxis} 轴的程度。接近 0 说明这两个轴基本不混合；绝对值变大说明坐标轴之间存在旋转/轴交换；接近 +1 或 -1 说明某个 VO 轴几乎被映射成另一个 GT 轴，常见于 ENU/NED、相机系/机体系或轴方向约定不同。`;
}

function translationElementIssue(index) {
  const axis = axisName(index);
  return `这是对齐平移向量在 GT ${axis} 方向上的偏移量，表示完成旋转和尺度后还需要平移多少米才能贴到 GT。绝对值大说明两条轨迹原点差得远，或首帧/坐标原点定义不同；绝对值小只说明原点接近，不代表后续漂移一定小。`;
}

function axisName(index) {
  return ["X", "Y", "Z"][index] || `axis${index}`;
}

function axisLabel(index) {
  return ["t_x", "t_y", "t_z"][index] || `t_${index}`;
}

function summaryMetricIssue(field) {
  const issues = {
    gt_path_length_m: "GT 在本次有效评估窗口内的真实路程；后续百分比误差都要以这个路程作为背景理解。",
    est_path_length_raw_m: "VO 原始输出轨迹长度；与 GT 路程差很多时，通常说明 VO 是无尺度或尺度漂移明显。",
    est_path_length_aligned_m: "VO 对齐后的轨迹长度；用于检查对齐后路程是否仍明显偏离 GT。",
    duration_s: "本次评估覆盖的飞行时间；时间过短时不能代表长航程表现。",
    matched_poses: "最终纳入评估的位姿数量；数量少会降低 ATE、RPE、p95 等统计可信度。",
    original_matched_poses: "时间同步后原始可匹配位姿数量；和 matched_poses 差距大说明后续断点策略丢掉了不少数据。",
    gt_poses: "GT 文件中可解析出的位姿数量；用于确认 GT 数据量是否足够。",
    est_poses: "VO 文件中可解析出的位姿数量；用于确认 VO 输出是否完整。",
    coverage_ratio: "整体覆盖比例；覆盖低说明本次评估只代表局部飞行段。",
    gt_pose_coverage_ratio: "GT 位姿被评估覆盖的比例；过低时要检查 VO 是否只覆盖 GT 的一小段。",
    gt_time_coverage_ratio: "GT 时间跨度被 VO 覆盖的比例；过低时说明 VO 与 GT 时间范围不一致。",
    est_pose_coverage_ratio: "VO 位姿被成功匹配并纳入评估的比例；过低时优先检查时间戳单位、时间偏移和插值阈值。",
    endpoint_error_m: "轨迹终点的累计位置误差；长航程任务里它直接反映最终落点/定位偏差。",
    endpoint_error_percent_of_path: "终点误差占总路程比例；便于不同航程之间比较终点漂移。",
    raw_path_scale_ratio_est_over_gt: "VO 原始路程与 GT 路程的比例；明显不为 1 时说明原始输出没有真实尺度或尺度不稳定。",
  };
  return issues[field] || "该总体参数提供评估数据规模、覆盖范围或全局漂移背景，用来解释后续误差指标。";
}

function associationMetricIssue(field) {
  const issues = {
    method: "实际使用的时间同步算法；决定 GT/VO 如何被放到同一时间轴。",
    mode: "用户选择的时间同步模式；选错会导致轨迹错位，从而让所有误差变大。",
    target: "插值或匹配使用的目标时间轴；estimate_timestamps 表示 reference 被插值到 VO 输出时刻。",
    interpolated: "是否真正生成插值后的 reference pose。true 表示不是最近邻匹配，而是 linear position + SLERP rotation。",
    position_method: "reference position 的插值方法；linear 表示按左右 GT 位姿和时间比例做线性插值。",
    rotation_method: "reference rotation 的插值方法；slerp 表示四元数球面插值，skipped 表示没有 reference 姿态或被配置关闭。",
    allow_extrapolation: "是否允许 VO 时间戳落在 reference 范围外时外推；默认 false，避免把无真值区间硬算进评估。",
    estimate_count_input: "VO 文件原始输出帧数；用于和 matched_count 比较，看有多少 VO 输出真正参与评估。",
    reference_count_input: "reference/GT 文件原始位姿数；用于判断真值采样是否足够密。",
    matched_count: "成功插值或匹配后进入评估的 VO 帧数；数量少会降低 ATE/RPE/RE 统计可信度。",
    matches: "成功匹配的时间戳数量；数量越少，统计结果越不稳定。",
    dropped_count: "未进入评估的 VO 帧总数；插值模式下主要来自超出 reference 时间范围、GT 空洞过大或时间戳无效。",
    coverage_estimate_ratio: "VO 插值覆盖率，等于 matched_count / estimate_count_input；低于 80% 时优先检查时间戳单位、范围、offset 和插值 gap 阈值。",
    dropped_before_reference_range: "VO 时间戳加 time_offset_s 后早于 reference 第一帧的数量；默认不外推，所以这些帧会被丢弃。",
    dropped_after_reference_range: "VO 时间戳加 time_offset_s 后晚于 reference 最后一帧的数量；默认不外推，所以这些帧会被丢弃。",
    dropped_gt_gap_too_large: "目标 VO 时刻左右相邻 reference 样本间隔超过 max_interpolation_gap_s 的数量；非零说明 reference 中存在空洞或阈值过严。",
    dropped_invalid_timestamp: "VO 时间戳不是有效数字或无法找到有效插值 bracket 的数量；非零时需要先清洗时间戳。",
    max_used_gt_gap_s: "成功插值样本里使用的最大左右 reference 时间间隔；越大越可能把真实运动细节抹平。",
    mean_used_gt_gap_s: "成功插值样本里使用的平均左右 reference 时间间隔；越小通常插值越可靠。",
    median_used_gt_gap_s: "成功插值样本里使用的中位左右 reference 时间间隔；比平均值更不受少量大 gap 影响。",
    p95_used_gt_gap_s: "成功插值样本里 95% 的左右 reference 时间间隔不超过该值；适合判断常态插值质量。",
    max_abs_time_offset_to_left_sample_s: "目标 VO 时刻到左侧 reference 样本的最大时间差；大值说明局部 reference 采样偏稀。",
    max_abs_time_offset_to_right_sample_s: "目标 VO 时刻到右侧 reference 样本的最大时间差；大值说明局部 reference 采样偏稀。",
    time_offset_s: "应用到 VO 或 GT 的时间偏移；如果设置不对，会出现整体轨迹相位错开。",
    max_time_diff_s: "最近邻匹配允许的最大时间差；阈值过大可能误匹配，过小可能丢匹配。",
    mean_time_diff_s: "匹配后的平均时间差；越大越可能引入运动中的位置误差。",
    max_interpolation_gap_s_allowed: "允许 GT 插值跨越的最大时间间隔；过大可能跨过 GT 空洞，过小可能丢掉 VO 帧。",
    max_interpolation_gap_s: "实际使用到的最大 GT 插值间隔；接近阈值时要检查 GT 是否有采样空洞。",
    mean_interpolation_gap_s: "GT 插值使用的平均邻近间隔；越小通常时间同步越可靠。",
    dropped_est_outside_gt_range: "因 VO 时间戳超出 GT 时间范围而丢弃的帧数；非零时说明两份数据起止时间不一致。",
    dropped_est_large_gt_gap: "因 GT 邻近采样间隔过大而丢弃的 VO 帧数；非零时说明 GT 中间可能有时间空洞。",
    gt_time_coverage_ratio: "VO 覆盖到的 GT 时间比例；低值说明评估不是完整 GT 飞行。",
    est_pose_coverage_ratio: "VO 输出中被成功评估的比例；低值说明 VO 有大量帧无法和 GT 对齐。",
  };
  return issues[field] || "该参数用于判断 GT 和 VO 时间戳是否对齐；时间同步不好会污染所有误差指标。";
}

function statisticMetricIssue(metric, field) {
  const context = metricContext(metric);
  const issues = {
    count: `${context}的样本数量；样本太少时，均值、p95 和 p99 都不稳定。`,
    rmse: `${context}的均方根值；会放大大误差，适合发现局部严重漂移或离群问题。`,
    mean: `${context}的平均水平；用于看整体常态表现，但可能被极端值影响。`,
    median: `${context}的中位数；代表更典型的表现，和 mean 差很多时说明误差分布偏斜或有离群点。`,
    std: `${context}的波动程度；越大说明不同片段/速度/帧之间表现越不稳定。`,
    min: `${context}的最好情况；只能说明最佳片段表现，不能代表整体质量。`,
    max: `${context}的最坏情况；用于定位最严重漂移、跟踪失败或异常航段。`,
    p95: `${context}的 95 分位值；代表大多数情况下的上界，比 max 更适合做工程容差判断。`,
    p99: `${context}的 99 分位值；用于观察极端但非单点的尾部风险。`,
  };
  return issues[field] || null;
}

function metricContext(metric) {
  if (metric.includes("translation_error_percent")) return "平移误差百分比";
  if (metric.includes("translation_error_m") || metric.includes("translation_m")) return "平移误差";
  if (metric.includes("rotation_error_deg_per_m")) return "单位距离旋转误差";
  if (metric.includes("rotation_deg")) return "旋转误差";
  if (metric.includes("scale_drift_percent")) return "尺度漂移百分比";
  if (metric.includes("scale_ratio_est_over_gt")) return "VO/GT 尺度比";
  if (metric.includes("ate_position_m")) return "ATE 位置误差";
  if (metric.includes("ate_horizontal_m")) return "水平 ATE";
  if (metric.includes("ate_vertical_m")) return "垂直 ATE";
  if (metric.includes("ate_orientation_deg")) return "姿态 ATE";
  if (metric.includes("ate_yaw_deg")) return "Yaw 误差";
  if (metric.includes("speed_bins")) return "该速度区间误差";
  if (metric.includes("segment_errors")) return "该子轨迹误差";
  return "该指标";
}

function segmentMetricIssue(field) {
  const issues = {
    length_m: "当前子轨迹统计对应的航程长度；短段主要看局部跟踪稳定性，长段主要看累计漂移。",
    translation_error_percent: "该长度子轨迹的平移误差占路程比例；越高说明固定航程内累计漂移越明显。",
    translation_error_m: "该长度子轨迹的绝对平移误差；用于判断实际米级偏差是否超过任务容差。",
    rotation_error_deg_per_m: "单位距离姿态累计误差；偏高时要检查外参、姿态约定和后端约束。",
    scale_ratio_est_over_gt: "子轨迹内 VO 路程与 GT 路程的比例；偏离 1 说明该段尺度不准。",
    scale_drift_percent: "子轨迹内尺度漂移百分比；偏高说明尺度随航段变化，常见于单目无尺度或高度/IMU 融合不足。",
  };
  return issues[field] || null;
}

function speedBinMetricIssue(field) {
  const issues = {
    speed_bin_mps: "当前误差统计对应的飞行速度区间；用于定位 VO 在低速、巡航或高速时是否退化。",
    count: "该速度区间内参与统计的样本数；样本少时不能据此判断该速度段好坏。",
    translation_error_percent: "该速度区间内的平移误差比例；高速偏高常和运动模糊/曝光/滚快门有关，低速偏高常和弱纹理或悬停退化有关。",
    rotation_error_deg_per_m: "该速度区间内单位距离姿态误差；偏高说明该速度下姿态估计或外参约定更不稳定。",
  };
  return issues[field] || null;
}

function discontinuityMetricIssue(field) {
  const issues = {
    step_threshold_m: "用于判断相邻匹配之间是否出现位置大跳变的距离阈值。",
    time_gap_threshold_s: "用于判断相邻匹配之间是否出现时间断裂的阈值。",
    break_count: "检测到的断点数量；非零通常表示 VO 重置、丢跟踪或时间数据不连续。",
    segment_count: "由断点切出的连续段数量；数量越多，越不适合把结果当作单条连续长航程轨迹。",
    start: "连续段在匹配序列中的起点索引，用于定位断点前后的数据范围。",
    end: "连续段在匹配序列中的终点索引，用于定位断点前后的数据范围。",
    start_index: "被选中评估段的起点索引；用于复查具体从哪一帧开始纳入统计。",
    end_index: "被选中评估段的终点索引；用于复查具体到哪一帧结束统计。",
    count: "该连续段包含的匹配位姿数量；段太短时误差统计代表性不足。",
    policy: "断点处理策略；决定是保留所有 VO 时间戳、逐段评估，还是只评估最长连续段。",
    selected_matches: "最终纳入评估的匹配数量；和原始匹配差距大时说明断点策略丢弃了不少数据。",
    dropped_matches: "因为断点策略未纳入评估的匹配数量；过高说明 VO 连续性问题明显。",
  };
  return issues[field] || "该参数用于定位 VO 是否有重置、丢跟踪或大跳变，并判断长航程连续性。";
}

function divergenceMetricIssue(field) {
  const issues = {
    diverged: "是否触发发散判定；True 表示误差超过了设定的绝对或相对阈值。",
    abs_threshold_m: "发散检测使用的绝对误差阈值；超过该米级误差会被认为不可接受。",
    rel_threshold_percent: "发散检测使用的相对路程阈值；用于长航程下按路程比例判断误差是否过大。",
    first_divergence_distance_m: "第一次触发发散时已经飞过的路程；用于定位问题开始出现的位置。",
    first_divergence_error_m: "第一次触发发散时的误差大小；用于判断触发是否严重。",
    max_error_m: "整段评估中的最大位置误差；用于定位最坏时刻。",
    final_error_m: "末尾位置误差；用于判断飞完整段后累计漂移是否仍可接受。",
  };
  return issues[field] || "该参数用于判断误差是否超过任务容差，并定位首次失效位置。";
}

function orientationCorrectionMetricIssue(field, metric = "", valueText = "") {
  if (metric === "orientation_correction") {
    return "姿态修正总览：判断 VO 输出姿态和 GT 姿态是否使用同一坐标系、同一旋转方向和同一 camera/body 外参约定。重点看 selected、best_score 以及 candidates 里各候选的 RMSE。";
  }
  if (/^orientation_correction\.candidates\[\d+\]$/.test(metric)) {
    return "一个自动姿态修正候选的试算结果：系统把这个候选应用到 VO 姿态后，重新计算姿态误差和 RPE。候选之间主要比较 score，越小越可能是正确坐标系/外参；但最终还要看 selected 是否选择了它。";
  }
  const candidateMatch = metric.match(/^orientation_correction\.candidates\[(\d+)\]\.(.+)$/);
  if (candidateMatch) {
    return orientationCandidateMetricIssue(candidateMatch[2], Number(candidateMatch[1]), valueText);
  }
  const issues = {
    requested: "用户请求的姿态修正方式；auto 表示系统会比较多个候选，none 表示直接使用原始姿态，ignore 表示不计算姿态类指标。选错会影响姿态 ATE、旋转 RPE 和带姿态的子轨迹旋转误差。",
    selected: "系统最终实际采用的姿态修正。若 selected 不是 none，说明原始 VO 和 GT 的姿态约定很可能不同；如果 selected 是 inverse，要检查旋转矩阵方向；如果是 ENU/NED 或 Rx/Ry/Rz，要检查坐标轴和 camera-to-body 外参。",
    auto: "是否启用自动候选选择。true 时系统会试多个姿态修正候选；false 时只按用户指定方式计算。自动选择只能辅助排查，不能替代你在 VO 输出端明确坐标系/外参定义。",
    available: "GT 和 VO 是否都有姿态数据。false 时姿态修正无法真正生效，姿态 ATE、yaw 误差、旋转 RPE 等指标会缺失或退化。",
    uses_rotations: "本次评估是否真的使用旋转矩阵。false 表示只评估位置，相当于不判断 yaw/pitch/roll、外参和旋转 RPE。",
    best_score: "自动姿态修正的最佳候选综合分，越小越好。它不是物理单位，而是 orientation RMSE、yaw RMSE、RPE 平移和 RPE 旋转的加权和；如果 best_score 仍很大，说明即使最优候选也不能很好解释姿态。",
    score_metric: "说明 score 由哪些误差项组成。它不是结果好坏本身，而是自动选择候选时的评分公式；各候选 score 只能在同一次评估内相互比较。",
  };
  return issues[field] || "该参数描述 VO 姿态坐标系或外参修正选择，用于排查 yaw/pitch/roll、ENU/NED 和 camera/body 约定。";
}

function orientationCandidateMetricIssue(field, candidateIndex, valueText) {
  const prefix = `第 ${candidateIndex + 1} 个候选。`;
  const value = Number(valueText);
  const valueHint = Number.isFinite(value) ? `当前值 ${valueText}。` : "";
  const issues = {
    mode: `${prefix}这是这个候选实际尝试的修正方式，不是误差大小。none 表示不修正，inverse 表示取 R^T，rx/ry/rz180 表示补 180 度外参，enu_ned 表示 ENU/NED 坐标转换。若这个候选最后被 selected 选中，说明它比其他候选更能解释 GT/VO 姿态差异。`,
    score: `${prefix}${valueHint}综合评分越小越好，只用于候选之间排序；小分说明这个修正同时让姿态 RMSE、yaw RMSE、RPE 平移和 RPE 旋转更低。分数大说明该候选不能很好解释坐标系/外参问题；如果所有候选都大，可能不是简单 ENU/NED 或 180 度外参能解决。`,
    orientation_rmse_deg: `${prefix}${valueHint}判断整体三维姿态差，单位度，越小越好。接近 0 表示 roll/pitch/yaw 整体都贴近 GT；大于 5-10 deg 通常要检查角度/弧度、欧拉角顺序、旋转取逆、camera-to-body 外参或 ENU/NED 约定。`,
    yaw_rmse_deg: `${prefix}${valueHint}判断航向角误差，单位度，越小越好。小但 orientation_rmse 大，说明 yaw 可能对了但 roll/pitch 或外参仍不对；大则说明航向方向、ENU/NED、NED yaw 符号或 yaw/pitch/roll 顺序需要重点检查。`,
    rpe_translation_rmse_m: `${prefix}${valueHint}判断应用该姿态候选后，固定帧间隔的相对平移是否一致，单位米，越小越好。它高说明该候选虽然可能改善角度，但相对运动仍不稳定或对齐旋转不合理；要和 RPE 旋转、ATE 一起看。`,
    rpe_rotation_rmse_deg: `${prefix}${valueHint}判断应用该姿态候选后，相邻/固定间隔相对旋转误差，单位度，越小越好。小表示帧间姿态变化和 GT 接近；大说明这个候选下姿态变化方向仍不对，常见于旋转矩阵方向、轴顺序或外参错误。`,
  };
  return issues[field] || `${prefix}这是自动姿态候选的一个细分结果；数值类通常越小越好，主要用于和其他候选对比，不应单独脱离 selected 和 score 判断。`;
}

function configMetricIssue(field) {
  const issues = {
    alignment: "控制使用 SE3、Sim3、首帧或不对齐；会直接影响所有位置误差解释。",
    orientation_correction: "控制是否修正 VO 姿态坐标系/外参；会影响姿态 ATE、旋转 RPE 和带姿态的子轨迹指标。",
    association_mode: "控制 GT 与 VO 如何按时间匹配；选错会让轨迹错位。",
    max_time_diff_s: "最近邻匹配允许的最大时间差；过大可能错配，过小可能丢帧。",
    max_interpolation_gap_s: "GT 插值允许跨越的最大采样间隔；用于避免跨 GT 空洞插值。",
    allow_extrapolation: "是否允许 VO 时间戳超出 reference 范围时外推；默认 false，避免无真值区间污染评估。",
    interpolate_rotation: "是否对 reference 姿态做 SLERP 插值；没有姿态时会自动降级为只插位置。",
    interpolation_position_method: "reference 位置插值方法；当前支持 linear。",
    interpolation_rotation_method: "reference 姿态插值方法；当前支持 slerp。",
    time_offset_s: "手动时间偏移；用于修正 GT 与 VO 固定延迟。",
    rpe_delta_frames: "RPE 使用的帧间隔兼容字段；新配置优先看 rpe_delta_value 和 rpe_delta_unit。",
    rpe_delta_value: "RPE 统计间隔数值；配合 rpe_delta_unit 使用，单位可以是帧 f 或距离 m。",
    rpe_delta_unit: "RPE 统计单位；frames/f 表示按固定帧数，meters/m 表示按 GT 路程窗口。",
    rpe_distance_tolerance_ratio: "RPE 距离模式的容差比例；例如 0.05 表示 100m 会在 95-105m 候选中选择误差最小的终点。",
    scale_delta_value: "尺度图统计间隔数值；配合 scale_delta_unit 使用，单位可以是帧 f 或距离 m。",
    scale_delta_unit: "尺度图统计单位；frames/f 表示按固定帧数，meters/m 表示按 GT 路程窗口。",
    scale_distance_tolerance_ratio: "尺度图距离模式的容差比例；例如 0.05 表示 100m 会在 95-105m 候选中取 GT 距离最接近 100m 的终点。",
    segment_lengths_m: "长航程子轨迹统计使用的距离列表；决定报告会比较哪些航程长度。",
    max_segments_per_length: "每个子轨迹长度最多抽样数量；限制计算量，过低会降低统计代表性。",
    segment_step_frames: "子轨迹抽样步长；步长越小样本越密，但计算更慢。",
    max_segment_length_diff_ratio: "允许实际子轨迹长度偏离目标长度的比例；过严会导致长距离样本不足。",
    continuous_segment_policy: "断点处理策略；决定跨 VO 重置的数据是否仍纳入同一评估。",
    discontinuity_step_m: "断点检测的位置跳变阈值；过小容易误报，过大可能漏掉重置。",
    discontinuity_time_gap_s: "断点检测的时间间隔阈值；用于发现数据中断或 VO 输出停顿。",
    divergence_abs_m: "发散检测的绝对误差阈值；用于判定米级误差是否不可接受。",
    divergence_rel_percent: "发散检测的相对路程阈值；用于长航程下按比例判断误差。",
    speed_bins_mps: "速度分箱边界；决定速度分箱误差如何分组。",
  };
  return issues[field] || "该配置项会影响评估方式或统计范围，不直接代表算法好坏，但会改变指标解释。";
}

function findSegment(report, length) {
  return (report.segment_errors || []).find((row) => Number(row.length_m) === length);
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

function buildTrajectoryWorkbook(sheets) {
  const orderedNames = [
    "input_gt_tum",
    "input_vo_tum",
    "filtered_vo_tum",
    "interpolated_gt_tum",
    "sim3_gt_tum",
    "sim3_vo_tum",
    "ate_per_frame",
    "rpe_per_frame",
    "scale_per_frame",
  ];
  const entries = orderedNames.map((name) => ({
    name,
    rows: Array.isArray(sheets?.[name]) ? sheets[name] : [],
  }));
  const files = {
    "[Content_Types].xml": workbookContentTypes(entries.length),
    "_rels/.rels": workbookRootRels(),
    "xl/workbook.xml": workbookXml(entries),
    "xl/_rels/workbook.xml.rels": workbookRels(entries.length),
  };
  entries.forEach((entry, index) => {
    files[`xl/worksheets/sheet${index + 1}.xml`] = worksheetXml(entry.rows);
  });
  return zipStore(files);
}

function workbookContentTypes(sheetCount) {
  const sheetOverrides = Array.from({ length: sheetCount }, (_, index) => (
    `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`
  )).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
${sheetOverrides}
</Types>`;
}

function workbookRootRels() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`;
}

function workbookXml(entries) {
  const sheets = entries.map((entry, index) => (
    `<sheet name="${escapeXml(excelSheetName(entry.name))}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`
  )).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>${sheets}</sheets>
</workbook>`;
}

function workbookRels(sheetCount) {
  const rels = Array.from({ length: sheetCount }, (_, index) => (
    `<Relationship Id="rId${index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`
  )).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels}</Relationships>`;
}

function worksheetXml(rows) {
  const columns = workbookColumns(rows);
  const allRows = columns.length ? [Object.fromEntries(columns.map((column) => [column, column])), ...rows] : [];
  const rowXml = allRows.map((row, rowIndex) => {
    const cells = columns.map((column, columnIndex) => cellXml(row[column], rowIndex + 1, columnIndex + 1)).join("");
    return `<row r="${rowIndex + 1}">${cells}</row>`;
  }).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>${rowXml}</sheetData>
</worksheet>`;
}

function workbookColumns(rows) {
  const seen = new Set();
  const columns = [];
  for (const row of rows || []) {
    for (const key of Object.keys(row || {})) {
      if (!seen.has(key)) {
        seen.add(key);
        columns.push(key);
      }
    }
  }
  return columns;
}

function cellXml(value, rowIndex, columnIndex) {
  const ref = `${excelColumnName(columnIndex)}${rowIndex}`;
  if (value === null || value === undefined) {
    return `<c r="${ref}"/>`;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return `<c r="${ref}"><v>${value}</v></c>`;
  }
  if (typeof value === "boolean") {
    return `<c r="${ref}" t="b"><v>${value ? 1 : 0}</v></c>`;
  }
  return `<c r="${ref}" t="inlineStr"><is><t>${escapeXml(String(value))}</t></is></c>`;
}

function excelColumnName(index) {
  let name = "";
  let value = index;
  while (value > 0) {
    value -= 1;
    name = String.fromCharCode(65 + (value % 26)) + name;
    value = Math.floor(value / 26);
  }
  return name;
}

function excelSheetName(name) {
  return String(name || "sheet").replace(/[\[\]:*?/\\]/g, "_").slice(0, 31) || "sheet";
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function zipStore(files) {
  const encoder = new TextEncoder();
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  for (const [name, text] of Object.entries(files)) {
    const nameBytes = encoder.encode(name);
    const data = encoder.encode(text);
    const crc = crc32(data);
    const localHeader = new Uint8Array(30 + nameBytes.length);
    const localView = new DataView(localHeader.buffer);
    localView.setUint32(0, 0x04034b50, true);
    localView.setUint16(4, 20, true);
    localView.setUint16(6, 0, true);
    localView.setUint16(8, 0, true);
    localView.setUint16(10, 0, true);
    localView.setUint16(12, 0, true);
    localView.setUint32(14, crc, true);
    localView.setUint32(18, data.length, true);
    localView.setUint32(22, data.length, true);
    localView.setUint16(26, nameBytes.length, true);
    localView.setUint16(28, 0, true);
    localHeader.set(nameBytes, 30);
    localParts.push(localHeader, data);

    const centralHeader = new Uint8Array(46 + nameBytes.length);
    const centralView = new DataView(centralHeader.buffer);
    centralView.setUint32(0, 0x02014b50, true);
    centralView.setUint16(4, 20, true);
    centralView.setUint16(6, 20, true);
    centralView.setUint16(8, 0, true);
    centralView.setUint16(10, 0, true);
    centralView.setUint16(12, 0, true);
    centralView.setUint16(14, 0, true);
    centralView.setUint32(16, crc, true);
    centralView.setUint32(20, data.length, true);
    centralView.setUint32(24, data.length, true);
    centralView.setUint16(28, nameBytes.length, true);
    centralView.setUint16(30, 0, true);
    centralView.setUint16(32, 0, true);
    centralView.setUint16(34, 0, true);
    centralView.setUint16(36, 0, true);
    centralView.setUint32(38, 0, true);
    centralView.setUint32(42, offset, true);
    centralHeader.set(nameBytes, 46);
    centralParts.push(centralHeader);
    offset += localHeader.length + data.length;
  }
  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(4, 0, true);
  endView.setUint16(6, 0, true);
  endView.setUint16(8, centralParts.length, true);
  endView.setUint16(10, centralParts.length, true);
  endView.setUint32(12, centralSize, true);
  endView.setUint32(16, offset, true);
  endView.setUint16(20, 0, true);
  return concatBytes([...localParts, ...centralParts, end]);
}

function concatBytes(parts) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function downloadText(filename, text, mime) {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadBytes(filename, bytes, mime) {
  const blob = new Blob([bytes], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
