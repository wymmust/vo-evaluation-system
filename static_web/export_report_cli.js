#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const vm = require("vm");

function makeElement() {
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

function loadAppContext(staticWebDir) {
  const elements = new Map();
  const document = {
    body: { appendChild() {} },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement());
      return elements.get(id);
    },
    createElement() {
      return makeElement();
    },
    querySelectorAll() {
      return [];
    },
    addEventListener() {},
  };
  const context = {
    console,
    document,
    window: { location: { protocol: "http:" } },
    TextEncoder,
    Uint8Array,
    DataView,
    Blob: function Blob() {},
    URL: { createObjectURL() { return ""; }, revokeObjectURL() {} },
    Plotly: { newPlot() {}, purge() {}, addTraces() {}, deleteTraces() {} },
  };
  context.globalThis = context;
  const appPath = path.join(staticWebDir, "app.js");
  const appSource = fs.readFileSync(appPath, "utf8").replace(/\ninit\(\);\n/, "\n");
  vm.runInNewContext(appSource, context, { filename: appPath });
  return context;
}

function main() {
  const [, , outputPathArg] = process.argv;
  if (!outputPathArg) {
    throw new Error("usage: export_report_cli.js <output.html>");
  }
  const staticWebDir = __dirname;
  const report = JSON.parse(fs.readFileSync(0, "utf8"));
  const plotlyPath = path.join(staticWebDir, "vendor", "plotly", "plotly-2.35.2.min.js");
  const plotlySource = fs.existsSync(plotlyPath) ? fs.readFileSync(plotlyPath, "utf8") : "";
  const context = loadAppContext(staticWebDir);
  const html = context.buildHtmlReport(report, { plotlySource });
  fs.mkdirSync(path.dirname(path.resolve(outputPathArg)), { recursive: true });
  fs.writeFileSync(outputPathArg, html, "utf8");
}

try {
  main();
} catch (error) {
  console.error(error?.stack || String(error));
  process.exit(1);
}
