import base64
import io
import importlib.util
import json
import subprocess
import textwrap
from pathlib import Path

from openpyxl import load_workbook


def test_static_directory_entry_ui_uses_vloc_vo_modes_instead_of_legacy_file_formats():
    html = Path("static_web/index.html").read_text()
    assert 'id="entryMode"' in html
    assert 'id="dataDirFiles"' in html
    assert 'id="logDirFiles"' in html
    assert 'id="dataDirButton"' in html
    assert 'id="logDirButton"' in html
    assert 'id="dataDirStatus"' in html
    assert 'id="logDirStatus"' in html
    assert "webkitdirectory" in html
    assert 'id="gtFile"' not in html
    assert 'id="estFile"' not in html
    assert 'id="gtFormat"' not in html
    assert 'id="estFormat"' not in html


def test_streamlit_frontend_defaults_align_with_static_web_directory_flow():
    source = Path("app.py").read_text()
    assert 'st.radio("评估入口", list(EVALUATION_ENTRY_OPTIONS), index=0)' in source
    assert "length_tolerance = st.number_input(" in source
    assert "value=0.05" in source
    assert 'segment_policy_label = st.selectbox("VO重置/大跳变处理", list(SEGMENT_POLICY_OPTIONS), index=1)' in source
    assert 'divergence_abs = st.number_input("发散绝对阈值 m", value=30.0' in source
    assert 'divergence_rel = st.number_input("发散相对阈值 % 路程", value=3.0' in source
    assert "视觉布局与 static_web 保持同一套信息组织" not in source


