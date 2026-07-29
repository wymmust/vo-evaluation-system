# 代码梳理与待优化项

逐层梳理整个调用链，记录每层的脉络和发现的待优化项。

---

## 分析原则

**硬性规定**：分析代码时，不仅要看函数是否被调用，还要看：
1. 这个函数在做什么事情？
2. 调用方调用后，用处理后的数据做了什么？
3. 这件事本身是否必要？

---

## 第一层：入口层

### `__main__.py`

调用脉络：
```
main(argv)
  ├─ 无参数 / -h/--help  →  打印用法
  ├─ "sf_vo" / "sf_vloc" →  cli.main(args)
  ├─ "eval"              →  cli.main(remainder)   旧格式兼容
  ├─ "server"            →  server.main(remainder)
  └─ 以 "-" 开头         →  cli.main(args)        旧格式兼容
```

待优化项：
1. **删除旧格式兼容**：只需保留 `voeval sf_vo`、`voeval sf_vloc`、`voeval server` 三个子命令。

### `cli.py`

调用脉络：
```
main(argv)
  ├─ argparse 解析参数（含位置参数和旧 flag）
  ├─ _resolve_eval_arguments()      ← 统一新旧格式
  ├─ configure_logging()
  ├─ 构建 EvaluationConfig
  ├─ sf_vo  →  load_vo_evaluation_bundle → evaluate_vo_bundle → 打印摘要
  ├─ sf_vloc →  load_vloc_evaluation_bundle → evaluate_vloc_bundle → 打印摘要
  ├─ [可选] report_to_json → 写 JSON
  └─ [可选] _write_html_report → 写/预览 HTML
```

待优化项：
1. **删除旧 flag 兼容逻辑**：删除 `--mode`、`--data_dir`、`--log_dir` 三个隐藏参数。
2. **删除 `_resolve_eval_arguments()`**：不需要新旧格式适配。
3. **删除 `_resolve_positional_directories()`**：路径不做猜测重建。
4. **删除 `_directory_match_score()`**：无存在必要。
5. **简化 `main()` 参数解析**：直接用位置参数。

### `server.py`

调用脉络：
```
main(argv)  →  启动 ThreadingHTTPServer  →  自动打开浏览器

LocalEvaluationHandler（HTTP 请求处理）
  ├─ POST /api/evaluate-paths   → evaluate_paths_payload()   从本地路径评估
  ├─ POST /api/evaluate-bundle  → evaluate_bundle_payload()  从上传文件内容评估
  ├─ GET  /api/report-slice     → get_report_slice()         读取缓存报告分片
  └─ GET  其他                  → 静态文件（visualization/）

evaluate_*_payload()
  → load_*_evaluation_bundle → evaluate_*_bundle
  → LAST_REPORT = _jsonable_report(report)（全局缓存）
  → return _light_report(report)
```

待优化项：
1. **删除文件上传模式（`evaluate_bundle_payload`）**：只接受路径模式。
2. **`required_local_files()` 返回值被丢弃**：简化或删除。
3. **`_light_report` 冗余 JSON 往返**：简化。

待验证：
- `get_report_slice(slice_name)` 前端是否真的区分调用不同 slice？

---

## 第二层：IO / 数据加载层

### `io/bundle.py`

调用脉络：
```
load_vo_evaluation_bundle(data_dir, log_dir, vo_filename) → SfVoBundle
  ├─ 验证目录和文件存在
  ├─ parse_imu_fixed() → Trajectory (nav)
  ├─ parse_vo_fixed() → Trajectory (vo)
  ├─ parse_calib_raw_fixed() → Calibration
  └─ 组装 SfVoBundle(nav, vo, calibration, data_dir, log_dir, files)

load_vloc_evaluation_bundle(data_dir, log_dir) → SfVlocBundle
  ├─ 验证目录和文件存在
  ├─ parse_imu_fixed() → Trajectory (nav)
  ├─ parse_vloc_fixed() → Trajectory (vloc)
  ├─ parse_home_point_fixed() → HomePoint
  ├─ parse_calib_raw_fixed() → Calibration
  └─ 组装 SfVlocBundle(nav, vloc, home_point, calibration, data_dir, log_dir, files)
```

待优化项：
1. **删除 `load_*_from_text` 两个函数**：只被废弃接口调用。
2. **删除 `files` 字段**：下游无使用。

### `io/parsers.py`

调用脉络：
```
固定格式解析器（SF 专用，主流程使用）：
  parse_imu_fixed(text) → Trajectory         # 21 列 IMU/nav GT
  parse_vloc_fixed(text) → Trajectory        # 13 列 VLOC 输出
  parse_vo_fixed(text) → Trajectory          # 11 列 VO 输出（兼容旧 14 列）
  parse_home_point_fixed(text) → HomePoint   # 3 列
  parse_calib_raw_fixed(text) → Calibration  # YAML 4x4 矩阵

通用轨迹加载器（TUM 格式，无内部调用）：
  load_trajectory(source, fmt) → Trajectory
  load_trajectory_from_text(text, fmt) → Trajectory
```

