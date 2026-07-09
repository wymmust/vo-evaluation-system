# VO Evaluation System

面向 SF 物流无人机数据的 VO/VLOC 轨迹评估系统。当前主版本只保留固定格式流程：VLOC 评估、VO 评估和 TUM 调试格式，不再维护旧版自适应表头、可选对齐方式、发散检测、速度分箱、Top-K 子轨迹和 runtime 自动统计。

## 本地网页

## 安装（可选）

不安装时，可从仓库根目录启动本地评估脚本。

```bash
python3 -m pip install -e . --no-build-isolation
```

安装后可直接使用`voeval`命令：

```bash
voeval --help
```

## web页面
从仓库根目录启动本地评估服务器：

```bash
python -m voeval server
```

运行后会自动打开浏览器进入本地可视化页面。默认地址是 `http://127.0.0.1:8766/`；如果端口被占用，可以加 `--port 8767`。


## CLI

VO：

```bash
python -m voeval sf_vo /path/to/data_dir /path/to/log_dir
```

VLOC：

```bash
python -m voeval sf_vloc /path/to/data_dir /path/to/log_dir
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
python -m voeval sf_vo /dataset/01_Normal/03_综合/5066/1509 /dataset/01_Normal/03_综合/5066/1509 -d 100 -u m -p
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
