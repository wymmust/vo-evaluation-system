# VO Evaluation System

一个用于视觉里程计（VO/VIO/SLAM trajectory）结果评估的本地 Python 工具。目标流程是：把 ground truth 和 VO 输出轨迹拖进页面，得到指标表、轨迹可视化、误差曲线、子轨迹漂移统计，并导出 HTML/JSON/CSV 报告。

## 运行

```bash
python3 -m pip install -r requirements.txt
streamlit run app.py
```

## 公网部署

这个项目是 Streamlit/Python 应用，需要部署到能运行 Python 服务的平台；GitHub Pages 只能托管静态网页，不能直接运行本工具。

## 纯静态网页版本

如果不想维护 Python 服务，可以直接部署 `static_web/` 文件夹。这个版本用 Pyodide 在浏览器里运行 Python 评估代码，用户上传的轨迹文件只在浏览器内处理，不需要后端服务器。

本地预览：

```bash
cd static_web
python3 -m http.server 8765
```

然后打开 `http://localhost:8765/`。不要直接双击 `index.html`，因为浏览器通常会限制本地文件读取，导致 Pyodide 或评估代码无法加载。

公网部署时，把 `static_web/` 文件夹上传到任意静态网站托管平台即可，例如 Netlify、Vercel、Cloudflare Pages、对象存储静态站点或普通 Nginx 静态目录。这个静态版首次打开会下载 Pyodide、numpy、pandas 和 Plotly，首屏加载比 Streamlit 版慢一些；超大日志也会受浏览器内存限制。

静态版如果出现 `Failed to fetch`，优先检查三点：

- 当前地址必须是 `http://...` 或 `https://...`，不能是 `file://.../index.html`。
- 本地预览时 `python3 -m http.server 8765` 必须保持运行。
- 公网部署时必须把 `static_web/py/` 目录和 `index.html` 一起上传，并确认浏览器可以访问 Pyodide CDN。

推荐方式一：Streamlit Community Cloud

1. 打开 Streamlit Community Cloud，新建 app。
2. 选择 GitHub 仓库 `wymmust/vo-evaluation-system`。
3. Main file path 填 `app.py`。
4. 部署完成后，平台会生成一个公网 URL，任何人都可以通过该 URL 上传自己的 GT/VO 文件并查看评估结果。

推荐方式二：Docker 平台

仓库已经包含 `Dockerfile`，可部署到 Render、Railway、Fly.io 或任意支持 Docker 的服务器。容器启动后监听 `8501` 端口。

本地 Docker 验证：

```bash
docker build -t vo-evaluation-system .
docker run --rm -p 8501:8501 vo-evaluation-system
```

部署注意事项：

- 不要把飞行日志、测试数据或导出报告提交到仓库；`.gitignore` 和 `.dockerignore` 已经默认排除这些文件。
- 上传文件大小默认上限为 200 MB，可在 `.streamlit/config.toml` 中调整 `maxUploadSize`。
- 如果要让所有人访问应用，部署平台上的访问权限需要设置为 public。

## 支持格式

- TUM：`timestamp tx ty tz qx qy qz qw`
- KITTI odometry：每行 12 个数，表示 3x4 pose matrix
- CSV/TSV：需要有 `x/y/z` 列，可选 `timestamp/time/frame` 和 `qx/qy/qz/qw`；支持 EuRoC 风格的 `p_RS_R_x/y/z` 与 `q_RS_w/x/y/z`
- 注释表头空格表：例如 `# ts x y z yaw pitch roll ...`，会忽略其他列；注释中有 `弧度/rad` 或 `角度/deg` 时会自动换算姿态单位
- XYZ：`x y z` 或 `timestamp x y z`
- 时间戳单位：表头含 `[ns]`、`[us]`、`[ms]` 时会统一换算到秒；无表头时会根据时间戳数量级和相邻步长推断常见纳秒/微秒格式

## 已实现指标

- ATE 位置误差：RMSE、mean、median、p95、p99、max
- ATE 水平误差、垂直/海拔误差
- 姿态误差和 yaw 误差（当输入含旋转时）
- RPE 固定帧间隔误差
- 按距离的 KITTI/rpg 风格子轨迹误差：平移百分比、旋转 deg/m、分段尺度比、尺度漂移百分比
- 终点漂移和占总路程比例
- 覆盖率、时间关联质量、匹配位姿数
- 发散检测：绝对阈值和随航程增长的相对阈值
- 速度分箱误差
- 可选 runtime 统计：CSV 中如有 `process_time_ms`、`fps`、`cpu_percent`、`memory_mb` 等列会自动汇总

## 与开源基准口径保持一致的实现点

- 默认时间同步方式是把 Ground Truth 插值到 VO 时间戳，适合 IMU/GT 连续记录、VO 只在算法运行期间输出，以及两者同频但相位错开的情况。
- 也保留 TUM RGB-D `associate.py` 的贪心最近邻匹配口径：先生成时间差小于阈值的候选，再按时间差从小到大做一对一匹配。
- ATE 使用 TUM RGB-D `evaluate_ate.py` 的 Horn/SVD 刚体对齐口径；单目尺度未知时可切换到 rpg/evo 常用的 Sim3 对齐。
- RPE 固定帧间隔使用 TUM `evaluate_rpe.py --fixed_delta --delta_unit f` 对应口径。
- 子轨迹误差使用 KITTI 的固定目标长度分母，默认每 10 帧取一个起点；同时加入 rpg 的长度容差思想，避免稀疏轨迹中把相差过大的段纳入统计。

## 时间同步方式

- `GT插值到VO时间戳`：默认推荐。评估点完全以 VO 输出时间戳为准，只取落在 GT 时间范围内的 VO 点；GT 位置线性插值，GT 姿态使用 SLERP 插值。比如 GT 为 `0.1/0.3/0.5`，VO 为 `0.2/0.4/0.6`，会在 `0.2/0.4/0.6` 处插值得到 GT。
- `TUM最近邻时间戳匹配`：用于复现 TUM RGB-D benchmark 的关联口径。只有时间差小于阈值的 GT/VO 位姿才会配对；如果两条轨迹同频但整体错半个采样周期，需要把阈值放大，否则会匹配不到。
- `按索引匹配`：忽略时间戳，只按行号配对，适合无时间戳或已经预同步的数据。

`GT 插值最大间隔 s` 用于避免 GT 中间长时间缺失时仍跨大间隔插值；填 `-1` 表示不限制。

## 对齐方式

- `SE3`：尺度已知时推荐，例如双目 VO、RGB-D、VIO。
- `Sim3`：单目 VO 或尺度未知时使用。
- `首帧对齐`：适合看误差如何随长航程累积。
- `不对齐`：当两条轨迹已在同一坐标系下使用。

## IMU 长时间记录与 VO 时间段

如果 ground truth 像 IMU 日志一样从开机开始持续记录，而 VO 只在算法运行期间输出，系统会以 VO 时间戳为基准，把 GT/IMU 插值到 VO 的每一个时间戳。默认策略是“按 VO 时间戳统一评估”：VO 有 2400 个时间戳，就只评估这 2400 个 VO 时刻，其他 IMU 记录不进入统计。断点检测只作为诊断提示，不会默认丢弃匹配点。

## 数据文件

仓库不包含测试数据、飞行日志、导出报告或轨迹样例。请在本地页面中上传自己的 ground truth 与 VO 输出文件运行评估。

## 指标与 evaluator.py 代码总表

本表是 `README.md` 和 `vo_eval/evaluator.py` 的统一索引。代码内同一份索引位于 `METRIC_CODE_MAP`；如果后续新增或改名 `report` 指标，需要同时更新 `METRIC_CODE_MAP` 和本表。