待优化项：
1. **删除 `load_trajectory` / `load_trajectory_from_text`** 及 5 个辅助函数：无内部调用。
2. **`extras` 保留**：重要数据通道。

### `io/formats.py`

调用脉络：
```
列定义（被 parsers.py 使用）：
  IMU_FIXED_COLUMNS      # 21 列
  VLOC_FIXED_COLUMNS     # 13 列
  VO_FIXED_COLUMNS       # 11 列

常量（被 core/ 和 reports/ 广泛使用）：
  WGS84_A_M, WGS84_E2              # 椭球参数
  FIXED_TIME_OFFSET_S              # 时间偏移
  FIXED_DISCONTINUITY_*            # 跳变检测阈值
  VO_MIN_VALID_SEGMENT_*           # 有效段最小要求
  *_MAX_INTERPOLATION_GAP_S        # 最大插值间隙

格式规范机制（仅导出，无内部使用）：
  EvaluationFormatSpec, EVALUATION_FORMAT_SPECS, SUPPORTED_EVALUATION_FORMATS
  normalize_evaluation_format(), get_evaluation_format_spec()
```

待优化项：
1. **删除 `EvaluationFormatSpec` 相关代码**（约 70 行）：无内部调用。
2. **保留所有列定义和常量**。

### `io/trajectory.py`

调用脉络：
```
@dataclass Trajectory:
  name: str                        # 轨迹名称
  stamps: np.ndarray               # 秒级时间戳
  positions: np.ndarray            # N x 3 位置
  rotations: np.ndarray | None     # 可选 N x 3 x 3 旋转矩阵
  extras: dict[str, np.ndarray]    # 附加字段
  source_format: str               # 格式标识

  __post_init__():
    - 校验 shapes
    - 按时间排序（stamps, positions, rotations, extras 同步重排）

  @property duration_s -> float
```

待优化项：
1. **（低优先级）移除 `rotations` 的 `None` 判断**：牵扯面广，后续处理。

### `io/calibration.py`

调用脉络：
```
@dataclass HomePoint:
  longitude: float
  latitude: float
  altitude_msl: float

@dataclass Calibration:
  t_imu_body: np.ndarray      # ✅ geometry.py 使用
  t_cam_imu: np.ndarray       # ✅ geometry.py 使用
  t_cn_cnm1: np.ndarray | None = None  # ❌ 仅解析，从未使用
```

待优化项：
1. **删除 `t_cn_cnm1`**：从未使用。

---

## 第三层：核心算法层

### `core/pipeline.py`

调用脉络：
```
evaluate_vloc_bundle_core(bundle, config) → BundleEvaluationResult
  ├─ sf_nav_to_body_ned_trajectory()      # nav → body/NED
  ├─ sf_vloc_to_body_ned_trajectory()     # vloc → body/NED
  ├─ 按 vloc_mode > 1 过滤
  └─ evaluate_trajectory_result()         # 核心评估
      ├─ prepare_evaluation_trajectories()   # 时间同步
      ├─ detect_associated_discontinuities() # 断点检测
      ├─ identity_alignment()                # VLOC 不对齐
      └─ 计算 ATE/RPE/summary

evaluate_vo_bundle_core(bundle, config) → BundleEvaluationResult
  ├─ sf_nav_to_camera_trajectory()        # nav → camera pose
  ├─ vo_valid_segment_indices()           # 按 reset_count 分段
  └─ evaluate_trajectory_result()
      ├─ prepare_evaluation_trajectories()
      ├─ detect_associated_discontinuities()
      ├─ sim3_alignment()                    # VO 逐段 Sim3
      └─ 计算 ATE/RPE/scale/summary
```

待优化项：
1. **删除 `evaluate_trajectories` 函数**：与 reports 层重复。
2. **简化或删除 `normalized_*_evaluation_config`**：只是 `replace(config)`。

### `core/config.py`

调用脉络：
```
@dataclass EvaluationConfig:
  rpe_delta_frames: int = 1
  rpe_delta_value: float | None = None
  rpe_delta_unit: str = "frames"
  rpe_distance_tolerance_ratio: float = 0.05
  scale_delta_value: float | None = None
  scale_delta_unit: str = "frames"
  scale_distance_tolerance_ratio: float = 0.05

  __post_init__(): 参数验证
```

待优化项：
1. **合并 `scale_delta_*` 与 `rpe_delta_*`**：CLI 总设为相同值。
2. **删除 `rpe_delta_frames`**：死代码。
3. **删除 `distance_tolerance_ratio`**：计算但从未使用。
4. **简化验证函数**：字段精简后可能不需要。

### `core/alignment.py`

调用脉络：
```
identity_alignment() → dict           # 返回单位变换（VLOC 用）
sim3_alignment(gt_pos, est_pos) → dict  # VO Sim3 对齐
  └─ umeyama_alignment(src, dst) → (scale, rot, trans)  # SVD 核心算法
apply_alignment(positions, alignment) → positions  # 应用位置对齐
apply_rotation_alignment(rotations, alignment) → rotations  # 应用旋转对齐
alignment_export_columns(alignment, count, prefix) → dict  # 导出列
aggregate_alignment(alignments, mode) → dict  # 聚合多段对齐
```

