#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const staticWebDir = path.resolve(__dirname, "..");

// ── Browser environment mocks ──
// dom-refs.js calls document.getElementById() at module load time, so globalThis
// must have the mocks BEFORE the dynamic import resolves the module chain.

function mockElement() {
  return {
    value: "",
    files: [],
    disabled: false,
    hidden: false,
    textContent: "",
    innerHTML: "",
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    appendChild() {},
    click() {},
    remove() {},
  };
}

globalThis.document = {
  body: { appendChild() {} },
  getElementById() { return mockElement(); },
  createElement() { return mockElement(); },
  querySelectorAll() { return []; },
  addEventListener() {},
};

globalThis.window = {
  location: { protocol: "http:" },
  CSS: {
    escape(value) { return String(value).replace(/'/g, "\\'"); },
  },
};

globalThis.Plotly = { newPlot() {}, purge() {}, addTraces() {}, deleteTraces() {} };
globalThis.URL = { createObjectURL() { return ""; }, revokeObjectURL() {} };
globalThis.Blob = class Blob { constructor() {} };
globalThis.Worker = class Worker { constructor() {} addEventListener() {} postMessage() {} };
globalThis.fetch = async () => ({ ok: false, status: 404, text: async () => "" });

// ── Dynamic import (mocks are on globalThis before import resolves) ──

const { buildHtmlReport } = await import("../js/html-export.js");

// ── Main ──

const [, , outputPathArg] = process.argv;
if (!outputPathArg) {
  throw new Error("usage: export_report_cli.js <output.html>");
}

const report = JSON.parse(fs.readFileSync(0, "utf8"));
const plotlyPath = path.join(staticWebDir, "vendor", "plotly", "plotly-2.35.2.min.js");
const cssPath = path.join(staticWebDir, "css", "style.css");
const reportCssPath = path.join(staticWebDir, "css", "report-export.css");
const plotlySource = fs.existsSync(plotlyPath) ? fs.readFileSync(plotlyPath, "utf8") : "";
const cssSource = fs.existsSync(cssPath) ? fs.readFileSync(cssPath, "utf8") : "";
const reportCssSource = fs.existsSync(reportCssPath) ? fs.readFileSync(reportCssPath, "utf8") : "";

const html = buildHtmlReport(report, { plotlySource, cssSource, reportCssSource });

fs.mkdirSync(path.dirname(path.resolve(outputPathArg)), { recursive: true });
fs.writeFileSync(outputPathArg, html, "utf8");
