// report_templates.js — 报告模板（ES module export）
// FR-004: 从 globalThis 挥手协议改为 ES module export
// FR-005: 移除重复 escapeHtml，统一使用 js/utils.js 的定义

import { escapeHtml } from "../js/utils.js";

function metricStatusClass(status) {
  if (status === "high") return "rank-high";
  if (status === "warning") return "rank-warning";
  if (status === "good") return "rank-good";
  return "";
}

function defaultFormatValue(value, unit) {
  if (typeof value === "string") {
    return escapeHtml(value);
  }
  if (!Number.isFinite(value)) {
    return "N/A";
  }
  const text = Number.isInteger(value) ? String(value) : value.toFixed(3);
  return `${text}${unit ? ` ${escapeHtml(unit)}` : ""}`;
}

function selectedSetFrom(selected) {
  if (selected instanceof Set) {
    return selected;
  }
  return new Set(selected || []);
}

export function chartDirectoryHtml(options, selected) {
  const selectedSet = selectedSetFrom(selected);
  return (options || []).map((option) => `
      <label class="chart-directory-item">
        <input type="checkbox" data-chart-id="${escapeHtml(option.id)}" ${selectedSet.has(option.id) ? "checked" : ""} />
        <span>${escapeHtml(option.label)}</span>
      </label>
    `).join("");
}

function metricCardHtml(item, index, formatValue) {
  const valueFormatter = formatValue || defaultFormatValue;
  return `
      <div class="metric ${metricStatusClass(item.status)}">
        <div class="metric-top">
          <div class="label">${escapeHtml(item.label)}</div>
          <div class="metric-rank">#${String(index + 1).padStart(2, "0")}</div>
        </div>
        <div class="value">${valueFormatter(item.value, item.unit)}</div>
        <div class="metric-note">${escapeHtml(item.note || "")}</div>
      </div>
    `;
}

export function metricGridHtml(metrics, options = {}) {
  return (metrics || []).map((item, index) => metricCardHtml(item, index, options.formatValue)).join("");
}

export { metricStatusClass };