| 指标 / 报告项 | report 字段 | evaluator.py 对应代码 | README 详细说明 |
| --- | --- | --- | --- |
| 时间同步 / GT 插值到 VO | `report["association"]` | `prepare_evaluation_trajectories()`、`build_associated_trajectories()`、`interpolate_reference_to_estimate()`、`associate_trajectories()` | `时间同步方式`、`#13 时间同步`、`HTML 调参报告新增参数与代码/公式对应 / 时间同步诊断细项` |
| 轨迹对齐 / 对齐尺度 | `report["alignment"]` | `compute_alignment()`、`umeyama_alignment()`、`aggregate_alignment()`、`apply_alignment()` | `对齐方式`、`#09 对齐尺度`、`尺度比与尺度漂移` |
| VO 姿态修正 | `report["orientation_correction"]` | `select_orientation_correction()`、`score_orientation_correction_candidate()`、`apply_orientation_correction()` | `#14 姿态修正`、`HTML 调参报告新增参数与代码/公式对应 / Attitude / yaw RMSE` |
| ATE 三维位置误差 | `report["ate_position_m"]`、`report["ate"]["primary_position_m"]` | `evaluate_trajectories()` 中的 `errors` / `pos_error_m`，以及 `describe()`、`build_ate_report()` | `#01 ATE RMSE`、`ATE 绝对轨迹误差` |
| ATE 水平误差 | `report["ate_horizontal_m"]` | `evaluate_trajectories()` 中的 `horizontal_error_m = norm(errors[:, :2])`，以及 `describe()` | `ATE 水平误差、垂直/海拔误差`、`误差随路程变化` |
| ATE 垂直 / 高度误差 | `report["ate_vertical_m"]`、`vertical_error_signed_m`、`vertical_error_abs_m` | `evaluate_trajectories()` 中的 `vertical_error_signed_m = errors[:, 2]`，以及 `describe()` | `#05 垂直 RMSE`、`高度与垂直误差` |
| ATE 姿态误差 | `report["ate_orientation_deg"]` | `rotation_errors()`、`apply_rotation_alignment()`、`describe()` | `HTML 调参报告新增参数与代码/公式对应 / Attitude / yaw RMSE` |
| ATE yaw 航向误差 | `report["ate_yaw_deg"]`、`yaw_error_signed_deg`、`yaw_error_abs_deg` | `yaw_from_rot()`、`wrap_pi()`、`describe()` | `HTML 调参报告新增参数与代码/公式对应 / Attitude / yaw RMSE` |
| RPE 固定帧间隔误差 | `report["rpe_frame_delta"]` | `rpe_error_arrays()`、`relative_error()`、`describe()` | `#02 RPE RMSE`、`RPE 相对位姿误差` |
| RPE 固定时间间隔误差 | `report["rpe_time_delta"]` | `rpe_error_arrays_by_time()`、`nearest_time_index()`、`summarize_time_rpe()` | `HTML 调参报告新增参数与代码/公式对应 / 固定时间 RPE` |
| 按距离子轨迹平移 / 旋转 / 尺度误差 | `report["segment_errors"]` | `segment_errors()`、`find_segment_end()`、`relative_error()`、`summarize_segment_records()` | `按距离子轨迹误差`、`HTML 调参报告新增参数与代码/公式对应 / 长航程子轨迹表新增列` |
| 每个子轨迹明细 | `report["segment_records"]` | `segment_errors()` 生成 records，`summarize_segment_records()` 聚合 | `HTML 调参报告新增参数与代码/公式对应 / Top-K 最差片段` |
| 速度分箱误差 | `report["speed_bins"]` | `summarize_by_speed_bins()`、`describe_clean()` | `速度分箱误差`、`HTML 调参报告新增参数与代码/公式对应 / 条件诊断` |
| 最差片段 Top-K | `report["worst_segments"]` | `build_worst_segments()` | `HTML 调参报告新增参数与代码/公式对应 / Top-K 最差片段` |
| 断点 / VO 重置 / 大跳变 | `report["discontinuities"]` | `detect_associated_discontinuities()`、`select_evaluation_segments()`、`summarize_continuity()` | `#12 断点数量`、`HTML 调参报告新增参数与代码/公式对应 / 连续性参数` |
| 发散检测 | `report["divergence"]` | `detect_divergence()`、`classify_tracking_failure()`、`classify_scale_divergence()` | `#06 发散状态`、`发散检测` |
| 航程 / 耗时 / 匹配数量 / 覆盖率 / 终点漂移 / 原始尺度比 | `report["summary"]` | `evaluate_trajectories()` 中的 `summary` dict，`path_distance()`、`_gt_coverage_ratio()` | `#03 终点漂移`、`#04 长航程路程`、`#07 GT 覆盖率`、`#08 Raw 尺度比`、`#10 匹配位姿`、`#11 VO 匹配率`、`#15 耗时` |
| runtime / CPU / 内存 / FPS | `report["runtime"]` | `summarize_runtime()`、`describe()` | `Runtime / 耗时统计` |
| 逐帧误差和轨迹可视化数据 | `report["per_pose"]` | `evaluate_trajectories()` 中的 `per_pose` DataFrame | `误差随路程变化`、`高度与垂直误差` |
| 统计口径 count/rmse/mean/median/std/min/max/p95/p99 | 所有 `describe(...)` 指标汇总 | `describe()`、`describe_clean()` | `运行结果截图指标卡与代码/公式对应`、`Runtime / 耗时统计` |

## 运行结果截图指标卡与代码/公式对应

本节对应页面第一屏 `EVALUATION SUMMARY / 运行结果` 的 15 个卡片。前端卡片由 `vo-evaluation-system/static_web/app.js:242-268` 生成，后端指标主要由 `vo-evaluation-system/vo_eval/evaluator.py:evaluate_trajectories()` 生成。所有 `rmse/mean/median/std/min/max/p95/p99` 统计最终都走 `describe()`：

```python
"rmse": float(np.sqrt(np.mean(arr * arr)))
```

位置类指标先把 VO 位置对齐到 GT 坐标系：

$$
\hat{\mathbf{p}}_i^{vo}=s\mathbf{R}\mathbf{p}_i^{vo}+\mathbf{t}
$$

对应代码：

```python
return scale * (positions @ rot.T) + trans
```

其中 `s/R/t` 来自 `compute_alignment()` 和 `umeyama_alignment()`；`SE3` 固定 `scale=1`，`Sim3` 会估计全局尺度。

### #01 ATE RMSE

- 前端取值：`value: ate.rmse`，其中 `ate = report.ate_position_m || {}`。
- 后端字段：`report["ate_position_m"]["rmse"]`。
- 后端代码：`errors = est_pos_aligned - gt_pos`，`pos_error_m = np.linalg.norm(errors, axis=1)`，`"ate_position_m": describe(pos_error_m)`。
- 公式：

$$
e_i^{ATE}=\left\|\hat{\mathbf{p}}_i^{vo}-\mathbf{p}_i^{gt}\right\|_2
$$

$$
ATE_{RMSE}=\sqrt{\frac{1}{N}\sum_{i=1}^{N}(e_i^{ATE})^2}
$$

- 含义：整条轨迹对齐后的全局位置一致性，数值越小越好；截图里的 `0.11 % 路程` 来自 `100 * ATE_RMSE / summary.gt_path_length_m`。
- 偏高时怎么改：先检查时间同步和时间戳单位，再看坐标系/外参、对齐方式 `SE3/Sim3`、尺度来源、轨迹异常点、后端优化和闭环约束。如果 `Sim3` 下 ATE 很低但 `Raw 尺度比` 异常，说明形状能对上，但原始 VO 没有真实尺度。

### #02 RPE RMSE

- 前端取值：`value: rpe.rmse`，其中 `rpe = report.rpe_frame_delta?.translation_m || {}`；卡片备注 `Δ=... frames` 来自 `report.rpe_frame_delta.delta_frames`。
- 后端字段：`report["rpe_frame_delta"]["translation_m"]["rmse"]`。
- 后端代码：`rpe_error_arrays(..., delta=max(1, int(cfg.rpe_delta_frames)))`，每个 `i` 取 `j=i+delta`，再调用 `relative_error()`。
- 公式：

$$
j=i+\Delta
$$

无姿态时：

$$
e_{ij}^{RPE,t}=
\left\|
(\hat{\mathbf{p}}_j^{vo}-\hat{\mathbf{p}}_i^{vo})
-
(\mathbf{p}_j^{gt}-\mathbf{p}_i^{gt})
\right\|_2
$$

有姿态时，先转到起点局部坐标系：

