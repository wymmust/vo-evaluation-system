# VO Evaluation System

面向 SF 物流无人机数据的 VO/VLOC 轨迹评估系统。当前主版本只保留固定格式流程：VLOC 评估、VO 评估和 TUM 调试格式，不再维护旧版自适应表头、可选对齐方式、发散检测、速度分箱、Top-K 子轨迹和 runtime 自动统计。

## 本地网页

## 安装

Python 3.8.10 也可以使用，但建议在虚拟环境里安装，避免 Ubuntu/Debian 的系统 Python 限制以及旧 pip 的 editable install 问题：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -e . --no-build-isolation
```

安装后可直接使用：

```bash
voeval --help
```

如果使用 Python 3.11+，同样建议使用上述虚拟环境方式。

从仓库根目录启动本地评估服务器：

```bash
python -m voeval server
```

运行后会自动打开浏览器进入本地可视化页面。默认地址是 `http://127.0.0.1:8766/`；如果端口被占用，可以加 `--port 8767`。

页面支持两种输入：

- 目录选择：浏览器读取必要文件内容后提交给后端。
- 本地路径：填写 `data_dir` / `log_dir`，由 `voeval/server.py` 在本机读取文件。

## CLI

VO：

```bash
python -m voeval eval --mode sf_vo --data_dir "/path/to/data_dir" --log_dir "/path/to/log_dir" -d 100 -u m
```

VLOC：

```bash
python -m voeval eval --mode sf_vloc --data_dir "/path/to/data_dir" --log_dir "/path/to/log_dir" -d 100 -u m
```

参数：

- `-d / --delta`：RPE 统计间隔，默认 `100`。
- `-u / --unit`：`m` 表示米，`f` 表示帧，默认 `m`。
- `-o / --output`：保存 JSON 报告。
- `-p`：生成临时 HTML 并打开浏览器预览，不保存到当前目录。
- `-s / --save-html`：保存 HTML 报告。
- `--html-output`：配合 `-s` 指定 HTML 保存路径。

示例：

```bash
python -m voeval eval --mode sf_vo \
  --data_dir "/Volumes/Extreme SSD/Baseline/01_Normal/03_综合/5066/1509" \
  --log_dir "/Volumes/Extreme SSD/Baseline/01_Normal/03_综合/5066/1509" \
  -d 100 -u m -p
```

## 固定输入格式

### VLOC 评估

读取文件：

- `data_dir/imu.txt`
- `log_dir/vloc.txt`
- `log_dir/home_point.txt`
- `log_dir/calib_raw.yaml`

`vloc.txt` 固定格式：

```text
ts status num_inliers reset_count tx ty tz yaw pitch roll latitude longitude altitude
```

VLOC 固定不做 Sim3，对比方式为 `nav_data.ned - vloc_data.ned`。

### VO 评估

读取文件：

- `data_dir/imu.txt`
- `log_dir/vo.txt`
- `log_dir/calib_raw.yaml`

`vo.txt` 主线固定格式：

```text
ts num_inliers tx ty tz yaw pitch roll is_keyframe frame_cost reset_count
```

兼容旧 14 列格式，最后三列深度字段会被读取端忽略：

```text
ts num_inliers tx ty tz yaw pitch roll is_keyframe frame_cost reset_count depth_mean depth_min depth_max
```

VO 固定使用 Sim3 对齐。

### IMU / Ground Truth

`imu.txt` 固定格式：

```text
ts1 ts2 status flight_mode x y z yaw pitch roll vx vy vz reset_count1 reset_count2 reset_count3 lati longi alti alti_msl height
```

时间戳单位固定为秒。固定格式不再做自适应表头识别。

### TUM 调试格式

```text
timestamp tx ty tz qx qy qz qw
```

TUM 主要用于测试、调试和与 evo 对齐口径，不是页面主输入流程。

## 固定评估流程

1. 读取固定格式文件并校验整数列、四元数、矩阵和必需文件。
2. 以 VO/VLOC 时间戳为基准，把 GT 插值到估计轨迹时间戳。
3. GT 插值最大间隔固定为 `1.0 s`，超过则丢弃该估计帧，不允许外推。
4. VO 按 `reset_count` 切连续段后分别 Sim3；VLOC 不对齐。
5. 计算 ATE、RPE、断点诊断、覆盖率、轨迹导出表和可视化明细。
6. 生成网页图表、JSON、Excel 或 HTML 报告。

## 指标与代码对应

| 指标 / 报告项 | report 字段 | 主要代码 |
| --- | --- | --- |
| 固定格式读取 | `inputs`、`trajectory_exports` | `voeval/io/formats.py`、`voeval/io/parsers.py`、`voeval/io/bundle.py` |
| 时间同步 / GT 插值 | `association` | `voeval/core/interpolation.py` |
| VO Sim3 对齐 | `alignment` | `voeval/core/alignment.py` |
| ATE 位置误差 | `ate_position_m`、`ate_horizontal_m`、`ate_vertical_m` | `voeval/core/pipeline.py`、`voeval/core/statistics.py` |
| ATE 姿态 / yaw 误差 | `ate_orientation_deg`、`ate_yaw_deg` | `voeval/core/errors.py`、`voeval/core/geometry.py` |
| RPE 帧数/距离间隔误差 | `rpe_frame_delta`、`rpe_per_frame` | `voeval/core/statistics.py`、`voeval/core/errors.py` |
| VO 局部尺度图 | `scale_frame_delta`、`scale_per_frame` | `voeval/core/statistics.py` |
| 断点 / reset 段诊断 | `discontinuities` | `voeval/core/segments.py` |
| VLOC 明细 | `vloc_details` | `voeval/reports/detail.py` |
| VO 明细 | `vo_details` | `voeval/reports/detail.py` |
| Excel / JSON 导出 | `trajectory_exports`、完整 report | `voeval/reports/export.py` |
| HTML 导出 | 离线 HTML | `voeval/visualization/cli/export_report_cli.js` |

## 当前保留指标

通用：

- `ATE RMSE`
- `RPE RMSE`
- `长航程路程`
- `垂直 RMSE`
- `GT 覆盖率`
- `匹配位姿`
- `VO/VLOC 匹配率`
- `断点数量`
- `耗时`

VO 专用：

- `Raw 尺度比`
- `对齐尺度`
- `局部 Sim3 尺度随时间戳变化`

VLOC 专用：

- `mean_error_pos_xy`
- `mean_error_pos_z`
- `mean_error_euler`
- `max_error_pos_xy`
- `max_error_pos_z`
- `max_error_euler`
- 导航状态、导航速度、导航 reset、VLOC 状态、NED/YPR 对比和误差图

## 导出内容

- JSON：完整 report，非有限数会转为 `null`。
- Excel：轨迹输入、插值后 GT、筛选后估计轨迹、Sim3 后轨迹（仅 VO）、逐帧 ATE、逐帧 RPE、逐帧尺度（仅 VO）。
- HTML：复用网页可视化代码，保留图表目录、图表交互、虚线联动和选点对比。

## 开发验证

运行测试：

```bash
python -m pytest -q
```

运行 coverage：

```bash
python -m coverage run -m pytest tests/test_evaluator.py
python -m coverage report -m voeval/io/*.py voeval/core/*.py voeval/reports/*.py
python -m coverage html
```

本仓库不包含测试数据、飞行日志或导出报告。不要把真实日志和生成报告提交到 Git。
