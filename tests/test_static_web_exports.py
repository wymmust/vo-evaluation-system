import base64
import io
import json
import subprocess
import textwrap

from openpyxl import load_workbook


def test_static_html_export_excludes_trajectory_exports_and_xlsx_has_six_sheets():
    script = textwrap.dedent(
        r"""
        const fs = require("fs");
        const vm = require("vm");
        const element = {
          addEventListener() {},
          classList: { add() {}, remove() {} },
          style: {},
          files: [],
          value: "",
          disabled: false,
          hidden: false,
          textContent: "",
        };
        const document = {
          body: { appendChild() {} },
          getElementById() { return element; },
          createElement() { return { ...element, click() {}, remove() {} }; },
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
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);

        const report = {
          summary: { matched_poses: 2 },
          per_pose: [{ timestamp: 1, error_m: 0.1 }],
          trajectory_exports: {
            input_gt_tum: [{ timestamp: 1, tx: 0, ty: 0, tz: 0 }],
            input_vo_tum: [{ timestamp: 1, tx: 1, ty: 0, tz: 0 }],
            filtered_vo_tum: [{ timestamp: 1, tx: 1, ty: 0, tz: 0 }],
            interpolated_gt_tum: [{ timestamp: 1, tx: 0, ty: 0, tz: 0 }],
            sim3_gt_tum: [{ timestamp: 1, tx: 0, ty: 0, tz: 0 }],
            sim3_vo_tum: [{ timestamp: 1, tx: 0, ty: 0, tz: 0 }],
          },
        };
        const sanitized = context.reportForHtmlExport(report);
        const workbook = context.buildTrajectoryWorkbook(report.trajectory_exports);
        process.stdout.write(JSON.stringify({
          sanitized,
          workbookBase64: Buffer.from(workbook).toString("base64"),
        }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)

    assert "trajectory_exports" not in payload["sanitized"]
    assert payload["sanitized"]["summary"]["matched_poses"] == 2
    assert payload["sanitized"]["per_pose"][0]["timestamp"] == 1

    workbook_bytes = base64.b64decode(payload["workbookBase64"])
    workbook = load_workbook(io.BytesIO(workbook_bytes), read_only=True)
    assert workbook.sheetnames == [
        "input_gt_tum",
        "input_vo_tum",
        "filtered_vo_tum",
        "interpolated_gt_tum",
        "sim3_gt_tum",
        "sim3_vo_tum",
    ]
    assert workbook["input_gt_tum"]["A1"].value == "timestamp"
    assert workbook["input_gt_tum"]["A2"].value == 1
