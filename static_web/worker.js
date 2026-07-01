let pyodide = null;
let evaluateVlocBundleJsonLight = null;
let evaluateVoBundleJsonLight = null;
let getReportSliceJson = null;

self.onmessage = async (event) => {
  const { id, type, payload = {} } = event.data || {};
  try {
    if (type === "init") {
      await initPyodideWorker(payload.pyodideIndexUrl);
      postResult(id, true);
      return;
    }
    if (type === "evaluate") {
      ensureReady();
      const result = evaluateBundle(payload);
      postResult(id, result);
      return;
    }
    if (type === "slice") {
      ensureReady();
      const result = getReportSliceJson(payload.sliceName);
      postResult(id, result);
      return;
    }
    throw new Error(`Unknown worker command: ${type}`);
  } catch (error) {
    postError(id, error);
  }
};

async function initPyodideWorker(pyodideIndexUrl) {
  if (pyodide) {
    return;
  }
  if (!pyodideIndexUrl) {
    throw new Error("pyodide_index_url_missing");
  }
  importScripts(`${pyodideIndexUrl}pyodide.js`);
  pyodide = await loadPyodide({ indexURL: pyodideIndexUrl });
  await pyodide.loadPackage(["numpy", "pandas"]);

  const [dataLoaderCode, utilsCode, reportCode, processingCode, runnerCode] = await Promise.all([
    fetchText("./py/vo_eval/data_loader.py"),
    fetchText("./py/vo_eval/utils.py"),
    fetchText("./py/vo_eval/report.py"),
    fetchText("./py/vo_eval/processing.py"),
    fetchText("./py/browser_runner.py"),
  ]);

  pyodide.FS.mkdirTree("/vo_eval");
  pyodide.FS.writeFile("/vo_eval/__init__.py", "");
  pyodide.FS.writeFile("/vo_eval/data_loader.py", dataLoaderCode);
  pyodide.FS.writeFile("/vo_eval/utils.py", utilsCode);
  pyodide.FS.writeFile("/vo_eval/report.py", reportCode);
  pyodide.FS.writeFile("/vo_eval/processing.py", processingCode);
  pyodide.FS.writeFile("/browser_runner.py", runnerCode);
  pyodide.runPython(`
import sys
sys.path.insert(0, "/")
from browser_runner import evaluate_vloc_bundle_json_light, evaluate_vo_bundle_json_light, get_report_slice_json
`);
  evaluateVlocBundleJsonLight = pyodide.globals.get("evaluate_vloc_bundle_json_light");
  evaluateVoBundleJsonLight = pyodide.globals.get("evaluate_vo_bundle_json_light");
  getReportSliceJson = pyodide.globals.get("get_report_slice_json");
}

async function fetchText(url) {
  const cacheBust = `cache_bust=${Date.now()}`;
  const requestUrl = `${url}${url.includes("?") ? "&" : "?"}${cacheBust}`;
  let response;
  try {
    response = await fetch(requestUrl, { cache: "no-store" });
  } catch (error) {
    throw new Error(`local_fetch_failed:${url}:${error.message}`);
  }
  if (!response.ok) {
    throw new Error(`local_fetch_status:${url}:${response.status}`);
  }
  return response.text();
}

function evaluateBundle(payload) {
  const fn = payload.entryMode === "vloc" ? evaluateVlocBundleJsonLight : evaluateVoBundleJsonLight;
  if (!fn) {
    throw new Error("worker_evaluator_missing");
  }
  return fn(
    payload.imuText,
    payload.estimateText,
    payload.homePointText,
    payload.calibRawText,
    payload.configJson,
    payload.imuName,
    payload.estimateName,
    payload.homePointName,
    payload.calibRawName,
    payload.dataDirName,
    payload.logDirName,
  );
}

function ensureReady() {
  if (!pyodide || !evaluateVlocBundleJsonLight || !evaluateVoBundleJsonLight || !getReportSliceJson) {
    throw new Error("worker_not_ready");
  }
}

function postResult(id, result) {
  self.postMessage({ id, ok: true, result });
}

function postError(id, error) {
  self.postMessage({ id, ok: false, error: error?.message || String(error) });
}
