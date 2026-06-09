import base64
import io
import json
import subprocess
import textwrap
from pathlib import Path

from openpyxl import load_workbook


def test_static_format_options_include_vloc_only_for_vo_output():
    html = Path("static_web/index.html").read_text()
    gt_select = html.split('<select id="gtFormat">', 1)[1].split("</select>", 1)[0]
    est_select = html.split('<select id="estFormat">', 1)[1].split("</select>", 1)[0]

    assert 'value="vloc"' not in gt_select
    assert '<option value="vloc">VLOC</option>' in est_select


def test_static_python_sources_are_fetched_without_browser_cache():
    app_js = Path("static_web/app.js").read_text()

    assert 'cache: "no-store"' in app_js
    assert "cacheBust" in app_js


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
              ate_per_frame: [{ timestamp: 1, ate_position_m: 0.1 }],
              rpe_per_frame: [{ timestamp: 1, rpe_translation_m: 0.2, rpe_available: true }],
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
        "ate_per_frame",
        "rpe_per_frame",
    ]
    assert workbook["input_gt_tum"]["A1"].value == "timestamp"
    assert workbook["input_gt_tum"]["A2"].value == 1
    assert workbook["ate_per_frame"]["B1"].value == "ate_position_m"
    assert workbook["rpe_per_frame"]["B1"].value == "rpe_translation_m"


def test_static_visualization_renders_time_series_and_rpe_charts():
    html = Path("static_web/index.html").read_text()
    expected_ids = [
        "seriesXTime",
        "seriesYTime",
        "seriesZTime",
        "seriesYawTime",
        "seriesPitchTime",
        "seriesRollTime",
        "errorXTime",
        "errorYTime",
        "errorZTime",
        "errorYawTime",
        "errorPitchTime",
        "errorRollTime",
        "sim3ScaleTime",
        "rpeTranslationTime",
        "rpeRotationTime",
    ]
    for chart_id in expected_ids:
        assert f'id="{chart_id}"' in html

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
        const plots = [];
        const context = {
          console,
          document,
          window: { location: { protocol: "http:" } },
          TextEncoder,
          Uint8Array,
          DataView,
          Blob: function Blob() {},
          URL: { createObjectURL() { return ""; }, revokeObjectURL() {} },
          Plotly: { newPlot(id, data, layout) { plots.push({ id, data, layout }); }, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);
        const perPose = [0, 1, 2].map((index) => ({
          timestamp: index,
          segment_id: 0,
          gt_x_m: index,
          gt_y_m: index + 1,
          gt_z_m: index + 2,
          est_x_aligned_m: index + 0.1,
          est_y_aligned_m: index + 1.1,
          est_z_aligned_m: index + 2.1,
          x_error_m: 0.1,
          y_error_m: 0.1,
          z_error_m: 0.1,
          gt_yaw_deg: index,
          gt_pitch_deg: index + 2,
          gt_roll_deg: index + 4,
          est_yaw_aligned_deg: index + 0.2,
          est_pitch_aligned_deg: index + 2.2,
          est_roll_aligned_deg: index + 4.2,
          yaw_error_signed_deg: 0.2,
          pitch_error_signed_deg: 0.2,
          roll_error_signed_deg: 0.2,
          distance_m: index,
          error_m: 0.1,
          horizontal_error_m: 0.1,
          vertical_error_m: 0.1,
        }));
        context.renderCharts({
          per_pose: perPose,
          segment_errors: [],
          speed_bins: [],
          trajectory_exports: {
            sim3_vo_tum: [
              { timestamp: 0, segment_id: 0, sim3_scale: 2 },
              { timestamp: 1, segment_id: 0, sim3_scale: 2 },
              { timestamp: 2, segment_id: 0, sim3_scale: 2 },
            ],
            rpe_per_frame: [
              { timestamp: 0, rpe_translation_m: 0.3, rpe_rotation_deg: 1.1, rpe_available: true },
              { timestamp: 1, rpe_translation_m: 0.4, rpe_rotation_deg: 1.2, rpe_available: true },
            ],
          },
        });
        process.stdout.write(JSON.stringify(plots.map((plot) => plot.id)));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    rendered_ids = set(json.loads(result.stdout))
    assert set(expected_ids).issubset(rendered_ids)


def test_static_sim3_scale_chart_uses_exported_scale_by_timestamp():
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
        const plots = [];
        const context = {
          console,
          document,
          window: { location: { protocol: "http:" } },
          TextEncoder,
          Uint8Array,
          DataView,
          Blob: function Blob() {},
          URL: { createObjectURL() { return ""; }, revokeObjectURL() {} },
          Plotly: { newPlot(id, data, layout) { plots.push({ id, data, layout }); }, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);
        context.renderSim3ScaleTimeChart("sim3ScaleTime", [
          { timestamp: 10, segment_id: 0, sim3_scale: 2 },
          { timestamp: 11, segment_id: 0, sim3_scale: 2 },
          { timestamp: 20, segment_id: 1, sim3_scale: 3 },
        ], {});
        process.stdout.write(JSON.stringify({ x: plots[0].data[0].x, y: plots[0].data[0].y }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == {"x": [10, 11, None, 20], "y": [2, 2, None, 3]}


def test_static_angle_time_series_unwraps_180_degree_boundary():
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
        const plots = [];
        const context = {
          console,
          document,
          window: { location: { protocol: "http:" } },
          TextEncoder,
          Uint8Array,
          DataView,
          Blob: function Blob() {},
          URL: { createObjectURL() { return ""; }, revokeObjectURL() {} },
          Plotly: { newPlot(id, data, layout) { plots.push({ id, data, layout }); }, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);
        context.renderGtVoTimeChart("seriesRollTime", [
          { timestamp: 0, segment_id: 0, gt_roll_deg: 0, est_roll_aligned_deg: 179 },
          { timestamp: 1, segment_id: 0, gt_roll_deg: 1, est_roll_aligned_deg: -179 },
          { timestamp: 2, segment_id: 0, gt_roll_deg: 2, est_roll_aligned_deg: 178 },
        ], { title: "Roll", gt: "gt_roll_deg", est: "est_roll_aligned_deg", unit: "deg", unwrap: true });
        process.stdout.write(JSON.stringify(plots[0].data[1].y));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [179, 181, 178]


def test_static_angle_error_time_series_unwraps_180_degree_boundary():
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
        const plots = [];
        const context = {
          console,
          document,
          window: { location: { protocol: "http:" } },
          TextEncoder,
          Uint8Array,
          DataView,
          Blob: function Blob() {},
          URL: { createObjectURL() { return ""; }, revokeObjectURL() {} },
          Plotly: { newPlot(id, data, layout) { plots.push({ id, data, layout }); }, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);
        context.renderErrorTimeChart("errorRollTime", [
          { timestamp: 0, segment_id: 0, roll_error_signed_deg: 179 },
          { timestamp: 1, segment_id: 0, roll_error_signed_deg: -179 },
          { timestamp: 2, segment_id: 0, roll_error_signed_deg: 178 },
        ], { title: "Roll error", field: "roll_error_signed_deg", unit: "deg", unwrap: true });
        process.stdout.write(JSON.stringify(plots[0].data[0].y));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [179, 181, 178]
