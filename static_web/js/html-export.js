// html-export.js — HTML 报告导出（含内嵌选点交互 JS）
// buildHtmlReport、reportForHtmlExport、downloadHtmlReport
// ExportPointSelection 从 point-selection.js 导入而非内嵌重复代码（FR-005）

import { state } from "./state.js";
import { PLOTLY_SCRIPT_URL, VLOC_CHART_OPTIONS, VO_CHART_OPTIONS, POINT_SELECTION_COLORS } from "./constants.js";
import { fetchLocalText } from "./worker-client.js";
import { reportEntryMode } from "./entry-mode.js";
import { metricItems } from "./metrics.js";
import { orientationCorrectionLabel } from "./metrics.js";
import { ExportPointSelection } from "./point-selection.js";
import { downloadText } from "./download-utils.js";
import { evaluationExportFilename } from "./download-utils.js";
import { escapeHtml, formatValue, safeJson } from "./utils.js";
import { showMessage } from "./report-render.js";
import { LABELS } from "./labels.js";

import { buildVisualizationFigureSpecs } from "../visualization/figure_specs.js";
import { chartDirectoryHtml, metricGridHtml } from "../visualization/report_templates.js";

export function buildHtmlReport(sourceReport = state.report || {}, options = {}) {
  const report = reportForHtmlExport(sourceReport || {});
  const entryMode = reportEntryMode(report);
  const isVloc = entryMode === "vloc";
  const title = isVloc ? LABELS.html_report_title_vloc : LABELS.html_report_title_vo;
  const summaryTitle = isVloc ? LABELS.html_report_summary_title_vloc : LABELS.html_report_summary_title_vo;
  const kicker = isVloc ? LABELS.html_report_kicker_vloc : LABELS.html_report_kicker_vo;
  const metrics = metricItems(report);
  const figures = buildVisualizationFigureSpecs(report, { variant: "export" });
  const plotlyScript = options.plotlySource
    ? `<script>${options.plotlySource.replaceAll("</script", "<\\/script")}<\/script>`
    : `<script src="${escapeHtml(PLOTLY_SCRIPT_URL)}"><\/script>`;
  const cssSource = `${options.cssSource || ""}\n${options.reportCssSource || ""}`.replaceAll("</style", "<\\/style");
  const chartOptions = isVloc ? VLOC_CHART_OPTIONS : VO_CHART_OPTIONS;
  const selectedIds = new Set(figures.map((figure) => figure.id));
  const chartDirectory = chartDirectoryHtml(
    chartOptions.filter((option) => selectedIds.has(option.id)),
    selectedIds,
  );
  const figureHtml = figures.map((figure) => `
    <section class="chart-card" data-chart-id="${escapeHtml(figure.id)}">
      <div class="chart-header">
        <div>
          <div class="chart-kicker">${escapeHtml(figure.pickable ? LABELS.html_report_selectable_label : LABELS.html_report_chart_label)}</div>
          <h2>${escapeHtml(figure.label)}</h2>
        </div>
        ${figure.pickable ? `<div class="chart-tools"><button type="button" data-action="select" data-chart-id="${escapeHtml(figure.id)}">${LABELS.html_report_select_point}</button><button type="button" data-action="clear" data-chart-id="${escapeHtml(figure.id)}">${LABELS.html_report_clear_point}</button></div>` : ""}
      </div>
      <div id="${escapeHtml(figure.id)}" class="chart export-plot" style="height:${Number(figure.layout?.height || 520)}px;width:100%;"></div>
    </section>
  `).join("");

  // ── ExportPointSelection inline script ──
  // FR-005: 使用 ExportPointSelection 的函数定义而非复制重复代码
  const eps = ExportPointSelection;
  const exportScript = `
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
    if (focusExportPointSelectionFromEvent(figure.id, eventData)) return;
    if (window.__VO_ACTIVE_CHART__ === figure.id) recordPointSelection(figure, eventData);
  });
  node.on("plotly_hover", (eventData) => focusExportPointSelectionFromEvent(figure.id, eventData));
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
  if (!crosshair) { crosshair = document.createElement("div"); crosshair.id = crosshairId; crosshair.className = "composite-crosshair"; plot.appendChild(crosshair); }
  let tooltip = document.getElementById(tooltipId);
  if (!tooltip) { tooltip = document.createElement("div"); tooltip.id = tooltipId; tooltip.className = "composite-floating-tooltip"; plot.appendChild(tooltip); }
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
  overlay.tooltip.innerHTML = "<strong>" + ${safeJson(LABELS.html_report_composite_timestamp_prefix)} + " " + numberText(timestamp) + " s</strong><div>" + exportAllHoverChips(chartId, timestamp) + "</div>";
  positionExportTooltip(overlay.tooltip, overlay.plot, mouse);
  overlay.tooltip.style.display = "block";
}
function exportMousePosition(eventData, plot) {
  const event = eventData?.event;
  const rect = plot.getBoundingClientRect ? plot.getBoundingClientRect() : { left: 0, top: 0 };
  return { x: Number.isFinite(Number(event?.clientX)) ? Number(event.clientX) - rect.left : 24, y: Number.isFinite(Number(event?.clientY)) ? Number(event.clientY) - rect.top : 24 };
}
function exportCrosshairX(point, mouseX) {
  const axis = point?.xaxis;
  if (axis && typeof axis.l2p === "function") { const axisOffset = Number(axis._offset || 0); const axisPixel = Number(axis.l2p(point.x)); if (Number.isFinite(axisPixel)) { return axisOffset + axisPixel; } }
  return Number.isFinite(Number(mouseX)) ? Number(mouseX) : 0;
}
function exportAllHoverChips(chartId, timestamp) {
  const figure = window.__VO_EXPORT_FIGURES__.find((item) => item.id === chartId);
  const target = Number(timestamp);
  if (!figure || !Number.isFinite(target)) return ${safeJson(LABELS.html_report_no_data)};
  const chips = [];
  for (const trace of figure.data || []) {
    if (trace?.type === "scatter3d" || trace?.meta?.pointSelectionMarker || trace?.meta?.pointSelectionHitTarget) continue;
    const point = nearestExportTracePoint(trace, target);
    if (!point) continue;
    chips.push('<span class="metric-chip"><strong>' + escapeHtml(trace.name || "trace") + '</strong><span class="metric-chip-value">' + numberText(point.y) + '</span></span>');
  }
  return chips.join("") || ${safeJson(LABELS.html_report_no_data)};
}
function nearestExportTracePoint(trace, target) {
  const xs = Array.isArray(trace?.x) ? trace.x : [];
  const ys = Array.isArray(trace?.y) ? trace.y : [];
  let bestIndex = -1; let bestDiff = Infinity;
  for (let index = 0; index < xs.length; index += 1) { const x = Number(xs[index]); const y = Number(ys[index]); if (!Number.isFinite(x) || !Number.isFinite(y)) continue; const diff = Math.abs(x - target); if (diff < bestDiff) { bestDiff = diff; bestIndex = index; } }
  if (bestIndex < 0) return null;
  return { x: Number(xs[bestIndex]), y: Number(ys[bestIndex]), index: bestIndex };
}
function positionExportTooltip(tooltip, plot, mouse) {
  const tooltipWidth = 380; const tooltipHeight = 190;
  const plotWidth = Number(plot.clientWidth || 0); const plotHeight = Number(plot.clientHeight || 0);
  const preferRight = mouse.x + tooltipWidth + 18 <= plotWidth;
  const left = preferRight ? mouse.x + 14 : Math.max(8, mouse.x - tooltipWidth - 14);
  const top = Math.max(8, Math.min(mouse.y + 14, Math.max(8, plotHeight - tooltipHeight)));
  tooltip.style.left = Math.round(left) + "px"; tooltip.style.top = Math.round(top) + "px";
}
function hideExportCompositeOverlay(chartId) {
  const crosshair = document.getElementById(chartId + "Crosshair");
  const tooltip = document.getElementById(chartId + "Tooltip");
  if (crosshair) crosshair.style.display = "none";
  if (tooltip) tooltip.style.display = "none";
}
function setChartVisible(chartId, visible) { const card = document.querySelector(".chart-card[data-chart-id='" + cssEscape(chartId) + "']"); if (card) card.hidden = !visible; }
function setAllChartsVisible(visible) { document.querySelectorAll("#chartDirectory input").forEach((input) => { input.checked = visible; setChartVisible(input.dataset.chartId, visible); }); }
function togglePointMode(chartId) { window.__VO_ACTIVE_CHART__ = window.__VO_ACTIVE_CHART__ === chartId ? null : chartId; refreshAllExportPointModeStates(); }
function recordPointSelection(figure, eventData) {
  const point = firstExportSelectablePlotPoint(eventData);
  if (!point) return;
  window.__VO_EXPORT_SELECTION_SEQUENCE__ += 1;
  const order = window.__VO_EXPORT_SELECTION_SEQUENCE__;
  const colorSlot = nextExportPointColorSlot();
  const colorMeta = exportPointColorMeta(colorSlot);
  const traceName = point.data?.name || "trace " + (Number(point.curveNumber) + 1);
  const selection = { id: "p" + Date.now() + "_" + order, order, colorSlot, chartId: figure.id, chartTitle: figure.label, traceName, timestamp: exportPointTimestamp(point), value: exportPointValueText(figure.id, point), color: colorMeta.color, markerText: colorMeta.text, x: Number(point.x), y: Number(point.y), xaxis: point.data?.xaxis || "x", yaxis: point.data?.yaxis || "y" };
  window.__VO_EXPORT_SELECTIONS__.push(selection);
  window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = selection.id;
  refreshExportChartSelectionMarkers(figure.id);
  renderPointSelectionOutput();
}
function exportPointColorMeta(slot) { const zeroIndex = Math.max(0, slot - 1); const colorIndex = zeroIndex % POINT_COLORS.length; const cycle = Math.floor(zeroIndex / POINT_COLORS.length); return { color: POINT_COLORS[colorIndex], text: cycle > 0 ? String(cycle) : "" }; }
function nextExportPointColorSlot() { const used = new Set(window.__VO_EXPORT_SELECTIONS__.map((s) => s.colorSlot).filter((slot) => Number.isFinite(Number(slot)))); let slot = 1; while (used.has(slot)) { slot += 1; } return slot; }
function refreshExportPointModeState(chartId) { const card = document.querySelector(".chart-card[data-chart-id='" + cssEscape(chartId) + "']"); if (card) { card.classList.toggle("point-selection-active", card.dataset.chartId === window.__VO_ACTIVE_CHART__); } }
function refreshAllExportPointModeStates() { document.querySelectorAll(".chart-card").forEach((card) => { card.classList.toggle("point-selection-active", card.dataset.chartId === window.__VO_ACTIVE_CHART__); }); }
function exportSelectionMarkerTrace(selection) { return { x: [selection.x], y: [selection.y], mode: selection.markerText ? "markers+text" : "markers", type: "scatter", name: "选点 " + selection.order, text: selection.markerText ? [selection.markerText] : [""], textposition: "middle center", textfont: { color: "#ffffff", size: 9, family: "Arial, sans-serif" }, marker: { color: selection.color, size: 9, symbol: "circle", line: { width: 0 } }, customdata: [{ selectionId: selection.id, timestamp: selection.timestamp }], meta: { pointSelectionMarker: true, selectionId: selection.id }, xaxis: selection.xaxis, yaxis: selection.yaxis, showlegend: false, hovertemplate: escapeHtml(selection.traceName) + "<br>timestamp=%{customdata.timestamp:.3f}<br>value=" + escapeHtml(String(selection.value)) + "<extra></extra>" }; }
function exportSelectionHitTargetTrace(selection) { return { x: [selection.x], y: [selection.y], mode: "markers", type: "scatter", name: "选点命中 " + selection.order, marker: { color: selection.color, size: 24, opacity: 0.04, symbol: "circle", line: { width: 0 } }, customdata: [{ selectionId: selection.id, timestamp: selection.timestamp }], meta: { pointSelectionHitTarget: true, selectionId: selection.id }, xaxis: selection.xaxis, yaxis: selection.yaxis, showlegend: false, hoverinfo: "none" }; }
function isExportSelectionTrace(trace) { return Boolean(trace?.meta?.pointSelectionMarker || trace?.meta?.pointSelectionHitTarget); }
function exportSelectionFromMarkerPoint(point) { if (!isExportSelectionTrace(point?.data)) return null; const markerData = Array.isArray(point.data.customdata) ? point.data.customdata[point.pointNumber] : null; const selectionId = markerData?.selectionId || point.data?.meta?.selectionId; return window.__VO_EXPORT_SELECTIONS__.find((s) => s.id === selectionId) || null; }
function exportPointTimestamp(point) { const custom = Array.isArray(point?.data?.customdata) ? point.data.customdata[point.pointNumber] : undefined; const customTimestamp = typeof custom === "object" && custom !== null ? custom.timestamp : custom; const timestamp = Number(customTimestamp); if (Number.isFinite(timestamp)) { return timestamp; } const x = Number(point?.x); return Number.isFinite(x) ? x : null; }
function exportPointValueText(chartId, point) { const x = Number(point?.x); const y = Number(point?.y); if (chartId === "trajectoryXY") { return "north=" + numberText(x) + ", east=" + numberText(y); } return numberText(y); }
function existingExportPointSelectionForPoint(chartId, point) { const traceName = point?.data?.name || "trace " + (Number(point?.curveNumber) + 1); const timestamp = exportPointTimestamp(point); const x = Number(point?.x); const y = Number(point?.y); return window.__VO_EXPORT_SELECTIONS__.find((s) => { if (s.chartId !== chartId || s.traceName !== traceName) return false; const sameVisiblePoint = numbersClose(s.x, x) && numbersClose(s.y, y); if (Number.isFinite(timestamp) && Number.isFinite(Number(s.timestamp))) { return numbersClose(s.timestamp, timestamp) && sameVisiblePoint; } return sameVisiblePoint; }) || null; }
function focusExportPointSelectionFromEvent(chartId, eventData) { const points = exportEventPoints(eventData); for (const point of points) { const selection = exportSelectionFromMarkerPoint(point); if (selection) { window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = selection.id; return true; } } for (const point of points) { const selection = existingExportPointSelectionForPoint(chartId, point); if (selection) { window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = selection.id; return true; } } return false; }
function exportEventPoints(eventData) { return Array.isArray(eventData?.points) ? eventData.points.filter(Boolean) : []; }
function firstExportSelectablePlotPoint(eventData) { return exportEventPoints(eventData).find((point) => !isExportSelectionTrace(point.data)) || null; }
function numbersClose(left, right) { const l = Number(left); const r = Number(right); return Number.isFinite(l) && Number.isFinite(r) && Math.abs(l - r) <= 1e-9; }
function exportSelectionMarkerTraceIndices(chartId) { const chart = document.getElementById(chartId); const data = Array.isArray(chart?.data) ? chart.data : []; return data.map((trace, i) => (isExportSelectionTrace(trace) ? i : -1)).filter((i) => i >= 0); }
function removeExportSelectionMarkerTraces(chartId) { const indices = exportSelectionMarkerTraceIndices(chartId); if (!indices.length || typeof Plotly === "undefined" || typeof Plotly.deleteTraces !== "function") return; Plotly.deleteTraces(chartId, indices); }
function refreshExportChartSelectionMarkers(chartId) { if (!document.getElementById(chartId)) return; removeExportSelectionMarkerTraces(chartId); const selections = window.__VO_EXPORT_SELECTIONS__.filter((s) => s.chartId === chartId); if (!selections.length || typeof Plotly === "undefined" || typeof Plotly.addTraces !== "function") return; Plotly.addTraces(chartId, selections.flatMap((s) => [exportSelectionHitTargetTrace(s), exportSelectionMarkerTrace(s)])); }
function refreshAllExportSelectionMarkers() { for (const figure of window.__VO_EXPORT_FIGURES__) { refreshExportChartSelectionMarkers(figure.id); } }
function clearChartSelections(chartId) { window.__VO_EXPORT_SELECTIONS__ = window.__VO_EXPORT_SELECTIONS__.filter((s) => s.chartId !== chartId); if (window.__VO_ACTIVE_CHART__ === chartId) { window.__VO_ACTIVE_CHART__ = null; } if (!window.__VO_EXPORT_SELECTIONS__.some((s) => s.id === window.__VO_EXPORT_FOCUSED_SELECTION_ID__)) { window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = null; } refreshExportChartSelectionMarkers(chartId); refreshExportPointModeState(chartId); renderPointSelectionOutput(); }
function clearAllPointSelections() { window.__VO_EXPORT_SELECTIONS__ = []; window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = null; window.__VO_ACTIVE_CHART__ = null; window.__VO_EXPORT_SELECTION_SEQUENCE__ = 0; refreshAllExportSelectionMarkers(); refreshAllExportPointModeStates(); renderPointSelectionOutput(); }
function deleteFocusedExportPointSelection() { const target = window.__VO_EXPORT_SELECTIONS__.find((s) => s.id === window.__VO_EXPORT_FOCUSED_SELECTION_ID__); if (!target) return; window.__VO_EXPORT_SELECTIONS__ = window.__VO_EXPORT_SELECTIONS__.filter((s) => s.id !== target.id); window.__VO_EXPORT_FOCUSED_SELECTION_ID__ = null; refreshExportChartSelectionMarkers(target.chartId); renderPointSelectionOutput(); }
function isExportTextEditingTarget(target) { const tag = target?.tagName?.toLowerCase(); if (!tag) return false; if (target?.isContentEditable) return true; if (tag === "textarea" || tag === "select") return true; if (tag !== "input") return false; const type = String(target.type || "text").toLowerCase(); return !["button", "checkbox", "color", "file", "radio", "range", "reset", "submit"].includes(type); }
function handleExportPointSelectionKeydown(event) { if (event.key !== "Delete" && event.key !== "Backspace") return; if (isExportTextEditingTarget(event.target)) return; if (window.__VO_EXPORT_FOCUSED_SELECTION_ID__) { event.preventDefault?.(); deleteFocusedExportPointSelection(); } }
function renderPointSelectionOutput() { const section = document.getElementById("pointSelectionOutputSection"); const output = document.getElementById("pointSelectionOutput"); const selections = window.__VO_EXPORT_SELECTIONS__; section.hidden = selections.length === 0; if (!selections.length) { output.innerHTML = ""; return; } const chartIds = [...new Set(selections.map((s) => s.chartId))]; output.innerHTML = chartIds.map((chartId) => { const rows = selections.filter((s) => s.chartId === chartId); return '<div class="point-selection-card"><h3>' + escapeHtml(rows[0].chartTitle) + '</h3><table class="point-selection-table"><thead><tr><th>' + ${safeJson(LABELS.point_selection_table_header_trace)} + '</th><th>' + ${safeJson(LABELS.point_selection_table_header_point)} + '</th><th>' + ${safeJson(LABELS.point_selection_table_header_timestamp)} + '</th><th>' + ${safeJson(LABELS.point_selection_table_header_value)} + '</th></tr></thead><tbody>' + rows.map((s) => '<tr><td>' + escapeHtml(s.traceName) + '</td><td><span class="selection-point-token" style="background:' + s.color + '">' + escapeHtml(s.markerText) + '</span></td><td>' + numberText(s.timestamp) + '</td><td>' + numberText(s.value) + '</td></tr>').join("") + '</tbody></table></div>'; }).join(""); }
function numberText(value) { const number = Number(value); return Number.isFinite(number) ? number.toFixed(3) : escapeHtml(String(value ?? "N/A")); }
function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char])); }
function cssEscape(value) { if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value); return String(value).replace(/'/g, "\\\\\\'"); }
initExportPage();
`;

  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>${escapeHtml(title)}</title>
${plotlyScript}
<style>${cssSource}</style>
</head><body>
<header class="topbar">
  <div>
    <h1>${escapeHtml(title)}</h1>
    <p>${LABELS.html_report_offline_hint}</p>
  </div>
  <span class="offline-mode-pill">${escapeHtml(kicker)}</span>
</header>
<main class="layout" data-entry-mode="${escapeHtml(entryMode)}">
  <aside class="controls">
    <section>
      <h2>${LABELS.html_report_chart_directory_title}</h2>
      <p class="section-hint">${LABELS.html_report_chart_directory_hint}</p>
      <div id="chartDirectory" class="chart-directory-list">${chartDirectory}</div>
      <div class="chart-directory-actions">
        <button type="button" id="selectAllCharts">${LABELS.html_report_select_all}</button>
        <button type="button" id="clearCharts">${LABELS.html_report_clear_charts}</button>
      </div>
    </section>
    <section id="pointSelectionOutputSection" hidden>
      <h2>${LABELS.html_report_point_output_title}</h2>
      <p class="section-hint">${LABELS.html_report_point_output_hint}</p>
      <div id="pointSelectionOutput" class="point-selection-output"></div>
      <button type="button" id="clearAllPointSelections" class="clear-point-selections">${LABELS.point_selection_clear_all}</button>
    </section>
  </aside>
  <section class="content">
    <section class="panel">
      <div class="section-head">
        <div>
          <div class="section-kicker">${escapeHtml(isVloc ? LABELS.summary_kicker_vloc : LABELS.summary_kicker_vo)}</div>
        <h2>${escapeHtml(summaryTitle)}</h2>
        </div>
      </div>
      <div class="metric-grid">${metricGridHtml(metrics, { formatValue })}</div>
    </section>
    <section class="panel">
      <div class="section-head">
        <div>
          <div class="section-kicker">${escapeHtml(isVloc ? LABELS.visual_kicker_vloc : LABELS.visual_kicker_vo)}</div>
        <h2>${escapeHtml(isVloc ? LABELS.visual_title_vloc : LABELS.visual_title_vo)}</h2>
        </div>
      </div>
      <div class="chart-grid">${figureHtml || `<div class="empty-state">${LABELS.html_report_no_charts}</div>`}</div>
    </section>
  </section>
</main>
<script>
${exportScript}
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

export { reportForHtmlExport };

export async function downloadHtmlReport() {
  try {
    const [plotlySource, cssSource, reportCssSource] = await Promise.all([
      fetchLocalText(PLOTLY_SCRIPT_URL),
      fetchLocalText("./css/style.css"),
      fetchLocalText("./css/report-export.css"),
    ]);
    downloadText(evaluationExportFilename("evaluation_report", "html"), buildHtmlReport(state.report || {}, { plotlySource, cssSource, reportCssSource }), "text/html");
  } catch (error) {
    showMessage(`${LABELS.error_export_html_prefix}${error.message}`, "error");
  }
}