def test_static_directory_picker_shows_selected_directory_name_in_custom_status():
    script = textwrap.dedent(
        r"""
        const fs = require("fs");
        const vm = require("vm");
        const makeElement = (value = "") => ({
          value,
          files: [],
          disabled: false,
          hidden: false,
          textContent: "",
          innerHTML: "",
          style: {},
          classList: { add() {}, remove() {} },
          addEventListener() {},
          click() { this.clicked = true; },
        });
        const elements = {
          runtimeStatus: makeElement(),
          message: makeElement(),
          runButton: makeElement(),
          entryMode: makeElement("vloc"),
          entryModeHint: makeElement(),
          dataDirFiles: makeElement(),
          logDirFiles: makeElement(),
          dataDirButton: makeElement(),
          logDirButton: makeElement(),
          dataDirStatus: makeElement(),
          logDirStatus: makeElement(),
          downloadJson: makeElement(),
          downloadPoseCsv: makeElement(),
          downloadSegmentCsv: makeElement(),
          downloadWorstCsv: makeElement(),
          downloadConfigJson: makeElement(),
          downloadTrajectoryExcel: makeElement(),
          downloadHtml: makeElement(),
          interpolationPreset: makeElement("0.15"),
          maxInterpolationGap: makeElement("0.15"),
        };
        const document = {
          body: { appendChild() {} },
          getElementById(id) { return elements[id] || makeElement(); },
          createElement() { return { ...makeElement(), remove() {} }; },
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
          Plotly: { newPlot() {}, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);

        elements.dataDirFiles.files = [
          { name: "imu.txt", webkitRelativePath: "data_dir/imu.txt" },
          { name: "extra.txt", webkitRelativePath: "data_dir/extra.txt" },
        ];
        elements.logDirFiles.files = [
          { name: "vloc.txt", webkitRelativePath: "log_dir/vloc.txt" },
        ];

        context.updateDirectoryStatus("data");
        context.updateDirectoryStatus("log");

        process.stdout.write(JSON.stringify({
          dataStatus: elements.dataDirStatus.textContent,
          logStatus: elements.logDirStatus.textContent,
        }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert "data_dir" in payload["dataStatus"]
    assert "2" in payload["dataStatus"]
    assert "log_dir" in payload["logStatus"]
    assert "1" in payload["logStatus"]


def test_static_browser_runner_uses_fixed_bundle_parsers_instead_of_legacy_single_file_loader(tmp_path):
    runner_path = Path("static_web/py/browser_runner.py")
    spec = importlib.util.spec_from_file_location("browser_runner_test", runner_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    imu_text = """ts ts_fcc status flight_mode x y z yaw pitch roll vx vy vz position_reset_count altitude_reset_count heading_reset_count latitude longitude altitude altitude_msl height
10.0 100.0 4194305 3 1 2 3 1.57079632679 0.1 -0.2 0.4 0.5 0.6 0 1 2 31.1 121.2 50 51 5
10.1 100.1 268435457 3 2 3 4 1.67079632679 0.2 -0.3 0.5 0.6 0.7 0 1 2 31.2 121.3 51 52 6
"""
    vloc_text = """ts status num_inliers reset_count x y z yaw pitch roll latitude longitude height
10.0 2 42 0 1.1 2.1 3.1 90 2 -1 31.1 121.2 5
10.1 3 43 1 2.1 3.1 4.1 91 3 -2 31.2 121.3 6
"""
    vo_text = """ts num_inliers x y z yaw pitch roll is_keyframe time_cost reset_count
10.0 50 1.2 2.2 3.2 90 2 -1 1 12.5 0
10.1 51 2.2 3.2 4.2 91 3 -2 0 13.5 1
"""
    home_text = "121.2 31.1 51.0\n"
    calib_text = """%YAML:1.0
---
T_imu_body: [ 1, 0, 0, 0.1, 0, 1, 0, 0.2, 0, 0, 1, 0.3, 0, 0, 0, 1 ]
cam0:
  T_cam_imu: [ 0, -1, 0, 1, 1, 0, 0, 2, 0, 0, 1, 3, 0, 0, 0, 1 ]
"""
    config_json = json.dumps({"segment_lengths_m": [50, 100], "max_interpolation_gap_s": 0.3})

    vloc_report = json.loads(
        module.evaluate_vloc_bundle_json(
            imu_text,
            vloc_text,
            home_text,
            calib_text,
            config_json,
            "imu.txt",
            "vloc.txt",
            "home_point.txt",
            "calib_raw.yaml",
        )
    )
    assert vloc_report["summary"]["matched_poses"] == 2

    vo_report = json.loads(
        module.evaluate_vo_bundle_json(
            imu_text,
            vo_text,
            home_text,
            calib_text,
            config_json,
            "imu.txt",
            "vo.txt",
            "home_point.txt",
            "calib_raw.yaml",
        )
    )
    assert vo_report["summary"]["matched_poses"] == 2


def test_static_python_sources_are_fetched_without_browser_cache():
    app_js = Path("static_web/app.js").read_text()

    assert 'cache: "no-store"' in app_js
    assert "cacheBust" in app_js


def test_static_scale_interval_controls_are_wired_into_config():
    html = Path("static_web/index.html").read_text()
    assert 'id="scaleDeltaValue"' in html
    assert 'id="scaleDeltaUnit"' in html

    script = textwrap.dedent(
        r"""
        const fs = require("fs");
        const vm = require("vm");
        const elements = {
          maxTimeDiff: { value: "0.02" },
          maxInterpolationGap: { value: "0.15" },
          allowExtrapolation: { value: "false" },
          interpolateRotation: { value: "true" },
          timeOffset: { value: "0" },
          rpeDeltaValue: { value: "1" },
          rpeDeltaUnit: { value: "frames" },
          scaleDeltaValue: { value: "100" },
          scaleDeltaUnit: { value: "meters" },
          segmentLengths: { value: "50,100" },
          maxSegments: { value: "10000" },
          segmentStep: { value: "10" },
          lengthTolerance: { value: "0.2" },
          alignment: { value: "sim3" },
          orientationCorrection: { value: "auto" },
          associationMode: { value: "interpolate_gt" },
          discontinuityStep: { value: "100" },
          discontinuityGap: { value: "5" },
          divergenceAbs: { value: "10" },
          divergenceRel: { value: "2" },
          segmentPolicy: { value: "segments" },
        };
        const element = { addEventListener() {}, classList: { add() {}, remove() {} }, style: {}, files: [], value: "" };
        const document = {
          body: { appendChild() {} },
          getElementById(id) { return elements[id] || element; },
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
          Plotly: { newPlot() {}, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);
        process.stdout.write(JSON.stringify(context.buildConfig()));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    config = json.loads(result.stdout)
    assert config["scale_delta_value"] == 100
    assert config["scale_delta_unit"] == "meters"
    assert config["scale_distance_tolerance_ratio"] == 0.05


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
              scale_per_frame: [{ timestamp: 1, local_sim3_scale: 2, scale_available: true }],
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
        "scale_per_frame",
    ]
    assert workbook["input_gt_tum"]["A1"].value == "timestamp"
    assert workbook["input_gt_tum"]["A2"].value == 1
    assert workbook["ate_per_frame"]["B1"].value == "ate_position_m"
    assert workbook["rpe_per_frame"]["B1"].value == "rpe_translation_m"
    assert workbook["scale_per_frame"]["B1"].value == "local_sim3_scale"


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
            scale_per_frame: [
              { timestamp: 0, segment_id: 0, local_sim3_scale: 2, scale_available: true },
              { timestamp: 1, segment_id: 0, local_sim3_scale: 2, scale_available: true },
            ],
          },
        });
        process.stdout.write(JSON.stringify(plots.map((plot) => plot.id)));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    rendered_ids = set(json.loads(result.stdout))
    assert set(expected_ids).issubset(rendered_ids)


def test_static_sim3_scale_chart_uses_local_scale_by_timestamp():
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
          { timestamp: 10, segment_id: 0, local_sim3_scale: 2, scale_available: true },
          { timestamp: 11, segment_id: 0, local_sim3_scale: 2, scale_available: true },
          { timestamp: 20, segment_id: 1, local_sim3_scale: 3, scale_available: true },
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
