# vo_eval_cli

Standalone batch CLI for validating `vo_eval` as a replacement for the current
`evo` / MATLAB summary workflow.

This folder is intentionally separate from the core `vo_eval` package. It adapts
log or dataset directories to the existing evaluator API and writes a compact
Excel summary.

## Modes

### `--mode tum`

Evo-compatible TUM evaluation for pipeline logs:

```text
log_root/
  0/
    run_metadata.json
    trajectory_tum.txt
```

Each `run_metadata.json` must contain `dataset_path`, and each dataset directory
must contain `groundtruth_tum.txt`.

```bash
cd /home/liu/vo-evaluation-system
vo_eval_cli/.venv/bin/python -m vo_eval_cli \
  --mode tum \
  --log-root /home/liu/slam_pipeline/logs/orbslam3 \
  --ids 0,1,2 \
  --rpe-deltas 1f,100m,500m
```

The meter RPE summary uses evo-compatible pair selection, so `1f/100m/500m` and
APE summary columns should match `evo_rpe/evo_ape` up to floating-point noise.

### `--mode vo`

Batch SF VO fixed-format evaluation for dataset directories:

```text
data_root/
  102/
    imu.txt
    vo.txt
    home_point.txt
    calib_raw.yaml
```

```bash
cd /home/liu/vo-evaluation-system
vo_eval_cli/.venv/bin/python -m vo_eval_cli \
  --mode vo \
  --data-root /home/liu/桌面/SFdataset \
  --ids 102,157,191 \
  --rpe-deltas 1f
```

`--mode vo` uses the existing `load_vo_evaluation_bundle()` /
`evaluate_vo_bundle()` path, including VO reset segment filtering and segment-wise
Sim3 alignment. Legacy 11-column `vo.txt` files are accepted by the core parser
and padded with zero depth columns. Excel classification defaults to `mean_xy`
and follows the slam_pipeline MATLAB-style rule: red when `max_xy > xy_fail`,
yellow when `max_xy > xy_warn` or `max_z > z_warn`.

### `--mode vloc`

Batch SF VLOC fixed-format evaluation for dataset directories:

```text
data_root/
  102/
    imu.txt
    vloc.txt
    home_point.txt
    calib_raw.yaml
```

```bash
cd /home/liu/vo-evaluation-system
vo_eval_cli/.venv/bin/python -m vo_eval_cli \
  --mode vloc \
  --data-root /home/liu/桌面/SFdataset \
  --ids 102,157,191 \
  --rpe-deltas 1f
```

`--mode vloc` uses the existing `load_vloc_evaluation_bundle()` /
`evaluate_vloc_bundle()` path, including fixed `vloc_mode > 1` filtering and
nav-to-VLOC timestamp interpolation. Excel classification defaults to `mean_xy`
and follows the same slam_pipeline MATLAB-style `max_xy` / `max_z` rule.

## Output

The output workbook has the same high-level shape as the current pipeline
summary: `Eval Summary` and `Statistics` sheets.
