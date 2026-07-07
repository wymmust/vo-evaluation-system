// download-utils.js — 下载辅助
// downloadText、downloadBytes、downloadReportJson

import { state } from "./state.js";
import { sanitizeFilenamePart } from "./utils.js";
import { reportEntryMode } from "./entry-mode.js";
import { showMessage } from "./report-render.js";
import { LABELS } from "./labels.js";
import { directoryNameFromFiles, selectedFiles } from "./file-bundle.js";
import { els } from "./dom-refs.js";

export function downloadText(filename, text, mime) {
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

export function downloadBytes(filename, bytes, mime) {
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

export async function downloadReportJson() {
  try {
    const text = JSON.stringify(await fetchReportSlice("full_report"), null, 2);
    downloadText("vo_evaluation_metrics.json", text, "application/json");
  } catch (error) {
    showMessage(`${LABELS.error_export_json_prefix}${error.message}`, "error");
  }
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

async function fetchReportSlice(sliceName) {
  const response = await fetch(`/api/report-slice?slice=${encodeURIComponent(sliceName)}`, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.error || `HTTP ${response.status}`);
  }
  return payload.data;
}

export { evaluationExportFilename, fetchReportSlice };
