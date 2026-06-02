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

- 时间关联使用 TUM RGB-D `associate.py` 的贪心匹配思想：先生成时间差小于阈值的候选，再按时间差从小到大做一对一匹配。
- ATE 使用 TUM RGB-D `evaluate_ate.py` 的 Horn/SVD 刚体对齐口径；单目尺度未知时可切换到 rpg/evo 常用的 Sim3 对齐。
- RPE 固定帧间隔使用 TUM `evaluate_rpe.py --fixed_delta --delta_unit f` 对应口径。
- 子轨迹误差使用 KITTI 的固定目标长度分母，默认每 10 帧取一个起点；同时加入 rpg 的长度容差思想，避免稀疏轨迹中把相差过大的段纳入统计。

## 对齐方式

- `SE3`：尺度已知时推荐，例如双目 VO、RGB-D、VIO。
- `Sim3`：单目 VO 或尺度未知时使用。
- `首帧对齐`：适合看误差如何随长航程累积。
- `不对齐`：当两条轨迹已在同一坐标系下使用。

## IMU 长时间记录与 VO 时间段

如果 ground truth 像 IMU 日志一样从开机开始持续记录，而 VO 只在算法运行期间输出，系统会以 VO 时间戳为基准匹配最近的 IMU 位姿。默认策略是“按 VO 时间戳统一评估”：VO 有 2400 个时间戳，就只取对应的 2400 个 IMU 位姿，其他 IMU 记录不进入统计。断点检测只作为诊断提示，不会默认丢弃匹配点。

## 数据文件

仓库不包含测试数据、飞行日志、导出报告或轨迹样例。请在本地页面中上传自己的 ground truth 与 VO 输出文件运行评估。

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
