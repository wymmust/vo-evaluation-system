import base64
import io
import importlib.util
import json
import subprocess
import textwrap
from pathlib import Path

from openpyxl import load_workbook


def test_static_browser_evaluator_exports_new_vloc_summary_metrics():
    source = Path("static_web/py/evaluator.py").read_text()
    assert "mean_error_pos_xy" in source
    assert "mean_error_pos_z" in source
    assert "mean_error_euler" in source
    assert "max_error_pos_xy" in source
    assert "max_error_pos_z" in source
    assert "max_error_euler" in source


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
    assert 'id="positionCompareComposite"' in html
    assert 'id="attitudeCompareComposite"' in html
    assert 'id="positionErrorComposite"' in html
    assert 'id="attitudeErrorComposite"' in html
    assert 'id="evaluationParametersSection" data-entry-hide="vloc"' in html
    assert 'id="seriesXTime"' not in html

    css = Path("static_web/style.css").read_text()
    assert "[hidden]" in css
    assert "display: none !important" in css


def test_static_dead_report_and_time_series_helpers_are_removed():
    source = Path("static_web/app.js").read_text()
    removed_names = [
        "associationLabel",
        "renderGtVoTimeChart",
        "renderErrorTimeChart",
        "reportSubtitle",
        "reportOverallStatus",
        "buildReportMetricCards",
        "reportMetricCardHtml",
        "buildReportFindings",
        "reportFindingHtml",
        "buildSegmentSummaryRows",
    ]
    for name in removed_names:
        assert f"function {name}" not in source


def test_streamlit_frontend_defaults_align_with_static_web_directory_flow():
    source = Path("app.py").read_text()
    assert 'st.radio("评估入口", list(EVALUATION_ENTRY_OPTIONS), index=0)' in source
    assert 'if entry_mode == "vloc":' in source
    assert 'alignment="none"' in source
    assert 'orientation_correction="none"' in source
    assert 'association_mode="interpolate_gt"' in source
    assert 'max_interpolation_gap_s=1.0' in source
    assert "length_tolerance = st.number_input(" in source
    assert "value=0.05" in source
    assert 'segment_policy_label = st.selectbox("VO重置/大跳变处理", list(SEGMENT_POLICY_OPTIONS), index=1)' in source
    assert 'segment_policy_label = "按VO时间戳统一评估（推荐）"' in source
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