$$
\mathbf{t}_{ij}^{gt}=(\mathbf{R}_i^{gt})^T(\mathbf{p}_j^{gt}-\mathbf{p}_i^{gt})
$$

$$
\mathbf{t}_{ij}^{vo}=(\hat{\mathbf{R}}_i^{vo})^T(\hat{\mathbf{p}}_j^{vo}-\hat{\mathbf{p}}_i^{vo})
$$

$$
RPE_{RMSE}=\sqrt{\frac{1}{M}\sum_{k=1}^{M}(e_k^{RPE,t})^2}
$$

- 含义：固定帧间隔内的局部相对运动误差，比 ATE 更敏感于帧间抖动、短时跟踪不稳和局部运动估计错误。
- 偏高时怎么改：优先看特征跟踪、RANSAC/外点剔除、曝光/运动模糊、IMU 与相机时间同步、rolling shutter 和单帧尺度估计。可调 `rpe_delta_frames`：小 `Δ` 看单帧稳定性，大 `Δ` 看中短程累计漂移。

### #03 终点漂移

- 前端取值：`value: summary.endpoint_error_m`，备注百分比来自 `summary.endpoint_error_percent_of_path`。
- 后端字段：`report["summary"]["endpoint_error_m"]`。
- 后端代码：`endpoint_error_m = float(pos_error_m[-1])`。
- 公式：

$$
E_{end}=
\left\|
\hat{\mathbf{p}}_N^{vo}-\mathbf{p}_N^{gt}
\right\|_2
$$

$$
E_{end,pct}=100\cdot\frac{E_{end}}{L_{gt}}
$$

- 含义：最后一个匹配位姿的最终定位偏差，长航程无人机里可直接理解为终点/降落点附近的累计误差。
- 偏高时怎么改：重点检查长距离累计漂移、航向漂移、尺度漂移、后端约束、闭环/地图复用、GNSS/高度计/IMU 融合；如果只有终点高而中间不高，排查末段丢跟踪或最后几帧外点。

### #04 长航程路程

- 前端取值：`value: summary.gt_path_length_m`，备注 `${summary.duration_s} / ${summary.matched_poses} 帧`。
- 后端字段：`report["summary"]["gt_path_length_m"]`。
- 后端代码：每个评估段 `local_distance_m = path_distance(gt_pos)`，然后 `total_gt_path_m += float(local_distance_m[-1])`。
- 公式：

$$
L_{gt}=\sum_{i=1}^{N-1}\left\|\mathbf{p}_{i+1}^{gt}-\mathbf{p}_{i}^{gt}\right\|_2
$$

- 含义：本次真正参与评估的 GT 航程，是 ATE 百分比、终点漂移百分比、发散阈值和长航程子轨迹统计的分母基础。它不是误差指标，不是越高越差。
- 异常时怎么改：如果和预期飞行距离不一致，检查 GT 单位、时间戳范围、VO 是否只覆盖 GT 的一小段、`association_mode`、`time_offset_s`、`max_interpolation_gap_s` 和 `continuous_segment_policy`。

### #05 垂直 RMSE

- 前端取值：`value: vertical.rmse`，其中 `vertical = report.ate_vertical_m || {}`。
- 后端字段：`report["ate_vertical_m"]["rmse"]`。
- 后端代码：`vertical_error_signed_m = errors[:, 2]`，`vertical_error_abs_m = np.abs(vertical_error_signed_m)`，`"ate_vertical_m": describe(vertical_error_abs_m)`。
- 公式：

$$
e_i^{vertical}=\hat{z}_i^{vo}-z_i^{gt}
$$

$$
RMSE_{vertical}=\sqrt{\frac{1}{N}\sum_{i=1}^{N}(e_i^{vertical})^2}
$$

- 含义：高度方向误差。代码对 `abs(vertical)` 做统计，RMSE 与 signed vertical 的 RMSE 等价。
- 偏高时怎么改：检查 z 轴方向、ENU/NED、相机到机体外参、气压计/GNSS/高度计融合、单目尺度、地面真值高度来源和起飞高度零点。

### #06 发散状态

- 前端取值：`value: divergence.diverged ? "是" : "否"`。
- 后端字段：`report["divergence"]["diverged"]`。
- 后端代码：`detect_divergence()` 先判断 ATE 是否超过动态阈值，再合并 `tracking_failure` 和 `scale_divergence`。
- 公式：

$$
T_i=\max(T_{abs},D_i\cdot T_{rel}/100)
$$

$$
diverged_{metric}=\exists i,\quad e_i^{ATE}>T_i
$$

最终页面上的 `diverged` 是：

$$
diverged=diverged_{metric}\lor diverged_{tracking}\lor diverged_{scale}
$$

- 含义：不是单一误差值，而是综合报警：可能是 ATE 超阈值、VO 断点/重置，也可能是尺度失控。
- 显示“是”时怎么改：先看 `report.divergence.metric_divergence`、`tracking_failure`、`scale_divergence` 哪个触发。ATE 触发就查时间同步/漂移；tracking 触发就查丢跟踪、reset、输出中断；scale 触发就查尺度初始化和尺度传感器。

### #07 GT 覆盖率

- 前端取值：`100 * (summary.gt_pose_coverage_ratio ?? summary.coverage_ratio)`。
- 后端字段：`report["summary"]["gt_pose_coverage_ratio"]`。
- 后端代码：`_gt_coverage_ratio()`；`interpolate_gt` 模式按 `total_duration_s / original_gt.duration_s`，最近邻/索引模式按 `used_count / len(original_gt.positions)`。
- 公式：

插值模式：

$$
Coverage_{gt}^{time}=\frac{T_{eval}}{T_{gt}}
$$

最近邻/索引模式：

$$
Coverage_{gt}^{pose}=\frac{N_{matched}}{N_{gt}}
$$

- 含义：本次评估覆盖了 GT 的多少范围。截图里的 37.581% 表示 VO 有效窗口只覆盖 GT 全记录的一部分。
- 偏低时怎么改：如果 GT 是开机到关机全程而 VO 只跑中间一段，低覆盖率可能正常；如果不正常，检查时间戳单位、固定时间偏移 `time_offset_s`、GT/VO 起止时间、插值最大间隔和是否需要裁剪 GT。

### #08 Raw 尺度比

- 前端取值：`value: summary.raw_path_scale_ratio_est_over_gt`。
- 后端字段：`report["summary"]["raw_path_scale_ratio_est_over_gt"]`。
- 后端代码：`total_raw_est_path_m += float(path_distance(est_pos)[-1])`，最后 `total_raw_est_path_m / total_gt_path_m`。
- 公式：

$$
ScaleRatio_{raw}=\frac{L_{vo}^{raw}}{L_{gt}}
$$

$$
L_{vo}^{raw}=\sum_{i=1}^{N-1}\left\|\mathbf{p}_{i+1}^{vo}-\mathbf{p}_{i}^{vo}\right\|_2
$$

- 含义：不经过 Sim3/SE3 对齐缩放前，VO 自己输出的路程和 GT 路程的比例。1 附近表示原始尺度接近米制真实尺度。
- 偏离 1 时怎么改：单目 VO 优先检查尺度初始化、三角化基线、IMU/GNSS/高度计/双目/深度尺度源和单位换算。双目/VIO 如果也明显偏离 1，检查相机标定、baseline、IMU 噪声/重力尺度和输入坐标单位。

### #09 对齐尺度

- 前端取值：`value: report.alignment?.scale`；如果有多段，会用 `scale_min-scale_max (range%)` 作为备注。
- 后端字段：`report["alignment"]["scale"]`，以及 `scale_min/scale_max`。
- 后端代码：`compute_alignment()` 调 `umeyama_alignment()`；`Sim3` 下 `scale = sum(singular_values * sign) / var_src`，`SE3` 下 `scale = 1.0`；多段由 `aggregate_alignment()` 取平均、最小、最大。
- 公式：

$$
\min_{s,\mathbf{R},\mathbf{t}}\sum_i\left\|s\mathbf{R}\mathbf{p}_i^{vo}+\mathbf{t}-\mathbf{p}_i^{gt}\right\|^2
$$

Sim3 尺度：

