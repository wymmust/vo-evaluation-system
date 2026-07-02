# refactor-supported-formats 版本说明

本文档解释当前主版本的设计目标、输入约定、评估流程、可视化、导出内容和部署注意事项。该版本面向物流无人机轨迹评估，把旧版“自动猜格式、混合 VO/VLOC 入口、过多可调项”的流程收敛为两条固定评估路径。

## 版本目标

- VLOC 和 VO 分开评估：左侧入口选择 `VLOC 评估` 或 `VO 评估`，页面只显示当前模式需要的参数、指标和图表。
- 输入从单文件上传改为目录读取：浏览器选择 `data_dir` 和 `log_dir` 两个目录，系统按固定文件名读取数据。
- 文件格式固定：不再依赖旧版自动表头识别，减少字段猜错导致的坐标、姿态和时间戳错误。
- VLOC 直接做 nav-vloc 对比：VLOC 有真实尺度，不做 Sim3 尺度对齐，不导出 Sim3 中间表。
- VO 仍保留 Sim3/尺度分析：VO 可以无尺度或尺度不稳定，因此保留按连续段的 Sim3 对齐、RPE 和局部尺度图。
- 静态网页离线化：Plotly、Pyodide、numpy、pandas 及依赖固定在 `static_web/vendor/`，页面运行时不再访问第三方 CDN。

## 目录和文件约定

评估时需要选择两个目录：

- `data_dir`：固定读取 `imu.txt`，作为 ground truth / nav 参考。
- `log_dir`：VLOC 模式读取 `vloc.txt`、`home_point.txt`、`calib_raw.yaml`；VO 模式读取 `vo.txt`、`calib_raw.yaml`。

浏览器不会暴露本地绝对路径，页面只显示目录名和文件数量。目录名不强制必须叫 `data_dir` / `log_dir`，但目录内部的文件名必须符合上述约定。

## 固定输入格式

### Ground truth / IMU

`imu.txt` 使用 SF nav 格式，核心字段包括：

```text
#ts1 ts2 status flight_mode x y z yaw pitch roll vx vy vz reset_count1 reset_count2 reset_count3 lati longi alti alti_msl height
```

系统固定读取时间戳、NED 位置、yaw/pitch/roll、速度、飞行状态和 reset 计数等字段。

### VLOC

`vloc.txt` 使用 VLOC 固定格式：

```text
ts status num_inliers reset_count tx ty tz yaw pitch roll latitude longitude altitude
```

VLOC 轨迹有真实尺度，评估时不做 Sim3 尺度对齐。姿态和位置按固定字段解析。

### VO

`vo.txt` 使用 VO 固定格式，包含历史兼容列：

```text
# ts num_inliers tx ty tz yaw pitch roll(degree) is_keyframe frame_cost reset_count depth_mean depth_min depth_max
```

VO 模式会使用时间戳、位置、姿态和 `reset_count`。其余字段允许存在，但不作为核心评估指标。

## 时间同步

VLOC 和 VO 都固定采用“GT 插值到估计轨迹时间戳”的方式：

1. 以 `vloc.txt` 或 `vo.txt` 的时间戳作为评估时间轴。
2. 在 `imu.txt` 中查找相邻 GT 点。
3. 位置使用线性插值。
4. 姿态使用 SLERP 插值。
5. 最大 GT 插值间隔固定为 `1.0 s`；如果某个估计帧落在超过 1 秒的 GT 间隔中，该帧直接丢弃。
6. 不允许外推，时间偏移固定为 `0`。

这样可以处理 GT 和估计轨迹同频但相位不同的情况，例如 GT 是 `0.1/0.3/0.5`，估计输出是 `0.2/0.4/0.6`。

## VLOC 评估流程

VLOC 模式对应 nav-vloc 对比：

1. 读取 `imu.txt` 得到 nav 参考轨迹。
2. 读取 `vloc.txt` 得到 VLOC 估计轨迹。
3. 将 nav 插值到 VLOC 时间戳。
4. 按 `reset_count` 和时间间隔诊断断点，但普通时间曲线保持连续显示。
5. 直接计算位置误差：`nav_data.ned - vloc_data.ned`。
6. 姿态误差用旋转矩阵计算：

   ```text
   R_error = inverse(R_wb_ref) * R_wb_est
   ```

   再转回欧拉角，方便页面按 yaw/pitch/roll 可视化。
7. 汇总轨迹长度、水平位置误差、垂直位置误差和欧拉角三维误差范数。

VLOC 指标卡包含：

- `ATE RMSE`：整体三维位置误差 RMSE。
- `长航程路程`：参考 nav 轨迹累计长度。
- `垂直 RMSE`：D / 高度方向误差 RMSE。
- `GT 覆盖率`：被评估的 GT 时间范围占原始 GT 的比例。
- `匹配位姿`：最终进入评估的 VLOC 时间戳数量。
- `VLOC 匹配率`：VLOC 输出中进入评估的比例。
- `断点数量`：VLOC reset 或大时间间隔诊断数量。
- `mean_error_pos_xy` / `max_error_pos_xy`：逐帧水平位置误差范数的平均值和最大值。
- `mean_error_pos_z` / `max_error_pos_z`：逐帧垂直位置误差绝对值的平均值和最大值。
- `mean_error_euler` / `max_error_euler`：逐帧欧拉角误差三维范数的平均值和最大值。
- `耗时`：有效评估窗口长度。

## VO 评估流程

VO 模式面向尺度可能未知或漂移的视觉里程计：

1. 读取 `imu.txt` 得到 GT。
2. 读取 `vo.txt` 得到 VO 输出。
3. 将 GT 插值到 VO 时间戳。
4. 按 `reset_count` 拆分连续段。
5. 每个连续段做 Sim3 对齐，得到旋转、平移和尺度。
6. 计算 ATE、RPE、局部尺度和逐帧误差。
7. 3D 轨迹图只在断点处标注 VO 段的起点和终点，避免起终点重叠导致看不清。

