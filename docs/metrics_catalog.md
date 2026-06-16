# VO 评估指标清单

本项目的指标口径参考了工作区内几篇基准论文：

- Sturm et al. 2012：RPE 衡量局部相对运动漂移，ATE 衡量对齐后的全局轨迹一致性。
- Geiger et al. 2012 / KITTI：不要只看终点误差，应按不同子轨迹长度和速度统计平移、旋转误差。
- Zhang and Scaramuzza 2018：评估前必须根据传感器可观性选择合适轨迹对齐方式，例如 SE3、Sim3 或首帧对齐。
- Schubert et al. 2018 / TUM VI：长序列需要关注是否发散、是否完整跟踪，以及起止段的误差。
- Delmerico and Scaramuzza 2018：飞行机器人部署还要评估 CPU、内存、每帧处理时间和鲁棒性。

## 一等指标

| 指标 | 输出 | 作用 | 物流无人机调整 |
| --- | --- | --- | --- |
| ATE 位置误差 | RMSE、mean、median、p95、p99、max | 全局轨迹一致性 | 长航程应同时看 `error / route length`，避免只看绝对米数 |
| RPE 固定间隔误差 | 固定帧间隔 Δ 的平移/旋转 RMSE | 局部漂移 | 用于观察连续视觉里程计是否稳定 |
| 按距离子轨迹误差 | 不同距离段的平移误差百分比、旋转 deg/m | KITTI/rpg 风格漂移指标 | 默认 50、100、200、500、1000、2000、5000 m，更适合长路线 |
| 终点漂移 | 终点误差 m、占总路程 % | 配送任务最终落点偏差 | 长距离任务必须单列 |
| 尺度误差 | Sim3 scale、raw path scale ratio、分段 scale ratio | 检查单目尺度漂移 | 单目 VO 必看，双目/VIO 也可用于发现标定问题 |
| 覆盖率/成功率 | matched poses、coverage ratio | 是否跑完整条路线 | 长航程中失败一次就可能不可用 |
| 发散点 | 首次超过阈值的时间、距离、误差 | 发现何处开始不可控漂移 | 阈值同时采用绝对米数和随路程增长的相对阈值 |
| 海拔/垂直误差 | z 误差 RMSE、bias、p95、max | 无人机高度安全 | 必须与水平误差分开看 |
| 水平误差 | XY 平面误差 RMSE、p95 | 投递/航线偏差 | 对任务区、航线走廊更直接 |
| 姿态/航向误差 | orientation/yaw error | 航向控制和相机朝向 | 若输出有四元数或旋转矩阵，则纳入 |

## 二等指标

| 指标 | 输出 | 作用 |
| --- | --- | --- |
| 速度分箱误差 | 不同速度区间的平移误差 % | 发现高速巡航、低速悬停、加减速下的失效模式 |
| 长航程滚动窗口误差 | error vs distance 曲线、分段 p95 | 发现误差是否随距离线性/非线性增长 |
| Runtime/资源 | per-frame ms、FPS、CPU、memory | 判断能否部署到机载计算平台 |
| 缺失/时间关联质量 | 最大时间差、平均时间差、匹配数量 | 判断 VO 输出和 GT 是否可比 |
| 场景条件分组 | 白天/夜间、低纹理、强风、转弯、起降 | 如果有路线标签，可做分组鲁棒性评估 |

## 关键计算方式

| 输出字段 | 计算方式 |
| --- | --- |
| `ate_position_m` | GT 与对齐后估计位置逐点差的 L2 范数，再统计 RMSE/mean/median/std/min/max/p95/p99 |
| `ate_horizontal_m` | 只取 XY 方向位置差的 L2 范数 |
| `ate_vertical_m` | `est_z_aligned - gt_z`，用于看高度偏差 |
| `ate_orientation_deg` | 对齐后 `R_est * R_gt^-1` 的旋转角，单位 deg |
| `ate_yaw_deg` | 对齐后 yaw 角差，wrap 到 `[-pi, pi]` 后转 deg |
| `rpe_frame_delta.translation_m` | 固定帧间隔 Δ 上，估计相对位姿与 GT 相对位姿的平移误差 |
| `rpe_frame_delta.rotation_deg` | 同一相对位姿误差的旋转角 |
| `segment_errors.translation_error_percent` | 固定目标段长 `L` 上的 `100 * trans_error / L` |
| `segment_errors.rotation_error_deg_per_m` | 固定目标段长 `L` 上的 `rot_error_deg / L` |
| `segment_errors.scale_ratio_est_over_gt` | 估计轨迹段累计长度 / GT 实际轨迹段累计长度 |
| `segment_errors.scale_drift_percent` | `(scale_ratio_est_over_gt - 1) * 100` |
| `speed_bins` | 将子轨迹记录按速度分箱后，对平移百分比和旋转 deg/m 做统计 |
| `endpoint_error_m` | 最后一个匹配位姿的 ATE 位置误差 |
| `coverage_ratio` | `matched_poses / gt_poses` |
| `divergence` | 当 ATE 超过 `max(abs_threshold, distance * rel_threshold_percent / 100)` 时记为发散 |

## 对齐方式建议

| 传感器/算法 | 默认对齐 |
| --- | --- |
| 单目 VO，尺度不可观 | Sim3 |
| 双目 VO、RGB-D、VIO，尺度已知 | SE3 |
| 想看漂移随距离增长 | 首帧对齐 |
| 两个轨迹已经在同一世界系 | 不对齐或首帧对齐 |

## 当前工具支持的输入

- TUM：`timestamp tx ty tz qx qy qz qw`
- KITTI：每行 12 个数，3x4 位姿矩阵
- CSV/TSV：表头中包含 `time/timestamp/frame`、`x/y/z`，可选 `qx/qy/qz/qw`；支持 EuRoC 风格 `p_RS_R_x/y/z` 与 `q_RS_w/x/y/z`
- XYZ：`x y z` 或 `timestamp x y z`
- 时间戳单位：表头中的 `[ns]`、`[us]`、`[ms]` 会自动换算到秒；无表头时按时间戳数量级和相邻步长推断常见纳秒/微秒格式