$$
s=\frac{\sum_k \sigma_k q_k}{\frac{1}{N}\sum_i\left\|\mathbf{p}_i^{vo}-\bar{\mathbf{p}}^{vo}\right\|^2}
$$

尺度范围备注：

$$
ScaleRange_{pct}=100\cdot\frac{s_{max}-s_{min}}{|s|}
$$

- 含义：评估时为了把 VO 对齐到 GT 需要乘上的全局尺度。`Sim3` 可以用它看轨迹形状，但不能证明 VO 原始输出已有真实尺度。
- 异常时怎么改：尺度已知的双目/VIO 应优先看 `SE3`，如果 `Sim3 scale` 远离 1 或分段范围很大，检查尺度源、重初始化后尺度是否变化、分段坐标系是否重置、单位是否米。

### #10 匹配位姿

- 前端取值：`value: summary.matched_poses`，备注 `${summary.original_matched_poses} 原始匹配`。
- 后端字段：`report["summary"]["matched_poses"]` 和 `original_matched_poses`。
- 后端代码：`matched_poses = len(used_gt_idx)`；`original_matched_poses = original_match_count`；如果连续段策略丢弃部分片段，二者会不同。
- 公式：

```text
N_matched = count(accepted matched pose pairs)
```

- 含义：真正进入 ATE/RPE/子轨迹统计的位姿数量。样本越多，统计越稳定，但前提是时间同步正确。
- 偏低时怎么改：检查时间同步模式、时间戳单位、`time_offset_s`、`max_time_diff_s`、`max_interpolation_gap_s`、VO 输出是否中断，以及 `continuous_segment_policy` 是否只保留了部分连续段。

### #11 VO 匹配率

- 前端取值：`estCoverage = 100 * summary.est_pose_coverage_ratio`。
- 后端字段：`report["summary"]["est_pose_coverage_ratio"]`。
- 后端代码：`len(used_est_idx) / max(1, len(original_est.positions))`。
- 公式：

$$
Coverage_{vo,pct}=100\cdot\frac{N_{matched}}{N_{vo}}
$$

- 含义：VO 输出中有多少比例成功进入评估。100% 表示所有 VO 位姿都找到了可用 GT 并未被连续段策略丢弃。
- 偏低时怎么改：优先排查 VO 时间戳是否超出 GT 范围、时间戳单位是否错、是否需要 `time_offset_s`、GT 插值间隔是否过严、VO 是否有大量无效/重复时间戳。

### #12 断点数量

- 前端取值：`report.discontinuities?.all_matches?.break_count || 0`。
- 后端字段：`report["discontinuities"]["all_matches"]["break_count"]`。
- 后端代码：`detect_associated_discontinuities()`；只要相邻匹配点满足 `gt_step > step_threshold_m`、`est_step > step_threshold_m` 或 `time_gap > time_gap_threshold_s`，就在该处记一个 break。
- 公式：

$$
break_i =
(d_i^{gt}>T_{step})\lor(d_i^{vo}>T_{step})\lor(\Delta t_i>T_{gap})
$$

$$
BreakCount=\sum_i \mathbf{1}(break_i)
$$

- 含义：长航程连续性诊断。非零通常表示 VO reset、丢跟踪、输出中断、时间戳大 gap 或轨迹出现大跳变。
- 偏高时怎么改：先看 `breaks[*].reasons` 是 `gt_step/est_step/time_gap` 哪个触发。`est_step` 多就查 VO 重定位和异常跳点；`time_gap` 多就查输出频率和丢帧；GT 本身跳变则先清理或裁剪真值。

### #13 时间同步

- 前端取值：`report["association"]` 中的 `method/mode`、`matches` 和 `max_interpolation_gap_s` 等字段。
- 后端字段：`report["association"]`。
- 后端代码：`prepare_evaluation_trajectories()` 调 `build_associated_trajectories()`；默认 `interpolate_gt` 会把 GT 插值到 VO 时间戳；`nearest` 使用 TUM greedy timestamp association；`index` 按行号截断配对。
- 公式：

插值模式查询时刻：

$$
t_{query}=t_{vo}+offset
$$

GT 位置线性插值：

$$
\mathbf{p}^{gt}(t)=(1-\alpha)\mathbf{p}^{gt}_{left}+\alpha\mathbf{p}^{gt}_{right}
$$

最近邻模式匹配条件：

$$
|t_{gt}-(t_{vo}+offset)|<T_{max}
$$

- 含义：说明 GT 和 VO 是如何放到同一个时间轴上的。截图里的 `GT插值到VO` 表示评估点以 VO 时间戳为准，GT 被插值到这些时刻。
- 异常时怎么改：如果匹配率低、最大插值间隔大或误差曲线整体错位，检查时间戳单位 ns/us/ms/s、固定时间偏移 `time_offset_s`、`max_interpolation_gap_s`、是否需要允许外推，以及是否误选了 `nearest/index`。

### #14 姿态修正

- 前端取值：`orientationCorrectionLabel(report.orientation_correction || {})`；自动模式会显示 `auto -> selected`。
- 后端字段：`report["orientation_correction"]["selected"]`。
- 后端代码：`select_orientation_correction()`；`auto` 遍历常见候选，调用 `score_orientation_correction_candidate()`，选择 score 最小者；真正应用在 `apply_orientation_correction()`。
- 公式：

自动选择评分：

$$
Score=
RMSE_{orientation}
+0.25\cdot RMSE_{yaw}
+2\cdot RMSE_{RPE,rotation}
+RMSE_{RPE,translation}
$$

常见修正形式：

$$
\mathbf{R}'=\mathbf{M}\mathbf{R},\quad
\mathbf{R}'=\mathbf{R}\mathbf{M},\quad
\mathbf{R}'=\mathbf{M}\mathbf{R}\mathbf{M}^T,\quad
\mathbf{R}'=\mathbf{R}^T
$$

- 含义：用于修正 VO 姿态坐标约定，例如 ENU/NED、camera-to-body 外参、旋转矩阵方向相反、绕轴 180 度。它主要影响姿态误差、旋转 RPE 和带姿态的相对位移口径。
- 出现 `auto -> 非 none` 时怎么改：不要长期依赖评估自动猜测。应回到 VO 输出端固化坐标系和外参定义，明确世界系、机体系、相机系、四元数方向和旋转矩阵是 body-to-world 还是 world-to-body。

### #15 耗时

- 前端取值：`value: summary.duration_s`，备注 `有效评估窗口`。
- 后端字段：`report["summary"]["duration_s"]`。
- 后端代码：每个评估段 `total_duration_s += stamps[-1] - stamps[0]`。
- 公式：

单段：

$$
T_{seg}=t_{last}-t_{first}
$$

多段：

$$
T_{eval}=\sum_s T_{seg}
$$

- 含义：截图卡片里的“耗时”是有效评估时间窗口，不是算法计算耗时。它和 `长航程路程` 一起说明本次统计覆盖了多长时间、多远路程。
- 异常时怎么改：如果和实际飞行时长不一致，检查时间戳单位、时间同步、GT/VO 起止范围和连续段策略。真正的算法运行耗时在 `report["runtime"]`，只有 VO CSV 里包含 `process_time_ms/fps/cpu_percent/memory_mb` 等字段时才会统计。

## HTML 调参报告新增参数与代码/公式对应

本节对应导出的 `vo_evaluation_report.html`。首页 15 个指标里已经解释过的 `ATE RMSE`、`RPE RMSE`、`终点漂移`、`长航程路程`、`垂直 RMSE`、`发散状态`、`GT 覆盖率`、`Raw 尺度比`、`对齐尺度`、`匹配位姿`、`VO 匹配率`、`断点数量`、`时间同步`、`姿态修正`、`耗时` 不在这里重复展开。

### 1. 报告 Hero 基本信息

