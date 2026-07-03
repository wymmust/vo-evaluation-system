const state = {
  worker: null,
  workerReady: false,
  workerRequestId: 0,
  workerRequests: new Map(),
  report: null,
  loadingStep: "",
  reportSource: "worker",
  chartRenderToken: 0,
  activePointSelectionChartId: null,
  focusedPointSelectionId: null,
  pointSelectionSequence: 0,
  pointSelections: [],
};

const PYODIDE_INDEX_URL = "./vendor/pyodide/v0.26.4/full/";
const PLOTLY_SCRIPT_URL = "./vendor/plotly/plotly-2.35.2.min.js";
const APP_ASSET_VERSION = "20260701-split-evaluator";

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
  dataDirPath: document.getElementById("dataDirPath"),
  logDirPath: document.getElementById("logDirPath"),
  dataDirButton: document.getElementById("dataDirButton"),
  logDirButton: document.getElementById("logDirButton"),
  dataDirStatus: document.getElementById("dataDirStatus"),
  logDirStatus: document.getElementById("logDirStatus"),
  vlocChartDirectorySection: document.getElementById("vlocChartDirectorySection"),
  vlocChartList: document.getElementById("vlocChartList"),
  vlocChartSelectAll: document.getElementById("vlocChartSelectAll"),
  vlocChartClear: document.getElementById("vlocChartClear"),
  voChartDirectorySection: document.getElementById("voChartDirectorySection"),
  voChartList: document.getElementById("voChartList"),
  voChartSelectAll: document.getElementById("voChartSelectAll"),
  voChartClear: document.getElementById("voChartClear"),
  pointSelectionOutputSection: document.getElementById("pointSelectionOutputSection"),
  pointSelectionOutput: document.getElementById("pointSelectionOutput"),
  clearAllPointSelections: document.getElementById("clearAllPointSelections"),
  downloadJson: document.getElementById("downloadJson"),
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
  "voStatus",
  "positionCompareComposite",
  "attitudeCompareComposite",
  "positionErrorComposite",
  "attitudeErrorComposite",
  "rpeTranslationTime",
  "rpeRotationTime",
  "scaleFrameTime",
];

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

const VO_CHART_OPTIONS = [
  { id: "trajectory3d", label: "3D 轨迹" },
  { id: "errorDistance", label: "ATE 绝对位姿误差" },
  { id: "navStatusModes", label: "导航状态信息" },
  { id: "navVelocity", label: "导航速度信息" },
  { id: "navResetCounts", label: "导航 reset 计数" },
  { id: "voStatus", label: "VO 状态信息" },
  { id: "positionCompareComposite", label: "位置随时间变化" },
  { id: "attitudeCompareComposite", label: "姿态随时间变化" },
  { id: "positionErrorComposite", label: "位置误差随时间变化" },
  { id: "attitudeErrorComposite", label: "姿态误差随时间变化" },
  { id: "rpeTranslationTime", label: "RPE 平移误差" },
  { id: "rpeRotationTime", label: "RPE 旋转误差" },
  { id: "scaleFrameTime", label: "局部 Sim3 尺度" },
];

const VLOC_VISIBLE_CHART_IDS = VLOC_CHART_OPTIONS.map((option) => option.id);
const VO_VISIBLE_CHART_IDS = VO_CHART_OPTIONS.map((option) => option.id);
const PICKABLE_VLOC_CHART_IDS = VLOC_VISIBLE_CHART_IDS.filter((id) => id !== "trajectory3d");
const PICKABLE_VO_CHART_IDS = VO_VISIBLE_CHART_IDS.filter((id) => id !== "trajectory3d");
const POINT_SELECTION_COLORS = [
  "#000000",
  "#ff00ff",
  "#ffd700",
  "#00ffff",
  "#ff1493",
  "#7fff00",
  "#8b4513",
  "#ff69b4",
  "#4b0082",
  "#00ff7f",
];

state.vlocSelectedChartIds = new Set(VLOC_VISIBLE_CHART_IDS);
state.voSelectedChartIds = new Set(VO_VISIBLE_CHART_IDS);

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
  els.downloadConfigJson.addEventListener("click", () => downloadText("vo_evaluation_config.json", JSON.stringify(state.report?.config || {}, null, 2), "application/json"));
  els.downloadTrajectoryExcel.addEventListener("click", downloadTrajectoryExcel);
  els.downloadHtml.addEventListener("click", downloadHtmlReport);
  updateEntryModeUi();
  renderVlocChartDirectory();
  renderVoChartDirectory();
  updateDirectoryStatus("data");
  updateDirectoryStatus("log");
}

async function initPyodide() {
  if (window.location.protocol === "file:") {
    throw new Error("local_file_protocol");
  }
  state.loadingStep = "worker";
  els.status.textContent = "加载后台运行环境...";
  state.worker = new Worker(`./worker.js?v=${APP_ASSET_VERSION}`);
  state.worker.addEventListener("message", handleWorkerMessage);
  state.worker.addEventListener("error", (event) => {
    rejectPendingWorkerRequests(event.message || "worker_error");
  });
  state.loadingStep = "packages";
  els.status.textContent = "后台加载 Pyodide/numpy/pandas...";
  await workerRequest("init", { pyodideIndexUrl: PYODIDE_INDEX_URL });
  state.workerReady = true;
}

function handleWorkerMessage(event) {
  const { id, ok, result, error } = event.data || {};
  const request = state.workerRequests.get(id);
  if (!request) {
    return;
  }
  state.workerRequests.delete(id);
  if (ok) {
    request.resolve(result);
  } else {
    request.reject(new Error(error || "worker_request_failed"));
  }
}

function workerRequest(type, payload = {}) {
  if (!state.worker) {
    return Promise.reject(new Error("worker_not_created"));
  }
  const id = ++state.workerRequestId;
  return new Promise((resolve, reject) => {
    state.workerRequests.set(id, { resolve, reject });
    state.worker.postMessage({ id, type, payload });
  });
}

function rejectPendingWorkerRequests(message) {
  for (const request of state.workerRequests.values()) {
    request.reject(new Error(message));
  }
  state.workerRequests.clear();
}

function describeRuntimeError(error) {
  const message = error?.message || String(error);
  if (message === "local_file_protocol") {
    return "当前页面是直接打开的本地 index.html。请进入 static_web 目录后运行 python3 -m http.server 8765，再访问 http://localhost:8765/；公网部署时也必须通过 http/https URL 访问。";
  }
  if (message.startsWith("local_fetch_failed:")) {
    const [, url] = message.split(":");
    return `无法读取静态资源 ${url}。如果你打开的是 localhost，请确认静态服务器还在运行；如果是公网部署，请确认 static_web/py 和 static_web/vendor 目录也一起上传了。`;
  }
  if (message.startsWith("local_fetch_status:")) {
    const [, url, status] = message.split(":");
    return `无法读取静态资源 ${url}，HTTP 状态码 ${status}。请确认 static_web/py 和 static_web/vendor 目录已经和 index.html 一起部署。`;
  }
  if (message.includes("Failed to fetch") && state.loadingStep === "packages") {
    return "无法读取本地 Pyodide/numpy/pandas 运行包。请确认 static_web/vendor/pyodide 已经和页面一起部署。";
  }
  if (message.includes("Failed to fetch")) {
    return "浏览器无法获取运行资源。请确认页面是通过 http/https 打开的、静态服务器没有停止，并且 static_web/vendor 目录已经一起部署。";
  }
  return message;
}

function updateRunButton() {
  const hasRuntime = Boolean(state.workerReady);
  const missing = missingBundleFiles();
  const hasLocalPaths = hasLocalPathInputs();
  els.runButton.disabled = !((hasRuntime && missing.length === 0) || hasLocalPaths);
}

