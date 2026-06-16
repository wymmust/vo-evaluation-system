# CODEBUDDY.md This file provides guidance to CodeBuddy when working with code in this repository.

## Commands

### Run the Streamlit app
```bash
streamlit run app.py
```
Opens on http://localhost:8501 by default.

### Run static web version locally
```bash
cd static_web && python3 -m http.server 8765
```
Open http://localhost:8765 — must use HTTP, not file://.

### Run all tests
```bash
pytest
```

### Run a single test file
```bash
pytest tests/test_evaluator.py -k "test_sim3_recovers_scale"
```

### Sync static_web evaluator copy (automatic via git hook)
```bash
python scripts/sync_static_web.py   # manual sync if needed
```
Copies `vo_eval/evaluator.py` → `static_web/py/evaluator.py` for Pyodide browser deployment. A git pre-commit hook (`scripts/pre-commit-sync.sh`) runs this automatically when evaluator.py is changed, so the copy is always in sync.

## Architecture

This is a VO (Visual Odometry) trajectory evaluation tool with two deployment modes: a Streamlit Python server (`app.py`) and a static web version (`static_web/`) that runs evaluation entirely in the browser via Pyodide.

### Three-tier separation

**Algorithm layer** (`vo_eval/evaluator.py`): All computation lives here. This single file (~2500+ lines) handles:
1. Input parsing — TUM, KITTI, CSV, EuRoC, SF, VLOC, XYZ formats into `Trajectory` dataclass
2. Time synchronization — GT interpolation to VO timestamps (default), TUM greedy nearest-neighbor, or index matching
3. Trajectory alignment — SE3, Sim3 (Umeyama), first-pose, or none; per-segment or global
4. Orientation correction — auto-selects best convention fix (Rz180, ENU/NED, inverse, etc.)
5. Metric computation — ATE, RPE, segment errors, speed bins, divergence, discontinuities, runtime stats
6. Report output — structured dict with `per_pose` DataFrame, `segment_records`, `segment_errors`, `summary`, etc.

**UI layer** (`app.py`, ~1660 lines): Streamlit sidebar collects config → calls `evaluate_trajectories()` → renders 15 metric cards + Plotly charts + downloadable HTML/JSON/CSV/Excel. Does NOT compute metrics — only displays them. Uses `importlib.reload()` on each run to pick up evaluator changes during Streamlit hot-reload.

**Static web layer** (`static_web/`): Pure client-side alternative. `app.js` builds UI and calls `static_web/py/browser_runner.py`, which wraps `vo_eval.evaluator` into a `evaluate_json()` function that takes text+config JSON and returns report JSON. Runs inside Pyodide with numpy/pandas bundled. `static_web/py/evaluator.py` is a copy of the core evaluator for Pyodide packaging.

### Key data structures

- `Trajectory` dataclass: `stamps` (1D), `positions` (N×3), `rotations` (N×3×3 optional), `extras` dict for runtime fields
- `EvaluationConfig` dataclass: All configurable parameters (alignment, association_mode, rpe_delta, segment_lengths, divergence thresholds, etc.)
- Report dict: The output of `evaluate_trajectories()` with keys: `summary`, `ate_position_m`, `ate_vertical_m`, `rpe_frame_delta`, `segment_errors`, `segment_records`, `per_pose` (DataFrame), `divergence`, `discontinuities`, `association`, `alignment`, `orientation_correction`, `speed_bins`, `runtime`, `trajectory_exports`, `inputs`, `config`

### Evaluation pipeline order

`evaluate_trajectories()` executes in this order:
1. `prepare_evaluation_trajectories()` → `build_associated_trajectories()` (time sync)
2. `select_orientation_correction()` + `apply_orientation_correction()` (if needed)
3. `compute_alignment()` + `aggregate_alignment()` + `apply_alignment()` (coordinate transform)
4. Error computation (ATE, RPE, segment, speed bins, divergence, discontinuities)
5. `build_ate_report()`, `describe()`, summary aggregation
6. `trajectory_exports` construction (TUM format sheets, per-frame ATE/RPE/scale DataFrames)

### Metric-code synchronization

`METRIC_CODE_MAP` at the top of `vo_eval/evaluator.py` is the authoritative index linking each metric to its report field and function names. When adding or renaming a metric, update `METRIC_CODE_MAP` AND the README "指标与 evaluator.py 代码总表" table simultaneously to prevent documentation/code divergence.

### Evaluator deployment copy

`static_web/py/evaluator.py` is a copy of `vo_eval/evaluator.py`, required because the browser (Pyodide) cannot import from the project Python package — it fetches files via HTTP and writes them into a virtual filesystem. After modifying `vo_eval/evaluator.py`, run `python scripts/sync_static_web.py` to update the copy. `static_web/py/browser_runner.py` is the thin Pyodide adapter that calls `evaluate_json()`.

The `py/` directory (with its duplicate `evaluator.py` and `browser_runner.py`) was deleted — it had no references and was pure redundancy.

### Streamlit config

`.streamlit/config.toml`: upload size limit 200MB (`maxUploadSize = 200`), headless mode, port 8501.