- 前端代码：`static_web/app.js` 的报告模板读取 `report.inputs`、`report.summary`、`report.config`、`alignmentSummaryLabel(report)` 和 `tuningRiskStatus(tuningRows)`。
- 新增字段：
  - `estimate`：`report.inputs.estimate.name`，本次评估的 VO 文件名。
  - `reference`：`report.inputs.ground_truth.name`，本次评估的 GT/reference 文件名；如果文件名像 `imu.txt`，报告会提示确认它是否是真值。
  - `profile`：`report.config.profile`，当前评估配置画像，例如 `monocular_long_range_uav`。
  - `alignment summary`：由 `report.alignment.mode/base_mode` 和分段信息生成，用来说明是全局对齐还是分段 Sim3。
  - `risk level`：由调参结论表的最高优先级生成。

风险等级规则：

```text
只要存在 P0 -> high
否则只要存在 P1 -> warning
否则 -> good
```

- 含义：Hero 区不是新误差公式，而是告诉读者“这份报告评的是哪个文件、用什么评估画像、整体风险等级是什么”。
- 异常时怎么改：`reference` 不可靠时先换真值源；`profile` 不符合当前任务时先改评估配置；`alignment summary` 显示分段 Sim3 时，不要把跨 reset 的结果解释成一条完全连续轨迹。

### 2. 调参结论摘要 P0/P1/P2

- 前端代码：`buildTuningConclusionRows(report)`。
- 输出列：`优先级 / 问题 / 证据 / 可能原因 / 建议动作 / 跳转`。
- 它不是单个传感器指标，而是基于多个字段的规则诊断。主要规则如下：

```text
break_count > 0 -> P0 VO 重置 / 大跳变
Sim3 scale range > 15% -> P0 单目尺度不稳定
Sim3 scale range > 8% -> P1 尺度稳定性需要关注
GT time coverage < 80% -> P0 评估覆盖不足
5000m p95 > 8% 或 1000m p95 > 5% -> P0 长距离累计漂移偏大
1000m mean > 2% 或 5000m mean > 4% -> P1 长距离漂移需要关注
auto 姿态修正选到非 none/ignore -> P1 姿态坐标系需要固化
divergence.diverged 为 true -> P1/P2 发散阈值被触发
Raw VO/GT 路程比 < 0.8 或 > 1.25 -> P2 原始尺度不一致
存在 dropped_est_outside_gt_range 或 dropped_est_large_gt_gap -> P1 部分 VO 帧未进入评估
reset_rate_per_km > 0.2 且 break_count > 0 -> P1 单位航程重置率偏高
```

- 含义：P0 是优先修复项，通常会影响报告可信度或长航程可用性；P1 是下一轮重点；P2 是解释性提示或后续优化项。
- 异常时怎么改：先按 P0 顺序处理，不要先调低优先级指标。例如同时有 `Reference 真值来源需要确认` 和 `VO 漂移偏大` 时，先确认真值，否则误差结论可能没有意义。

### 3. 连续性参数

这些参数在报告的“核心健康指标 Dashboard”和“完整指标”里出现，来源是 `detect_associated_discontinuities()` 和 `summarize_continuity()`。

#### 最大时间 gap

- 前端字段：`discontinuities.all_matches.breaks[].time_gap_s` 的最大值。
- 公式：

$$
MaxGap=\max_i(t_{i+1}-t_i)
$$

其中只统计被判定为断点的相邻匹配点。

- 含义：VO 是否长时间没有有效输出。报告里 `197.550 s` 这种值通常表示 VO 中断、reset 或数据时间轴有大空洞。
- 偏高时怎么改：检查 VO 输出频率、丢帧、重定位、日志分段、时间戳跳变；先回放 gap 前后图像和 VO 日志。

#### 最长连续段

- 后端字段：`discontinuities.continuity.longest_continuous_segment_m`、`longest_continuous_segment_s`、`longest_continuous_segment_pose_count`。
- 后端代码：对每个连续段计算 `distance_m = cumulative[end - 1] - cumulative[start]`，再按 `distance_m` 取最大。
- 公式：

$$
L_s=D_{end_s-1}-D_{start_s}
$$

$$
T_s=t_{end_s-1}-t_{start_s}
$$

$$
Longest=\max_s L_s
$$

- 含义：比断点数量更直观，表示 VO 单次不 reset 最远能连续飞多远。
- 偏低时怎么改：降低丢跟踪概率，增加重定位/地图复用，检查弱纹理、运动模糊和关键帧策略。

#### 重置率

- 后端字段：`discontinuities.continuity.reset_rate_per_km`、`reset_rate_per_hour`。
- 公式：

$$
ResetRate_{km}=\frac{BreakCount}{L_{gt}/1000}
$$

$$
ResetRate_{hour}=\frac{BreakCount}{T_{eval}/3600}
$$

- 含义：把断点数量归一化到单位距离/单位时间，便于不同航线长度之间比较连续性。
- 偏高时怎么改：优先修跟踪连续性，而不是只看 ATE；分开统计每次 reset 前后的尺度，确认 reset 后是否换了坐标系或尺度。

#### 连续段覆盖率

- 后端字段：`coverage_time_ratio`、`coverage_distance_ratio`。
- 公式：

$$
CoverageTime=\frac{\sum_s T_s}{t_N-t_0}
$$

$$
CoverageDistance=\frac{\sum_s L_s}{L_{gt}}
$$

- 含义：断点切分后的连续段合计覆盖了多少时间/路程。
- 偏低时怎么改：检查断点阈值是否过严、GT/VO 是否有异常跳点，以及 `continuous_segment_policy` 是否丢弃了大量片段。

### 4. 时间同步诊断细项

首页 #13 已解释“时间同步方式”，这里补充报告表里的细分参数。前端代码是 `buildAssociationDiagnosticRows(report)`，后端主要来自 `interpolate_reference_to_estimate()`。

#### 插值方法

- 字段：`association.position_method`、`association.rotation_method`。
- 代码口径：position 固定为 `linear`；reference 有姿态且启用时 rotation 使用 `slerp`，没有姿态时跳过。
- 位置插值公式：

$$
\mathbf{p}^{gt}(t)=(1-\alpha)\mathbf{p}^{gt}_{left}+\alpha\mathbf{p}^{gt}_{right}
$$

$$
\alpha=\frac{t-t_{left}}{t_{right}-t_{left}}
$$

- 含义：说明 GT/reference 是怎么补到 VO 时间戳上的。
- 异常时怎么改：GT 采样稀疏或存在大空洞时，不要盲目放宽插值；先确认 GT 是否连续可靠。

#### 是否允许外推

- 字段：`association.allow_extrapolation`。
- 规则：默认 `False`。VO 查询时刻早于 reference 首帧或晚于末帧时会被丢弃。
- 含义：外推会产生没有真值约束的“假 GT”，默认关闭更稳妥。
- 异常时怎么改：如果大量帧早于/晚于 reference 范围，先修起止时间和 `time_offset_s`，不要优先打开外推。

#### 插值目标时间轴

- 字段：`association.target`。
- 常见值：
  - `estimate_timestamps`：以 VO 时间戳为评估基准，把 GT 插值到 VO。
  - `nearest_timestamp_pairs`：只保留时间差足够小的离散配对。
- 含义：决定所有后续 ATE/RPE/segment 的评估时刻。
- 异常时怎么改：GT 高频、VO 低频或两者相位错开时优先用 `estimate_timestamps`；已经严格同步的数据可用 nearest/index 做复现对比。

#### 原始帧数、成功对齐帧数、丢弃帧数

- 字段：
  - `estimate_count_input` / `estimate_pose_count`：原始 VO 帧数。
  - `reference_count_input` / `reference_pose_count`：原始 reference 帧数。
  - `matched_count` / `matches`：成功进入评估的帧数。
  - `dropped_count` / `dropped`：未进入评估的 VO 帧数。
- 公式：

$$
Dropped=N_{vo}-N_{matched}
$$

$$
Coverage_{estimate}=\frac{N_{matched}}{N_{vo}}
$$

- 含义：判断报告是否覆盖了足够多的 VO 输出。
- 偏低时怎么改：检查时间戳单位、起止时间、固定 offset、GT 空洞、重复/无效时间戳。

#### 丢弃原因拆分

- 字段：
  - `dropped_before_reference_range`：VO 查询时刻早于 reference。
  - `dropped_after_reference_range`：VO 查询时刻晚于 reference。
  - `outside_gt_range_count` / `dropped_est_outside_gt_range`：超出 GT 范围总数。
  - `dropped_gt_gap_too_large` / `dropped_est_large_gt_gap`：GT 左右样本间隔超过阈值。
  - `dropped_invalid_timestamp`：无效时间戳。
