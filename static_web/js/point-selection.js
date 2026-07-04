// point-selection.js — 选点交互（live 版 + ExportPointSelection）
// FR-005: 合并 live 版和 export 版的选点逻辑，ExportPointSelection 供 html-export.js 引用

import { state } from "./state.js";
import {
  PICKABLE_VLOC_CHART_IDS, PICKABLE_VO_CHART_IDS,
  POINT_SELECTION_COLORS, chartIds,
} from "./constants.js";
import { reportEntryMode, chartTitleById } from "./entry-mode.js";
import { escapeHtml, formatPointNumber, numbersNearlyEqual, cssEscape } from "./utils.js";
import { LABELS } from "./labels.js";

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

export function resetPointSelectionState() {
  state.activePointSelectionChartId = null;
  state.focusedPointSelectionId = null;
  state.pointSelectionSequence = 0;
  state.pointSelections = [];
  renderPointSelectionOutput();
  refreshAllPointSelectionTools();
}

export function ensurePointSelectionTools(chartId) {
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
      <button type="button" class="chart-point-tool pick" title="${LABELS.point_selection_pick_title}" aria-label="${LABELS.point_selection_pick_aria}">⌖</button>
      <button type="button" class="chart-point-tool clear" title="${LABELS.point_selection_clear_title}" aria-label="${LABELS.point_selection_clear_aria}">⌫</button>
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

function existingPointSelectionForPoint(chartId, point) {
  const traceName = point?.data?.name || `trace ${Number(point?.curveNumber) + 1}`;
  const timestamp = pointTimestamp(point);
  const x = Number(point?.x);
  const y = Number(point?.y);
  return state.pointSelections.find((selection) => {
    if (selection.chartId !== chartId || selection.traceName !== traceName) {
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
    name: `${LABELS.point_selection_label_prefix} ${selection.order}`,
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
    name: `${LABELS.point_selection_hit_label_prefix} ${selection.order}`,
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

export function clearAllPointSelections() {
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

export function handlePointSelectionKeydown(event) {
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
            <tr><th>${LABELS.point_selection_table_header_trace}</th><th>${LABELS.point_selection_table_header_point}</th><th>${LABELS.point_selection_table_header_timestamp}</th><th>${LABELS.point_selection_table_header_value}</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }).join("");
}

import { els } from "./dom-refs.js";

// ── ExportPointSelection ──
// FR-005: Export 版选点逻辑供 html-export.js 内嵌到离线 HTML 中
// 这是一组纯函数，不依赖 DOM/state，可被序列化嵌入到导出 HTML 的 <script> 中

export const ExportPointSelection = {
  POINT_COLORS: POINT_SELECTION_COLORS,

  numberText(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(3) : escapeHtml(String(value ?? "N/A"));
  },

  exportPointColorMeta(slot) {
    const zeroIndex = Math.max(0, slot - 1);
    const colorIndex = zeroIndex % POINT_SELECTION_COLORS.length;
    const cycle = Math.floor(zeroIndex / POINT_SELECTION_COLORS.length);
    return { color: POINT_SELECTION_COLORS[colorIndex], text: cycle > 0 ? String(cycle) : "" };
  },

  nextExportPointColorSlot(selections) {
    const used = new Set(selections.map((s) => s.colorSlot).filter((slot) => Number.isFinite(Number(slot))));
    let slot = 1;
    while (used.has(slot)) { slot += 1; }
    return slot;
  },

  exportPointTimestamp(point) {
    const custom = Array.isArray(point?.data?.customdata) ? point.data.customdata[point.pointNumber] : undefined;
    const customTimestamp = typeof custom === "object" && custom !== null ? custom.timestamp : custom;
    const timestamp = Number(customTimestamp);
    if (Number.isFinite(timestamp)) { return timestamp; }
    const x = Number(point?.x);
    return Number.isFinite(x) ? x : null;
  },

  exportPointValueText(chartId, point) {
    const x = Number(point?.x);
    const y = Number(point?.y);
    if (chartId === "trajectoryXY") {
      return "north=" + this.numberText(x) + ", east=" + this.numberText(y);
    }
    return this.numberText(y);
  },

  isExportSelectionTrace(trace) {
    return Boolean(trace?.meta?.pointSelectionMarker || trace?.meta?.pointSelectionHitTarget);
  },

  exportSelectionFromMarkerPoint(point, selections) {
    if (!this.isExportSelectionTrace(point?.data)) return null;
    const markerData = Array.isArray(point.data.customdata) ? point.data.customdata[point.pointNumber] : null;
    const selectionId = markerData?.selectionId || point.data?.meta?.selectionId;
    return selections.find((s) => s.id === selectionId) || null;
  },

  exportEventPoints(eventData) {
    return Array.isArray(eventData?.points) ? eventData.points.filter(Boolean) : [];
  },

  firstExportSelectablePlotPoint(eventData) {
    return this.exportEventPoints(eventData).find((point) => !this.isExportSelectionTrace(point.data)) || null;
  },

  numbersClose(left, right) {
    const l = Number(left);
    const r = Number(right);
    return Number.isFinite(l) && Number.isFinite(r) && Math.abs(l - r) <= 1e-9;
  },

  existingExportPointSelectionForPoint(chartId, point, selections) {
    const traceName = point?.data?.name || "trace " + (Number(point?.curveNumber) + 1);
    const timestamp = this.exportPointTimestamp(point);
    const x = Number(point?.x);
    const y = Number(point?.y);
    return selections.find((s) => {
      if (s.chartId !== chartId || s.traceName !== traceName) return false;
      const sameVisiblePoint = this.numbersClose(s.x, x) && this.numbersClose(s.y, y);
      if (Number.isFinite(timestamp) && Number.isFinite(Number(s.timestamp))) {
        return this.numbersClose(s.timestamp, timestamp) && sameVisiblePoint;
      }
      return sameVisiblePoint;
    }) || null;
  },

  focusExportPointSelectionFromEvent(chartId, eventData, selections, state) {
    const points = this.exportEventPoints(eventData);
    for (const point of points) {
      const selection = this.exportSelectionFromMarkerPoint(point, selections);
      if (selection) { state.focusedSelectionId = selection.id; return true; }
    }
    for (const point of points) {
      const selection = this.existingExportPointSelectionForPoint(chartId, point, selections);
      if (selection) { state.focusedSelectionId = selection.id; return true; }
    }
    return false;
  },

  exportSelectionMarkerTrace(selection) {
    return {
      x: [selection.x], y: [selection.y],
      mode: selection.markerText ? "markers+text" : "markers",
      type: "scatter",
      name: "选点 " + selection.order,
      text: selection.markerText ? [selection.markerText] : [""],
      textposition: "middle center",
      textfont: { color: "#ffffff", size: 9, family: "Arial, sans-serif" },
      marker: { color: selection.color, size: 9, symbol: "circle", line: { width: 0 } },
      customdata: [{ selectionId: selection.id, timestamp: selection.timestamp }],
      meta: { pointSelectionMarker: true, selectionId: selection.id },
      xaxis: selection.xaxis, yaxis: selection.yaxis,
      showlegend: false,
      hovertemplate: escapeHtml(selection.traceName) + "<br>timestamp=%{customdata.timestamp:.3f}<br>value=" + escapeHtml(String(selection.value)) + "<extra></extra>",
    };
  },

  exportSelectionHitTargetTrace(selection) {
    return {
      x: [selection.x], y: [selection.y],
      mode: "markers", type: "scatter",
      name: "选点命中 " + selection.order,
      marker: { color: selection.color, size: 24, opacity: 0.04, symbol: "circle", line: { width: 0 } },
      customdata: [{ selectionId: selection.id, timestamp: selection.timestamp }],
      meta: { pointSelectionHitTarget: true, selectionId: selection.id },
      xaxis: selection.xaxis, yaxis: selection.yaxis,
      showlegend: false, hoverinfo: "none",
    };
  },

  exportSelectionMarkerTraceIndices(chartId) {
    const chart = document.getElementById(chartId);
    const data = Array.isArray(chart?.data) ? chart.data : [];
    return data.map((trace, i) => (this.isExportSelectionTrace(trace) ? i : -1)).filter((i) => i >= 0);
  },

  removeExportSelectionMarkerTraces(chartId) {
    const indices = this.exportSelectionMarkerTraceIndices(chartId);
    if (!indices.length || typeof Plotly === "undefined" || typeof Plotly.deleteTraces !== "function") return;
    Plotly.deleteTraces(chartId, indices);
  },

  refreshExportChartSelectionMarkers(chartId, selections) {
    if (!document.getElementById(chartId)) return;
    this.removeExportSelectionMarkerTraces(chartId);
    const chartSelections = selections.filter((s) => s.chartId === chartId);
    if (!chartSelections.length || typeof Plotly === "undefined" || typeof Plotly.addTraces !== "function") return;
    Plotly.addTraces(chartId, chartSelections.flatMap((s) => [this.exportSelectionHitTargetTrace(s), this.exportSelectionMarkerTrace(s)]));
  },

  nearestExportTracePoint(trace, target) {
    const xs = Array.isArray(trace?.x) ? trace.x : [];
    const ys = Array.isArray(trace?.y) ? trace.y : [];
    let bestIndex = -1;
    let bestDiff = Infinity;
    for (let i = 0; i < xs.length; i++) {
      const x = Number(xs[i]);
      const y = Number(ys[i]);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const diff = Math.abs(x - target);
      if (diff < bestDiff) { bestDiff = diff; bestIndex = i; }
    }
    if (bestIndex < 0) return null;
    return { x: Number(xs[bestIndex]), y: Number(ys[bestIndex]), index: bestIndex };
  },

  isExportTextEditingTarget(target) {
    const tag = target?.tagName?.toLowerCase();
    if (!tag) return false;
    if (target?.isContentEditable) return true;
    if (tag === "textarea" || tag === "select") return true;
    if (tag !== "input") return false;
    const type = String(target.type || "text").toLowerCase();
    return !["button", "checkbox", "color", "file", "radio", "range", "reset", "submit"].includes(type);
  },
};

export { isPointSelectableChart, initPointSelection };
function initPointSelection() { /* no-op, tools are created per-chart */ }
