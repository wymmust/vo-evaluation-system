const state = {
  pyodide: null,
  evaluateJson: null,
  report: null,
  loadingStep: "",
};

const PYODIDE_INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

const els = {
  status: document.getElementById("runtimeStatus"),
  message: document.getElementById("message"),
  runButton: document.getElementById("runButton"),
  gtFile: document.getElementById("gtFile"),
  estFile: document.getElementById("estFile"),
  downloadJson: document.getElementById("downloadJson"),
  downloadPoseCsv: document.getElementById("downloadPoseCsv"),
  downloadSegmentCsv: document.getElementById("downloadSegmentCsv"),
  downloadHtml: document.getElementById("downloadHtml"),
};

const chartIds = ["trajectory3d", "trajectoryXY", "errorDistance", "altitudeDistance", "segmentError", "speedError"];

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
  [els.gtFile, els.estFile].forEach((input) => input.addEventListener("change", updateRunButton));
  els.runButton.addEventListener("click", runEvaluation);
  els.downloadJson.addEventListener("click", () => downloadText("vo_evaluation_metrics.json", JSON.stringify(state.report, null, 2), "application/json"));
  els.downloadPoseCsv.addEventListener("click", () => downloadText("vo_per_pose_errors.csv", toCsv(state.report?.per_pose || []), "text/csv"));
  els.downloadSegmentCsv.addEventListener("click", () => downloadText("vo_segment_errors.csv", toCsv(state.report?.segment_records || []), "text/csv"));
  els.downloadHtml.addEventListener("click", () => downloadText("vo_evaluation_report.html", buildHtmlReport(), "text/html"));
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
from browser_runner import evaluate_json
`);
  state.evaluateJson = state.pyodide.globals.get("evaluate_json");
}

async function fetchText(url) {
  let response;
  try {
    response = await fetch(url);
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
  els.runButton.disabled = !(state.evaluateJson && els.gtFile.files.length && els.estFile.files.length);
}

async function runEvaluation() {
  clearMessage();
  setBusy(true);
  try {
    const gtFile = els.gtFile.files[0];
    const estFile = els.estFile.files[0];
    const [gtText, estText] = await Promise.all([gtFile.text(), estFile.text()]);
    const config = buildConfig();
    const reportJson = state.evaluateJson(
      gtText,
      estText,
      valueOf("gtFormat"),
      valueOf("estFormat"),
      JSON.stringify(config),
      gtFile.name,
      estFile.name,
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
  const maxTimeDiff = numberOf("maxTimeDiff");
  return {
    alignment: valueOf("alignment"),
    max_time_diff_s: maxTimeDiff < 0 ? null : maxTimeDiff,
    time_offset_s: numberOf("timeOffset"),
    rpe_delta_frames: integerOf("rpeDelta"),
    segment_lengths_m: parseFloatList(valueOf("segmentLengths")),
    max_segments_per_length: integerOf("maxSegments"),
    segment_step_frames: integerOf("segmentStep"),
    max_segment_length_diff_ratio: numberOf("lengthTolerance"),
    continuous_segment_policy: valueOf("segmentPolicy"),
    discontinuity_step_m: numberOf("discontinuityStep"),
    discontinuity_time_gap_s: numberOf("discontinuityGap"),
    divergence_abs_m: numberOf("divergenceAbs"),
    divergence_rel_percent: numberOf("divergenceRel"),
  };
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
  els.runButton.disabled = isBusy || !(els.gtFile.files.length && els.estFile.files.length && state.evaluateJson);
  els.runButton.textContent = isBusy ? "计算中..." : "运行评估";
}

function renderReport(report) {
  renderMetrics(report);
  renderMessages(report);
  renderCharts(report);
}

function renderMetrics(report) {
  const summary = report.summary || {};
  const ate = report.ate_position_m || {};
  const vertical = report.ate_vertical_m || {};
  const rpe = report.rpe_frame_delta?.translation_m || {};
  const divergence = report.divergence || {};
  const metrics = [
    ["路程", summary.gt_path_length_m, "m"],
    ["ATE RMSE", ate.rmse, "m"],
    ["RPE RMSE", rpe.rmse, "m"],
    ["终点漂移", summary.endpoint_error_m, "m"],
    ["垂直 RMSE", vertical.rmse, "m"],
    ["是否发散", divergence.diverged ? "是" : "否", ""],
    ["GT覆盖率", 100 * (summary.gt_pose_coverage_ratio ?? summary.coverage_ratio), "%"],
    ["Raw 尺度比", summary.raw_path_scale_ratio_est_over_gt, ""],
    ["对齐尺度", report.alignment?.scale, ""],
    ["匹配位姿", summary.matched_poses, ""],
    ["VO匹配率", 100 * summary.est_pose_coverage_ratio, "%"],
    ["耗时", summary.duration_s, "s"],
  ];

  document.getElementById("metrics").innerHTML = metrics.map(([label, value, unit]) => `
    <div class="metric">
      <div class="label">${escapeHtml(label)}</div>
      <div class="value">${formatValue(value, unit)}</div>
    </div>
  `).join("");
}

function renderMessages(report) {
  const messages = [];
  const summary = report.summary || {};
  const rawRatio = summary.raw_path_scale_ratio_est_over_gt;
  const alignMode = report.alignment?.base_mode || report.alignment?.mode;
  if (Number.isFinite(rawRatio) && alignMode === "se3" && (rawRatio < 0.8 || rawRatio > 1.25)) {
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
  const perPose = report.per_pose || [];
  const segmentSummary = report.segment_errors || [];
  const speedBins = report.speed_bins || [];

  const [gtX, gtY, gtZ] = segmentedValues(perPose, ["gt_x_m", "gt_y_m", "gt_z_m"]);
  const [estX, estY, estZ] = segmentedValues(perPose, ["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"]);
  Plotly.newPlot("trajectory3d", [
    { x: gtX, y: gtY, z: gtZ, mode: "lines", type: "scatter3d", name: "Ground truth" },
    { x: estX, y: estY, z: estZ, mode: "lines", type: "scatter3d", name: "VO aligned" },
  ], layout("3D 轨迹", { scene: { xaxis: { title: "x m" }, yaxis: { title: "y m" }, zaxis: { title: "z m" } } }));

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

  const [distGt, gtAlt] = segmentedValues(perPose, ["distance_m", "gt_z_m"]);
  const [distEst, estAlt] = segmentedValues(perPose, ["distance_m", "est_z_aligned_m"]);
  const [distErr, zErr] = segmentedValues(perPose, ["distance_m", "vertical_error_m"]);
  Plotly.newPlot("altitudeDistance", [
    { x: distGt, y: gtAlt, mode: "lines", type: "scatter", name: "GT altitude" },
    { x: distEst, y: estAlt, mode: "lines", type: "scatter", name: "VO altitude" },
    { x: distErr, y: zErr, mode: "lines", type: "scatter", name: "vertical error" },
  ], layout("高度与垂直误差", { xaxis: { title: "distance m" }, yaxis: { title: "z/error m" } }));

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
}

function segmentedValues(rows, columns) {
  if (!rows.length) {
    return columns.map(() => []);
  }
  const outputs = columns.map(() => []);
  let currentSegment = rows[0].segment_id;
  for (const row of rows) {
    if (row.segment_id !== currentSegment) {
      outputs.forEach((items) => items.push(null));
      currentSegment = row.segment_id;
    }
    columns.forEach((column, index) => outputs[index].push(row[column]));
  }
  return outputs;
}

function layout(title, extra = {}) {
  return {
    title,
    height: 380,
    margin: { l: 50, r: 20, t: 45, b: 45 },
    legend: { orientation: "h" },
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
  [els.downloadJson, els.downloadPoseCsv, els.downloadSegmentCsv, els.downloadHtml].forEach((button) => {
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
  const figures = chartIds.map((id) => document.getElementById(id).innerHTML);
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>VO Evaluation Report</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"><\/script>
<style>body{font-family:Arial,sans-serif;margin:28px;color:#20242a}pre{white-space:pre-wrap}.chart{margin:20px 0}</style>
</head><body>
<h1>VO Evaluation Report</h1>
<h2>Metrics JSON</h2>
<pre>${escapeHtml(JSON.stringify(state.report, null, 2))}</pre>
<h2>Visualizations</h2>
${figures.map((html) => `<div class="chart">${html}</div>`).join("\n")}
</body></html>`;
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