- 判断：

$$
t_{query}=t_{vo}+time\_offset_s
$$

$$
Gap=t_{right}^{gt}-t_{left}^{gt}
$$

若 `Gap > max_interpolation_gap_s`，该 VO 帧不进入评估。

- 含义：解释 VO 帧为什么没进评估。
- 异常时怎么改：`before/after` 高说明时间范围或 offset 错；`GT 空洞过大` 高说明 reference 不连续或阈值过严；`invalid timestamp` 高说明输入解析或时间戳列有问题。

#### 实际使用插值间隔

- 字段：`max_used_gt_gap_s`、`mean_used_gt_gap_s`、`p95_used_gt_gap_s`。
- 公式：

$$
Gap_i=t_{right,i}^{gt}-t_{left,i}^{gt}
$$

$$
MaxGap_{used}=\max_i Gap_i
$$

$$
P95Gap_{used}=P_{95}(Gap_i)
$$

- 含义：成功插值样本实际跨了多大的 reference 时间间隔。`p95` 比 `max` 更能代表常态质量。
- 偏高时怎么改：提高 GT/reference 频率，清理 GT 空洞，或降低 `max_interpolation_gap_s` 避免跨缺口插值。

### 5. 长航程子轨迹表新增列

基础的按距离子轨迹平移误差、旋转误差和尺度漂移公式见下方“按距离子轨迹误差”和“尺度比与尺度漂移”。报告表里额外需要理解这些列：

- `长度 m`：`segment_errors[*].length_m`，目标子轨迹长度。
- `样本数`：该长度下有效子轨迹数量 `count`。
- `平移 mean/p95/max %`：`translation_error_percent.mean/p95/max`，用于判断对应距离的累计漂移。
- `yaw p95`：`segment_yaw_error_abs_deg.p95`，固定距离内航向变化误差的 95 分位。
- `vertical p95`：`vertical_error_abs_m.p95`，固定距离内高度误差绝对值的 95 分位。
- `scale p95`：`scale_drift_percent.p95`，固定距离内原始尺度漂移百分比的 95 分位。

诊断标签来自 `longRangeTag(row)`：

```text
translation p95 > 8% -> 平移漂移高
abs(scale p95) > 15% -> 尺度漂移高
yaw p95 > 8 deg -> 航向漂移高
vertical p95 > 30 m -> 高度漂移高
translation p95 > 3% -> 需要关注
否则 -> 正常
```

- 含义：短距离看局部跟踪稳定性，长距离看累计漂移；`p95` 更适合作为工程容差，因为它比 mean 更能暴露较差航段。
- 异常时怎么改：平移高看尺度/后端/闭环；yaw 高看航向约定、外参和 IMU/视觉姿态融合；vertical 高看 Z 轴、尺度和高度约束；scale 高看单目尺度源和重初始化。

### 6. Top-K 最差片段

- 后端字段：`report["worst_segments"]`。
- 后端代码：`build_worst_segments()` 从 `segment_records` 中按 `translation_error_percent` 降序排序，取 `top_k`。
- 排序公式：

```text
rank = sort_desc(translation_error_percent)
```

- 输出列：
  - `#`：最差片段排名。
  - `时间段`：`start_time_s -> end_time_s`。
  - `长度`：`length_m` 或 `actual_length_m`。
  - `平移误差`：`translation_error_percent`。
  - `米级误差`：`translation_error_m`。
  - `速度`：`speed_mps = actual_length_m / duration_s`。
  - `yaw`：`yaw_error_abs_deg`。
  - `vertical`：`vertical_error_abs_m`。
  - `近断点`：片段起止索引附近是否包含断点。

近断点判断：

```text
near_break = 任一 break_index 落在 [start_index - 10, end_index + 10]
```

建议动作规则：

```text
near_break 为 true -> 优先查丢跟踪、重定位、地图切换和 reset
yaw_error_abs_deg > 8 -> 查 yaw 约定、外参、ENU/NED 或姿态融合
vertical_error_abs_m > 30 -> 查 Z 轴、尺度、高度计约束和爬升下降
speed_mps > 16 -> 查高速段运动模糊、曝光、滚快门、特征跟踪和 RANSAC
否则 -> 回放该时间段图像和前后端日志
```

- 含义：Top-K 用来定位“最值得回放的时间段”，比只看平均指标更适合调参。
- 异常时怎么改：直接按 Top-K 时间段回放图像、特征数、光流/RANSAC 内点率、关键帧、重定位和局部地图日志。

### 7. 条件诊断

- 前端代码：`buildConditionDiagnosticRows(report)`。
- 目前报告包含四类条件：
  - `速度分箱`：来自 `report.speed_bins`。
  - `断点附近`：统计 `worst_segments.near_break`。
  - `转弯 / yaw-rate`：当前未接入。
  - `爬升 / 下降`：当前未接入。

速度分箱后端代码是 `summarize_by_speed_bins()`：

$$
v_{ij}=\frac{L_{ij}^{actual}}{t_j-t_i}
$$

然后按 `config.speed_bins_mps` 用左闭右开区间分箱，例如 `[8,12)`。

- 含义：判断 VO 是否只在某些运动条件下退化。高速差通常对应运动模糊、曝光、滚快门、特征跟踪跟不上；低速/悬停差通常对应视差不足、弱纹理、初始化或尺度退化。
- 异常时怎么改：按最差速度区间筛选 Top-K 或 `segment_records`，回放对应时间段；如果需要分析急转弯或爬升下降，需要在 `segment_records` 中新增 `yaw_rate_deg_s` 或 `climb_rate_mps` 分箱字段。

### 8. A/B 对比占位

- 前端代码：`comparisonPlaceholderHtml()`。
- 当前字段：`comparison`，显示“当前报告未包含 baseline”。
- 含义：这不是当前算法好坏指标，只说明报告还没有加载 baseline/current 两组结果做对比。
- 后续接入后建议比较：断点数量、scale variation、1000/5000m p95、Top-K 最差片段和 runtime。

### 9. 辅助论文指标中未重复的项

报告中的 `segment-wise Sim3 ATE RMSE` 与首页 `ATE RMSE` 重复，`Frame-to-frame RPE` 与首页 `RPE RMSE` 重复，`Endpoint drift` 与首页 `终点漂移` 重复，这里不再展开。

#### Global Sim3 ATE RMSE

- 前端字段：`ate.global_sim3_ate_position_m.rmse` 或 `ate.global.sim3.position_m.rmse`。
- 后端代码：`compute_global_ate(..., mode="sim3")`。
- 公式：仍是 ATE RMSE，但只对全程求一个 Sim3 对齐：

$$
\min_{s,\mathbf{R},\mathbf{t}}\sum_i\left\|s\mathbf{R}\mathbf{p}_i^{vo}+\mathbf{t}-\mathbf{p}_i^{gt}\right\|^2
$$

然后：

$$
ATE_{global\_sim3}=\sqrt{\frac{1}{N}\sum_i\left\|s\mathbf{R}\mathbf{p}_i^{vo}+\mathbf{t}-\mathbf{p}_i^{gt}\right\|^2}
$$

- 含义：全程只用一个 Sim3，比 segment-wise Sim3 更能暴露跨 reset、跨连续段的尺度和坐标系不一致。
- 偏高时怎么改：如果 segment-wise ATE 低但 global Sim3 ATE 高，说明每段形状尚可，但段与段之间不连续；优先查 reset、重定位、地图复用和分段尺度。

#### 固定时间 RPE：1s / 5s / 10s

- 前端字段：`rpe_time_delta.1s.translation_m.rmse`、`5s`、`10s`。
- 后端代码：`rpe_error_arrays_by_time()` 和 `summarize_time_rpe()`。
- 计算方式：对每个起点 `i`，寻找最接近 `stamps[i] + delta_s` 的终点 `j`，再调用和 RPE 相同的 `relative_error()`。

$$
j=\arg\min_{k>i}\left|t_k-(t_i+\Delta t)\right|
$$

