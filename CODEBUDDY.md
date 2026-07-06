# CODEBUDDY.md This file provides guidance to CodeBuddy when working with code in this repository.

## Commands

### Run local server (required for evaluation)
```bash
python web/server.py --host 127.0.0.1 --port 8766
```
Open http://127.0.0.1:8766/ — the server provides both static files and evaluation API endpoints. Must run from repo root so that `vo_eval/` is importable.

### Run all tests
```bash
pytest
```

### Run a single test file
```bash
pytest tests/test_evaluator.py -k "test_sim3_recovers_scale"
```

## Architecture

This is a VO (Visual Odometry) trajectory evaluation tool with a local-server-based web UI (`web/`). All evaluation runs in Python on the server side via HTTP API.

### Layer separation

**Data loading layer** (`vo_eval/data_loader.py`): Defines `Trajectory`, `EvaluationFormatSpec`, `HomePoint`, `Calibration`, `SfVlocBundle`, `SfVoBundle`, fixed SF/VO/VLOC columns, parsers, directory loaders, TUM readers, and input normalization. Also provides `load_vo_evaluation_bundle_from_text()` and `load_vloc_evaluation_bundle_from_text()` for file-upload API evaluation.

**Processing layer** (`vo_eval/processing.py`): Owns `EvaluationConfig`, `evaluate_vloc_bundle()`, `evaluate_vo_bundle()`, and `evaluate_trajectories()`. It controls the evaluation flow and assembles the report, but delegates low-level math to `utils.py` and export tables to `report.py`.

**Utility layer** (`vo_eval/utils.py`): Contains reusable numerical logic: NED/geodetic conversion, interpolation, quaternion/euler/rotation helpers, Sim3/Umeyama alignment, RPE pair selection, local scale estimation, discontinuity detection, and descriptive statistics.

**Report layer** (`vo_eval/report.py`): Builds VLOC/VO detail tables and export artifacts, including JSON and Excel output.

**Web UI layer** (`web/`): Local-server + browser UI. `js/main.js` is the ES module entry point that wires all UI modules; `js/state.js`, `js/constants.js`, `js/dom-refs.js`, `js/utils.js`, `js/labels.js` are foundational modules with no cross-dependencies. `server.py` is the HTTP server providing `/api/evaluate-paths`, `/api/evaluate-bundle`, `/api/report-slice`, and `/api/health` endpoints. `visualization/figure_specs.js` and `visualization/report_templates.js` use ES module `export` (no globalThis handshake). `cli/export_report_cli.js` is the Node.js CLI for offline HTML report generation. `css/style.css` provides base styles and CSS variables; `css/report-export.css` extends them for offline HTML reports.

### Key data structures

- `Trajectory` dataclass: `stamps` (1D), `positions` (N×3), `rotations` (N×3×3 optional), `extras` dict for runtime fields
- `EvaluationConfig` dataclass: Supported evaluation parameters for the current VO/VLOC workflows, mainly RPE and local-scale interval settings plus fixed synchronization defaults.
- Report dict: The output of `evaluate_trajectories()` with keys such as `summary`, `ate_position_m`, `ate_horizontal_m`, `ate_vertical_m`, `ate_orientation_deg`, `ate_yaw_deg`, `rpe_frame_delta`, `per_pose` (DataFrame), `discontinuities`, `association`, `alignment`, `trajectory_exports`, `inputs`, and `config`. VO reports can additionally include `scale_frame_delta` / `scale_per_frame`; VLOC and VO wrappers add their own `vloc_details` / `vo_details`.

### Evaluation pipeline order

`evaluate_trajectories()` in `vo_eval/processing.py` executes in this order:
1. `prepare_evaluation_trajectories()` (GT interpolation to estimate timestamps)
2. discontinuity diagnosis and optional continuous segment selection
3. fixed VO/VLOC alignment policy (`VO = Sim3`, `VLOC = none`)
4. ATE, per-frame RPE, and local scale calculations
5. summary aggregation and `trajectory_exports` construction

### Metric-code synchronization

There is no generated metric registry in code. Keep `README.md` and the concrete report fields in `vo_eval/processing.py` / `vo_eval/report.py` aligned when adding or renaming metrics.
