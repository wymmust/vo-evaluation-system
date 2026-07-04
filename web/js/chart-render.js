// chart-render.js — 图表渲染调度
// scheduleRenderCharts、renderCharts、purgeChart、purgeUnselectedCharts

import { state } from "./state.js";
import { chartIds } from "./constants.js";
import { reportEntryMode, selectedChartIdsForEntryMode, visibleChartIdsForEntryMode, applyEntryModeChartVisibility } from "./entry-mode.js";
import { ensurePointSelectionTools } from "./point-selection.js";
import { attachCompositeOverlay } from "./composite-overlay.js";

export function scheduleRenderCharts(report) {
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

export function purgeChart(chartId) {
  const node = document.getElementById(chartId);
  if (!node) {
    return;
  }
  if (typeof Plotly !== "undefined" && typeof Plotly.purge === "function") {
    Plotly.purge(chartId);
  }
  node.innerHTML = "";
}

export function purgeUnselectedCharts(entryMode) {
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

import { buildVisualizationFigureSpecs } from "../visualization/figure_specs.js";

function renderCharts(report, onlyChartId = null) {
  const entryMode = reportEntryMode(report);
  applyEntryModeChartVisibility(entryMode);
  const selectedIds = selectedChartIdsForEntryMode(entryMode);
  buildVisualizationFigureSpecs(report, { variant: "live" })
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

export { renderCharts };