$$
RPE_{\Delta t}=\sqrt{\frac{1}{M}\sum_k(e_k^{RPE,t})^2}
$$

- 含义：固定时间窗口的局部累计误差，比固定帧 RPE 更适合帧率不稳定或不同算法输出频率不同的对比。
- 偏高时怎么改：`1s` 高多半是短时跟踪/同步问题；`5s/10s` 高更像局部累计漂移、尺度或航向约束不足。

#### Attitude / yaw RMSE

- 前端字段：`ate_orientation_deg.rmse / ate_yaw_deg.rmse`。
- 后端代码：`rotation_errors()` 和 `yaw_from_rot()`。
- 姿态误差公式：

$$
\mathbf{R}_{err}=(\mathbf{R}^{gt})^T\hat{\mathbf{R}}^{vo}
$$

$$
e^{rot}=\arccos\left(\frac{trace(\mathbf{R}_{err})-1}{2}\right)\cdot\frac{180}{\pi}
$$

Yaw 误差：

$$
e^{yaw}=wrap(\hat{yaw}^{vo}-yaw^{gt})
$$

$$
Yaw_{RMSE}=\sqrt{\frac{1}{N}\sum_i(e_i^{yaw})^2}
$$

- 含义：`Attitude RMSE` 是完整三维姿态误差；`yaw RMSE` 单独看航向误差，更贴近无人机巡航方向控制。
- 偏高时怎么改：检查欧拉角顺序、角度/弧度、四元数顺序、旋转方向取逆、ENU/NED、camera-to-body 外参，以及是否长期依赖 `auto` 姿态修正。

## 指标计算方式

### 1. 误差随路程变化

该指标用于展示轨迹误差随飞行/行驶路程的变化情况。横轴为 Ground Truth 累计路程，纵轴为位置误差。

GT 累计路程：

```math
D_0=0
```

```math
D_i=\sum_{k=1}^{i}\left\|\mathbf{p}_k^{gt}-\mathbf{p}_{k-1}^{gt}\right\|_2
```

三维位置误差：

```math
e_i^{3D}=\left\|\hat{\mathbf{p}}_i^{vo}-\mathbf{p}_i^{gt}\right\|_2
```

水平误差：

```math
e_i^{horizontal}=
\sqrt{
(\hat{x}_i^{vo}-x_i^{gt})^2+
(\hat{y}_i^{vo}-y_i^{gt})^2
}
```

其中：

- $\mathbf{p}_i^{gt}$ 表示 Ground Truth 位置；
- $\hat{\mathbf{p}}_i^{vo}$ 表示对齐后的 VO 位置；
- $D_i$ 表示第 $i$ 个匹配位姿对应的累计路程；
- $e_i^{3D}$ 对应图中的 “3D error”；
- $e_i^{horizontal}$ 对应图中的 “horizontal”。

该图中每个点对应一个匹配位姿，展示该位置处 VO 轨迹相对于 Ground Truth 的误差。

---

### 2. 高度与垂直误差

该指标用于单独评估高度方向的误差。图中同时展示 Ground Truth 高度、VO 对齐后高度，以及二者之间的垂直误差。

Ground Truth 高度：

```math
z_i^{gt}
```

VO 对齐后高度：

```math
\hat{z}_i^{vo}
```

垂直误差：

```math
e_i^{vertical}=\hat{z}_i^{vo}-z_i^{gt}
```

垂直误差 RMSE：

```math
RMSE_{vertical}
=
\sqrt{
\frac{1}{N}
\sum_{i=1}^{N}
(e_i^{vertical})^2
}
```

其中：

- $z_i^{gt}$ 对应图中的 “GT altitude”；
- $\hat{z}_i^{vo}$ 对应图中的 “VO altitude”；
- $e_i^{vertical}$ 对应图中的 “vertical error”；
- $N$ 为成功匹配的位姿数量。

---

### 3. ATE 绝对轨迹误差

ATE 用于统计整条轨迹在对齐后的整体位置误差。

单点 ATE 误差：

```math
e_i^{ATE}
=
\left\|
\hat{\mathbf{p}}_i^{vo}
-
\mathbf{p}_i^{gt}
\right\|_2
```

ATE RMSE：

```math
ATE_{RMSE}
=
\sqrt{
\frac{1}{N}
\sum_{i=1}^{N}
(e_i^{ATE})^2
}
```

ATE mean：

```math
ATE_{mean}
=
\frac{1}{N}
\sum_{i=1}^{N}
e_i^{ATE}
```

ATE median：

```math
ATE_{median}
=
median(e_i^{ATE})
```

ATE p95：

```math
ATE_{p95}
=
P_{95}(e_i^{ATE})
```

ATE p99：

```math
ATE_{p99}
=
P_{99}(e_i^{ATE})
```

ATE max：

```math
ATE_{max}
=
\max(e_i^{ATE})
```

其中：

- $N$ 为成功匹配的位姿数量；
- $\hat{\mathbf{p}}_i^{vo}$ 为对齐后的 VO 位置；
- $\mathbf{p}_i^{gt}$ 为 Ground Truth 位置；
- 页面中的 “ATE RMSE” 即为 $ATE_{RMSE}$。

---

### 4. RPE 相对位姿误差

RPE 用于评估固定帧间隔下的局部运动误差。设固定帧间隔为 $\Delta$，则：

```math
j=i+\Delta
```

无姿态时，RPE 平移误差计算为：

```math
e_{ij}^{RPE,t}
=
\left\|
(\hat{\mathbf{p}}_j^{vo}-\hat{\mathbf{p}}_i^{vo})
-
(\mathbf{p}_j^{gt}-\mathbf{p}_i^{gt})
\right\|_2
```

有姿态时，先计算相对位移：

```math
\mathbf{t}_{ij}^{gt}
=
(\mathbf{R}_i^{gt})^T
(\mathbf{p}_j^{gt}-\mathbf{p}_i^{gt})
```

```math
\mathbf{t}_{ij}^{vo}
=
(\hat{\mathbf{R}}_i^{vo})^T
(\hat{\mathbf{p}}_j^{vo}-\hat{\mathbf{p}}_i^{vo})
```

RPE 平移误差为：

```math
e_{ij}^{RPE,t}
=
\left\|
\mathbf{t}_{ij}^{vo}
-
\mathbf{t}_{ij}^{gt}
\right\|_2
```

RPE RMSE：

```math
RPE_{RMSE}
=
\sqrt{
\frac{1}{M}
\sum_{k=1}^{M}
(e_k^{RPE,t})^2
}
```

如果输入包含姿态，还可以计算 RPE 旋转误差：

```math
\mathbf{R}_{ij}^{gt}
=
(\mathbf{R}_i^{gt})^T
\mathbf{R}_j^{gt}
```

```math
\mathbf{R}_{ij}^{vo}
=
(\hat{\mathbf{R}}_i^{vo})^T
\hat{\mathbf{R}}_j^{vo}
```

```math
\mathbf{R}_{ij}^{err}
=
(\mathbf{R}_{ij}^{gt})^T
\mathbf{R}_{ij}^{vo}
```

```math
e_{ij}^{RPE,r}
=
\arccos
\left(
\frac{trace(\mathbf{R}_{ij}^{err})-1}{2}
\right)
\cdot
\frac{180}{\pi}
```

其中：

- $\Delta$ 为固定帧间隔；
- $M$ 为可计算 RPE 的相对位姿数量；
- 页面中的 “RPE RMSE” 即为 $RPE_{RMSE}$。

---

### 5. 按距离子轨迹误差

该指标用于评估不同长度子轨迹上的漂移情况。横轴为目标子轨迹长度，纵轴为平移误差百分比和旋转误差。

设目标子轨迹长度为：

```math
L
```

例如：

```math
L\in \{50,100,200,500,1000,2000,5000\}\ m
```

对每个起点 $i$，寻找终点 $j$，使得：

```math
D_j-D_i\approx L
```

实际子轨迹长度为：

```math
L_{ij}^{actual}=D_j-D_i
```

长度容差判断：

```math
\left|
L_{ij}^{actual}-L
\right|
\leq
\alpha L
```

