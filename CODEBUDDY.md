# CODEBUDDY.md This file provides guidance to CodeBuddy when working with code in this repository.

## Commands

### Run local server (required for evaluation)
```bash
python -m voeval server
```
This auto-opens the browser at http://127.0.0.1:8766/ — the server provides both static files and evaluation API endpoints. Must run from repo root so that `voeval/` is importable.

### Run all tests
```bash
pytest
```

### Run a single test file
```bash
pytest tests/test_evaluator.py -k "test_sim3_recovers_scale"
```

## Architecture

This is a VO (Visual Odometry) trajectory evaluation tool with a local-server-based web UI (`voeval/visualization/`). All evaluation runs in Python on the server side via HTTP API.

### Layer separation

**Data loading layer** (`voeval/io/`): Defines `Trajectory`, `EvaluationFormatSpec`, `HomePoint`, `Calibration`, `SfVlocBundle`, `SfVoBundle`, fixed SF/VO/VLOC columns, parsers, directory loaders, TUM readers, and input normalization. Also provides `load_vo_evaluation_bundle_from_text()` and `load_vloc_evaluation_bundle_from_text()` for file-upload API evaluation.

**Core layer** (`voeval/core/`): Owns `EvaluationConfig`, core workflow evaluation (`evaluate_*_core()` / `evaluate_trajectory_result()`), alignment, interpolation, geometry, error, statistics, and segment logic. It returns metrics and intermediate artifacts only; it does not import or assemble `reports`.

**Report layer** (`voeval/reports/`): Owns the public full-report evaluators (`evaluate_vloc_bundle()`, `evaluate_vo_bundle()`, `evaluate_trajectories()`), then attaches VLOC/VO detail tables, trajectory export sheets, JSON, Excel, HTML report generation, path helpers, preview helpers, and chart specs.

**Web UI layer** (`voeval/visualization/` + `voeval/server.py`): `voeval/server.py` is the HTTP server providing `/api/evaluate-paths`, `/api/evaluate-bundle`, `/api/report-slice`, and `/api/health` endpoints. `js/main.js` is the ES module entry point that wires all UI modules; `js/state.js`, `js/constants.js`, `js/dom-refs.js`, `js/utils.js`, and `js/labels.js` are foundational modules with no cross-dependencies. `visualization/figure_specs.js` and `visualization/report_templates.js` use ES module `export` (no globalThis handshake). `cli/export_report_cli.js` is the Node.js CLI for offline HTML report generation. `css/style.css` provides base styles and CSS variables; `css/report-export.css` extends them for offline HTML reports.

### Key data structures

- `Trajectory` dataclass: `stamps` (1D), `positions` (N×3), `rotations` (N×3×3 optional), `extras` dict for runtime fields
- `EvaluationConfig` dataclass: Supported evaluation parameters for the current VO/VLOC workflows, mainly RPE and local-scale interval settings plus fixed synchronization defaults.
- Report dict: The output of `voeval.reports.evaluate_trajectories()` with keys such as `summary`, `ate_position_m`, `ate_horizontal_m`, `ate_vertical_m`, `ate_orientation_deg`, `ate_yaw_deg`, `rpe_frame_delta`, `per_pose` (DataFrame), `discontinuities`, `association`, `alignment`, `trajectory_exports`, `inputs`, and `config`. VO reports can additionally include `scale_frame_delta` / `scale_per_frame`; VLOC and VO wrappers add their own `vloc_details` / `vo_details`.

### Evaluation pipeline order

`evaluate_trajectory_result()` in `voeval/core/pipeline.py` executes in this order:
1. `prepare_evaluation_trajectories()` (GT interpolation to estimate timestamps)
2. discontinuity diagnosis and optional continuous segment selection
3. fixed VO/VLOC alignment policy (`VO = Sim3`, `VLOC = none`)
4. ATE, per-frame RPE, and local scale calculations
5. summary aggregation and intermediate artifacts for the report layer

### Metric-code synchronization

There is no generated metric registry in code. Keep `README.md` and the concrete report fields in `voeval/core/pipeline.py` / `voeval/reports/` aligned when adding or renaming metrics.
