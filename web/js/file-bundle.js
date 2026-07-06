// file-bundle.js — 文件选择/打包/上传
// 目录选择、文件映射、缺失文件检查、bundle payload 构建

import { els } from "./dom-refs.js";
import { valueOf } from "./utils.js";

export function requiredBundleFiles(entryMode) {
  const estimateName = entryMode === "vloc" ? "vloc.txt" : "vo.txt";
  const logFiles = entryMode === "vloc" ? [estimateName, "home_point.txt", "calib_raw.yaml"] : [estimateName, "calib_raw.yaml"];
  return {
    data: ["imu.txt"],
    log: logFiles,
  };
}

export function selectedFiles(input) {
  return Array.from(input?.files || []);
}

export function directoryFileMap(input, allowedNames = null) {
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

export function directoryNameFromFiles(files) {
  if (!files.length) {
    return "";
  }
  const relative = files[0].webkitRelativePath || "";
  if (relative.includes("/")) {
    return relative.split("/")[0];
  }
  return files[0].name || "";
}

export function missingBundleFiles() {
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

export async function buildBundlePayload(entryMode) {
  const missing = missingBundleFiles();
  if (missing.length) {
    if ((els.dataDirPath?.value || els.logDirPath?.value || "").trim()) {
      throw new Error(`${LABELS.error_missing_files_in_static_prefix}${missing.join("，")}`);
    }
    throw new Error(`${LABELS.error_missing_files_prefix}${missing.join("，")}`);
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

export function hasLocalPathInputs() {
  return Boolean((els.dataDirPath?.value || "").trim() && (els.logDirPath?.value || "").trim());
}

export function updateDirectoryStatus(kind) {
  const isData = kind === "data";
  const input = isData ? els.dataDirFiles : els.logDirFiles;
  const pathInput = isData ? els.dataDirPath : els.logDirPath;
  const target = isData ? els.dataDirStatus : els.logDirStatus;
  const files = selectedFiles(input);
  if (!files.length) {
    const typedPath = (pathInput?.value || "").trim();
    target.textContent = typedPath ? LABELS.file_path_typed : LABELS.file_unselected;
    return;
  }
  const name = directoryNameFromFiles(files) || (isData ? "data_dir" : "log_dir");
  target.textContent = `${name} · ${files.length} 个文件`;
}

import { LABELS } from "./labels.js";
