# VO/VLOC 评估指标清单

当前主版本只保留固定 SF VO、固定 SF VLOC 和 TUM 调试格式，不再维护旧版自适应格式、子轨迹 Top-K、速度分箱、发散检测或 runtime 自动统计。

## 通用指标

| 指标 | 输出字段 | 计算方式 | 用途 |
| --- | --- | --- | --- |
| ATE 位置误差 | `ate_position_m` | `||p_est_aligned - p_gt||` 后做 `describe()` | 看整体轨迹位置一致性 |
| ATE 水平误差 | `ate_horizontal_m` | `sqrt(dx^2 + dy^2)` | 看水平投递/航线偏差 |
| ATE 垂直误差 | `ate_vertical_m` | `abs(z_est_aligned - z_gt)` | 看高度方向误差 |
| 姿态误差 | `ate_orientation_deg` | 旋转矩阵误差角 | 看整体姿态一致性 |
| yaw 误差 | `ate_yaw_deg` | yaw 差 wrap 到 `[-pi, pi]` | 看航向漂移 |
| RPE | `rpe_frame_delta` | 按帧数或距离间隔计算相对位姿误差 | 看局部漂移 |
| 覆盖率 | `summary.gt_pose_coverage_ratio`、`summary.est_pose_coverage_ratio` | 已评估时长/GT 时长，已评估估计位姿数/原始估计位姿数 | 看日志是否覆盖有效飞行段 |
| 断点诊断 | `discontinuities` | 按时间间隔、GT 步长、估计步长判断大跳变 | 提示 reset 或日志中断 |

## VO 专用

| 指标 | 输出字段 | 计算方式 | 用途 |
| --- | --- | --- | --- |
| Sim3 对齐 | `alignment` | Umeyama 相似变换估计 `scale/R/t` | 单目 VO 尺度与坐标对齐 |
| Raw 尺度比 | `summary.raw_path_scale_ratio_est_over_gt` | 原始 VO 路程 / GT 路程 | 判断原始 VO 是否无尺度 |
| 局部尺度 | `scale_frame_delta`、`scale_per_frame` | 按左侧尺度图间隔计算局部 GT/VO 路程比 | 看尺度是否随时间漂移 |

## VLOC 专用

| 指标 | 输出字段 | 计算方式 | 用途 |
| --- | --- | --- | --- |
| 水平平均误差 | `summary.mean_error_pos_xy` | VLOC/NAV 水平误差范数平均 | 看水平定位质量 |
| 垂直平均误差 | `summary.mean_error_pos_z` | 垂直误差绝对值平均 | 看高度质量 |
| 欧拉角平均误差 | `summary.mean_error_euler` | yaw/pitch/roll 误差三维范数平均 | 看姿态质量 |
| 水平最大误差 | `summary.max_error_pos_xy` | 水平误差范数最大值 | 找最差水平定位点 |
| 垂直最大误差 | `summary.max_error_pos_z` | 垂直误差绝对值最大值 | 找最差高度点 |
| 欧拉角最大误差 | `summary.max_error_euler` | yaw/pitch/roll 误差三维范数最大值 | 找最差姿态点 |

## 统计口径

`describe()` 输出 `count/rmse/mean/median/std/min/max/p95/p99`。其中 `std` 使用 NumPy 默认 `ddof=0`，这是当前项目固定统计口径。
