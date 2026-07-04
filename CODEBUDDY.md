# CODEBUDDY.md This file provides guidance to CodeBuddy when working with code in this repository.

## Commands

### Run static web version locally
```bash
python3 -m http.server 8765
```
Open http://localhost:8765/static_web/ — must use HTTP, not file://. Must run from repo root (not `static_web/`) so that `vo_eval/` is accessible as a sibling directory.

### Run all tests
```bash
pytest
```

### Run a single test file
```bash
pytest tests/test_evaluator.py -k "test_sim3_recovers_scale"
```

## Architecture

This is a VO (Visual Odometry) trajectory evaluation tool with a static web version (`static_web/`) that runs evaluation entirely in the browser via Pyodide.

### Layer separation

**Data loading layer** (`vo_eval/data_loader.py`): Defines `Trajectory`, `EvaluationFormatSpec`, `HomePoint`, `Calibration`, `SfVlocBundle`, `SfVoBundle`, fixed SF/VO/VLOC columns, parsers, directory loaders, TUM readers, and input normalization.

**Processing layer** (`vo_eval/processing.py`): Owns `EvaluationConfig`, `evaluate_vloc_bundle()`, `evaluate_vo_bundle()`, and `evaluate_trajectories()`. It controls the evaluation flow and assembles the report, but delegates low-level math to `utils.py` and export tables to `report.py`.

**Utility layer** (`vo_eval/utils.py`): Contains reusable numerical logic: NED/geodetic conversion, interpolation, quaternion/euler/rotation helpers, Sim3/Umeyama alignment, RPE pair selection, local scale estimation, discontinuity detection, and descriptive statistics.

**Report layer** (`vo_eval/report.py`): Builds VLOC/VO detail tables and export artifacts, including JSON and Excel output.

**Static web layer** (`static_web/`): Pure client-side alternative organized by role into subdirectories. `js/main.js` is the ES module entry point that wires all UI modules; `js/state.js`, `js/constants.js`, `js/dom-refs.js`, `js/utils.js`, `js/labels.js` are foundational modules with no cross-dependencies. `worker/worker.js` loads `vo_eval` modules from `./py/vo_eval/` via HTTP (symlink to `../../vo_eval/`) and writes them into Pyodide's virtual filesystem. `py/browser_runner.py` is the thin Pyodide adapter. `visualization/figure_specs.js` and `visualization/report_templates.js` use ES module `export` (no globalThis handshake). `cli/export_report_cli.js` is the Node.js CLI for offline HTML report generation, using dynamic `import()` with globalThis browser mocks. `css/style.css` provides base styles and CSS variables; `css/report-export.css` extends them for offline HTML reports.

### Key data structures

- `Trajectory` dataclass: `stamps` (1D), `positions` (N×3), `rotations` (N×3×3 optional), `extras` dict for runtime fields
- `EvaluationConfig` dataclass: Supported evaluation parameters for the current VO/VLOC workflows, mainly RPE and local-scale interval settings plus fixed synchronization defaults.
- Report dict: The output of `evaluate_trajectories()` with keys: `summary`, `ate_position_m`, `ate_vertical_m`, `rpe_frame_delta`, `segment_errors`, `segment_records`, `per_pose` (DataFrame), `divergence`, `discontinuities`, `association`, `alignment`, `orientation_correction`, `speed_bins`, `runtime`, `trajectory_exports`, `inputs`, `config`

### Evaluation pipeline order

`evaluate_trajectories()` in `vo_eval/processing.py` executes in this order:
1. `prepare_evaluation_trajectories()` (GT interpolation to estimate timestamps)
2. discontinuity diagnosis and optional continuous segment selection
3. fixed VO/VLOC alignment policy (`VO = Sim3`, `VLOC = none`)
4. ATE, per-frame RPE, and local scale calculations
5. summary aggregation and `trajectory_exports` construction

### Metric-code synchronization

`METRIC_CODE_MAP` in `vo_eval/data_loader.py` is the authoritative index linking each metric to its report field and function names. When adding or renaming a metric, update `METRIC_CODE_MAP` and the README "指标与代码总表" table simultaneously to prevent documentation/code divergence.