子轨迹平移误差：

```math
e_{ij}^{seg,t}
=
\left\|
(\hat{\mathbf{p}}_j^{vo}-\hat{\mathbf{p}}_i^{vo})
-
(\mathbf{p}_j^{gt}-\mathbf{p}_i^{gt})
\right\|_2
```

平移误差百分比：

```math
E_{ij}^{seg,t,pct}
=
100
\cdot
\frac{
e_{ij}^{seg,t}
}{L}
```

如果输入包含姿态，子轨迹旋转误差为：

```math
e_{ij}^{seg,r,deg}
```

单位距离旋转误差为：

```math
E_{ij}^{seg,r}
=
\frac{
e_{ij}^{seg,r,deg}
}{L}
```

单位为：

```math
deg/m
```

每个目标长度下，对所有有效子轨迹统计 mean 和 p95：

```math
Mean_L
=
\frac{1}{M}
\sum_{m=1}^{M}
E_m
```

```math
P95_L
=
P_{95}(E_m)
```

其中：

- $L$ 为目标子轨迹长度；
- $M$ 为该长度下有效子轨迹数量；
- 图中的 “translation mean %” 为 $Mean_L$；
- 图中的 “translation p95 %” 为 $P95_L$；
- 图中的 “rotation deg/m” 为单位距离旋转误差。

---

### 6. 速度分箱误差

该指标用于评估不同运动速度下的轨迹误差表现。系统先根据子轨迹计算平均速度，再按速度区间统计误差。

子轨迹平均速度：

```math
v_{ij}
=
\frac{L}{t_j-t_i}
```

速度分箱示例：

```math
[0,5),[5,10),[10,15),[15,20),[20,30),[30,\infty)
```

每个子轨迹的平移误差百分比为：

```math
E_{ij}^{seg,t,pct}
=
100
\cdot
\frac{
e_{ij}^{seg,t}
}{L}
```

每个速度箱内的 mean：

```math
Mean_{bin}
=
\frac{1}{M}
\sum_{m=1}^{M}
E_m^{seg,t,pct}
```

每个速度箱内的 p95：

```math
P95_{bin}
=
P_{95}
(
E_m^{seg,t,pct}
)
```

其中：

- $v_{ij}$ 为子轨迹平均速度；
- $L$ 为目标子轨迹长度；
- $t_j-t_i$ 为该子轨迹持续时间；
- $M$ 为当前速度箱内有效子轨迹数量；
- 图中的 “mean %” 为该速度箱内平移误差百分比均值；
- 图中的 “p95 %” 为该速度箱内平移误差百分比 95 分位数。

---

### 7. 终点漂移

终点漂移表示最后一个匹配位姿处，VO 轨迹相对于 Ground Truth 的最终位置偏差。

终点漂移：

```math
E_{end}
=
\left\|
\hat{\mathbf{p}}_N^{vo}
-
\mathbf{p}_N^{gt}
\right\|_2
```

终点漂移占总路程比例：

```math
E_{end,pct}
=
100
\cdot
\frac{
E_{end}
}{L_{gt}}
```

其中：

- $N$ 为最后一个匹配位姿；
- $L_{gt}$ 为 Ground Truth 总路程；
- 页面中的 “终点漂移” 即为 $E_{end}$。

---

### 8. 尺度比与尺度漂移

尺度指标用于判断 VO 轨迹长度与 Ground Truth 轨迹长度之间的比例关系。

VO 原始路程：

```math
L_{vo}^{raw}
=
\sum_{i=1}^{N-1}
\left\|
\mathbf{p}_{i+1}^{vo}
-
\mathbf{p}_{i}^{vo}
\right\|_2
```

Ground Truth 路程：

```math
L_{gt}
=
\sum_{i=1}^{N-1}
\left\|
\mathbf{p}_{i+1}^{gt}
-
\mathbf{p}_{i}^{gt}
\right\|_2
```

Raw 尺度比：

```math
ScaleRatio_{raw}
=
\frac{
L_{vo}^{raw}
}{
L_{gt}
}
```

子轨迹尺度比：

```math
ScaleRatio_{ij}
=
\frac{
\sum_{k=i+1}^{j}
\left\|
\hat{\mathbf{p}}_k^{vo}
-
\hat{\mathbf{p}}_{k-1}^{vo}
\right\|_2
}{
D_j-D_i
}
```

子轨迹尺度漂移百分比：

```math
ScaleDrift_{ij,pct}
=
(ScaleRatio_{ij}-1)
\times
100
```

其中：

- 页面中的 “Raw 尺度比” 即为 $ScaleRatio_{raw}$；
- 页面中的 “对齐尺度” 为轨迹对齐时求得的尺度因子 $s$；
- $ScaleRatio_{ij}$ 用于表示某一子轨迹段内 VO 路程和 GT 路程的比例关系。

---

### 9. 覆盖率与匹配率

覆盖率用于表示 Ground Truth 和 VO 轨迹中有多少位姿成功参与评估。

GT 覆盖率：

```math
Coverage_{gt}
=
\frac{
N_{matched}
}{
N_{gt}
}
```

VO 匹配率：

```math
Coverage_{vo}
=
\frac{
N_{matched}
}{
N_{vo}
}
```

百分比形式：

```math
Coverage_{gt,pct}
=
100
\cdot
\frac{
N_{matched}
}{
N_{gt}
}
```

```math
Coverage_{vo,pct}
=
100
\cdot
\frac{
N_{matched}
}{
N_{vo}
}
```

其中：

- $N_{matched}$ 为成功匹配的位姿数量；
- $N_{gt}$ 为 Ground Truth 总位姿数量；
- $N_{vo}$ 为 VO 输出总位姿数量；
- 页面中的 “GT 覆盖率” 对应 $Coverage_{gt,pct}$；
- 页面中的 “VO匹配率” 对应 $Coverage_{vo,pct}$；
- 页面中的 “匹配位姿” 对应 $N_{matched}$。

---

### 10. 发散检测

发散检测用于判断轨迹误差是否超过设定阈值。

动态发散阈值：

```math
T_i
=
\max
\left(
T_{abs},
D_i
\cdot
\frac{
T_{rel}
}{100}
\right)
```

发散判断：

```math
diverged
=
\exists i,
\quad
e_i^{ATE}
>
T_i
```

首次发散点：

```math
k
=
\min
\{
i
\mid
e_i^{ATE}
>
T_i
\}
```

首次发散距离：

```math
D_{div}=D_k
```

首次发散误差：

```math
E_{div}=e_k^{ATE}
```

其中：

- $T_{abs}$ 为绝对误差阈值；
- $T_{rel}$ 为相对路程阈值，单位为 %；
- $D_i$ 为当前累计路程；
- 页面中的 “是否发散” 根据上述条件判断。

---

### 11. Runtime / 耗时统计

如果输入文件或运行日志中包含耗时、CPU、内存、FPS 等字段，系统会对这些字段进行统计。

支持的字段包括：

| 字段 | 含义 |
| --- | --- |
| process_time_ms | 处理耗时，单位 ms |
| processing_time_ms | 处理耗时，单位 ms |
| frame_time_ms | 单帧耗时，单位 ms |
| latency_ms | 延迟，单位 ms |
| cpu_percent | CPU 占用百分比 |
| memory_percent | 内存占用百分比 |
| memory_mb | 内存占用，单位 MB |
| fps | 每秒处理帧数 |

对任意字段数组 $x_i$，计算：

RMSE：

```math
RMSE
=
\sqrt{
\frac{1}{N}
\sum_{i=1}^{N}
x_i^2
}
```

mean：

```math
Mean
=
\frac{1}{N}
\sum_{i=1}^{N}
x_i
```

median：

```math
Median
=
median(x_i)
```

std：

```math
Std
=
\sqrt{
\frac{1}{N}
\sum_{i=1}^{N}
(x_i-Mean)^2
}
```

p95：

```math
P95=P_{95}(x_i)
```

p99：

```math
P99=P_{99}(x_i)
```

其中：

- 页面中的 “耗时” 对应算法运行或评估过程统计得到的时间；

详细指标说明见 [metrics_catalog.md](metrics_catalog.md)。