def test_static_vloc_mode_hides_transform_controls_and_uses_fixed_sync_defaults():
    html = Path("static_web/index.html").read_text()
    assert 'id="modeAndAlignmentSection"' in html
    assert 'data-entry-hide="vloc"' in html

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
          click() {},
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
          maxTimeDiff: makeElement("0.02"),
          allowExtrapolation: makeElement("false"),
          interpolateRotation: makeElement("true"),
          timeOffset: makeElement("2.0"),
          rpeDeltaValue: makeElement("1"),
          rpeDeltaUnit: makeElement("frames"),
          scaleDeltaValue: makeElement("100"),
          scaleDeltaUnit: makeElement("meters"),
          segmentLengths: makeElement("50,100"),
          maxSegments: makeElement("10000"),
          segmentStep: makeElement("10"),
          lengthTolerance: makeElement("0.05"),
          alignment: makeElement("sim3"),
          orientationCorrection: makeElement("auto"),
          associationMode: makeElement("nearest"),
          discontinuityStep: makeElement("100"),
          discontinuityGap: makeElement("5"),
          divergenceAbs: makeElement("10"),
          divergenceRel: makeElement("2"),
          segmentPolicy: makeElement("segments"),
          modeAndAlignmentSection: makeElement(),
        };
        const hiddenNodes = [
          { dataset: { entryHide: "vloc" }, hidden: false },
          { dataset: { entryHide: "vo" }, hidden: false },
        ];
        const document = {
          body: { appendChild() {} },
          getElementById(id) { return elements[id] || makeElement(); },
          createElement() { return { ...makeElement(), remove() {} }; },
          querySelectorAll(selector) {
            if (selector === "[data-entry-hide]") return hiddenNodes;
            return [];
          },
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
        context.updateEntryModeUi();
        process.stdout.write(JSON.stringify({
          config: context.buildConfig(),
          hiddenStates: hiddenNodes.map((node) => node.hidden),
          sectionHidden: elements.modeAndAlignmentSection.hidden,
        }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["config"]["alignment"] == "none"
    assert payload["config"]["orientation_correction"] == "none"
    assert payload["config"]["association_mode"] == "interpolate_gt"
    assert payload["config"]["max_interpolation_gap_s"] == 1.0
    assert payload["config"]["allow_extrapolation"] is False
    assert payload["config"]["time_offset_s"] == 0.0
    assert payload["config"]["continuous_segment_policy"] == "vo_timestamps"
    assert payload["hiddenStates"] == [True, False]


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
        "positionCompareComposite",
        "attitudeCompareComposite",
        "positionErrorComposite",
        "attitudeErrorComposite",
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
          visual_segment_id: index < 2 ? 0 : 1,
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
          inputs: { entry_mode: "vo" },
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
        const byId = Object.fromEntries(plots.map((plot) => [plot.id, plot]));
        process.stdout.write(JSON.stringify({
          ids: plots.map((plot) => plot.id),
          trajectory3dNames: byId.trajectory3d.data.map((trace) => trace.name),
          gtStartText: byId.trajectory3d.data[2].text,
          gtEndText: byId.trajectory3d.data[3].text,
          gtStartMarker: byId.trajectory3d.data[2].marker,
          positionCompareNames: byId.positionCompareComposite.data.map((trace) => trace.name),
          thirdRowColors: [
            byId.positionCompareComposite.data[4].line.color,
            byId.positionCompareComposite.data[5].line.color,
          ],
        }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    rendered_ids = set(payload["ids"])
    assert set(expected_ids).issubset(rendered_ids)
    assert {"GT start", "GT end", "VO start", "VO end"}.issubset(set(payload["trajectory3dNames"]))
    assert payload["gtStartText"] == ["GT S1", "GT S2"]
    assert payload["gtEndText"] == ["GT E1", "GT E2"]
    assert payload["gtStartMarker"]["size"] == 9
    assert payload["gtStartMarker"]["color"] == "#2563eb"
    assert {"X Ground truth", "X VO aligned", "Y Ground truth", "Y VO aligned", "Z Ground truth", "Z VO aligned"} == set(payload["positionCompareNames"])
    assert payload["thirdRowColors"] == ["#dc2626", "#0891b2"]


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
    assert json.loads(result.stdout) == {"x": [10, 11, 20], "y": [2, 2, 3]}


def test_static_composite_angle_time_series_unwraps_180_degree_boundary():
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
        context.renderPairCompositeChart("attitudeCompareComposite", [
          { timestamp: 0, segment_id: 0, gt_roll_deg: 0, est_roll_aligned_deg: 179 },
          { timestamp: 1, segment_id: 0, gt_roll_deg: 1, est_roll_aligned_deg: -179 },
          { timestamp: 2, segment_id: 0, gt_roll_deg: 2, est_roll_aligned_deg: 178 },
        ], {
          title: "Roll",
          leftName: "Ground truth",
          rightName: "VO aligned",
          rows: [{ label: "Roll", left: "gt_roll_deg", right: "est_roll_aligned_deg", unit: "deg", unwrap: true }],
        });
        process.stdout.write(JSON.stringify(plots[0].data[1].y));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [179, 181, 178]


def test_static_composite_angle_error_time_series_unwraps_180_degree_boundary():
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
        context.renderSingleCompositeChart("attitudeErrorComposite", [
          { timestamp: 0, segment_id: 0, roll_error_signed_deg: 179 },
          { timestamp: 1, segment_id: 0, roll_error_signed_deg: -179 },
          { timestamp: 2, segment_id: 0, roll_error_signed_deg: 178 },
        ], {
          title: "Roll error",
          rows: [{ label: "Roll error", field: "roll_error_signed_deg", unit: "deg", unwrap: true }],
        });
        process.stdout.write(JSON.stringify(plots[0].data[0].y));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [179, 181, 178]


def test_static_composite_charts_disable_native_spikes_for_custom_overlay():
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
          innerHTML: "",
        };
        const document = {
          body: { appendChild() {} },
          getElementById() { return element; },
          createElement() { return { ...element, click() {}, remove() {}, appendChild() {} }; },
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
          Plotly: { newPlot(id, data, layout) { plots.push({ id, data, layout }); return Promise.resolve(); }, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);
        context.renderPairCompositeChart("positionCompareComposite", [
          { timestamp: 1, nav_n_m: 10, vloc_n_m: 9, nav_e_m: 20, vloc_e_m: 19 },
          { timestamp: 2, nav_n_m: 11, vloc_n_m: 10, nav_e_m: 21, vloc_e_m: 20 },
        ], {
          title: "NED",
          leftName: "nav",
          rightName: "vloc",
          rows: [
            { label: "N", left: "nav_n_m", right: "vloc_n_m", unit: "m" },
            { label: "E", left: "nav_e_m", right: "vloc_e_m", unit: "m" },
          ],
        });
        const plot = plots[0];
        process.stdout.write(JSON.stringify({
          hovermode: plot.layout.hovermode,
          hoversubplots: plot.layout.hoversubplots,
          xaxisShowspikes: plot.layout.xaxis.showspikes,
          xaxis2Showspikes: plot.layout.xaxis2.showspikes,
          firstTraceHoverinfo: plot.data[0].hoverinfo,
          secondTraceHoverinfo: plot.data[1].hoverinfo,
        }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload == {
        "hovermode": "x unified",
        "hoversubplots": "axis",
        "xaxisShowspikes": False,
        "xaxis2Showspikes": False,
        "firstTraceHoverinfo": "none",
        "secondTraceHoverinfo": "none",
    }


def test_static_composite_payload_helpers_compute_hover_and_range_payloads():
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
          innerHTML: "",
          parentNode: { insertBefore() {} },
        };
        const document = {
          body: { appendChild() {} },
          getElementById() { return element; },
          createElement() { return { ...element, click() {}, remove() {}, appendChild() {}, parentNode: element.parentNode }; },
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
          Plotly: { newPlot() { return Promise.resolve(); }, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);
        const rows = [
          { timestamp: 10, nav_n_m: 1, vloc_n_m: 2, position_error_n_m: 0.1 },
          { timestamp: 20, nav_n_m: 3, vloc_n_m: 4, position_error_n_m: 0.3 },
          { timestamp: 30, nav_n_m: 5, vloc_n_m: 6, position_error_n_m: 0.5 },
        ];
        const pairSpec = {
          rows: [{ label: "N", left: "nav_n_m", right: "vloc_n_m", unit: "m" }],
          leftName: "nav",
          rightName: "vloc",
        };
        const errorSpec = {
          rows: [{ label: "N error", field: "position_error_n_m", unit: "m" }],
        };
        process.stdout.write(JSON.stringify({
          hover: context.compositeHoverPayload(rows, pairSpec, 19),
          range: context.compositeRangePayload(rows, errorSpec, [9, 21]),
        }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["hover"]["timestamp"] == 20
    assert payload["hover"]["values"] == [
        {"label": "N nav", "value": 3, "unit": "m"},
        {"label": "N vloc", "value": 4, "unit": "m"},
    ]
    assert payload["range"]["start"] == 9
    assert payload["range"]["end"] == 21
    assert payload["range"]["sampleCount"] == 2
    assert payload["range"]["stats"][0]["label"] == "N error"
    assert payload["range"]["stats"][0]["mean"] == 0.2


def test_static_composite_hover_overlay_spans_chart_and_follows_cursor():
    script = textwrap.dedent(
        r"""
        const fs = require("fs");
        const vm = require("vm");
        const makeElement = (id = "") => ({
          id,
          children: [],
          parentNode: null,
          style: {},
          files: [],
          value: "",
          disabled: false,
          hidden: false,
          textContent: "",
          innerHTML: "",
          className: "",
          clientWidth: 900,
          clientHeight: 720,
          classList: {
            values: [],
            add(value) { this.values.push(value); },
            remove() {},
          },
          appendChild(child) {
            child.parentNode = this;
            this.children.push(child);
            if (child.id) {
              elements[child.id] = child;
            }
            return child;
          },
          addEventListener(type, handler) {
            this[`event_${type}`] = handler;
          },
          remove() {},
          getBoundingClientRect() {
            return { left: 10, top: 20, width: this.clientWidth, height: this.clientHeight };
          },
        });
        const elements = {};
        const document = {
          body: makeElement("body"),
          getElementById(id) {
            return elements[id] || null;
          },
          createElement(tag) {
            return makeElement(tag);
          },
        };
        const plot = makeElement("positionCompareComposite");
        plot.onHandlers = {};
        plot.on = (name, handler) => { plot.onHandlers[name] = handler; };
        elements.positionCompareComposite = plot;
        const context = {
          console,
          document,
          window: { location: { protocol: "http:" } },
          TextEncoder,
          Uint8Array,
          DataView,
          Blob: function Blob() {},
          URL: { createObjectURL() { return ""; }, revokeObjectURL() {} },
          Plotly: { newPlot() { return Promise.resolve(); }, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);
        context.renderPairCompositeChart("positionCompareComposite", [
          { timestamp: 10, nav_n_m: 1, vloc_n_m: 2, nav_e_m: 3, vloc_e_m: 4, nav_d_m: -5, vloc_d_m: -6 },
          { timestamp: 20, nav_n_m: 11, vloc_n_m: 12, nav_e_m: 13, vloc_e_m: 14, nav_d_m: -15, vloc_d_m: -16 },
        ], {
          title: "NED",
          leftName: "nav",
          rightName: "vloc",
          rows: [
            { label: "N", left: "nav_n_m", right: "vloc_n_m", unit: "m" },
            { label: "E", left: "nav_e_m", right: "vloc_e_m", unit: "m" },
            { label: "D", left: "nav_d_m", right: "vloc_d_m", unit: "m" },
          ],
        });
        plot.onHandlers.plotly_hover({
          points: [{ x: 19, xaxis: { _offset: 80, l2p(x) { return x * 2; } } }],
          event: { clientX: 240, clientY: 280 },
        });
        const crosshair = elements.positionCompareCompositeCrosshair;
        const tooltip = elements.positionCompareCompositeTooltip;
        process.stdout.write(JSON.stringify({
          crosshairClass: crosshair.className,
          crosshairDisplay: crosshair.style.display,
          crosshairLeft: crosshair.style.left,
          crosshairTop: crosshair.style.top,
          crosshairBottom: crosshair.style.bottom,
          tooltipClass: tooltip.className,
          tooltipDisplay: tooltip.style.display,
          tooltipLeft: tooltip.style.left,
          tooltipTop: tooltip.style.top,
          tooltipHtml: tooltip.innerHTML,
        }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["crosshairClass"] == "composite-crosshair"
    assert payload["crosshairDisplay"] == "block"
    assert payload["crosshairLeft"] == "118px"
    assert payload["crosshairTop"] == "0px"
    assert payload["crosshairBottom"] == "0px"
    assert payload["tooltipClass"] == "composite-floating-tooltip"
    assert payload["tooltipDisplay"] == "block"
    assert payload["tooltipLeft"] != ""
    assert payload["tooltipTop"] != ""
    assert "当前时间戳 20.000 s" in payload["tooltipHtml"]
    for label in ["N nav", "N vloc", "E nav", "E vloc", "D nav", "D vloc"]:
        assert label in payload["tooltipHtml"]


def test_static_entry_mode_switches_between_vloc_and_vo_result_pages():
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
          click() {},
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
          modeAndAlignmentSection: makeElement(),
          interpolationPreset: makeElement("0.15"),
          maxInterpolationGap: makeElement("0.15"),
          downloadJson: makeElement(),
          downloadPoseCsv: makeElement(),
          downloadSegmentCsv: makeElement(),
          downloadWorstCsv: makeElement(),
          downloadConfigJson: makeElement(),
          downloadTrajectoryExcel: makeElement(),
          downloadHtml: makeElement(),
          trajectory3d: makeElement(),
          trajectoryXY: makeElement(),
          errorDistance: makeElement(),
          segmentError: makeElement(),
          speedError: makeElement(),
          sim3ScaleTime: makeElement(),
          rpeTranslationTime: makeElement(),
          rpeRotationTime: makeElement(),
          summaryKicker: makeElement(),
          summaryTitle: makeElement(),
          visualKicker: makeElement(),
          visualTitle: makeElement(),
          metrics: makeElement(),
        };
        const document = {
          body: { appendChild() {} },
          getElementById(id) { return elements[id] || makeElement(); },
          createElement() { return { ...makeElement(), remove() {} }; },
          querySelectorAll() { return []; },
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

        context.updateEntryModeUi();
        const vlocState = {
          segmentErrorHidden: elements.segmentError.hidden,
          speedErrorHidden: elements.speedError.hidden,
          sim3ScaleHidden: elements.sim3ScaleTime.hidden,
          rpeTranslationHidden: elements.rpeTranslationTime.hidden,
          trajectory3dHidden: elements.trajectory3d.hidden,
          summaryTitle: elements.summaryTitle.textContent,
          visualTitle: elements.visualTitle.textContent,
        };

        elements.entryMode.value = "vo";
        context.updateEntryModeUi();
        const voState = {
          segmentErrorHidden: elements.segmentError.hidden,
          speedErrorHidden: elements.speedError.hidden,
          sim3ScaleHidden: elements.sim3ScaleTime.hidden,
          rpeTranslationHidden: elements.rpeTranslationTime.hidden,
          trajectory3dHidden: elements.trajectory3d.hidden,
          summaryTitle: elements.summaryTitle.textContent,
          visualTitle: elements.visualTitle.textContent,
        };

        process.stdout.write(JSON.stringify({ vlocState, voState }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["vlocState"]["segmentErrorHidden"] is True
    assert payload["vlocState"]["speedErrorHidden"] is True
    assert payload["vlocState"]["sim3ScaleHidden"] is True
    assert payload["vlocState"]["rpeTranslationHidden"] is True
    assert payload["vlocState"]["trajectory3dHidden"] is False
    assert "VLOC" in payload["vlocState"]["summaryTitle"]
    assert "VLOC" in payload["vlocState"]["visualTitle"]
    assert payload["voState"]["segmentErrorHidden"] is False
    assert payload["voState"]["speedErrorHidden"] is False
    assert payload["voState"]["sim3ScaleHidden"] is False
    assert payload["voState"]["rpeTranslationHidden"] is False
    assert payload["voState"]["trajectory3dHidden"] is False
    assert "VO" in payload["voState"]["summaryTitle"]
    assert "VO" in payload["voState"]["visualTitle"]


def test_static_vloc_visuals_use_vloc_detail_tables_and_show_status_charts():
    html = Path("static_web/index.html").read_text()
    for chart_id in ["navStatusModes", "navVelocity", "navResetCounts", "vlocStatus", "heightComparison"]:
        assert f'id="{chart_id}"' in html

    script = textwrap.dedent(
        r"""
        const fs = require("fs");
        const vm = require("vm");
        const plots = [];
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
          click() {},
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
          modeAndAlignmentSection: makeElement(),
          interpolationPreset: makeElement("0.15"),
          maxInterpolationGap: makeElement("0.15"),
          downloadJson: makeElement(),
          downloadPoseCsv: makeElement(),
          downloadSegmentCsv: makeElement(),
          downloadWorstCsv: makeElement(),
          downloadConfigJson: makeElement(),
          downloadTrajectoryExcel: makeElement(),
          downloadHtml: makeElement(),
          metrics: makeElement(),
        };
        [
          "trajectory3d", "trajectoryXY", "errorDistance",
          "segmentError", "speedError", "sim3ScaleTime",
          "positionCompareComposite", "attitudeCompareComposite",
          "positionErrorComposite", "attitudeErrorComposite",
          "rpeTranslationTime", "rpeRotationTime",
          "navStatusModes", "navVelocity", "navResetCounts", "vlocStatus", "heightComparison",
        ].forEach((id) => { elements[id] = makeElement(); });
        const document = {
          body: { appendChild() {} },
          getElementById(id) { return elements[id] || makeElement(); },
          createElement() { return { ...makeElement(), remove() {} }; },
          querySelectorAll() { return []; },
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
          Plotly: { newPlot(id, data, layout) { plots.push({ id, data, layout }); }, purge() {} },
        };
        context.globalThis = context;
        const code = fs.readFileSync("static_web/app.js", "utf8").replace(/\ninit\(\);\n/, "\n");
        vm.runInNewContext(code, context);

        context.renderCharts({
          inputs: { entry_mode: "vloc" },
          per_pose: [
            { timestamp: 10, segment_id: 0, distance_m: 0, gt_x_m: 999, gt_y_m: 999, gt_z_m: 999, est_x_aligned_m: 888, est_y_aligned_m: 888, est_z_aligned_m: 888, x_error_m: 777 },
          ],
          segment_errors: [{ length_m: 100, translation_error_percent: { mean: 99 } }],
          speed_bins: [{ speed_bin_mps: "0-5", translation_error_percent: { mean: 99 } }],
          vloc_details: {
            nav_status: [
              { timestamp: 1, flight_mode: 3, navi_mode: 5, rtk_yaw: 1, rtk_alti: 0, position_reset_count: 0, altitude_reset_count: 1, heading_reset_count: 2, vx: 0.1, vy: 0.2, vz: 0.3, velocity_norm: 0.374 },
              { timestamp: 2, flight_mode: 4, navi_mode: 6, rtk_yaw: 1, rtk_alti: 1, position_reset_count: 0, altitude_reset_count: 1, heading_reset_count: 3, vx: 0.4, vy: 0.5, vz: 0.6, velocity_norm: 0.877 },
            ],
            vloc_status: [
              { timestamp: 1, vloc_mode: 2, num_inliers: 40, reset_count: 0 },
              { timestamp: 2, vloc_mode: 3, num_inliers: 41, reset_count: 1 },
            ],
            comparison: [
              { timestamp: 1, segment_id: 0, visual_segment_id: 0, nav_n_m: 10, nav_e_m: 20, nav_d_m: -3, vloc_n_m: 9, vloc_e_m: 21, vloc_d_m: -4, nav_height_m: 7, vloc_height_m: 6, position_error_n_m: 1, position_error_e_m: -1, position_error_d_m: 1, horizontal_position_error_m: 1.414, attitude_error_yaw_deg: 0.5, attitude_error_pitch_deg: -0.2, attitude_error_roll_deg: 0.1, nav_yaw_deg: 4, vloc_yaw_deg: 3.5, nav_pitch_deg: 1, vloc_pitch_deg: 1.2, nav_roll_deg: 2, vloc_roll_deg: 1.9 },
              { timestamp: 2, segment_id: 1, visual_segment_id: 1, nav_n_m: 11, nav_e_m: 22, nav_d_m: -5, vloc_n_m: 10, vloc_e_m: 23, vloc_d_m: -6, nav_height_m: 8, vloc_height_m: 7, position_error_n_m: 1, position_error_e_m: -1, position_error_d_m: 1, horizontal_position_error_m: 1.414, attitude_error_yaw_deg: 0.6, attitude_error_pitch_deg: -0.3, attitude_error_roll_deg: 0.2, nav_yaw_deg: 5, vloc_yaw_deg: 4.4, nav_pitch_deg: 2, vloc_pitch_deg: 2.3, nav_roll_deg: 3, vloc_roll_deg: 2.8 },
            ],
          },
        });

        const byId = Object.fromEntries(plots.map((plot) => [plot.id, plot]));
        process.stdout.write(JSON.stringify({
          plottedIds: plots.map((plot) => plot.id),
          xChartGt: byId.positionCompareComposite.data[0].y,
          xChartEst: byId.positionCompareComposite.data[1].y,
          xError: byId.positionErrorComposite.data[0].y,
          trajectory3dNames: byId.trajectory3d.data.map((trace) => trace.name),
          vlocStartText: byId.trajectory3d.data.find((trace) => trace.name === "vloc start").text,
          vlocEndText: byId.trajectory3d.data.find((trace) => trace.name === "vloc end").text,
          vlocStartMarker: byId.trajectory3d.data.find((trace) => trace.name === "vloc start").marker,
          vlocStartTextFont: byId.trajectory3d.data.find((trace) => trace.name === "vloc start").textfont,
          positionCompareNames: byId.positionCompareComposite.data.map((trace) => trace.name),
          positionCompareThirdRowColors: [
            byId.positionCompareComposite.data[4].line.color,
            byId.positionCompareComposite.data[5].line.color,
          ],
          heightNames: byId.heightComparison.data.map((trace) => trace.name),
          navVelocityNames: byId.navVelocity.data.map((trace) => trace.name),
          vlocStatusNames: byId.vlocStatus.data.map((trace) => trace.name),
          segmentHidden: elements.segmentError.hidden,
          navStatusHidden: elements.navStatusModes.hidden,
        }));
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert "navStatusModes" in payload["plottedIds"]
    assert "navVelocity" in payload["plottedIds"]
    assert "navResetCounts" in payload["plottedIds"]
    assert "vlocStatus" in payload["plottedIds"]
    assert "heightComparison" in payload["plottedIds"]
    assert payload["xChartGt"] == [10, 11]
    assert payload["xChartEst"] == [9, 10]
    assert payload["xError"] == [1, 1]
    assert "nav start" not in payload["trajectory3dNames"]
    assert "nav end" not in payload["trajectory3dNames"]
    assert {"vloc start", "vloc end"}.issubset(set(payload["trajectory3dNames"]))
    assert payload["vlocStartText"] == ["vloc S1", "vloc S2"]
    assert payload["vlocEndText"] == ["vloc E1", "vloc E2"]
    assert payload["vlocStartMarker"]["color"] == "#9333ea"
    assert payload["vlocStartMarker"]["size"] == 5
    assert payload["vlocStartMarker"]["line"]["width"] == 1
    assert payload["vlocStartTextFont"]["size"] == 10
    assert {"N nav", "N vloc", "E nav", "E vloc", "D nav", "D vloc"} == set(payload["positionCompareNames"])
    assert payload["positionCompareThirdRowColors"] == ["#dc2626", "#0891b2"]
    assert payload["heightNames"] == ["nav height", "vloc height"]
    assert "velocity_norm" in payload["navVelocityNames"]
    assert {"vloc_mode", "reset_count", "num_inliers"}.issubset(set(payload["vlocStatusNames"]))
    assert payload["segmentHidden"] is True
    assert payload["navStatusHidden"] is False


def test_static_vloc_metrics_hide_vo_specific_summary_cards():
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
          click() {},
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
          modeAndAlignmentSection: makeElement(),
          interpolationPreset: makeElement("0.15"),
          maxInterpolationGap: makeElement("0.15"),
          downloadJson: makeElement(),
          downloadPoseCsv: makeElement(),
          downloadSegmentCsv: makeElement(),
          downloadWorstCsv: makeElement(),
          downloadConfigJson: makeElement(),
          downloadTrajectoryExcel: makeElement(),
          downloadHtml: makeElement(),
          metrics: makeElement(),
        };
        const document = {
          body: { appendChild() {} },
          getElementById(id) { return elements[id] || makeElement(); },
          createElement() { return { ...makeElement(), remove() {} }; },
          querySelectorAll() { return []; },
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
        context.renderMetrics({
          summary: {
            gt_path_length_m: 1000,
            duration_s: 100,
            matched_poses: 200,
            original_matched_poses: 200,
            gt_pose_coverage_ratio: 0.95,
            est_pose_coverage_ratio: 0.95,
            endpoint_error_m: 1,
            endpoint_error_percent_of_path: 0.1,
            est_poses: 210,
            raw_path_scale_ratio_est_over_gt: 0.32,
          },
          ate_position_m: { rmse: 1.5 },
          ate_vertical_m: { rmse: 0.5 },
          rpe_frame_delta: { translation_m: { rmse: 0.3 }, delta_unit: "frames", delta_frames: 1 },
          divergence: { diverged: false },
          association: { mode: "interpolate_gt", max_interpolation_gap_s: 1.0 },
          discontinuities: { all_matches: { break_count: 2 }, selected_segment: { policy: "segments" } },
          alignment: { scale: 1.0 },
          orientation_correction: { selected: "none" },
          inputs: { entry_mode: "vloc" },
        });
        process.stdout.write(elements.metrics.innerHTML);
        """
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    html = result.stdout
    assert "ATE RMSE" in html
    assert "mean_error_pos_xy" in html
    assert "mean_error_euler" in html
    assert "时间同步" not in html
    assert "Raw 尺度比" not in html
    assert "对齐尺度" not in html
    assert "姿态修正" not in html
    assert "终点漂移" not in html
    assert "发散状态" not in html