VO 左侧只保留两个必要参数：

- `RPE 统计间隔`：可选帧数 `f` 或距离 `m`。
- `尺度图间隔`：可选帧数 `f` 或距离 `m`。

当选择距离 `m` 时，系统使用目标距离的 `±5%` 范围寻找候选终点，并取误差最小的候选纳入统计。

## 图表目录

VLOC 和 VO 都支持左侧“图表目录”：

- 评估完成后默认全选。
- 用户可以按图表模块选择右侧展示内容。
- 支持一键全选和清除。
- 3D 轨迹不支持选点；其他图表支持选点。

图表布局从两列改为单列，图像宽度更大，适合查看长航程曲线。

## 联动图和选点

NED、YPR、误差曲线和速度/状态类大图采用多子图拼接：

- 一个大图中包含多个垂直排列的小图。
- 鼠标悬停时使用一条贯穿所有子图的同步虚线。
- 悬停信息显示在鼠标附近，包含该时间戳下所有子图对应曲线的值。
- 用户点击选点后，选中点会以不同颜色标注，并写入左侧“输出对比”。
- 同一张图的选点记录集中在一个表格中，包含曲线名、点标记、时间戳和值。
- 右上角橡皮按钮清除当前图表的选点。
- 左侧“清除所有点”清除全部图表选点。
- 鼠标靠近选中点时按 `Delete` 可以删除单个点。

选点颜色使用一组高区分度颜色循环；超过预设颜色数量后，会在点标记中加入编号区分。

## VLOC 图表

VLOC 页面保留需求文档要求的图表：

- 3D 轨迹。
- 俯视 NE 轨迹。
- 误差随路程变化。
- 对地高随时间变化。
- 导航状态信息。
- 导航速度信息。
- 导航 reset 计数。
- VLOC 状态信息。
- NED 随时间变化。
- YPR 随时间变化。
- NED 误差随时间变化。
- YPR 误差随时间变化。

VLOC 不显示尺度图，也不导出 Sim3 对齐工作簿。

## VO 图表

VO 页面只保留需求文档中需要的图表和 VO 必要诊断：

- 3D 轨迹。
- 俯视 NE 轨迹。
- 误差随路程变化。
- VO 状态信息。
- NED 随时间变化。
- YPR 随时间变化。
- NED 误差随时间变化。
- YPR 误差随时间变化。
- RPE 平移误差随时间变化。
- RPE 旋转误差随时间变化。
- 局部 Sim3 尺度随时间变化。

VO 的局部尺度图与左侧“尺度图间隔”参数对应，用于观察不同帧数或距离窗口下的尺度稳定性。

## 导出内容

页面支持导出：

- JSON 指标。
- 每帧误差 CSV。
- 子轨迹误差 CSV。
- 最差片段 CSV。
- 配置 JSON。
- 轨迹 Excel。
- HTML 报告。

导出文件名包含：

- 选取目录名称。
- 评估类型：`vloc` 或 `vo`。
- 导出内容类型。

VLOC Excel 不包含 Sim3 工作簿；VO Excel 保留 Sim3 相关中间表。导出的 HTML 报告保留页面上的核心图表和选点交互，不再引用外部 CDN。

## 安全与隐私

- 上传数据只在当前浏览器内处理，不会发送到后端服务器。
- 静态网页版本通过 Pyodide 在浏览器中运行 Python 评估逻辑。
- `static_web/vendor/` 固定包含 Plotly、Pyodide、numpy、pandas 及必要依赖，运行时不再从第三方 CDN 拉取脚本。
- `_headers` 中的 CSP 已移除第三方 CDN 白名单，脚本和数据连接限制在同源资源。
- 仓库不应提交真实飞行日志、测试数据或导出报告。

## 部署方式

静态网页部署时上传完整 `static_web/` 目录：

```text
static_web/
  index.html
  app.js
  style.css
  worker.js
  py/
  vendor/
```

本地预览：

```bash
cd static_web
python3 -m http.server 8765
```

然后打开：

```text
http://localhost:8765/
```

如果要使用页面左侧的 `data_dir` / `log_dir` 本地路径输入框，请从仓库根目录启动本地路径服务：

```bash
python3 static_web/local_server.py --host 127.0.0.1 --port 8766
```

然后打开：

```text
http://127.0.0.1:8766/
```

该模式由本机 Python 读取固定文件契约：`data_dir/imu.txt`；VO 的 `log_dir/vo.txt`、`log_dir/calib_raw.yaml`；VLOC 的 `log_dir/vloc.txt`、`log_dir/home_point.txt`、`log_dir/calib_raw.yaml`。

不要直接双击 `index.html`，否则浏览器可能阻止本地资源读取。

## 验证命令

推荐在提交前运行：

```bash
node --check static_web/app.js
python -m pytest -q
```

静态资源访问验证：

```bash
cd static_web
python3 -m http.server 8765
```

确认页面、`vendor/plotly/plotly-2.35.2.min.js` 和 `vendor/pyodide/v0.26.4/full/pyodide-lock.json` 都能通过 HTTP 访问。

## 与旧版的主要区别

- 不再把所有格式混在一个入口中自动猜测。
- 不再在 VLOC 中做 Sim3 尺度对齐。
- 不再显示需求外的大量调参项和图表。
- 不再依赖公网 CDN 加载运行时代码。
- 导出内容按 VLOC/VO 模式分开，避免把无关中间表塞进报告。
- 页面图表支持目录化展示和点选对比，更适合从长航程曲线中定位异常点。
