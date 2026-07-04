// worker-client.js — Pyodide Worker 通信
// Worker 初始化、消息处理、请求/响应管理

import { state } from "./state.js";
import { PYODIDE_VENDOR_PATH, APP_ASSET_VERSION } from "./constants.js";
import { els } from "./dom-refs.js";
import { LABELS } from "./labels.js";

/** Resolve vendor path to absolute URL from the main page's origin.
 *  Both importScripts() and fetch() inside a Worker resolve relative
 *  paths against the Worker script's own URL, not the main page.
 *  Computing absolute URLs in the main thread avoids that ambiguity. */
const PYODIDE_INDEX_URL = new URL(PYODIDE_VENDOR_PATH, window.location.href).href;

/** Base URL for all static_web resources — passed to the Worker so it
 *  can fetch Python files with absolute URLs instead of relative paths
 *  that would resolve against the Worker's own location. */
const BASE_URL = new URL("./", window.location.href).href;

export async function initPyodide() {
  if (window.location.protocol === "file:") {
    throw new Error("local_file_protocol");
  }
  state.loadingStep = "worker";
  els.status.textContent = LABELS.runtime_loading_worker;
  state.worker = new Worker(`./worker/worker.js?v=${APP_ASSET_VERSION}`);
  state.worker.addEventListener("message", handleWorkerMessage);
  state.worker.addEventListener("error", (event) => {
    rejectPendingWorkerRequests(event.message || "worker_error");
  });
  state.loadingStep = "packages";
  els.status.textContent = LABELS.runtime_loading_packages;
  await workerRequest("init", { pyodideIndexUrl: PYODIDE_INDEX_URL, baseUrl: BASE_URL });
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

export function workerRequest(type, payload = {}) {
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

export async function fetchLocalText(url) {
  let response;
  try {
    response = await fetch(url, { cache: "no-store" });
  } catch (error) {
    throw new Error(`${LABELS.error_cannot_fetch_prefix} ${url}：${error.message || error}`);
  }
  if (!response.ok) {
    throw new Error(`${LABELS.error_cannot_fetch_prefix} ${url}，HTTP 状态码 ${response.status}`);
  }
  return response.text();
}

export function describeRuntimeError(error) {
  const message = error?.message || String(error);
  if (message === "local_file_protocol") {
    return LABELS.error_local_file_protocol;
  }
  if (message.startsWith("local_fetch_failed:")) {
    const [, url] = message.split(":");
    return `${LABELS.error_local_fetch_failed} ${url}。`;
  }
  if (message.startsWith("local_fetch_status:")) {
    const [, url, status] = message.split(":");
    return `${LABELS.error_local_fetch_status} ${url}，HTTP 状态码 ${status}。`;
  }
  if (message.includes("Failed to fetch") && state.loadingStep === "packages") {
    return LABELS.error_fetch_packages;
  }
  if (message.includes("Failed to fetch")) {
    return LABELS.error_fetch_generic;
  }
  return message;
}
