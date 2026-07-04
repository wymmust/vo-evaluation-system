// utils.js — 通用工具函数
// 统一的 escapeHtml 定义（FR-005：消除3处重复），格式化工具，文件名清理

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

export function formatValue(value, unit) {
  if (typeof value === "string") {
    return escapeHtml(value);
  }
  if (!Number.isFinite(value)) {
    return "N/A";
  }
  const text = Number.isInteger(value) ? String(value) : value.toFixed(3);
  return `${text}${unit ? ` ${unit}` : ""}`;
}

export function formatNumber(value) {
  return Number.isFinite(value) ? value.toFixed(2) : "N/A";
}

export function formatPointNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "N/A";
  }
  return number.toFixed(3);
}

export function formatOverlayNumber(value) {
  if (!Number.isFinite(Number(value))) {
    return "N/A";
  }
  const number = Number(value);
  return number.toFixed(3);
}

export function numbersNearlyEqual(left, right, tolerance = 1e-9) {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  return Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && Math.abs(leftNumber - rightNumber) <= tolerance;
}

export function sanitizeFilenamePart(value) {
  return String(value || "")
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function safeJson(value) {
  return JSON.stringify(value).replaceAll("</", "<\\/");
}

export function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(value);
  }
  return String(value).replace(/'/g, "\\\\'");
}

export function valueOf(id) {
  return document.getElementById(id).value;
}

export function numberOf(id) {
  const value = Number(valueOf(id));
  if (!Number.isFinite(value)) {
    throw new Error(`${id} 不是有效数字`);
  }
  return value;
}