待优化项：
1. **删除 `identity_alignment()`**：VLOC 应跳过对齐，不该用单位变换占位。
2. **合并 `apply_alignment()` 和 `apply_rotation_alignment()`**：输入总有位置和姿态。
3. **删除 `alignment_export_columns()`**：未来不需要导出。
4. **删除 `aggregate_alignment()`**：未来不需要。
5. **保留 `sim3_alignment()` 和 `umeyama_alignment()`**：核心算法。

### `core/interpolation.py`

调用脉络：
```
prepare_evaluation_trajectories(gt, est, max_interpolation_gap_s)
  └─ interpolate_reference_to_estimate()
      ├─ _unique_timestamp_trajectory()   # 去重时间戳
      ├─ interpolation_brackets()         # 计算左右样本和 alpha
      ├─ interpolate_positions_from_brackets()  # 位置线性插值
      └─ interpolate_rotations_from_brackets()  # 旋转 SLERP
          └─ slerp_quaternion()

subset_trajectory(traj, indices)          # 按索引截取轨迹

extra_values_linear/nearest/trajectory_extra_or_nan  # 供 comparison.py 构建状态帧
  └─ nearest_indices_for_stamps()
```

待优化项：
1. **精简 `info` dict（第 153-196 行）**：40+ 字段中大量重复。pipeline.py 只用 3 个字段（`matches`, `dropped`, `max_used_gt_gap_s`）用于 debug log。
   - 删除重复命名：`matches`/`matched_count`、`dropped`/`dropped_count` 等
   - 删除冗余统计：`p95_*`、`median_*` 等可按需在前端计算
   - 建议保留：`matches`, `dropped`, `max_gt_gap_s`, `mean_gt_gap_s`, `coverage_ratio`, 各项 dropped 原因计数

### `core/statistics.py`

调用脉络：
```
path_distance(positions) → np.ndarray            # 累计路程
describe(values) → dict                          # 统计描述（RMSE/mean/std 等）

normalize_rpe_delta_config(cfg) → dict           # 规范化 RPE 配置
normalize_scale_delta_config(cfg) → dict         # 规范化 scale 配置

rpe_frame_dataframe(...) → pd.DataFrame          # RPE 明细表
scale_frame_dataframe(...) → pd.DataFrame        # 尺度明细表
```

待优化项：
1. **`rpe_frame_dataframe` 的 `distance_tolerance_ratio` 逻辑已死**：meters 模式已改用 evo 口径（第 214-217 行），tolerance 窗口逻辑被注释掉（第 218-222 行），但参数仍被计算（第 171-173 行）和写入 DataFrame（第 256-257 行）。
2. **`normalize_rpe_delta_config` 和 `normalize_scale_delta_config` 可以合并**：两个函数结构几乎相同，仅字段名前缀不同。甚至可以删掉。
3. **仔细研究`rpe_frame_dataframe`与`scale_frame_dataframe`**的作用。

### `core/segments.py`

调用脉络：
```
vo_valid_segment_indices(vo) → (valid_indices, segment_ids, filter_info)
  # 按 reset_count 分段，过滤短段（<10s 或 <200帧）

detect_associated_discontinuities(stamps, gt_pos, est_pos, ...)
  # 检测轨迹跳变/断点
  └─ segments_from_breaks()
```

待优化项：
无明显待优化项。

### `core/geometry.py`

调用脉络：
```
坐标变换：
  sf_nav_to_body_ned_trajectory(nav, home_point) → Trajectory
  sf_vloc_to_body_ned_trajectory(vloc, home_point, calibration) → Trajectory
  sf_nav_to_camera_trajectory(nav, calibration) → Trajectory
  geodetic_to_ned(...) → NED 坐标
  geodetic_to_ecef(...) → ECEF 坐标

旋转工具：
  euler_yaw_pitch_roll_from_matrix(rotations) → ypr
  euler_yaw_pitch_roll_to_matrix(yaw, pitch, roll) → rotations
  quaternion_to_matrix(qx, qy, qz, qw) → rotations
  matrix_to_quaternion(rot) → (qx, qy, qz, qw)
  rotation_angle(rot) → float
  yaw_from_rot(rotations) → yaw
  wrap_pi(values) → normalized angles

内部辅助：
  _required_extra(traj, key) → np.ndarray
```

待优化项：
无明显待优化项。

### `core/errors.py`

调用脉络：
```
relative_error(gt_pos, est_pos, gt_rot, est_rot, i, j) → (trans_error, rot_error)
  └─ relative_pose(r_i, p_i, r_j, p_j) → (rel_rot, rel_trans)

rotation_errors(gt_rot, est_rot) → np.ndarray  # 每帧姿态误差（弧度）
```

待优化项：
无明显待优化项。

---

## 第四层：报告输出层

（尚未梳理）