async function runEvaluation() {
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
    showMessage(`评估失败：${error.message}`, "error");
    enableDownloads(false);
  } finally {
    setBusy(false);
  }
}

function hasLocalPathInputs() {
  return Boolean((els.dataDirPath?.value || "").trim() && (els.logDirPath?.value || "").trim());
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
    throw new Error(`本地路径评估失败：${detail}`);
  }
  state.reportSource = "local_paths";
  return JSON.stringify(payload.report || payload);
}

function localPathServerErrorMessage(response, payload) {
  if ([404, 405, 501].includes(response.status)) {
    return "当前页面不是通过 static_web/local_server.py 启动，不能直接读取本地路径。请在仓库根目录运行 python static_web/local_server.py --host 127.0.0.1 --port 8766 后打开 http://127.0.0.1:8766/，或者改用目录选择按钮导入文件。";
  }
  return payload?.error || `HTTP ${response.status}`;
}

function buildConfig() {
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

function requiredBundleFiles(entryMode) {
  const estimateName = entryMode === "vloc" ? "vloc.txt" : "vo.txt";
  const logFiles = entryMode === "vloc" ? [estimateName, "home_point.txt", "calib_raw.yaml"] : [estimateName, "calib_raw.yaml"];
  return {
    data: ["imu.txt"],
    log: logFiles,
  };
}

function selectedFiles(input) {
  return Array.from(input?.files || []);
}

function directoryFileMap(input, allowedNames = null) {
  const files = selectedFiles(input);
  const out = new Map();
  const allowed = allowedNames ? new Set(allowedNames) : null;
  for (const file of files) {
    const relative = file.webkitRelativePath || file.name;
    const parts = relative.split("/");
    const basename = parts[parts.length - 1];
    if (allowed && !allowed.has(basename)) {
      continue;
    }
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
  const pathInput = isData ? els.dataDirPath : els.logDirPath;
  const target = isData ? els.dataDirStatus : els.logDirStatus;
  const files = selectedFiles(input);
  if (!files.length) {
    const typedPath = (pathInput?.value || "").trim();
    target.textContent = typedPath ? "已填写路径，静态网页仍需选择必需文件" : "未选择目录";
    return;
  }
  const name = directoryNameFromFiles(files) || (isData ? "data_dir" : "log_dir");
  target.textContent = `${name} · ${files.length} 个文件`;
}

function missingBundleFiles() {
  const entryMode = valueOf("entryMode");
  const required = requiredBundleFiles(entryMode);
  const dataFiles = directoryFileMap(els.dataDirFiles, required.data);
  const logFiles = directoryFileMap(els.logDirFiles, required.log);
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
    if ((els.dataDirPath?.value || els.logDirPath?.value || "").trim()) {
      throw new Error(`静态网页不能直接读取本地路径，请用选择按钮导入必需文件：${missing.join("，")}`);
    }
    throw new Error(`缺少必需文件：${missing.join("，")}`);
  }
  const required = requiredBundleFiles(entryMode);
  const dataFiles = directoryFileMap(els.dataDirFiles, required.data);
  const logFiles = directoryFileMap(els.logDirFiles, required.log);
  const imuFile = dataFiles.get(required.data[0]);
  const estimateFile = logFiles.get(required.log[0]);
  const calibRawFile = logFiles.get("calib_raw.yaml");
  const readTasks = [
    imuFile.text(),
    estimateFile.text(),
    calibRawFile.text(),
  ];
  let homePointFile = null;
  if (entryMode === "vloc") {
    homePointFile = logFiles.get("home_point.txt");
    readTasks.splice(2, 0, homePointFile.text());
  }
  const texts = await Promise.all(readTasks);
  const payload = {
    imuText: texts[0],
    estimateText: texts[1],
    calibRawText: entryMode === "vloc" ? texts[3] : texts[2],
    dataDirName: directoryNameFromFiles(selectedFiles(els.dataDirFiles)) || "data_dir",
    logDirName: directoryNameFromFiles(selectedFiles(els.logDirFiles)) || "log_dir",
    imuName: imuFile.name,
    estimateName: estimateFile.name,
    calibRawName: calibRawFile.name,
  };
  if (entryMode === "vloc") {
    payload.homePointText = texts[2];
    payload.homePointName = homePointFile.name;
  }
  return payload;
}

function updateEntryModeHint() {
  const entryMode = valueOf("entryMode");
  const estimateName = entryMode === "vloc" ? "vloc.txt" : "vo.txt";
  const logFiles = entryMode === "vloc"
    ? `<code>log_dir/${estimateName}</code>、<code>home_point.txt</code> 和 <code>calib_raw.yaml</code>`
    : `<code>log_dir/${estimateName}</code> 和 <code>calib_raw.yaml</code>`;
  els.entryModeHint.innerHTML = `当前模式会读取 ${logFiles}。`;
}

function reportEntryMode(report = null) {
  return report?.inputs?.entry_mode || valueOf("entryMode") || "vloc";
}

function visibleChartIdsForEntryMode(entryMode) {
  return entryMode === "vloc" ? VLOC_VISIBLE_CHART_IDS : VO_VISIBLE_CHART_IDS;
}

function selectedChartIdsForEntryMode(entryMode) {
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

function visualizationTemplates() {
  if (!globalThis.VoVisualizationTemplates) {
    throw new Error("Visualization templates failed to load");
  }
  return globalThis.VoVisualizationTemplates;
}

function visualizationFigures() {
  if (!globalThis.VoVisualizationFigures) {
    throw new Error("Visualization figure specs failed to load");
  }
  return globalThis.VoVisualizationFigures;
}

function renderChartDirectory(listNode, options, selected) {
  if (!listNode) {
    return;
  }
  listNode.innerHTML = visualizationTemplates().chartDirectoryHtml(options, selected);
}

function renderVlocChartDirectory() {
  renderChartDirectory(els.vlocChartList, VLOC_CHART_OPTIONS, selectedVlocChartIds());
}

function renderVoChartDirectory() {
  renderChartDirectory(els.voChartList, VO_CHART_OPTIONS, selectedVoChartIds());
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

function chartTitleById(chartId, entryMode = reportEntryMode(state.report)) {
  const primaryOptions = entryMode === "vo" ? VO_CHART_OPTIONS : VLOC_CHART_OPTIONS;
  const fallbackOptions = entryMode === "vo" ? VLOC_CHART_OPTIONS : VO_CHART_OPTIONS;
  return [...primaryOptions, ...fallbackOptions].find((option) => option.id === chartId)?.label || chartId;
}

function isPointSelectableChart(chartId) {
  if (!state.report) {
    return false;
  }
  const entryMode = reportEntryMode(state.report);
  if (entryMode === "vloc") {
    return PICKABLE_VLOC_CHART_IDS.includes(chartId);
  }
  if (entryMode === "vo") {
    return PICKABLE_VO_CHART_IDS.includes(chartId);
  }
  return false;
}

function pointColorMeta(sequence) {
  const zeroIndex = Math.max(0, sequence - 1);
  const colorIndex = zeroIndex % POINT_SELECTION_COLORS.length;
  const cycle = Math.floor(zeroIndex / POINT_SELECTION_COLORS.length);
  return {
    color: POINT_SELECTION_COLORS[colorIndex],
    text: cycle > 0 ? String(cycle) : "",
  };
}

function nextPointSelectionColorSlot() {
  const usedSlots = new Set(state.pointSelections.map((selection) => selection.colorSlot).filter(Number.isFinite));
  let slot = 1;
  while (usedSlots.has(slot)) {
    slot += 1;
  }
  return slot;
}

function resetPointSelectionState() {
  state.activePointSelectionChartId = null;
  state.focusedPointSelectionId = null;
  state.pointSelectionSequence = 0;
  state.pointSelections = [];
  renderPointSelectionOutput();
  refreshAllPointSelectionTools();
}

function ensurePointSelectionTools(chartId) {
  const chart = document.getElementById(chartId);
  if (!chart) {
    return;
  }
  if (!isPointSelectableChart(chartId)) {
    removePointSelectionTools(chartId);
    return;
  }
  let tools = chart.querySelector?.(".chart-point-tools");
  if (!tools && typeof chart.appendChild === "function") {
    tools = document.createElement("div");
    tools.className = "chart-point-tools";
    tools.innerHTML = `
      <button type="button" class="chart-point-tool pick" title="选取当前图的点" aria-label="选取当前图的点">⌖</button>
      <button type="button" class="chart-point-tool clear" title="清除当前图的点" aria-label="清除当前图的点">⌫</button>
    `;
    chart.appendChild(tools);
    tools.querySelector(".pick")?.addEventListener("click", (event) => {
      event.stopPropagation();
      togglePointSelectionMode(chartId);
    });
    tools.querySelector(".clear")?.addEventListener("click", (event) => {
      event.stopPropagation();
      clearPointSelectionsForChart(chartId);
    });
  }
  if (!chart._pointSelectionClickBound && typeof chart.on === "function") {
    chart.on("plotly_click", (eventData) => handlePlotPointClick(chartId, eventData));
    chart._pointSelectionClickBound = true;
  }
  if (!chart._pointSelectionHoverBound && typeof chart.on === "function") {
    chart.on("plotly_hover", (eventData) => handlePlotPointHover(chartId, eventData));
    chart._pointSelectionHoverBound = true;
  }
  refreshPointSelectionToolState(chartId);
  refreshChartSelectionMarkers(chartId);
}

function removePointSelectionTools(chartId) {
  const chart = document.getElementById(chartId);
  const tools = chart?.querySelector?.(".chart-point-tools");
  if (tools) {
    tools.remove();
  }
  if (chart) {
    chart.classList?.remove?.("point-selection-active");
  }
}

function refreshPointSelectionToolState(chartId) {
  const chart = document.getElementById(chartId);
  if (!chart) {
    return;
  }
  const active = state.activePointSelectionChartId === chartId;
  chart.classList?.toggle?.("point-selection-active", active);
  const pickButton = chart.querySelector?.(".chart-point-tool.pick");
  if (pickButton) {
    pickButton.classList?.toggle?.("active", active);
  }
}

function refreshAllPointSelectionTools() {
  for (const chartId of chartIds) {
    if (isPointSelectableChart(chartId)) {
      ensurePointSelectionTools(chartId);
    } else {
      removePointSelectionTools(chartId);
    }
  }
}

function togglePointSelectionMode(chartId) {
  if (!isPointSelectableChart(chartId)) {
    return;
  }
  state.activePointSelectionChartId = state.activePointSelectionChartId === chartId ? null : chartId;
  refreshAllPointSelectionTools();
}

function isSelectionMarkerTrace(trace) {
  return Boolean(trace?.meta?.pointSelectionMarker || trace?.meta?.pointSelectionHitTarget);
}

function pointTimestamp(point) {
  const custom = Array.isArray(point?.data?.customdata) ? point.data.customdata[point.pointNumber] : undefined;
  const customTimestamp = typeof custom === "object" && custom !== null ? custom.timestamp : custom;
  const timestamp = Number(customTimestamp);
  if (Number.isFinite(timestamp)) {
    return timestamp;
  }
  const x = Number(point?.x);
  return Number.isFinite(x) ? x : null;
}

function pointValueText(chartId, point) {
  const x = Number(point?.x);
  const y = Number(point?.y);
  if (chartId === "trajectoryXY") {
    return `north=${formatPointNumber(x)}, east=${formatPointNumber(y)}`;
  }
  return formatPointNumber(y);
}

function formatPointNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "N/A";
  }
  return number.toFixed(3);
}

function numbersNearlyEqual(left, right, tolerance = 1e-9) {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  return Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && Math.abs(leftNumber - rightNumber) <= tolerance;
}

function existingPointSelectionForPoint(chartId, point) {
  const traceName = point?.data?.name || `trace ${Number(point?.curveNumber) + 1}`;
  const timestamp = pointTimestamp(point);
  const x = Number(point?.x);
  const y = Number(point?.y);
  return state.pointSelections.find((selection) => {
    if (selection.chartId !== chartId) {
      return false;
    }
    if (selection.traceName !== traceName) {
      return false;
    }
    const sameVisiblePoint = numbersNearlyEqual(selection.x, x) && numbersNearlyEqual(selection.y, y);
    if (Number.isFinite(timestamp) && Number.isFinite(selection.timestamp)) {
      return numbersNearlyEqual(selection.timestamp, timestamp) && sameVisiblePoint;
    }
    return sameVisiblePoint;
  });
}

function focusPointSelection(selection) {
  if (!selection) {
    return false;
  }
  if (state.focusedPointSelectionId === selection.id) {
    return true;
  }
  state.focusedPointSelectionId = selection.id;
  return true;
}

function selectionFromMarkerPoint(point) {
  if (!isSelectionMarkerTrace(point?.data)) {
    return null;
  }
  const markerData = Array.isArray(point.data.customdata) ? point.data.customdata[point.pointNumber] : null;
  const selectionId = markerData?.selectionId || point.data?.meta?.selectionId;
  return state.pointSelections.find((selection) => selection.id === selectionId) || null;
}

function eventPoints(eventData) {
  return Array.isArray(eventData?.points) ? eventData.points.filter(Boolean) : [];
}

function pointSelectionFromEventPoints(chartId, eventData) {
  const points = eventPoints(eventData);
  for (const point of points) {
    const selection = selectionFromMarkerPoint(point);
    if (selection) {
      return selection;
    }
  }
  for (const point of points) {
    const selection = existingPointSelectionForPoint(chartId, point);
    if (selection) {
      return selection;
    }
  }
  return null;
}

function focusPointSelectionFromEvent(chartId, eventData) {
  return focusPointSelection(pointSelectionFromEventPoints(chartId, eventData));
}

function firstSelectablePlotPoint(eventData) {
  return eventPoints(eventData).find((point) => !isSelectionMarkerTrace(point.data)) || null;
}

function addPointSelectionFromEvent(chartId, eventData) {
  const point = firstSelectablePlotPoint(eventData);
  if (!point) {
    return;
  }
  if (focusPointSelectionFromEvent(chartId, eventData)) {
    return;
  }
  state.pointSelectionSequence += 1;
  const sequence = state.pointSelectionSequence;
  const colorSlot = nextPointSelectionColorSlot();
  const colorMeta = pointColorMeta(colorSlot);
  const selection = {
    id: `picked-${Date.now()}-${sequence}`,
    order: sequence,
    colorSlot,
    chartId,
    chartTitle: chartTitleById(chartId),
    traceName: point.data?.name || `trace ${Number(point.curveNumber) + 1}`,
    markerColor: colorMeta.color,
    markerText: colorMeta.text,
    timestamp: pointTimestamp(point),
    value: pointValueText(chartId, point),
    x: Number(point.x),
    y: Number(point.y),
    xaxis: point.data?.xaxis || "x",
    yaxis: point.data?.yaxis || "y",
  };
  state.pointSelections.push(selection);
  state.focusedPointSelectionId = selection.id;
  refreshChartSelectionMarkers(chartId);
  renderPointSelectionOutput();
}

function handlePlotPointClick(chartId, eventData) {
  if (!eventPoints(eventData).length) {
    return;
  }
  if (focusPointSelectionFromEvent(chartId, eventData)) {
    return;
  }
  if (state.activePointSelectionChartId !== chartId || !isPointSelectableChart(chartId)) {
    return;
  }
  addPointSelectionFromEvent(chartId, eventData);
}

function handlePlotPointHover(chartId, eventData) {
  if (!eventPoints(eventData).length || !isPointSelectableChart(chartId)) {
    return;
  }
  focusPointSelectionFromEvent(chartId, eventData);
}

function selectionMarkerTrace(selection) {
  return {
    x: [selection.x],
    y: [selection.y],
    mode: selection.markerText ? "markers+text" : "markers",
    type: "scatter",
    name: `选点 ${selection.order}`,
    showlegend: false,
    hovertemplate: `${escapeHtml(selection.traceName)}<br>timestamp=%{customdata.timestamp:.3f}<br>value=${escapeHtml(selection.value)}<extra></extra>`,
    marker: {
      color: selection.markerColor,
      size: 10,
      symbol: "circle",
      line: { width: 0 },
    },
    text: selection.markerText ? [selection.markerText] : [""],
    textposition: "middle center",
    textfont: { color: "#ffffff", size: 9, family: "Arial, sans-serif" },
    customdata: [{ selectionId: selection.id, timestamp: selection.timestamp }],
    meta: { pointSelectionMarker: true, selectionId: selection.id },
    xaxis: selection.xaxis,
    yaxis: selection.yaxis,
  };
}

function selectionHitTargetTrace(selection) {
  return {
    x: [selection.x],
    y: [selection.y],
    mode: "markers",
    type: "scatter",
    name: `选点命中 ${selection.order}`,
    showlegend: false,
    hoverinfo: "none",
    marker: {
      color: selection.markerColor,
      size: 24,
      opacity: 0.04,
      symbol: "circle",
      line: { width: 0 },
    },
    customdata: [{ selectionId: selection.id, timestamp: selection.timestamp }],
    meta: { pointSelectionHitTarget: true, selectionId: selection.id },
    xaxis: selection.xaxis,
    yaxis: selection.yaxis,
  };
}

function selectionMarkerTraceIndices(chartId) {
  const chart = document.getElementById(chartId);
  const data = Array.isArray(chart?.data) ? chart.data : [];
  return data
    .map((trace, index) => (isSelectionMarkerTrace(trace) ? index : -1))
    .filter((index) => index >= 0);
}

function removeSelectionMarkerTraces(chartId) {
  const indices = selectionMarkerTraceIndices(chartId);
  if (!indices.length || typeof Plotly === "undefined" || typeof Plotly.deleteTraces !== "function") {
    return;
  }
  Plotly.deleteTraces(chartId, indices);
}

function refreshChartSelectionMarkers(chartId) {
  if (!document.getElementById(chartId)) {
    return;
  }
  removeSelectionMarkerTraces(chartId);
  const selections = state.pointSelections.filter((selection) => selection.chartId === chartId);
  if (!selections.length || typeof Plotly === "undefined" || typeof Plotly.addTraces !== "function") {
    return;
  }
  Plotly.addTraces(chartId, selections.flatMap((selection) => [selectionHitTargetTrace(selection), selectionMarkerTrace(selection)]));
}

function refreshAllSelectionMarkers() {
  for (const chartId of new Set([...PICKABLE_VLOC_CHART_IDS, ...PICKABLE_VO_CHART_IDS])) {
    refreshChartSelectionMarkers(chartId);
  }
}

function clearPointSelectionsForChart(chartId) {
  state.pointSelections = state.pointSelections.filter((selection) => selection.chartId !== chartId);
  if (state.activePointSelectionChartId === chartId) {
    state.activePointSelectionChartId = null;
  }
  if (!state.pointSelections.some((selection) => selection.id === state.focusedPointSelectionId)) {
    state.focusedPointSelectionId = null;
  }
  refreshChartSelectionMarkers(chartId);
  refreshPointSelectionToolState(chartId);
  renderPointSelectionOutput();
}

function clearAllPointSelections() {
  state.pointSelections = [];
  state.focusedPointSelectionId = null;
  state.activePointSelectionChartId = null;
  state.pointSelectionSequence = 0;
  refreshAllSelectionMarkers();
  refreshAllPointSelectionTools();
  renderPointSelectionOutput();
}

function deleteFocusedPointSelection() {
  if (!state.focusedPointSelectionId) {
    return;
  }
  const target = state.pointSelections.find((selection) => selection.id === state.focusedPointSelectionId);
  state.pointSelections = state.pointSelections.filter((selection) => selection.id !== state.focusedPointSelectionId);
  state.focusedPointSelectionId = null;
  if (target) {
    refreshChartSelectionMarkers(target.chartId);
  }
  renderPointSelectionOutput();
}

function isTextEditingTarget(target) {
  const tag = target?.tagName?.toLowerCase();
  if (!tag) {
    return false;
  }
  if (target?.isContentEditable) {
    return true;
  }
  if (tag === "textarea" || tag === "select") {
    return true;
  }
  if (tag !== "input") {
    return false;
  }
  const type = String(target.type || "text").toLowerCase();
  return !["button", "checkbox", "color", "file", "radio", "range", "reset", "submit"].includes(type);
}

function handlePointSelectionKeydown(event) {
  if (event.key !== "Delete" && event.key !== "Backspace") {
    return;
  }
  if (isTextEditingTarget(event.target)) {
    return;
  }
  if (state.focusedPointSelectionId) {
    event.preventDefault();
    deleteFocusedPointSelection();
  }
}

function groupedSelectionsForChart(selections) {
  const groupOrder = new Map();
  for (const selection of selections) {
    if (!groupOrder.has(selection.traceName)) {
      groupOrder.set(selection.traceName, groupOrder.size);
    }
  }
  return [...selections].sort((left, right) => {
    const groupDiff = groupOrder.get(left.traceName) - groupOrder.get(right.traceName);
    return groupDiff || left.order - right.order;
  });
}

function renderPointSelectionOutput() {
  if (!els.pointSelectionOutputSection || !els.pointSelectionOutput) {
    return;
  }
  const entryMode = reportEntryMode(state.report);
  const pickableIds = entryMode === "vo" ? PICKABLE_VO_CHART_IDS : entryMode === "vloc" ? PICKABLE_VLOC_CHART_IDS : [];
  const selections = state.pointSelections.filter((selection) => pickableIds.includes(selection.chartId));
  els.pointSelectionOutputSection.hidden = selections.length === 0;
  if (!selections.length) {
    els.pointSelectionOutput.innerHTML = "";
    return;
  }
  const chartOrder = [];
  for (const selection of selections) {
    if (!chartOrder.includes(selection.chartId)) {
      chartOrder.push(selection.chartId);
    }
  }
  els.pointSelectionOutput.innerHTML = chartOrder.map((chartId) => {
    const chartSelections = groupedSelectionsForChart(selections.filter((selection) => selection.chartId === chartId));
    const title = chartSelections[0]?.chartTitle || chartTitleById(chartId);
    const rows = chartSelections.map((selection) => `
      <tr data-selection-id="${escapeHtml(selection.id)}">
        <td>${escapeHtml(selection.traceName)}</td>
        <td><span class="selection-point-token" style="background:${escapeHtml(selection.markerColor)}">${escapeHtml(selection.markerText)}</span></td>
        <td>${selection.timestamp === null ? "N/A" : formatPointNumber(selection.timestamp)}</td>
        <td>${escapeHtml(selection.value)}</td>
      </tr>
    `).join("");
    return `
      <div class="point-selection-card">
        <h3>${escapeHtml(title)}</h3>
        <table class="point-selection-table">
          <thead>
            <tr><th>线</th><th>点</th><th>时间戳</th><th>值</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }).join("");
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
  renderPointSelectionOutput();
  refreshAllPointSelectionTools();
}

function resetRenderedReport() {
  state.report = null;
  state.chartRenderToken += 1;
  resetPointSelectionState();
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

function setBusy(isBusy) {
  els.runButton.textContent = isBusy ? "计算中..." : "运行评估";
  if (isBusy) {
    els.runButton.disabled = true;
    return;
  }
  updateRunButton();
}

function renderReport(report) {
  if (reportEntryMode(report) === "vloc") {
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

function renderMetrics(report) {
  document.getElementById("metrics").innerHTML = visualizationTemplates().metricGridHtml(metricItems(report), { formatValue });
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

function scheduleRenderCharts(report) {
  if (!report) {
    return;
  }
  const entryMode = reportEntryMode(report);
  applyEntryModeChartVisibility(entryMode);
  purgeUnselectedCharts(entryMode);
  const token = ++state.chartRenderToken;
  const selectedIds = Array.from(selectedChartIdsForEntryMode(entryMode)).filter((id) => visibleChartIdsForEntryMode(entryMode).includes(id));
  (async () => {
    for (const chartId of selectedIds) {
      if (token !== state.chartRenderToken) {
        return;
      }
      await nextRenderFrame();
      if (token !== state.chartRenderToken) {
        return;
      }
      renderCharts(report, chartId);
    }
  })();
}

function nextRenderFrame() {
  if (typeof requestAnimationFrame === "function") {
    return new Promise((resolve) => requestAnimationFrame(resolve));
  }
  if (typeof setTimeout === "function") {
    return new Promise((resolve) => setTimeout(resolve, 0));
  }
  return Promise.resolve();
}

function purgeChart(chartId) {
  const node = document.getElementById(chartId);
  if (!node) {
    return;
  }
  if (typeof Plotly !== "undefined" && typeof Plotly.purge === "function") {
    Plotly.purge(chartId);
  }
  node.innerHTML = "";
}

function purgeUnselectedCharts(entryMode) {
  const selectedIds = selectedChartIdsForEntryMode(entryMode);
  const visibleIds = new Set(visibleChartIdsForEntryMode(entryMode));
  for (const chartId of chartIds) {
    if (!visibleIds.has(chartId) || selectedIds.has(chartId)) {
      continue;
    }
    purgeChart(chartId);
  }
}

function shouldRenderChart(chartId, onlyChartId, selectedIds) {
  return (!onlyChartId || onlyChartId === chartId) && selectedIds.has(chartId);
}

function renderCharts(report, onlyChartId = null) {
  const entryMode = reportEntryMode(report);
  applyEntryModeChartVisibility(entryMode);
  const selectedIds = selectedChartIdsForEntryMode(entryMode);
  visualizationFigures().buildVisualizationFigureSpecs(report, { variant: "live" })
    .filter((figure) => shouldRenderChart(figure.id, onlyChartId, selectedIds))
    .forEach(renderLiveFigure);
}

function renderLiveFigure(figure) {
  Plotly.newPlot(figure.id, figure.data, figure.layout);
  if (figure.compositeRows && figure.compositeSpec) {
    attachCompositeOverlay(figure.id, figure.compositeRows, figure.compositeSpec);
  }
  if (figure.livePickable) {
    ensurePointSelectionTools(figure.id);
  }
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
  [els.downloadJson, els.downloadConfigJson, els.downloadTrajectoryExcel, els.downloadHtml].forEach((button) => {
    button.disabled = !enabled;
  });
}

async function downloadReportJson() {
  try {
    const text = JSON.stringify(await fetchReportSlice("full_report"), null, 2);
    downloadText("vo_evaluation_metrics.json", text, "application/json");
  } catch (error) {
    showMessage(`导出 JSON 失败：${error.message}`, "error");
  }
}

async function downloadTrajectoryExcel() {
  try {
    const trajectoryExports = await fetchReportSlice("trajectory_exports");
    downloadBytes(
      evaluationExportFilename("trajectory_exports", "xlsx"),
      buildTrajectoryWorkbook(trajectoryExports || {}),
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    );
  } catch (error) {
    showMessage(`导出 Excel 失败：${error.message}`, "error");
  }
}

async function downloadHtmlReport() {
  try {
    const [plotlySource, cssSource, reportCssSource] = await Promise.all([
      fetchLocalText(PLOTLY_SCRIPT_URL),
      fetchLocalText("./style.css"),
      fetchLocalText("./visualization/report_export.css"),
    ]);
    downloadText(evaluationExportFilename("evaluation_report", "html"), buildHtmlReport(state.report || {}, { plotlySource, cssSource, reportCssSource }), "text/html");
  } catch (error) {
    showMessage(`导出 HTML 失败：${error.message}`, "error");
  }
}

async function fetchLocalText(url) {
  let response;
  try {
    response = await fetch(url, { cache: "no-store" });
  } catch (error) {
    throw new Error(`无法读取本地资源 ${url}：${error.message || error}`);
  }
  if (!response.ok) {
    throw new Error(`无法读取本地资源 ${url}，HTTP 状态码 ${response.status}`);
  }
  return response.text();
}

function evaluationExportFilename(kind, extension, report = state.report) {
  const entryMode = sanitizeFilenamePart(reportEntryMode(report)) || "vloc";
  const dataset = exportDatasetName(report);
  const prefix = dataset ? `${dataset}_${entryMode}` : entryMode;
  return `${prefix}_${sanitizeFilenamePart(kind)}.${sanitizeFilenamePart(extension)}`;
}

function exportDatasetName(report = state.report) {
  const inputs = report?.inputs || {};
  const dataName = meaningfulDirectoryName(inputs.data_dir_name || directoryNameFromFiles(selectedFiles(els.dataDirFiles)));
  const logName = meaningfulDirectoryName(inputs.log_dir_name || directoryNameFromFiles(selectedFiles(els.logDirFiles)));
  if (dataName && logName && dataName !== logName) {
    return `${dataName}__${logName}`;
  }
  return logName || dataName || "";
}

function meaningfulDirectoryName(value) {
  const name = sanitizeFilenamePart(value);
  const lower = name.toLowerCase();
  if (lower === "data_dir" || lower === "log_dir") {
    return "";
  }
  return name;
}

function sanitizeFilenamePart(value) {
  return String(value || "")
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
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

function buildHtmlReport(sourceReport = state.report || {}, options = {}) {
  const report = reportForHtmlExport(sourceReport || {});
  const entryMode = reportEntryMode(report);
  const isVloc = entryMode === "vloc";
  const title = isVloc ? "VLOC 评估结果" : "VO 评估结果";
  const summaryTitle = isVloc ? "VLOC 运行结果" : "VO 运行结果";
  const kicker = isVloc ? "VLOC Offline Visualization" : "VO Offline Visualization";
  const metrics = metricItems(report);
  const figures = visualizationFigures().buildVisualizationFigureSpecs(report, { variant: "export" });
  const plotlyScript = options.plotlySource
    ? `<script>${options.plotlySource.replaceAll("</script", "<\\/script")}<\/script>`
    : `<script src="${escapeHtml(PLOTLY_SCRIPT_URL)}"><\/script>`;
  const cssSource = `${options.cssSource || ""}\n${options.reportCssSource || ""}`.replaceAll("</style", "<\\/style");
  const chartOptions = isVloc ? VLOC_CHART_OPTIONS : VO_CHART_OPTIONS;
  const selectedIds = new Set(figures.map((figure) => figure.id));
  const chartDirectory = visualizationTemplates().chartDirectoryHtml(
    chartOptions.filter((option) => selectedIds.has(option.id)),
    selectedIds,
  );
  const figureHtml = figures.map((figure) => `
    <section class="chart-card" data-chart-id="${escapeHtml(figure.id)}">
      <div class="chart-header">
        <div>
          <div class="chart-kicker">${escapeHtml(figure.pickable ? "Selectable chart" : "Chart")}</div>
          <h2>${escapeHtml(figure.label)}</h2>
        </div>
        ${figure.pickable ? `<div class="chart-tools"><button type="button" data-action="select" data-chart-id="${escapeHtml(figure.id)}">选点</button><button type="button" data-action="clear" data-chart-id="${escapeHtml(figure.id)}">清除</button></div>` : ""}
      </div>
      <div id="${escapeHtml(figure.id)}" class="chart export-plot" style="height:${Number(figure.layout?.height || 520)}px;width:100%;"></div>
    </section>
  `).join("");
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>${escapeHtml(title)}</title>
${plotlyScript}
<style>${cssSource}</style>
</head><body>
<header class="topbar">
  <div>
    <h1>${escapeHtml(title)}</h1>
    <p>离线可视化快照。保留页面上的指标卡、图表目录、图表交互和选点记录；不包含上传与重新评估功能。</p>
  </div>
  <span class="offline-mode-pill">${escapeHtml(kicker)}</span>
</header>
<main class="layout" data-entry-mode="${escapeHtml(entryMode)}">
  <aside class="controls">
    <section>
      <h2>图表目录</h2>
      <p class="section-hint">选择右侧展示的图表；导出的报告默认全开。</p>
      <div id="chartDirectory" class="chart-directory-list">${chartDirectory}</div>
      <div class="chart-directory-actions">
        <button type="button" id="selectAllCharts">全选</button>
        <button type="button" id="clearCharts">清除</button>
      </div>
    </section>
    <section id="pointSelectionOutputSection" hidden>
      <h2>输出对比</h2>
      <p class="section-hint">选取图中点后，这里按图表汇总点所在曲线、点标记、时间戳和值。</p>
      <div id="pointSelectionOutput" class="point-selection-output"></div>
      <button type="button" id="clearAllPointSelections" class="clear-point-selections">清除所有点</button>
    </section>
  </aside>
  <section class="content">
    <section class="panel">
      <div class="section-head">
        <div>
          <div class="section-kicker">${escapeHtml(isVloc ? "VLOC Evaluation Summary" : "VO Evaluation Summary")}</div>
        <h2>${escapeHtml(summaryTitle)}</h2>
        </div>
      </div>
      <div class="metric-grid">${visualizationTemplates().metricGridHtml(metrics, { formatValue })}</div>
    </section>
    <section class="panel">
      <div class="section-head">
        <div>
          <div class="section-kicker">${escapeHtml(isVloc ? "Navigation & Estimation" : "Trajectory & Drift")}</div>
        <h2>${escapeHtml(isVloc ? "VLOC 可视化" : "VO 可视化")}</h2>
        </div>
      </div>
      <div class="chart-grid">${figureHtml || `<div class="empty-state">当前报告没有可导出的图表数据。</div>`}</div>
    </section>
  </section>
</main>
<script>
window.__VO_EXPORT_REPORT__ = ${safeJson(report)};
window.__VO_EXPORT_FIGURES__ = ${safeJson(figures)};
window.__VO_EXPORT_SELECTIONS__ = [];
window.__VO_ACTIVE_CHART__ = null;
window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = null;
window.__VO_EXPORT_SELECTION_SEQUENCE__ = 0;
const POINT_COLORS = ${safeJson(POINT_SELECTION_COLORS)};
function initExportPage() {
  renderAllCharts();
  document.querySelectorAll("#chartDirectory input").forEach((input) => {
    input.addEventListener("change", () => setChartVisible(input.dataset.chartId, input.checked));
  });
  document.getElementById("selectAllCharts")?.addEventListener("click", () => setAllChartsVisible(true));
  document.getElementById("clearCharts")?.addEventListener("click", () => setAllChartsVisible(false));
  document.getElementById("clearAllPointSelections")?.addEventListener("click", clearAllPointSelections);
  document.addEventListener("keydown", handleExportPointSelectionKeydown);
  document.querySelectorAll("[data-action='select']").forEach((button) => {
    button.addEventListener("click", () => togglePointMode(button.dataset.chartId));
  });
  document.querySelectorAll("[data-action='clear']").forEach((button) => {
    button.addEventListener("click", () => clearChartSelections(button.dataset.chartId));
  });
}
function renderAllCharts() {
  for (const figure of window.__VO_EXPORT_FIGURES__) {
    const node = document.getElementById(figure.id);
    if (!node) continue;
    Promise.resolve(Plotly.newPlot(figure.id, figure.data, figure.layout, {responsive: true})).then(() => {
      attachExportCompositeOverlay(figure);
      attachExportPointSelection(figure);
    });
  }
}
function attachExportPointSelection(figure) {
  const node = document.getElementById(figure.id);
  if (!node || !figure.pickable || typeof node.on !== "function" || node.__exportPointSelectionAttached) return;
  node.__exportPointSelectionAttached = true;
  node.on("plotly_click", (eventData) => {
    if (focusExportPointSelectionFromEvent(figure.id, eventData)) {
      return;
    }
    if (window.__VO_ACTIVE_CHART__ === figure.id) {
      recordPointSelection(figure, eventData);
    }
  });
  node.on("plotly_hover", (eventData) => {
    focusExportPointSelectionFromEvent(figure.id, eventData);
  });
}
function attachExportCompositeOverlay(figure) {
  const node = document.getElementById(figure.id);
  if (!node || figure.layout?.scene || typeof node.on !== "function" || node.__exportCompositeOverlayAttached) return;
  node.__exportCompositeOverlayAttached = true;
  ensureExportCompositeOverlay(figure.id);
  node.on("plotly_hover", (eventData) => renderExportCompositeHoverOverlay(figure.id, eventData));
  node.on("plotly_unhover", () => hideExportCompositeOverlay(figure.id));
  if (typeof node.addEventListener === "function") {
    node.addEventListener("mouseleave", () => hideExportCompositeOverlay(figure.id));
  }
}
function ensureExportCompositeOverlay(chartId) {
  const plot = document.getElementById(chartId);
  if (!plot) return null;
  if (!plot.style.position) plot.style.position = "relative";
  const crosshairId = chartId + "Crosshair";
  const tooltipId = chartId + "Tooltip";
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
function renderExportCompositeHoverOverlay(chartId, eventData) {
  const overlay = ensureExportCompositeOverlay(chartId);
  if (!overlay) return;
  const point = eventData?.points?.[0];
  const mouse = exportMousePosition(eventData, overlay.plot);
  const x = exportCrosshairX(point, mouse.x);
  const timestamp = point?.x;
  overlay.crosshair.style.left = Math.round(x) + "px";
  overlay.crosshair.style.top = "0px";
  overlay.crosshair.style.bottom = "0px";
  overlay.crosshair.style.display = "block";
  overlay.tooltip.innerHTML = "<strong>当前时间戳 " + numberText(timestamp) + " s</strong><div>" + exportAllHoverChips(chartId, timestamp) + "</div>";
  positionExportTooltip(overlay.tooltip, overlay.plot, mouse);
  overlay.tooltip.style.display = "block";
}
function exportMousePosition(eventData, plot) {
  const event = eventData?.event;
  const rect = plot.getBoundingClientRect ? plot.getBoundingClientRect() : { left: 0, top: 0 };
  return {
    x: Number.isFinite(Number(event?.clientX)) ? Number(event.clientX) - rect.left : 24,
    y: Number.isFinite(Number(event?.clientY)) ? Number(event.clientY) - rect.top : 24,
  };
}
function exportCrosshairX(point, mouseX) {
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
function exportAllHoverChips(chartId, timestamp) {
  const figure = window.__VO_EXPORT_FIGURES__.find((item) => item.id === chartId);
  const target = Number(timestamp);
  if (!figure || !Number.isFinite(target)) return "没有可用数据";
  const chips = [];
  for (const trace of figure.data || []) {
    if (trace?.type === "scatter3d" || trace?.meta?.pointSelectionMarker || trace?.meta?.pointSelectionHitTarget) {
      continue;
    }
    const point = nearestExportTracePoint(trace, target);
    if (!point) {
      continue;
    }
    chips.push('<span class="metric-chip"><strong>' + escapeHtml(trace.name || "trace") + '</strong><span class="metric-chip-value">' + numberText(point.y) + '</span></span>');
  }
  return chips.join("") || "没有可用数据";
}
function nearestExportTracePoint(trace, target) {
  const xs = Array.isArray(trace?.x) ? trace.x : [];
  const ys = Array.isArray(trace?.y) ? trace.y : [];
  let bestIndex = -1;
  let bestDiff = Infinity;
  for (let index = 0; index < xs.length; index += 1) {
    const x = Number(xs[index]);
    const y = Number(ys[index]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      continue;
    }
    const diff = Math.abs(x - target);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestIndex = index;
    }
  }
  if (bestIndex < 0) {
    return null;
  }
  return { x: Number(xs[bestIndex]), y: Number(ys[bestIndex]), index: bestIndex };
}
function positionExportTooltip(tooltip, plot, mouse) {
  const tooltipWidth = 380;
  const tooltipHeight = 190;
  const plotWidth = Number(plot.clientWidth || 0);
  const plotHeight = Number(plot.clientHeight || 0);
  const preferRight = mouse.x + tooltipWidth + 18 <= plotWidth;
  const left = preferRight ? mouse.x + 14 : Math.max(8, mouse.x - tooltipWidth - 14);
  const top = Math.max(8, Math.min(mouse.y + 14, Math.max(8, plotHeight - tooltipHeight)));
  tooltip.style.left = Math.round(left) + "px";
  tooltip.style.top = Math.round(top) + "px";
}
function hideExportCompositeOverlay(chartId) {
  const crosshair = document.getElementById(chartId + "Crosshair");
  const tooltip = document.getElementById(chartId + "Tooltip");
  if (crosshair) crosshair.style.display = "none";
  if (tooltip) tooltip.style.display = "none";
}
function setChartVisible(chartId, visible) {
  const card = document.querySelector(".chart-card[data-chart-id='" + cssEscape(chartId) + "']");
  if (card) card.hidden = !visible;
}
function setAllChartsVisible(visible) {
  document.querySelectorAll("#chartDirectory input").forEach((input) => {
    input.checked = visible;
    setChartVisible(input.dataset.chartId, visible);
  });
}
function togglePointMode(chartId) {
  window.__VO_ACTIVE_CHART__ = window.__VO_ACTIVE_CHART__ === chartId ? null : chartId;
  refreshAllExportPointModeStates();
}
function recordPointSelection(figure, eventData) {
  const point = firstExportSelectablePlotPoint(eventData);
  if (!point) return;
  window.__VO_EXPORT_SELECTION_SEQUENCE__ += 1;
  const order = window.__VO_EXPORT_SELECTION_SEQUENCE__;
  const colorSlot = nextExportPointColorSlot();
  const colorMeta = exportPointColorMeta(colorSlot);
  const traceName = point.data?.name || "trace " + (Number(point.curveNumber) + 1);
  const selection = {
    id: "p" + Date.now() + "_" + order,
    order,
    colorSlot,
    chartId: figure.id,
    chartTitle: figure.label,
    traceName,
    timestamp: exportPointTimestamp(point),
    value: exportPointValueText(figure.id, point),
    color: colorMeta.color,
    markerText: colorMeta.text,
    x: Number(point.x),
    y: Number(point.y),
    xaxis: point.data?.xaxis || "x",
    yaxis: point.data?.yaxis || "y",
  };
  window.__VO_EXPORT_SELECTIONS__.push(selection);
  window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = selection.id;
  refreshExportChartSelectionMarkers(figure.id);
  renderPointSelectionOutput();
}
function exportPointColorMeta(slot) {
  const zeroIndex = Math.max(0, slot - 1);
  const colorIndex = zeroIndex % POINT_COLORS.length;
  const cycle = Math.floor(zeroIndex / POINT_COLORS.length);
  return { color: POINT_COLORS[colorIndex], text: cycle > 0 ? String(cycle) : "" };
}
function nextExportPointColorSlot() {
  const used = new Set(window.__VO_EXPORT_SELECTIONS__.map((selection) => selection.colorSlot).filter((slot) => Number.isFinite(Number(slot))));
  let slot = 1;
  while (used.has(slot)) {
    slot += 1;
  }
  return slot;
}
function refreshExportPointModeState(chartId) {
  const card = document.querySelector(".chart-card[data-chart-id='" + cssEscape(chartId) + "']");
  if (card) {
    card.classList.toggle("point-selection-active", card.dataset.chartId === window.__VO_ACTIVE_CHART__);
  }
}
function refreshAllExportPointModeStates() {
  document.querySelectorAll(".chart-card").forEach((card) => {
    card.classList.toggle("point-selection-active", card.dataset.chartId === window.__VO_ACTIVE_CHART__);
  });
}
function exportSelectionMarkerTrace(selection) {
  return {
    x: [selection.x],
    y: [selection.y],
    mode: selection.markerText ? "markers+text" : "markers",
    type: "scatter",
    name: "选点 " + selection.order,
    text: selection.markerText ? [selection.markerText] : [""],
    textposition: "middle center",
    textfont: { color: "#ffffff", size: 9, family: "Arial, sans-serif" },
    marker: { color: selection.color, size: 9, symbol: "circle", line: { width: 0 } },
    customdata: [{ selectionId: selection.id, timestamp: selection.timestamp }],
    meta: { pointSelectionMarker: true, selectionId: selection.id },
    xaxis: selection.xaxis,
    yaxis: selection.yaxis,
    showlegend: false,
    hovertemplate: escapeHtml(selection.traceName) + "<br>timestamp=%{customdata.timestamp:.3f}<br>value=" + escapeHtml(String(selection.value)) + "<extra></extra>",
  };
}
function exportSelectionHitTargetTrace(selection) {
  return {
    x: [selection.x],
    y: [selection.y],
    mode: "markers",
    type: "scatter",
    name: "选点命中 " + selection.order,
    marker: { color: selection.color, size: 24, opacity: 0.04, symbol: "circle", line: { width: 0 } },
    customdata: [{ selectionId: selection.id, timestamp: selection.timestamp }],
    meta: { pointSelectionHitTarget: true, selectionId: selection.id },
    xaxis: selection.xaxis,
    yaxis: selection.yaxis,
    showlegend: false,
    hoverinfo: "none",
  };
}
function isExportSelectionTrace(trace) {
  return Boolean(trace?.meta?.pointSelectionMarker || trace?.meta?.pointSelectionHitTarget);
}
function exportSelectionFromMarkerPoint(point) {
  if (!isExportSelectionTrace(point?.data)) return null;
  const markerData = Array.isArray(point.data.customdata) ? point.data.customdata[point.pointNumber] : null;
  const selectionId = markerData?.selectionId || point.data?.meta?.selectionId;
  return window.__VO_EXPORT_SELECTIONS__.find((selection) => selection.id === selectionId) || null;
}
function exportPointTimestamp(point) {
  const custom = Array.isArray(point?.data?.customdata) ? point.data.customdata[point.pointNumber] : undefined;
  const customTimestamp = typeof custom === "object" && custom !== null ? custom.timestamp : custom;
  const timestamp = Number(customTimestamp);
  if (Number.isFinite(timestamp)) {
    return timestamp;
  }
  const x = Number(point?.x);
  return Number.isFinite(x) ? x : null;
}
function exportPointValueText(chartId, point) {
  const x = Number(point?.x);
  const y = Number(point?.y);
  if (chartId === "trajectoryXY") {
    return "north=" + numberText(x) + ", east=" + numberText(y);
  }
  return numberText(y);
}
function existingExportPointSelectionForPoint(chartId, point) {
  const traceName = point?.data?.name || "trace " + (Number(point?.curveNumber) + 1);
  const timestamp = exportPointTimestamp(point);
  const x = Number(point?.x);
  const y = Number(point?.y);
  return window.__VO_EXPORT_SELECTIONS__.find((selection) => {
    if (selection.chartId !== chartId || selection.traceName !== traceName) {
      return false;
    }
    const sameVisiblePoint = numbersClose(selection.x, x) && numbersClose(selection.y, y);
    if (Number.isFinite(timestamp) && Number.isFinite(Number(selection.timestamp))) {
      return numbersClose(selection.timestamp, timestamp) && sameVisiblePoint;
    }
    return sameVisiblePoint;
  }) || null;
}
function focusExportPointSelectionFromEvent(chartId, eventData) {
  const points = exportEventPoints(eventData);
  for (const point of points) {
    const selection = exportSelectionFromMarkerPoint(point);
    if (selection) {
      window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = selection.id;
      return true;
    }
  }
  for (const point of points) {
    const selection = existingExportPointSelectionForPoint(chartId, point);
    if (selection) {
      window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = selection.id;
      return true;
    }
  }
  return false;
}
function exportEventPoints(eventData) {
  return Array.isArray(eventData?.points) ? eventData.points.filter(Boolean) : [];
}
function firstExportSelectablePlotPoint(eventData) {
  return exportEventPoints(eventData).find((point) => !isExportSelectionTrace(point.data)) || null;
}
function numbersClose(left, right) {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  return Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && Math.abs(leftNumber - rightNumber) <= 1e-9;
}
function exportSelectionMarkerTraceIndices(chartId) {
  const chart = document.getElementById(chartId);
  const data = Array.isArray(chart?.data) ? chart.data : [];
  return data
    .map((trace, index) => (isExportSelectionTrace(trace) ? index : -1))
    .filter((index) => index >= 0);
}
function removeExportSelectionMarkerTraces(chartId) {
  const indices = exportSelectionMarkerTraceIndices(chartId);
  if (!indices.length || typeof Plotly === "undefined" || typeof Plotly.deleteTraces !== "function") {
    return;
  }
  Plotly.deleteTraces(chartId, indices);
}
function refreshExportChartSelectionMarkers(chartId) {
  if (!document.getElementById(chartId)) {
    return;
  }
  removeExportSelectionMarkerTraces(chartId);
  const selections = window.__VO_EXPORT_SELECTIONS__.filter((selection) => selection.chartId === chartId);
  if (!selections.length || typeof Plotly === "undefined" || typeof Plotly.addTraces !== "function") {
    return;
  }
  Plotly.addTraces(chartId, selections.flatMap((selection) => [exportSelectionHitTargetTrace(selection), exportSelectionMarkerTrace(selection)]));
}
function refreshAllExportSelectionMarkers() {
  for (const figure of window.__VO_EXPORT_FIGURES__) {
    refreshExportChartSelectionMarkers(figure.id);
  }
}
function clearChartSelections(chartId) {
  window.__VO_EXPORT_SELECTIONS__ = window.__VO_EXPORT_SELECTIONS__.filter((selection) => selection.chartId !== chartId);
  if (window.__VO_ACTIVE_CHART__ === chartId) {
    window.__VO_ACTIVE_CHART__ = null;
  }
  if (!window.__VO_EXPORT_SELECTIONS__.some((selection) => selection.id === window.__VO_EXPORT_FOCUSED_SELECTION_ID__)) {
    window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = null;
  }
  refreshExportChartSelectionMarkers(chartId);
  refreshExportPointModeState(chartId);
  renderPointSelectionOutput();
}
function clearAllPointSelections() {
  window.__VO_EXPORT_SELECTIONS__ = [];
  window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = null;
  window.__VO_ACTIVE_CHART__ = null;
  window.__VO_EXPORT_SELECTION_SEQUENCE__ = 0;
  refreshAllExportSelectionMarkers();
  refreshAllExportPointModeStates();
  renderPointSelectionOutput();
}
function deleteFocusedExportPointSelection() {
  const target = window.__VO_EXPORT_SELECTIONS__.find((selection) => selection.id === window.__VO_EXPORT_FOCUSED_SELECTION_ID__);
  if (!target) return;
  window.__VO_EXPORT_SELECTIONS__ = window.__VO_EXPORT_SELECTIONS__.filter((selection) => selection.id !== target.id);
  window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = null;
  refreshExportChartSelectionMarkers(target.chartId);
  renderPointSelectionOutput();
}
function isExportTextEditingTarget(target) {
  const tag = target?.tagName?.toLowerCase();
  if (!tag) {
    return false;
  }
  if (target?.isContentEditable) {
    return true;
  }
  if (tag === "textarea" || tag === "select") {
    return true;
  }
  if (tag !== "input") {
    return false;
  }
  const type = String(target.type || "text").toLowerCase();
  return !["button", "checkbox", "color", "file", "radio", "range", "reset", "submit"].includes(type);
}
function handleExportPointSelectionKeydown(event) {
  if (event.key !== "Delete" && event.key !== "Backspace") return;
  if (isExportTextEditingTarget(event.target)) return;
  if (window.__VO_EXPORT_FOCUSED_SELECTION_ID__) {
    event.preventDefault?.();
    deleteFocusedExportPointSelection();
  }
}
function renderPointSelectionOutput() {
  const section = document.getElementById("pointSelectionOutputSection");
  const output = document.getElementById("pointSelectionOutput");
  const selections = window.__VO_EXPORT_SELECTIONS__;
  section.hidden = selections.length === 0;
  if (!selections.length) {
    output.innerHTML = "";
    return;
  }
  const chartIds = [...new Set(selections.map((selection) => selection.chartId))];
  output.innerHTML = chartIds.map((chartId) => {
    const rows = selections.filter((selection) => selection.chartId === chartId);
    return '<div class="point-selection-card"><h3>' + escapeHtml(rows[0].chartTitle) + '</h3><table class="point-selection-table"><thead><tr><th>线</th><th>点</th><th>时间戳</th><th>值</th></tr></thead><tbody>' + rows.map((selection) => '<tr><td>' + escapeHtml(selection.traceName) + '</td><td><span class="selection-point-token" style="background:' + selection.color + '">' + escapeHtml(selection.markerText) + '</span></td><td>' + numberText(selection.timestamp) + '</td><td>' + numberText(selection.value) + '</td></tr>').join("") + '</tbody></table></div>';
  }).join("");
}
function numberText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(3) : escapeHtml(String(value ?? "N/A"));
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}
function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
  return String(value).replace(/'/g, "\\\\'");
}
initExportPage();
<\/script>
</body></html>`;
}

function reportForHtmlExport(report) {
  const isVo = reportEntryMode(report || {}) === "vo";
  const {
    trajectory_exports: trajectoryExports,
    per_pose: _perPose,
    segment_records: _segmentRecords,
    ...htmlReport
  } = report || {};
  if (trajectoryExports?.rpe_per_frame) {
    htmlReport.trajectory_exports = { ...htmlReport.trajectory_exports, rpe_per_frame: trajectoryExports.rpe_per_frame };
  }
  if (isVo && trajectoryExports?.scale_per_frame) {
    htmlReport.trajectory_exports = { ...htmlReport.trajectory_exports, scale_per_frame: trajectoryExports.scale_per_frame };
  }
  return htmlReport;
}

function metricItems(report) {
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
  return entryMode === "vloc" ? vlocMetrics : voMetrics;
}

function safeJson(value) {
  return JSON.stringify(value).replaceAll("</", "<\\/");
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
  const entries = orderedNames.filter((name) => Object.prototype.hasOwnProperty.call(sheets || {}, name)).map((name) => ({
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
