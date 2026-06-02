# 开源评估工具口径对照

## 参考的开源/官方实现

- TUM RGB-D benchmark tools：`associate.py`、`evaluate_ate.py`、`evaluate_rpe.py`
  - 工具页：https://cvg.cit.tum.de/data/datasets/rgbd-dataset/tools
  - SVN 源码：https://svncvpr.in.tum.de/svn/cvpr-ros-pkg/trunk/rgbd_benchmark/rgbd_benchmark_tools/src/rgbd_benchmark_tools/
- KITTI odometry benchmark/devkit
  - 官方说明：https://www.cvlibs.net/datasets/kitti/eval_odometry.php
  - Python 复现参考：https://github.com/LeoQLi/KITTI_odometry_evaluation_tool
- rpg_trajectory_evaluation
  - 仓库：https://github.com/edgar-explorer/rpg_trajectory_evaluation

## 当前系统输出指标

| 输出字段 | 计算方式 | 对照来源 | 当前实现状态 |
| --- | --- | --- | --- |
| `association.matches` | 时间差小于阈值的 GT/VO 候选按差值排序，贪心一对一匹配 | TUM `associate.py` | 已改为 TUM 口径 |
| `alignment.scale/rotation/translation` | 将估计轨迹对齐到 GT；SE3 用 Horn/SVD，Sim3 用 Umeyama scale | TUM `evaluate_ate.py`、rpg/evo | 已实现 |
| `ate_position_m` | `||p_est_aligned - p_gt||`，输出 RMSE/mean/median/std/min/max/p95/p99 | TUM `evaluate_ate.py` | 核心统计一致，额外给 p95/p99 |
| `ate_horizontal_m` | `sqrt(dx^2 + dy^2)` | 无官方单项，是无人机场景拆分 | 保留扩展指标 |
| `ate_vertical_m` | `dz = z_est_aligned - z_gt` | 无官方单项，是无人机场景拆分 | 保留扩展指标 |
| `ate_orientation_deg` | `angle(R_est_aligned * R_gt^-1)` | rpg `compute_absolute_error` | 已实现 |
| `ate_yaw_deg` | yaw 差，wrap 到 `[-pi, pi]` | rpg relative yaw 思路 | 已实现 |
| `rpe_frame_delta.translation_m` | 固定帧间隔 Δ 的相对位姿误差平移范数 | TUM `evaluate_rpe.py --fixed_delta --delta_unit f` | 已实现 |
| `rpe_frame_delta.rotation_deg` | 固定帧间隔 Δ 的相对位姿误差旋转角 | TUM `evaluate_rpe.py` | 已实现 |
| `segment_errors.translation_error_percent` | 固定目标段长 `L`，`100 * trans_error / L` | KITTI devkit / rpg relative error | 已按固定目标段长修正 |
| `segment_errors.rotation_error_deg_per_m` | 固定目标段长 `L`，`rot_error_deg / L` | KITTI devkit | 已按固定目标段长修正 |
| `segment_errors.scale_ratio_est_over_gt` | 估计段累计长度 / GT 实际段累计长度 | rpg scale drift 思路 | 已实现 |
| `segment_errors.scale_drift_percent` | `(scale_ratio - 1) * 100` | rpg scale drift 思路 | 已新增 |
| `speed_bins` | 按子轨迹速度分箱后统计 translation % / rotation deg/m | KITTI speed plots | 已实现，速度用时间戳泛化 |
| `endpoint_error_m` | 最后一个匹配位姿的 3D ATE | 常用工程指标 | 保留扩展指标 |
| `coverage_ratio` | `matched_poses / gt_poses` | TUM VI/长序列鲁棒性思想 | 保留扩展指标 |
| `divergence` | ATE 超过绝对阈值或相对路程阈值即发散 | TUM VI divergence 思路 | 保留扩展指标 |
| `runtime` | 对 CSV 中 `process_time_ms/fps/cpu_percent/memory_mb` 等列做统计 | Delmerico flying robot benchmark | 保留扩展指标 |

## 与第一版相比已修正的出入

1. 时间关联：第一版采用 nearest timestamp 顺序扫描。现在改为 TUM 官方工具的候选排序 + 贪心一对一匹配。
2. 子轨迹误差分母：第一版使用实际段长 `actual_length`。现在按 KITTI/rpg 口径使用目标段长 `L`，即 `translation_error_percent = 100 * error / L`、`rotation_error_deg_per_m = rot_deg / L`。
3. 子轨迹起点采样：第一版默认每一帧都做起点。现在默认每 10 帧取一个起点，匹配 KITTI devkit；界面中可调回 1。
4. 子轨迹长度容差：加入 rpg 默认的 `0.2 * L` 容差思想，避免轨迹稀疏时把长度偏差过大的段纳入统计。
5. 尺度漂移：第一版只输出 ratio。现在同时输出 `scale_drift_percent`，更接近 rpg 的 scale drift 表达。

