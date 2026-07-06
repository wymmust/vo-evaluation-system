# 开源评估工具口径对照

## 当前保留的对照来源

- TUM RGB-D benchmark：ATE/RPE 的基本定义。
- evo：Sim3 Umeyama 对齐、固定帧数/固定距离 RPE 的 consecutive pairs 口径。
- Zhang and Scaramuzza 2018：尺度可观性和 Sim3/SE3 选择的评估背景。

## 当前系统输出指标

| 输出字段 | 当前计算方式 | 对照来源 | 说明 |
| --- | --- | --- | --- |
| `association.matches` | GT 插值到 VO/VLOC 时间戳，丢弃 GT 范围外或 GT 插值间隔超过 1.0 s 的估计帧 | 工程同步扩展 | 服务 ATE/RPE 可比性 |
| `alignment.scale/rotation/translation` | VO 固定 Sim3，VLOC 固定不对齐 | evo `-as` / Umeyama | VLOC 有真实尺度，不做 Sim3 |
| `ate_position_m` | `||p_est_aligned - p_gt||` | TUM ATE | 额外输出 p95/p99 |
| `ate_horizontal_m` | `sqrt(dx^2 + dy^2)` | 无官方单项 | 无人机水平航线偏差扩展 |
| `ate_vertical_m` | `abs(z_est_aligned - z_gt)` | 无官方单项 | 无人机高度安全扩展 |
| `ate_orientation_deg` | 旋转矩阵误差角 | TUM/evo 姿态误差语境 | 输入含旋转时计算 |
| `ate_yaw_deg` | yaw 差 wrap 到 `[-pi, pi]` | 航向误差工程扩展 | 用于看航向偏差 |
| `rpe_frame_delta.translation_m` | 固定帧数或固定距离的相对位姿平移误差 | TUM RPE / evo consecutive pairs | 距离模式按起点向后找第一段满足目标距离的 pair |
| `rpe_frame_delta.rotation_deg` | 同一相对位姿误差的旋转角 | TUM RPE / evo | 输入含旋转时计算 |
| `scale_frame_delta` | 固定帧数或距离窗口的局部 GT/VO 路程比 | evo/rpg 尺度分析背景 | 当前只在 VO 端展示 |
| `summary.gt_pose_coverage_ratio` | 有效评估窗口时长 / 原始 GT 时长 | 长序列完整性工程扩展 | 不再输出旧 `coverage_ratio` |

## 已删除的旧版扩展

旧版中的子轨迹 `segment_errors`、速度分箱 `speed_bins`、Top-K `worst_segments`、终点漂移、发散检测和 runtime 自动统计已经不属于当前需求文档范围，代码和前端不再生成这些字段。
