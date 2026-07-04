// composite-overlay.js — Composite 浮动 tooltip
// 复合图表的 hover/range overlay 交互

import { escapeHtml, formatOverlayNumber } from "./utils.js";

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

export function ensureCompositeOverlay(id) {
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
  overlay.tooltip.innerHTML = `<strong>${LABELS.composite_timestamp_prefix} ${formatOverlayNumber(payload.timestamp)} s</strong><div>${chips || LABELS.composite_no_data}</div>`;
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
  overlay.tooltip.innerHTML = `<strong>选区 ${formatOverlayNumber(payload.start)}-${formatOverlayNumber(payload.end)} s，${payload.sampleCount} 帧</strong><div>${chips || LABELS.composite_no_data}</div>`;
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

export function attachCompositeOverlay(id, rows, spec) {
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

import { LABELS } from "./labels.js";
